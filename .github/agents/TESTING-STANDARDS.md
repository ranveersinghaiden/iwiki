---
name: Testing-Standards
description: Zero Mockito policy, real test doubles, JUnit 5 conventions, Awaitility patterns.
---

# Testing Standards

## Hard Rule: Zero Mocking

**No `@Mock`, `@MockBean`, `@Spy`, `@InjectMocks`, `Mockito.mock()` anywhere.**

Use **real test doubles** — inner `static` classes extending real class, override only method under test.

## Why Real Test Doubles?

| Mockito mock | Real double |
|-------------|-----------|
| Breaks silently on sig changes | Compile-time failure → forces fix |
| Hides constructor deps | Requires real dep graph |
| `verify()` tests impl details | Tests observable behavior |
| Risky refactoring | Safe to rename/move |

## Pattern

```java
class StrategyAgentTest {

    // Real test double
    static class FixedCoverageAnalyzer extends E2ECoverageAnalyzer {
        private final CoverageLevel level;
        
        FixedCoverageAnalyzer(CoverageLevel level) {
            super(null);  // null for unused deps
            this.level = level;
        }
        
        @Override
        public CoverageReport analyse(ImpactEnvelope env) {
            return CoverageReport.builder().level(level).build();
        }
    }

    @Test
    void lowRiskNoTests_shouldCreateTests() {
        StrategyAgent agent = new StrategyAgent(
            new FixedCoverageAnalyzer(CoverageLevel.NONE), // real double
            ...
        );
        
        StrategyDecision decision = agent.decide(buildLowRiskEnvelope());
        
        assertEquals(StrategyDecision.CREATE_TESTS, decision.getAction());
    }
}
```

## Test Naming Convention

```
{methodName}_given{Condition}_expected{Outcome}()
```

Examples:
```java
void decide_withCriticalRisk_shouldCreateTests()
void decide_withOnlyInfraChanges_shouldSkip()
void consume_withInvalidJson_shouldLogAndContinue()
void publish_withValidPr_shouldSendToCorrectTopic()
```

## JUnit 5 (No TestNG, No JUnit 4)

| Decorator | Use |
|-----------|-----|
| `@Test` | Single test |
| `@ParameterizedTest` | Data-driven |
| `@BeforeEach` | Setup per test |
| `@AfterEach` | Teardown per test |
| `@DisplayName("...")` | Human-readable name |

## Assertions (AssertJ Preferred)

```java
// ✅ AssertJ
assertThat(result.getStatus()).isEqualTo("UP");
assertThat(list).hasSize(3).contains("item1");
assertThat(exception).isInstanceOf(BddGenException.class)
                      .hasMessageContaining("AI unavailable");

// ❌ JUnit assertEquals (verbose)
assertEquals("UP", result.getStatus());
```

## No Spring Context in Unit Tests

```java
// ✅ Pure unit test — fast
class RiskScorerTest {
    private final RiskScorer scorer = new RiskScorer();

    @Test
    void score_withHighChurnAndCritical_shouldReturnCritical() {
        double score = scorer.score(buildHighRiskDiff());
        assertThat(score).isGreaterThanOrEqualTo(0.8);
    }
}

// Use @SpringBootTest ONLY for real integration tests
@SpringBootTest
class ImpactAnalysisIntegrationTest {
    @Autowired private ImpactService service;
    // full context needed
}
```

## Awaitility (Never Thread.sleep)

```java
// ❌ Flaky
Thread.sleep(1000);
assertThat(producer.published).hasSize(1);

// ✅ Awaitility
import static org.awaitility.Awaitility.await;
import static java.util.concurrent.TimeUnit.SECONDS;

await().atMost(5, SECONDS)
       .until(() -> !producer.published.isEmpty());

assertThat(producer.published).hasSize(1);
```

## Capturing Test Double Pattern

```java
static class CapturingProducer extends FeatureUpdatesProducer {
    final List<PullRequest> published = new ArrayList<>();

    CapturingProducer() { super(null, null); }  // nulls for unused deps

    @Override
    public CompletableFuture<SendResult<String, String>> publishPullRequest(
            PullRequest pr) {
        published.add(pr);
        return CompletableFuture.completedFuture(null);
    }
}

@Test
void process_withValidPr_shouldPublishOnce() {
    var producer = new CapturingProducer();
    service.process(buildPr());

    assertThat(producer.published).hasSize(1);
    assertThat(producer.published.get(0).getId()).isEqualTo("PR-123");
}
```

## Test Data Builders

```java
private static ImpactEnvelope buildEnvelope() {
    return ImpactEnvelope.builder()
            .prId("PR-TEST-001")
            .repositoryName("payment-service")
            .riskLevel(RiskLevel.HIGH)
            .build();
}

private static ImpactEnvelope buildLowRiskEnvelope() {
    return buildEnvelope().toBuilder()
            .riskLevel(RiskLevel.LOW)
            .build();
}
```

## Forbidden Test Patterns

| Pattern | Reason |
|---------|--------|
| `@Mock` / `@MockBean` / `@Spy` | Zero-mock policy |
| `@InjectMocks` | Forces Mockito |
| `Mockito.mock/when/verify` | Zero-mock policy |
| `Thread.sleep()` | Use Awaitility |
| `new ObjectMapper()` in test | Use injected or builder |
| `catch (Exception e) {}` | Always verify/assert |

## Test Structure (AAA Pattern)

```java
@Test
void myTest() {
    // Arrange — setup
    var input = buildTestData();
    
    // Act — execute
    var result = service.doSomething(input);
    
    // Assert — verify
    assertThat(result).isEqualTo(expected);
}
```

## Parameterized Tests

```java
@ParameterizedTest
@ValueSource(strings = { "PR-001", "PR-002", "PR-003" })
void processPr_withValidId_shouldSucceed(String prId) {
    var result = service.process(prId);
    assertThat(result).isNotNull();
}

@ParameterizedTest
@CsvSource({
    "HIGH,  true",
    "MEDIUM, false",
    "LOW,   false"
})
void decide_riskLevel(String risk, boolean expectTests) {
    var decision = agent.decide(buildEnvelope(risk));
    assertThat(decision.needsTests()).isEqualTo(expectTests);
}
```

## Integration Test Setup

```java
@SpringBootTest
@Testcontainers
class ImpactServiceIntegrationTest {
    @Container
    static PostgreSQLContainer<?> postgres = new PostgreSQLContainer<>(...);
    
    @Autowired private ImpactService service;
    @Autowired private TestRepository repo;
    
    @BeforeEach
    void setUp() {
        repo.deleteAll();  // clean state per test
    }
    
    @Test
    void analyzeImpact_withValidDiff_shouldReturnEnvelope() {
        var result = service.analyzeImpact(loadTestDiff());
        assertThat(result).isNotNull();
        assertThat(result.getRiskLevel()).isNotNull();
    }
}
```

## Test File Locations

| Module | Location |
|--------|----------|
| pr-service | `src/test/java/nz/co/eroad/qaisystem/prservice/**/*Test.java` |
| spring tests | BDD in `src/test/resources/features/` + step defs in Java tests |
| integration | Same folder, `*IntegrationTest.java` naming |

## Validation Checklist

Before merging test code:

- [ ] No `@Mock`, `@MockBean`, `@Spy`, `@InjectMocks`
- [ ] No `Mockito.mock/when/verify`
- [ ] No `Thread.sleep()` — use `Awaitility`
- [ ] Test names follow `method_givenCondition_expectedOutcome()`
- [ ] JUnit 5 annotations only
- [ ] All assertions use AssertJ
- [ ] AAA pattern (Arrange/Act/Assert)
- [ ] Real test doubles are `static` inner classes
- [ ] Unit tests have no Spring context
- [ ] Integration tests use `@SpringBootTest`
- [ ] No hardcoded timeouts — use `Awaitility`

