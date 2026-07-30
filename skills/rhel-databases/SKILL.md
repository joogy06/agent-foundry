---
name: rhel-databases
description: Use when installing, configuring, or managing databases on RHEL 9 (and AlmaLinux/Rocky 9) — PostgreSQL 15/16 via module streams, MySQL 8/MariaDB 10.11, Redis 7, performance tuning, backup/restore, replication, connection pooling, user/role management, SELinux contexts, and firewalld rules. Part of the rhel-* skill family.
family: rhel
applies_when: os_family == rhel
disambiguation: The open-source engines on RHEL — PostgreSQL, MySQL/MariaDB, MongoDB, Redis. IBM DB2 LUW has its own skill, db2-rhel.
---

# Red Hat Enterprise Linux 9 — Database Administration

Companion skill to `rhel-server-admin`. For other workloads see: `rhel-web-servers`, `rhel-docker-host`, `rhel-file-storage`, `rhel-network-infra`, `rhel-monitoring`, `rhel-ollama-nvidia`.

<HARD-RULE>
Always take a full backup before any database upgrade, major config change, or replication topology change. Untested restores are not backups — verify by restoring to a scratch instance.
</HARD-RULE>

<HARD-RULE>
Never run database processes as root. PostgreSQL uses `postgres`, MySQL/MariaDB uses `mysql`, Redis uses `redis`. Grant application accounts only the minimum privileges needed.
</HARD-RULE>

<HARD-RULE>
Never expose database ports (5432, 3306, 6379) to the public internet without TLS and strong authentication. Use firewalld rich rules to restrict to trusted subnets.
</HARD-RULE>

<HARD-RULE>
Never disable SELinux to fix database access problems. Use the correct SELinux contexts, booleans, and port labels instead. See SELinux sections for each database below.
</HARD-RULE>

---

## 1. PostgreSQL 15/16

### Installation — Module Stream (AppStream)

```bash
# List available PostgreSQL module streams
dnf module list postgresql

# Install PostgreSQL 16 via module stream (RHEL 9.4+)
sudo dnf module enable postgresql:16
sudo dnf install postgresql-server postgresql-contrib

# Or PostgreSQL 15 (available earlier)
sudo dnf module enable postgresql:15
sudo dnf install postgresql-server postgresql-contrib

# Initialize and start
sudo postgresql-setup --initdb
sudo systemctl enable --now postgresql
```

### Installation — PGDG Repository (Latest Versions)

```bash
# Install PGDG repo
sudo dnf install -y https://download.postgresql.org/pub/repos/yum/reporpms/EL-9-x86_64/pgdg-redhat-repo-latest.noarch.rpm

# Disable built-in module to avoid conflicts
sudo dnf -qy module disable postgresql

# Install PostgreSQL 16
sudo dnf install -y postgresql16-server postgresql16-contrib

# Initialize and start (note: different binary path for PGDG)
sudo /usr/pgsql-16/bin/postgresql-16-setup initdb
sudo systemctl enable --now postgresql-16
```

Key paths (module stream): config `/var/lib/pgsql/data/postgresql.conf`, auth `/var/lib/pgsql/data/pg_hba.conf`, data `/var/lib/pgsql/data/`.

Key paths (PGDG): config `/var/lib/pgsql/16/data/postgresql.conf`, auth `/var/lib/pgsql/16/data/pg_hba.conf`, data `/var/lib/pgsql/16/data/`.

### pg_hba.conf

```
local   all       postgres                    peer
local   all       all                         scram-sha-256
host    all       all        10.0.1.0/24      scram-sha-256
host    replication replicator 10.0.1.20/32   scram-sha-256
host    all       all        0.0.0.0/0        reject
```

Reload after edit: `sudo systemctl reload postgresql`

### postgresql.conf Tuning (16 GB RAM / 4-core example)

```
listen_addresses = '*'
max_connections = 200
shared_buffers = 4GB              # ~25% of RAM
effective_cache_size = 12GB
work_mem = 32MB
maintenance_work_mem = 1GB
huge_pages = try
wal_level = replica
wal_buffers = 64MB
max_wal_size = 4GB
min_wal_size = 1GB
checkpoint_completion_target = 0.9
archive_mode = on
archive_command = 'cp %p /var/lib/pgsql/data/archive/%f'
random_page_cost = 1.1            # SSD (4.0 for HDD)
effective_io_concurrency = 200    # SSD (2 for HDD)
max_parallel_workers_per_gather = 2
max_parallel_workers = 4
log_min_duration_statement = 500  # ms — log slow queries
log_checkpoints = on
log_lock_waits = on
```

Restart for `shared_buffers`/`max_connections`/`wal_level`; reload for most others.

### User/Role Management

```sql
-- As postgres superuser: sudo -u postgres psql
CREATE ROLE appuser WITH LOGIN PASSWORD 'StrongP@ss!2024' VALID UNTIL '2027-01-01';
CREATE ROLE readonly WITH LOGIN PASSWORD 'ReadP@ss!2024';
CREATE DATABASE myapp OWNER appuser ENCODING 'UTF8';
GRANT CONNECT ON DATABASE myapp TO readonly;
\c myapp
GRANT USAGE ON SCHEMA public TO readonly;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO readonly;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO readonly;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
```

### Backup — pg_dump / pg_restore

```bash
# Custom format (parallel-restore capable)
sudo -u postgres pg_dump -Fc myapp -f /backup/pg/myapp_$(date +%Y%m%d).dump

# All databases (globals + schemas)
sudo -u postgres pg_dumpall > /backup/pg/all_$(date +%Y%m%d).sql

# Restore (parallel, clean)
sudo -u postgres pg_restore -d myapp -j 4 --clean --if-exists /backup/pg/myapp.dump
```

### Streaming Replication

**Primary:** ensure `wal_level = replica`, create replication user, allow standby in pg_hba.conf.

```bash
sudo -u postgres psql -c "CREATE ROLE replicator WITH REPLICATION LOGIN PASSWORD 'ReplP@ss!2024';"
```

**Standby:** stop PG, clear data dir, base backup with `-R` flag, start.

```bash
sudo systemctl stop postgresql
sudo rm -rf /var/lib/pgsql/data/*
sudo -u postgres pg_basebackup -h 10.0.1.10 -U replicator -D /var/lib/pgsql/data -Fp -Xs -P -R
sudo systemctl start postgresql
```

Verify on primary:
```sql
SELECT client_addr, state, replay_lsn FROM pg_stat_replication;
```

Verify on standby:
```sql
SELECT pg_is_in_recovery();   -- should return 't'
```

### PgBouncer Connection Pooling

```bash
sudo dnf install -y pgbouncer
```

Config `/etc/pgbouncer/pgbouncer.ini`:

```ini
[databases]
myapp = host=127.0.0.1 port=5432 dbname=myapp

[pgbouncer]
listen_addr = 0.0.0.0
listen_port = 6432
auth_type = scram-sha-256
auth_file = /etc/pgbouncer/userlist.txt
pool_mode = transaction
default_pool_size = 25
max_client_conn = 500
```

Generate userlist from PG:
```bash
sudo -u postgres psql -tAc "SELECT '\"'||rolname||'\" \"'||rolpassword||'\"' FROM pg_authid WHERE rolcanlogin" > /etc/pgbouncer/userlist.txt
sudo chown pgbouncer:pgbouncer /etc/pgbouncer/userlist.txt
sudo systemctl enable --now pgbouncer
```

### pg_stat Monitoring Queries

```sql
-- Active queries
SELECT pid, usename, state, query FROM pg_stat_activity WHERE state != 'idle';

-- Dead tuples (vacuum candidates)
SELECT relname, n_dead_tup, last_autovacuum FROM pg_stat_user_tables ORDER BY n_dead_tup DESC LIMIT 10;

-- Cache hit ratio (should be > 99%)
SELECT round(100.0*sum(blks_hit)/nullif(sum(blks_hit)+sum(blks_read),0),2) AS cache_pct FROM pg_stat_database;

-- Top slow queries (requires shared_preload_libraries = 'pg_stat_statements')
SELECT query, calls, mean_exec_time::numeric(10,2) FROM pg_stat_statements ORDER BY total_exec_time DESC LIMIT 10;

-- Replication lag in bytes
SELECT client_addr, pg_wal_lsn_diff(pg_current_wal_lsn(), replay_lsn) AS lag_bytes FROM pg_stat_replication;
```

### PostgreSQL SELinux

```bash
# If using a non-standard port (e.g. 5433)
sudo semanage port -a -t postgresql_port_t -p tcp 5433

# If data directory is moved to a custom path
sudo semanage fcontext -a -t postgresql_db_t "/data/pgsql(/.*)?"
sudo restorecon -Rv /data/pgsql

# Common booleans
sudo setsebool -P postgresql_can_rsync on

# Verify port labels
sudo semanage port -l | grep postgresql

# Troubleshoot SELinux denials
sudo ausearch -m AVC -c postgres --start recent
sudo sealert -a /var/log/audit/audit.log
```

---

## 2. MariaDB 10.11 / MySQL 8

### MariaDB 10.11 — Default in RHEL 9 AppStream

```bash
# Install MariaDB (default stream in RHEL 9)
sudo dnf install -y mariadb-server mariadb
sudo systemctl enable --now mariadb
sudo mariadb-secure-installation
```

### MySQL 8 — Community Repository

```bash
# Install MySQL community repo
sudo dnf install -y https://dev.mysql.com/get/mysql80-community-release-el9-5.noarch.rpm

# Disable MariaDB module to avoid conflicts
sudo dnf module disable mariadb -y

# Install MySQL 8
sudo dnf install -y mysql-community-server
sudo systemctl enable --now mysqld

# Retrieve temporary root password and secure
sudo grep 'temporary password' /var/log/mysqld.log
mysql -u root -p    # use temp password, then:
ALTER USER 'root'@'localhost' IDENTIFIED BY 'NewStr0ngP@ss!2024';
```

### my.cnf.d Tuning (16 GB / 4-core)

Drop-in: `/etc/my.cnf.d/99-tuning.cnf`

```ini
[mysqld]
innodb_buffer_pool_size = 11G     # ~70% RAM for dedicated DB
innodb_buffer_pool_instances = 8
innodb_log_file_size = 1G
innodb_flush_log_at_trx_commit = 1
innodb_flush_method = O_DIRECT
innodb_io_capacity = 2000
max_connections = 300
log_bin = /var/log/mariadb/mariadb-bin   # or /var/log/mysql/mysql-bin for MySQL
binlog_expire_logs_seconds = 604800
binlog_format = ROW
sync_binlog = 1
server_id = 1
slow_query_log = 1
slow_query_log_file = /var/log/mariadb/slow.log
long_query_time = 1
character_set_server = utf8mb4
```

Note: MariaDB log path is `/var/log/mariadb/`, MySQL community uses `/var/log/mysql/` or `/var/log/mysqld.log`.

### User Management

```sql
CREATE USER 'appuser'@'10.0.1.%' IDENTIFIED BY 'StrongP@ss!2024';
GRANT SELECT, INSERT, UPDATE, DELETE ON myapp.* TO 'appuser'@'10.0.1.%';
CREATE USER 'readonly'@'10.0.1.%' IDENTIFIED BY 'ReadP@ss!2024';
GRANT SELECT ON myapp.* TO 'readonly'@'10.0.1.%';
FLUSH PRIVILEGES;
```

### Backup — mysqldump / mariadb-dump

```bash
# MariaDB
mariadb-dump -u root --single-transaction --routines --triggers myapp \
  | gzip > /backup/mariadb/myapp_$(date +%Y%m%d).sql.gz

# MySQL
mysqldump -u root --single-transaction --routines --triggers myapp \
  | gzip > /backup/mysql/myapp_$(date +%Y%m%d).sql.gz

# Restore
gunzip < /backup/mariadb/myapp.sql.gz | mariadb -u root myapp
```

### Replication (Source / Replica)

**Source:** enable `log_bin`, set `server_id=1`, create replicator user.

```sql
CREATE USER 'replicator'@'10.0.1.%' IDENTIFIED BY 'ReplP@ss!2024';
GRANT REPLICATION SLAVE ON *.* TO 'replicator'@'10.0.1.%';
FLUSH PRIVILEGES;
SHOW MASTER STATUS;   -- note File and Position
```

**Replica:** set `server_id=2`, then:

```sql
CHANGE REPLICATION SOURCE TO SOURCE_HOST='10.0.1.10', SOURCE_USER='replicator',
  SOURCE_PASSWORD='ReplP@ss!2024', SOURCE_LOG_FILE='mariadb-bin.000001', SOURCE_LOG_POS=154;
START REPLICA;
SHOW REPLICA STATUS\G   -- check Replica_IO_Running=Yes, Replica_SQL_Running=Yes
```

### Slow Query Analysis

```bash
# Built-in summary
mysqldumpslow -s t -t 10 /var/log/mariadb/slow.log

# With Percona Toolkit (from EPEL or Percona repo)
sudo dnf install -y percona-toolkit
pt-query-digest /var/log/mariadb/slow.log
```

### MariaDB / MySQL SELinux

```bash
# Common booleans
sudo setsebool -P mysql_connect_any 1           # allow outbound connections
sudo setsebool -P selinuxuser_mysql_connect_enabled 1

# If using a non-standard port
sudo semanage port -a -t mysqld_port_t -p tcp 3307

# If data directory is moved
sudo semanage fcontext -a -t mysqld_db_t "/data/mysql(/.*)?"
sudo restorecon -Rv /data/mysql

# If log directory is custom
sudo semanage fcontext -a -t mysqld_log_t "/data/logs/mysql(/.*)?"
sudo restorecon -Rv /data/logs/mysql

# Verify
sudo semanage port -l | grep mysqld
getsebool -a | grep mysql

# Troubleshoot
sudo ausearch -m AVC -c mysqld --start recent
```

---

## 3. Redis 7

### Installation — EPEL

```bash
# EPEL provides Redis 7 on RHEL 9
sudo dnf install -y epel-release    # AlmaLinux/Rocky
# RHEL: sudo dnf install -y https://dl.fedoraproject.org/pub/epel/epel-release-latest-9.noarch.rpm

sudo dnf install -y redis
sudo systemctl enable --now redis
```

### Installation — Remi Repository (Alternate / Latest)

```bash
sudo dnf install -y https://rpms.remirepo.net/enterprise/remi-release-9.rpm
sudo dnf module enable redis:remi-7.2 -y
sudo dnf install -y redis
sudo systemctl enable --now redis
```

### redis.conf Tuning

Config: `/etc/redis/redis.conf` (or `/etc/redis.conf` depending on package)

```
bind 127.0.0.1 10.0.1.10
protected-mode yes
maxmemory 4gb
maxmemory-policy allkeys-lru       # options: noeviction, allkeys-lfu, volatile-lru, volatile-ttl

# RDB persistence
save 900 1
save 300 10
save 60 10000

# AOF persistence (enable for durability)
appendonly yes
appendfsync everysec               # always | everysec | no

io-threads 4
requirepass YourStr0ngRedisP@ss!

# Disable dangerous commands
rename-command FLUSHALL ""
rename-command FLUSHDB ""
```

RDB = fast restart, minutes of data loss. AOF = ~1s loss, slower restart. Enable both for critical data.

### Sentinel (HA)

```bash
sudo dnf install -y redis-sentinel    # included with redis package on some repos
```

Config `/etc/redis/sentinel.conf`:

```
port 26379
sentinel monitor mymaster 10.0.1.10 6379 2
sentinel auth-pass mymaster YourStr0ngRedisP@ss!
sentinel down-after-milliseconds mymaster 5000
sentinel failover-timeout mymaster 60000
```

```bash
sudo systemctl enable --now redis-sentinel
```

### ACLs (Redis 6+)

```
ACL SETUSER appuser on >AppP@ss123 ~app:* &* +get +set +del +exists +expire -@admin
ACL SETUSER readonly on >ReadP@ss123 ~* &* +get +mget +scan -@write -@admin
ACL SAVE
```

### Monitoring

```bash
redis-cli -a 'YourStr0ngRedisP@ss!' INFO memory     # used_memory, maxmemory
redis-cli -a 'YourStr0ngRedisP@ss!' INFO stats       # ops/sec, evicted_keys, hit ratio
redis-cli -a 'YourStr0ngRedisP@ss!' --stat           # live dashboard
redis-cli -a 'YourStr0ngRedisP@ss!' SLOWLOG GET 10   # slow commands
redis-cli -a 'YourStr0ngRedisP@ss!' INFO replication  # check replica lag
```

### Redis SELinux

```bash
# If using a non-standard port
sudo semanage port -a -t redis_port_t -p tcp 6380

# If data directory is moved
sudo semanage fcontext -a -t redis_var_lib_t "/data/redis(/.*)?"
sudo restorecon -Rv /data/redis

# Verify
sudo semanage port -l | grep redis

# Troubleshoot
sudo ausearch -m AVC -c redis-server --start recent
```

---

## 4. Common Patterns

### Systemd Services

```bash
# PostgreSQL (module stream)
sudo systemctl start|stop|restart|reload postgresql

# PostgreSQL (PGDG)
sudo systemctl start|stop|restart|reload postgresql-16

# MariaDB
sudo systemctl start|stop|restart mariadb

# MySQL community
sudo systemctl start|stop|restart mysqld

# Redis
sudo systemctl start|stop|restart redis

# Tail logs
journalctl -u postgresql -f
journalctl -u mariadb -f
journalctl -u redis -f
```

### Firewalld Rules

<HARD-RULE>
Never open database ports to all sources. Always restrict to trusted subnets or specific IPs using firewalld rich rules.
</HARD-RULE>

```bash
# PostgreSQL (restrict to app subnet)
sudo firewall-cmd --permanent --add-rich-rule='rule family="ipv4" source address="10.0.1.0/24" port port="5432" protocol="tcp" accept'

# PgBouncer
sudo firewall-cmd --permanent --add-rich-rule='rule family="ipv4" source address="10.0.1.0/24" port port="6432" protocol="tcp" accept'

# MariaDB / MySQL
sudo firewall-cmd --permanent --add-rich-rule='rule family="ipv4" source address="10.0.1.0/24" port port="3306" protocol="tcp" accept'

# Redis
sudo firewall-cmd --permanent --add-rich-rule='rule family="ipv4" source address="10.0.1.0/24" port port="6379" protocol="tcp" accept'

# Redis Sentinel
sudo firewall-cmd --permanent --add-rich-rule='rule family="ipv4" source address="10.0.1.0/24" port port="26379" protocol="tcp" accept'

# Apply all rules
sudo firewall-cmd --reload
sudo firewall-cmd --list-rich-rules
```

### TLS/SSL

**PostgreSQL:** generate cert, set `ssl = on` + paths in postgresql.conf, use `hostssl` in pg_hba.conf.

```bash
sudo -u postgres openssl req -new -x509 -days 3650 -nodes \
  -out /var/lib/pgsql/data/server.crt \
  -keyout /var/lib/pgsql/data/server.key \
  -subj "/CN=db01"
sudo chmod 600 /var/lib/pgsql/data/server.key
sudo chown postgres:postgres /var/lib/pgsql/data/server.{crt,key}
```

Add to `postgresql.conf`:
```
ssl = on
ssl_cert_file = 'server.crt'
ssl_key_file = 'server.key'
```

**MariaDB / MySQL:** auto-generates certs at install in `/var/lib/mysql/`. Enforce per user:

```sql
ALTER USER 'appuser'@'10.0.1.%' REQUIRE SSL;
```

**Redis:** set `tls-port 6380`, `port 0`, `tls-cert-file`, `tls-key-file`, `tls-ca-cert-file` in redis.conf. Requires Redis compiled with TLS support.

### Health Checks

```bash
# PostgreSQL
sudo -u postgres pg_isready -h 127.0.0.1 -p 5432   # exit 0 = healthy

# MariaDB
mysqladmin -u root ping

# MySQL community
mysqladmin -u root -p ping

# Redis
redis-cli -a 'YourStr0ngRedisP@ss!' ping            # returns PONG
```

### Log Rotation

PostgreSQL and MariaDB/MySQL handle rotation internally via `log_rotation_age`/`log_rotation_size` (PG) and `expire_logs_days` (MySQL). For Redis, create `/etc/logrotate.d/redis`:

```
/var/log/redis/*.log {
    weekly
    rotate 12
    compress
    delaycompress
    missingok
    copytruncate
}
```

---

## 5. Backup Strategies

### PostgreSQL — Automated Backup (systemd timer)

`/etc/systemd/system/pg-backup.service`:
```ini
[Unit]
Description=PostgreSQL daily backup
After=postgresql.service

[Service]
Type=oneshot
User=postgres
ExecStart=/usr/local/bin/pg-backup.sh
```

`/etc/systemd/system/pg-backup.timer`:
```ini
[Unit]
Description=PG backup daily 02:00

[Timer]
OnCalendar=*-*-* 02:00:00
Persistent=true
RandomizedDelaySec=300

[Install]
WantedBy=timers.target
```

`/usr/local/bin/pg-backup.sh`:
```bash
#!/bin/bash
set -euo pipefail
BACKUP_DIR="/backup/postgresql"
RETENTION=14
TS=$(date +%Y%m%d_%H%M%S)
mkdir -p "$BACKUP_DIR"
for DB in $(psql -At -c "SELECT datname FROM pg_database WHERE NOT datistemplate AND datname!='postgres'"); do
  pg_dump -Fc "$DB" -f "$BACKUP_DIR/${DB}_${TS}.dump"
done
pg_dumpall --globals-only -f "$BACKUP_DIR/globals_${TS}.sql"
find "$BACKUP_DIR" -name "*.dump" -mtime +$RETENTION -delete
find "$BACKUP_DIR" -name "*.sql" -mtime +$RETENTION -delete
```

Enable:
```bash
sudo chmod +x /usr/local/bin/pg-backup.sh
sudo systemctl daemon-reload
sudo systemctl enable --now pg-backup.timer
systemctl list-timers | grep pg-backup
```

### PostgreSQL — Point-in-Time Recovery (PITR)

Requires `archive_mode = on` + `archive_command` in postgresql.conf (see tuning section).

```bash
# Create archive directory
sudo -u postgres mkdir -p /var/lib/pgsql/data/archive

# Take a base backup
sudo -u postgres pg_basebackup -D /backup/postgresql/pitr_base -Ft -z -Xs -P
```

Recovery procedure:
```bash
sudo systemctl stop postgresql
sudo rm -rf /var/lib/pgsql/data/*
sudo -u postgres tar xzf /backup/postgresql/pitr_base/base.tar.gz -C /var/lib/pgsql/data/
sudo -u postgres tar xzf /backup/postgresql/pitr_base/pg_wal.tar.gz -C /var/lib/pgsql/data/pg_wal/
sudo -u postgres touch /var/lib/pgsql/data/recovery.signal
sudo -u postgres tee -a /var/lib/pgsql/data/postgresql.auto.conf <<'EOF'
restore_command = 'cp /var/lib/pgsql/data/archive/%f %p'
recovery_target_time = '2026-03-22 14:30:00'
recovery_target_action = 'promote'
EOF
sudo systemctl start postgresql
```

### MariaDB / MySQL — Binary Log PITR

```bash
# Flush logs before backup
mariadb -u root -e "FLUSH BINARY LOGS;"
sudo cp /var/log/mariadb/mariadb-bin.* /backup/mariadb/binlogs/

# Restore: load full dump, then replay binlogs to target time
gunzip < /backup/mariadb/myapp_full.sql.gz | mariadb -u root myapp
mysqlbinlog --stop-datetime="2026-03-22 14:30:00" /backup/mariadb/binlogs/mariadb-bin.00004* \
  | mariadb -u root
```

### MariaDB / MySQL — Automated Backup (systemd timer)

`/usr/local/bin/mariadb-backup.sh`:
```bash
#!/bin/bash
set -euo pipefail
BACKUP_DIR="/backup/mariadb"
RETENTION=14
TS=$(date +%Y%m%d_%H%M%S)
mkdir -p "$BACKUP_DIR"
mariadb-dump -u root --all-databases --single-transaction --routines --triggers --events \
  --flush-logs --source-data=2 | gzip > "$BACKUP_DIR/all_${TS}.sql.gz"
find "$BACKUP_DIR" -name "*.sql.gz" -mtime +$RETENTION -delete
```

Create matching `.service` and `.timer` units (same pattern as pg-backup above).

### Redis — Backup

```bash
# Trigger RDB save
redis-cli -a 'YourStr0ngRedisP@ss!' BGSAVE

# Copy RDB file
sudo cp /var/lib/redis/dump.rdb /backup/redis/dump_$(date +%Y%m%d).rdb

# AOF backup
# sudo cp -r /var/lib/redis/appendonlydir/ /backup/redis/aof_$(date +%Y%m%d)/

# Restore: stop Redis, replace dump.rdb (or AOF dir), start Redis
sudo systemctl stop redis
sudo cp /backup/redis/dump_20260322.rdb /var/lib/redis/dump.rdb
sudo chown redis:redis /var/lib/redis/dump.rdb
sudo systemctl start redis
```

---

---

## Anti-Patterns

| Anti-Pattern | Why It Fails | Correct Approach |
|---|---|---|
| Using default PostgreSQL/MySQL configuration for production | Default settings (shared_buffers=128MB, innodb_buffer_pool_size=128MB) are tuned for development, not production | Tune key parameters for available RAM: PostgreSQL shared_buffers=25% RAM, effective_cache_size=75%; MySQL innodb_buffer_pool_size=70% |
| No automated backup testing | Backups run nightly but are never tested; discover the backup is corrupt during an actual disaster | Test restore to a separate instance monthly; validate data integrity after restore; alert on backup job failures |
| Running databases without connection pooling | Each application connection costs memory (5-10MB per connection); 200 connections exhausts server RAM | Use PgBouncer (PostgreSQL) or ProxySQL (MySQL) for connection pooling; set pool size to match actual concurrent query needs |
| Granting superuser/root privileges to application accounts | One SQL injection gives attacker full database control; can drop tables, read other schemas, modify users | Create application-specific users with minimal privileges; GRANT only SELECT/INSERT/UPDATE/DELETE on required tables |
| Not monitoring slow query logs | Performance degradation builds silently; one bad query can saturate CPU/IO for all database users | Enable slow query logging (log_min_duration_statement for PG, slow_query_log for MySQL); review weekly; set alerts for extremes |

---

## Related Skills

| Workload | Skill |
|---|---|
| Core system admin (dnf, SELinux, firewalld, LVM) | `rhel-server-admin` |
| Web servers (Nginx, Apache, Caddy) | `rhel-web-servers` |
| Docker / Podman containers | `rhel-docker-host` |
| File sharing (NFS, Samba, Stratis) | `rhel-file-storage` |
| DNS, DHCP, NTP | `rhel-network-infra` |
| Prometheus, Grafana, logging | `rhel-monitoring` |
| NVIDIA GPU, Ollama, CUDA | `rhel-ollama-nvidia` |
