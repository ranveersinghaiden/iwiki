# Graph Report - .  (2026-06-28)

## Corpus Check
- 80 files · ~59,060 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 399 nodes · 724 edges · 40 communities (29 shown, 11 thin omitted)
- Extraction: 76% EXTRACTED · 24% INFERRED · 0% AMBIGUOUS · INFERRED: 173 edges (avg confidence: 0.56)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- [[_COMMUNITY_Confluence & Jira Ingestion|Confluence & Jira Ingestion]]
- [[_COMMUNITY_Query API & RAG Answering|Query API & RAG Answering]]
- [[_COMMUNITY_Data Model & Sync State|Data Model & Sync State]]
- [[_COMMUNITY_Redis Cache & LLM Client|Redis Cache & LLM Client]]
- [[_COMMUNITY_Agent Governance & Standards|Agent Governance & Standards]]
- [[_COMMUNITY_Taxonomy Classification|Taxonomy Classification]]
- [[_COMMUNITY_E2E Stub & App Lifecycle|E2E Stub & App Lifecycle]]
- [[_COMMUNITY_Ingestion Admin API|Ingestion Admin API]]
- [[_COMMUNITY_Embedding & Chunking|Embedding & Chunking]]
- [[_COMMUNITY_Reranker Scoring|Reranker Scoring]]
- [[_COMMUNITY_E2E Test Script|E2E Test Script]]
- [[_COMMUNITY_Service Configuration|Service Configuration]]
- [[_COMMUNITY_HTML Cleaning|HTML Cleaning]]
- [[_COMMUNITY_Query Expert Repository|Query Expert Repository]]
- [[_COMMUNITY_Product Expert Synthesis|Product Expert Synthesis]]
- [[_COMMUNITY_Token-Based Chunker|Token-Based Chunker]]
- [[_COMMUNITY_Expert Refresher Module|Expert Refresher Module]]
- [[_COMMUNITY_Java Coding Standards|Java Coding Standards]]
- [[_COMMUNITY_Query DB Session|Query DB Session]]
- [[_COMMUNITY_Ingestion DB Session|Ingestion DB Session]]
- [[_COMMUNITY_CICD Deploy Workflows|CI/CD Deploy Workflows]]
- [[_COMMUNITY_MCP Server Docs|MCP Server Docs]]
- [[_COMMUNITY_Agent Compression Report|Agent Compression Report]]
- [[_COMMUNITY_Ingestion Dependencies|Ingestion Dependencies]]
- [[_COMMUNITY_Product Map Knowledge|Product Map Knowledge]]
- [[_COMMUNITY_Product Hierarchy|Product Hierarchy]]
- [[_COMMUNITY_Spring Constructor Injection|Spring Constructor Injection]]
- [[_COMMUNITY_Spring Kafka Patterns|Spring Kafka Patterns]]
- [[_COMMUNITY_Spring Redis Patterns|Spring Redis Patterns]]

## God Nodes (most connected - your core abstractions)
1. `HierarchyClassifier` - 27 edges
2. `IngestionPipeline` - 26 edges
3. `ChunkRecord` - 20 edges
4. `Embedder` - 20 edges
5. `TextChunker` - 18 edges
6. `ProductExpertRefresher` - 18 edges
7. `ConfluenceClient` - 16 edges
8. `AsyncSession` - 15 edges
9. `ConfluencePage` - 14 edges
10. `JiraClient` - 14 edges

## Surprising Connections (you probably didn't know these)
- `Confluence Cursor Pagination` --references--> `ConfluenceClient`  [EXTRACTED]
  ARCHITECTURE.md → ingestion-service/app/clients/confluence_client.py
- `Semantic Chunking` --references--> `TextChunker`  [EXTRACTED]
  ARCHITECTURE.md → ingestion-service/app/pipeline/chunker.py
- `3-Stage Hierarchy Classification` --references--> `HierarchyClassifier`  [EXTRACTED]
  ARCHITECTURE.md → ingestion-service/app/pipeline/classifier.py
- `Atomic Document+Chunk Upsert` --references--> `upsert_document_with_chunks()`  [EXTRACTED]
  ARCHITECTURE.md → ingestion-service/app/db/repository.py
- `HTML / Text Cleaning` --references--> `clean_html()`  [EXTRACTED]
  ARCHITECTURE.md → ingestion-service/app/pipeline/cleaner.py

## Import Cycles
- 1-file cycle: `ingestion-service/app/clients/confluence_client.py -> ingestion-service/app/clients/confluence_client.py`
- 1-file cycle: `ingestion-service/app/clients/jira_client.py -> ingestion-service/app/clients/jira_client.py`
- 1-file cycle: `ingestion-service/app/db/repository.py -> ingestion-service/app/db/repository.py`
- 1-file cycle: `ingestion-service/main.py -> ingestion-service/main.py`
- 1-file cycle: `query-service/main.py -> query-service/main.py`
- 1-file cycle: `query-service/app/search/reranker.py -> query-service/app/search/reranker.py`

## Hyperedges (group relationships)
- **QA Agent Pipeline Orchestration** — conductor_agent_conductor, javacoder_agent_javacoder, agents_codereviewer_codereviewer, agents_security_security, agents_tester_tester [EXTRACTED 1.00]
- **Coding Standards & Rules Cluster** — agents_shared_rules_shared_rules, copilot_instructions_zero_mockito, copilot_instructions_java25_rules, copilot_instructions_spring_di [INFERRED 0.85]
- **Java Standards Cluster** — java_coding_conventions, java_error_handling, java_logging, spring_dependency_injection [INFERRED 0.85]
- **Document Ingestion Flow** — arch_html_clean, arch_chunking, arch_batch_embedding, arch_classification, arch_upsert [INFERRED 0.85]
- **Query → Answer Flow** — arch_query_embedding, arch_hybrid_search, arch_reranking, arch_rag_generation [INFERRED 0.85]
- **Vector Storage & Indexing** — arch_chunks_table, arch_hnsw_index, arch_halfvec, arch_pgvector_cosine [INFERRED 0.85]

## Communities (40 total, 11 thin omitted)

### Community 0 - "Confluence & Jira Ingestion"
Cohesion: 0.09
Nodes (39): ingest_single_document(), IngestDocumentRequest, Index a single raw document directly through the full pipeline.     Useful for t, Product Experts Synthesis, product_experts table, BackgroundTasks, ConfluenceClient, ConfluencePage (+31 more)

### Community 1 - "Query API & RAG Answering"
Cohesion: 0.11
Nodes (32): DependencyEntry, _expert_to_response(), get_product_expert(), list_product_experts(), _parse_header_list(), ProductExpertResponse, query_knowledge_base(), QueryRequest (+24 more)

### Community 2 - "Data Model & Sync State"
Cohesion: 0.11
Nodes (34): Content-Hash Dedup, Delete Reconciliation, Incremental Sync (watermark), sync_state table, Base, Document, ProductExpert, Synthesised product/component knowledge used by AI agents and query service. (+26 more)

### Community 3 - "Redis Cache & LLM Client"
Cohesion: 0.09
Nodes (25): aclose_redis(), answer_key(), _digest(), embedding_key(), _enabled(), get_json(), get_redis(), Redis-backed cache for the query service.  Two things are cached:  * **Query emb (+17 more)

### Community 4 - "Agent Governance & Standards"
Cohesion: 0.10
Nodes (28): CodeReviewer Checklist (12 sections), Security Audit Checklist (10 sections), CodeReviewer Agent, Documentation Agent, Generic Coding Practices, Java Coder Implementation Guide, MCP Server Patterns, Agent Pipeline (Conductor → Coder → CodeReviewer → Security → Tester) (+20 more)

### Community 5 - "Taxonomy Classification"
Cohesion: 0.15
Nodes (14): Any, _cosine(), HierarchyClassifier, _keywords(), _name_and_extra(), _Node, Product hierarchy classifier — hybrid, taxonomy-aware.  Cheapest-first cascade p, Flatten the taxonomy into match nodes. The catch-all product is skipped. (+6 more)

### Community 6 - "E2E Stub & App Lifecycle"
Cohesion: 0.10
Nodes (23): chat_completions(), _classification_response(), _deterministic_embedding(), embeddings(), _expert_response(), Stub OpenAI-compatible server for E2E testing. Implements /v1/embeddings and /v1, Return a valid JSON index ordering for the reranker prompt.      Echoes identity, Generate a deterministic unit vector from text using MD5 seed. (+15 more)

### Community 7 - "Ingestion Admin API"
Cohesion: 0.11
Nodes (13): Dependency — reject request if admin key is missing or wrong., Trigger a full re-index of all configured Jira projects and Confluence spaces., Trigger an incremental sync — only items updated since last sync watermark., Delete indexed documents that no longer exist at the source.      Safe by design, Return current sync state for all sources., Manually trigger a refresh of all product expert records., _require_admin(), sync_status() (+5 more)

### Community 8 - "Embedding & Chunking"
Cohesion: 0.15
Nodes (17): Batch Embedding, Semantic Chunking, chunks table (embedding+FTS), 3-Stage Hierarchy Classification, Confluence Cursor Pagination, documents table, Embedding Dimension Contract (768), halfvec Quantization (+9 more)

### Community 9 - "Reranker Scoring"
Cohesion: 0.20
Nodes (15): datetime, SearchResult, _authority(), _blended_score(), _freshness(), _llm_rerank(), _parse_order(), Reranker — refines hybrid-search candidates before answer generation.  Two stage (+7 more)

### Community 10 - "E2E Test Script"
Cohesion: 0.38
Nodes (12): assert(), assert_ge(), fail(), info(), ingest(), ok(), psql_q(), qok() (+4 more)

### Community 11 - "Service Configuration"
Cohesion: 0.20
Nodes (6): Return Ollama base URL if configured, otherwise None (→ OpenAI default)., BaseSettings, get_settings(), Settings, get_settings(), Settings

### Community 12 - "HTML Cleaning"
Cohesion: 0.27
Nodes (9): HTML / Text Cleaning, clean_html(), clean_text(), _normalise(), HTML → clean plain text / markdown converter., Convert HTML to clean, readable markdown text., Normalise plain text (strip extra whitespace, blank lines)., Hard-strip all HTML tags — use when markdown conversion isn't needed. (+1 more)

### Community 13 - "Query Expert Repository"
Cohesion: 0.29
Nodes (9): get_expert(), get_experts_for_product(), list_experts(), Query-service read-only repository for product_experts., Return all product expert records., Return a single expert by product (and optional component)., Return all expert records for a given product (product-level + all components)., Any (+1 more)

### Community 14 - "Product Expert Synthesis"
Cohesion: 0.33
Nodes (7): _adf_to_text(), _display_name(), _parse_dt(), Jira REST API v3 client (Jira Cloud — basic auth with email + API token)., Recursively extract plain text from Atlassian Document Format (ADF) JSON., Any, datetime

### Community 16 - "Expert Refresher Module"
Cohesion: 0.40
Nodes (3): ExpertResult, ProductExpertRefresher — synthesises a compressed context entry for each product, Refresh expert records for every distinct product in the index.

### Community 17 - "Java Coding Standards"
Cohesion: 0.50
Nodes (4): Java 25 Coding Conventions, Java Error Handling Guidelines, Java Logging Standards (@Slf4j), Zero Mock Policy (Real Test Doubles)

### Community 20 - "CI/CD Deploy Workflows"
Cohesion: 0.67
Nodes (3): GitHub Actions: Deploy All Services, GitHub Actions: Deploy Ingestion Service, GitHub Actions: Deploy Query Service

## Knowledge Gaps
- **34 isolated node(s):** `Any`, `AsyncSession`, `AsyncSession`, `AsyncSession`, `Exception` (+29 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **11 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `IngestionPipeline` connect `Confluence & Jira Ingestion` to `Embedding & Chunking`, `Taxonomy Classification`, `E2E Stub & App Lifecycle`?**
  _High betweenness centrality (0.170) - this node is a cross-community bridge._
- **Why does `IngestDocumentRequest` connect `Confluence & Jira Ingestion` to `Query API & RAG Answering`, `Taxonomy Classification`, `Ingestion Admin API`?**
  _High betweenness centrality (0.125) - this node is a cross-community bridge._
- **Why does `ChunkRecord` connect `Confluence & Jira Ingestion` to `Data Model & Sync State`?**
  _High betweenness centrality (0.109) - this node is a cross-community bridge._
- **Are the 13 inferred relationships involving `HierarchyClassifier` (e.g. with `IngestDocumentRequest` and `BackgroundTasks`) actually correct?**
  _`HierarchyClassifier` has 13 INFERRED edges - model-reasoned connections that need verification._
- **Are the 13 inferred relationships involving `IngestionPipeline` (e.g. with `IngestDocumentRequest` and `BackgroundTasks`) actually correct?**
  _`IngestionPipeline` has 13 INFERRED edges - model-reasoned connections that need verification._
- **Are the 18 inferred relationships involving `ChunkRecord` (e.g. with `ingest_single_document()` and `IngestDocumentRequest`) actually correct?**
  _`ChunkRecord` has 18 INFERRED edges - model-reasoned connections that need verification._
- **Are the 15 inferred relationships involving `Embedder` (e.g. with `IngestDocumentRequest` and `BackgroundTasks`) actually correct?**
  _`Embedder` has 15 INFERRED edges - model-reasoned connections that need verification._