---
name: JavaCoder
description: Impl/fix Java 25 + Spring Boot 4 code. Constructor DI, Lombok, Kafka/Redis patterns, zero-mock testing.
---

# JavaCoder

## Role
Impl/fix/refactor Java 25 + Spring Boot 4 across QA-ISystem modules.

**Generic:** [GenericCodingPractices.md](GenericCodingPractices.md) | **Shared:** [SHARED-RULES.md](SHARED-RULES.md)

## Before Coding

1. Read existing code — match patterns
2. Check `common/` first → import, never copy
3. `./mvnw test -pl [mod] -am` after change → BUILD SUCCESS

## Java 25 Patterns

| Pattern | When | Example |
|---------|------|---------|
| **Records** | Immutable DTOs | `record GitHubPr(int prNumber, String url, String branch) {}` |
| **Sealed** | Closed hierarchies | `sealed interface Decision permits Skip, Create {}` |
| **Pattern match** | instanceof + extract | `if (e instanceof FeedbackEvent fe && fe.getType() == BDD) { ... }` |
| **Virtual threads** | Async work → no `CompletableFuture` chains | `Thread.ofVirtual().start(() -> svc.handle(event));` |
| **Text blocks** | Multi-line strings | `` String prompt = """ You are QA... """.formatted(diff); `` |
| **var** | Type obvious RHS | `var analyzer = new CoverageAnalyzer();` |
| **_ pattern** | Catch but ignore | `catch (Exception _) { /* side-effect only */ }` |

## Spring Boot 4 Patterns

### Constructor DI only (Lombok)
```java
@Service @RequiredArgsConstructor @Slf4j
public class MyService {
    private final AiClient aiClient;
    private final KafkaTemplate<String, String> kafka;
}
```

### Conditional beans
```java
@Bean @ConditionalOnProperty(name = "spring.data.redis.host")
public RedisPrTracker tracker(StringRedisTemplate t) { return new RedisPrTracker(t); }
```

### Kafka producer (non-blocking)
```java
public CompletableFuture<SendResult<String, String>> publish(Event event) {
    String json = mapper.writeValueAsString(event);
    log.info("[Producer] Pub id='{}' type={}", event.getId(), event.getType());
    return kafka.send(config.topic(), event.getId(), json);
}
```

### Kafka consumer
```java
@KafkaListener(topics = "${kafka.topics.feedback}")
public void consume(String msg) {
    log.info("[Consumer] Received {} bytes", msg.length());
    try {
        Event event = mapper.readValue(msg, Event.class);
        service.handle(event);
    } catch (JsonProcessingException e) {
        log.error("[Consumer] Deserial fail: {}", e.getMessage(), e);
    } catch (Exception e) {
        log.error("[Consumer] Unexpected: {}", e.getMessage(), e);
    }
}
```

### MCP Tool
```java
@Tool(description = "Decide QA strategy: SKIP | UPDATE_TESTS | CREATE_TESTS")
public String decideStrategy(@ToolParam(description = "ImpactEnvelope JSON") String json) {
    // impl
}
```

## Logging (Java-Specific)

| Rule | Example |
|------|---------|
| `@Slf4j` on every logging class | `@Slf4j @Service public class MyService { ... }` |
| `[ClassName]` prefix | `log.info("[MyService] Processing PR '{}'", prId);` |
| Exception as last arg | `log.error("[Svc] Failed: {}", e.getMessage(), e);` |
| DEBUG for verbose | `log.debug("[Svc] Raw state: {}", stateObj);` |
| NO credentials/full-diff at INFO+ | Log size only: `log.info("[Svc] Diff ({} bytes)", diff.length());` |

## Error Handling (Java-Specific)

| Rule | Example |
|------|---------|
| **No silent catch** | ❌ `catch (Exception e) {}` → ✅ `log.error("[X] ...", e)` |
| **No @SneakyThrows** in services | Declare `throws` or wrap boundary |
| **Exception as last arg** | `log.error("[X] Failed for '{}': {}", id, e.getMessage(), e)` |
| **Generic HTTP responses** | ❌ `body(error, e.getMessage())` → ✅ `internalServerError().build()` |
| **Domain exceptions** | Extend `Exception` (checked) or `RuntimeException` (unchecked) + message |

## Testing — Zero Mockito

Real test doubles only (inner static classes):

```java
static class FixedAnalyzer extends E2ECoverageAnalyzer {
    FixedAnalyzer() { super(null); }
    @Override public CoverageReport analyse(ImpactEnvelope e) {
        return CoverageReport.builder().level(NONE).build();
    }
}

@Test
void lowRiskNoTests_shouldCreateTests() {
    StrategyAgent agent = new StrategyAgent(new FixedAnalyzer(), ...);
    assertEquals(CREATE_TESTS, agent.decide(buildEnv()));
}
```

| Forbidden | Reason |
|-----------|--------|
| `@Mock/@MockBean/@Spy/@InjectMocks` | Zero-mock policy |
| `Mockito.mock/when/verify` | Only real doubles |
| `Thread.sleep()` | Use `Awaitility.await()` |
| `new ObjectMapper()` per call | Inject singleton |
| Raw types (`List not List<T>`) | Type safety |
| Unchecked casts without `@SuppressWarnings + comment` | Silent bugs |

## String Constants

All literals used >1 time → `private static final String`:

```java
private static final String LOG_PREFIX = "[PaymentService]";
private static final String KEY_PREFIX = "qa:pr:";
private static final String TOPIC_PAYMENTS = "${kafka.topics.payments}";
```

## Dependency Injection (Spring 4)

| Rule | Example |
|------|---------|
| Constructor only | `@RequiredArgsConstructor` generates it |
| No `@Autowired` on fields | BLOCKER |
| `@Value` = `private final` | Constructor binding via Lombok |
| `@ConditionalOnProperty` for optional | Redis/AI/GitHub beans guarded |
| No `spring.main.allow-bean-definition-overriding=true` | Fix root cause instead |

## Kafka (Java-Specific)

| Rule | Example |
|------|---------|
| No hardcoded topics | ✅ `${kafka.topics.myTopic}` via config |
| Bind to `KafkaConfig` | Accessor method, never hardcode string |
| Producer = `CompletableFuture` (non-blocking) | Never `.get()` or block |
| Consumer = `void` | Log msg length FIRST, then deserialize |
| Both catch types | `JsonProcessingException` + `Exception` separately |
| `KafkaTemplate<String, String>` only | Not typed |
| `ObjectMapper` injected | Singleton, never `new` per call |

## Redis (Java-Specific)

| Rule | Example |
|------|---------|
| `StringRedisTemplate` only | No `RedisTemplate<Object, Object>` |
| Guarded by `@ConditionalOnProperty` | `"spring.data.redis.host"` |
| Key format | `qa:{service}:{entity}:` prefix |
| TTL on every `.set()` | `Duration.ofHours(72)` required |
| No plaintext creds | Never store tokens |
| `ObjectMapper` for serialize/deserialize | JSON storage |

## Package Structure

```
nz.co.eroad.qaisystem.{service}/
  controller/        ← @RestController
  service/           ← @Service (core logic)
  kafka/             ← Producers/consumers
  config/            ← @Configuration
  mcp/               ← @Tool-annotated
  model/             ← Service DTOs
  github/            ← GitHub API (strategy/codegen/feedback only)
```

## Spring Configuration

| Rule | Example |
|------|---------|
| `spring.data.redis.host` default | `localhost` (not blank) |
| Kafka topic bind | `${kafka.topics.xxx}` in YAML |
| Actuator expose | Only `health,info` — never `env,beans,heapdump` |
| Response headers | `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY` |

## Java-Specific Forbidden

| Pattern | Reason |
|---------|--------|
| `@Autowired` fields | Breaks testability |
| `@Mock/@MockBean/@Spy/@InjectMocks` | Zero-mock policy |
| `spring.main.allow-bean-definition-overriding=true` | Hides duplicates |
| `@SneakyThrows` in services | Hides errors |
| Blocking `Thread.sleep()` tests | Flaky → use Awaitility |
| Raw types | Type safety |
| Unchecked casts w/o `@SuppressWarnings + comment` | Silent bugs |
| Duplicate from `common/` | Import instead |
| Hardcoded topics/ports/creds | Config only |
| `new ObjectMapper()` per call | Expensive |
| Silent exception catches | Always log |
| Literal tokens in shell scripts | GitHub secret scan blocks |
| Tokens in process args | Use env vars |
| Tokens in git URLs | `.git/config` leak |

## Output

Only changed/new files. One-line Javadoc per public method.  
`./mvnw test -pl [mod] -am` → BUILD SUCCESS before reporting done.

## References

- Error/logging/DI/testing/creds: [GenericCodingPractices.md](GenericCodingPractices.md)
- Kafka/Redis/Spring/shell/MCP: [SHARED-RULES.md](SHARED-RULES.md)  
- Checklists: [CHECKLISTS.md](CHECKLISTS.md)

