# Redis Conventions
# Scope: ALL generated code (shared across API / UI / Mobile test types)

## Core Rules

1. Use **`StringRedisTemplate`** only — store values as serialised JSON strings.
2. Redis beans must be guarded with `@ConditionalOnProperty(name = "spring.data.redis.host")`.
3. Key prefix format: `"qa:{service-short}:{entityType}:{id}"`.
4. Always set a TTL when writing keys that should not persist forever.

---

## `application.yaml` — Redis Config

```yaml
spring:
  data:
    redis:
      host: ${REDIS_HOST:localhost}  # default to localhost for local dev
      port: ${REDIS_PORT:6379}
```

> **Important:** `host` must default to `localhost`, NOT blank. Spring Boot 4 throws
> `'host' must not be empty` if `REDIS_HOST` is unset and the default is empty.

---

## Key Naming Convention

```
qa:{service-short}:{entityType}:{identifier}
```

| Service | entityType | Example key |
|---------|-----------|-------------|
| `strategy-service` | `pr` | `qa:pr:bdd:feature/payments-42` |
| `codegen-service` | `pr` | `qa:pr:test:feature/payments-42` |
| `feedback-service` | `feedback` | `qa:feedback:event:PR-001` |

---

## `RedisPrTracker` Pattern

```java
@Service
@RequiredArgsConstructor
@Slf4j
@ConditionalOnProperty(name = "spring.data.redis.host")
public class RedisPrTracker implements PrTracker {

    private static final String KEY_PREFIX = "qa:pr:";
    private static final long   TTL_HOURS  = 72;

    private final StringRedisTemplate template;
    private final ObjectMapper objectMapper;

    @Override
    public void trackBdd(String branchName, int prNumber, BddScenario scenario) {
        String key = KEY_PREFIX + branchName;
        try {
            PrRecord record = PrRecord.builder()
                    .branchName(branchName)
                    .prNumber(prNumber)
                    .type(PrType.BDD)
                    .bddScenario(objectMapper.writeValueAsString(scenario))
                    .build();
            template.opsForValue().set(key, objectMapper.writeValueAsString(record),
                    Duration.ofHours(TTL_HOURS));
            log.info("[RedisPrTracker] Tracked BDD PR branch='{}' prNumber={}", branchName, prNumber);
        } catch (JsonProcessingException e) {
            log.error("[RedisPrTracker] Failed to track BDD PR '{}': {}", branchName, e.getMessage(), e);
        }
    }

    @Override
    public Optional<PrRecord> findByBranch(String branchName) {
        String raw = template.opsForValue().get(KEY_PREFIX + branchName);
        if (raw == null) return Optional.empty();
        try {
            return Optional.of(objectMapper.readValue(raw, PrRecord.class));
        } catch (JsonProcessingException e) {
            log.error("[RedisPrTracker] Deserialisation failed for branch '{}': {}", branchName, e.getMessage(), e);
            return Optional.empty();
        }
    }

    @Override
    public void remove(String branchName) {
        template.delete(KEY_PREFIX + branchName);
        log.info("[RedisPrTracker] Removed PR tracker entry for branch='{}'", branchName);
    }
}
```

---

## `InMemoryPrTracker` — Default (no Redis)

```java
@Service
@ConditionalOnMissingBean(RedisPrTracker.class)
@Slf4j
public class InMemoryPrTracker implements PrTracker {

    private final ConcurrentHashMap<String, PrRecord> store = new ConcurrentHashMap<>();

    @Override
    public void trackBdd(String branchName, int prNumber, BddScenario scenario) {
        store.put(branchName, PrRecord.builder()
                .branchName(branchName).prNumber(prNumber)
                .type(PrType.BDD).build());
        log.info("[InMemoryPrTracker] Tracked BDD branch='{}' (in-memory)", branchName);
    }

    // ... other PrTracker methods
}
```

---

## When to Use Redis vs In-Memory

| Scenario | Use |
|----------|-----|
| Local development, single pod | `InMemoryPrTracker` (default — no infra needed) |
| Kubernetes / multi-pod / pod restarts | `RedisPrTracker` (set `REDIS_HOST`) |
| Docker Compose production | `RedisPrTracker` (Redis service in `docker-compose.prod.yml`) |

