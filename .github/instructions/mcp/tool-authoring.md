# Spring AI MCP — Tool Authoring Guide
# Scope: ALL generated code (shared across API / UI / Mobile test types)

## Tool Class Structure

```java
package nz.co.eroad.qaisystem.mcp;

import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.ai.tool.annotation.Tool;
import org.springframework.ai.tool.annotation.ToolParam;
import org.springframework.stereotype.Service;
import com.fasterxml.jackson.databind.ObjectMapper;

@Service
@RequiredArgsConstructor
@Slf4j
public class StrategyMcpTools {

    private final StrategyAgent strategyAgent;
    private final ObjectMapper  objectMapper;

    @Tool(description = """
            Decide the QA strategy for a pull request given its impact analysis result.
            Input:  ImpactEnvelope JSON — fields: prId (string), riskLevel (LOW|MEDIUM|HIGH|CRITICAL),
                    changeTypes (array of strings), coverage (object with level and ratio).
            Output: StrategyResult JSON — fields: action (SKIP|UPDATE_TESTS|CREATE_TESTS),
                    expandedScope (boolean), fullRegressionRequired (boolean).
            Side effects: none — read-only decision.
            """)
    public String decideStrategy(
            @ToolParam(description = "ImpactEnvelope JSON produced by impact-service") String impactEnvelopeJson) {
        log.info("[StrategyMcpTools] decideStrategy called");
        try {
            var envelope = objectMapper.readValue(impactEnvelopeJson, ImpactEnvelope.class);
            var result   = strategyAgent.decide(envelope);
            return objectMapper.writeValueAsString(result);
        } catch (Exception e) {
            log.error("[StrategyMcpTools] decideStrategy failed: {}", e.getMessage(), e);
            return errorJson(e.getMessage());
        }
    }
}
```

---

## Tool Description Rules

AI agents (Copilot) decide whether and how to call a tool **solely from its description**.
A vague description means the tool will be called incorrectly or ignored.

| Requirement | Example |
|-------------|---------|
| **What** the tool does | `"Analyze a pull request diff and classify its risk."` |
| **Input format** — field names and types | `"Input: JSON with prId (string), diff (string)."` |
| **Output format** — field names and types | `"Output: JSON with riskLevel (LOW/MEDIUM/HIGH/CRITICAL) and score (0.0–1.0)."` |
| **Side effects** if any | `"Creates a GitHub branch and opens a PR in the target test repository."` |
| **None** if read-only | `"Side effects: none."` |

Keep tool method names under 64 characters. Full documentation goes in the description string.

### `@ToolParam` — every parameter must have a description

```java
@Tool(description = "Generate Gherkin BDD scenarios from a TestStrategy.")
public String generateBdd(
        @ToolParam(description = "TestStrategy JSON with prId, action, testType") String strategyJson,
        @ToolParam(description = "Optional product context — pass empty string if unavailable") String context) {
    ...
}
```

---

## Error Response Convention

MCP tools **must never throw unhandled exceptions** — Copilot treats uncaught errors
as complete tool failures and may retry indefinitely.

Always catch all exceptions and return a JSON `{"error": "..."}` string:

```java
private String errorJson(String message) {
    // escape quotes to keep JSON valid
    return "{\"error\": \"" + message.replace("\"", "'") + "\"}";
}
```

Full pattern:
```java
@Tool(description = "...")
public String myTool(@ToolParam(description = "...") String input) {
    try {
        MyResult result = service.process(objectMapper.readValue(input, MyRequest.class));
        return objectMapper.writeValueAsString(result);
    } catch (JsonProcessingException e) {
        log.error("[MyMcpTools] Invalid input JSON: {}", e.getMessage(), e);
        return errorJson("Invalid input: " + e.getMessage());
    } catch (Exception e) {
        log.error("[MyMcpTools] myTool failed: {}", e.getMessage(), e);
        return errorJson(e.getMessage());
    }
}
```

---

## All Tools Per Service

### `pr-service` — `PrMcpTools`
```java
@Tool(description = "Submit a PullRequest for QA analysis. Input: PullRequest JSON. "
    + "Output: submission result with prId and status. Side effects: publishes to FeatureUpdatesQueue.")
String submitPr(@ToolParam(description = "PullRequest JSON") String prJson)

@Tool(description = "Get a sample demo PullRequest payload for testing the pipeline. "
    + "Output: PullRequest JSON with realistic diff. Side effects: none.")
String getDemoPayload()
```

### `impact-service` — `ImpactMcpTools`
```java
@Tool(description = "Analyze a source code diff and return a risk assessment. "
    + "Input: JSON with diff (string, unified diff format). "
    + "Output: ImpactEnvelope JSON with riskLevel, score, changeTypes, coverage. Side effects: none.")
String analyzeDiff(@ToolParam(description = "Unified diff string (git diff output)") String diff)
```

### `strategy-service` — `StrategyMcpTools` + `BddMcpTools`
```java
@Tool(description = "Decide QA strategy for a PR. Input: ImpactEnvelope JSON. "
    + "Output: StrategyResult JSON (action, expandedScope). Side effects: none.")
String decideStrategy(@ToolParam(description = "ImpactEnvelope JSON") String envelopeJson)

@Tool(description = "Generate Gherkin BDD scenarios from a test strategy. "
    + "Input: TestStrategy JSON. Output: BddScenario JSON with title, steps, and prId. "
    + "Side effects: creates a GitHub branch and opens a BDD review PR if TARGET_REPO_URL is set.")
String generateBdd(@ToolParam(description = "TestStrategy JSON") String strategyJson)

@Tool(description = "Re-pull the target test repository and rebuild the coverage and context cache. "
    + "Output: JSON with status, api, ui, mobile summaries. Side effects: triggers git pull.")
String refreshRepoContext()
```

### `codegen-service` — `CodegenMcpTools`
```java
@Tool(description = "Generate executable test code from a BDD scenario. "
    + "Input: BddScenario JSON with testType (API|UI|MOBILE). "
    + "Output: TestScript JSON with code and status. "
    + "Side effects: runs stabilization loop, opens final test PR on GitHub if code compiles.")
String generateTests(@ToolParam(description = "BddScenario JSON") String scenarioJson)
```

### `feedback-service` — `FeedbackMcpTools`
```java
@Tool(description = "Process a rejected PR feedback event and trigger re-generation. "
    + "Input: FeedbackEvent JSON with prId, type (BDD|TEST), branchName, reviewComments. "
    + "Output: JSON with status and newPrNumber. "
    + "Side effects: may update productExpert/ files, opens a revised PR on GitHub.")
String handleRejection(@ToolParam(description = "FeedbackEvent JSON") String eventJson)
```

---

## Checklist — Before Shipping a New Tool

- [ ] Tool class in `{service}/src/main/java/.../mcp/` package
- [ ] Class annotated `@Service @RequiredArgsConstructor @Slf4j`
- [ ] `@Tool` description covers: **what**, **input format**, **output format**, **side effects**
- [ ] Every `@ToolParam` has a non-empty description
- [ ] Tool method catches ALL exceptions → returns `errorJson(message)` on failure
- [ ] Tool class registered in `McpToolsConfig.serviceToolCallbackProvider()`
- [ ] `/mcp/**` is permit-listed in security config (if security enabled)
- [ ] `.github/mcp.json` already lists this service (no change needed per new tool)

