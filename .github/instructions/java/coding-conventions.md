# Java 25 Coding Conventions
# Scope: ALL generated code (shared across API / UI / Mobile test types)

---

## ⚠️ Two Separate Instruction Systems — Do Not Confuse Them

This project has two distinct places where instructions/conventions live.
They serve completely different purposes and must **never** be mixed.

| Location | Purpose | Read by |
|----------|---------|---------|
| `.github/instructions/` and `.github/agents/` (this repo) | **Local development** — coding standards, Copilot guidance, Spring Boot / Java / MCP conventions for developers working on QA-ISystem itself | GitHub Copilot in the IDE, Copilot CLI via `mcp.json` |
| `{target-test-repo}/.github/agents/` | **Test generation context** — conventions for how tests should be written in the target test repository (e.g. base classes, naming, assertion style) | `RepoContextService` at runtime — these files are embedded into AI prompts when generating BDD scenarios and test code |

**`RepoContextService`** clones the **target test repository** (configured via `aiqa.target-repo.url`) and scans *that repo's* `.github/agents/` directory. It has no knowledge of and no connection to the `.github/instructions/` folder in the QA-ISystem project.

If you want to influence how tests are generated for a target product, add convention files to `.github/agents/` **in the target test repo** — not here.

---

## Language Version — Java 25

Prefer modern Java features over older idioms:

| Feature | When to use |
|---------|------------|
| **Records** | Immutable data carriers, DTOs passed between services |
| **Sealed classes** | Closed type hierarchies (e.g. `StrategyDecision`, `FeedbackType`) |
| **Pattern matching** | `instanceof` checks, `switch` expressions over types |
| **Virtual threads** (`Thread.ofVirtual()`) | Non-blocking async work — replaces `CompletableFuture` chains |
| **Text blocks** (`"""`) | Multi-line AI prompts, JSON payloads, SQL, HTML templates |
| **`var`** | When the type is obvious from the right-hand side |
| **`_` unnamed patterns** | `catch (Exception _)` when only the side-effect matters |

```java
// Records — immutable, compiler-generated equals/hashCode/toString
public record ImpactEnvelope(String prId, RiskLevel riskLevel, double score) {}

// Sealed classes — exhaustive at compile time
sealed interface StrategyDecision
    permits StrategyDecision.Skip, StrategyDecision.CreateTests, StrategyDecision.UpdateTests {
    record Skip(String reason) implements StrategyDecision {}
    record CreateTests(String prId) implements StrategyDecision {}
    record UpdateTests(String prId, List<String> targets) implements StrategyDecision {}
}

// Pattern matching switch
String label = switch (decision) {
    case StrategyDecision.Skip s       -> "SKIP: " + s.reason();
    case StrategyDecision.CreateTests c -> "CREATE";
    case StrategyDecision.UpdateTests u -> "UPDATE (" + u.targets().size() + ")";
};

// Virtual threads — lightweight, no thread-pool configuration needed
Thread.ofVirtual().start(() -> feedbackService.handleRejection(event));

// Text blocks — for AI prompts
String prompt = """
        You are a senior QA engineer. Given this pull request diff:
        %s

        Generate Gherkin BDD scenarios covering happy path, edge cases, and error paths.
        Output only valid Gherkin syntax starting with 'Feature:'.
        """.formatted(diff);
```

---

## Immutable vs Mutable Models

```java
// ── Immutable (no setters, no Spring/Jackson mutability needed) ──────────────
// Use Java record
public record GitHubPrResult(int prNumber, String url, String branch) {}
// Access via: result.prNumber()  result.url()  result.branch()  (NO get prefix)

// ── Mutable DTO (Jackson deserialization, Spring @ConfigurationProperties) ────
// Use Lombok @Data @Builder
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class PrRecord {
    private String branchName;
    private int    prNumber;
    private PrType type;        // enum
    private String bddScenario;
    private String testScript;
}
// Access via: record.getBranchName()  record.getPrNumber()  (standard Lombok getters)
```

> **Rule:** Java record accessors have NO `get` prefix. Lombok `@Data` getters DO have `get`.
> Mixing these up causes `NoSuchMethodError` at runtime — always check which you are using.

---

## Lombok Annotations

| Annotation | Use case |
|-----------|---------|
| `@Slf4j` | Every class that needs logging |
| `@RequiredArgsConstructor` | Service/component — generates constructor for all `private final` fields |
| `@Data` | Mutable DTOs, `@ConfigurationProperties` classes |
| `@Builder` | Classes constructed in a builder pattern (tests, producers) |
| `@Value` | Fully immutable value objects — all fields `private final` |
| `@AllArgsConstructor` | Only when every field must be set via constructor |
| `@NoArgsConstructor` | Required alongside `@AllArgsConstructor` for Jackson deserialization |

---

## String Constants

All string literals used more than once → `private static final String`:

```java
private static final String LOG_PREFIX  = "[PaymentService]";
private static final String TOPIC_KEY   = "kafka.topics.payments";
private static final String CACHE_KEY   = "qa:pr:payments:";
```

---

## Package Structure (per service)

```
nz.co.eroad.qaisystem.{service-short}/
  controller/     ← @RestController classes
  service/        ← @Service (core business logic)
  kafka/          ← Kafka producers and consumers
  config/         ← @Configuration, @ConfigurationProperties
  mcp/            ← @Tool-annotated classes for MCP server
  model/          ← service-local DTOs (prefer classes from common/ where they exist)
  github/         ← GitHub API integration (only strategy/codegen/feedback)
```

---

## Forbidden Patterns

| Pattern | Replace with |
|---------|-------------|
| `@Autowired` on fields | `@RequiredArgsConstructor` (constructor injection) |
| `Mockito.mock()` / `@Mock` / `@MockBean` | Real test double inner static class |
| `Thread.sleep()` in tests | `Awaitility.await().atMost(...)` |
| Hardcoded topic names / port numbers | `@Value("${kafka.topics.xxx}")` / `application.yaml` |
| `spring.main.allow-bean-definition-overriding=true` | Fix the duplicate bean root cause |
| Duplicate class from `common/` | Import from `common` — never copy |
| `@SneakyThrows` in service/business classes | Declare `throws` or wrap at the boundary |

