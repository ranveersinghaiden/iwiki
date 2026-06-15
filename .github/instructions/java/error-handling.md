# Java Error Handling Conventions
# Scope: ALL generated code (shared across API / UI / Mobile test types)

## Guiding Principle

Errors must be **visible** — never hidden. The right response depends on the layer.

---

## Service Layer

Declare checked exceptions — let the caller decide how to handle them:

```java
public BddScenario generate(ImpactEnvelope env) throws BddGenerationException {
    try {
        String response = aiClient.complete(buildSystemPrompt(), buildUserMessage(env));
        return parseScenario(response);
    } catch (HttpClientErrorException e) {
        log.error("[BddGenerator] AI request failed (HTTP {}): {}", e.getStatusCode(), e.getMessage(), e);
        throw new BddGenerationException("AI request failed: " + e.getMessage(), e);
    } catch (JsonProcessingException e) {
        log.error("[BddGenerator] Failed to parse AI response: {}", e.getMessage(), e);
        throw new BddGenerationException("Invalid AI response format", e);
    }
}
```

---

## Kafka Consumer Layer

Log and swallow — dead-letter queue is a future enhancement:

```java
@KafkaListener(topics = "${kafka.topics.impact-results}", groupId = "${spring.kafka.consumer.group-id}")
public void consume(String message) {
    log.info("[ImpactResultsConsumer] Received ({} bytes)", message.length());
    try {
        var envelope = objectMapper.readValue(message, ImpactEnvelope.class);
        strategyAgent.decide(envelope);
    } catch (JsonProcessingException e) {
        log.error("[ImpactResultsConsumer] Deserialisation failed — message discarded: {}", e.getMessage(), e);
    } catch (Exception e) {
        log.error("[ImpactResultsConsumer] Unexpected error — message discarded: {}", e.getMessage(), e);
    }
}
```

---

## Controller Layer

Wrap service exceptions in HTTP responses — use `@RestControllerAdvice` for global handling:

```java
@RestController
@RequestMapping("/api/strategy")
@RequiredArgsConstructor
@Slf4j
public class StrategyController {

    private final BddGenerator bddGenerator;

    @PostMapping("/generate-bdd")
    public ResponseEntity<BddScenario> generateBdd(@RequestBody @Valid ImpactEnvelope envelope) {
        log.info("[StrategyController] POST /generate-bdd — prId='{}'", envelope.getPrId());
        try {
            return ResponseEntity.ok(bddGenerator.generate(envelope));
        } catch (BddGenerationException e) {
            log.error("[StrategyController] BDD generation failed: {}", e.getMessage(), e);
            return ResponseEntity.internalServerError().build();
        }
    }
}
```

---

## Custom Exception Convention

Domain-specific exceptions should extend `RuntimeException` for unchecked or `Exception` for checked:

```java
// Checked — caller must handle
public class BddGenerationException extends Exception {
    public BddGenerationException(String message, Throwable cause) {
        super(message, cause);
    }
}

// Unchecked — programming error / configuration problem
public class MissingConfigurationException extends RuntimeException {
    public MissingConfigurationException(String property) {
        super("Required property '" + property + "' is not configured");
    }
}
```

---

## What Is NEVER Acceptable

```java
// ❌ Swallowing silently — hides bugs
catch (Exception e) {}

// ❌ Logging without the exception — loses the stack trace
log.error("[MyService] Something went wrong: {}", e.getMessage());

// ❌ @SneakyThrows in service/business classes — hides checked exceptions
@SneakyThrows  // FORBIDDEN in services
public void process() { ... }

// ❌ Generic RuntimeException with no context
throw new RuntimeException(e);  // always add a message
```

```java
// ✅ Correct at every layer
log.error("[MyService] Processing failed for '{}': {}", id, e.getMessage(), e);
throw new MyDomainException("Failed to process " + id, e);
```

---

## Wrapping Checked Exceptions at Boundaries

Only wrap checked exceptions in `RuntimeException` at the outermost boundary (controller or Kafka listener). Internal methods should declare `throws`:

```java
// ✅ Internal method — declares throws
private BddScenario callAi(String prompt) throws BddGenerationException { ... }

// ✅ Boundary — wraps at the Kafka listener
@KafkaListener(...)
public void consume(String msg) {
    try {
        process(msg);
    } catch (BddGenerationException e) {
        // boundary: log + swallow
        log.error("[Consumer] BDD generation error: {}", e.getMessage(), e);
    }
}
```

