"""Jira REST API v3 client (Jira Cloud — basic auth with email + API token)."""
from __future__ import annotations

import base64
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, AsyncIterator

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

_DATE_FMT = "%Y-%m-%d %H:%M"


@dataclass
class JiraIssue:
    issue_key: str
    summary: str
    description: str
    comments: list[str]
    issue_type: str
    status: str
    project_key: str
    labels: list[str]
    assignee: str | None
    reporter: str | None
    created_at: datetime | None
    updated_at: datetime | None
    source_url: str
    allowed_projects: list[str]


class JiraClient:
    def __init__(self) -> None:
        raw = f"{settings.jira_user_email}:{settings.jira_api_token}"
        token = base64.b64encode(raw.encode()).decode()
        self._headers = {
            "Authorization": f"Basic {token}",
            "Accept": "application/json",
        }
        self._base = settings.jira_base_url.rstrip("/")

    async def fetch_issues(
        self,
        project_keys: list[str],
        updated_after: datetime | None = None,
    ) -> AsyncIterator[JiraIssue]:
        """Yield all issues for the given projects, optionally filtered by update time."""
        projects_jql = ", ".join(f'"{k}"' for k in project_keys)
        jql = f"project in ({projects_jql})"
        if updated_after:
            ts = updated_after.strftime(_DATE_FMT)
            jql += f' AND updated >= "{ts}"'
        jql += " ORDER BY updated ASC"

        start = 0
        async with httpx.AsyncClient(headers=self._headers, timeout=30) as client:
            while True:
                resp = await client.get(
                    f"{self._base}/rest/api/3/search",
                    params={
                        "jql": jql,
                        "startAt": start,
                        "maxResults": settings.jira_page_size,
                        "fields": "summary,description,comment,issuetype,status,project,labels,assignee,reporter,created,updated",
                        "expand": "renderedFields",
                    },
                )
                resp.raise_for_status()
                data = resp.json()
                issues: list[dict[str, Any]] = data.get("issues", [])
                if not issues:
                    break

                for raw in issues:
                    yield self._parse(raw)

                start += len(issues)
                if start >= data.get("total", 0):
                    break

        logger.info("[JiraClient] fetched issues for projects=%s updated_after=%s", project_keys, updated_after)

    def _parse(self, raw: dict[str, Any]) -> JiraIssue:
        fields = raw.get("fields", {})
        rendered = raw.get("renderedFields", {})

        description = (
            rendered.get("description")
            or _adf_to_text(fields.get("description"))
            or ""
        )

        comments: list[str] = []
        for c in fields.get("comment", {}).get("comments", []):
            body = c.get("renderedBody") or _adf_to_text(c.get("body")) or ""
            if body:
                comments.append(body)

        project_key = fields.get("project", {}).get("key", "")

        return JiraIssue(
            issue_key=raw["key"],
            summary=fields.get("summary") or "",
            description=description,
            comments=comments,
            issue_type=fields.get("issuetype", {}).get("name", ""),
            status=fields.get("status", {}).get("name", ""),
            project_key=project_key,
            labels=fields.get("labels") or [],
            assignee=_display_name(fields.get("assignee")),
            reporter=_display_name(fields.get("reporter")),
            created_at=_parse_dt(fields.get("created")),
            updated_at=_parse_dt(fields.get("updated")),
            source_url=f"{self._base}/browse/{raw['key']}",
            allowed_projects=[project_key] if project_key else [],
        )


def _display_name(obj: dict | None) -> str | None:
    return obj.get("displayName") if obj else None


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _adf_to_text(node: Any, depth: int = 0) -> str:
    """Recursively extract plain text from Atlassian Document Format (ADF) JSON."""
    if depth > 20:
        return ""
    if node is None:
        return ""
    if isinstance(node, str):
        return node
    if isinstance(node, dict):
        node_type = node.get("type", "")
        if node_type == "text":
            return node.get("text", "")
        parts = [_adf_to_text(child, depth + 1) for child in node.get("content", [])]
        joined = " ".join(p for p in parts if p)
        if node_type in ("paragraph", "heading", "listItem", "tableCell", "tableHeader"):
            return joined + "\n"
        return joined
    if isinstance(node, list):
        return " ".join(_adf_to_text(item, depth + 1) for item in node)
    return ""

