---
name: mongodb
description: Use when installing, configuring, developing with, or managing MongoDB — replica sets, sharding, aggregation framework, indexing strategies, schema design patterns, security (SCRAM/x.509/LDAP), backup and restore (mongodump/mongorestore, filesystem snapshots, Atlas backup), monitoring (mongostat/mongotop/Atlas), performance tuning, and change streams. Covers MongoDB 7.x/8.x and Atlas.
---

# MongoDB Administration & Development

<HARD-RULE>
Never deploy MongoDB without authentication enabled — default installations allow unauthenticated access. Always enable --auth or security.authorization in mongod.conf.
</HARD-RULE>

<HARD-RULE>
Always disable Transparent Huge Pages (THP) on Linux — THP causes severe latency spikes with WiredTiger. Verify with `cat /sys/kernel/mm/transparent_hugepage/enabled`.
</HARD-RULE>

<HARD-RULE>
Never use a monotonically increasing field (timestamps, ObjectId, auto-increment) as shard key — it creates hot spots on a single shard. Use hashed shard keys or compound keys with high cardinality.
</HARD-RULE>

<HARD-RULE>
Always test replica set failover before production — election timeouts (default 10s) and driver behavior vary. Test with rs.stepDown() and verify application reconnection.
</HARD-RULE>

---

## 1. Installation

### RHEL 9

```bash
# Add MongoDB 8.0 repo
cat > /etc/yum.repos.d/mongodb-org-8.0.repo << 'EOF'
[mongodb-org-8.0]
name=MongoDB Repository
baseurl=https://repo.mongodb.org/yum/redhat/9/mongodb-org/8.0/x86_64/
gpgcheck=1
enabled=1
gpgkey=https://pgp.mongodb.com/server-8.0.asc
EOF

sudo dnf install -y mongodb-org

# Disable THP (critical)
echo 'never' | sudo tee /sys/kernel/mm/transparent_hugepage/enabled
echo 'never' | sudo tee /sys/kernel/mm/transparent_hugepage/defrag

# Persist THP disable via systemd
cat > /etc/systemd/system/disable-thp.service << 'EOF'
[Unit]
Description=Disable Transparent Huge Pages

[Service]
Type=simple
ExecStart=/bin/sh -c "echo never > /sys/kernel/mm/transparent_hugepage/enabled && echo never > /sys/kernel/mm/transparent_hugepage/defrag"

[Install]
WantedBy=multi-user.target
EOF
sudo systemctl enable --now disable-thp

# Kernel tuning
echo "vm.swappiness = 1" | sudo tee -a /etc/sysctl.conf
echo "net.core.somaxconn = 4096" | sudo tee -a /etc/sysctl.conf
sudo sysctl -p

# Start
sudo systemctl enable --now mongod
```

### Core Configuration (mongod.conf)

```yaml
storage:
  dbPath: /var/lib/mongo
  engine: wiredTiger
  wiredTiger:
    engineConfig:
      cacheSizeGB: 4              # Default: 50% RAM - 1GB
      journalCompressor: snappy
    collectionConfig:
      blockCompressor: snappy
    indexConfig:
      prefixCompression: true

systemLog:
  destination: file
  logAppend: true
  path: /var/log/mongodb/mongod.log

net:
  port: 27017
  bindIp: 0.0.0.0
  tls:
    mode: requireTLS
    certificateKeyFile: /etc/ssl/mongodb.pem
    CAFile: /etc/ssl/ca.pem

security:
  authorization: enabled
  keyFile: /etc/mongodb/keyfile     # For replica set auth

replication:
  replSetName: rs0
  oplogSizeMB: 4096
```

---

## 2. Replica Sets

### Initialize

```javascript
// Connect to primary and initiate
rs.initiate({
  _id: "rs0",
  members: [
    { _id: 0, host: "mongo1.example.com:27017", priority: 2 },
    { _id: 1, host: "mongo2.example.com:27017", priority: 1 },
    { _id: 2, host: "mongo3.example.com:27017", priority: 1 }
  ]
})

// Add members
rs.add("mongo4.example.com:27017")

// Add arbiter (vote-only, no data — use sparingly)
rs.addArb("arbiter.example.com:27017")

// Add hidden/delayed member (for backup)
rs.add({
  host: "mongo-delayed.example.com:27017",
  priority: 0,
  hidden: true,
  secondaryDelaySecs: 3600   // 1 hour delay
})

// Check status
rs.status()
rs.conf()
rs.printReplicationInfo()     // Oplog window
rs.printSecondaryReplicationInfo()  // Replication lag
```

### Read Preferences

| Preference | Reads From | Use Case |
|------------|-----------|----------|
| `primary` | Primary only | Default — consistent reads |
| `primaryPreferred` | Primary, fallback secondary | HA with consistency preference |
| `secondary` | Secondaries only | Read scale-out, analytics |
| `secondaryPreferred` | Secondary, fallback primary | Read scale-out with HA |
| `nearest` | Lowest latency member | Geo-distributed reads |

### Write Concerns

```javascript
// Majority write concern (recommended for durability)
db.orders.insertOne(
  { item: "widget", qty: 100 },
  { writeConcern: { w: "majority", j: true, wtimeout: 5000 } }
)

// w:1 — acknowledged by primary only (faster, less durable)
// w:0 — fire-and-forget (not recommended)
```

---

## 3. Sharding

### Architecture Setup

```javascript
// 1. Start config servers (replica set)
// mongod --configsvr --replSet configRS --port 27019

// 2. Start mongos routers
// mongos --configdb configRS/cfg1:27019,cfg2:27019,cfg3:27019

// 3. Add shards
sh.addShard("rs0/mongo1:27017,mongo2:27017,mongo3:27017")
sh.addShard("rs1/mongo4:27017,mongo5:27017,mongo6:27017")

// 4. Enable sharding on database
sh.enableSharding("mydb")

// 5. Shard a collection
// Hashed shard key (even distribution)
sh.shardCollection("mydb.orders", { customer_id: "hashed" })

// Range shard key (targeted queries)
sh.shardCollection("mydb.events", { timestamp: 1, device_id: 1 })
```

### Shard Key Selection

| Key Type | Distribution | Query Routing | Example |
|----------|-------------|---------------|---------|
| Hashed | Even | Scatter-gather | `{ _id: "hashed" }` |
| Range (good cardinality) | Targeted | Targeted | `{ region: 1, date: 1 }` |
| Compound | Targeted + even | Targeted | `{ tenant_id: 1, _id: 1 }` |
| Monotonic (BAD) | Hot shard | Always last shard | `{ createdAt: 1 }` |

### Zone Sharding (Data Locality)

```javascript
// Assign zones to shards
sh.addShardTag("rs-us", "US")
sh.addShardTag("rs-eu", "EU")

// Define zone ranges
sh.addTagRange("mydb.users",
  { region: "US", _id: MinKey },
  { region: "US", _id: MaxKey },
  "US"
)
sh.addTagRange("mydb.users",
  { region: "EU", _id: MinKey },
  { region: "EU", _id: MaxKey },
  "EU"
)
```

### Balancer Management

```javascript
sh.getBalancerState()
sh.stopBalancer()
sh.startBalancer()

// Set balancer window (off-peak hours)
db.settings.updateOne(
  { _id: "balancer" },
  { $set: { activeWindow: { start: "02:00", stop: "06:00" } } },
  { upsert: true }
)
```

---

## 4. Schema Design

### Embedding vs Referencing

| Pattern | When to Use | Example |
|---------|------------|---------|
| **Embed** | 1:1, 1:few, data read together | Address inside user doc |
| **Reference** | 1:many, many:many, independent access | Orders referencing products |
| **Subset** | Embed most-used fields, reference rest | Top 10 reviews embedded, rest referenced |

### Common Patterns

```javascript
// Bucket pattern — time-series data
{
  sensor_id: "temp_001",
  bucket_start: ISODate("2026-03-31T00:00:00Z"),
  count: 60,
  readings: [
    { ts: ISODate("2026-03-31T00:00:00Z"), val: 22.5 },
    { ts: ISODate("2026-03-31T00:01:00Z"), val: 22.7 }
    // ... up to 60 per bucket
  ],
  sum: 1350.0,
  avg: 22.5
}

// Polymorphic pattern — different shapes, same collection
{ type: "book", title: "...", isbn: "...", pages: 300 }
{ type: "movie", title: "...", runtime: 120, director: "..." }

// Computed pattern — pre-calculated fields
{
  product_id: "P001",
  total_reviews: 1547,        // Incremented on each review
  avg_rating: 4.3,            // Recalculated periodically
  last_review_date: ISODate("2026-03-30")
}
```

### Document Validation

```javascript
db.createCollection("orders", {
  validator: {
    $jsonSchema: {
      bsonType: "object",
      required: ["customer_id", "items", "total"],
      properties: {
        customer_id: { bsonType: "objectId" },
        total: { bsonType: "decimal", minimum: 0 },
        status: { enum: ["pending", "shipped", "delivered", "cancelled"] },
        items: {
          bsonType: "array",
          minItems: 1,
          items: {
            bsonType: "object",
            required: ["sku", "qty", "price"],
            properties: {
              sku: { bsonType: "string" },
              qty: { bsonType: "int", minimum: 1 },
              price: { bsonType: "decimal", minimum: 0 }
            }
          }
        }
      }
    }
  },
  validationLevel: "strict",
  validationAction: "error"
})
```

---

## 5. Indexing

### Index Types

```javascript
// Compound index (most common)
db.orders.createIndex({ customer_id: 1, order_date: -1 })

// Unique index
db.users.createIndex({ email: 1 }, { unique: true })

// Multikey index (arrays)
db.products.createIndex({ tags: 1 })

// Text index (full-text search)
db.articles.createIndex({ title: "text", body: "text" },
  { weights: { title: 10, body: 5 } })

// TTL index (auto-expire documents)
db.sessions.createIndex({ createdAt: 1 }, { expireAfterSeconds: 3600 })

// Partial index (index subset of documents)
db.orders.createIndex(
  { status: 1, created_at: -1 },
  { partialFilterExpression: { status: "active" } }
)

// Wildcard index (dynamic schemas)
db.events.createIndex({ "metadata.$**": 1 })

// Hidden index (test removal impact without dropping)
db.orders.hideIndex("idx_old_field")
db.orders.unhideIndex("idx_old_field")
```

### Explain Plans

```javascript
// Check query plan
db.orders.find({ customer_id: 123 }).explain("executionStats")

// Key fields to check:
// - winningPlan.stage: IXSCAN (good) vs COLLSCAN (bad)
// - executionStats.totalKeysExamined vs totalDocsExamined vs nReturned
// - Ratio of keysExamined:nReturned should be close to 1:1

// Index usage stats
db.orders.aggregate([{ $indexStats: {} }])
```

---

## 6. Aggregation Framework

```javascript
// Sales report with multiple stages
db.orders.aggregate([
  // Stage 1: Filter date range
  { $match: {
    order_date: {
      $gte: ISODate("2026-01-01"),
      $lt: ISODate("2026-04-01")
    }
  }},

  // Stage 2: Unwind items array
  { $unwind: "$items" },

  // Stage 3: Lookup product details
  { $lookup: {
    from: "products",
    localField: "items.sku",
    foreignField: "sku",
    as: "product"
  }},
  { $unwind: "$product" },

  // Stage 4: Group by category
  { $group: {
    _id: "$product.category",
    total_revenue: { $sum: { $multiply: ["$items.qty", "$items.price"] } },
    order_count: { $sum: 1 },
    avg_order_value: { $avg: { $multiply: ["$items.qty", "$items.price"] } }
  }},

  // Stage 5: Sort by revenue
  { $sort: { total_revenue: -1 } },

  // Stage 6: Format output
  { $project: {
    category: "$_id",
    total_revenue: { $round: ["$total_revenue", 2] },
    order_count: 1,
    avg_order_value: { $round: ["$avg_order_value", 2] },
    _id: 0
  }}
])

// Window functions
db.sales.aggregate([
  { $setWindowFields: {
    partitionBy: "$region",
    sortBy: { date: 1 },
    output: {
      running_total: {
        $sum: "$amount",
        window: { documents: ["unbounded", "current"] }
      },
      moving_avg_7d: {
        $avg: "$amount",
        window: { range: [-7, "current"], unit: "day" }
      }
    }
  }}
])

// Multi-faceted search (parallel pipelines)
db.products.aggregate([
  { $facet: {
    by_category: [
      { $group: { _id: "$category", count: { $sum: 1 } } }
    ],
    price_ranges: [
      { $bucket: {
        groupBy: "$price",
        boundaries: [0, 25, 50, 100, 500],
        default: "500+",
        output: { count: { $sum: 1 } }
      }}
    ],
    top_rated: [
      { $sort: { rating: -1 } },
      { $limit: 5 }
    ]
  }}
])
```

---

## 7. Security

### Authentication Setup

```javascript
// Create admin user (do this first, before enabling auth)
use admin
db.createUser({
  user: "adminUser",
  pwd: passwordPrompt(),
  roles: [
    { role: "userAdminAnyDatabase", db: "admin" },
    { role: "readWriteAnyDatabase", db: "admin" },
    { role: "clusterAdmin", db: "admin" }
  ]
})

// Create application user
use mydb
db.createUser({
  user: "appUser",
  pwd: passwordPrompt(),
  roles: [
    { role: "readWrite", db: "mydb" }
  ]
})

// Custom role
use admin
db.createRole({
  role: "orderProcessor",
  privileges: [
    { resource: { db: "mydb", collection: "orders" },
      actions: ["find", "insert", "update"] },
    { resource: { db: "mydb", collection: "inventory" },
      actions: ["find", "update"] }
  ],
  roles: []
})
```

### LDAP Authentication

```yaml
# mongod.conf
security:
  authorization: enabled
  ldap:
    servers: "ldap.example.com"
    transportSecurity: tls
    bind:
      method: simple
      queryUser: "cn=mongodb,ou=services,dc=example,dc=com"
      queryPassword: "<password>"
    userToDNMapping: '[
      { match: "(.+)", substitution: "uid={0},ou=users,dc=example,dc=com" }
    ]'
    authz:
      queryTemplate: "ou=groups,dc=example,dc=com??sub?(member={USER})"

setParameter:
  authenticationMechanisms: PLAIN
```

### Client-Side Field Level Encryption (CSFLE)

```javascript
// Define encryption schema
const encryptedFieldsMap = {
  "mydb.patients": {
    fields: [
      {
        path: "ssn",
        keyId: UUID("..."),
        bsonType: "string",
        queries: [{ queryType: "equality" }]
      },
      {
        path: "medical_records",
        keyId: UUID("..."),
        bsonType: "array"
      }
    ]
  }
}
```

---

## 8. Backup & Restore

```bash
# mongodump — logical backup
mongodump --uri="mongodb://user:pass@mongo1:27017/mydb?authSource=admin" \
  --gzip --out=/backups/mongo/$(date +%Y%m%d)

# mongorestore
mongorestore --uri="mongodb://user:pass@mongo1:27017" \
  --gzip /backups/mongo/20260331/

# Point-in-time recovery (oplog replay)
mongodump --oplog --out=/backups/mongo/pitr/
mongorestore --oplogReplay /backups/mongo/pitr/

# Filesystem snapshot (fastest for large datasets)
# 1. Lock writes
db.fsyncLock()
# 2. Take LVM/EBS snapshot
# 3. Unlock
db.fsyncUnlock()
```

---

## 9. Performance Tuning

### Profiler

```javascript
// Enable profiler (slow queries >100ms)
db.setProfilingLevel(1, { slowms: 100 })

// Query profiler data
db.system.profile.find({
  millis: { $gt: 100 },
  ns: "mydb.orders"
}).sort({ ts: -1 }).limit(10)

// Disable profiler
db.setProfilingLevel(0)
```

### WiredTiger Cache

```yaml
# mongod.conf — set cache to 50% of RAM minus OS overhead
storage:
  wiredTiger:
    engineConfig:
      cacheSizeGB: 8    # For 16GB RAM server
```

### Connection Pooling (Application Side)

```javascript
// Node.js driver — connection pool settings
const client = new MongoClient(uri, {
  maxPoolSize: 100,
  minPoolSize: 10,
  maxIdleTimeMS: 30000,
  waitQueueTimeoutMS: 5000
})
```

---

## 10. Monitoring

```bash
# Real-time stats
mongostat --uri="mongodb://..." --rowcount=10
mongotop --uri="mongodb://..." 5    # 5-second intervals

# Key metrics to watch
# - Replication lag: rs.printSecondaryReplicationInfo()
# - Connections: db.serverStatus().connections
# - Cache: db.serverStatus().wiredTiger.cache
# - Opcounters: db.serverStatus().opcounters
# - Lock %: db.serverStatus().globalLock
```

### Prometheus Exporter

```bash
# Deploy percona/mongodb_exporter
docker run -d --name mongo-exporter \
  -p 9216:9216 \
  percona/mongodb_exporter:0.40 \
  --mongodb.uri="mongodb://monitor:pass@mongo1:27017/admin"
```

### Alert Thresholds

| Metric | Warning | Critical |
|--------|---------|----------|
| Replication lag | >10s | >60s |
| Connections used | >70% max | >90% max |
| Cache dirty ratio | >5% | >20% |
| Oplog window | <24h | <2h |
| Page faults/sec | >10 | >100 |

---

## 11. Change Streams

```javascript
// Watch collection for changes
const pipeline = [
  { $match: { "fullDocument.status": "shipped" } }
]

const changeStream = db.orders.watch(pipeline, {
  fullDocument: "updateLookup",    // Include full doc on updates
  fullDocumentBeforeChange: "whenAvailable"  // Pre-image (7.0+)
})

changeStream.on("change", (change) => {
  console.log(`Operation: ${change.operationType}`)
  console.log(`Document: ${JSON.stringify(change.fullDocument)}`)
  // Store resume token for crash recovery
  saveResumeToken(change._id)
})

// Resume from stored token
const resumeToken = loadResumeToken()
const stream = db.orders.watch([], { resumeAfter: resumeToken })
```

---

---

## Anti-Patterns

| Anti-Pattern | Why It Fails | Correct Approach |
|---|---|---|
| Treating MongoDB as a relational database with deeply nested references | Excessive $lookup operations (equivalent to JOINs) are slow; MongoDB is optimized for denormalized reads | Embed related data in the same document when read together; reference only when data is shared across collections |
| No indexes on query fields | Full collection scans on millions of documents; queries that should take milliseconds take seconds | Create indexes on fields used in find/sort/aggregate filters; use `explain()` to verify index usage |
| Using unbounded arrays in documents | Documents grow past 16MB BSON limit; write performance degrades as array grows; index on array elements becomes expensive | Use the Bucket pattern or Outlier pattern; cap arrays at a reasonable size; overflow to separate collection |
| Not configuring write concern for important data | Default write concern may acknowledge before replication; data loss if primary fails before sync | Use `w: "majority"` for important writes; `w: 1` only for ephemeral data where some loss is acceptable |
| Running replica set with only 2 data-bearing members | No automatic failover — cannot elect a primary with only 1 of 2 votes; requires manual intervention | Use 3+ data-bearing members or 2 + an arbiter; odd number of voting members ensures election success |

---

## Related Skills

| Skill | When to Use |
|-------|-------------|
| `rhel-databases` | PostgreSQL/MySQL/Redis on RHEL |
| `ubuntu-databases` | PostgreSQL/MySQL/Redis on Ubuntu |
| `data-lake` | MongoDB as source for data lake ingestion |
| `python-data-engineer` | Python MongoDB drivers, ETL pipelines |
| `docker-fundamentals` | Containerized MongoDB deployments |
