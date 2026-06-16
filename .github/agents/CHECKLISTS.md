---
name: CHECKLISTS
description: Consolidated review checklists for CodeReviewer and Security agents. Use this file to eliminate duplication in individual agent instructions.
---

# Code Review & Security Checklists

All review and audit checklists consolidated here. CodeReviewer and Security reference specific sections instead of repeating them.

---

## CodeReviewer Checklist (12 sections)

### 1. Java 25 Idioms

| Check | BLOCKER if violated |
|-------|-------------------|
| Records for immutable DTOs | No |
| Sealed classes/interfaces for closed hierarchies | No |
| Pattern matching `switch`/`instanceof` instead of if-else chains | No |
| Virtual threads (`Thread.ofVirtual()`) instead of `CompletableFuture` | No |
| Text blocks (`"""`) for multi-line strings | No |
| `var` when RHS type is obvious | No |
| `List.of()` / `Map.of()` / `Set.of()` for constants | No |
| No raw types | **Yes** |
| No unchecked casts without `@SuppressWarnings + comment` | **Yes** |
| String literals used >1x extracted to `private static final` | No |

### 2. Spring Boot 4 — Dependency Injection

| Check | BLOCKER if violated |
|-------|-------------------|
| Constructor injection only via `@RequiredArgsConstructor` | **Yes** |
| No `@Autowired` on fields or setters | **Yes** |
| `@Value` fields are `private final` | Yes |
| Optional beans guarded by `@ConditionalOnProperty` or `@ConditionalOnMissingBean` | Yes |
| No `spring.main.allow-bean-definition-overriding=true` in YAML | **Yes** |
| No class from `common/` duplicated in service module | **Yes** |
| `@ConfigurationProperties` for multi-property config blocks | No |

### 3. Spring Boot 4 — Bean Lifecycle & Conditionals

| Check | BLOCKER if violated |
|-------|-------------------|
| Redis beans have `@ConditionalOnProperty(name = "spring.data.redis.host")` | Yes |
| AI/GitHub beans have `@ConditionalOnProperty(name = "aiqa.github.enabled", havingValue = "true")` | Yes |
| No `matchIfMissing = true` on credential-backed beans | Yes |
| `@ConfigurationProperties` classes use `@Data @Component` | No |
| No circular dependencies | Yes |

### 4. Logging

| Check | BLOCKER if violated |
|-------|-------------------|
| Every class has `@Slf4j` | Yes |
| Every log message starts with `[ClassName]` | Yes |
| `log.error()` passes exception as last argument | Yes |
| No credentials / tokens / API keys / full diffs logged at INFO+ | **Yes** |
| Verbose state logged at `debug`, not `info` | No |

### 5. Error Handling

| Check | BLOCKER if violated |
|-------|-------------------|
| No silent exception swallowing (`catch (Exception e) {}`) | **Yes** |
| No `@SneakyThrows` in service/business logic | **Yes** |
| Checked exceptions wrapped at controller/Kafka boundary only | Yes |
| Custom exceptions extend `Exception` or `RuntimeException` | No |
| HTTP responses use generic messages (no `e.getMessage()`) | Yes |
| Kafka consumers catch `JsonProcessingException` and `Exception` separately | No |

### 6. Kafka

| Check | BLOCKER if violated |
|-------|-------------------|
| No hardcoded topic names in Java | **Yes** |
| Topics bound via `${kafka.topics.xxx}` | **Yes** |
| Producer returns `CompletableFuture<SendResult<String,String>>` | No |
| Consumer method is `void`; logs raw message length first | No |
| Consumer catches `JsonProcessingException` and `Exception` separately | No |
| `KafkaTemplate<String, String>` used (not typed) | Yes |
| `ObjectMapper` for serialization | No |

### 7. Redis

| Check | BLOCKER if violated |
|-------|-------------------|
| `StringRedisTemplate` used (not generic `RedisTemplate`) | Yes |
| Redis bean guarded by `@ConditionalOnProperty` | Yes |
| Key prefix follows `qa:{service}:{entityType}:` | No |
| TTL set on every `set()` call (no eternal keys) | No |
| No credentials stored as values | **Yes** |
| `ObjectMapper` for serialization | No |

### 8. Testing — Zero Mockito

| Check | BLOCKER if violated |
|-------|-------------------|
| No `@Mock`, `@MockBean`, `@Spy`, `@InjectMocks` | **Yes** |
| No `Mockito.mock()`, `when()`, `verify()` | **Yes** |
| No `Thread.sleep()` (use `Awaitility` instead) | **Yes** |
| Real test doubles as `static` inner classes extending real class | Required |
| JUnit 5 annotations (`@Test`, `@ParameterizedTest`, `@BeforeEach`) | Yes |
| Test names follow `method_givenCondition_expectedOutcome()` | No |
| AssertJ preferred over `Assertions.assertEquals` | No |

### 9. API Design & Controller Layer

| Check | BLOCKER if violated |
|-------|-------------------|
| `@RestControllerAdvice` for exception → HTTP mapping | No |
| `@Valid` on `@RequestBody` with Bean Validation constraints | No |
| `ResponseEntity<T>` with explicit status codes | No |
| Admin endpoints protected with `X-Admin-Key` or Spring Security | Yes |
| No `e.getMessage()` in HTTP responses | Yes |
| Request body size limits configured | No |

### 10. Configuration & Secrets

| Check | BLOCKER if violated |
|-------|-------------------|
| No hardcoded credentials/tokens/passwords in Java/YAML/scripts | **Yes** |
| All credentials as `${ENV_VAR:}` in `application.yaml` | **Yes** |
| No credentials in `.git/config` remote URLs | **Yes** |
| No Kafka topics/ports/strings hardcoded | **Yes** |
| Actuator exposes `health,info` only | Yes |

### 11. Performance & Concurrency

| Check | BLOCKER if violated |
|-------|-------------------|
| No `Thread.sleep()` in production | Yes |
| Async work uses virtual threads or `CompletableFuture` | No |
| No synchronised blocks where virtual threads suffice | No |
| No N+1 patterns | No |
| `ObjectMapper` injected as singleton (not `new` per call) | Yes |

### 12. Code Maintainability

| Check | BLOCKER if violated |
|-------|-------------------|
| Methods > 40 lines decomposed | No (flag only) |
| Public methods have one-line Javadoc | No |
| No commented-out code | No |
| Single responsibility per class | No |
| Package structure: `controller/ service/ kafka/ config/ mcp/ model/ github/` | No |

---

## Security Audit Checklist (10 sections)

### 1. Credential & Secret Safety ⚠️ SCAN EVERYWHERE

| Check | Pass condition |
|-------|--------------|
| No credentials in `.java`, `.yaml`, `.yml`, `.properties` | All tokens/passwords as `${ENV_VAR:}` |
| No credentials in scripts (`.sh`) | Read from env vars; fail with `[ERROR]` if unset |
| No credentials in state/JSON files (`.agents/state/`, `*.json`) | No tokens, API keys, passwords, or URLs with credentials |
| No credentials in documentation (`.md`, `.html`) | Use placeholders like `<your-token>`, `ghp_your_token_here` |
| No credentials in logs | Never log token, key, password, or embedded-token URL |
| No tokens in process arguments | Use `GIT_ASKPASS` or env vars, not `ProcessBuilder` args |
| No credentials in `.git/config` remote URLs | Use `https://github.com/...` (no tokens embedded) |
| `.env` in `.gitignore` | **Required** |
| `docker-compose*.yml` has no hardcoded secrets | Only `${VAR}` references |

**If any secret found:** rate as CRITICAL.

### 2. API Authentication

| Endpoint pattern | Required protection |
|-----------------|-------------------|
| State-mutating ops (`POST`/`PUT`/`DELETE`) on admin paths | `X-Admin-Key` header OR Spring Security |
| Webhook endpoints | HMAC-SHA256 signature verified; fail-secure if secret not configured |
| High-cost triggers (codegen, refresh-context, approve-bdd) | Admin key required |
| Read-only info endpoints | Admin key recommended; at minimum rate-limited |

### 3. Input Validation & Size Limits

| Service | Required limits |
|---------|----------------|
| `pr-service` | `max-request-size=10MB`; `rawDiffContent` max 500 KB |
| All services | `server.tomcat.max-http-form-post-size=10MB` |
| Diff content | Truncate before logging — never log full diff at INFO+ |

### 4. Actuator Exposure

Must restrict to `health,info` only:

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

Never expose: `env`, `beans`, `configprops`, `heapdump`, `threaddump`, `loggers`

### 5. Error Response Sanitisation

- HTTP responses must not include `e.getMessage()`, stack traces, or internal paths
- Use generic messages: `"An internal error occurred"`
- Log full exception internally at ERROR level with original exception arg

### 6. Dependency & CVE Hygiene

- Run `./mvnw dependency:check -Powasp` in CI
- No dependency with CVSS ≥ 7 without documented exception
- Spring Boot version within 2 minor versions of latest stable

### 7. ProcessBuilder / Command Execution

- Always use `List<String>` (not shell string) to prevent injection
- Set `GIT_TERMINAL_PROMPT=0`, `GIT_ASKPASS=echo` to prevent interactive prompts
- Tokens must never appear in process args — use env vars or credential helpers
- Validate all inputs against allowlist before passing to `ProcessBuilder`

### 8. Redis / Kafka Data Security

- Redis keys follow `qa:{service}:{entity}:` — never store plaintext tokens
- Kafka messages must not carry tokens/passwords/full diffs at INFO logs
- Consumer errors log at ERROR but never re-throw raw (avoid DLQ exposure)

### 9. Secure Headers

Every service `application.yaml`:

```yaml
server:
  tomcat:
    response-headers:
      X-Content-Type-Options: nosniff
      X-Frame-Options: DENY
      Referrer-Policy: no-referrer
```

### 10. Temp File Handling

- `Files.createTempFile` followed by `deleteIfExists` in `finally`
- Temp files with prompts/secrets use `PosixFilePermissions.fromString("rw-------")`

---

## Shell Script Security (Special Section)

When reviewing any `.sh` file, explicitly check:

1. No literal assignments: `VAR="ghp_..."`, `TOKEN="sk-..."` → **CRITICAL**
2. No inline credential before command: `TOKEN="secret" java -jar ...` → **CRITICAL**
3. Guard pattern for every required env var:
   ```bash
   for var in VAR1 VAR2; do
     [ -z "${!var:-}" ] && echo "[ERROR] $var not set" && exit 1
   done
   ```
4. Env vars passed by reference to child processes: `TOKEN="${TOKEN}" nohup ...`

---

## Findings Report Format

### CodeReviewer

```
## Code Review Findings — {Module} — {Date}

### Reviewed Files
- `path/to/ChangedFile.java`

### [BLOCKER] <Title>
- File: `path/to/File.java:line`
- Rule: <section.check>
- Issue: one-sentence description
- Fix: concrete code change required

### [MAJOR] <Title>
...

### Summary
- BLOCKER: N | MAJOR: N | MINOR: N | INFO: N
- Status: APPROVED | NEEDS_FIXES
```

### Security

```
## Security Findings — {Module} — {Date}

### [SEVERITY] Finding title
- File: `path/to/File.java:line` (or `scripts/foo.sh`, `.agents/state/status.json`)
- Issue: one-sentence description
- Risk: what an attacker/accidental committer can do
- Fix: concrete remediation (replace with `${ENV_VAR:}`, delete, etc.)
```

---

## Severity Levels

### CodeReviewer

| Level | Definition | Pipeline action |
|-------|-----------|----------------|
| **BLOCKER** | Violates non-negotiable rule (secrets, Mockito, inject, duplicate) | Stop. Return to Coder. Do not forward to Security. |
| **MAJOR** | Wrong Spring/Kafka/Redis pattern, missing error handling | Return to Coder. Forward to Security only after MAJOR fixed. |
| **MINOR** | Style, missing Javadoc, sub-optimal idiom | File and track. Fix in same pass if trivial. |
| **INFO** | Suggestion for improvement | Include in report but do not block. |

### Security

| Level | Definition | Action |
|-------|-----------|--------|
| **CRITICAL** | Credential in any file; secret in git | Block immediately — fix before anything else |
| **HIGH** | Unauthenticated mutating endpoints, fail-open auth bypass | Fix before commit |
| **MEDIUM** | Missing size limits, over-exposed actuator | Fix in same sprint |
| **LOW** | Missing security headers, minor info leak | Next sprint |

---

## What Both Reviewers Must NEVER Do

| Forbidden | Reason |
|-----------|--------|
| Write code directly | Produce findings only — delegate to Coder |
| Run `./mvnw` in CI | Tester's role only |
| Skip any checklist section | Every section applies to every changed file |
| Mark APPROVED with outstanding BLOCKERs/MAJORs | Report them first, then re-review after Coder fixes |
| Forward with outstanding CRITICAL/HIGH | File findings, get Coder to fix, re-review, then forward |

