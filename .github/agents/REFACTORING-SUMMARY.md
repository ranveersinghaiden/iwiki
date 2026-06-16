---
name: REFACTORING-SUMMARY
description: Summary of refactoring from single Coder agent to language-specific coders.
---

# Coder Agent Refactoring — Complete ✅

## What Changed

### Before
```
Coder.agent.md (236 lines)
  ├── Java 25 patterns (20 lines)
  ├── Spring Boot patterns (80 lines)
  ├── Kafka/Redis patterns (80 lines)
  ├── Testing rules (30 lines)
  ├── Script safety (30 lines)
  └── Forbidden patterns (20 lines)
```

### After
```
GenericCodingPractices.md (150 lines) ← Language-agnostic
  ├── Before writing anything
  ├── Logging rules
  ├── Error handling
  ├── Testing (zero mocking)
  ├── Dependency injection
  ├── Credential safety
  ├── Shell script safety
  ├── API response rules
  └── Naming conventions

JavaCoder.agent.md (150 lines) ← Java-specific
  ├── Java 25 patterns (10 lines)
  ├── Spring Boot 4 patterns (40 lines)
  ├── Kafka/Redis (30 lines)
  ├── Testing examples (20 lines)
  └── Forbidden patterns (10 lines)
  └── → References GenericCodingPractices.md for common rules

PythonCoder.agent.md (150 lines) ← Python-specific
  ├── Python 3.10+ patterns (30 lines)
  ├── FastAPI patterns (30 lines)
  ├── Async/testing (20 lines)
  ├── Configuration (10 lines)
  └── Forbidden patterns (10 lines)
  └── → References GenericCodingPractices.md for common rules
```

---

## Key Benefits

| Benefit | Impact |
|---------|--------|
| **Language agnostic** | Same logging, error handling, DI rules apply to Java and Python |
| **Reduced duplication** | Zero-mock testing rule in GenericCodingPractices, not repeated |
| **Selective reading** | JavaCoder reader ignores Python-specific content (smaller files) |
| **Easier onboarding** | "New to Java?" → Read JavaCoder + GenericCodingPractices |
| **Easier maintenance** | Update logging rules once in GenericCodingPractices → applies everywhere |
| **Clear separation** | Language-specific (JavaCoder/PythonCoder) vs. cross-language (GenericCodingPractices) |

---

## File Structure Changes

### New Consolidated File
- **GenericCodingPractices.md** (150 lines) — Common practices for all coders

### New Language-Specific Files
- **JavaCoder.agent.md** (150 lines) — Java/Spring Boot patterns
- **PythonCoder.agent.md** (150 lines) — Python/FastAPI patterns

### Renamed
- `Coder.agent.md` → `Coder.agent.md.old` (backup)

### Updated
- **Conductor.agent.md** — Agent Team table now shows JavaCoder + PythonCoder
- **README.md** — Navigation updated for 3 coder files

---

## How Agents Reference Each Other

```
┌─────────────────────────────────────────────────────┐
│                  GenericCodingPractices.md          │
│  (logging, error handling, testing, DI, creds)     │
└──────────────┬──────────────────────┬───────────────┘
               │                      │
        ┌──────▼─────────┐    ┌───────▼────────┐
        │ JavaCoder.md   │    │ PythonCoder.md │
        │ Java patterns  │    │ Python patterns│
        │ Spring Boot    │    │ FastAPI        │
        │ Kafka/Redis    │    │ Async/await    │
        └────────────────┘    └────────────────┘
               │                      │
               └──────────┬───────────┘
                          │
                   CodeReviewer
                   (checks all)
```

Both JavaCoder and PythonCoder:
- **Reference:** GenericCodingPractices.md (common practices)
- **Reference:** SHARED-RULES.md (shell scripts, Kafka/Redis details)
- **Output to:** CodeReviewer (for code review)

---

## When to Use Each File

### GenericCodingPractices.md
"How should I handle errors in my code?" → GenericCodingPractices.md § Error Handling
"What logging pattern should I use?" → GenericCodingPractices.md § Logging Rules
"How do I avoid mocking in tests?" → GenericCodingPractices.md § Testing Rules

### JavaCoder.agent.md
"How do I write a Kafka producer in Java?" → JavaCoder.agent.md § Kafka Producer
"What Spring Boot patterns should I use?" → JavaCoder.agent.md § Spring Boot 4 Patterns
"Show me a Java test example" → JavaCoder.agent.md § Testing

### PythonCoder.agent.md
"How do I write an async endpoint?" → PythonCoder.agent.md § FastAPI Patterns
"What's the Python pattern for DI?" → PythonCoder.agent.md § Dependency Injection
"Show me a Python test example" → PythonCoder.agent.md § Testing

---

## Conductor Integration

Conductor now delegates to language-specific coders:

```
Conductor
├── "JavaCoder, implement [task] in Java module"
│   → JavaCoder.agent.md + GenericCodingPractices.md
│
└── "PythonCoder, implement [task] in Python module"
    → PythonCoder.agent.md + GenericCodingPractices.md
```

Both types of coders then:
1. CodeReviewer audits (uses CHECKLISTS.md)
2. Security audits (uses CHECKLISTS.md + SHARED-RULES.md)
3. Documentation updates

---

## Backward Compatibility

- Old `Coder.agent.md` backed up as `Coder.agent.md.old`
- All references to "Coder" in projects should now specify:
  - "JavaCoder" for Java/Spring Boot code
  - "PythonCoder" for Python code

---

## File Sizes Comparison

| File | Before | After | Change |
|------|--------|-------|--------|
| Coder.agent.md | 236 lines | — | Removed |
| GenericCodingPractices.md | — | 150 lines | New |
| JavaCoder.agent.md | — | 150 lines | New (from Coder) |
| PythonCoder.agent.md | — | 150 lines | New |
| **Total** | **236 lines** | **450 lines** | **+214 lines, but zero duplication** |

**Key:** More lines, but clearer separation. JavaCoder reader won't read Python patterns; PythonCoder reader won't read Java patterns. Total "effective" lines ≈ 150 per reader.

---

## Next Steps

1. **Update project documentation** — Reference JavaCoder or PythonCoder (not Coder)
2. **Update CI/CD pipelines** — Use language-specific agent names
3. **Test the workflow** — Have Java and Python developers use new agents
4. **Archive old Coder.agent.md** — After verification, can delete `Coder.agent.md.old`

---

## Example Conductor Delegations (Updated)

### For Java Development
```
"JavaCoder, implement payment processor in pr-service.
Task: Add X-Admin-Key validation to endpoints.
Reference: JavaCoder.agent.md, GenericCodingPractices.md, SHARED-RULES.md.
Run ./mvnw test -pl pr-service -am and confirm BUILD SUCCESS."
```

### For Python Development
```
"PythonCoder, implement embedding service in ingestion-service.
Task: Add batch embedding endpoint with caching.
Reference: PythonCoder.agent.md, GenericCodingPractices.md, SHARED-RULES.md.
Run pytest and confirm all tests pass."
```

---

## Verification Checklist

- ✅ GenericCodingPractices.md created (150 lines)
- ✅ JavaCoder.agent.md created (150 lines, Java-specific)
- ✅ PythonCoder.agent.md created (150 lines, Python-specific)
- ✅ Both reference GenericCodingPractices.md + SHARED-RULES.md
- ✅ Conductor.agent.md updated (Agent Team + delegation templates)
- ✅ README.md updated (navigation for 3 coder files)
- ✅ Old Coder.agent.md backed up as `.old`
- ✅ No duplication between JavaCoder and PythonCoder
- ✅ All files concise and focused

---

**Refactoring Complete ✅** — Language-specific coders with shared generic practices.

