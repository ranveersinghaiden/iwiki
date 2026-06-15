# Spring AI MCP Server — Setup & Registration
# Scope: ALL generated code (shared across API / UI / Mobile test types)

## Overview

The **Spring AI MCP (Model Context Protocol) Server** exposes Spring Boot service
methods as structured tools that GitHub Copilot, Copilot CLI, and other AI agents
can call at runtime without any bespoke HTTP client code.

---

## Maven Dependency

Add to the specific service `pom.xml` (version managed via Spring AI BOM in root `pom.xml`):

```xml
<!-- SSE transport — standard for running HTTP services -->
<dependency>
    <groupId>org.springframework.ai</groupId>
    <artifactId>spring-ai-starter-mcp-server-webmvc</artifactId>
</dependency>
```

For STDIO transport (Copilot CLI / local process mode):
```xml
<dependency>
    <groupId>org.springframework.ai</groupId>
    <artifactId>spring-ai-starter-mcp-server</artifactId>
</dependency>
```

---

## `application.yaml` Configuration

```yaml
spring:
  ai:
    mcp:
      server:
        enabled:              ${MCP_ENABLED:true}
        name:                 ${spring.application.name}-mcp
        version:              "1.0.0"
        type:                 SYNC          # SYNC (blocking) or ASYNC (reactive)
        sse-message-endpoint: /mcp/message  # POST endpoint for MCP messages
        sse-endpoint:         /mcp/sse      # GET endpoint for SSE event stream
```

---

## Tool Registration — `McpToolsConfig`

All `@Tool` beans for a service are registered in **one `@Configuration` class**:

```java
package nz.co.eroad.qaisystem.config;

import org.springframework.ai.tool.MethodToolCallbackProvider;
import org.springframework.ai.tool.ToolCallbackProvider;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import nz.co.eroad.qaisystem.mcp.StrategyMcpTools;
import nz.co.eroad.qaisystem.mcp.BddMcpTools;

@Configuration
public class McpToolsConfig {

    /**
     * Registers all MCP tool objects for this service.
     * Add new @Tool beans here as additional toolObjects() arguments.
     */
    @Bean
    public ToolCallbackProvider serviceToolCallbackProvider(
            StrategyMcpTools strategyTools,
            BddMcpTools bddTools) {
        return MethodToolCallbackProvider.builder()
                .toolObjects(strategyTools, bddTools)
                .build();
    }
}
```

---

## Auto-Registered Endpoints

`spring-ai-starter-mcp-server-webmvc` auto-registers these endpoints — no controller needed:

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/mcp/sse` | `GET` | SSE event stream — Copilot connects here |
| `/mcp/message` | `POST` | MCP tool call messages |

Ensure these paths are permit-listed if Spring Security is enabled:
```java
http.authorizeHttpRequests(auth -> auth
    .requestMatchers("/mcp/**", "/api/*/health").permitAll()
    .anyRequest().authenticated());
```

---

## MCP Server Discovery — `.github/mcp.json`

GitHub Copilot discovers local MCP servers via `.github/mcp.json`:

```json
{
  "mcpServers": {
    "qa-pr-service":       { "type": "sse", "url": "http://localhost:8080/mcp/message" },
    "qa-impact-service":   { "type": "sse", "url": "http://localhost:8081/mcp/message" },
    "qa-strategy-service": { "type": "sse", "url": "http://localhost:8082/mcp/message" },
    "qa-codegen-service":  { "type": "sse", "url": "http://localhost:8083/mcp/message" },
    "qa-feedback-service": { "type": "sse", "url": "http://localhost:8084/mcp/message" }
  }
}
```

---

## STDIO Mode (Copilot CLI / Local Dev)

For use without a running HTTP server:

```yaml
# application-cli.yaml  (activate: --spring.profiles.active=cli)
spring:
  ai:
    mcp:
      server:
        type: SYNC
        stdio: true
```

Copilot CLI config:
```json
{
  "mcpServers": {
    "qa-strategy-service": {
      "type": "stdio",
      "command": "java",
      "args": ["-jar", "/path/to/strategy-service.jar", "--spring.profiles.active=cli"]
    }
  }
}
```

---

## Service → Tool Class Mapping

| Service | Config class | Tool classes |
|---------|-------------|-------------|
| `pr-service` | `McpToolsConfig` | `PrMcpTools` |
| `impact-service` | `McpToolsConfig` | `ImpactMcpTools` |
| `strategy-service` | `McpToolsConfig` | `StrategyMcpTools`, `BddMcpTools` |
| `codegen-service` | `McpToolsConfig` | `CodegenMcpTools` |
| `feedback-service` | `McpToolsConfig` | `FeedbackMcpTools` |

