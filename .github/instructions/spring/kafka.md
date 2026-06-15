# Kafka Conventions
# Scope: ALL generated code (shared across API / UI / Mobile test types)

## Core Rules

1. **Never hardcode topic names** — always bind via `${kafka.topics.xxx}`.
2. **Producer returns `CompletableFuture<SendResult<String, String>>`** — don't block.
3. **Consumer is `void`** — log the raw message first, then deserialise.
4. **Consumer errors are logged and swallowed** — DLQ is a future enhancement.

---

## Producer Pattern

```java
@Service
@RequiredArgsConstructor
@Slf4j
public class FeedbackEventProducer {

    private final KafkaTemplate<String, String> kafkaTemplate;
    private final KafkaConfig kafkaConfig;
    private final ObjectMapper objectMapper;

    /** Publishes a FeedbackEvent to the FeedbackQueue topic. */
    public CompletableFuture<SendResult<String, String>> publishFeedbackEvent(FeedbackEvent event) {
        try {
            String json = objectMapper.writeValueAsString(event);
            log.info("[FeedbackEventProducer] Publishing FeedbackEvent prId='{}' type={}",
                    event.getPrId(), event.getType());
            return kafkaTemplate.send(kafkaConfig.feedbackTopic(), event.getPrId(), json);
        } catch (JsonProcessingException e) {
            throw new RuntimeException("[FeedbackEventProducer] Serialisation failed for prId="
                    + event.getPrId(), e);
        }
    }
}
```

---

## Consumer Pattern

```java
@Service
@RequiredArgsConstructor
@Slf4j
public class FeedbackEventConsumer {

    private final PrFeedbackService feedbackService;
    private final ObjectMapper objectMapper;

    @KafkaListener(
        topics   = "${kafka.topics.feedback}",
        groupId  = "${spring.kafka.consumer.group-id}"
    )
    public void consume(String message) {
        // 1. Log raw message FIRST (size, not content — may contain PII)
        log.info("[FeedbackEventConsumer] Received ({} bytes)", message.length());
        try {
            FeedbackEvent event = objectMapper.readValue(message, FeedbackEvent.class);
            log.info("[FeedbackEventConsumer] Processing prId='{}' type={}",
                    event.getPrId(), event.getType());

            if (event.getType() == PrType.BDD) {
                feedbackService.handleBddRejection(event);
            } else {
                feedbackService.handleTestRejection(event);
            }
        } catch (JsonProcessingException e) {
            log.error("[FeedbackEventConsumer] Deserialisation failed — message discarded: {}",
                    e.getMessage(), e);
        } catch (Exception e) {
            log.error("[FeedbackEventConsumer] Unexpected error — message discarded: {}",
                    e.getMessage(), e);
        }
    }
}
```

---

## KafkaConfig Bean

Topic names are centralised in `KafkaConfig` in `common`:

```java
// In common/config/KafkaConfig.java — DO NOT add topic beans in individual services
@Configuration
public class KafkaConfig {

    @Value("${kafka.topics.feature-updates:FeatureUpdatesQueue}")
    private String featureUpdatesTopic;

    @Value("${kafka.topics.feedback:FeedbackQueue}")
    private String feedbackTopic;

    @Bean public NewTopic featureUpdatesTopic() { return TopicBuilder.name(featureUpdatesTopic).build(); }
    @Bean public NewTopic feedbackTopic()        { return TopicBuilder.name(feedbackTopic).build(); }

    // Accessor methods used by producers
    public String featureUpdatesTopic() { return featureUpdatesTopic; }
    public String feedbackTopic()       { return feedbackTopic; }
}
```

---

## `application.yaml` — Kafka Topics Block

```yaml
spring:
  kafka:
    bootstrap-servers: ${KAFKA_BOOTSTRAP_SERVERS:localhost:9092}
    consumer:
      group-id: my-service-group
      auto-offset-reset: earliest
      key-deserializer: org.apache.kafka.common.serialization.StringDeserializer
      value-deserializer: org.apache.kafka.common.serialization.StringDeserializer
    producer:
      key-serializer: org.apache.kafka.common.serialization.StringSerializer
      value-serializer: org.apache.kafka.common.serialization.StringSerializer

kafka:
  topics:
    feature-updates: FeatureUpdatesQueue   # pr-service → impact-service
    impact-results:  ImpactResultsQueue    # impact-service → strategy-service
    test-scripts:    TestScriptsQueue      # strategy-service → codegen-service
    test-results:    TestResultsQueue      # codegen-service (future)
    feedback:        FeedbackQueue         # strategy-service → feedback-service
```

---

## Conditional Consumer

Use `@ConditionalOnProperty` to disable a consumer in services that shouldn't own it:

```java
// strategy-service disabled TestScriptsConsumer — codegen-service owns this queue
@Service
@ConditionalOnProperty(name = "aiqa.codegen.enabled", havingValue = "true", matchIfMissing = false)
public class TestScriptsConsumer { ... }
```

