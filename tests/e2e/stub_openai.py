"""
Stub OpenAI-compatible server for E2E testing.
Implements /v1/embeddings and /v1/chat/completions with no real AI.

Embeddings:
  Deterministic 768-dim unit vector derived from MD5 of input text.
  768 matches the shipped chunks.embedding vector/halfvec(768) schema
  (Ollama nomic-embed-text default). For OpenAI (1536) bump this + the column.
  Same text -> same vector (idempotent). FTS search drives relevance in tests.

Chat completions -- two modes detected from prompt content:
  1. Expert synthesis: prompt contains "synthesising expert knowledge" ->
     returns a valid JSON expert record (description, compressed_context,
     upstream_dependencies, downstream_affected).
  2. RAG answer: all other prompts -> returns a templated answer quoting
     the question, allowing assertions on non-empty answer + source list.
"""
from __future__ import annotations

import hashlib
import json
import math
import random
import re
from typing import Any

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

app = FastAPI(title="iWiki Stub OpenAI")


def _deterministic_embedding(text: str, dim: int = 768) -> list[float]:
    """Generate a deterministic unit vector from text using MD5 seed."""
    seed = int(hashlib.md5(text.encode("utf-8", errors="replace")).hexdigest(), 16) % (2**32)
    rng = random.Random(seed)
    vec = [rng.gauss(0.0, 1.0) for _ in range(dim)]
    magnitude = math.sqrt(sum(x * x for x in vec)) or 1.0
    return [x / magnitude for x in vec]


def _classification_response(user_msg: str) -> str:
    """Return a valid JSON product classification based on document title keywords."""
    title = ""
    for line in user_msg.splitlines():
        if line.startswith("Document title:"):
            title = line.split(":", 1)[1].strip().lower()
            break

    # keyword → product mapping mirrors product_hierarchy.yaml
    pay_kw = {"pay", "payment", "checkout", "invoice", "tax", "3ds2", "visa", "stripe", "refund"}
    track_kw = {"track", "gps", "fleet", "geofence", "location", "vehicle", "telematics"}
    plat_kw = {"plat", "auth", "jwt", "api key", "platform", "infrastructure", "token"}

    if any(k in title for k in pay_kw):
        return json.dumps({"product": "Payments", "feature": "Checkout", "component": None})
    if any(k in title for k in track_kw):
        return json.dumps({"product": "Tracking", "feature": "GPS", "component": None})
    if any(k in title for k in plat_kw):
        return json.dumps({"product": "Platform", "feature": "Authentication", "component": None})
    return json.dumps({"product": "General", "feature": "Uncategorized", "component": None})


def _expert_response(user_msg: str) -> str:
    """Return a deterministic valid JSON expert record for the detected product."""
    # Extract product name from the prompt line "product: "..."
    product = "Unknown"
    for line in user_msg.splitlines():
        if 'synthesising expert knowledge for the product:' in line:
            start = line.find('"') + 1
            end = line.rfind('"')
            if start < end:
                product = line[start:end]
            break

    expert: dict[str, Any] = {
        "description": (
            f"{product} is a core platform product responsible for its domain functionality. "
            "It provides APIs consumed by multiple downstream services."
        ),
        "compressed_context": (
            f"The {product} product manages end-to-end workflows in its domain. "
            "Key responsibilities include data ingestion, validation, and downstream event emission. "
            "It integrates with platform authentication via JWT tokens and communicates with the "
            "database layer through an async repository pattern. Known failure modes include "
            "upstream API rate limiting and database connection pool exhaustion under high load."
        ),
        "upstream_dependencies": [
            {"product": "Platform", "component": "Authentication", "reason": "JWT token verification for all API calls"},
        ],
        "downstream_affected": [
            {"product": "General", "component": None, "reason": "Downstream consumers depend on events emitted by this product"},
        ],
    }
    return json.dumps(expert)


def _rerank_response(user_msg: str) -> str:
    """Return a valid JSON index ordering for the reranker prompt.

    Echoes identity order (0..n-1) — enough to exercise the parse/apply path
    without perturbing order-independent E2E assertions.
    """
    match = re.search(r"indices \(0 to (\d+)\)", user_msg)
    if match:
        return json.dumps(list(range(int(match.group(1)) + 1)))
    return json.dumps([int(x) for x in re.findall(r"\[(\d+)\]", user_msg)])


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

    user_msg = next(
        (m.get("content", "") for m in reversed(messages) if m.get("role") == "user"), ""
    )

    # Detect expert synthesis requests — return structured JSON
    if "synthesising expert knowledge for the product:" in user_msg:
        content = _expert_response(user_msg)
    # Detect reranker requests — return a JSON index ordering
    elif "You are a precise search result reranker." in user_msg:
        content = _rerank_response(user_msg)
    # Detect classification requests — return product hierarchy JSON
    elif "Classify this document into the hierarchy" in user_msg:
        content = _classification_response(user_msg)
    else:
        # RAG answer mode — templated response referencing the question
        question_marker = "Question:"
        if question_marker in user_msg:
            question = user_msg[user_msg.index(question_marker) + len(question_marker):].strip()
        else:
            question = user_msg[:200]

        content = (
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
                    "message": {"role": "assistant", "content": content},
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

