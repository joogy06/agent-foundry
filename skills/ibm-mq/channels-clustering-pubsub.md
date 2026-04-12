# Channels, Listeners, Clustering, and Pub/Sub

Reference file for the `ibm-mq` skill. Covers channels, listeners/triggers, MQ clustering, and publish/subscribe messaging.

## 6. Listeners & Triggers

### Listeners

```
runmqsc QM1

* Define a TCP listener on port 1414
DEFINE LISTENER('QM1.LSR') +
  TRPTYPE(TCP) +
  PORT(1414) +
  CONTROL(QMGR) +
  DESCR('TCP listener for QM1')

* CONTROL(QMGR) means the listener starts/stops with the queue manager

* Start the listener
START LISTENER('QM1.LSR')

* Display listener status
DISPLAY LSSTATUS('QM1.LSR') ALL

END
```

### Triggers

Triggers start applications automatically when messages arrive on a queue.

**Trigger types:**
- `FIRST` — fires when first message arrives on an empty queue.
- `EVERY` — fires for every message.
- `DEPTH` — fires when queue depth reaches TRIGDPTH.

```
runmqsc QM1

* Define the process (what to run)
DEFINE PROCESS('APP.PROCESS') +
  APPLICID('/opt/app/bin/process_messages.sh') +
  APPLTYPE(UNIX) +
  DESCR('Message processing application')

* Set trigger on the queue
ALTER QLOCAL('APP.REQUEST.Q') +
  TRIGTYPE(FIRST) +
  TRIGGER +
  INITQ('SYSTEM.DEFAULT.INITIATION.QUEUE') +
  PROCESS('APP.PROCESS')

END
```

Start the trigger monitor:

```bash
# As mqm user — starts the trigger monitor for the default initiation queue
runmqtrm -m QM1 -q SYSTEM.DEFAULT.INITIATION.QUEUE
```

---

## 7. Clustering

### Cluster Architecture

A cluster allows QMs to communicate without explicit remote queue/channel/transmission queue definitions for every pair. Requires at least two **full repository** QMs that hold the cluster metadata. Other QMs are **partial repositories**.

### Setting Up a Two-Node Cluster

```
* --- On QM1 (full repository) ---
runmqsc QM1

ALTER QMGR REPOS('MYCLUSTER')

DEFINE CHANNEL('TO.QM1') +
  CHLTYPE(CLUSRCVR) +
  TRPTYPE(TCP) +
  CONNAME('qm1-host.example.com(1414)') +
  CLUSTER('MYCLUSTER') +
  DESCR('Cluster receiver for QM1')

DEFINE CHANNEL('TO.QM2') +
  CHLTYPE(CLUSSDR) +
  TRPTYPE(TCP) +
  CONNAME('qm2-host.example.com(1414)') +
  CLUSTER('MYCLUSTER') +
  DESCR('Cluster sender to QM2')

END

* --- On QM2 (full repository) ---
runmqsc QM2

ALTER QMGR REPOS('MYCLUSTER')

DEFINE CHANNEL('TO.QM2') +
  CHLTYPE(CLUSRCVR) +
  TRPTYPE(TCP) +
  CONNAME('qm2-host.example.com(1414)') +
  CLUSTER('MYCLUSTER') +
  DESCR('Cluster receiver for QM2')

DEFINE CHANNEL('TO.QM1') +
  CHLTYPE(CLUSSDR) +
  TRPTYPE(TCP) +
  CONNAME('qm1-host.example.com(1414)') +
  CLUSTER('MYCLUSTER') +
  DESCR('Cluster sender to QM1')

END
```

### Adding a Partial Repository QM

```
* --- On QM3 (partial repository) ---
runmqsc QM3

DEFINE CHANNEL('TO.QM3') +
  CHLTYPE(CLUSRCVR) +
  TRPTYPE(TCP) +
  CONNAME('qm3-host.example.com(1414)') +
  CLUSTER('MYCLUSTER') +
  DESCR('Cluster receiver for QM3')

* Only needs one CLUSSDR to any full repository
DEFINE CHANNEL('TO.QM1') +
  CHLTYPE(CLUSSDR) +
  TRPTYPE(TCP) +
  CONNAME('qm1-host.example.com(1414)') +
  CLUSTER('MYCLUSTER') +
  DESCR('Cluster sender to full-repo QM1')

END
```

### Cluster Queues and Workload Balancing

```
runmqsc QM2

* Advertise a queue to the cluster — available cluster-wide
DEFINE QLOCAL('SHARED.WORK.Q') +
  CLUSTER('MYCLUSTER') +
  DEFPSIST(YES) +
  MAXDEPTH(50000) +
  DEFBIND(NOTFIXED) +
  CLWLRANK(1) +
  DESCR('Cluster-visible work queue on QM2')

END
```

When the same queue name is defined on multiple QMs in the cluster with `DEFBIND(NOTFIXED)`, MQ round-robins messages across instances (workload balancing). Use `CLWLRANK` and `CLWLPRTY` to control preference.

### Cluster Maintenance

```
runmqsc QM1

* Refresh cluster metadata (use sparingly — causes redistribution)
REFRESH CLUSTER('MYCLUSTER')

* Display cluster queue managers
DISPLAY CLUSQMGR(*) CLUSTER('MYCLUSTER')

* Display cluster queues
DISPLAY QC(*) CLUSTER('MYCLUSTER')

* Suspend a QM from the cluster (planned maintenance)
SUSPEND QMGR CLUSTER('MYCLUSTER')

* Resume after maintenance
RESUME QMGR CLUSTER('MYCLUSTER')

END
```

---

## 8. Publish/Subscribe

### Topics

```
runmqsc QM1

* Define an administrative topic object
DEFINE TOPIC('PRICES') +
  TOPICSTR('/market/prices') +
  DEFPSIST(NO) +
  DURSUB(YES) +
  DESCR('Market price updates')

* Display topic status
DISPLAY TPSTATUS('/market/prices/#') TYPE(PUB)
DISPLAY TPSTATUS('/market/prices/#') TYPE(SUB)

END
```

### Subscriptions

```
runmqsc QM1

* Administrative subscription (messages delivered to a queue)
DEFINE SUB('PRICES.SUB.AUDIT') +
  TOPICSTR('/market/prices/#') +
  DEST('AUDIT.PRICES.Q') +
  DESTQMGR('QM1') +
  DESCR('Audit subscription for all price updates')

END
```

### Wildcards

- `#` matches zero or more levels: `/market/prices/#` matches `/market/prices/fx`, `/market/prices/fx/eurusd`.
- `+` matches exactly one level: `/market/+/update` matches `/market/prices/update` but not `/market/prices/fx/update`.

### Retained Publications

```
runmqsc QM1

* Enable retained publications on a topic
ALTER TOPIC('PRICES') RETAIN(YES)

* New subscribers immediately receive the last published message.
* Clear retained publication:
CLEAR TOPICSTR('/market/prices')

END
```

### MQTT

IBM MQ supports MQTT clients via the Telemetry (MQXR) service. Define an MQTT channel:

```
runmqsc QM1

DEFINE CHANNEL('MQTT.SVRCONN') +
  CHLTYPE(MQTT) +
  TRPTYPE(TCP) +
  PORT(1883) +
  MCAUSER('mqtt_svc') +
  DESCR('MQTT client channel')

END
```

---

## 9. Security

### TLS Configuration

```bash
# Create key repository for the queue manager (as mqm user)
su - mqm
cd /var/mqm/qmgrs/QM1/ssl

# Create key database
runmqakm -keydb -create -db key.kdb -pw 'KeyDb$tr0ng!' -type cms -stash

# Generate a self-signed certificate (for testing)
runmqakm -cert -create -db key.kdb -pw 'KeyDb$tr0ng!' \
  -label ibmwebspheremqqm1 -dn "CN=qm1-host.example.com,O=MyOrg,C=GB" \
  -size 2048 -sig_alg SHA256WithRSA -expire 3650

# Import a CA-signed certificate
runmqakm -cert -receive -db key.kdb -pw 'KeyDb$tr0ng!' \
  -file qm1_signed.pem -label ibmwebspheremqqm1

# Add the CA certificate
runmqakm -cert -add -db key.kdb -pw 'KeyDb$tr0ng!' \
  -file ca_cert.pem -label "My CA"

# List certificates in the key database
runmqakm -cert -list -db key.kdb -pw 'KeyDb$tr0ng!'
```

Note: The certificate label must follow the pattern `ibmwebspheremq<qmgr_name_lowercase>` for queue managers, or `ibmwebspheremq<username>` for clients.

```
runmqsc QM1

* Set the key repository path (without .kdb extension)
ALTER QMGR SSLKEYR('/var/mqm/qmgrs/QM1/ssl/key') CERTLABL('ibmwebspheremqqm1')

* Enable TLS on a channel
ALTER CHANNEL('APP.SVRCONN') CHLTYPE(SVRCONN) +
  SSLCIPH('TLS_AES_256_GCM_SHA384') +
  SSLCAUTH(REQUIRED)

* For older TLS 1.2 cipher specs
ALTER CHANNEL('QM1.TO.QM2') CHLTYPE(SDR) +
  SSLCIPH('ECDHE_RSA_AES_256_GCM_SHA384')

* Refresh TLS after changes
REFRESH SECURITY TYPE(SSL)

END
```

### Channel Authentication Rules (CHLAUTH)

```
runmqsc QM1

* Block all connections by default on SVRCONN channels
SET CHLAUTH('*') TYPE(ADDRESSMAP) ADDRESS('*') USERSRC(NOACCESS) +
  DESCR('Default deny all')

* Allow specific subnet
SET CHLAUTH('APP.SVRCONN') TYPE(ADDRESSMAP) ADDRESS('10.0.1.*') +
  USERSRC(CHANNEL) +
  DESCR('Allow app subnet via APP.SVRCONN')

* Block the mqm user from connecting remotely
SET CHLAUTH('*') TYPE(BLOCKUSER) USERLIST('mqm') +
  DESCR('Block mqm user on all channels')

* Map TLS peer to specific MCAUSER
SET CHLAUTH('APP.SVRCONN') TYPE(SSLPEERMAP) +
  SSLPEER('CN=appserver.example.com,O=MyOrg') +
  USERSRC(MAP) MCAUSER('app_svc_acct') +
  DESCR('Map TLS cert to app service account')

* Map IP to specific MCAUSER
SET CHLAUTH('APP.SVRCONN') TYPE(USERMAP) +
  CLNTUSER('jdoe') USERSRC(MAP) MCAUSER('app_svc_acct') +
  DESCR('Map jdoe to app_svc_acct')

* Display CHLAUTH rules
DISPLAY CHLAUTH('APP.SVRCONN') ALL

END
```

### Object Authority Manager (OAM)

```bash
# Grant connect and inquire on the queue manager (as mqm user)
setmqaut -m QM1 -t qmgr -p app_svc_acct +connect +inq

# Grant put/get/browse on a queue
setmqaut -m QM1 -t queue -n 'APP.REQUEST.Q' -p app_svc_acct +put +get +browse +inq

# Grant subscribe on a topic
setmqaut -m QM1 -t topic -n 'PRICES' -p app_svc_acct +sub +pub

# Display authorities
dspmqaut -m QM1 -t queue -n 'APP.REQUEST.Q' -p app_svc_acct

# Dump all authorities
dmpmqaut -m QM1

# Grant authority to a group instead of a user
setmqaut -m QM1 -t queue -n 'APP.REQUEST.Q' -g appgroup +put +get +browse +inq
```

### Connection Authentication (CONNAUTH)

```
runmqsc QM1

* Require OS-level user/password for client connections
ALTER QMGR CONNAUTH('SYSTEM.DEFAULT.AUTHINFO.IDPWOS')

ALTER AUTHINFO('SYSTEM.DEFAULT.AUTHINFO.IDPWOS') +
  AUTHTYPE(IDPWOS) +
  ADOPTCTX(YES) +
  CHCKCLNT(REQUIRED) +
  CHCKLOCL(OPTIONAL)

REFRESH SECURITY TYPE(CONNAUTH)

END
```

---

