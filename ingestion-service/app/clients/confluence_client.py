"""Confluence Cloud REST API v2 client."""
from __future__ import annotations

import base64
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, AsyncIterator

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


@dataclass
class ConfluencePage:
    page_id: str
    title: str
    body_html: str
    space_key: str
    author: str | None
    created_at: datetime | None
    updated_at: datetime | None
    source_url: str
    allowed_spaces: list[str]


class ConfluenceClient:
    def __init__(self) -> None:
        raw = f"{settings.jira_user_email}:{settings.confluence_api_token}"
        token = base64.b64encode(raw.encode()).decode()
        self._headers = {
            "Authorization": f"Basic {token}",
            "Accept": "application/json",
        }
        self._base = settings.confluence_base_url.rstrip("/")

    async def fetch_pages(
        self,
        space_keys: list[str],
        updated_after: datetime | None = None,
    ) -> AsyncIterator[ConfluencePage]:
        """Yield all pages in the given spaces, optionally filtered by update time."""
        for space_key in space_keys:
            async for page in self._fetch_space_pages(space_key, updated_after):
                yield page

    async def _fetch_space_pages(
        self,
        space_key: str,
        updated_after: datetime | None,
    ) -> AsyncIterator[ConfluencePage]:
        cursor: str | None = None
        async with httpx.AsyncClient(headers=self._headers, timeout=30) as client:
            while True:
                params: dict[str, Any] = {
                    "spaceKey": space_key,
                    "limit": settings.confluence_page_size,
                    "expand": "body.storage,version,history.createdBy",
                    "status": "current",
                }
                if cursor:
                    params["cursor"] = cursor

                resp = await client.get(
                    f"{self._base}/wiki/rest/api/content",
                    params=params,
                )
                resp.raise_for_status()
                data = resp.json()
                results: list[dict[str, Any]] = data.get("results", [])
                if not results:
                    break

                for raw in results:
                    page = self._parse(raw, space_key)
                    if updated_after and page.updated_at and page.updated_at <= updated_after:
                        continue
                    yield page

                # v1 API uses _links.next for pagination
                next_link = data.get("_links", {}).get("next")
                if not next_link:
                    break
                # extract cursor from next link query string
                cursor = _extract_cursor(next_link)
                if not cursor:
                    break

        logger.info("[ConfluenceClient] fetched pages for space=%s updated_after=%s", space_key, updated_after)

    def _parse(self, raw: dict[str, Any], space_key: str) -> ConfluencePage:
        history = raw.get("history", {})
        version = raw.get("version", {})
        body_html: str = raw.get("body", {}).get("storage", {}).get("value", "")

        return ConfluencePage(
            page_id=str(raw["id"]),
            title=raw.get("title", ""),
            body_html=body_html,
            space_key=space_key,
            author=history.get("createdBy", {}).get("displayName"),
            created_at=_parse_dt(history.get("createdDate")),
            updated_at=_parse_dt(version.get("when")),
            source_url=f"{self._base}/wiki{raw.get('_links', {}).get('webui', '')}",
            allowed_spaces=[space_key],
        )


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _extract_cursor(next_link: str) -> str | None:
    """Extract 'cursor' query param from a relative URL string."""
    if "cursor=" not in next_link:
        return None
    for part in next_link.split("&"):
        if part.startswith("cursor=") or "?cursor=" in part:
            return part.split("cursor=")[-1].split("&")[0]
    return None

