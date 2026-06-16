---
name: GenericCodingPractices
description: Language-agnostic coding best practices. Referenced by JavaCoder, PythonCoder, and other language agents.
---

# Generic Coding Practices

All coder agents follow these language-agnostic practices. Language-specific patterns are in individual agent files.

---

## Before Writing Anything

1. **Read existing code** — understand patterns, never assume signatures/fields
2. **Check `common/` first** — import if exists, never duplicate
3. **Run tests after every change** — `./mvnw test` (Java) or `pytest` (Python) to confirm zero regressions

---

## Logging Rules (All Languages)

Every class/module must:
1. Include logging at the entry point
2. Prefix every log with `[ClassName]` or `[module_name]`
3. Pass exception as **last argument** to error log
4. Never log credentials, tokens, full diffs at INFO or above
5. Use `debug` level for verbose internal state

```python
# Python example
logger.info("[MyService] Processing PR '%s' risk=%s", pr_id, risk)
logger.error("[MyService] Failed to publish event: %s", e, exc_info=e)
```

```java
// Java example
log.info("[MyService] Processing PR '{}' risk={}", prId, risk);
log.error("[MyService] Failed to publish event: {}", e.getMessage(), e);
```

---

## Error Handling Rules

| Rule | Severity |
|------|----------|
| No silent exception swallowing (`catch (Exception e) {}` or `except: pass`) | BLOCKER |
| Pass exception to logger (last arg) | BLOCKER |
| HTTP/API responses use generic messages (no `e.getMessage()`) | BLOCKER |
| Checked exceptions wrapped only at boundary (controller/Kafka listener) | YES |

```python
# ❌ WRONG
except Exception as e:
    pass

# ✅ CORRECT
except ValueError as ve:
    logger.error("[MyService] Invalid input: %s", e, exc_info=e)
    raise
except Exception as e:
    logger.error("[MyService] Unexpected error: %s", e, exc_info=e)
    raise RuntimeError(f"[MyService] Processing failed") from e
```

---

## Testing Rules — Zero Mocking

Every test uses a **real test double** — a class that extends/overrides only the method under test.

```python
# ✅ CORRECT — real test double
class FixedAnalyzer(E2ECoverageAnalyzer):
    def analyze(self, env):
        return CoverageReport(level=CoverageLevel.NONE)

class TestStrategyAgent:
    def test_low_risk_no_tests_should_create_tests(self):
        agent = StrategyAgent(FixedAnalyzer(), ...)
        decision = agent.decide(build_low_risk_envelope())
        assert decision == StrategyDecision.CREATE_TESTS

# ❌ WRONG — mocking
@patch('module.E2ECoverageAnalyzer')
def test_strategy(mock_analyzer):
    ...
```

---

## Dependency Injection (DI) Rules

**Python:** Use constructor parameters, type hints, never module-level singletons for testability.

```python
# ✅ CORRECT
class MyService:
    def __init__(self, ai_client: AiClient, kafka_template: KafkaTemplate):
        self._ai_client = ai_client
        self._kafka = kafka_template

# ❌ WRONG
AI_CLIENT = AiClient()  # module-level singleton, hard to test

class MyService:
    def process(self):
        AI_CLIENT.complete(...)
```

**Java:** Constructor injection via Lombok (already enforced in SHARED-RULES.md).

---

## Credential Safety (All Languages)

| Location | Rule |
|----------|------|
| Source code (`.py`, `.java`, `.yaml`) | All credentials → environment variables only |
| Shell scripts (`.sh`) | Read from env vars; fail with `[ERROR]` if unset (guard pattern) |
| State files (`.json`) | No tokens, passwords, API keys |
| Git config | Remote URLs must be `https://github.com/...` (no embedded tokens) |
| `.env` file | MUST be in `.gitignore` |

```python
# ❌ CRITICAL
OPENAI_KEY = "sk-abc123"  # in code
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")  # OK

# ✅ CORRECT
OPENAI_KEY = os.getenv("OPENAI_KEY", "")
if not OPENAI_KEY:
    raise RuntimeError("[ERROR] OPENAI_KEY environment variable must be set")
```

---

## Shell Script Safety

Any `.sh` file must follow these rules:

1. **No literal tokens/passwords/API keys** — ever
2. **Read credentials from env vars only**
3. **Guard pattern — fail loudly if required var missing**
4. **Pass env vars by reference**, not as command-line args

```bash
# ✅ CORRECT
for var in GITHUB_TOKEN REPO_URL; do
  [ -z "${!var:-}" ] && echo "[ERROR] $var not set" && exit 1
done
GITHUB_TOKEN="${GITHUB_TOKEN}" python script.py

# ❌ WRONG
GITHUB_TOKEN="ghp_abc123" python script.py  # literal token
python -DTOKEN="${GITHUB_TOKEN}" ...         # token in process args
```

---

## API/HTTP Response Rules

- Never include `e.getMessage()` or stack traces in HTTP responses
- Use generic messages: `"An internal error occurred"` or `"Request processing failed"`
- Log full exception internally at ERROR level with original exception

```python
# ❌ WRONG
return {"error": str(e)}  # leaks internal details

# ✅ CORRECT
logger.error("[MyService] Failed to process: %s", e, exc_info=e)
return {"error": "Request processing failed"}  # generic
```

---

## Immutability & Data Structures

**Python:** Use `dataclasses`, `typing.NamedTuple`, or `pydantic.BaseModel` for immutable DTOs.

```python
from dataclasses import dataclass

@dataclass(frozen=True)
class GitHubPrResult:
    pr_number: int
    url: str
    branch: str
```

**Java:** Use records (Java 25).

---

## Naming Conventions

| Element | Convention | Example |
|---------|-----------|---------|
| Classes/Services | PascalCase | `MyService`, `PrAnalyzer` |
| Functions/Methods | snake_case (Python), camelCase (Java) | `process_pull_request()`, `processPullRequest()` |
| Constants | UPPER_SNAKE_CASE | `MAX_RETRIES = 3`, `KAFKA_TIMEOUT_MS = 5000` |
| Private vars | `_leading_underscore` (Python), private keyword (Java) | `_internal_state`, `private final String internalState` |
| Environment vars | UPPER_SNAKE_CASE | `GITHUB_TOKEN`, `OPENAI_API_KEY` |

---

## Code Organization

**Python:**
```
module/
├── __init__.py
├── config.py        # configuration, env vars
├── client.py        # external API clients
├── service.py       # business logic
├── repository.py    # data access
└── tests/
    ├── conftest.py
    ├── test_service.py
```

**Java:** Package structure (from SHARED-RULES.md).

---

## What All Coders Must NEVER Do

| Forbidden | Reason |
|-----------|--------|
| Hardcode credentials/tokens in any file | Will be caught by secret scanning |
| Hardcode port numbers, topic names, config | Use environment variables + `.env` template |
| Duplicate a class that exists in `common/` | Causes split-brain maintenance |
| Use mocking frameworks (`mock`, `@Mock`, `Mockito`) | Zero-mock policy — use real test doubles |
| Blocking sleeps in tests (`time.sleep()`, `Thread.sleep()`) | Flaky; use `Awaitility` (Java) or polling loops (Python) |
| Silent exception handling (`except: pass`, `catch (Exception e) {}`) | Hides bugs |
| Commit `.env` files or secrets | Must be in `.gitignore` |

---

## Output Expectations

**Python Coder:** Only changed/new files. Docstring on every class/function. Run `pytest` before reporting done.

**Java Coder:** Only changed/new files. One-line Javadoc per public method. Run `./mvnw test` before reporting done.

Both: No prose. Brief change summary only.

