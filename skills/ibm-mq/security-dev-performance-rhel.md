# Security, Developer Patterns, Performance, Monitoring, and RHEL Config

Reference file for the `ibm-mq` skill. Covers MQ security, developer patterns (JMS, Spring JMS, MQ classes for Java), performance tuning, monitoring, and RHEL-specific configuration.

## 10. Developer Patterns

### JMS 2.0

```java
import javax.jms.*;
import com.ibm.msg.client.jms.JmsConnectionFactory;
import com.ibm.msg.client.jms.JmsFactoryFactory;
import com.ibm.msg.client.wmq.WMQConstants;

JmsFactoryFactory ff = JmsFactoryFactory.getInstance(WMQConstants.WMQ_PROVIDER);
JmsConnectionFactory cf = ff.createConnectionFactory();
cf.setStringProperty(WMQConstants.WMQ_HOST_NAME, "qm1-host.example.com");
cf.setIntProperty(WMQConstants.WMQ_PORT, 1414);
cf.setStringProperty(WMQConstants.WMQ_CHANNEL, "APP.SVRCONN");
cf.setIntProperty(WMQConstants.WMQ_CONNECTION_MODE, WMQConstants.WMQ_CM_CLIENT);
cf.setStringProperty(WMQConstants.WMQ_QUEUE_MANAGER, "QM1");

try (JMSContext context = cf.createContext("app_svc_acct", "password")) {
    Destination queue = context.createQueue("queue:///APP.REQUEST.Q");

    // Send
    JMSProducer producer = context.createProducer();
    producer.send(queue, "Hello from JMS 2.0");

    // Receive (synchronous, 5 second timeout)
    JMSConsumer consumer = context.createConsumer(queue);
    String msg = consumer.receiveBody(String.class, 5000);
    System.out.println("Received: " + msg);
}
```

### MQI (C — Low-Level API)

```c
#include <cmqc.h>
#include <cmqxc.h>
#include <string.h>

MQHCONN hConn;
MQHOBJ  hObj;
MQOD    od = {MQOD_DEFAULT};
MQMD    md = {MQMD_DEFAULT};
MQPMO   pmo = {MQPMO_DEFAULT};
MQGMO   gmo = {MQGMO_DEFAULT};
MQLONG  compCode, reason;
char    buffer[4096];

/* Connect */
MQCONN("QM1", &hConn, &compCode, &reason);

/* Open queue for output */
strncpy(od.ObjectName, "APP.REQUEST.Q", MQ_Q_NAME_LENGTH);
MQOPEN(hConn, &od, MQOO_OUTPUT, &hObj, &compCode, &reason);

/* Put a message */
memcpy(md.Format, MQFMT_STRING, MQ_FORMAT_LENGTH);
pmo.Options = MQPMO_NO_SYNCPOINT | MQPMO_NEW_MSG_ID | MQPMO_NEW_CORREL_ID;
char *msg = "Hello from MQI";
MQPUT(hConn, hObj, &md, &pmo, strlen(msg), msg, &compCode, &reason);

/* Close and disconnect */
MQCLOSE(hConn, &hObj, MQCO_NONE, &compCode, &reason);
MQDISC(&hConn, &compCode, &reason);
```

Compile:
```bash
gcc -m64 -o mqput mqput.c -I/opt/mqm/inc -L/opt/mqm/lib64 -lmqm_r
```

### Python (pymqi)

```bash
pip install pymqi
```

```python
import pymqi

qmgr_name = "QM1"
channel = "APP.SVRCONN"
host = "qm1-host.example.com"
port = "1414"
conn_info = f"{host}({port})"
user = "app_svc_acct"
password = "password"

# Connect
qmgr = pymqi.connect(qmgr_name, channel, conn_info, user, password)

# Put a message
queue = pymqi.Queue(qmgr, "APP.REQUEST.Q")
queue.put(b"Hello from Python pymqi")
queue.close()

# Get a message
queue = pymqi.Queue(qmgr, "APP.REQUEST.Q")
try:
    msg = queue.get()
    print(f"Received: {msg.decode()}")
except pymqi.MQMIError as e:
    if e.comp == pymqi.CMQC.MQCC_FAILED and e.reason == pymqi.CMQC.MQRC_NO_MSG_AVAILABLE:
        print("No messages available")
    else:
        raise
finally:
    queue.close()

# Disconnect
qmgr.disconnect()
```

### .NET

```csharp
using IBM.WMQ;
using System.Collections;

Hashtable props = new Hashtable {
    { MQConstants.HOST_NAME_PROPERTY, "qm1-host.example.com" },
    { MQConstants.PORT_PROPERTY, 1414 },
    { MQConstants.CHANNEL_PROPERTY, "APP.SVRCONN" },
    { MQConstants.USER_ID_PROPERTY, "app_svc_acct" },
    { MQConstants.PASSWORD_PROPERTY, "password" },
    { MQConstants.TRANSPORT_PROPERTY, MQConstants.TRANSPORT_MQSERIES_MANAGED }
};

MQQueueManager qmgr = new MQQueueManager("QM1", props);

// Put
MQQueue putQueue = qmgr.AccessQueue("APP.REQUEST.Q", MQConstants.MQOO_OUTPUT);
MQMessage putMsg = new MQMessage();
putMsg.WriteString("Hello from .NET");
putQueue.Put(putMsg);
putQueue.Close();

// Get
MQQueue getQueue = qmgr.AccessQueue("APP.REQUEST.Q", MQConstants.MQOO_INPUT_AS_Q_DEF);
MQMessage getMsg = new MQMessage();
MQGetMessageOptions gmo = new MQGetMessageOptions { WaitInterval = 5000 };
gmo.Options |= MQConstants.MQGMO_WAIT;
getQueue.Get(getMsg, gmo);
Console.WriteLine($"Received: {getMsg.ReadString(getMsg.MessageLength)}");
getQueue.Close();

qmgr.Disconnect();
```

### REST API (MQ 9.1+)

```bash
# Enable the MQ REST API (mqweb server)
su - mqm
/opt/mqm/bin/strmqweb

# Get queue manager details
curl -k -u admin:password https://qm1-host.example.com:9443/ibmmq/rest/v2/admin/qmgr/QM1

# Browse messages on a queue
curl -k -u admin:password https://qm1-host.example.com:9443/ibmmq/rest/v2/messaging/qmgr/QM1/queue/APP.REQUEST.Q/message

# Post a message
curl -k -u admin:password -X POST \
  -H "Content-Type: text/plain" \
  -H "ibm-mq-rest-csrf-token: blank" \
  -d "Hello from REST" \
  https://qm1-host.example.com:9443/ibmmq/rest/v2/messaging/qmgr/QM1/queue/APP.REQUEST.Q/message
```

### Request/Reply Pattern

```python
import pymqi
import pymqi.CMQC as CMQC

qmgr = pymqi.connect("QM1", "APP.SVRCONN", "qm1-host(1414)", "user", "pass")

# Create a temporary dynamic reply queue
reply_queue = pymqi.Queue(qmgr, "APP.REPLY.MODEL")

# Get the dynamic queue name
reply_qname = reply_queue.inquire(CMQC.MQCA_Q_NAME).strip()

# Build request message with ReplyToQ
md = pymqi.MD()
md.ReplyToQ = reply_qname.encode()
md.MsgType = CMQC.MQMT_REQUEST
md.Format = CMQC.MQFMT_STRING

# Send request
request_q = pymqi.Queue(qmgr, "APP.REQUEST.Q")
request_q.put(b"What is the price of EURUSD?", md)
request_q.close()

# Wait for reply (correlate by MsgId -> CorrelId)
gmo = pymqi.GMO()
gmo.Options = CMQC.MQGMO_WAIT | CMQC.MQGMO_CONVERT
gmo.WaitInterval = 30000
get_md = pymqi.MD()
get_md.CorrelId = md.MsgId

reply = reply_queue.get(None, get_md, gmo)
print(f"Reply: {reply.decode()}")
reply_queue.close()
qmgr.disconnect()
```

### Poison Message Handling

When an application fails to process a message and rolls back repeatedly, the message becomes a "poison message." Configure the backout threshold and requeue queue:

```
ALTER QLOCAL('APP.REQUEST.Q') BOTHRESH(3) BOQNAME('APP.REQUEST.Q.BACKOUT')
```

Application code should check the `BackoutCount` in the MQMD:
- If `BackoutCount >= BOTHRESH`, move the message to the backout queue or a dead-letter queue programmatically.
- JMS: The IBM MQ JMS client handles this automatically if `BOTHRESH` and `BOQNAME` are set.

---

## 11. Performance Tuning

### Log Tuning

```bash
# View current log settings
dspmqinf -o command QM1
```

**Circular logging (default):** reuses log extents. Good for performance, but no media recovery. Suitable when replaying from backups is acceptable.

**Linear logging:** keeps all log extents. Required for media recovery. Higher disk usage.

```bash
# Created at crtmqm time — cannot change after creation
# Circular (default):
crtmqm -lc QM1

# Linear:
crtmqm -ll QM1

# Tune log extent sizes in qm.ini (/var/mqm/qmgrs/QM1/qm.ini)
# [Log]
#   LogPrimaryFiles=16
#   LogSecondaryFiles=4
#   LogFilePages=4096       # each page = 4 KB, so 4096 pages = 16 MB per extent
#   LogBufferPages=512
```

### Persistent vs Non-Persistent Messages

- **Persistent (DEFPSIST YES):** written to log before acknowledged. Survives QM restart. Higher latency.
- **Non-persistent (DEFPSIST NO):** held in memory. Faster, but lost on QM restart. Use for ephemeral data (events, heartbeats).

### Channel Tuning

```
runmqsc QM1

* Increase batch size (messages per batch before sync point)
ALTER CHANNEL('QM1.TO.QM2') CHLTYPE(SDR) BATCHSZ(100)

* Batch interval — wait up to N ms to fill a batch (reduces network round-trips)
ALTER CHANNEL('QM1.TO.QM2') CHLTYPE(SDR) BATCHINT(2000)

* Disconnect interval — 0 means never disconnect (persistent connection)
ALTER CHANNEL('QM1.TO.QM2') CHLTYPE(SDR) DISCINT(0)

* Heartbeat interval (seconds) — detect dead connections
ALTER CHANNEL('QM1.TO.QM2') CHLTYPE(SDR) HBINT(30)

* Shared conversations on SVRCONN (multiplex clients over fewer connections)
ALTER CHANNEL('APP.SVRCONN') CHLTYPE(SVRCONN) SHARECNV(10)

END
```

### Queue Depth and Buffer Pool

```
runmqsc QM1

* Increase max depth for high-throughput queues
ALTER QLOCAL('APP.EVENT.Q') MAXDEPTH(999999999)

END
```

### Read-Ahead

For non-persistent messages, read-ahead allows the client to buffer messages locally, reducing network round-trips:

```
runmqsc QM1

* Enable read-ahead on a queue
ALTER QLOCAL('APP.EVENT.Q') DEFREADA(YES)

END
```

Application must use `MQOO_READ_AHEAD` option on MQOPEN, and the queue must have `DEFREADA(YES)`.

### qm.ini Tuning (Key Parameters)

```ini
# /var/mqm/qmgrs/QM1/qm.ini

[TuningParameters]
DefaultPQBufferSize=1048576
DefaultQBufferSize=1048576

[Channels]
MaxChannels=500
MaxActiveChannels=500

[TCP]
KeepAlive=YES
```

---

## 12. Monitoring

### dspmq and runmqsc

```bash
# Queue manager status
dspmq -m QM1 -o all

# Queue depth monitoring
echo "DISPLAY QLOCAL(*) CURDEPTH MAXDEPTH" | runmqsc QM1

# Specific queue status (detailed)
echo "DISPLAY QSTATUS('APP.REQUEST.Q') ALL" | runmqsc QM1

# Channel status
echo "DISPLAY CHSTATUS(*) ALL" | runmqsc QM1

# Connection status (who is connected)
echo "DISPLAY CONN(*) ALL" | runmqsc QM1

# Subscription status
echo "DISPLAY SBSTATUS(*) ALL" | runmqsc QM1
```

### Event Queues

```
runmqsc QM1

* Enable queue manager events
ALTER QMGR AUTHOREV(ENABLED) INHIBTEV(ENABLED) LOCALEV(ENABLED) +
  REMOTEEV(ENABLED) STRSTPEV(ENABLED) PERFMEV(ENABLED)

* Events are written to system event queues:
*   SYSTEM.ADMIN.QMGR.EVENT
*   SYSTEM.ADMIN.PERFM.EVENT
*   SYSTEM.ADMIN.CHANNEL.EVENT
*   SYSTEM.ADMIN.COMMAND.EVENT

END
```

### amqsmon — Sample Event Monitor

```bash
# Display performance events
/opt/mqm/samp/bin/amqsmon -m QM1 -t statistics -q SYSTEM.ADMIN.STATISTICS.QUEUE

# Display accounting data
/opt/mqm/samp/bin/amqsmon -m QM1 -t accounting -q SYSTEM.ADMIN.ACCOUNTING.QUEUE
```

### Prometheus Exporter

The community `mq_exporter` or IBM's `mq-metric-samples` expose MQ metrics for Prometheus/Grafana:

```bash
# Clone IBM MQ metric samples
git clone https://github.com/ibm-messaging/mq-metric-samples.git

# Build the Prometheus collector
cd mq-metric-samples/cmd/mq_prometheus
go build -o mq_prometheus

# Run (connects as MQ client)
./mq_prometheus -ibmmq.queueManager=QM1 \
  -ibmmq.connName="qm1-host(1414)" \
  -ibmmq.channel=SYSTEM.ADMIN.SVRCONN \
  -ibmmq.userid=monitor_user \
  -ibmmq.password=password \
  -log.level=info
```

Metrics endpoint: `http://localhost:9157/metrics`. Scrape with Prometheus and build Grafana dashboards for queue depth, channel status, message rates, and connection counts.

### Common Alerts

| Condition | What to Monitor | Threshold |
|---|---|---|
| Queue filling up | `CURDEPTH / MAXDEPTH` | > 80% |
| Channel retrying | `CHSTATUS` state = `RETRYING` | Any occurrence |
| Channel stopped | `CHSTATUS` state = `STOPPED` | Any occurrence |
| DLQ depth growing | `DLQ.QM1 CURDEPTH` | > 0 (investigate) |
| QM not running | `dspmq` status != `Running` | Any occurrence |
| Connection count high | `DISPLAY CONN(*) COUNT` | > 80% of max |
| Persistent message rate | Performance events | Sustained high rate |

---

## 13. RHEL-Specific

### SELinux for /var/mqm

```bash
# Set correct SELinux context for MQ data directory
sudo semanage fcontext -a -t var_t "/var/mqm(/.*)?"
sudo restorecon -Rv /var/mqm

# If MQ data is on a non-standard path
sudo semanage fcontext -a -t var_t "/data/mqm(/.*)?"
sudo restorecon -Rv /data/mqm

# Verify
ls -ldZ /var/mqm

# Troubleshoot SELinux denials
sudo ausearch -m AVC -c amqzxma0 --start recent
sudo ausearch -m AVC -c runmqsc --start recent
sudo sealert -a /var/log/audit/audit.log

# If SELinux is blocking MQ network operations
sudo setsebool -P nis_enabled 1
```

### Firewalld

```bash
# MQ listener port (restrict to app subnet)
sudo firewall-cmd --permanent --add-rich-rule='rule family="ipv4" source address="10.0.1.0/24" port port="1414" protocol="tcp" accept'

# MQ web console / REST API
sudo firewall-cmd --permanent --add-rich-rule='rule family="ipv4" source address="10.0.1.0/24" port port="9443" protocol="tcp" accept'

# MQTT (if used)
sudo firewall-cmd --permanent --add-rich-rule='rule family="ipv4" source address="10.0.1.0/24" port port="1883" protocol="tcp" accept'

# Cluster inter-QM communication (if QMs on different hosts)
sudo firewall-cmd --permanent --add-rich-rule='rule family="ipv4" source address="10.0.2.0/24" port port="1414" protocol="tcp" accept'

# Apply and verify
sudo firewall-cmd --reload
sudo firewall-cmd --list-rich-rules
```

### Systemd Service

IBM MQ does not ship a systemd unit file by default. Create one:

`/etc/systemd/system/mq@.service` (template unit per queue manager):

```ini
[Unit]
Description=IBM MQ Queue Manager %i
After=network-online.target
Wants=network-online.target

[Service]
Type=forking
User=mqm
Group=mqm
Environment=PATH=/opt/mqm/bin:/usr/bin:/bin
Environment=LD_LIBRARY_PATH=/opt/mqm/lib64

ExecStart=/opt/mqm/bin/strmqm %i
ExecStop=/opt/mqm/bin/endmqm -w %i
ExecReload=/opt/mqm/bin/endmqm -r %i

TimeoutStartSec=120
TimeoutStopSec=300
Restart=on-failure
RestartSec=30

LimitNOFILE=10240
LimitNPROC=4096

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now mq@QM1.service
sudo systemctl status mq@QM1.service
journalctl -u mq@QM1.service -f
```

### mqm Group Permissions

```bash
# Application users that need MQ client libraries must be in the mqm group
sudo usermod -aG mqm appuser

# Verify
id appuser
groups appuser

# For non-privileged access (MQ 9.1+), use CONNAUTH instead of mqm group membership
# Only administrative tools (runmqsc, dspmq, crtmqm) require mqm group
```

### limits.conf

```bash
# /etc/security/limits.d/99-mqm.conf
mqm  hard  nofile  10240
mqm  soft  nofile  10240
mqm  hard  nproc   4096
mqm  soft  nproc   4096
mqm  hard  core    unlimited
mqm  soft  core    unlimited
```

Verify after login as mqm: `ulimit -a`

---

## Related Skills

| Workload | Skill |
|---|---|
| Core RHEL admin (dnf, SELinux, firewalld, LVM) | `rhel-server-admin` |
| WebSphere Application Server | `ibm-websphere` |
| DB2 on RHEL | `db2-rhel` |
| DB2 on z/OS | `db2-mainframe` |
| Python MQ connectors | `python-enterprise-connectors` |
| Docker / Podman containers | `rhel-docker-host` |
| Prometheus, Grafana, logging | `rhel-monitoring` |
| IBM mainframe (JCL, VSAM, TSO) | `ibm-mainframe` |
