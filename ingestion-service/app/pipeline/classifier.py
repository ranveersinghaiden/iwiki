"""
Product hierarchy classifier — hybrid, taxonomy-aware.

Cheapest-first cascade per document:
  1. Rule      — keyword/alias hits derived from product_hierarchy.yaml
                 (deterministic, free, no network).
  2. Semantic  — embedding cosine similarity vs. node labels
                 (one embed call, only when rules are inconclusive).
  3. LLM       — full LLM classification, only for ambiguous / low-signal docs.

Every result carries:
  {product, feature, component, confidence (0-1), method, needs_review}

Hierarchy consistency is always enforced — a chosen feature must belong to the
chosen product and a component to the chosen feature. Low-confidence results are
flagged ``needs_review`` so they can be triaged instead of silently trusted.

The hierarchy YAML may stay as plain names (back-compatible) or optionally add
``aliases``/``keywords`` lists per node to boost rule recall, e.g.:

    - name: Authentication
      aliases: [auth, login, sso]
      keywords: [jwt, oauth, token]
"""
from __future__ import annotations

import json
import logging
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from openai import APIError, AsyncOpenAI

from app.config import settings
from app.pipeline.embedder import Embedder

logger = logging.getLogger(__name__)

_GENERAL_PRODUCT = "General"
_GENERAL_FEATURE = "Uncategorized"
_FALLBACK: dict[str, Any] = {
    "product": _GENERAL_PRODUCT,
    "feature": _GENERAL_FEATURE,
    "component": None,
    "confidence": 0.0,
    "method": "fallback",
    "needs_review": True,
}

_SYSTEM_PROMPT = (
    "You are a classification assistant. "
    "Return ONLY a valid JSON object — no markdown, no code fences, no explanation."
)

# Generic words that must not become standalone match keywords.
_STOPWORDS = frozenset(
    {"and", "the", "of", "for", "management", "general", "uncategorized", "service", "services"}
)
_TOKEN_RE = re.compile(r"[a-z0-9]+")


@dataclass(frozen=True)
class _Node:
    """A single classifiable node (product / feature / component) in the taxonomy."""

    product: str
    feature: str | None
    component: str | None
    keywords: frozenset[str]
    label: str
    depth: int  # 1=product, 2=feature, 3=component (deeper = more specific)


def _keywords(*names: str | None) -> frozenset[str]:
    """Build a keyword set from a node name plus optional aliases/keywords."""
    kws: set[str] = set()
    for name in names:
        if not name:
            continue
        low = name.lower().strip()
        if not low:
            continue
        kws.add(low)  # full phrase (matched with higher weight)
        for tok in _TOKEN_RE.findall(low):
            if len(tok) >= 3 and tok not in _STOPWORDS:
                kws.add(tok)
    return frozenset(kws)


def _name_and_extra(item: Any) -> tuple[str | None, list[str], list[str]]:
    """Accept a node as a bare string or a dict with name/aliases/keywords."""
    if isinstance(item, str):
        return item, [], []
    if isinstance(item, dict):
        return item.get("name"), list(item.get("aliases") or []), list(item.get("keywords") or [])
    return None, [], []


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


class HierarchyClassifier:
    def __init__(self) -> None:
        self._client = AsyncOpenAI(
            api_key=settings.openai_api_key,
            base_url=settings.ai_base_url,
        )
        self._model = settings.llm_model
        self._hierarchy = self._load_hierarchy()
        self._hierarchy_yaml = yaml.dump(self._hierarchy, default_flow_style=False)
        self._nodes = self._build_nodes(self._hierarchy)
        self._products_map = self._build_products_map(self._hierarchy)
        # Lazily-populated cache of node-label embeddings (semantic fallback).
        self._embedder = Embedder()
        self._node_embeddings: list[list[float]] | None = None

    # ── Loading / taxonomy build ──────────────────────────────────────────────

    def _load_hierarchy(self) -> dict[str, Any]:
        path = Path(settings.hierarchy_config_path)
        if not path.exists():
            logger.warning("[HierarchyClassifier] hierarchy file not found at %s — using fallback", path)
            return {"products": [{"name": _GENERAL_PRODUCT, "features": [{"name": _GENERAL_FEATURE}]}]}
        with path.open(encoding="utf-8") as f:
            return yaml.safe_load(f) or {}

    def _build_nodes(self, hierarchy: dict[str, Any]) -> list[_Node]:
        """Flatten the taxonomy into match nodes. The catch-all product is skipped."""
        nodes: list[_Node] = []
        for product in hierarchy.get("products", []) or []:
            pname, pal, pkw = _name_and_extra(product)
            if not pname or pname == _GENERAL_PRODUCT:
                continue
            nodes.append(_Node(pname, None, None, _keywords(pname, *pal, *pkw), pname, 1))

            features = product.get("features") if isinstance(product, dict) else None
            for feature in features or []:
                fname, fal, fkw = _name_and_extra(feature)
                if not fname:
                    continue
                nodes.append(
                    _Node(pname, fname, None, _keywords(fname, *fal, *fkw), f"{pname} > {fname}", 2)
                )

                components = feature.get("components") if isinstance(feature, dict) else None
                for component in components or []:
                    cname, cal, ckw = _name_and_extra(component)
                    if not cname:
                        continue
                    nodes.append(
                        _Node(
                            pname,
                            fname,
                            cname,
                            _keywords(cname, *cal, *ckw),
                            f"{pname} > {fname} > {cname}",
                            3,
                        )
                    )
        return nodes

    def _build_products_map(self, hierarchy: dict[str, Any]) -> dict[str, Any]:
        """Lowercased lookup tree used to validate (and repair) LLM output."""
        products: dict[str, Any] = {}
        for product in hierarchy.get("products", []) or []:
            pname, _, _ = _name_and_extra(product)
            if not pname:
                continue
            feats: dict[str, Any] = {}
            features = product.get("features") if isinstance(product, dict) else None
            for feature in features or []:
                fname, _, _ = _name_and_extra(feature)
                if not fname:
                    continue
                comps: dict[str, str] = {}
                components = feature.get("components") if isinstance(feature, dict) else None
                for component in components or []:
                    cname, _, _ = _name_and_extra(component)
                    if cname:
                        comps[cname.lower()] = cname
                feats[fname.lower()] = {"name": fname, "components": comps}
            products[pname.lower()] = {"name": pname, "features": feats}
        return products

    # ── Public API ────────────────────────────────────────────────────────────

    async def classify(self, title: str, content_preview: str) -> dict[str, Any]:
        """Return {product, feature, component, confidence, method, needs_review}."""
        title = (title or "").strip()
        content_preview = (content_preview or "").strip()

        rule = self._rule_match(title, content_preview)
        if rule is not None:
            return rule

        if settings.classification_semantic_fallback and self._nodes:
            semantic = await self._semantic_match(title, content_preview)
            if semantic is not None:
                return semantic

        return await self._llm_classify(title, content_preview)

    # ── Stage 1: deterministic rule / keyword match ───────────────────────────

    def _rule_match(self, title: str, content_preview: str) -> dict[str, Any] | None:
        title_l = title.lower()
        body_l = f"{title} {content_preview}".lower()

        best: _Node | None = None
        best_score = 0.0
        second_score = 0.0

        for node in self._nodes:
            score = 0.0
            for kw in node.keywords:
                weight = 2.0 if " " in kw else 1.0  # multi-word phrase beats single token
                if kw in title_l:
                    score += weight * 3.0
                elif kw in body_l:
                    score += weight * 1.0
            if score > 0.0:
                score += node.depth * 0.01  # tie-break toward more specific nodes
            if score > best_score:
                best, second_score, best_score = node, best_score, score
            elif score > second_score:
                second_score = score

        if best is None or best_score < settings.classification_rule_min_score:
            return None

        confidence = min(0.95, 0.5 + 0.07 * best_score)
        logger.debug(
            "[HierarchyClassifier] rule match %s score=%.2f (runner-up=%.2f)",
            best.label, best_score, second_score,
        )
        return self._result(best.product, best.feature, best.component, confidence, "rule")

    # ── Stage 2: embedding similarity fallback ────────────────────────────────

    async def _semantic_match(self, title: str, content_preview: str) -> dict[str, Any] | None:
        try:
            node_vecs = await self._ensure_node_embeddings()
            doc_vec = await self._embedder.embed_single(f"{title}\n{content_preview}".strip())
        except APIError as exc:
            logger.warning("[HierarchyClassifier] semantic fallback embed failed: %s", exc)
            return None

        if not node_vecs:
            return None

        best_idx, best_sim = -1, -1.0
        for idx, vec in enumerate(node_vecs):
            sim = _cosine(doc_vec, vec)
            if sim > best_sim:
                best_idx, best_sim = idx, sim

        if best_idx < 0 or best_sim < settings.classification_semantic_threshold:
            return None

        node = self._nodes[best_idx]
        confidence = min(0.9, max(0.5, best_sim))
        logger.debug("[HierarchyClassifier] semantic match %s sim=%.3f", node.label, best_sim)
        return self._result(node.product, node.feature, node.component, confidence, "semantic")

    async def _ensure_node_embeddings(self) -> list[list[float]]:
        if self._node_embeddings is None:
            labels = [n.label for n in self._nodes]
            self._node_embeddings = await self._embedder.embed_batch(labels) if labels else []
            logger.info("[HierarchyClassifier] cached %d node-label embeddings", len(self._node_embeddings))
        return self._node_embeddings

    # ── Stage 3: LLM classification ───────────────────────────────────────────

    async def _llm_classify(self, title: str, content_preview: str) -> dict[str, Any]:
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
            parsed = json.loads(self._strip_fences(raw))
            if not isinstance(parsed, dict):
                raise ValueError("LLM classification result is not a JSON object")
        except (APIError, json.JSONDecodeError, ValueError, TypeError) as exc:
            logger.warning(
                "[HierarchyClassifier] LLM classification failed for %r: %s — using fallback",
                title, exc,
            )
            return dict(_FALLBACK)

        product, feature, component, fully_valid = self._validate(
            parsed.get("product"), parsed.get("feature"), parsed.get("component")
        )
        confidence = 0.7 if fully_valid else 0.5
        if product == _GENERAL_PRODUCT:
            confidence = min(confidence, 0.3)
        return self._result(product, feature, component, confidence, "llm")

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _strip_fences(raw: str) -> str:
        text = raw.strip()
        if text.startswith("```"):
            text = text.strip("`")
            if text.lower().startswith("json"):
                text = text[4:]
        return text.strip()

    def _validate(
        self, product: Any, feature: Any, component: Any
    ) -> tuple[str, str | None, str | None, bool]:
        """Coerce LLM output to a real branch of the taxonomy. Returns (..., fully_valid)."""
        prod = product if isinstance(product, str) else ""
        prod_entry = self._products_map.get(prod.lower())
        if prod_entry is None:
            return _GENERAL_PRODUCT, _GENERAL_FEATURE, None, False

        feat = feature if isinstance(feature, str) else ""
        feat_entry = prod_entry["features"].get(feat.lower())
        if feat_entry is None:
            return prod_entry["name"], None, None, False

        comp = component if isinstance(component, str) else ""
        comp_name = feat_entry["components"].get(comp.lower())
        if comp and comp_name is None:
            return prod_entry["name"], feat_entry["name"], None, False

        return prod_entry["name"], feat_entry["name"], comp_name, True

    def _result(
        self, product: str, feature: str | None, component: str | None, confidence: float, method: str
    ) -> dict[str, Any]:
        return {
            "product": product,
            "feature": feature,
            "component": component,
            "confidence": round(confidence, 3),
            "method": method,
            "needs_review": confidence < settings.classification_review_threshold,
        }
