# Build, Performance, and Jakarta EE

Reference file for the `java-backend` skill. Covers build and deployment (Maven/Gradle, multi-stage Docker, Jib, GraalVM native image), performance and observability (connection pooling, caching, Micrometer metrics, structured logging), and Jakarta EE patterns.

## 10. Performance & Observability

### JVM Tuning

```bash
# Container-aware JVM flags (Java 17+)
java \
  -XX:+UseG1GC \                      # General purpose — low pause, good throughput
  -XX:MaxRAMPercentage=75.0 \         # Use 75% of container memory limit
  -XX:+UseStringDeduplication \        # Reduce heap for string-heavy apps
  -XX:+ExitOnOutOfMemoryError \        # Fail fast on OOM — let orchestrator restart
  -Xlog:gc*:file=/var/log/app/gc.log:time,uptime:filecount=5,filesize=50M \
  -jar app.jar

# Low-latency alternative (Java 21+)
java -XX:+UseZGC -XX:+ZGenerational -XX:MaxRAMPercentage=75.0 -jar app.jar

# High-throughput alternative
java -XX:+UseShenandoahGC -XX:MaxRAMPercentage=75.0 -jar app.jar
```

G1GC: default, good all-around. ZGC: sub-millisecond pauses, best for large heaps (>4GB). Shenandoah: similar to ZGC, available in OpenJDK builds.

### Micrometer Metrics + Prometheus

```yaml
management:
  endpoints:
    web:
      exposure:
        include: health,info,metrics,prometheus
  metrics:
    tags:
      application: ${spring.application.name}
    distribution:
      percentiles-histogram:
        http.server.requests: true
      slo:
        http.server.requests: 50ms, 100ms, 250ms, 500ms, 1s
```

```java
// Custom business metric
@Service
@RequiredArgsConstructor
public class OrderService {

    private final MeterRegistry meterRegistry;

    public OrderResponse create(CreateOrderRequest request) {
        Timer.Sample timer = Timer.start(meterRegistry);
        try {
            OrderResponse response = doCreate(request);
            meterRegistry.counter("orders.created",
                "status", "success").increment();
            return response;
        } catch (Exception e) {
            meterRegistry.counter("orders.created",
                "status", "failure").increment();
            throw e;
        } finally {
            timer.stop(Timer.builder("orders.create.duration")
                .description("Time to create an order")
                .register(meterRegistry));
        }
    }
}
```

### Structured Logging — Logback + JSON

`src/main/resources/logback-spring.xml`:

```xml
<configuration>
    <!-- Console (human-readable) for dev -->
    <springProfile name="dev">
        <appender name="CONSOLE" class="ch.qos.logback.core.ConsoleAppender">
            <encoder>
                <pattern>%d{HH:mm:ss.SSS} %highlight(%-5level) [%thread] %cyan(%logger{36}) - %msg%n</pattern>
            </encoder>
        </appender>
        <root level="INFO">
            <appender-ref ref="CONSOLE"/>
        </root>
    </springProfile>

    <!-- JSON (structured) for prod — parseable by ELK/Loki -->
    <springProfile name="prod">
        <appender name="JSON" class="ch.qos.logback.core.ConsoleAppender">
            <encoder class="net.logstash.logback.encoder.LogstashEncoder">
                <includeMdcKeyName>traceId</includeMdcKeyName>
                <includeMdcKeyName>spanId</includeMdcKeyName>
            </encoder>
        </appender>
        <root level="INFO">
            <appender-ref ref="JSON"/>
        </root>
    </springProfile>
</configuration>
```

Add `net.logstash.logback:logstash-logback-encoder:8.0` dependency.

### HikariCP Connection Pool Tuning

```yaml
spring:
  datasource:
    hikari:
      maximum-pool-size: 20          # Start at 2x CPU cores, tune from there
      minimum-idle: 5
      idle-timeout: 300000           # 5 minutes
      max-lifetime: 1800000          # 30 minutes (must be < DB wait_timeout)
      connection-timeout: 30000      # 30 seconds
      validation-timeout: 5000
      leak-detection-threshold: 60000  # Log warning if connection held >60s
```

Monitor via Micrometer: `hikaricp.connections.active`, `hikaricp.connections.pending`, `hikaricp.connections.timeout`.

### Caching — @Cacheable with Redis/Caffeine

```java
@Configuration
@EnableCaching
public class CacheConfig {

    // Local cache (Caffeine) — for small, frequently accessed data
    @Bean
    public CacheManager caffeineCacheManager() {
        CaffeineCacheManager manager = new CaffeineCacheManager();
        manager.setCaffeine(Caffeine.newBuilder()
            .maximumSize(1000)
            .expireAfterWrite(Duration.ofMinutes(10))
            .recordStats());
        return manager;
    }
}
```

```java
@Service
public class ProductService {

    @Cacheable(value = "products", key = "#id")
    public ProductResponse findById(Long id) {
        // Expensive DB call — result cached
        return productRepository.findById(id)
            .map(productMapper::toResponse)
            .orElseThrow(() -> new ResourceNotFoundException("Product", id));
    }

    @CacheEvict(value = "products", key = "#id")
    public ProductResponse update(Long id, UpdateProductRequest request) {
        // Cache evicted after update
    }

    @CacheEvict(value = "products", allEntries = true)
    @Scheduled(fixedRate = 3600000)  // Evict all every hour as safety net
    public void evictAllProducts() {}
}
```

For Redis cache (distributed), use `spring-boot-starter-data-redis` and configure `RedisCacheManager` with TTL per cache name.

### Async Processing

```java
@Configuration
@EnableAsync
public class AsyncConfig {

    @Bean
    public TaskExecutor asyncExecutor() {
        ThreadPoolTaskExecutor executor = new ThreadPoolTaskExecutor();
        executor.setCorePoolSize(4);
        executor.setMaxPoolSize(16);
        executor.setQueueCapacity(100);
        executor.setThreadNamePrefix("async-");
        executor.setRejectedExecutionHandler(new ThreadPoolExecutor.CallerRunsPolicy());
        executor.initialize();
        return executor;
    }
}

@Service
public class ReportService {

    @Async
    public CompletableFuture<byte[]> generateReport(ReportRequest request) {
        // Long-running operation runs on async thread pool
        byte[] pdf = buildPdf(request);
        return CompletableFuture.completedFuture(pdf);
    }
}
```

---

## 11. Jakarta EE

### When to Use Jakarta EE vs Spring Boot

Use **Spring Boot** for: greenfield microservices, cloud-native apps, rapid prototyping, when the team already knows Spring. Use **Jakarta EE** for: existing enterprise apps on WAS/Liberty, when mandated by corporate standards, when vendor-neutral spec compliance is required.

### CDI (Contexts and Dependency Injection)

```java
// Jakarta CDI equivalent of Spring's @Service + @Autowired
@ApplicationScoped
public class OrderService {

    @Inject
    private OrderRepository orderRepository;

    @Inject
    private Event<OrderCreatedEvent> orderCreatedEvent;

    public Order createOrder(OrderRequest request) {
        Order order = mapToEntity(request);
        Order saved = orderRepository.save(order);
        orderCreatedEvent.fire(new OrderCreatedEvent(saved.getId()));
        return saved;
    }
}
```

### JAX-RS (REST APIs)

```java
@Path("/api/v1/orders")
@Produces(MediaType.APPLICATION_JSON)
@Consumes(MediaType.APPLICATION_JSON)
@ApplicationScoped
public class OrderResource {

    @Inject
    private OrderService orderService;

    @GET
    public Response listOrders(@QueryParam("status") String status,
                                @QueryParam("page") @DefaultValue("0") int page,
                                @QueryParam("size") @DefaultValue("20") int size) {
        List<OrderResponse> orders = orderService.findByStatus(status, page, size);
        return Response.ok(orders).build();
    }

    @GET
    @Path("/{id}")
    public Response getOrder(@PathParam("id") Long id) {
        return orderService.findById(id)
            .map(Response::ok)
            .orElse(Response.status(Response.Status.NOT_FOUND))
            .build();
    }

    @POST
    public Response createOrder(@Valid CreateOrderRequest request) {
        OrderResponse created = orderService.create(request);
        return Response.status(Response.Status.CREATED).entity(created).build();
    }
}
```

### JPA in Jakarta EE (Entity Manager)

```java
@ApplicationScoped
public class OrderRepository {

    @PersistenceContext
    private EntityManager em;

    public Optional<Order> findById(Long id) {
        return Optional.ofNullable(em.find(Order.class, id));
    }

    @Transactional
    public Order save(Order order) {
        if (order.getId() == null) {
            em.persist(order);
            return order;
        }
        return em.merge(order);
    }

    public List<Order> findByStatus(String status, int page, int size) {
        return em.createQuery(
                "SELECT o FROM Order o WHERE o.status = :status ORDER BY o.createdAt DESC",
                Order.class)
            .setParameter("status", OrderStatus.valueOf(status))
            .setFirstResult(page * size)
            .setMaxResults(size)
            .getResultList();
    }
}
```

### JMS in Jakarta EE

```java
@ApplicationScoped
public class JmsOrderPublisher {

    @Inject
    @JMSConnectionFactory("jms/orderCF")
    private JMSContext jmsContext;

    @Resource(lookup = "jms/orderQueue")
    private Queue orderQueue;

    public void publishOrderEvent(OrderEvent event, String eventType) {
        TextMessage message = jmsContext.createTextMessage(toJson(event));
        message.setStringProperty("eventType", eventType);
        jmsContext.createProducer()
            .setDeliveryMode(DeliveryMode.PERSISTENT)
            .send(orderQueue, message);
    }
}

@MessageDriven(activationConfig = {
    @ActivationConfigProperty(propertyName = "destinationLookup", propertyValue = "jms/orderQueue"),
    @ActivationConfigProperty(propertyName = "destinationType", propertyValue = "jakarta.jms.Queue")
})
public class OrderEventMDB implements MessageListener {

    @Override
    public void onMessage(Message message) {
        // Process message...
    }
}
```

### Jakarta EE 10 on Liberty

For deployment on WebSphere Liberty or Open Liberty, see the `ibm-websphere` skill for server.xml configuration, feature management, deployment descriptors, and Liberty-specific tuning.

```xml
<!-- server.xml features for Jakarta EE 10 -->
<featureManager>
    <feature>jakartaee-10.0</feature>
    <!-- Or pick individual features: -->
    <feature>restfulWS-3.1</feature>
    <feature>cdi-4.0</feature>
    <feature>persistence-3.1</feature>
    <feature>messaging-3.1</feature>
    <feature>jsonb-3.0</feature>
    <feature>mpHealth-4.0</feature>
    <feature>mpMetrics-5.1</feature>
</featureManager>
```

---

