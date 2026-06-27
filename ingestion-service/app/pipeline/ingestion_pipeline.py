"""
Main ingestion pipeline orchestrator.

Flow per document:
  raw content → clean → chunk → embed (batch) → classify → upsert DB

After all sources are synced, product experts are refreshed automatically.
Supports full sync (all items) and incremental sync (updated since watermark).
"""
from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from app.clients.confluence_client import ConfluenceClient, ConfluencePage
from app.clients.jira_client import JiraClient, JiraIssue
from app.config import settings
from app.db.database import AsyncSessionFactory
from app.db import repository
from app.db.repository import ChunkRecord
from app.pipeline.chunker import TextChunker
from app.pipeline.classifier import HierarchyClassifier
from app.pipeline.cleaner import clean_html, clean_text
from app.pipeline.embedder import Embedder
from app.pipeline.expert_refresher import ProductExpertRefresher

logger = logging.getLogger(__name__)


@dataclass
class SyncResult:
    source_type: str
    items_processed: int
    items_failed: int
    started_at: datetime
    finished_at: datetime


class IngestionPipeline:
    def __init__(
        self,
        jira_client: JiraClient,
        confluence_client: ConfluenceClient,
        chunker: TextChunker,
        embedder: Embedder,
        classifier: HierarchyClassifier,
        expert_refresher: ProductExpertRefresher,
    ) -> None:
        self._jira = jira_client
        self._confluence = confluence_client
        self._chunker = chunker
        self._embedder = embedder
        self._classifier = classifier
        self._expert_refresher = expert_refresher

    @classmethod
    def build(cls) -> "IngestionPipeline":
        """Factory — construct a pipeline from current settings."""
        return cls(
            jira_client=JiraClient(),
            confluence_client=ConfluenceClient(),
            chunker=TextChunker(),
            embedder=Embedder(),
            classifier=HierarchyClassifier(),
            expert_refresher=ProductExpertRefresher(),
        )

    async def run(self, full_sync: bool = False) -> list[SyncResult]:
        """Run ingestion for all configured sources, then refresh product experts."""
        results: list[SyncResult] = []

        if settings.jira_project_list:
            result = await self._sync_jira(full_sync=full_sync)
            results.append(result)

        if settings.confluence_space_list:
            result = await self._sync_confluence(full_sync=full_sync)
            results.append(result)

        # Reconcile deletions only on a full sync, where we enumerate every
        # remote item anyway — removes documents deleted at the source.
        if full_sync and settings.reconcile_on_full_sync:
            try:
                await self.reconcile_deletions()
            except Exception as exc:
                logger.error("[IngestionPipeline] reconcile failed: %s", exc, exc_info=exc)

        # Refresh product experts after every sync so context stays current
        try:
            await self._expert_refresher.refresh_all()
        except Exception as exc:
            logger.error("[IngestionPipeline] expert refresh failed: %s", exc, exc_info=exc)

        return results

    # ── Jira ──────────────────────────────────────────────────────────────────

    async def _sync_jira(self, full_sync: bool) -> SyncResult:
        started = datetime.now(timezone.utc)
        processed = failed = 0

        async with AsyncSessionFactory() as session:
            watermark = None if full_sync else await repository.get_watermark(session, "jira")
            logger.info("[IngestionPipeline] jira sync start full=%s watermark=%s", full_sync, watermark)

            async for issue in self._jira.fetch_issues(settings.jira_project_list, updated_after=watermark):
                try:
                    await self._process_jira_issue(issue, skip_unchanged=not full_sync)
                    processed += 1
                except Exception as exc:
                    logger.error("[IngestionPipeline] jira issue %s failed: %s", issue.issue_key, exc, exc_info=exc)
                    failed += 1

            finished = datetime.now(timezone.utc)
            await repository.update_sync_state(
                session,
                source_type="jira",
                last_synced_at=finished,
                total_items_indexed=processed,
                last_run_status="success" if failed == 0 else "partial",
            )

        logger.info("[IngestionPipeline] jira sync done processed=%d failed=%d", processed, failed)
        return SyncResult("jira", processed, failed, started, finished)

    async def _process_jira_issue(self, issue: JiraIssue, skip_unchanged: bool = False) -> None:
        # Build raw text: summary + description + comments
        parts = [issue.summary, issue.description] + issue.comments
        raw = "\n\n".join(p for p in parts if p)
        cleaned = clean_text(raw)

        # Skip the expensive embed+classify+upsert when content is unchanged.
        content_hash = hashlib.sha256(cleaned.encode("utf-8")).hexdigest()
        if skip_unchanged and await self._is_unchanged("jira", issue.issue_key, content_hash):
            logger.debug("[IngestionPipeline] jira %s unchanged — skip", issue.issue_key)
            return

        chunks = self._chunker.chunk(cleaned)
        if not chunks:
            return

        texts = [c.content for c in chunks]
        embeddings = await self._embedder.embed_batch(texts)
        classification = await self._classifier.classify(issue.summary, cleaned[:600])

        doc_metadata: dict[str, Any] = {
            "issue_type": issue.issue_type,
            "status": issue.status,
            "project_key": issue.project_key,
            "labels": issue.labels,
            "assignee": issue.assignee,
            "reporter": issue.reporter,
            "created_at": issue.created_at.isoformat() if issue.created_at else None,
        }

        chunk_records = [
            ChunkRecord(
                chunk_index=c.chunk_index,
                content=c.content,
                embedding=embeddings[i],
                token_count=c.token_count,
                metadata={"source": "jira", "issue_key": issue.issue_key},
            )
            for i, c in enumerate(chunks)
        ]

        async with AsyncSessionFactory() as session:
            await repository.upsert_document_with_chunks(
                session,
                source_type="jira",
                source_id=issue.issue_key,
                source_url=issue.source_url,
                title=f"[{issue.issue_key}] {issue.summary}",
                raw_content=raw,
                cleaned_content=cleaned,
                doc_metadata=doc_metadata,
                allowed_spaces=[],
                allowed_projects=issue.allowed_projects,
                product_hierarchy=classification,
                source_updated_at=issue.updated_at,
                chunks=chunk_records,
                content_hash=content_hash,
            )

    # ── Confluence ────────────────────────────────────────────────────────────

    async def _sync_confluence(self, full_sync: bool) -> SyncResult:
        started = datetime.now(timezone.utc)
        processed = failed = 0

        async with AsyncSessionFactory() as session:
            watermark = None if full_sync else await repository.get_watermark(session, "confluence")
            logger.info("[IngestionPipeline] confluence sync start full=%s watermark=%s", full_sync, watermark)

            async for page in self._confluence.fetch_pages(settings.confluence_space_list, updated_after=watermark):
                try:
                    await self._process_confluence_page(page, skip_unchanged=not full_sync)
                    processed += 1
                except Exception as exc:
                    logger.error("[IngestionPipeline] confluence page %s failed: %s", page.page_id, exc, exc_info=exc)
                    failed += 1

            finished = datetime.now(timezone.utc)
            await repository.update_sync_state(
                session,
                source_type="confluence",
                last_synced_at=finished,
                total_items_indexed=processed,
                last_run_status="success" if failed == 0 else "partial",
            )

        logger.info("[IngestionPipeline] confluence sync done processed=%d failed=%d", processed, failed)
        return SyncResult("confluence", processed, failed, started, finished)

    async def _process_confluence_page(self, page: ConfluencePage, skip_unchanged: bool = False) -> None:
        cleaned = clean_html(page.body_html)

        content_hash = hashlib.sha256(cleaned.encode("utf-8")).hexdigest()
        if skip_unchanged and await self._is_unchanged("confluence", page.page_id, content_hash):
            logger.debug("[IngestionPipeline] confluence %s unchanged — skip", page.page_id)
            return

        chunks = self._chunker.chunk(cleaned)
        if not chunks:
            return

        texts = [c.content for c in chunks]
        embeddings = await self._embedder.embed_batch(texts)
        classification = await self._classifier.classify(page.title, cleaned[:600])

        doc_metadata: dict[str, Any] = {
            "space_key": page.space_key,
            "author": page.author,
            "created_at": page.created_at.isoformat() if page.created_at else None,
        }

        chunk_records = [
            ChunkRecord(
                chunk_index=c.chunk_index,
                content=c.content,
                embedding=embeddings[i],
                token_count=c.token_count,
                metadata={"source": "confluence", "space_key": page.space_key},
            )
            for i, c in enumerate(chunks)
        ]

        async with AsyncSessionFactory() as session:
            await repository.upsert_document_with_chunks(
                session,
                source_type="confluence",
                source_id=page.page_id,
                source_url=page.source_url,
                title=page.title,
                raw_content=page.body_html,
                cleaned_content=cleaned,
                doc_metadata=doc_metadata,
                allowed_spaces=page.allowed_spaces,
                allowed_projects=[],
                product_hierarchy=classification,
                source_updated_at=page.updated_at,
                chunks=chunk_records,
                content_hash=content_hash,
            )

    # ── Helpers ───────────────────────────────────────────────────────────────

    async def _is_unchanged(self, source_type: str, source_id: str, content_hash: str) -> bool:
        """True when the document already exists with an identical content hash."""
        async with AsyncSessionFactory() as session:
            existing = await repository.get_document_content_hash(session, source_type, source_id)
        return existing is not None and existing == content_hash

    # ── Delete reconciliation ─────────────────────────────────────────────────

    async def reconcile_deletions(self) -> dict[str, int]:
        """Remove documents that no longer exist at the source.

        Enumerates every current remote id, diffs against the DB, and deletes the
        stragglers (their chunks cascade via FK). Guards against mass deletion: if
        the remote id-set comes back empty (e.g. API outage or misconfiguration)
        the source is skipped entirely rather than wiping the index.
        """
        deleted: dict[str, int] = {}

        if settings.jira_project_list:
            remote_ids = {
                issue.issue_key
                async for issue in self._jira.fetch_issues(
                    settings.jira_project_list, updated_after=None
                )
            }
            deleted["jira"] = await self._reconcile_source("jira", remote_ids)

        if settings.confluence_space_list:
            remote_ids = {
                page.page_id
                async for page in self._confluence.fetch_pages(
                    settings.confluence_space_list, updated_after=None
                )
            }
            deleted["confluence"] = await self._reconcile_source("confluence", remote_ids)

        return deleted

    async def _reconcile_source(self, source_type: str, remote_ids: set[str]) -> int:
        if not remote_ids:
            logger.warning(
                "[IngestionPipeline] %s reconcile skipped — empty remote id set (safety guard)",
                source_type,
            )
            return 0

        async with AsyncSessionFactory() as session:
            db_ids = await repository.list_source_ids(session, source_type)
            stale = list(db_ids - remote_ids)
            if not stale:
                logger.info("[IngestionPipeline] %s reconcile — nothing to delete", source_type)
                return 0
            count = await repository.delete_documents_by_source_ids(session, source_type, stale)

        logger.info("[IngestionPipeline] %s reconcile — deleted %d stale documents", source_type, count)
        return count

