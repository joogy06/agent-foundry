# Addendum: Java symbol vocabulary + call/read/write semantics

Read this alongside `analyze-symbols.md` when `format == java`. Vocabulary grounded in
`java-backend` / `java-frontend`. This addendum targets **legacy JEE / Spring estates**
(servlets, EJBs, Spring MVC/Boot, JPA/Hibernate, JDBC, JAX-RS) the way the rest of the
skill targets COBOL/DSX/ETL/Pick — symbols + occurrences + relationships, NOT a full
type hierarchy (SCIP's package/type lattice stays dropped).

## Format detection
`.java` extension is the primary signal. Reinforce with content: `package x.y.z;`,
`import …;`, `public class`/`interface`/`enum`/`record`, annotations (`@Override`,
`@Entity`, `@Service`, `@RestController`, `@Query`). A `.jsp`/`.jspx` file with embedded
`<% … %>` scriptlets is Java-adjacent — treat the scriptlet body as Java.

## `kind` closed set (Java)
`class`, `interface`, `method`, `field`, `enum`, `annotation`, `package`, `endpoint`,
`bean`.

- `class` — a top-level or nested `class` / `record`. The primary container.
- `interface` — an `interface` (incl. a Spring Data `Repository` interface).
- `method` — a method or constructor. Carry the owning type in `container_symbol_id`.
- `field` — a class/instance field; carry the declared type in `attributes.java_type`.
- `enum` — an `enum` declaration (constants are `field`s of it).
- `annotation` — a declared `@interface` (an annotation *type*, not a use site).
- `package` — the `package` declaration (a namespace container).
- `endpoint` — a mapped HTTP route (`@RequestMapping` / `@GetMapping` / `@Path`); carry
  the verb + path template in `attributes.http_route`.
- `bean` — a Spring/CDI managed component (`@Component`/`@Service`/`@Repository`/
  `@Controller`/`@Bean`) when worth its own node.

## Scoped names (for the path-independent symbol_id)
- Package: `<dotted.package.name>`.
- Class / interface / enum / annotation: `<package>/<TypeName>` (nested:
  `<package>/<Outer>.<Inner>`) — path-independent: the same fully-qualified type resolves
  to the same ID across files.
- Method: `<package>/<TypeName>#<methodName>(<arity-or-erased-param-types>)` — include
  arity (or erased parameter types when visible) to disambiguate overloads.
- Field: `<package>/<TypeName>#<fieldName>`.
- Endpoint: `endpoint/<HTTP-VERB>/<path-template>` (e.g. `endpoint/GET/orders/{id}`) —
  path-independent so the same route mapped from two controllers collides intentionally.

## Relationships
- `new Foo(...)` / `Foo.bar(...)` / `obj.bar(...)` → `calls` from the enclosing method to
  the target method, **grounded** when the receiver type resolves in the chunk (literal
  type, constructor, declared-type field/param); **speculative** for a reflective call
  (`Method.invoke`, `Class.forName(...).newInstance()`) — also emit a `dynamic_call` gap.
- `extends` / `implements` → an `inherits` relationship to the named super-type/interface,
  grounded when the name is imported/visible.
- `@Autowired` / constructor injection / `@Inject` of a field/param → a `references`
  (dependency) edge from the bean to the injected type's bean.
- A type `contains` its methods, fields, and nested types (`container_symbol_id` +
  `contains`).
- `@Entity` + `@Table(name = "orders")` → the class `references` a logical table
  `table/orders` (the JPA-to-relational bridge — the symbol-graph analogue of a COBOL FD;
  defer the dataset-flow edge itself to `lineage-extract-static`).
- A Spring Data repository method (`findByX` / `@Query("…")`) → `references` the entity it
  is typed on (`JpaRepository<Order, Long>` → `references` `…/Order`).
- `@GetMapping("/orders")` etc. on a method → defines an `endpoint` symbol; the method
  `contains`/handles it. Class-level `@RequestMapping` prefixes compose into the route.

## Dynamic-construction caution (HARD-RULE 2)
Force `speculative` (and emit a gap) for: reflection (`Class.forName`, `Method.invoke`,
`Proxy.newProxyInstance`); a Spring `@Value("${prop}")` / SpEL `#{…}` whose value is not
resolvable in-repo; an interpolated/concatenated SQL or route string; an interface call
whose concrete implementation is chosen at runtime by the container (record the interface
edge as `inferred`, never `grounded`, when no concrete binding is visible in the chunk).

## Credential caution
Java estates carry credentials in `application.properties` / `application.yml`,
`@Value("${spring.datasource.password}")`, JNDI lookups, JDBC URLs, and hard-coded
connection strings. Follow `redact-secrets.md` — never place a password, token, or full
connection string in `evidence_snippet`; emit the structure with the credential elided.
