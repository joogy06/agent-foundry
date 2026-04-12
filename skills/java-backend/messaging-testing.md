# Messaging and Testing

Reference file for the `java-backend` skill. Covers messaging (Kafka producer/consumer, RabbitMQ, Spring Events, outbox pattern) and testing (JUnit 5, Mockito, MockMvc, @DataJpaTest, Testcontainers, contract testing).

## 7. Messaging

### Spring JMS — IBM MQ Integration

```xml
<dependency>
    <groupId>com.ibm.mq</groupId>
    <artifactId>mq-jms-spring-boot-starter</artifactId>
    <version>3.3.3</version>
</dependency>
```

```yaml
ibm:
  mq:
    queue-manager: QM1
    channel: DEV.APP.SVRCONN
    conn-name: mqserver(1414)
    user: app
    password: ${MQ_PASSWORD}
```

```java
@Service
@RequiredArgsConstructor
@Slf4j
public class MqOrderPublisher {

    private final JmsTemplate jmsTemplate;
    private final ObjectMapper objectMapper;

    public void publishOrderEvent(OrderEvent event) {
        try {
            String json = objectMapper.writeValueAsString(event);
            jmsTemplate.convertAndSend("DEV.QUEUE.ORDER.EVENTS", json, message -> {
                message.setStringProperty("eventType", event.type().name());
                message.setJMSCorrelationID(event.correlationId());
                return message;
            });
            log.info("Published order event: type={}, orderId={}", event.type(), event.orderId());
        } catch (JsonProcessingException e) {
            throw new MessagingException("Failed to serialize order event", e);
        }
    }
}

@Component
@Slf4j
public class MqOrderListener {

    @JmsListener(destination = "DEV.QUEUE.ORDER.EVENTS", concurrency = "3-10")
    public void onOrderEvent(Message message) throws JMSException {
        String body = ((TextMessage) message).getText();
        String eventType = message.getStringProperty("eventType");
        log.info("Received order event: type={}, messageId={}", eventType, message.getJMSMessageID());
        // Process event...
    }
}
```

### Spring Kafka

```yaml
spring:
  kafka:
    bootstrap-servers: kafka-1:9092,kafka-2:9092,kafka-3:9092
    producer:
      key-serializer: org.apache.kafka.common.serialization.StringSerializer
      value-serializer: org.springframework.kafka.support.serializer.JsonSerializer
      acks: all
      retries: 3
      properties:
        enable.idempotence: true
    consumer:
      group-id: order-service
      key-deserializer: org.apache.kafka.common.serialization.StringDeserializer
      value-deserializer: org.springframework.kafka.support.serializer.JsonDeserializer
      auto-offset-reset: earliest
      properties:
        spring.json.trusted.packages: com.example.myapp.model.event
```

```java
@Service
@RequiredArgsConstructor
@Slf4j
public class KafkaOrderPublisher {

    private final KafkaTemplate<String, OrderEvent> kafkaTemplate;

    public void publish(OrderEvent event) {
        kafkaTemplate.send("order-events", String.valueOf(event.orderId()), event)
            .whenComplete((result, ex) -> {
                if (ex != null) {
                    log.error("Failed to publish order event: orderId={}", event.orderId(), ex);
                } else {
                    log.info("Published to partition={}, offset={}",
                        result.getRecordMetadata().partition(),
                        result.getRecordMetadata().offset());
                }
            });
    }
}

@Component
@Slf4j
public class KafkaOrderConsumer {

    @KafkaListener(topics = "order-events", groupId = "order-service",
        concurrency = "3", containerFactory = "kafkaListenerContainerFactory")
    @RetryableTopic(
        attempts = "3",
        backoff = @Backoff(delay = 1000, multiplier = 2),
        dltTopicSuffix = ".dlt",
        autoCreateTopics = "true"
    )
    public void consume(OrderEvent event, @Header(KafkaHeaders.RECEIVED_TOPIC) String topic) {
        log.info("Consumed order event: orderId={}, topic={}", event.orderId(), topic);
        // Process with idempotency check...
    }

    @DltHandler
    public void handleDlt(OrderEvent event) {
        log.error("Dead letter — failed to process order event after retries: orderId={}",
            event.orderId());
        // Alert, persist to dead letter table, etc.
    }
}
```

### Spring AMQP — RabbitMQ

```java
@Configuration
public class RabbitConfig {

    @Bean
    public TopicExchange orderExchange() {
        return new TopicExchange("order.exchange");
    }

    @Bean
    public Queue orderQueue() {
        return QueueBuilder.durable("order.queue")
            .withArgument("x-dead-letter-exchange", "order.dlx")
            .withArgument("x-dead-letter-routing-key", "order.dead")
            .build();
    }

    @Bean
    public Binding orderBinding(Queue orderQueue, TopicExchange orderExchange) {
        return BindingBuilder.bind(orderQueue).to(orderExchange).with("order.#");
    }
}

@RabbitListener(queues = "order.queue")
public void handleOrderMessage(OrderEvent event, Channel channel,
        @Header(AmqpHeaders.DELIVERY_TAG) long tag) throws IOException {
    try {
        processOrder(event);
        channel.basicAck(tag, false);
    } catch (Exception e) {
        log.error("Failed to process order event", e);
        channel.basicNack(tag, false, false);  // Send to DLQ
    }
}
```

### Idempotent Consumer Pattern

```java
@Service
@RequiredArgsConstructor
public class IdempotentOrderProcessor {

    private final ProcessedEventRepository processedEventRepo;

    @Transactional
    public void process(OrderEvent event) {
        String eventId = event.eventId();
        if (processedEventRepo.existsById(eventId)) {
            log.info("Duplicate event ignored: eventId={}", eventId);
            return;
        }
        // Process the event...
        processedEventRepo.save(new ProcessedEvent(eventId, Instant.now()));
    }
}
```

---

## 8. Testing

### JUnit 5 — Unit Test with Mockito

```java
@ExtendWith(MockitoExtension.class)
class OrderServiceTest {

    @Mock OrderRepository orderRepository;
    @Mock CustomerRepository customerRepository;
    @Mock ProductRepository productRepository;
    @Mock OrderMapper orderMapper;
    @Mock ApplicationEventPublisher eventPublisher;
    @InjectMocks OrderService orderService;
    @Captor ArgumentCaptor<OrderCreatedEvent> eventCaptor;

    @Test
    void create_validRequest_savesOrderAndPublishesEvent() {
        // Given
        var customer = new Customer();
        customer.setId(1L);
        var product = new Product();
        product.setId(10L);
        product.setPrice(new BigDecimal("29.99"));

        var request = new CreateOrderRequest(1L,
            List.of(new OrderItemRequest(10L, 2)), "Rush order");

        when(customerRepository.findById(1L)).thenReturn(Optional.of(customer));
        when(productRepository.findById(10L)).thenReturn(Optional.of(product));
        when(orderRepository.save(any(Order.class))).thenAnswer(inv -> {
            Order o = inv.getArgument(0);
            o.setId(100L);
            return o;
        });
        when(orderMapper.toResponse(any())).thenReturn(
            new OrderResponse(100L, "John", OrderStatus.PENDING,
                new BigDecimal("59.98"), List.of(), Instant.now(), Instant.now()));

        // When
        OrderResponse response = orderService.create(request);

        // Then
        assertThat(response.id()).isEqualTo(100L);
        assertThat(response.totalAmount()).isEqualByComparingTo("59.98");

        verify(orderRepository).save(any(Order.class));
        verify(eventPublisher).publishEvent(eventCaptor.capture());
        assertThat(eventCaptor.getValue().orderId()).isEqualTo(100L);
    }

    @Test
    void findById_notFound_throwsResourceNotFoundException() {
        when(orderRepository.findByIdWithDetails(999L)).thenReturn(Optional.empty());

        assertThatThrownBy(() -> orderService.findById(999L))
            .isInstanceOf(ResourceNotFoundException.class)
            .hasMessageContaining("Order")
            .hasMessageContaining("999");
    }

    @Nested
    class DeleteTests {

        @Test
        void delete_existingOrder_deletesSuccessfully() {
            when(orderRepository.existsById(1L)).thenReturn(true);
            orderService.delete(1L);
            verify(orderRepository).deleteById(1L);
        }

        @Test
        void delete_nonExistentOrder_throwsNotFound() {
            when(orderRepository.existsById(999L)).thenReturn(false);
            assertThatThrownBy(() -> orderService.delete(999L))
                .isInstanceOf(ResourceNotFoundException.class);
        }
    }

    @ParameterizedTest
    @EnumSource(value = OrderStatus.class, names = {"PENDING", "CONFIRMED", "SHIPPED"})
    void findByStatus_validStatuses_returnsPage(OrderStatus status) {
        when(orderRepository.findByStatusOrderByCreatedAtDesc(eq(status), any()))
            .thenReturn(Page.empty());

        Page<OrderResponse> result = orderService.findByStatus(status, Pageable.ofSize(10));

        assertThat(result).isNotNull();
        verify(orderRepository).findByStatusOrderByCreatedAtDesc(status, Pageable.ofSize(10));
    }
}
```

### @WebMvcTest — Controller Slice

```java
@WebMvcTest(OrderController.class)
@Import(SecurityConfig.class)
class OrderControllerTest {

    @Autowired MockMvc mockMvc;
    @Autowired ObjectMapper objectMapper;
    @MockBean OrderService orderService;

    @Test
    @WithMockUser
    void createOrder_validRequest_returns201() throws Exception {
        var request = new CreateOrderRequest(1L,
            List.of(new OrderItemRequest(10L, 2)), null);
        var response = new OrderResponse(1L, "John", OrderStatus.PENDING,
            new BigDecimal("59.98"), List.of(), Instant.now(), Instant.now());

        when(orderService.create(any())).thenReturn(response);

        mockMvc.perform(post("/api/v1/orders")
                .contentType(MediaType.APPLICATION_JSON)
                .content(objectMapper.writeValueAsString(request)))
            .andExpect(status().isCreated())
            .andExpect(jsonPath("$.id").value(1))
            .andExpect(jsonPath("$.status").value("PENDING"))
            .andExpect(jsonPath("$.totalAmount").value(59.98));
    }

    @Test
    @WithMockUser
    void createOrder_invalidRequest_returns400WithFieldErrors() throws Exception {
        var request = new CreateOrderRequest(null, List.of(), null);  // Missing required fields

        mockMvc.perform(post("/api/v1/orders")
                .contentType(MediaType.APPLICATION_JSON)
                .content(objectMapper.writeValueAsString(request)))
            .andExpect(status().isBadRequest())
            .andExpect(jsonPath("$.title").value("Validation Failed"))
            .andExpect(jsonPath("$.fieldErrors.customerId").exists())
            .andExpect(jsonPath("$.fieldErrors.items").exists());
    }

    @Test
    @WithMockUser
    void listOrders_withPagination_returns200() throws Exception {
        when(orderService.findByStatus(any(), any())).thenReturn(Page.empty());

        mockMvc.perform(get("/api/v1/orders")
                .param("status", "PENDING")
                .param("page", "0")
                .param("size", "20"))
            .andExpect(status().isOk())
            .andExpect(jsonPath("$.content").isArray());
    }
}
```

### @DataJpaTest — Repository Slice

```java
@DataJpaTest
@AutoConfigureTestDatabase(replace = AutoConfigureTestDatabase.Replace.NONE)
@Testcontainers
class OrderRepositoryTest {

    @Container
    static PostgreSQLContainer<?> postgres = new PostgreSQLContainer<>("postgres:16-alpine")
        .withDatabaseName("testdb");

    @DynamicPropertySource
    static void overrideProperties(DynamicPropertyRegistry registry) {
        registry.add("spring.datasource.url", postgres::getJdbcUrl);
        registry.add("spring.datasource.username", postgres::getUsername);
        registry.add("spring.datasource.password", postgres::getPassword);
    }

    @Autowired OrderRepository orderRepository;
    @Autowired TestEntityManager em;

    @Test
    void findByIdWithDetails_existingOrder_loadsAllRelationships() {
        // Given
        Customer customer = new Customer();
        customer.setName("Jane Doe");
        customer.setEmail("jane@example.com");
        em.persist(customer);

        Product product = new Product();
        product.setName("Widget");
        product.setPrice(new BigDecimal("19.99"));
        em.persist(product);

        Order order = new Order();
        order.setCustomer(customer);
        order.setStatus(OrderStatus.PENDING);
        order.setTotalAmount(new BigDecimal("39.98"));
        OrderItem item = new OrderItem();
        item.setProduct(product);
        item.setQuantity(2);
        item.setUnitPrice(product.getPrice());
        order.addItem(item);
        em.persistAndFlush(order);
        em.clear();  // Clear persistence context to force fresh load

        // When
        Optional<Order> result = orderRepository.findByIdWithDetails(order.getId());

        // Then
        assertThat(result).isPresent();
        assertThat(result.get().getCustomer().getName()).isEqualTo("Jane Doe");
        assertThat(result.get().getItems()).hasSize(1);
        assertThat(result.get().getItems().get(0).getProduct().getName()).isEqualTo("Widget");
    }
}
```

### @SpringBootTest — Full Integration Test with Testcontainers

```java
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
@Testcontainers
class OrderIntegrationTest {

    @Container
    static PostgreSQLContainer<?> postgres = new PostgreSQLContainer<>("postgres:16-alpine");

    @Container
    static KafkaContainer kafka = new KafkaContainer(
        DockerImageName.parse("confluentinc/cp-kafka:7.6.0"));

    @DynamicPropertySource
    static void overrideProperties(DynamicPropertyRegistry registry) {
        registry.add("spring.datasource.url", postgres::getJdbcUrl);
        registry.add("spring.datasource.username", postgres::getUsername);
        registry.add("spring.datasource.password", postgres::getPassword);
        registry.add("spring.kafka.bootstrap-servers", kafka::getBootstrapServers);
    }

    @Autowired TestRestTemplate restTemplate;
    @Autowired OrderRepository orderRepository;

    @Test
    void orderLifecycle_createAndRetrieve() {
        // Create
        var request = new CreateOrderRequest(1L,
            List.of(new OrderItemRequest(10L, 2)), null);

        ResponseEntity<OrderResponse> createResp = restTemplate.postForEntity(
            "/api/v1/orders", request, OrderResponse.class);

        assertThat(createResp.getStatusCode()).isEqualTo(HttpStatus.CREATED);
        Long orderId = createResp.getBody().id();

        // Retrieve
        ResponseEntity<OrderResponse> getResp = restTemplate.getForEntity(
            "/api/v1/orders/{id}", OrderResponse.class, orderId);

        assertThat(getResp.getStatusCode()).isEqualTo(HttpStatus.OK);
        assertThat(getResp.getBody().status()).isEqualTo(OrderStatus.PENDING);
    }
}
```

### WireMock — External Service Mocking

```java
@SpringBootTest
@WireMockTest(httpPort = 9090)
class PaymentClientTest {

    @Autowired PaymentClient paymentClient;

    @Test
    void chargePayment_success_returnsConfirmation() {
        stubFor(post(urlPathEqualTo("/payments/charge"))
            .withHeader("Content-Type", equalTo("application/json"))
            .willReturn(aResponse()
                .withStatus(200)
                .withHeader("Content-Type", "application/json")
                .withBody("""
                    {"transactionId": "txn_123", "status": "COMPLETED"}
                    """)));

        PaymentResponse response = paymentClient.charge(new PaymentRequest("order_1", 59.98));

        assertThat(response.transactionId()).isEqualTo("txn_123");
        assertThat(response.status()).isEqualTo("COMPLETED");
    }

    @Test
    void chargePayment_timeout_throwsException() {
        stubFor(post(urlPathEqualTo("/payments/charge"))
            .willReturn(aResponse().withFixedDelay(5000)));

        assertThatThrownBy(() -> paymentClient.charge(new PaymentRequest("order_1", 59.98)))
            .isInstanceOf(WebClientRequestException.class);
    }
}
```

---

## 9. Build & Deployment

### Maven — pom.xml Essentials

```xml
<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0"
         xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
         xsi:schemaLocation="http://maven.apache.org/POM/4.0.0
         https://maven.apache.org/xsd/maven-4.0.0.xsd">
    <modelVersion>4.0.0</modelVersion>

    <parent>
        <groupId>org.springframework.boot</groupId>
        <artifactId>spring-boot-starter-parent</artifactId>
        <version>3.4.1</version>
    </parent>

    <groupId>com.example</groupId>
    <artifactId>my-app</artifactId>
    <version>1.0.0-SNAPSHOT</version>

    <properties>
        <java.version>21</java.version>
        <spring-cloud.version>2024.0.0</spring-cloud.version>
        <mapstruct.version>1.6.3</mapstruct.version>
    </properties>

    <dependencies>
        <dependency>
            <groupId>org.springframework.boot</groupId>
            <artifactId>spring-boot-starter-web</artifactId>
        </dependency>
        <dependency>
            <groupId>org.springframework.boot</groupId>
            <artifactId>spring-boot-starter-data-jpa</artifactId>
        </dependency>
        <dependency>
            <groupId>org.springframework.boot</groupId>
            <artifactId>spring-boot-starter-validation</artifactId>
        </dependency>
        <dependency>
            <groupId>org.springframework.boot</groupId>
            <artifactId>spring-boot-starter-security</artifactId>
        </dependency>
        <dependency>
            <groupId>org.springframework.boot</groupId>
            <artifactId>spring-boot-starter-actuator</artifactId>
        </dependency>
        <dependency>
            <groupId>org.flywaydb</groupId>
            <artifactId>flyway-core</artifactId>
        </dependency>
        <dependency>
            <groupId>org.flywaydb</groupId>
            <artifactId>flyway-database-postgresql</artifactId>
        </dependency>
        <dependency>
            <groupId>org.postgresql</groupId>
            <artifactId>postgresql</artifactId>
            <scope>runtime</scope>
        </dependency>
        <dependency>
            <groupId>org.mapstruct</groupId>
            <artifactId>mapstruct</artifactId>
            <version>${mapstruct.version}</version>
        </dependency>
        <dependency>
            <groupId>org.projectlombok</groupId>
            <artifactId>lombok</artifactId>
            <optional>true</optional>
        </dependency>

        <!-- Test -->
        <dependency>
            <groupId>org.springframework.boot</groupId>
            <artifactId>spring-boot-starter-test</artifactId>
            <scope>test</scope>
        </dependency>
        <dependency>
            <groupId>org.springframework.security</groupId>
            <artifactId>spring-security-test</artifactId>
            <scope>test</scope>
        </dependency>
        <dependency>
            <groupId>org.testcontainers</groupId>
            <artifactId>postgresql</artifactId>
            <scope>test</scope>
        </dependency>
        <dependency>
            <groupId>org.testcontainers</groupId>
            <artifactId>junit-jupiter</artifactId>
            <scope>test</scope>
        </dependency>
    </dependencies>

    <build>
        <plugins>
            <plugin>
                <groupId>org.springframework.boot</groupId>
                <artifactId>spring-boot-maven-plugin</artifactId>
                <configuration>
                    <excludes>
                        <exclude>
                            <groupId>org.projectlombok</groupId>
                            <artifactId>lombok</artifactId>
                        </exclude>
                    </excludes>
                </configuration>
            </plugin>
            <plugin>
                <groupId>org.apache.maven.plugins</groupId>
                <artifactId>maven-compiler-plugin</artifactId>
                <configuration>
                    <annotationProcessorPaths>
                        <path>
                            <groupId>org.projectlombok</groupId>
                            <artifactId>lombok</artifactId>
                        </path>
                        <path>
                            <groupId>org.mapstruct</groupId>
                            <artifactId>mapstruct-processor</artifactId>
                            <version>${mapstruct.version}</version>
                        </path>
                        <path>
                            <groupId>org.projectlombok</groupId>
                            <artifactId>lombok-mapstruct-binding</artifactId>
                            <version>0.2.0</version>
                        </path>
                    </annotationProcessorPaths>
                </configuration>
            </plugin>
        </plugins>
    </build>
</project>
```

### Gradle — build.gradle.kts

```kotlin
plugins {
    java
    id("org.springframework.boot") version "3.4.1"
    id("io.spring.dependency-management") version "1.1.7"
}

group = "com.example"
version = "1.0.0-SNAPSHOT"

java {
    toolchain {
        languageVersion = JavaLanguageVersion.of(21)
    }
}

configurations {
    compileOnly {
        extendsFrom(configurations.annotationProcessor.get())
    }
}

dependencies {
    implementation("org.springframework.boot:spring-boot-starter-web")
    implementation("org.springframework.boot:spring-boot-starter-data-jpa")
    implementation("org.springframework.boot:spring-boot-starter-validation")
    implementation("org.springframework.boot:spring-boot-starter-security")
    implementation("org.springframework.boot:spring-boot-starter-actuator")
    implementation("org.flywaydb:flyway-core")
    implementation("org.flywaydb:flyway-database-postgresql")
    implementation("org.mapstruct:mapstruct:1.6.3")

    runtimeOnly("org.postgresql:postgresql")

    compileOnly("org.projectlombok:lombok")
    annotationProcessor("org.projectlombok:lombok")
    annotationProcessor("org.mapstruct:mapstruct-processor:1.6.3")
    annotationProcessor("org.projectlombok:lombok-mapstruct-binding:0.2.0")

    testImplementation("org.springframework.boot:spring-boot-starter-test")
    testImplementation("org.springframework.security:spring-security-test")
    testImplementation("org.testcontainers:postgresql")
    testImplementation("org.testcontainers:junit-jupiter")
}

tasks.test {
    useJUnitPlatform()
}
```

### Multi-Stage Dockerfile

```dockerfile
# Stage 1: Build
FROM eclipse-temurin:21-jdk-alpine AS builder
WORKDIR /app
COPY .mvn/ .mvn/
COPY mvnw pom.xml ./
RUN ./mvnw dependency:go-offline -B
COPY src/ src/
RUN ./mvnw package -DskipTests -B

# Stage 2: Runtime (layered JAR)
FROM eclipse-temurin:21-jre-alpine
RUN addgroup -S appgroup && adduser -S appuser -G appgroup
WORKDIR /app

COPY --from=builder /app/target/*.jar app.jar

# Extract Spring Boot layers for better caching
RUN java -Djarmode=tools -jar app.jar extract --layers --launcher --destination extracted

FROM eclipse-temurin:21-jre-alpine
RUN addgroup -S appgroup && adduser -S appuser -G appgroup
WORKDIR /app

COPY --from=1 /app/extracted/dependencies/ ./
COPY --from=1 /app/extracted/spring-boot-loader/ ./
COPY --from=1 /app/extracted/snapshot-dependencies/ ./
COPY --from=1 /app/extracted/application/ ./

USER appuser
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=3s --retries=3 \
    CMD wget -qO- http://localhost:8080/actuator/health || exit 1

ENTRYPOINT ["java", \
    "-XX:+UseG1GC", \
    "-XX:MaxRAMPercentage=75.0", \
    "-Djava.security.egd=file:/dev/urandom", \
    "org.springframework.boot.loader.launch.JarLauncher"]
```

### Jib (Containerize without Dockerfile)

```xml
<!-- Maven plugin -->
<plugin>
    <groupId>com.google.cloud.tools</groupId>
    <artifactId>jib-maven-plugin</artifactId>
    <version>3.4.4</version>
    <configuration>
        <from>
            <image>eclipse-temurin:21-jre-alpine</image>
        </from>
        <to>
            <image>registry.example.com/my-app</image>
            <tags>
                <tag>${project.version}</tag>
                <tag>latest</tag>
            </tags>
        </to>
        <container>
            <jvmFlags>
                <jvmFlag>-XX:+UseG1GC</jvmFlag>
                <jvmFlag>-XX:MaxRAMPercentage=75.0</jvmFlag>
            </jvmFlags>
            <ports>
                <port>8080</port>
            </ports>
            <creationTime>USE_CURRENT_TIMESTAMP</creationTime>
        </container>
    </configuration>
</plugin>
```

```bash
# Build and push (no Docker daemon needed)
./mvnw jib:build

# Build to local Docker daemon
./mvnw jib:dockerBuild
```

### GraalVM Native Image

```xml
<!-- Use Spring Boot's native profile -->
<profiles>
    <profile>
        <id>native</id>
        <build>
            <plugins>
                <plugin>
                    <groupId>org.graalvm.buildtools</groupId>
                    <artifactId>native-maven-plugin</artifactId>
                </plugin>
            </plugins>
        </build>
    </profile>
</profiles>
```

```bash
# Build native image (requires GraalVM JDK)
./mvnw -Pnative native:compile

# Or build native container image
./mvnw -Pnative spring-boot:build-image
```

Native images start in ~100ms vs ~3-5s for JVM. Trade-off: longer build times, no runtime reflection without hints, limited library compatibility. Best for serverless/functions.

---

