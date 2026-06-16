---
name: MCP-Servers
description: Spring AI MCP Server setup and tool authoring for QA-ISystem agents.
---

# MCP Servers

## Role

Every service that exposes business operations **must** declare `@Tool`-annotated methods via Spring AI MCP Server.

Tools are discovered by agents and embedded into AI prompts for decision-making.

## Setup

MCP server auto-starts: `spring-ai-starter-mcp-server-webmvc` in Spring Boot 4.

Registration: `MethodToolCallbackProvider` in `@Configuration` class.

## Tool Declaration

### Pattern

```java
@Service @RequiredArgsConstructor
public class StrategyMcpTools {
    private final StrategyAgent strategyAgent;

    @Tool(description = "Decide QA strategy for PR based on impact envelope. "
            + "Returns: SKIP, UPDATE_TESTS, or CREATE_TESTS")
    public String decideStrategy(
            @ToolParam(description = "ImpactEnvelope JSON from impact-service") String impactJson) {
        ImpactEnvelope env = objectMapper.readValue(impactJson, ImpactEnvelope.class);
        StrategyDecision decision = strategyAgent.decide(env);
        return decision.toString();
    }
}
```

### Rules

| Rule | Why |
|------|-----|
| `@Tool` on public method | Auto-discovered by MCP server |
| Description = precise, self-contained | AI reads this to understand tool purpose |
| `@ToolParam` all params | Param descriptions explicit for AI |
| JSON in/out | Tools communicate via JSON serialization |
| No `null` returns | Always return valid value or throw |
| Log all invocations | `log.info("[ToolName] Invoked by {} with ...", agentId)` |

### Tool Description Format

```
{action} {what} {returns summary}

Examples:
- "Decide QA strategy for a pull request based on its impact envelope. " +
  "Returns one of: SKIP, UPDATE_TESTS, CREATE_TESTS."

- "Generate BDD test scenarios for a given impact analysis result. " +
  "Returns Gherkin-formatted feature file content."

- "Approve BDD scenarios for merge into main branch. " +
  "Returns approval status: APPROVED or REJECTED_WITH_REASON."
```

### Parameter Description Format

```
{what} {format} {constraints}

Examples:
- "ImpactEnvelope JSON containing PR metadata, risk level, and diff summary"
- "Gherkin feature file content (must start with 'Feature:')"
- "Approval decision: JSON {prId, approved: true|false, reason: string}"
```

## Registration (Required)

```java
@Configuration
public class McpToolsConfig {

    @Bean
    public MethodToolCallbackProvider strategyToolProvider(StrategyMcpTools tools) {
        return new MethodToolCallbackProvider(tools);
    }

    @Bean
    public MethodToolCallbackProvider codegenToolProvider(CodegenMcpTools tools) {
        return new MethodToolCallbackProvider(tools);
    }
}
```

## Tool Locations (Per Service)

| Service | Package | Tools |
|---------|---------|-------|
| strategy-service | `nz.co.eroad.qaisystem.strategy.mcp` | `StrategyMcpTools` |
| codegen-service | `nz.co.eroad.qaisystem.codegen.mcp` | `CodegenMcpTools` |
| feedback-service | `nz.co.eroad.qaisystem.feedback.mcp` | `FeedbackMcpTools` |
| impact-service | `nz.co.eroad.qaisystem.impact.mcp` | `ImpactMcpTools` |

## Common Tools (QA-ISystem)

### Strategy Service

Tool: `decideStrategy(ImpactEnvelope)`
- In: PR metadata, risk level, diff summary
- Out: SKIP | UPDATE_TESTS | CREATE_TESTS
- Agents: Conductor uses for BDD/test generation decision

Tool: `generateBddScenarios(ImpactEnvelope)`  
- In: Impact data, repo context, diff
- Out: Gherkin feature file content
- Agents: Uses for test scenario generation

Tool: `approveBddForMerge(PrRecord)`
- In: PR ID, branch, BDD scenarios
- Out: APPROVED | REJECTED_WITH_REASON
- Agents: Conductor uses before merging BDD PR to main

### Codegen Service

Tool: `generateTestCode(TestScenario[])`
- In: BDD scenarios from strategy-service
- Out: JUnit 5 test class code
- Agents: Conversion of BDD → code

Tool: `stabiliseTests(TestScenario, TestResult[])`
- In: Failing test results, original scenario
- Out: Fixed test code
- Agents: Iterative test stabilisation

### Feedback Service

Tool: `analyzeRejection(PrRecord, FeedbackText)`
- In: Rejected PR details, GitHub feedback comment
- Out: AI-generated improvement suggestions + code fixes
- Agents: Used for rejection feedback loop

## Logging Requirements

Every tool must log entry/exit:

```java
@Tool(description = "...")
public String doSomething(@ToolParam String param) {
    log.info("[ToolName] Invoked: param='{}'", param);
    try {
        String result = performWork(param);
        log.info("[ToolName] Success: result='{}'", result);
        return result;
    } catch (Exception e) {
        log.error("[ToolName] Failed: {}", e.getMessage(), e);
        throw new RuntimeException("[ToolName] Error", e);
    }
}
```

## Error Handling

| Rule | Example |
|------|---------|
| No null returns | Always return valid value or throw |
| Log full exception | Include stack trace at ERROR level |
| Throw `RuntimeException` | Wrap checked exceptions |
| Message = specific | Add context: service name, param summary, root cause |

## Testing Tools

| Rule | Example |
|------|---------|
| Unit test tool method directly | No Mockito—real dependencies |
| Mock only external APIs | `FixedAiClient extends OpenAiClient { ... }` |
| Verify JSON serialization | Input/output are valid JSON |
| Test error paths | Verify exceptions thrown + logged |

## Validation

### Before merging tool-declaring code:

- [ ] `@Tool` on all public methods exposing decisions
- [ ] Description = precise, self-contained (agents read this)
- [ ] All `@ToolParam` have descriptions
- [ ] Logging at entry/exit
- [ ] Exception handling (no silent catches)
- [ ] Unit tests for tool method
- [ ] Registration in MCP config (e.g., `McpToolsConfig`)
- [ ] No null returns
- [ ] All JSON in/out validated

