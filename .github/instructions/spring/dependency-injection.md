# Spring Boot Dependency Injection & Bean Conventions
# Scope: ALL generated code (shared across API / UI / Mobile test types)

## Constructor Injection — Mandatory

Field injection with `@Autowired` is **forbidden**. Always use constructor injection
via `@RequiredArgsConstructor` (Lombok).

```java
// ✅ CORRECT
@Service
@RequiredArgsConstructor
@Slf4j
public class BddGenerator {
    private final AiClient aiClient;
    private final RepoContextService repoContextService;
    private final TestPrService testPrService;
}

// ❌ WRONG — field injection
@Service
public class BddGenerator {
    @Autowired private AiClient aiClient;          // NEVER
    @Autowired private RepoContextService context;  // NEVER
}
```

---

## Bean Declaration Priority

1. **`@Service` / `@Component` / `@Repository`** — for singleton application beans
2. **`@Bean` in `@Configuration`** — for infrastructure or third-party beans
3. **`@ConditionalOnProperty` / `@ConditionalOnMissingBean`** — for optional beans

---

## Optional Beans — `@ConditionalOnProperty`

Any bean that requires credentials, external infrastructure, or optional config
**must** be guarded with a condition:

```java
// ✅ Redis — only create if host is configured
@Bean
@ConditionalOnProperty(name = "spring.data.redis.host")
public RedisPrTracker redisPrTracker(StringRedisTemplate template) {
    return new RedisPrTracker(template);
}

// ✅ GitHub / AI — only in services that explicitly opt in
@Service
@ConditionalOnProperty(name = "aiqa.github.enabled", havingValue = "true", matchIfMissing = false)
public class GitHubService { ... }

@Configuration
@ConditionalOnProperty(name = "aiqa.github.enabled", havingValue = "true", matchIfMissing = false)
public class AiClientConfig { ... }
```

### `matchIfMissing` guide

| Value | Effect |
|-------|--------|
| `matchIfMissing = false` (default) | Bean NOT created when property is absent → safe for credentials |
| `matchIfMissing = true` | Bean IS created when property is absent → for features ON by default |

---

## `@ConditionalOnMissingBean` — Default Implementations

Use when a module provides a default that can be replaced:

```java
// Default: in-memory (no infra required)
@Bean
@ConditionalOnMissingBean(RedisPrTracker.class)
public InMemoryPrTracker inMemoryPrTracker() {
    return new InMemoryPrTracker();
}

// Override: Redis-backed (only when Redis is configured)
@Bean
@ConditionalOnProperty(name = "spring.data.redis.host")
public RedisPrTracker redisPrTracker(StringRedisTemplate template) {
    return new RedisPrTracker(template);
}
```

---

## `@ConfigurationProperties`

Bind a whole prefix block from `application.yaml` to a typed class:

```java
@ConfigurationProperties(prefix = "aiqa.ai")
@Data
@Component
public class AiProviderProperties {
    /** "openai" or "copilot" */
    private String provider = "openai";

    private OpenAiConfig openai = new OpenAiConfig();
    private CopilotConfig copilot = new CopilotConfig();

    @Data
    public static class OpenAiConfig {
        private String apiKey   = "";
        private String baseUrl  = "https://api.openai.com";
        private String model    = "gpt-4o";
    }

    @Data
    public static class CopilotConfig {
        private String token   = "";
        private String baseUrl = "https://api.githubcopilot.com";
        private String model   = "gpt-4o";
    }

    public boolean isOpenAi()  { return "openai".equalsIgnoreCase(provider); }
    public boolean isCopilot() { return "copilot".equalsIgnoreCase(provider); }
}
```

Corresponding `application.yaml`:
```yaml
aiqa:
  ai:
    provider: ${AI_PROVIDER:openai}
    openai:
      api-key:  ${OPENAI_API_KEY:}
      base-url: ${OPENAI_BASE_URL:https://api.openai.com}
      model:    ${OPENAI_MODEL:gpt-4o}
    copilot:
      token:    ${GITHUB_COPILOT_TOKEN:}
      base-url: ${COPILOT_BASE_URL:https://api.githubcopilot.com}
      model:    ${COPILOT_MODEL:gpt-4o}
```

---

## Never Duplicate Beans

If a bean is already defined in `common/`, import it — never copy it:

```java
// ❌ WRONG — copies AiClient from common into strategy-service
package nz.co.eroad.qaisystem.agent;  // in strategy-service
public interface AiClient { ... }     // already exists in common!

// ✅ CORRECT — import from common
import nz.co.eroad.qaisystem.agent.AiClient;
```

Duplicate beans with the same name cause `BeanDefinitionOverrideException` on startup.
The fix is always to remove the duplicate, never to add `spring.main.allow-bean-definition-overriding=true`.

