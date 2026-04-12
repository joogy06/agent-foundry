---
name: python-enterprise-connectors
description: Use when connecting Python to enterprise databases (DB2, Oracle, SQL Server, Teradata), mainframe systems (z/OS, CICS, IMS, MQ), or building custom database connectors. Covers ibm_db, Zowe SDK, pyodbc, python-oracledb, EBCDIC handling, credential management, and connection security.
---

# Python Enterprise Connectors

## Overview

Enterprise database and mainframe connectivity in Python requires specific drivers, careful credential management, and understanding of legacy data formats. This skill covers DB2, Oracle, SQL Server, mainframe systems, and patterns for building robust connectors with proper security.

## IBM DB2

### Drivers

| Driver | Use Case | Status (2026) |
|--------|----------|---------------|
| **ibm_db** (v3.2.3) | Direct DB2 access via CLI/ODBC | Active, Python 3.9-3.14 |
| **ibm_db_sa** | SQLAlchemy dialect for DB2 | Active, supports SA 2.0 |
| **ibm_db_dbi** | DB-API 2.0 interface | Part of ibm_db package |
| pyodbc + DB2 ODBC | Alternative via ODBC driver | Works but less feature-rich |
| jaydebeapi + JDBC | JVM-based alternative | Requires JRE |

### Connection Patterns

```python
import ibm_db

# DB2 LUW (Linux/Unix/Windows)
conn = ibm_db.connect(
    f"DATABASE={db};HOSTNAME={host};PORT={port};PROTOCOL=TCPIP;UID={user};PWD={pwd};SECURITY=SSL;",
    "", ""
)

# DB2 z/OS (mainframe) — REQUIRES DB2 Connect license
conn = ibm_db.connect(
    f"DATABASE={location};HOSTNAME={host};PORT={port};PROTOCOL=TCPIP;UID={user};PWD={pwd};",
    "", ""
)
```

**Critical gotcha:** DB2 z/OS connections **require a paid DB2 Connect license**. Without it: `SQL1598N` error. This is the #1 issue developers hit.

### Performance Tuning

```python
# Increase fetch size for large result sets
stmt = ibm_db.exec_immediate(conn, sql)
ibm_db.set_option(stmt, {ibm_db.SQL_ATTR_CURSOR_TYPE: ibm_db.SQL_CURSOR_FORWARD_ONLY}, 1)
# Use array fetch for bulk operations
```

### EBCDIC Handling

Mainframe DB2 (z/OS) uses EBCDIC encoding. Known issues with ibm_db error message decoding.

```python
# Convert EBCDIC to UTF-8
data.decode('cp500').encode('utf-8')  # CP500 = common EBCDIC code page
# Or use codecs
import codecs
text = codecs.decode(ebcdic_bytes, 'cp037')  # CP037 = US EBCDIC
```

**Common EBCDIC code pages:** CP037 (US/Canada), CP500 (International), CP1047 (z/OS Unix).

## Mainframe Connectivity

### Zowe Python SDK (Modern Approach)

```bash
pip install zowe-zos-files-for-zowe-sdk zowe-zos-jobs-for-zowe-sdk zowe-zos-tso-for-zowe-sdk
```

| Package | Capability |
|---------|-----------|
| `zowe-zos-files` | Read/write MVS datasets, USS files |
| `zowe-zos-jobs` | Submit JCL, monitor job status, retrieve output |
| `zowe-zos-tso` | Execute TSO commands |
| `zowe-zos-console` | Issue console commands |

**Status (2026):** Pre-release (v1.0.0.dev25) but actively developed. For production, consider Zowe CLI with subprocess calls as a more stable alternative.

### z/OSMF REST API (Direct)

```python
import httpx

client = httpx.Client(base_url="https://mainframe:443/zosmf", verify=True,
                      auth=(user, password))

# List datasets
response = client.get("/restfiles/ds", params={"dslevel": "USER.PROD.*"})

# Submit JCL
response = client.put("/restjobs/jobs",
    content=jcl_content,
    headers={"Content-Type": "text/plain"})
job_id = response.json()["jobid"]

# Check job status
response = client.get(f"/restjobs/jobs/{job_name}/{job_id}")
```

### Terminal Emulation (3270)

| Library | Status | Notes |
|---------|--------|-------|
| **IBM tnz** | Recommended | Pure Python, no external emulator, battle-tested inside IBM |
| py3270 | Active | Requires x3270/s3270 installed |
| x3270 via subprocess | Works | Shell out to x3270 binary |

### IBM MQ (Messaging)

```python
# Package renamed: pymqi → ibmmq (v2.0.3, Feb 2026)
import ibmmq

qmgr = ibmmq.connect(queue_manager)
queue = ibmmq.Queue(qmgr, 'QUEUE.NAME')
queue.put('message data')
message = queue.get()
queue.close()
qmgr.disconnect()
```

### z/OS Connect (REST → CICS/IMS)

z/OS Connect 3.0 provides RESTful access to CICS transactions and IMS programs. **This is the recommended path** for Python-to-CICS/IMS since CTG has no native Python client.

```python
# Call a CICS transaction via z/OS Connect
response = httpx.post(
    "https://zosconnect:9443/zosConnect/apis/myApi/operation",
    json={"input_field": "value"},
    auth=(user, password)
)
```

## Other Enterprise Databases

| Database | Driver | Key Notes |
|----------|--------|-----------|
| **Oracle** | `python-oracledb` (replaces cx_Oracle) | Thin mode = no Oracle Client dependency. Migration: keyword-only params breaking change |
| **SQL Server** | `mssql-python` (GA Nov 2025) | New first-party driver, 40% faster than pyodbc, no dependencies |
| **SQL Server** (legacy) | `pyodbc` | Still works, wider compatibility |
| **Teradata** | `teradatasql` | Official driver + SQLAlchemy dialect |
| **SAP HANA** | `hdbcli` | Official SAP driver |
| **Snowflake** | `snowflake-connector-python` | Official, includes pandas integration |
| **BigQuery** | `google-cloud-bigquery` | Service account auth, magics for notebooks |

### Deprecated — Migrate Away

| Old | New | Deadline |
|-----|-----|---------|
| cx_Oracle | **python-oracledb** | cx_Oracle in maintenance only |
| pymqi | **ibmmq** (v2.0+) | pymqi still works but renamed |
| Motor (MongoDB async) | **PyMongo native async** | Motor EOL May 2026 |
| aioredis | **redis.asyncio** (redis-py v4.2+) | aioredis merged |

## Connector Building Patterns

### DB-API 2.0 Compliance

All Python database drivers should implement [PEP 249](https://peps.python.org/pep-0249/):
- `connect()` → connection object
- `connection.cursor()` → cursor object
- `cursor.execute(sql, params)` → parameterized queries
- `cursor.fetchone()`, `fetchmany()`, `fetchall()`
- `connection.commit()`, `connection.rollback()`

### Connection Factory

```python
class DatabaseConnector:
    def __init__(self, config: dict):
        self.config = config
        self._engine = None

    def get_engine(self):
        if self._engine is None:
            self._engine = create_engine(
                self.config['url'],
                pool_size=self.config.get('pool_size', 10),
                pool_pre_ping=True,
                pool_recycle=300,
            )
        return self._engine

    def health_check(self) -> bool:
        try:
            with self.get_engine().connect() as conn:
                conn.execute(text("SELECT 1"))
            return True
        except Exception:
            return False
```

### Retry Pattern

```python
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    retry=retry_if_exception_type((ConnectionError, TimeoutError)),
)
def execute_query(engine, sql, params):
    with engine.connect() as conn:
        return conn.execute(text(sql), params)
```

## Credential Security

### Hierarchy (Best → Worst)

1. **HashiCorp Vault** dynamic secrets (auto-rotating, short-lived)
2. **Cloud secret managers** (AWS Secrets Manager, Azure Key Vault, GCP Secret Manager)
3. **Environment variables** (acceptable for simple deployments)
4. **Config files** (encrypted, not in git)
5. **Hardcoded in code** — **NEVER**

```python
# Vault dynamic secrets (hvac library)
import hvac
client = hvac.Client(url='https://vault:8200', token=os.environ['VAULT_TOKEN'])
creds = client.secrets.database.generate_credentials('my-role')
username, password = creds['data']['username'], creds['data']['password']
# Credentials auto-expire after TTL
```

### Connection String Safety

```python
# NEVER log connection strings with passwords
import re
def sanitize_url(url: str) -> str:
    return re.sub(r'://[^:]+:[^@]+@', '://***:***@', url)
```

## Data Type Gotchas

| Issue | Databases | Solution |
|-------|-----------|---------|
| Decimal precision loss | All | Use `decimal.Decimal`, never `float` for money |
| Timezone-naive datetimes | MySQL, older Postgres | Always store UTC, use `datetime.timezone.utc` |
| EBCDIC encoding | DB2 z/OS | Decode with `cp037`/`cp500`/`cp1047` |
| Packed decimal (COMP-3) | Mainframe | Custom unpacking or `struct` module |
| NULL vs empty string | Oracle (treats '' as NULL) | Handle in application logic |
| BLOB/CLOB streaming | Oracle, DB2 | Use LOB locators, don't fetch full object to memory |

## Anti-Patterns

| Don't | Why |
|-------|-----|
| Hardcode credentials in code | Exposed in version control — use vault or env vars |
| Disable TLS verification (`verify=False`) | MITM vulnerability — always verify in production |
| Use `float` for financial data | Precision loss — use `decimal.Decimal` |
| Create connections per request | Performance killer — use connection pooling |
| Assume same SQL works across databases | Dialects differ — test per database or use ORM |
| Use cx_Oracle for new projects | Deprecated — use `python-oracledb` |
| Skip DB2 Connect license check for z/OS | SQL1598N at runtime — verify license first |
| Log connection strings with passwords | Credential leak — sanitize before logging |
| Use `pickle` for data transfer between systems | Security risk — use JSON/Protocol Buffers |
