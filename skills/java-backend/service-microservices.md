# Service Layer and Microservices

Reference file for the `java-backend` skill. Covers service layer patterns (transactions, retry, caching, events), microservices (service discovery, circuit breaker/Resilience4j, API gateway, distributed tracing, config server).

## 5. Service Layer Patterns

### @Transactional with DTO Mapping

```java
@Service
@RequiredArgsConstructor
@Slf4j
public class OrderService {

    private final OrderRepository orderRepository;
    private final CustomerRepository customerRepository;
    private final ProductRepository productRepository;
    private final OrderMapper orderMapper;
    private final ApplicationEventPublisher eventPublisher;

    @Transactional(readOnly = true)
    public OrderResponse findById(Long id) {
        Order order = orderRepository.findByIdWithDetails(id)
            .orElseThrow(() -> new ResourceNotFoundException("Order", id));
        return orderMapper.toResponse(order);
    }

    @Transactional(readOnly = true)
    public Page<OrderResponse> findByStatus(OrderStatus status, Pageable pageable) {
        return orderRepository.findByStatusOrderByCreatedAtDesc(status, pageable)
            .map(orderMapper::toResponse);
    }

    @Transactional  // Default: propagation=REQUIRED, isolation=DEFAULT
    public OrderResponse create(CreateOrderRequest request) {
        Customer customer = customerRepository.findById(request.customerId())
            .orElseThrow(() -> new ResourceNotFoundException("Customer", request.customerId()));

        Order order = new Order();
        order.setCustomer(customer);
        order.setStatus(OrderStatus.PENDING);

        BigDecimal total = BigDecimal.ZERO;
        for (OrderItemRequest itemReq : request.items()) {
            Product product = productRepository.findById(itemReq.productId())
                .orElseThrow(() -> new ResourceNotFoundException("Product", itemReq.productId()));

            OrderItem item = new OrderItem();
            item.setProduct(product);
            item.setQuantity(itemReq.quantity());
            item.setUnitPrice(product.getPrice());
            order.addItem(item);

            total = total.add(product.getPrice().multiply(BigDecimal.valueOf(itemReq.quantity())));
        }
        order.setTotalAmount(total);

        Order saved = orderRepository.save(order);
        log.info("Order created: id={}, customerId={}, total={}", saved.getId(),
            customer.getId(), total);

        eventPublisher.publishEvent(new OrderCreatedEvent(saved.getId(), customer.getId()));
        return orderMapper.toResponse(saved);
    }

    @Transactional
    public void delete(Long id) {
        if (!orderRepository.existsById(id)) {
            throw new ResourceNotFoundException("Order", id);
        }
        orderRepository.deleteById(id);
        log.info("Order deleted: id={}", id);
    }
}
```

### MapStruct Mapper

```java
@Mapper(componentModel = "spring")
public interface OrderMapper {

    @Mapping(source = "customer.name", target = "customerName")
    OrderResponse toResponse(Order order);

    OrderItemResponse toItemResponse(OrderItem item);
}
```

### Domain Events

```java
public record OrderCreatedEvent(Long orderId, Long customerId) {}

@Component
@RequiredArgsConstructor
@Slf4j
public class OrderCreatedListener {

    private final NotificationService notificationService;

    @TransactionalEventListener(phase = TransactionPhase.AFTER_COMMIT)
    @Async
    public void handleOrderCreated(OrderCreatedEvent event) {
        log.info("Processing order created event: orderId={}", event.orderId());
        notificationService.sendOrderConfirmation(event.orderId());
    }
}
```

### @Transactional Propagation and Isolation

```java
// REQUIRES_NEW — runs in a separate transaction; commits independently
@Transactional(propagation = Propagation.REQUIRES_NEW)
public void logAuditEvent(AuditEvent event) {
    auditRepository.save(event);
}

// Isolation level for financial operations
@Transactional(isolation = Isolation.SERIALIZABLE)
public void transferFunds(Long fromAccountId, Long toAccountId, BigDecimal amount) {
    // ...
}

// readOnly=true — hints to provider for optimization (no dirty checking, read replicas)
@Transactional(readOnly = true)
public List<OrderSummary> getReport() { /* ... */ }
```

---

## 6. Microservices

### Spring Cloud Dependencies (BOM)

```xml
<!-- pom.xml — Spring Cloud BOM -->
<dependencyManagement>
    <dependencies>
        <dependency>
            <groupId>org.springframework.cloud</groupId>
            <artifactId>spring-cloud-dependencies</artifactId>
            <version>2024.0.0</version>
            <type>pom</type>
            <scope>import</scope>
        </dependency>
    </dependencies>
</dependencyManagement>
```

### Service Discovery — Eureka

```java
// Discovery Server
@SpringBootApplication
@EnableEurekaServer
public class DiscoveryServerApplication { }
```

```yaml
# Discovery client (each microservice)
spring:
  application:
    name: order-service
eureka:
  client:
    service-url:
      defaultZone: http://discovery:8761/eureka/
  instance:
    prefer-ip-address: true
```

### Spring Cloud Gateway

```yaml
# gateway application.yml
spring:
  cloud:
    gateway:
      routes:
        - id: order-service
          uri: lb://order-service
          predicates:
            - Path=/api/v1/orders/**
          filters:
            - StripPrefix=0
            - name: CircuitBreaker
              args:
                name: orderCB
                fallbackUri: forward:/fallback/orders
        - id: product-service
          uri: lb://product-service
          predicates:
            - Path=/api/v1/products/**
      default-filters:
        - name: RequestRateLimiter
          args:
            redis-rate-limiter.replenishRate: 50
            redis-rate-limiter.burstCapacity: 100
```

### Circuit Breaker — Resilience4j

```java
@Service
@RequiredArgsConstructor
public class InventoryClient {

    private final WebClient.Builder webClientBuilder;

    @CircuitBreaker(name = "inventory", fallbackMethod = "fallbackCheckStock")
    @Retry(name = "inventory")
    @TimeLimiter(name = "inventory")
    public CompletableFuture<StockResponse> checkStock(Long productId) {
        return webClientBuilder.build()
            .get()
            .uri("http://inventory-service/api/v1/stock/{productId}", productId)
            .retrieve()
            .bodyToMono(StockResponse.class)
            .toFuture();
    }

    private CompletableFuture<StockResponse> fallbackCheckStock(Long productId, Throwable t) {
        log.warn("Inventory service unavailable for product {}: {}", productId, t.getMessage());
        return CompletableFuture.completedFuture(new StockResponse(productId, 0, false));
    }
}
```

```yaml
# application.yml — Resilience4j config
resilience4j:
  circuitbreaker:
    instances:
      inventory:
        sliding-window-size: 10
        failure-rate-threshold: 50
        wait-duration-in-open-state: 30s
        permitted-number-of-calls-in-half-open-state: 3
  retry:
    instances:
      inventory:
        max-attempts: 3
        wait-duration: 500ms
        exponential-backoff-multiplier: 2
  timelimiter:
    instances:
      inventory:
        timeout-duration: 3s
```

### Inter-Service Communication — OpenFeign

```java
@FeignClient(name = "inventory-service", fallbackFactory = InventoryFallbackFactory.class)
public interface InventoryFeignClient {

    @GetMapping("/api/v1/stock/{productId}")
    StockResponse checkStock(@PathVariable Long productId);

    @PostMapping("/api/v1/stock/reserve")
    ReservationResponse reserveStock(@RequestBody ReservationRequest request);
}

@Component
@Slf4j
public class InventoryFallbackFactory implements FallbackFactory<InventoryFeignClient> {
    @Override
    public InventoryFeignClient create(Throwable cause) {
        log.error("Inventory service fallback triggered", cause);
        return new InventoryFeignClient() {
            @Override
            public StockResponse checkStock(Long productId) {
                return new StockResponse(productId, 0, false);
            }
            @Override
            public ReservationResponse reserveStock(ReservationRequest request) {
                throw new ServiceUnavailableException("Inventory service unavailable");
            }
        };
    }
}
```

### Distributed Tracing — Micrometer + OpenTelemetry

```xml
<dependency>
    <groupId>io.micrometer</groupId>
    <artifactId>micrometer-tracing-bridge-otel</artifactId>
</dependency>
<dependency>
    <groupId>io.opentelemetry</groupId>
    <artifactId>opentelemetry-exporter-otlp</artifactId>
</dependency>
```

```yaml
management:
  tracing:
    sampling:
      probability: 1.0  # 100% in dev; reduce in prod
  otlp:
    tracing:
      endpoint: http://otel-collector:4318/v1/traces
```

Trace IDs propagate automatically across WebClient, RestClient, OpenFeign, and JMS/Kafka via Micrometer instrumentation.

### API Versioning Strategies

```java
// URI versioning (most common)
@RestController
@RequestMapping("/api/v1/orders")
public class OrderControllerV1 { }

@RestController
@RequestMapping("/api/v2/orders")
public class OrderControllerV2 { }

// Header versioning
@GetMapping(value = "/api/orders", headers = "X-API-Version=2")
public OrderResponseV2 getOrderV2(@PathVariable Long id) { }

// Content negotiation versioning
@GetMapping(value = "/api/orders/{id}",
    produces = "application/vnd.example.order.v2+json")
public OrderResponseV2 getOrderV2(@PathVariable Long id) { }
```

---

