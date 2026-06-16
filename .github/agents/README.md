---
name: AGENT-INSTRUCTIONS-GUIDE
description: Quick navigation for all agent instruction files after compression and consolidation.
---

# Agent Instructions — Quick Navigation

All agents in this directory work together using consolidated standards files. Use this guide to find what you need.

---

## 📋 Consolidated Standards (Read These First)

### [SHARED-RULES.md](SHARED-RULES.md) — 380 lines
**What:** All cross-cutting coding standards that apply to everyone (Coder, CodeReviewer, Security).

**Contains:**
- Two Instruction Systems explanation
- 14 Non-Negotiable Constraints
- Java 25 patterns (records, sealed, pattern matching, virtual threads, text blocks)
- Dependency Injection (Spring Boot 4, constructor injection only)
- Logging rules (`@Slf4j`, `[ClassName]` prefix)
- Kafka patterns (producers, consumers, topic binding)
- Redis patterns (`StringRedisTemplate`, key formats, TTL)
- Error handling (no silent catches, exception as last arg)
- Testing — Zero Mockito (real test doubles only)
- Shell script safety (env vars, guard pattern, credential handling)
- Credential safety (code, YAML, scripts, state files, git remotes)
- MCP tool declaration
- Actuator security

**When to use:**
- Coder: Reference for any coding question
- CodeReviewer: Reference for checking code against standards
- Security: Reference for checking credentials/shell scripts

---

### [CHECKLISTS.md](CHECKLISTS.md) — 360 lines
**What:** All review & security audit checklists, severity levels, findings formats.

**Contains:**

#### CodeReviewer Checklist (12 sections, ~150 lines)
1. Java 25 Idioms (10 checks)
2. Spring Boot 4 — Dependency Injection (7 checks)
3. Spring Boot 4 — Bean Lifecycle & Conditionals (5 checks)
4. Logging (5 checks)
5. Error Handling (6 checks)
6. Kafka (7 checks)
7. Redis (6 checks)
8. Testing — Zero Mockito (8 checks)
9. API Design & Controller Layer (6 checks)
10. Configuration & Secrets (5 checks)
11. Performance & Concurrency (5 checks)
12. Code Maintainability (5 checks)

Each section lists: Check | BLOCKER if violated? | (guidance)

#### Security Audit Checklist (10 sections, ~150 lines)
1. Credential & Secret Safety (9 checks)
2. API Authentication (4 checks)
3. Input Validation & Size Limits (4 checks)
4. Actuator Exposure (1 check w/ yaml config)
5. Error Response Sanitisation (3 checks)
6. Dependency & CVE Hygiene (3 checks)
7. ProcessBuilder / Command Execution (4 checks)
8. Redis / Kafka Data Security (3 checks)
9. Secure Headers (1 check w/ yaml config)
10. Temp File Handling (2 checks)

Plus: **Shell Script Security** (special section: 4 explicit checks)

#### Severity Levels (20 lines)
- CodeReviewer: BLOCKER | MAJOR | MINOR | INFO
- Security: CRITICAL | HIGH | MEDIUM | LOW

#### Findings Report Format (20 lines)
- CodeReviewer findings template
- Security findings template

**When to use:**
- CodeReviewer: Run all 12 sections on every changed file
- Security: Run all 10 sections + shell script section on every changed file
- Conductor: Reference when delegating to CodeReviewer / Security

---

## 🎭 Agent Instructions (Role-Specific Workflows)

### [Conductor.agent.md](Conductor.agent.md) — 263 lines
**Role:** Orchestrate feature delivery. Break tasks down, delegate to specialists, enforce gates.

**Unique content:**
- Full workflow: INTAKE → TESTING → FIXING → DONE (11 stages + 2 gates)
- Detailed stage instructions for each agent
- Delegation templates for each agent
- Status file schema (persistent conductor-status.json)
- Module reference (port, responsibility)
- Integration points (when each agent runs, what blocks what)

**Relations:**
- Delegates to → Coder, CodeReviewer, Security, TestPlanner, Tester, Documentation
- References → SHARED-RULES.md (non-negotiable constraints), CHECKLISTS.md (code/security gates)

**Read this if:** You need to understand the full orchestration workflow or troubleshoot a stuck stage.

---

## 🔧 Language-Specific Coders

### [GenericCodingPractices.md](GenericCodingPractices.md) — 150 lines
**What:** Language-agnostic coding best practices shared by all coders.

**Contains:**
- Before writing anything (read code, check `common/`, test after changes)
- Logging rules (prefix with `[ClassName]`, last arg exception)
- Error handling (no silent catches, generic API responses)
- Testing (zero mocking, real test doubles)
- Dependency injection patterns (constructor-based)
- Credential safety (env vars only)
- Shell script safety (guard pattern)
- API/HTTP response rules
- Immutability & data structures
- Naming conventions
- Code organization
- Forbidden patterns (all languages)

**When to use:** Both JavaCoder and PythonCoder reference this file.

---

### [JavaCoder.agent.md](JavaCoder.agent.md) — 150 lines
**Role:** Implement Java/Spring Boot code (Java 25, Spring Boot 4, Kafka/Redis).

**Unique Java-specific content:**
- Java 25 patterns (records, sealed classes, pattern matching, virtual threads, text blocks)
- Spring Boot 4 (constructor injection via Lombok, conditional beans, Kafka producers/consumers, MCP tools)
- Testing (JUnit 5, real test doubles, no Mockito)
- Java-specific forbidden patterns

**References:**
- [GenericCodingPractices.md](GenericCodingPractices.md) (error handling, logging, testing fundamentals)
- [SHARED-RULES.md](SHARED-RULES.md) (Spring patterns, Kafka, Redis, shell scripts)

**Read this if:** You are implementing Java/Spring Boot code.

---

### [PythonCoder.agent.md](PythonCoder.agent.md) — 150 lines
**Role:** Implement Python code (Python 3.10+, FastAPI, async, RAG services).

**Unique Python-specific content:**
- Python 3.10+ patterns (type hints, pattern matching, async/await, dataclasses, f-strings)
- FastAPI patterns (endpoints with logging, dependency injection, error handling)
- Testing (pytest, real test doubles, no mock.patch)
- Python-specific forbidden patterns

**References:**
- [GenericCodingPractices.md](GenericCodingPractices.md) (error handling, logging, DI, testing fundamentals)
- [SHARED-RULES.md](SHARED-RULES.md) (credential safety, shell scripts when needed)

**Read this if:** You are implementing Python code (iWiki services).

---

### [CodeReviewer.agent.md](CodeReviewer.agent.md) — 386 lines
**Role:** Audit every Coder change for correctness. Block on BLOCKER/MAJOR. Forward approval to Security.

**Unique content:**
- 12-section review checklist with BLOCKER/MAJOR rules
- Common violations and fixes (per section, with code examples)
- Severity levels (BLOCKER, MAJOR, MINOR, INFO)
- Findings report format
- Rules (never skip sections, never forward with outstanding BLOCKERs)
- Integration with Conductor workflow (gates, iterations, approvals)

**Relations:**
- References → CHECKLISTS.md (all 12 sections consolidated here now)
- DEPRECATED → Checklist details moved to CHECKLISTS.md (this file still has examples)
- Receives from → Conductor (after Coder BUILD SUCCESS)
- Outputs to → Security (if APPROVED) or back to Coder (if findings)

**Read this if:** You need to review code or understand code review gates.

---

### [Security.agent.md](Security.agent.md) — 177 lines
**Role:** Audit for credentials, API auth, input validation, actuator exposure, temp files, CVEs.

**Unique content:**
- 10-section audit checklist with pass conditions
- Shell script specific rules (guard pattern, env vars, process args)
- Severity levels (CRITICAL, HIGH, MEDIUM, LOW)
- Findings report format
- Rules (never accept hardcoded secrets, fail-secure on auth)
- Integration with Conductor (design review + code review gates)

**Relations:**
- References → CHECKLISTS.md (all 10 sections + shell script section consolidated)
- DEPRECATED → Checklist details moved to CHECKLISTS.md (this file still has context)
- Receives from → Conductor (design stage OR after CodeReviewer APPROVED)
- Outputs to → Documentation (if passed) or back to Coder (if findings)

**Read this if:** You need to audit for security or understand security gates.

---

### [TestPlanner.agent.md](TestPlanner.agent.md) — 84 lines
**Role:** Convert feature descriptions into test scenarios (JUnit 5, no code).

**Unique content:**
- Test scenario planning process
- Test naming convention
- Zero Mockito constraints
- Module placement paths
- Output format (test plan, not implementation)

**Relations:**
- References → SHARED-RULES.md § Testing (zero mockito examples)
- Receives from → Conductor (feature description)
- Outputs to → Coder (test stubs for implementation)

**Read this if:** You need to write test scenarios.

---

### [Tester.agent.md](Tester.agent.md) — 72 lines
**Role:** Run and validate tests. Fix step definitions or page objects if tests fail.

**Unique content:**
- Test execution steps (Maven command, JUnit 5 runner)
- Failure interpretation (compilation, undefined steps, assertions, locators)
- Fix and re-run procedure
- Module-specific file locations (web, mobile)
- Rules (never modify feature files to work around failures)

**Relations:**
- Receives from → Conductor (test & fix iterations)
- May output to → Coder (if test doubles needed) or CodeReviewer

**Read this if:** You need to run tests or troubleshoot test failures.

---

### [Documentation.agent.md](Documentation.agent.md) — 160 lines
**Role:** Update and maintain docs. Keep precise, concise, DRY (one source of truth per concept).

**Unique content:**
- Responsibilities (update ARCHITECTURE.md, README.md after changes)
- Documentation philosophy (link don't duplicate, 3-file max)
- Consolidation checklist
- Update patterns (new feature, config change, performance, troubleshooting)
- Forbidden actions (no agent file writes, no duplication)
- Approval criteria (no section >2000 words, one concept = one location)

**Relations:**
- Receives from → Conductor (after Security APPROVED) for major changes
- References → README.md, ARCHITECTURE.md, `.env.example` (only docs to maintain)

**Read this if:** You need to update documentation.

---

## 🔗 Project Documentation

These are what Documentation agent maintains:

- **[README.md](../../README.md)** — Quick start, environment variables, API reference, local development
- **[ARCHITECTURE.md](../../ARCHITECTURE.md)** — System design, data model, pipeline flows, performance, troubleshooting
- **[.env.example](../../.env.example)** — Environment variable template

---

## 📊 File Cross-References

| Agent | Reads | References |
|-------|-------|-----------|
| **JavaCoder** | Task from Conductor | GenericCodingPractices + SHARED-RULES |
| **PythonCoder** | Task from Conductor | GenericCodingPractices + SHARED-RULES |
| **CodeReviewer** | Code from Coder | CHECKLISTS (CodeReviewer) + SHARED-RULES |
| **Security** | Code from CodeReviewer | CHECKLISTS (Security) + SHARED-RULES |
| **TestPlanner** | Feature from Conductor | SHARED-RULES (testing) |
| **Tester** | Tests from Coder | — |
| **Documentation** | Change summary | Project docs (README, ARCHITECTURE, .env.example) |
| **Conductor** | Feature request | All agents, SHARED-RULES, CHECKLISTS, GenericCodingPractices |

---

## 🚀 For First-Time Users

1. **Understand the workflow:** Read [Conductor.agent.md](Conductor.agent.md) § Standard Workflow
2. **Learn generic practices:** Read [GenericCodingPractices.md](GenericCodingPractices.md) (first 3 sections)
3. **Pick your language & role:**
   - **Writing Java code?** → Read [JavaCoder.agent.md](JavaCoder.agent.md)
   - **Writing Python code?** → Read [PythonCoder.agent.md](PythonCoder.agent.md)
   - **Reviewing code?** → Read [CodeReviewer.agent.md](CodeReviewer.agent.md)
   - **Auditing security?** → Read [Security.agent.md](Security.agent.md)
   - **Creating tests?** → Read [TestPlanner.agent.md](TestPlanner.agent.md)
4. **Reference GenericCodingPractices.md whenever you need common patterns** (logging, error handling, testing, etc.)
5. **Use SHARED-RULES.md for cross-cutting concerns** (shell scripts, credentials, Kafka/Redis)
6. **Use CHECKLISTS.md when reviewing** (12 code sections, 10 security sections)

---

## 📋 Quick Checklist for Code Review

Copy this and use it:

```
CodeReviewer running [CHECKLISTS.md](CHECKLISTS.md) on: [FILES]

File: ___________

## Java 25 Idioms (§1)
- [ ] Records for DTOs
- [ ] Sealed classes present where applicable
- [ ] Pattern matching instead of casts
- [ ] Virtual threads if async
- [ ] No raw types
- [ ] No unchecked casts without @SuppressWarnings

## DI (§2)
- [ ] Constructor injection (@RequiredArgsConstructor)
- [ ] No @Autowired on fields
- [ ] No `common/` duplicates

## Logging (§4)
- [ ] @Slf4j present
- [ ] [ClassName] prefix on all logs
- [ ] Exception as last arg to log.error()
- [ ] No credentials logged

## Error Handling (§5)
- [ ] No silent catches
- [ ] No @SneakyThrows in services
- [ ] HTTP responses generic (no e.getMessage())

## Kafka (§6)
- [ ] Binding via${kafka.topics.xxx}
- [ ] No hardcoded topics

## Testing (§8)
- [ ] No Mockito
- [ ] Real test doubles only

## Config & Secrets (§10)
- [ ] No hardcoded credentials
- [ ] All via ${ENV_VAR:}

Status: APPROVED | NEEDS_FIXES
```

---

## 📋 Quick Checklist for Security Audit

```
Security running [CHECKLISTS.md](CHECKLISTS.md) on: [FILES + scripts + state]

## Credentials (§1)
- [ ] No tokens in .java, .yaml, .sh, .json, .md
- [ ] All via env vars
- [ ] Shell guard pattern present
- [ ] .env in .gitignore
- [ ] No credentials in git remote URLs

## API Auth (§2)
- [ ] Admin endpoints protected (X-Admin-Key or auth)
- [ ] Webhooks verified
- [ ] Fail-secure (not fail-open)

## Input Validation (§3)
- [ ] Size limits configured
- [ ] Diffs truncated before logging

## Actuator (§4)
- [ ] Exposes only health,info
- [ ] Never env, beans, heapdump

## Error Responses (§5)
- [ ] No e.getMessage() in responses
- [ ] Generic error messages

## ProcessBuilder (§7)
- [ ] Use List<String> (not shell string)
- [ ] No tokens in args

## Temp Files (§10)
- [ ] deleteIfExists in finally
- [ ] PosixFilePermissions for sensitive files

Status: CRITICAL | HIGH | MEDIUM | LOW findings
```

---

## Version
Last updated: 2024-06-16
Compression report: [COMPRESSION-REPORT.md](COMPRESSION-REPORT.md)

