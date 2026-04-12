# Spring Data JPA / Hibernate

Reference file for the `java-backend` skill. Covers entity mapping, repository interfaces, query methods and @Query, projections, N+1 prevention (@EntityGraph, JOIN FETCH), auditing, and Flyway migrations.

## 3. Spring Data JPA / Hibernate

### Entity Mapping

```java
@Entity
@Table(name = "orders")
@Getter @Setter
@NoArgsConstructor
@EntityListeners(AuditingEntityListener.class)
public class Order {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @ManyToOne(fetch = FetchType.LAZY)  // ALWAYS explicit LAZY
    @JoinColumn(name = "customer_id", nullable = false)
    private Customer customer;

    @OneToMany(mappedBy = "order", cascade = CascadeType.ALL, orphanRemoval = true)
    private List<OrderItem> items = new ArrayList<>();

    @Enumerated(EnumType.STRING)
    @Column(nullable = false, length = 20)
    private OrderStatus status = OrderStatus.PENDING;

    @Column(nullable = false, precision = 12, scale = 2)
    private BigDecimal totalAmount;

    @CreatedDate
    @Column(nullable = false, updatable = false)
    private Instant createdAt;

    @LastModifiedDate
    @Column(nullable = false)
    private Instant updatedAt;

    @Version
    private Integer version;  // Optimistic locking

    // Helper method to maintain bidirectional relationship
    public void addItem(OrderItem item) {
        items.add(item);
        item.setOrder(this);
    }

    public void removeItem(OrderItem item) {
        items.remove(item);
        item.setOrder(null);
    }
}
```

```java
@Entity
@Table(name = "order_items")
@Getter @Setter
@NoArgsConstructor
public class OrderItem {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @ManyToOne(fetch = FetchType.LAZY)
    @JoinColumn(name = "order_id", nullable = false)
    private Order order;

    @ManyToOne(fetch = FetchType.LAZY)
    @JoinColumn(name = "product_id", nullable = false)
    private Product product;

    @Column(nullable = false)
    private int quantity;

    @Column(nullable = false, precision = 10, scale = 2)
    private BigDecimal unitPrice;
}
```

### Many-to-Many with Join Table

```java
@Entity
@Table(name = "products")
public class Product {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @ManyToMany
    @JoinTable(
        name = "product_categories",
        joinColumns = @JoinColumn(name = "product_id"),
        inverseJoinColumns = @JoinColumn(name = "category_id")
    )
    private Set<Category> categories = new HashSet<>();
}
```

### Repository with Query Methods and @Query

```java
public interface OrderRepository extends JpaRepository<Order, Long> {

    // Derived query method
    Page<Order> findByStatusOrderByCreatedAtDesc(OrderStatus status, Pageable pageable);

    // JPQL with @EntityGraph to prevent N+1
    @EntityGraph(attributePaths = {"customer", "items", "items.product"})
    @Query("SELECT o FROM Order o WHERE o.id = :id")
    Optional<Order> findByIdWithDetails(@Param("id") Long id);

    // JPQL with JOIN FETCH (alternative to @EntityGraph)
    @Query("""
        SELECT DISTINCT o FROM Order o
        JOIN FETCH o.customer
        JOIN FETCH o.items i
        JOIN FETCH i.product
        WHERE o.customer.id = :customerId
        AND o.status = :status
        """)
    List<Order> findByCustomerAndStatus(
        @Param("customerId") Long customerId,
        @Param("status") OrderStatus status);

    // Native query for complex reporting
    @Query(value = """
        SELECT DATE(o.created_at) AS order_date,
               COUNT(*) AS order_count,
               SUM(o.total_amount) AS revenue
        FROM orders o
        WHERE o.created_at >= :since
        GROUP BY DATE(o.created_at)
        ORDER BY order_date
        """, nativeQuery = true)
    List<DailyRevenueProjection> getDailyRevenue(@Param("since") Instant since);

    // Modifying query
    @Modifying
    @Query("UPDATE Order o SET o.status = :status WHERE o.id = :id")
    int updateStatus(@Param("id") Long id, @Param("status") OrderStatus status);
}
```

### Interface Projection

```java
public interface DailyRevenueProjection {
    LocalDate getOrderDate();
    Long getOrderCount();
    BigDecimal getRevenue();
}

// DTO projection (constructor expression)
@Query("""
    SELECT new com.example.myapp.model.dto.OrderSummary(
        o.id, c.name, o.status, o.totalAmount, o.createdAt)
    FROM Order o JOIN o.customer c
    WHERE o.status = :status
    """)
List<OrderSummary> findSummariesByStatus(@Param("status") OrderStatus status);
```

### Auditing Configuration

```java
@Configuration
@EnableJpaAuditing
public class JpaConfig {

    @Bean
    public AuditorAware<String> auditorProvider() {
        return () -> Optional.ofNullable(SecurityContextHolder.getContext())
            .map(SecurityContext::getAuthentication)
            .filter(Authentication::isAuthenticated)
            .map(Authentication::getName);
    }
}
```

### Flyway Migrations

File: `src/main/resources/db/migration/V1__create_orders_schema.sql`

```sql
CREATE TABLE customers (
    id         BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name       VARCHAR(255) NOT NULL,
    email      VARCHAR(255) NOT NULL UNIQUE,
    created_at TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE TABLE orders (
    id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    customer_id  BIGINT         NOT NULL REFERENCES customers(id),
    status       VARCHAR(20)    NOT NULL DEFAULT 'PENDING',
    total_amount NUMERIC(12, 2) NOT NULL,
    created_at   TIMESTAMPTZ    NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ    NOT NULL DEFAULT now(),
    version      INT            NOT NULL DEFAULT 0
);

CREATE INDEX idx_orders_customer_id ON orders(customer_id);
CREATE INDEX idx_orders_status      ON orders(status);

CREATE TABLE order_items (
    id         BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    order_id   BIGINT         NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    product_id BIGINT         NOT NULL,
    quantity   INT            NOT NULL,
    unit_price NUMERIC(10, 2) NOT NULL
);

CREATE INDEX idx_order_items_order_id ON order_items(order_id);
```

---

