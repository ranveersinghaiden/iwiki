# Graph Report - .  (2026-06-25)

## Corpus Check
- 78 files · ~58,366 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 353 nodes · 639 edges · 36 communities (27 shown, 9 thin omitted)
- Extraction: 75% EXTRACTED · 25% INFERRED · 0% AMBIGUOUS · INFERRED: 160 edges (avg confidence: 0.54)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- [[_COMMUNITY_Ingestion API & External Clients|Ingestion API & External Clients]]
- [[_COMMUNITY_Expert Query API|Expert Query API]]
- [[_COMMUNITY_E2E Test Stubs & Mocks|E2E Test Stubs & Mocks]]
- [[_COMMUNITY_AI Agent Orchestration|AI Agent Orchestration]]
- [[_COMMUNITY_Content Classification Pipeline|Content Classification Pipeline]]
- [[_COMMUNITY_Ingestion Document Routes|Ingestion Document Routes]]
- [[_COMMUNITY_Database Models|Database Models]]
- [[_COMMUNITY_System Architecture & Data Flow|System Architecture & Data Flow]]
- [[_COMMUNITY_Search Reranking|Search Reranking]]
- [[_COMMUNITY_E2E Test Runner|E2E Test Runner]]
- [[_COMMUNITY_App Configuration|App Configuration]]
- [[_COMMUNITY_Confluence API Client|Confluence API Client]]
- [[_COMMUNITY_Expert Repository|Expert Repository]]
- [[_COMMUNITY_Jira API Client|Jira API Client]]
- [[_COMMUNITY_Text Chunker|Text Chunker]]
- [[_COMMUNITY_Expert Refresher|Expert Refresher]]
- [[_COMMUNITY_Java Coding Standards|Java Coding Standards]]
- [[_COMMUNITY_Ingestion DB Session|Ingestion DB Session]]
- [[_COMMUNITY_Query DB Session|Query DB Session]]
- [[_COMMUNITY_MCP Server Config|MCP Server Config]]
- [[_COMMUNITY_Agent Compression Report|Agent Compression Report]]
- [[_COMMUNITY_Product Knowledge Map|Product Knowledge Map]]
- [[_COMMUNITY_Spring Dependency Injection|Spring Dependency Injection]]
- [[_COMMUNITY_Spring Kafka Patterns|Spring Kafka Patterns]]
- [[_COMMUNITY_Spring Redis Patterns|Spring Redis Patterns]]

## God Nodes (most connected - your core abstractions)
1. `HierarchyClassifier` - 26 edges
2. `IngestionPipeline` - 21 edges
3. `ChunkRecord` - 20 edges
4. `Embedder` - 19 edges
5. `TextChunker` - 17 edges
6. `ProductExpertRefresher` - 17 edges
7. `ConfluenceClient` - 15 edges
8. `ConfluencePage` - 14 edges
9. `JiraClient` - 14 edges
10. `JiraIssue` - 13 edges

## Surprising Connections (you probably didn't know these)
- `Exception` --uses--> `IngestionPipeline`  [INFERRED]
  ingestion-service/main.py → ingestion-service/app/pipeline/ingestion_pipeline.py
- `unhandled_exception_handler()` --calls--> `JSONResponse`  [INFERRED]
  ingestion-service/main.py → tests/e2e/stub_openai.py
- `unhandled_exception_handler()` --calls--> `JSONResponse`  [INFERRED]
  query-service/main.py → tests/e2e/stub_openai.py
- `Caveman Communication Mode` --references--> `QA-ISystem Copilot Instructions`  [EXTRACTED]
  .agents/skills/caveman/SKILL.md → .github/copilot-instructions.md
- `ingestion-service Dependencies (FastAPI, pgvector, openai)` --references--> `ingestion-service (port 8090)`  [EXTRACTED]
  ingestion-service/requirements.txt → ARCHITECTURE.md

## Import Cycles
- 1-file cycle: `ingestion-service/app/clients/confluence_client.py -> ingestion-service/app/clients/confluence_client.py`
- 1-file cycle: `ingestion-service/app/clients/jira_client.py -> ingestion-service/app/clients/jira_client.py`
- 1-file cycle: `ingestion-service/app/db/repository.py -> ingestion-service/app/db/repository.py`
- 1-file cycle: `ingestion-service/main.py -> ingestion-service/main.py`
- 1-file cycle: `query-service/app/search/reranker.py -> query-service/app/search/reranker.py`
- 1-file cycle: `query-service/main.py -> query-service/main.py`

## Hyperedges (group relationships)
- **QA Agent Pipeline Orchestration** — conductor_agent_conductor, javacoder_agent_javacoder, agents_codereviewer_codereviewer, agents_security_security, agents_tester_tester [EXTRACTED 1.00]
- **Coding Standards & Rules Cluster** — agents_shared_rules_shared_rules, copilot_instructions_zero_mockito, copilot_instructions_java25_rules, copilot_instructions_spring_di [INFERRED 0.85]
- **iWiki Core Service Triad** — architecture_ingestion_service, architecture_query_service, architecture_postgresql_pgvector [EXTRACTED 1.00]
- **Hybrid Search Stack (RRF + Vector + BM25)** — architecture_rrf, architecture_vector_ann, architecture_bm25_fts [EXTRACTED 1.00]
- **Java Standards Cluster** — java_coding_conventions, java_error_handling, java_logging, spring_dependency_injection [INFERRED 0.85]

## Communities (36 total, 9 thin omitted)

### Community 0 - "Ingestion API & External Clients"
Cohesion: 0.15
Nodes (27): IngestDocumentRequest, BackgroundTasks, ConfluenceClient, ConfluencePage, JiraClient, JiraIssue, Yield all issues for the given projects, optionally filtered by update time., ConfluenceClient (+19 more)

### Community 1 - "Expert Query API"
Cohesion: 0.10
Nodes (31): DependencyEntry, _expert_to_response(), get_product_expert(), list_product_experts(), _parse_header_list(), ProductExpertResponse, query_knowledge_base(), QueryRequest (+23 more)

### Community 2 - "E2E Test Stubs & Mocks"
Cohesion: 0.09
Nodes (25): chat_completions(), _classification_response(), _deterministic_embedding(), embeddings(), _expert_response(), Stub OpenAI-compatible server for E2E testing. Implements /v1/embeddings and /v1, Generate a deterministic unit vector from text using MD5 seed., Return a valid JSON product classification based on document title keywords. (+17 more)

### Community 3 - "AI Agent Orchestration"
Cohesion: 0.10
Nodes (28): CodeReviewer Checklist (12 sections), Security Audit Checklist (10 sections), CodeReviewer Agent, Documentation Agent, Generic Coding Practices, Java Coder Implementation Guide, MCP Server Patterns, Agent Pipeline (Conductor → Coder → CodeReviewer → Security → Tester) (+20 more)

### Community 4 - "Content Classification Pipeline"
Cohesion: 0.15
Nodes (14): Any, _cosine(), HierarchyClassifier, _keywords(), _name_and_extra(), _Node, Product hierarchy classifier — hybrid, taxonomy-aware.  Cheapest-first cascade p, Flatten the taxonomy into match nodes. The catch-all product is skipped. (+6 more)

### Community 5 - "Ingestion Document Routes"
Cohesion: 0.09
Nodes (21): ingest_single_document(), Index a single raw document directly through the full pipeline.     Useful for t, Dependency — reject request if admin key is missing or wrong., Trigger a full re-index of all configured Jira projects and Confluence spaces., Trigger an incremental sync — only items updated since last sync watermark., Return current sync state for all sources., Manually trigger a refresh of all product expert records., _require_admin() (+13 more)

### Community 6 - "Database Models"
Cohesion: 0.18
Nodes (24): Base, Document, ProductExpert, Synthesised product/component knowledge used by AI agents and query service., SyncState, get_all_product_experts(), get_distinct_products(), get_documents_by_product() (+16 more)

### Community 7 - "System Architecture & Data Flow"
Cohesion: 0.12
Nodes (23): BM25 Full-Text Search (GIN Index), Chunks Table (Core Data Model), Classification Cascade: Rule→Semantic→LLM, Ingestion Metadata Table (Sync Watermarks), Ingestion Pipeline: Fetch→Clean→Chunk→Embed→Classify→Upsert, ingestion-service (port 8090), iWiki RAG Knowledge Search Platform, Permission Filtering (X-Allowed-Spaces, X-Allowed-Projects) (+15 more)

### Community 8 - "Search Reranking"
Cohesion: 0.20
Nodes (15): datetime, SearchResult, _authority(), _blended_score(), _freshness(), _llm_rerank(), _parse_order(), Reranker — refines hybrid-search candidates before answer generation.  Two stage (+7 more)

### Community 9 - "E2E Test Runner"
Cohesion: 0.38
Nodes (12): assert(), assert_ge(), fail(), info(), ingest(), ok(), psql_q(), qok() (+4 more)

### Community 10 - "App Configuration"
Cohesion: 0.20
Nodes (6): Return Ollama base URL if configured, otherwise None (→ OpenAI default)., BaseSettings, get_settings(), Settings, get_settings(), Settings

### Community 11 - "Confluence API Client"
Cohesion: 0.25
Nodes (7): _extract_cursor(), _parse_dt(), Confluence Cloud REST API v2 client., Extract 'cursor' query param from a relative URL string., Yield all pages in the given spaces, optionally filtered by update time., Any, datetime

### Community 12 - "Expert Repository"
Cohesion: 0.29
Nodes (9): get_expert(), get_experts_for_product(), list_experts(), Query-service read-only repository for product_experts., Return all product expert records., Return a single expert by product (and optional component)., Return all expert records for a given product (product-level + all components)., Any (+1 more)

### Community 13 - "Jira API Client"
Cohesion: 0.33
Nodes (7): _adf_to_text(), _display_name(), _parse_dt(), Jira REST API v3 client (Jira Cloud — basic auth with email + API token)., Recursively extract plain text from Atlassian Document Format (ADF) JSON., Any, datetime

### Community 15 - "Expert Refresher"
Cohesion: 0.40
Nodes (3): ExpertResult, ProductExpertRefresher — synthesises a compressed context entry for each product, Refresh expert records for every distinct product in the index.

### Community 16 - "Java Coding Standards"
Cohesion: 0.50
Nodes (4): Java 25 Coding Conventions, Java Error Handling Guidelines, Java Logging Standards (@Slf4j), Zero Mock Policy (Real Test Doubles)

## Knowledge Gaps
- **33 isolated node(s):** `Any`, `AsyncSession`, `AsyncSession`, `AsyncSession`, `Exception` (+28 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **9 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `IngestDocumentRequest` connect `Ingestion API & External Clients` to `Expert Query API`, `Content Classification Pipeline`, `Ingestion Document Routes`?**
  _High betweenness centrality (0.187) - this node is a cross-community bridge._
- **Why does `IngestionPipeline` connect `Ingestion API & External Clients` to `E2E Test Stubs & Mocks`, `Content Classification Pipeline`?**
  _High betweenness centrality (0.163) - this node is a cross-community bridge._
- **Why does `ChunkRecord` connect `Ingestion API & External Clients` to `Ingestion Document Routes`, `Database Models`?**
  _High betweenness centrality (0.097) - this node is a cross-community bridge._
- **Are the 13 inferred relationships involving `HierarchyClassifier` (e.g. with `IngestDocumentRequest` and `BackgroundTasks`) actually correct?**
  _`HierarchyClassifier` has 13 INFERRED edges - model-reasoned connections that need verification._
- **Are the 13 inferred relationships involving `IngestionPipeline` (e.g. with `IngestDocumentRequest` and `BackgroundTasks`) actually correct?**
  _`IngestionPipeline` has 13 INFERRED edges - model-reasoned connections that need verification._
- **Are the 18 inferred relationships involving `ChunkRecord` (e.g. with `ingest_single_document()` and `IngestDocumentRequest`) actually correct?**
  _`ChunkRecord` has 18 INFERRED edges - model-reasoned connections that need verification._
- **Are the 15 inferred relationships involving `Embedder` (e.g. with `IngestDocumentRequest` and `BackgroundTasks`) actually correct?**
  _`Embedder` has 15 INFERRED edges - model-reasoned connections that need verification._