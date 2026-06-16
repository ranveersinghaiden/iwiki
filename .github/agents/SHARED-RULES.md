---
name: SHARED-RULES
description: Non-negotiable constraints, coding standards, and patterns shared across all agents. Reference this file from individual agent instructions to eliminate duplication.
---

# Shared Rules & Standards

All agents follow these non-negotiable rules. Reference this file instead of repeating constraints in individual agent instructions.

---

## ⚠️ Two Instruction Systems

| Location | Purpose |
|----------|---------|
| `.github/instructions/` + `.github/agents/` **(this repo)** | Coding standards for QA-ISystem developers (read by Copilot in IDE) |
| `{target-repo}/.github/agents/` | Test conventions for target product (read by `RepoContextService` at runtime) |

**Never duplicate:** Do not add test conventions to this repo — put them in the target repo's `.github/agents/`.

---

## Non-Negotiable Constraints

| Constraint | Reason |
|-----------|--------|
| **Java 25 only** | Records, sealed classes, pattern matching, virtual threads mandatory |
| **Spring Boot 4.0.x** | Constructor injection via `@RequiredArgsConstructor` only |
| **Zero Mockito** | No `@Mock`, `@MockBean`, `@Spy`, `@InjectMocks`, `Mockito.mock()` anywhere |
| **No field injection** | `@Autowired` on fields → BLOCKER |
| **No secrets in code** | All credentials → `${ENV_VAR:}` placeholders or env vars from code |
| **No hardcoded topics/ports** | Bind via config: `${kafka.topics.xxx}`, `${server.port:}` |
| **Check `common/` first** | Never duplicate a class that exists in `common/` module |
| **Constructor injection only** | Use Lombok `@RequiredArgsConstructor`; never field injection |
| **`@Slf4j` prefix required** | Every log: `log.info("[ClassName] message")` |
| **`@ConditionalOnProperty`** | Guard optional beans (AI, Redis, GitHub) |
| **No `@SneakyThrows`** | In services/business logic, declare `throws` or wrap at boundary |

---

## Java 25 Patterns (All Code Must Use)

```java
// Records for immutable DTOs
public record GitHubPrResult(int prNumber, String url, String branch) {}

// Pattern matching
if (event instanceof FeedbackEvent fe && fe.getType() == PrType.BDD) { ... }

// Sealed classes for closed type hierarchies
sealed interface StrategyDecision permits Skip, CreateTests, UpdateTests {}

// Virtual threads for async work
Thread.ofVirtual().start(() -> feedbackService.handle(event));

// Text blocks for multi-line strings
String prompt = """
    You are a QA engineer. Given this diff:
    %s
    Generate BDD scenarios.
    """.formatted(diff);

// Immutable collections
private static final List<String> TOPICS = List.of("topic1", "topic2");

// Use `var` when type is obvious
var results = analyzer.getMetrics();  // type is clear from RHS

// No raw types
List<String> items = new ArrayList<>();  // not: List items = ...
```

---

## Logging Rules

Every class must:
1. Annotate with `@Slf4j` (Lombok)
2. Prefix every log with `[ClassName]`: `log.info("[MyService] message")`
3. Pass exception as **last argument**: `log.error("[X] failed: {}", e.getMessage(), e)`
4. Never log credentials, tokens, full diffs at INFO or above
5. Use `log.debug` for verbose internal state

```java
// ✅ CORRECT
log.info("[MyService] Processing PR '{}' risk={}", prId, risk);
log.error("[MyService] Failed to publish event: {}", e.getMessage(), e);

// ❌ WRONG
log.info("Processing PR");
log.error("[X] failed: {}", e.getMessage());  // missing exception arg
log.info("[X] Using token: {}", token);  // credentials in log
```

---

## Dependency Injection (Spring Boot 4)

```java
// ✅ CORRECT — constructor injection only
@Service
@RequiredArgsConstructor
@Slf4j
public class MyService {
    private final AiClient aiClient;
    private final KafkaTemplate<String, String> kafka;
}

// ❌ WRONG — field injection
@Autowired private AiClient aiClient;
```

### Optional Beans

```java
// Guard with @ConditionalOnProperty
@Bean
@ConditionalOnProperty(name = "spring.data.redis.host")
public RedisPrTracker redisPrTracker(StringRedisTemplate template) {
    return new RedisPrTracker(template);
}
```

---

## Kafka Patterns

### Producer
- Inject `KafkaTemplate<String, String>` (typed templates forbidden)
- Inject `KafkaConfig` for topic names (never hardcode)
- Return `CompletableFuture<SendResult<String, String>>` (non-blocking)
- Serialize via `ObjectMapper`

```java
String json = objectMapper.writeValueAsString(event);
kafkaTemplate.send(kafkaConfig.myTopic(), event.getId(), json);
```

### Consumer
- Bind topic via `${kafka.topics.xxx}` in `@KafkaListener`
- Log raw message length **first**, then deserialize
- Catch `JsonProcessingException` and `Exception` separately
- Producer method is `void`

```java
@KafkaListener(topics = "${kafka.topics.my-queue}")
public void consume(String message) {
    log.info("[MyConsumer] Received ({} bytes)", message.length());
    try {
        var event = objectMapper.readValue(message, MyEvent.class);
        service.handle(event);
    } catch (JsonProcessingException jpe) {
        log.error("[MyConsumer] Deserialization failed: {}", jpe.getMessage(), jpe);
    } catch (Exception e) {
        log.error("[MyConsumer] Processing failed: {}", e.getMessage(), e);
    }
}
```

---

## Redis Patterns

- Use `StringRedisTemplate` only (not `RedisTemplate<Object, Object>`)
- Bean guarded by `@ConditionalOnProperty(name = "spring.data.redis.host")`
- Key prefix: `qa:{service-short}:{entityType}:`
- Always set TTL (no eternal keys)
- Serialize/deserialize via `ObjectMapper`

```java
template.opsForValue().set(KEY_PREFIX + branch, json, Duration.ofHours(72));
```

---

## Error Handling

| Rule | Severity |
|------|----------|
| No silent exception swallowing (`catch (Exception e) {}`) | BLOCKER |
| No `@SneakyThrows` in services | BLOCKER |
| Pass exception as last arg to log | BLOCKER |
| HTTP responses use generic messages (no `e.getMessage()`) | BLOCKER |
| Checked exceptions wrapped at controller/Kafka boundary only | YES |

```java
// ❌ WRONG
catch (Exception e) {}
log.error("[X] failed: {}", e.getMessage());
return ResponseEntity.badRequest().body(Map.of("error", e.getMessage()));

// ✅ CORRECT
log.error("[X] failed: {}", e.getMessage(), e);
return ResponseEntity.internalServerError().build();
```

---

## Testing — Zero Mockito

Every test uses a **real test double** — inner static class extending the real class:

```java
static class FixedAiClient extends OpenAiClient {
    FixedAiClient(String response) { super(null); this.response = response; }
    @Override public String complete(String sys, String user) { return response; }
}

@Test
void lowRiskNoTests_shouldCreateTests() {
    StrategyAgent agent = new StrategyAgent(new FixedAiClient("tests needed"), ...);
    assertThat(agent.decide(env)).isEqualTo(StrategyDecision.CREATE_TESTS);
}
```

**Never:**
- `@Mock`, `@MockBean`, `@Spy`, `@InjectMocks`
- `Mockito.mock()`, `Mockito.when()`, `Mockito.verify()`
- `Thread.sleep()` — use `await().atMost(...).until(...)`
- JUnit 4 — use JUnit 5 only (`@Test`, `@ParameterizedTest`, `@BeforeEach`)

---

## Shell Script Safety

Any `.sh` file must pass Security review:

1. **No literal tokens/passwords/API keys** — ever (GitHub secret scanning blocks push)
2. **Read credentials from env vars only**
3. **Guard pattern — fail loudly if required var missing**
4. **Pass env vars by reference**, not as JVM flags

```bash
# ✅ CORRECT
for var in TARGET_REPO_TOKEN TARGET_REPO_URL; do
  [ -z "${!var:-}" ] && echo "[ERROR] $var not set" && exit 1
done
TARGET_REPO_TOKEN="${TARGET_REPO_TOKEN}" nohup java -jar app.jar > logs/app.log 2>&1 &

# ❌ WRONG
TARGET_REPO_TOKEN="ghp_abc123..." java -jar app.jar  # literal token
java -DTARGET_REPO_TOKEN="${TOKEN}" -jar app.jar     # token in process args
```

---

## Credential Safety (Code, Scripts, State Files)

| Location | Rule |
|----------|------|
| `.java` files | All credentials → `${ENV_VAR:}` or fetched from env at runtime |
| `.yaml` / `.properties` | All credentials → `${ENV_VAR:}` placeholders |
| `.sh` scripts | Read from env vars only; fail with `[ERROR]` if unset |
| `.json` state files | No tokens, passwords, or URLs containing credentials |
| `.git/config` | Remote URLs must be `https://github.com/...` (no embedded tokens) |
| `.env` file | MUST be in `.gitignore` |

**If any secret found:** rate as CRITICAL and replace immediately.

```bash
# ❌ CRITICAL
OPENAI_KEY="sk-abc123"  # in code or script
ghc_abc123xyz  # GitHub token in state file
https://ghp_token@github.com/repo.git  # in git config
```

---

## MCP Tool Declaration

Annotate service methods with `@Tool` so MCP server exposes to AI agents:

```java
@Service
@RequiredArgsConstructor
public class StrategyMcpTools {
    @Tool(description = "Decide QA strategy. Returns: SKIP | UPDATE_TESTS | CREATE_TESTS")
    public String decideStrategy(
            @ToolParam(description = "ImpactEnvelope JSON") String impactJson) {
        // ...
    }
}
```

---

## Actuator Security

Every service `application.yaml` must restrict actuator exposure:

```yaml
management:
  endpoints:
    web:
      exposure:
        include: health,info
  endpoint:
    health:
      show-details: never
```

`env`, `beans`, `configprops`, `heapdump`, `threaddump`, `loggers` must **never** be exposed.

---

## What Coder Must NEVER Do

| Forbidden | Reason |
|-----------|--------|
| `@Autowired` on fields | Breaks testability |
| `@Mock` / `@MockBean` / `Mockito.mock()` | Zero-mock policy |
| `spring.main.allow-bean-definition-overriding=true` | Hides duplicate bean bugs |
| Duplicate class from `common/` | Creates split-brain |
| Hardcode topic names, port numbers, credentials | Use YAML config |
| `@SneakyThrows` in services | Hides errors |
| Blocking `Thread.sleep()` in tests | Use `Awaitility` |
| Hardcode token in shell script | Will be caught by GitHub secret scanning |
| Embed credentials in git remote URLs | Leaked in logs |

