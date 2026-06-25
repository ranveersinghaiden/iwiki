import sys, json
from graphify.build import build_from_json
from graphify.cluster import score_all
from graphify.analyze import god_nodes, surprising_connections, suggest_questions
from graphify.report import generate
from pathlib import Path

extraction = json.loads(Path('graphify-out/.graphify_extract.json').read_text(encoding='utf-8'))
detection  = json.loads(Path('graphify-out/.graphify_detect.json').read_text(encoding='utf-8'))
analysis   = json.loads(Path('graphify-out/.graphify_analysis.json').read_text(encoding='utf-8'))

G = build_from_json(extraction)
communities = {int(k): v for k, v in analysis['communities'].items()}
cohesion = {int(k): v for k, v in analysis['cohesion'].items()}
tokens = {'input': extraction.get('input_tokens', 0), 'output': extraction.get('output_tokens', 0)}

labels = {
    0: "Ingestion API & External Clients",
    1: "Expert Query API",
    2: "E2E Test Stubs & Mocks",
    3: "AI Agent Orchestration",
    4: "Content Classification Pipeline",
    5: "Ingestion Document Routes",
    6: "Database Models",
    7: "System Architecture & Data Flow",
    8: "Search Reranking",
    9: "E2E Test Runner",
    10: "App Configuration",
    11: "Confluence API Client",
    12: "Expert Repository",
    13: "Jira API Client",
    14: "Text Chunker",
    15: "Expert Refresher",
    16: "Java Coding Standards",
    17: "Ingestion DB Session",
    18: "Query DB Session",
    19: "MCP Server Config",
    20: "Agent Compression Report",
    21: "Client Init",
    22: "E2E Test Writer",
    23: "Ingestion API Init",
    24: "Ingestion DB Init",
    25: "Ingestion App Init",
    26: "Product Knowledge Map",
    27: "Pipeline Init",
    28: "Query API Init",
    29: "Query DB Init",
    30: "Query App Init",
    31: "RAG Init",
    32: "Search Init",
    33: "Spring Dependency Injection",
    34: "Spring Kafka Patterns",
    35: "Spring Redis Patterns",
}

questions = suggest_questions(G, communities, labels)

report = generate(G, communities, cohesion, labels, analysis['gods'], analysis['surprises'], detection, tokens, '.', suggested_questions=questions)
Path('graphify-out/GRAPH_REPORT.md').write_text(report, encoding='utf-8')
Path('graphify-out/.graphify_labels.json').write_text(json.dumps({str(k): v for k, v in labels.items()}, ensure_ascii=False), encoding='utf-8')
print('Report updated with community labels')

