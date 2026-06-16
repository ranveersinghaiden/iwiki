"""
Stub OpenAI-compatible server for E2E testing.
Implements /v1/embeddings and /v1/chat/completions with no real AI.

Embeddings: deterministic 1536-dim unit vector derived from MD5 of input text.
  - Same text → same vector (idempotent)
  - FTS search remains the primary driver of relevance in tests

Completions: echoes back a templated answer that includes the user query,
  so the E2E test can assert the answer is non-empty and cites sources.
"""
from __future__ import annotations

import hashlib
import math
import random
from typing import Any

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

app = FastAPI(title="iWiki Stub OpenAI")


def _deterministic_embedding(text: str, dim: int = 1536) -> list[float]:
    """Generate a deterministic unit vector from text using MD5 seed."""
    seed = int(hashlib.md5(text.encode("utf-8", errors="replace")).hexdigest(), 16) % (2**32)
    rng = random.Random(seed)
    vec = [rng.gauss(0.0, 1.0) for _ in range(dim)]
    magnitude = math.sqrt(sum(x * x for x in vec)) or 1.0
    return [x / magnitude for x in vec]


@app.post("/v1/embeddings")
async def embeddings(request: Request) -> JSONResponse:
    body: dict[str, Any] = await request.json()
    raw_input = body.get("input", [])
    inputs: list[str] = [raw_input] if isinstance(raw_input, str) else list(raw_input)
    data = [
        {
            "object": "embedding",
            "index": i,
            "embedding": _deterministic_embedding(text),
        }
        for i, text in enumerate(inputs)
    ]
    return JSONResponse(
        {
            "object": "list",
            "data": data,
            "model": body.get("model", "stub-embedding"),
            "usage": {"prompt_tokens": sum(len(t.split()) for t in inputs), "total_tokens": 0},
        }
    )


@app.post("/v1/chat/completions")
async def chat_completions(request: Request) -> JSONResponse:
    body: dict[str, Any] = await request.json()
    messages: list[dict] = body.get("messages", [])

    # Extract the user question from the last user message
    user_msg = next(
        (m.get("content", "") for m in reversed(messages) if m.get("role") == "user"), ""
    )
    question_marker = "Question:"
    if question_marker in user_msg:
        question = user_msg[user_msg.index(question_marker) + len(question_marker):].strip()
    else:
        question = user_msg[:200]

    answer = (
        f"Based on the indexed knowledge base, here is what was found regarding: '{question[:120]}'. "
        "The relevant documents in the context provide detailed information on this topic. "
        "Please review the Sources section below for the original references.\n\n"
        "Sources:\n[1] See source documents listed in the API response."
    )

    return JSONResponse(
        {
            "id": "chatcmpl-stub-001",
            "object": "chat.completion",
            "model": body.get("model", "stub-llm"),
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": answer},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 100, "completion_tokens": 80, "total_tokens": 180},
        }
    )


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "stub-openai"}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=11435, log_level="warning")

