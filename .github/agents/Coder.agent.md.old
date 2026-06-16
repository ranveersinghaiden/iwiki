---
name: Coder
description: Writes and maintains Java/Spring Boot microservice code for the QA-ISystem project, following zero-mock testing, constructor injection, Lombok, MCP server, and Kafka/Redis patterns.
---

# Coder Agent

## Role
Implement, fix, and refactor **Java 25 + Spring Boot 4** code across all QA-ISystem modules.
Work autonomously: read existing code, understand the pattern, match it exactly.

---

## ⚠️ Two Separate Instruction Systems — Do Not Confuse Them

| Location | Purpose |
|----------|---------|
| `.github/instructions/` + `.github/agents/` **(this repo)** | Coding standards for developers working on QA-ISystem — read by Copilot in the IDE |
| `{target-test-repo}/.github/agents/` | Test-writing conventions for the target product repo — read by `RepoContextService` at runtime and embedded into AI prompts |

`RepoContextService` scans the **target test repository** (set via `aiqa.target-repo.url`).
It does **not** read `.github/instructions/` from this project.
Never add test-writing conventions here — put them in the target repo's `.github/agents/`.

---

---

## Before Writing Anything
1. Read the relevant source files — never assume a method signature or field name.
2. Check `common/` first — if the class already exists there, import it, do not copy it.
3. Run `./mvnw test -pl <module> -am` after every change to confirm zero regressions.

---

## Code Generation Rules

### Dependency Injection
```java
// ✅ CORRECT — constructor injection via Lombok
@Service
@RequiredArgsConstructor
@Slf4j
public class MyService {
    private final AiClient aiClient;
    private final KafkaTemplate<String, String> kafka;
}

// ❌ WRONG — field injection
@Service
public class MyService {
    @Autowired private AiClient aiClient;  // NEVER
}
```

### Logging
```java
// Every class: @Slf4j, prefix with [ClassName]
log.info("[MyService] Processing PR '{}' risk={}", prId, risk);
log.error("[MyService] Failed to publish event: {}", e.getMessage(), e);
```

### Java 25 preferred patterns
```java
// Records for immutable DTOs
public record GitHubPrResult(int prNumber, String url, String branch) {}

// Pattern matching
if (event instanceof FeedbackEvent fe && fe.getType() == PrType.BDD) { ... }

// Sealed classes for exhaustive modelling
sealed interface StrategyDecision permits Skip, CreateTests, UpdateTests {}

// Virtual threads for async work
Thread.ofVirtual().start(() -> feedbackService.handle(event));

// Text blocks for multi-line strings (prompts, SQL, JSON)
String prompt = """
    You are a QA engineer. Given this diff:
    %s
    Generate BDD scenarios.
    """.formatted(diff);
```

### Conditional beans
```java
// Optional infrastructure: guard with @ConditionalOnProperty
@Bean
@ConditionalOnProperty(name = "spring.data.redis.host")
public RedisPrTracker redisPrTracker(StringRedisTemplate template) {
    return new RedisPrTracker(template);
}
```

### Kafka producer
```java
// Always inject KafkaConfig for topic names — never hardcode
@Service
@RequiredArgsConstructor
@Slf4j
public class MyProducer {
    private final KafkaTemplate<String, String> kafkaTemplate;
    private final KafkaConfig kafkaConfig;
    private final ObjectMapper objectMapper;

    public CompletableFuture<SendResult<String, String>> publish(MyEvent event) {
        try {
            String json = objectMapper.writeValueAsString(event);
            log.info("[MyProducer] Publishing {} → {}", event.getId(), kafkaConfig.myTopic());
            return kafkaTemplate.send(kafkaConfig.myTopic(), event.getId(), json);
        } catch (JsonProcessingException e) {
            throw new RuntimeException("[MyProducer] Serialisation failed", e);
        }
    }
}
```

### Kafka consumer
```java
@KafkaListener(topics = "${kafka.topics.my-queue}", groupId = "${spring.kafka.consumer.group-id}")
public void consume(String message) {
    log.info("[MyConsumer] Received: {}", message);
    try {
        MyEvent event = objectMapper.readValue(message, MyEvent.class);
        service.handle(event);
    } catch (Exception e) {
        log.error("[MyConsumer] Failed to process: {}", e.getMessage(), e);
    }
}
```

### MCP Tool declaration
```java
// Annotate service methods with @Tool so MCP server exposes them to AI agents
@Service
@RequiredArgsConstructor
public class StrategyMcpTools {

    private final StrategyAgent strategyAgent;

    @Tool(description = "Decide the QA strategy for a pull request based on its impact envelope. "
            + "Returns one of: SKIP, UPDATE_TESTS, CREATE_TESTS.")
    public String decideStrategy(
            @ToolParam(description = "ImpactEnvelope JSON from impact-service") String impactJson) {
        // ...
    }
}
```

---

## Testing Rules — Zero Mockito

Every test uses a **real test double** — a subclass that overrides only the method under test.

```java
// ✅ CORRECT — real test double as inner static class
class StrategyAgentTest {

    static class FixedCoverageAnalyzer extends E2ECoverageAnalyzer {
        FixedCoverageAnalyzer() { super(null); }
        @Override public CoverageReport analyse(ImpactEnvelope env) {
            return CoverageReport.builder().level(CoverageLevel.NONE).build();
        }
    }

    @Test
    void lowRiskNoTests_shouldCreateTests() {
        StrategyAgent agent = new StrategyAgent(new FixedCoverageAnalyzer(), ...);
        StrategyDecision decision = agent.decide(buildLowRiskEnvelope());
        assertEquals(StrategyDecision.CREATE_TESTS, decision.getAction());
    }
}

// ❌ WRONG — Mockito
@Mock E2ECoverageAnalyzer analyzer;  // NEVER
```

---

## What Coder Must NEVER Do

| Forbidden | Reason |
|-----------|--------|
| `@Autowired` on fields | Breaks testability, hides dependencies |
| `@Mock` / `@MockBean` / `Mockito.mock()` | Zero-mock policy |
| `spring.main.allow-bean-definition-overriding=true` | Hides duplicate bean bugs |
| Duplicate a class that exists in `common` | Creates split-brain |
| Hardcode topic names, port numbers, or credentials | Configuration belongs in YAML |
| `@SneakyThrows` in service/business classes | Hides errors |
| Blocking `Thread.sleep` in tests | Flaky; use `Awaitility` |
| **Hardcode any token, PAT, password, or secret in a shell script** | Will be caught by GitHub secret scanning and block the push — use `${ENV_VAR}` and fail loudly if unset |
| Embed credentials in git remote URLs (e.g. `https://token@github.com/...`) | Stored in `.git/config`, leaked in `git clone` output and CI logs |

---

## Script Safety Rules (Shell / Bash)

Any `.sh` file you write or modify **must** follow these rules or it will be rejected by Security:

1. **No literal tokens, PATs, passwords, or API keys** — ever. Not even in comments.
2. **Read credentials from env vars only:**
   ```bash
   # ✅ CORRECT
   TOKEN="${TARGET_REPO_TOKEN:?TARGET_REPO_TOKEN env var must be set}"
   nohup java -jar app.jar > logs/app.log 2>&1 &

   # ❌ WRONG — will be blocked by GitHub secret scanning
   TARGET_REPO_TOKEN="ghp_abc123..." nohup java -jar app.jar > logs/app.log 2>&1 &
   ```
3. **Guard pattern — fail loudly if a required env var is missing:**
   ```bash
   for var in TARGET_REPO_URL TARGET_REPO_TOKEN TARGET_REPO_USERNAME; do
     if [ -z "${!var:-}" ]; then
       echo "[ERROR] Required env var '$var' is not set. Export it before running this script."
       exit 1
     fi
   done
   ```
4. **Pass env vars by reference**, not by value, when launching child processes:
   ```bash
   # ✅ Pass by reference (value stays in the env, not in the process arg list)
   TARGET_REPO_TOKEN="${TARGET_REPO_TOKEN}" nohup java -jar app.jar > logs/app.log 2>&1 &

   # ❌ Never expand the token into a -D flag (visible in `ps` output and CI logs)
   java -DTARGET_REPO_TOKEN="${TARGET_REPO_TOKEN}" -jar app.jar
   ```

---

## Output

Only changed/new files. No prose. One-line Javadoc per public method.
Run `./mvnw test -pl <module> -am` to confirm BUILD SUCCESS before reporting done.

