# GitHub Copilot — Workspace Instructions for QA-ISystem

> These instructions apply to **every file** in this repository.
> Agent-mode files in `.github/agents/` add deeper role-specific rules on top.
> Agent pipeline: **Coder** → **CodeReviewer** → **Security** → **Tester** (orchestrated by **Conductor**).

## 🗿 Communication Style — Caveman Mode (always on)

Skill installed: `.agents/skills/caveman/SKILL.md` — **active for every agent response in this repo**.

All agents (Conductor, Coder, CodeReviewer, Security, TestPlanner, Tester) respond in **caveman ultra** mode:
- Drop articles, filler, pleasantries, hedging, conjunctions.
- Abbreviate prose words (DB/auth/config/req/res/fn/impl) — never abbreviate code symbols, function names, API names, error strings.
- Arrows for causality (X → Y). One word when one word enough. Fragments always OK.
- Technical terms, code, API names, CLI commands, error strings: exact, verbatim.
- Code blocks: unchanged.
- Deactivate only for security warnings and irreversible-action confirmations; resume after.
- Off only when user says "stop caveman" or "normal mode".

---

## Project Overview

QA-ISystem is an **autonomous, event-driven QA pipeline** built on:

| Layer | Technology |
|-------|-----------|
| Language | **Java 25** |
| Framework | **Spring Boot 4.0.x** |
| Messaging | **Apache Kafka** (Spring Kafka 3.2) |
| State | **Redis** (`StringRedisTemplate` / `RedisPrTracker`) |
| AI clients | `OpenAiClient` (OpenAI / Azure / Ollama) or `CopilotClient` (GitHub Copilot API) — selected via `aiqa.ai.provider` |
| MCP server | **Spring AI MCP Server** (`spring-ai-starter-mcp-server-webmvc`) |
| Build | Maven 3.9 multi-module |
| Boilerplate | Lombok |

### Module ports

| Module | Port | Role |
|--------|------|------|
| `pr-service` | 8080 | Webhook ingestion |
| `impact-service` | 8081 | Deterministic impact analysis |
| `strategy-service` | 8082 | Strategy + BDD generation |
| `codegen-service` | 8083 | Test code generation + stabilisation |
| `feedback-service` | 8084 | AI rejection feedback loop |
| `common` | — | Shared models, Kafka, Redis, AI clients |

---

## Non-Negotiable Rules

### 1 · Java style
- **Java 25** features are available and preferred: records, sealed classes, pattern matching for switch, unnamed patterns, virtual threads (`Thread.ofVirtual()`).
- Use `var` when the type is already obvious from the right-hand side.
- Prefer **immutable data** — `List.of()`, `Map.of()`, `record` types, `@Builder` with `@Value`.
- All string literals used more than once → `private static final String`.
- No raw types. No unchecked casts without a `@SuppressWarnings("unchecked")` + comment.

### 2 · Spring injection
- **Constructor injection only.** Never `@Autowired` on a field.
- Use `@RequiredArgsConstructor` (Lombok) — it generates the constructor automatically.
- `@Value` fields must be `private final` (use constructor-based `@Value` with Lombok).

### 3 · Logging
- Annotate every class with `@Slf4j` (Lombok).
- Every log message starts with `[ClassName]` so grep works: `log.info("[MyService] ...")`.
- Never log credentials, tokens, or full diff content at INFO or above.
- Use `log.debug` for verbose internal state.

### 4 · Error handling
- Never swallow exceptions silently (`catch (Exception e) {}`).
- Always include the original exception as the last argument to the log call: `log.error("[X] failed: {}", e.getMessage(), e)`.
- Wrap checked exceptions in `RuntimeException` only at the boundary (controller / Kafka listener). Internal methods may declare `throws`.

### 5 · Testing — **zero Mockito policy**
This project has a hard no-mocking rule.
- `@Mock`, `@MockBean`, `@Spy`, `Mockito.mock(...)`, `@InjectMocks` → **forbidden**.
- Write **real test doubles** as inner `static` classes that extend the real class and override only the methods under test.
- Use `@SpringBootTest` with a real application context for integration tests.
- Use JUnit 5 (`@Test`, `@ParameterizedTest`, `@BeforeEach`). No TestNG, no JUnit 4.

### 6 · Conditional beans
- Beans that are optional (require credentials, remote services, or specific infra) **must** use `@ConditionalOnProperty` or `@ConditionalOnMissingBean`.
- Services that must NOT create AI/GitHub/Redis beans unless explicitly enabled must set `aiqa.github.enabled: true` / `aiqa.ai.provider: ...` in their `application.yaml`.

### 7 · Kafka
- Producers use `KafkaTemplate<String, String>` with Jackson serialisation.
- Consumers use `@KafkaListener(topics = "${kafka.topics.xxx}")` — **never hardcode topic names**.
- Consumer methods are `void`, log the raw message first, then deserialise.
- All consumer errors are logged and swallowed (dead-letter queue is a future enhancement).

### 8 · Redis
- Use `StringRedisTemplate` — store serialised JSON strings.
- Redis beans are `@ConditionalOnProperty(name = "spring.data.redis.host")`.
- Key prefix format: `"qa:{service-short}:{entityType}:"`.

### 9 · Spring Boot MCP Server
- Every service that exposes business operations **should** declare `@Tool`-annotated methods.
- Tool descriptions must be self-contained and precise — they are read by AI agents.
- Register tools via `MethodToolCallbackProvider` in a `@Configuration` class.
- See `.github/agents/mcp-server.instructions.md` for full patterns.

### 10 · No secrets in code
- **Never** commit API keys, tokens, passwords, or connection strings.
- All credentials → `${ENV_VAR_NAME:}` placeholders in `application.yaml`.
- `.env` files are in `.gitignore`.

---

## File locations

| What | Where |
|------|-------|
| Shared models | `common/src/main/java/nz/co/eroad/qaisystem/model/` |
| Shared config | `common/src/main/java/nz/co/eroad/qaisystem/config/` |
| Shared services | `common/src/main/java/nz/co/eroad/qaisystem/service/` |
| Kafka config | `common/src/main/java/nz/co/eroad/qaisystem/config/KafkaConfig.java` |
| AI client interface | `common/src/main/java/nz/co/eroad/qaisystem/agent/AiClient.java` |
| AI client config | `common/src/main/java/nz/co/eroad/qaisystem/config/AiClientConfig.java` |
| Per-service app yaml | `{service}/src/main/resources/application.yaml` |

---

## Commit message format

```
type(scope): short description

body (optional, wrap at 72 chars)
```

Types: `feat` | `fix` | `refactor` | `test` | `docs` | `chore` | `ci`
Scope: service name, e.g. `strategy-service`, `common`, `codegen-service`

---

## What Copilot must NOT do

- Add `spring.main.allow-bean-definition-overriding=true` — fix the root cause instead.
- Use `@SneakyThrows` to hide checked exceptions in service/business logic classes.
- Add blocking `Thread.sleep()` — use virtual threads + `Awaitility` in tests.
- Duplicate classes that already exist in `common`.
- Add new Maven dependencies without checking `common/pom.xml` first.
- Hardcode Kafka topic names, Redis key prefixes, or port numbers in Java code.

