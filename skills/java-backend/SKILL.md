---
name: java-backend
description: Use when developing Java backend applications — Spring Boot 3.x (auto-configuration, starters, actuator, profiles), Spring Security (OAuth2/OIDC, JWT, method security), Spring Data JPA/Hibernate (entity mapping, repositories, query methods, N+1 prevention), REST API design (controllers, validation, error handling, HATEOAS), microservices patterns (service discovery, circuit breaker, API gateway, config server), testing (JUnit 5, Mockito, Testcontainers, MockMvc), build tools (Maven/Gradle), and Jakarta EE patterns. Part of the java-* skill family.
---

# Java Backend Development

Covers Spring Boot 3.x, Spring Security, Spring Data JPA, REST APIs, microservices, messaging, testing, build tooling, performance, and Jakarta EE patterns. For IBM WebSphere/Liberty deployments see `ibm-websphere`. For IBM MQ messaging see `ibm-mq`. For database administration see `rhel-databases` or `ubuntu-databases`.

<HARD-RULE>
Always use DTOs for API request/response — never expose JPA entities directly. Exposing entities leaks internal schema, breaks encapsulation, and causes lazy loading exceptions during serialization. Use MapStruct or manual mapping between entities and DTOs.
</HARD-RULE>

<HARD-RULE>
Never use @Transactional on private methods — Spring proxies only intercept public methods. A @Transactional annotation on a private method silently does nothing; the code runs without a transaction boundary and data integrity is at risk.
</HARD-RULE>

<HARD-RULE>
Always define fetch strategy explicitly on JPA relationships — the default EAGER fetch on @ManyToOne and @OneToOne causes N+1 queries that destroy performance at scale. Set fetch = FetchType.LAZY on every relationship and use @EntityGraph or JOIN FETCH for controlled eager loading.
</HARD-RULE>

<HARD-RULE>
Never catch and swallow exceptions in the service layer without logging — silent catch blocks make production debugging impossible. At minimum log the exception at ERROR level with full stack trace. Prefer letting exceptions propagate to a @ControllerAdvice handler.
</HARD-RULE>

---

## Reference Files

Detailed code examples, patterns, and configuration are in the reference files below. Read the relevant file when working on that area.

| File | Covers |
|---|---|
| [build-performance-jakartaee.md](build-performance-jakartaee.md) | build and deployment (Maven/Gradle, multi-stage Docker, Jib, GraalVM native image), performance and observability (connection pooling, caching, Micrometer metrics, structured logging), and Jakarta EE patterns |
| [messaging-testing.md](messaging-testing.md) | messaging (Kafka producer/consumer, RabbitMQ, Spring Events, outbox pattern) and testing (JUnit 5, Mockito, MockMvc, @DataJpaTest, Testcontainers, contract testing) |
| [rest-api-design.md](rest-api-design.md) | controllers with validation and pagination, DTO pattern with MapStruct, global exception handling with @ControllerAdvice, and HATEOAS |
| [service-microservices.md](service-microservices.md) | service layer patterns (transactions, retry, caching, events), microservices (service discovery, circuit breaker/Resilience4j, API gateway, distributed tracing, config server) |
| [spring-data-jpa.md](spring-data-jpa.md) | entity mapping, repository interfaces, query methods and @Query, projections, N+1 prevention (@EntityGraph, JOIN FETCH), auditing, and Flyway migrations |
| [spring-fundamentals.md](spring-fundamentals.md) | project structure, application entry point, multi-profile YAML configuration, @ConfigurationProperties, and Actuator endpoints |
| [spring-security.md](spring-security.md) | SecurityFilterChain configuration, JWT authentication with OAuth2 resource server, method-level security (@PreAuthorize), CORS configuration, and CSRF handling |

---

---

## Anti-Patterns

| Anti-Pattern | Why It Fails | Correct Approach |
|---|---|---|
| N+1 query problem with JPA lazy loading | Fetching a list then accessing each entity's relation fires N additional queries; destroys performance | Use JOIN FETCH in JPQL, @EntityGraph, or batch size hints; monitor query count with Hibernate statistics |
| Catching generic Exception everywhere | Swallows unexpected errors; masks bugs; makes debugging impossible; violates fail-fast principle | Catch specific exceptions; let unexpected ones propagate to global handler; log with full stack trace |
| Not using constructor injection in Spring | Field injection hides dependencies, prevents immutability, makes testing harder, and breaks with final fields | Use constructor injection (Lombok @RequiredArgsConstructor); makes dependencies explicit and testable |
| Blocking calls in reactive/WebFlux endpoints | One blocking call exhausts the event loop thread pool; entire application stops responding | Use .subscribeOn(Schedulers.boundedElastic()) for blocking calls; prefer non-blocking drivers |
| Exposing JPA entities directly as REST responses | Tight coupling between DB schema and API; any schema change breaks clients; serialization of lazy proxies causes errors | Use DTOs/records for API responses; map entities to DTOs in a service layer |

---

## Related Skills

| Domain | Skill |
|---|---|
| IBM WebSphere/Liberty deployment | `ibm-websphere` |
| IBM MQ messaging | `ibm-mq` |
| PostgreSQL/MySQL/Redis administration | `rhel-databases`, `ubuntu-databases` |
| Docker containerization | `docker-fundamentals`, `docker-admin` |
| Python Flask/FastAPI alternative | `python-flask-developer` |
| Authentication and security patterns | `python-auth-security` |
| CI/CD with Docker | `docker-cicd` |
| Microservices architecture | `saas-architecture` |
| MongoDB (NoSQL alternative) | `mongodb` |
| DB2 database integration | `db2-rhel`, `db2-mainframe` |
