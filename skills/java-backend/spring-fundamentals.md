# Spring Boot Fundamentals

Reference file for the `java-backend` skill. Covers project structure, application entry point, multi-profile YAML configuration, @ConfigurationProperties, and Actuator endpoints.

## 1. Spring Boot Fundamentals

### Project Structure

```
src/
├── main/
│   ├── java/com/example/myapp/
│   │   ├── MyAppApplication.java          # @SpringBootApplication entry point
│   │   ├── config/                        # @Configuration classes
│   │   ├── controller/                    # @RestController classes
│   │   ├── service/                       # @Service business logic
│   │   ├── repository/                    # JpaRepository interfaces
│   │   ├── model/
│   │   │   ├── entity/                    # @Entity JPA classes
│   │   │   └── dto/                       # Request/Response DTOs
│   │   ├── mapper/                        # MapStruct mappers
│   │   ├── exception/                     # Custom exceptions + @ControllerAdvice
│   │   └── security/                      # Security configuration
│   └── resources/
│       ├── application.yml                # Default config
│       ├── application-dev.yml            # Dev profile overrides
│       ├── application-test.yml           # Test profile overrides
│       ├── application-prod.yml           # Prod profile overrides
│       └── db/migration/                  # Flyway migrations
└── test/
    └── java/com/example/myapp/
        ├── controller/                    # @WebMvcTest slices
        ├── service/                       # Unit tests with Mockito
        ├── repository/                    # @DataJpaTest slices
        └── integration/                   # @SpringBootTest full context
```

### Application Entry Point

```java
@SpringBootApplication
public class MyAppApplication {
    public static void main(String[] args) {
        SpringApplication.run(MyAppApplication.class, args);
    }
}
```

`@SpringBootApplication` combines `@Configuration`, `@EnableAutoConfiguration`, and `@ComponentScan`. Auto-configuration detects classpath dependencies and configures beans automatically (e.g. DataSource if H2/PostgreSQL driver is present, Jackson if jackson-databind is present).

### application.yml — Multi-Profile Configuration

```yaml
# Default (all profiles)
spring:
  application:
    name: my-app
  jackson:
    default-property-inclusion: non_null
    serialization:
      write-dates-as-timestamps: false

server:
  port: 8080
  shutdown: graceful

management:
  endpoints:
    web:
      exposure:
        include: health,info,metrics,prometheus
  endpoint:
    health:
      show-details: when-authorized

---
# Dev profile
spring:
  config:
    activate:
      on-profile: dev
  datasource:
    url: jdbc:postgresql://localhost:5432/myapp_dev
    username: dev_user
    password: dev_pass
  jpa:
    show-sql: true
    properties:
      hibernate:
        format_sql: true

logging:
  level:
    com.example.myapp: DEBUG
    org.hibernate.SQL: DEBUG
    org.hibernate.orm.jdbc.bind: TRACE

---
# Production profile
spring:
  config:
    activate:
      on-profile: prod
  datasource:
    url: ${DB_URL}
    username: ${DB_USERNAME}
    password: ${DB_PASSWORD}
  jpa:
    show-sql: false
    open-in-view: false

logging:
  level:
    com.example.myapp: INFO
    root: WARN
```

### @ConfigurationProperties — Type-Safe Configuration

```java
@ConfigurationProperties(prefix = "app.notification")
@Validated
public record NotificationProperties(
    @NotBlank String fromEmail,
    @Min(1) @Max(100) int batchSize,
    Duration retryDelay,
    Map<String, String> templates
) {}
```

```yaml
app:
  notification:
    from-email: noreply@example.com
    batch-size: 25
    retry-delay: 30s
    templates:
      welcome: email/welcome.html
      reset: email/reset-password.html
```

Enable on the application class or a config class:

```java
@SpringBootApplication
@ConfigurationPropertiesScan
public class MyAppApplication { }
```

### Actuator Endpoints

Key actuator endpoints for production: `/actuator/health` (liveness/readiness), `/actuator/metrics` (Micrometer), `/actuator/prometheus` (Prometheus scrape), `/actuator/info` (build info). Secure actuator endpoints in production — never expose `/actuator/env` or `/actuator/configprops` publicly.

---

