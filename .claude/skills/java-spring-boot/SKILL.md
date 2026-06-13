# Spring Boot Backend Skill

When this skill is invoked, write or review Spring Boot backend code following the guidelines below.
Apply all rules by default. If the user provides an argument (e.g. `/spring-boot-backend review`), focus on that mode.

---

## Stack & Exact Versions

Pin every dependency explicitly — never let a version float (`3.+`, `LATEST`, ranges). Treat `pom.xml` (or `build.gradle`) as the source of truth; if it pins different versions than listed here, follow the build file and update this skill to match.

- **Java 21** (LTS) — `<java.version>21</java.version>` / `sourceCompatibility = JavaVersion.VERSION_21`
- **Spring Boot 3.2.x** as the parent POM / BOM (Spring Web, Spring Data JPA, Validation, Actuator) — let the BOM manage transitive Spring versions, don't redeclare them
- **JUnit 5.10.x**, **Mockito 5.x**, **Testcontainers 1.19.x** — all via `spring-boot-starter-test` + `testcontainers-bom`
- Build with **Maven** (`mvnw`) using the `spring-boot-starter-parent` parent POM

```xml
<parent>
    <groupId>org.springframework.boot</groupId>
    <artifactId>spring-boot-starter-parent</artifactId>
    <version>3.2.5</version>
</parent>
<properties>
    <java.version>21</java.version>
</properties>
```

---

## Package Layout

Group by **layer/role** under a single root package — never dump unrelated classes into flat `util`/`common`/`misc` packages.

```
com.akamai.miniwsa
  ├── controller/      # one class per resource, thin (EventController, StatsController)
  ├── service/         # business logic (EnrichmentService, StatsService)
  ├── repository/      # Spring Data JPA interfaces only (EventRepository)
  ├── model/
  │    ├── entity/     # JPA @Entity classes (Event, Rule, GeoLocation)
  │    └── dto/        # request/response records (EventRequest, StatsSummaryResponse)
  ├── mapper/          # entity <-> DTO conversion (EventMapper)
  ├── validation/      # custom @Constraint annotations + validators
  ├── exception/       # domain exceptions + @RestControllerAdvice handler
  └── config/          # @Configuration / @ConfigurationProperties classes
```

**Rule:** Controllers call services. Services call repositories. Repositories own all persistence. No JPA/repository access from controllers, no HTTP types (`HttpServletRequest`, `ResponseEntity`) inside services.

---

## Naming Conventions

- Classes: `UpperCamelCase`, suffixed by role — `EventController`, `EnrichmentService`, `EventRepository`
- Entities use the bare domain noun (`Event`, `Rule`); DTOs are suffixed `Request`/`Response` (`EventRequest`, `StatsSummaryResponse`) and written as `record`s
- Packages: lowercase, singular, no underscores (`controller`, not `Controllers`/`controllers_v2`)
- Constants: `UPPER_SNAKE_CASE`; enum types `UpperCamelCase`, constants `UPPER_SNAKE_CASE` (`Severity.CRITICAL`)
- Test classes: `<ClassUnderTest>Test` for unit tests, `<ClassUnderTest>IT` or `*IntegrationTest` for Testcontainers-backed integration tests

---

## Controllers

- `@RestController`, thin — validate input, call one service method, map the result to a response status. No business logic, no repository access.
- Annotate request bodies with `@Valid @RequestBody`.
- Return `ResponseEntity<T>` (or `@ResponseStatus` for fixed codes) — never raw maps.
- Let domain exceptions bubble up to a global `@RestControllerAdvice`; don't `try/catch` in the handler.

```java
@RestController
@RequestMapping("/v1/events")
class EventController {

    private final IngestionService ingestionService;

    EventController(IngestionService ingestionService) {
        this.ingestionService = ingestionService;
    }

    @PostMapping("/ingest")
    ResponseEntity<List<EventResponse>> ingest(@Valid @RequestBody List<EventRequest> events) {
        List<EventResponse> stored = ingestionService.ingest(events);
        return ResponseEntity.status(HttpStatus.CREATED).body(stored);
    }
}
```

---

## Swagger / OpenAPI

**Rule:** Every new endpoint must be documented with OpenAPI annotations before the task is done. Use `springdoc-openapi-starter-webmvc-ui` (already in `pom.xml`) — all annotations come from `io.swagger.v3.oas.annotations.*`.

- `@Tag(name = "...", description = "...")` on the controller class — one tag per resource
- `@Operation(summary = "...")` on every handler method — one short sentence, no period
- `@ApiResponse(responseCode = "...", description = "...")` for each distinct HTTP status the endpoint can return (at minimum: the success code and 400)
- `@Schema(description = "...")` on DTO `record` fields that are not self-evident from the name

```java
@Tag(name = "Events", description = "Security event ingestion")
@RestController
@RequestMapping("/v1/events")
class IngestionController {

    @Operation(summary = "Ingest one or a batch of security events")
    @ApiResponse(responseCode = "201", description = "Events processed; see per-event status in body")
    @ApiResponse(responseCode = "400", description = "Request body is not parseable or not event-shaped")
    @PostMapping("/ingest")
    ResponseEntity<IngestionResponse> ingest(@RequestBody JsonNode body) { ... }
}
```

For DTOs, annotate fields that carry domain-specific meaning:

```java
record IngestionResponse(
        @Schema(description = "Number of events accepted and stored") int accepted,
        @Schema(description = "Number of events rejected due to validation errors") int rejected,
        List<EventResult> results
) {}
```

Do **not** put `@Operation` summaries or `@ApiResponse` on internal/private helpers — only on `@RequestMapping`-annotated handler methods.

---

## Services

- `@Service`, **constructor injection only** — never field `@Autowired`.
- Pure business logic: orchestration, enrichment, scoring. Throw domain exceptions, not `ResponseStatusException`.
- Add an interface only when there is a genuine second implementation or test seam need — don't create `FooService`/`FooServiceImpl` ceremony for a single implementation.
- Place `@Transactional` at the service boundary, not on repositories or controllers.

---

## Repositories

- `interface EventRepository extends JpaRepository<Event, UUID>` — Spring Data interfaces only, no implementation classes.
- Prefer derived query methods; use `@Query` with named parameters (`:clientIp`) for anything non-trivial — never string-concatenate SQL/JPQL.
- Return `Page<T>` with `Pageable` for paginated endpoints; never load unbounded result sets into memory.
- No business logic in repositories — they return data, services interpret it.

---

## Entities & DTOs

- Entities (`model/entity/`) are persistence-only: `@Entity`, JPA annotations, no Jackson/JSON annotations, never returned directly from controllers.
- DTOs (`model/dto/`) are immutable Java `record`s with Bean Validation annotations on request types (`@NotBlank`, `@NotNull`, `@Pattern`).
- Convert between the two in a dedicated `mapper/` class (hand-written or MapStruct) — never let entities leak across the API boundary.

```java
record EventRequest(
        @NotBlank String eventId,
        @NotNull Instant timestamp,
        @NotNull Long configId,
        @NotBlank @Pattern(regexp = "^(\\d{1,3}\\.){3}\\d{1,3}$") String clientIp,
        @Valid @NotNull RuleRequest rule
) {}
```

---

## Configuration

- Bind settings with `@ConfigurationProperties(prefix = "miniwsa")` records loaded from `application.yml` — no scattered `@Value("${...}")`.
- Define separate profiles (`application-test.yml`, `application-docker.yml`) instead of branching on environment in code.
- Register `@ConfigurationProperties` types via `@EnableConfigurationProperties` or `@ConfigurationPropertiesScan`, not as `@Component`.

---

## Error Handling

- One global `@RestControllerAdvice` mapping domain exceptions (defined in `exception/`) to HTTP responses.
- Use Spring Boot 3.2's built-in RFC 7807 `ProblemDetail` for structured error bodies — don't hand-roll `{"error": "..."}` maps.
- Never leak stack traces or internal messages in API responses; log them via SLF4J instead.

---

## Testing

**Rule:** Every new public method, endpoint, or component gets tests before the task is considered done. Cover at minimum: the happy path, key abnormalities (null/missing input, boundary values, invalid state, exception paths), and all meaningful enum/flag variations when behavior branches on them.

### Choose the right test type for the layer

| Layer | Test type | Annotation |
|---|---|---|
| Service / enrichment / validation logic | Unit test | `@ExtendWith(MockitoExtension.class)` |
| Controller (HTTP/JSON contract) | Slice test | `@WebMvcTest(FooController.class)` |
| Redis / ClickHouse / external store | Integration test | `@Testcontainers` + real container |

Never use `@SpringBootTest` for unit or slice tests — it boots the full context and is slow.

### Unit test pattern (services, enrichment, validators)

```java
@ExtendWith(MockitoExtension.class)
class FooServiceTest {

    @Mock private FooRepository repository;
    private FooService service;

    @BeforeEach
    void setUp() {
        service = new FooService(repository);
    }

    @Test
    void returnsEnrichedResultOnValidInput() {
        when(repository.find(any())).thenReturn(Optional.of(someEntity()));
        var result = service.process(validRequest());
        assertThat(result.status()).isEqualTo("accepted");
    }

    @Test
    void throwsDomainExceptionWhenEntityNotFound() {
        when(repository.find(any())).thenReturn(Optional.empty());
        assertThatThrownBy(() -> service.process(validRequest()))
                .isInstanceOf(EntityNotFoundException.class);
    }
}
```

Use `lenient().when(...)` only for setup mocks that not all tests will trigger — don't use it to suppress real "unnecessary stubbing" warnings.

### Controller slice test pattern

```java
@WebMvcTest(FooController.class)
class FooControllerTest {

    @Autowired MockMvc mockMvc;
    @MockBean FooService fooService;

    @Test
    void validRequestReturns201() throws Exception {
        when(fooService.process(any())).thenReturn(successResponse());

        mockMvc.perform(post("/v1/foo")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{ \"id\": \"abc\" }"))
                .andExpect(status().isCreated())
                .andExpect(jsonPath("$.status").value("accepted"));
    }

    @Test
    void malformedJsonReturns400() throws Exception {
        mockMvc.perform(post("/v1/foo")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{ not json }"))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.status").value(400));
    }
}
```

Always cover: valid input → expected status + response shape; domain exception → correct HTTP status; unparseable JSON → 400.

### Integration test pattern (Testcontainers)

```java
@Testcontainers
@SpringBootTest
class FooRepositoryIT {

    @Container
    static RedisContainer redis = new RedisContainer(DockerImageName.parse("redis:7-alpine"));

    @DynamicPropertySource
    static void redisProps(DynamicPropertyRegistry registry) {
        registry.add("spring.data.redis.host", redis::getHost);
        registry.add("spring.data.redis.port", () -> redis.getMappedPort(6379));
    }

    @Autowired FooRepository repository;

    @Test
    void persistsAndRetrievesEntry() {
        repository.save("key", "value");
        assertThat(repository.get("key")).isEqualTo("value");
    }
}
```

Name integration test classes `*IT` (e.g., `RepeatOffenderCacheIT`).

### Naming and structure

- Class: `<ClassUnderTest>Test` for unit/slice, `<ClassUnderTest>IT` for Testcontainers tests
- Method: descriptive verb + condition — `addsPathBonusForAdminPath`, `rejectsEventWithMissingClientIp`, `throwsWhenCacheUnavailable`
- One logical concept per test; multiple `assertThat` lines are fine when they all verify the same result
- Place domain-object factory helpers (`private SecurityEvent event(...)`) at the bottom of the class

### Parameterized tests for enum/table-driven logic

Use `@ParameterizedTest` whenever behavior branches on an enum or a known set of inputs:

```java
@ParameterizedTest
@EnumSource(Severity.class)
void appliesSeverityWeight(Severity severity) {
    int score = calculator.calculate(event(severity, Action.MONITOR, "/path"));
    int expected = switch (severity) {
        case CRITICAL -> 40; case HIGH -> 30; case MEDIUM -> 20; case LOW -> 10;
    };
    assertThat(score).isEqualTo(expected);
}

@ParameterizedTest
@CsvSource({ "DENY,20", "ALERT,10", "MONITOR,0" })
void appliesActionWeight(String action, int expectedBonus) { ... }
```

### Assertions

Use AssertJ (`assertThat(...)`) exclusively — never JUnit's `assertEquals` or Hamcrest matchers.

---

## What to Avoid

- Flat `util`/`common`/`misc`/`helpers` dumping packages — every class belongs to a layer.
- Field injection (`@Autowired private Foo foo`) — use constructor injection.
- Returning JPA entities directly from controllers or serializing them to JSON.
- Catching broad `Exception`/`Throwable` and swallowing it — convert to a domain exception or let it propagate to the advice.
- Floating dependency versions (`3.+`, `LATEST`) in `pom.xml`/`build.gradle`.
- `System.out.println` for logging — use `private static final Logger log = LoggerFactory.getLogger(ClassName.class)`.
- We love logs so please incorporate the. Log in info logs anything essential to understand the general picture of the flow, warnings for anything abnormal or unexpected and any field related to that issue, in error logs the same - but error only on critical system issues.
- Public mutable static state or singletons created outside the Spring container.
