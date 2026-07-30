---
name: ubuntu-databases
description: Use when installing, configuring, or managing databases on Ubuntu 24.04 LTS — PostgreSQL 16, MySQL 8/MariaDB, Redis 7, performance tuning, backup/restore, replication, connection pooling, user/role management, and monitoring. Part of the ubuntu-* skill family.
family: ubuntu
applies_when: os_family == debian
---

# Ubuntu Server 24.04 LTS — Database Administration

Companion skill to `ubuntu-server-admin`. For other workloads see: `ubuntu-web-servers`, `ubuntu-docker-host`, `ubuntu-file-storage`, `ubuntu-network-infra`, `ubuntu-monitoring`, `ubuntu-ollama-nvidia`.

<HARD-RULE>
Always take a full backup before any database upgrade, major config change, or replication topology change. Untested restores are not backups — verify by restoring to a scratch instance.
</HARD-RULE>

<HARD-RULE>
Never run database processes as root. PostgreSQL uses `postgres`, MySQL uses `mysql`, Redis uses `redis`. Grant application accounts only the minimum privileges needed.
</HARD-RULE>

<HARD-RULE>
Never expose database ports (5432, 3306, 6379) to the public internet without TLS and strong authentication. Use UFW to restrict to trusted subnets.
</HARD-RULE>

---

## 1. PostgreSQL 16

### Installation (Official Apt Repo)

```bash
sudo apt install -y curl ca-certificates
sudo install -d /usr/share/postgresql-common/pgdg
sudo curl -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc \
  --fail https://www.postgresql.org/media/keys/ACCC4CF8.asc
echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] \
  https://apt.postgresql.org/pub/repos/apt noble-pgdg main" \
  | sudo tee /etc/apt/sources.list.d/pgdg.list
sudo apt update && sudo apt install -y postgresql-16 postgresql-client-16
```

Key paths: config `/etc/postgresql/16/main/postgresql.conf`, auth `/etc/postgresql/16/main/pg_hba.conf`, data `/var/lib/postgresql/16/main/`, logs `/var/log/postgresql/postgresql-16-main.log`.

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
archive_command = 'cp %p /var/lib/postgresql/16/archive/%f'
random_page_cost = 1.1            # SSD (4.0 for HDD)
effective_io_concurrency = 200    # SSD (2 for HDD)
max_parallel_workers_per_gather = 2
max_parallel_workers = 4
log_min_duration_statement = 500  # ms
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
sudo -u postgres pg_dump -Fc myapp -f /backup/pg/myapp_$(date +%Y%m%d).dump    # custom format
sudo -u postgres pg_dumpall > /backup/pg/all_$(date +%Y%m%d).sql               # all databases
sudo -u postgres pg_restore -d myapp -j 4 --clean --if-exists /backup/pg/myapp.dump  # restore
```

### Streaming Replication

**Primary:** create replication user, ensure `wal_level = replica` and pg_hba allows standby.

```bash
sudo -u postgres psql -c "CREATE ROLE replicator WITH REPLICATION LOGIN PASSWORD 'ReplP@ss!2024';"
```

**Standby:** stop PG, clear data dir, base backup with `-R` flag, start.

```bash
sudo systemctl stop postgresql
sudo rm -rf /var/lib/postgresql/16/main/*
sudo -u postgres pg_basebackup -h 10.0.1.10 -U replicator -D /var/lib/postgresql/16/main -Fp -Xs -P -R
sudo systemctl start postgresql
```

Verify: `SELECT client_addr, state, replay_lsn FROM pg_stat_replication;` (primary), `SELECT pg_is_in_recovery();` (standby).

### PgBouncer Connection Pooling

```bash
sudo apt install -y pgbouncer
```

`/etc/pgbouncer/pgbouncer.ini`:

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

Generate userlist from PG: `sudo -u postgres psql -tAc "SELECT '\"'||rolname||'\" \"'||rolpassword||'\"' FROM pg_authid WHERE rolcanlogin" > /etc/pgbouncer/userlist.txt`

### pg_stat Monitoring

```sql
SELECT pid, usename, state, query FROM pg_stat_activity WHERE state != 'idle';
SELECT relname, n_dead_tup, last_autovacuum FROM pg_stat_user_tables ORDER BY n_dead_tup DESC LIMIT 10;
SELECT round(100.0*sum(blks_hit)/nullif(sum(blks_hit)+sum(blks_read),0),2) AS cache_pct FROM pg_stat_database;
-- Requires shared_preload_libraries = 'pg_stat_statements'
SELECT query, calls, mean_exec_time::numeric(10,2) FROM pg_stat_statements ORDER BY total_exec_time DESC LIMIT 10;
SELECT client_addr, pg_wal_lsn_diff(pg_current_wal_lsn(), replay_lsn) AS lag_bytes FROM pg_stat_replication;
```

---

## 2. MySQL 8 / MariaDB

### Installation

```bash
# MySQL 8 (from default Ubuntu repos)
sudo apt install -y mysql-server && sudo systemctl enable --now mysql
sudo mysql_secure_installation

# MariaDB (alternative)
sudo apt install -y mariadb-server && sudo systemctl enable --now mariadb
sudo mariadb-secure-installation
```

### my.cnf Tuning (16 GB / 4-core)

Drop-in: `/etc/mysql/mysql.conf.d/99-tuning.cnf`

```ini
[mysqld]
innodb_buffer_pool_size = 11G     # ~70% RAM for dedicated DB
innodb_buffer_pool_instances = 8
innodb_log_file_size = 1G
innodb_flush_log_at_trx_commit = 1
innodb_flush_method = O_DIRECT
innodb_io_capacity = 2000
max_connections = 300
log_bin = /var/log/mysql/mysql-bin
binlog_expire_logs_seconds = 604800
binlog_format = ROW
sync_binlog = 1
server_id = 1
slow_query_log = 1
slow_query_log_file = /var/log/mysql/mysql-slow.log
long_query_time = 1
character_set_server = utf8mb4
```

### User Management

```sql
CREATE USER 'appuser'@'10.0.1.%' IDENTIFIED BY 'StrongP@ss!2024';
GRANT SELECT, INSERT, UPDATE, DELETE ON myapp.* TO 'appuser'@'10.0.1.%';
CREATE USER 'readonly'@'10.0.1.%' IDENTIFIED BY 'ReadP@ss!2024';
GRANT SELECT ON myapp.* TO 'readonly'@'10.0.1.%';
FLUSH PRIVILEGES;
```

### Backup — mysqldump

```bash
mysqldump -u root --single-transaction --routines --triggers myapp | gzip > /backup/mysql/myapp_$(date +%Y%m%d).sql.gz
mysql -u root myapp < /backup/mysql/myapp.sql   # restore
```

### Replication (Source / Replica)

**Source:** enable `log_bin`, `server_id=1`, create replicator user with `REPLICATION SLAVE`.

**Replica:** set `server_id=2`, then:

```sql
CHANGE REPLICATION SOURCE TO SOURCE_HOST='10.0.1.10', SOURCE_USER='replicator',
  SOURCE_PASSWORD='ReplP@ss!2024', SOURCE_LOG_FILE='mysql-bin.000001', SOURCE_LOG_POS=154;
START REPLICA;
SHOW REPLICA STATUS\G   -- check Replica_IO_Running=Yes, Replica_SQL_Running=Yes
```

### Slow Query Analysis

```bash
mysqldumpslow -s t -t 10 /var/log/mysql/mysql-slow.log
# Or: sudo apt install -y percona-toolkit && pt-query-digest /var/log/mysql/mysql-slow.log
```

---

## 3. Redis 7

### Installation (Official Repo)

```bash
curl -fsSL https://packages.redis.io/gpg | sudo gpg --dearmor -o /usr/share/keyrings/redis-archive-keyring.gpg
echo "deb [signed-by=/usr/share/keyrings/redis-archive-keyring.gpg] https://packages.redis.io/deb noble main" \
  | sudo tee /etc/apt/sources.list.d/redis.list
sudo apt update && sudo apt install -y redis-server
sudo systemctl enable --now redis-server
```

### redis.conf Tuning

Config: `/etc/redis/redis.conf`

```
bind 127.0.0.1 10.0.1.10
protected-mode yes
maxmemory 4gb
maxmemory-policy allkeys-lru       # options: noeviction, allkeys-lfu, volatile-lru, volatile-ttl, etc.
# RDB persistence
save 900 1
save 300 10
save 60 10000
# AOF persistence (enable for durability)
appendonly yes
appendfsync everysec               # always | everysec | no
io-threads 4
requirepass YourStr0ngRedisP@ss!
rename-command FLUSHALL ""
rename-command FLUSHDB ""
```

RDB = fast restart, minutes of data loss. AOF = ~1s loss, slower restart. Enable both for critical data.

### Sentinel (HA)

```bash
sudo apt install -y redis-sentinel
```

`/etc/redis/sentinel.conf`:

```
port 26379
sentinel monitor mymaster 10.0.1.10 6379 2
sentinel auth-pass mymaster YourStr0ngRedisP@ss!
sentinel down-after-milliseconds mymaster 5000
sentinel failover-timeout mymaster 60000
```

### ACLs

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
```

---

## 4. Common Patterns

### Systemd Services

```bash
sudo systemctl start|stop|restart|reload postgresql   # reload for config
sudo systemctl start|stop|restart mysql
sudo systemctl start|stop|restart redis-server
journalctl -u postgresql -f   # tail logs (substitute service name)
```

### UFW Firewall Rules

```bash
sudo ufw allow from 10.0.1.0/24 to any port 5432 proto tcp comment 'PostgreSQL'
sudo ufw allow from 10.0.1.0/24 to any port 6432 proto tcp comment 'PgBouncer'
sudo ufw allow from 10.0.1.0/24 to any port 3306 proto tcp comment 'MySQL'
sudo ufw allow from 10.0.1.0/24 to any port 6379 proto tcp comment 'Redis'
```

### TLS/SSL

**PostgreSQL:** generate cert, set `ssl = on` + `ssl_cert_file` + `ssl_key_file` in postgresql.conf, use `hostssl` in pg_hba.conf.

```bash
sudo -u postgres openssl req -new -x509 -days 3650 -nodes \
  -out /etc/postgresql/16/main/server.crt -keyout /etc/postgresql/16/main/server.key -subj "/CN=db01"
sudo chmod 600 /etc/postgresql/16/main/server.key
```

**MySQL:** auto-generates certs at install. Enforce per user: `ALTER USER 'appuser'@'10.0.1.%' REQUIRE SSL;`

**Redis:** set `tls-port 6380`, `port 0`, `tls-cert-file`, `tls-key-file`, `tls-ca-cert-file` in redis.conf.

### Health Checks

```bash
sudo -u postgres pg_isready -h 127.0.0.1 -p 5432   # exit 0 = healthy
mysqladmin -u root ping
redis-cli -a 'YourStr0ngRedisP@ss!' ping            # returns PONG
```

### Log Rotation

PG and MySQL handle rotation internally. For Redis, add `/etc/logrotate.d/redis`:

```
/var/log/redis/*.log { weekly rotate 12 compress delaycompress missingok copytruncate }
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
[Install]
WantedBy=timers.target
```

`/usr/local/bin/pg-backup.sh`:
```bash
#!/bin/bash
set -euo pipefail
BACKUP_DIR="/backup/postgresql"; RETENTION=14; TS=$(date +%Y%m%d_%H%M%S)
mkdir -p "$BACKUP_DIR"
for DB in $(psql -At -c "SELECT datname FROM pg_database WHERE NOT datistemplate AND datname!='postgres'"); do
  pg_dump -Fc "$DB" -f "$BACKUP_DIR/${DB}_${TS}.dump"
done
pg_dumpall --globals-only -f "$BACKUP_DIR/globals_${TS}.sql"
find "$BACKUP_DIR" -name "*.dump" -mtime +$RETENTION -delete
find "$BACKUP_DIR" -name "*.sql" -mtime +$RETENTION -delete
```

Enable: `sudo chmod +x /usr/local/bin/pg-backup.sh && sudo systemctl daemon-reload && sudo systemctl enable --now pg-backup.timer`

### PostgreSQL — Point-in-Time Recovery (PITR)

Requires `archive_mode = on` + `archive_command` (see tuning above).

```bash
# Baseline: take a base backup
sudo -u postgres pg_basebackup -D /backup/postgresql/pitr_base -Ft -z -Xs -P

# Recovery: stop PG, clear data dir, restore base, create recovery.signal
sudo systemctl stop postgresql
sudo rm -rf /var/lib/postgresql/16/main/*
sudo -u postgres tar xzf /backup/postgresql/pitr_base/base.tar.gz -C /var/lib/postgresql/16/main/
sudo -u postgres tar xzf /backup/postgresql/pitr_base/pg_wal.tar.gz -C /var/lib/postgresql/16/main/pg_wal/
sudo -u postgres touch /var/lib/postgresql/16/main/recovery.signal
sudo -u postgres tee -a /var/lib/postgresql/16/main/postgresql.auto.conf <<'EOF'
restore_command = 'cp /var/lib/postgresql/16/archive/%f %p'
recovery_target_time = '2026-03-22 14:30:00'
recovery_target_action = 'promote'
EOF
sudo systemctl start postgresql
```

### MySQL — Binary Log PITR

```bash
mysql -u root -e "FLUSH BINARY LOGS;"
sudo cp /var/log/mysql/mysql-bin.* /backup/mysql/binlogs/
# Restore: load full dump, then replay binlogs to target time
mysql -u root myapp < /backup/mysql/myapp_full.sql
mysqlbinlog --stop-datetime="2026-03-22 14:30:00" /backup/mysql/binlogs/mysql-bin.00004* | mysql -u root
```

### MySQL — Automated Backup (systemd timer)

Same pattern as PG above. Script essentials:

```bash
#!/bin/bash
set -euo pipefail
BACKUP_DIR="/backup/mysql"; RETENTION=14; TS=$(date +%Y%m%d_%H%M%S)
mkdir -p "$BACKUP_DIR"
mysqldump -u root --all-databases --single-transaction --routines --triggers --events \
  --flush-logs --source-data=2 | gzip > "$BACKUP_DIR/all_${TS}.sql.gz"
find "$BACKUP_DIR" -name "*.sql.gz" -mtime +$RETENTION -delete
```

### Redis — Backup

```bash
redis-cli -a 'YourStr0ngRedisP@ss!' BGSAVE
sudo cp /var/lib/redis/dump.rdb /backup/redis/dump_$(date +%Y%m%d).rdb
# AOF: sudo cp -r /var/lib/redis/appendonlydir/ /backup/redis/aof_$(date +%Y%m%d)/
# Restore: stop Redis, replace dump.rdb or AOF dir, start Redis
```

---

---

## Anti-Patterns

| Anti-Pattern | Why It Fails | Correct Approach |
|---|---|---|
| Running PostgreSQL with default shared_buffers (128MB) in production | Database constantly reads from disk; query performance 5-10x slower than properly tuned instance | Set shared_buffers to 25% of RAM; effective_cache_size to 75%; tune work_mem based on query complexity |
| No automated backups with tested restore | Backups may exist but have never been verified; discover corruption during actual disaster recovery | Schedule pg_dump or pg_basebackup nightly; test restore to separate instance monthly; alert on backup failures |
| Granting superuser to application database users | SQL injection gives attacker full database control; can read other databases, modify roles, drop tables | Create application-specific roles with minimal privileges; GRANT only needed permissions on specific schemas/tables |
| Running Redis without persistence configuration | Server restart loses all cached data; if used as primary store, data loss is permanent | Configure RDB snapshots and/or AOF persistence; choose based on durability vs performance trade-off |
| Not using connection pooling for PostgreSQL | Each connection costs 5-10MB RAM; 200 application threads = 2GB just for connections; OOM kills PostgreSQL | Deploy PgBouncer in transaction pooling mode; size pool to actual concurrent query needs (usually 20-50) |

---

## Related Skills

| Workload | Skill |
|---|---|
| Core system admin | `ubuntu-server-admin` |
| Web servers (Nginx, Apache, Caddy) | `ubuntu-web-servers` |
| Docker / containers | `ubuntu-docker-host` |
| File sharing (NFS, Samba, ZFS) | `ubuntu-file-storage` |
| DNS, DHCP, NTP | `ubuntu-network-infra` |
| Prometheus, Grafana, logging | `ubuntu-monitoring` |
| NVIDIA GPU, Ollama, CUDA | `ubuntu-ollama-nvidia` |
