# Testing Conventions — Zero Mockito Policy
# Scope: ALL generated test types (API / UI / Mobile)

## Hard Rule

**Mockito is forbidden.** No `@Mock`, `@MockBean`, `@Spy`, `@InjectMocks`, or
`Mockito.mock(...)` anywhere in this project.

Use **real test doubles** — inner `static` classes that extend the real class and
override only the behaviour under test.

---

## Why Real Test Doubles?

| Mockito mock | Real test double |
|-------------|-----------------|
| Breaks silently when method signatures change | Compile-time failure — forces fix immediately |
| Hides constructor dependencies | Requires constructing the real dependency graph |
| `verify()` tests implementation details | Tests observable behaviour only |
| Makes refactoring risky | Safe to rename/move methods |

---

## Test Double Pattern

```java
class BddGeneratorTest {

    // ── Real test double ──────────────────────────────────────────────────────
    // Subclass the real type. Override only the method under test.
    // Pass null for dependencies the override doesn't need.
    static class FixedAiClient extends OpenAiClient {
        private final String fixedResponse;

        FixedAiClient(String response) {
            super(null);  // null WebClient — never actually called
            this.fixedResponse = response;
        }

        @Override
        public String complete(String systemPrompt, String userPrompt) {
            return fixedResponse;
        }
    }

    // ── Capturing test double — records calls for assertion ──────────────────
    static class CapturingProducer extends FeatureUpdatesProducer {
        final List<PullRequest> published = new ArrayList<>();

        CapturingProducer() { super(null, null); }  // nulls: KafkaTemplate, KafkaConfig

        @Override
        public CompletableFuture<SendResult<String, String>> publishPullRequest(PullRequest pr) {
            published.add(pr);
            return CompletableFuture.completedFuture(null);
        }
    }

    // ── Tests ─────────────────────────────────────────────────────────────────
    @Test
    void generate_withValidEnvelope_returnsParsedGherkin() {
        var client    = new FixedAiClient("Feature: Payment\n  Scenario: Charge card\n    Given...");
        var generator = new BddGenerator(client, null, null);

        BddScenario scenario = generator.generate(buildEnvelope());

        assertThat(scenario.getTitle()).contains("Payment");
        assertThat(scenario.getSteps()).isNotEmpty();
    }

    // ── Test data helpers ─────────────────────────────────────────────────────
    private static ImpactEnvelope buildEnvelope() {
        return ImpactEnvelope.builder()
                .prId("PR-TEST-001")
                .repositoryName("payment-service")
                .riskLevel(RiskLevel.HIGH)
                .build();
    }
}
```

---

## Naming Convention

```
methodName_givenCondition_expectedOutcome()
```

Examples:
```java
void decide_withCriticalRisk_shouldCreateTests()
void decide_withOnlyInfraChanges_shouldSkip()
void consume_withInvalidJson_shouldLogAndContinue()
void publish_withValidPr_shouldSendToCorrectTopic()
```

---

## Test Structure

Use JUnit 5 with AssertJ:

```java
// Annotations
@Test               // simple test
@ParameterizedTest  // data-driven test
@BeforeEach         // setup before each test
@AfterEach          // teardown after each test
@DisplayName("Human readable description")

// Assertions (AssertJ — preferred over Assertions.assertEquals)
assertThat(result.getStatus()).isEqualTo("UP");
assertThat(list).hasSize(3).contains("item1");
assertThat(exception).isInstanceOf(BddGenerationException.class)
                      .hasMessageContaining("AI unavailable");
```

---

## No Spring Context in Unit Tests

Unit tests should construct dependencies directly — no `@SpringBootTest`:

```java
// ✅ Pure unit test — fast, no container overhead
class RiskScorerTest {
    private final RiskScorer scorer = new RiskScorer();

    @Test
    void score_withHighChurnAndCriticalComponent_shouldReturnCritical() {
        double score = scorer.score(buildHighRiskDiff());
        assertThat(score).isGreaterThanOrEqualTo(0.8);
    }
}

// Use @SpringBootTest only for genuine integration tests that need
// the full context (e.g., Kafka consumer + database in one flow)
```

---

## Awaitility for Async Tests

Never use `Thread.sleep()`. Use `Awaitility`:

```java
import static org.awaitility.Awaitility.await;
import static java.util.concurrent.TimeUnit.SECONDS;

@Test
void asyncHandler_shouldCompleteWithinTimeout() {
    var producer = new CapturingProducer();
    service.processAsync(buildEvent());

    await().atMost(5, SECONDS)
           .until(() -> !producer.published.isEmpty());

    assertThat(producer.published).hasSize(1);
}
```

---

## Forbidden Test Patterns

```java
@Mock    SomeService service;              // FORBIDDEN
@MockBean SomeService service;            // FORBIDDEN
@Spy     SomeService service;             // FORBIDDEN
@InjectMocks SomeTarget target;           // FORBIDDEN
Mockito.mock(SomeService.class);          // FORBIDDEN
Mockito.when(x.method()).thenReturn(y);  // FORBIDDEN
Mockito.verify(x, times(1)).method();    // FORBIDDEN
Thread.sleep(1000);                       // FORBIDDEN — use Awaitility
```

