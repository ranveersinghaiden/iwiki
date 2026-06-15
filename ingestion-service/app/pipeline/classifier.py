"""
Product hierarchy classifier.
Loads product_hierarchy.yaml at startup, then asks the LLM to assign
a (product, feature, component) tag to each document.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import yaml
from openai import AsyncOpenAI

from app.config import settings

logger = logging.getLogger(__name__)

_FALLBACK: dict[str, Any] = {"product": "General", "feature": "Uncategorized", "component": None}

_SYSTEM_PROMPT = (
    "You are a classification assistant. "
    "Return ONLY a valid JSON object — no markdown, no code fences, no explanation."
)


class HierarchyClassifier:
    def __init__(self) -> None:
        self._client = AsyncOpenAI(
            api_key=settings.openai_api_key,
            base_url=settings.ai_base_url,
        )
        self._model = settings.llm_model
        self._hierarchy = self._load_hierarchy()
        self._hierarchy_yaml = yaml.dump(self._hierarchy, default_flow_style=False)

    def _load_hierarchy(self) -> dict[str, Any]:
        path = Path(settings.hierarchy_config_path)
        if not path.exists():
            logger.warning("[HierarchyClassifier] hierarchy file not found at %s — using fallback", path)
            return {"products": [{"name": "General", "features": [{"name": "Uncategorized"}]}]}
        with path.open(encoding="utf-8") as f:
            return yaml.safe_load(f)

    async def classify(self, title: str, content_preview: str) -> dict[str, Any]:
        """Return {product, feature, component} for the given document."""
        prompt = (
            f"Product hierarchy (YAML):\n{self._hierarchy_yaml}\n\n"
            f"Document title: {title}\n"
            f"Content preview: {content_preview[:600]}\n\n"
            "Classify this document into the hierarchy above.\n"
            'Return JSON: {"product": "...", "feature": "...", "component": "..." or null}\n'
            "Use the closest match. If nothing fits, use General/Uncategorized/null."
        )
        try:
            response = await self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=100,
                temperature=0,
            )
            raw = response.choices[0].message.content or ""
            return json.loads(raw.strip())
        except (json.JSONDecodeError, Exception) as exc:
            logger.warning(
                "[HierarchyClassifier] classification failed for %r: %s — using fallback",
                title,
                exc,
            )
            return _FALLBACK

