# Architecture, Installation, Queue Manager, and Queue Types

Reference file for the `ibm-mq` skill. Covers MQ architecture, RHEL 9 installation, queue manager administration, and queue types (local, remote, alias, model).

## 1. Architecture

### Core Model

IBM MQ is a message-oriented middleware that provides asynchronous, reliable message delivery between applications. The fundamental unit is the **queue manager** (QM), which owns and manages queues, channels, listeners, and other objects.

**Message flow (point-to-point):** Application A -> MQPUT -> Local Queue -> Channel (sender/receiver) -> Remote Queue Manager -> Local Queue -> MQGET -> Application B.

**Key concepts:**
- **Queue Manager (QM):** Independent MQ server process. Each QM has its own directory under `/var/mqm/qmgrs/`. Multiple QMs can run on one host.
- **Queues:** Named message stores. Messages are byte arrays with headers (MQMD). Queue types: local, remote (pointer), alias (indirection), model (template for dynamic queues).
- **Channels:** Unidirectional communication links between QMs (MCA channels) or between client applications and QMs (MQI channels). Always defined in pairs (sender/receiver or SVRCONN/CLNTCONN).
- **Listeners:** TCP endpoints that accept inbound channel connections (default port 1414).
- **Messages:** Persistent (survives QM restart, written to log) or non-persistent (faster, lost on restart). Maximum message size configurable up to 100 MB.
- **Transactions (XA):** MQ participates in two-phase commit with XA-compliant transaction managers (e.g., WebSphere, Tuxedo). Local units of work (syncpoint) also supported.

### Messaging Patterns

- **Point-to-point (put/get):** Producer puts to a queue, consumer gets from it. Decoupled by time and location.
- **Request/reply:** Requester puts a message with ReplyToQ and CorrelId, responder reads and replies to the designated queue.
- **Publish/subscribe:** Publishers send to topics, subscribers receive based on topic string matching and wildcards.
- **Clusters:** Multiple QMs form a cluster for workload distribution and simplified administration — no need to define remote queues and channels for every QM pair.

---

## 2. Installation on RHEL 9

### Prerequisites

```bash
# Required packages
sudo dnf install -y bc tar gzip

# Create mqm group and user (installer does this, but pre-create if needed)
sudo groupadd -g 1001 mqm
sudo useradd -u 1001 -g mqm -d /home/mqm -m mqm

# Kernel tuning — /etc/sysctl.d/99-mq.conf
cat <<'EOF' | sudo tee /etc/sysctl.d/99-mq.conf
kernel.shmmni = 4096
kernel.shmall = 2097152
kernel.shmmax = 268435456
kernel.sem = 500 256000 250 1024
fs.file-max = 524288
EOF
sudo sysctl --system

# User limits — /etc/security/limits.d/99-mqm.conf
cat <<'EOF' | sudo tee /etc/security/limits.d/99-mqm.conf
mqm  hard  nofile  10240
mqm  soft  nofile  10240
mqm  hard  nproc   4096
mqm  soft  nproc   4096
EOF
```

### IBM MQ 9.3/9.4 RPM Installation

```bash
# Download MQ Advanced from IBM Passport Advantage or Fix Central
# Extract the tar.gz to a staging directory
mkdir -p /tmp/mq-install && cd /tmp/mq-install
tar xzf IBM_MQ_9.4.0_LINUX_X86-64.tar.gz

# Accept license
cd MQServer
sudo ./mqlicense.sh -accept

# Install core components
sudo rpm -ivh MQSeriesRuntime-*.rpm
sudo rpm -ivh MQSeriesServer-*.rpm
sudo rpm -ivh MQSeriesClient-*.rpm
sudo rpm -ivh MQSeriesSDK-*.rpm
sudo rpm -ivh MQSeriesJava-*.rpm
sudo rpm -ivh MQSeriesJRE-*.rpm
sudo rpm -ivh MQSeriesSamples-*.rpm
sudo rpm -ivh MQSeriesMan-*.rpm

# Set as primary installation
sudo /opt/mqm/bin/setmqinst -i -p /opt/mqm

# Verify installation
/opt/mqm/bin/dspmqver
```

### Fix Packs

```bash
# Stop all queue managers first
su - mqm -c "dspmq | grep Running | awk '{print \$1}' | sed 's/QMNAME(//;s/)//' | while read QM; do endmqm -i \$QM; done"

# Apply fix pack RPMs (downloaded from IBM Fix Central)
sudo rpm -Uvh MQSeriesRuntime-U*.rpm MQSeriesServer-U*.rpm MQSeriesClient-U*.rpm \
  MQSeriesSDK-U*.rpm MQSeriesJava-U*.rpm MQSeriesJRE-U*.rpm

# Verify
/opt/mqm/bin/dspmqver
```

### Environment Setup

```bash
# Add to mqm user profile (~mqm/.bash_profile)
export PATH=/opt/mqm/bin:/opt/mqm/samp/bin:$PATH
export LD_LIBRARY_PATH=/opt/mqm/lib64:$LD_LIBRARY_PATH
export MQ_INSTALLATION_PATH=/opt/mqm

# For application users, source the setmqenv script
. /opt/mqm/bin/setmqenv -s
```

---

## 3. Queue Manager Administration

### Create, Start, Stop, Delete

```bash
# Create a queue manager (as mqm user)
su - mqm

# Create QM with specified log type and dead-letter queue name
crtmqm -lc -ld /var/mqm/log -md /var/mqm/qmgrs -u SYSTEM.DEAD.LETTER.QUEUE QM1

# Start queue manager
strmqm QM1

# Display all queue managers and their status
dspmq

# Stop queue manager (controlled — waits for connections to end)
endmqm QM1

# Stop queue manager (immediate — disconnects clients)
endmqm -i QM1

# Stop queue manager (preemptive — last resort)
endmqm -p QM1

# Delete queue manager (must be stopped)
dltmqm QM1
```

### runmqsc — Interactive Administration

```bash
# Interactive mode
runmqsc QM1

# Non-interactive (scripted) mode
echo "DISPLAY QMGR ALL" | runmqsc QM1

# Run commands from a file
runmqsc QM1 < /path/to/commands.mqsc
```

### ALTER QMGR — Key Settings

```
runmqsc QM1

* Set dead-letter queue
ALTER QMGR DEADQ('DLQ.QM1')

* Set maximum message length (default 4 MB, max 100 MB)
ALTER QMGR MAXMSGL(104857600)

* Set trigger interval (milliseconds)
ALTER QMGR TRIGINT(999999999)

* Channel authentication
ALTER QMGR CHLAUTH(ENABLED)

* Connection authentication (require user/password)
ALTER QMGR CONNAUTH('SYSTEM.DEFAULT.AUTHINFO.IDPWOS')
ALTER AUTHINFO('SYSTEM.DEFAULT.AUTHINFO.IDPWOS') AUTHTYPE(IDPWOS) ADOPTCTX(YES) CHCKCLNT(REQUIRED) CHCKLOCL(OPTIONAL)
REFRESH SECURITY TYPE(CONNAUTH)

* Display current QM settings
DISPLAY QMGR DEADQ MAXMSGL CHLAUTH CONNAUTH TRIGINT

END
```

### Define the Dead-Letter Queue

```
runmqsc QM1

DEFINE QLOCAL('DLQ.QM1') +
  DEFPSIST(YES) +
  MAXDEPTH(100000) +
  MAXMSGL(104857600) +
  DESCR('Dead-letter queue for QM1')

ALTER QMGR DEADQ('DLQ.QM1')

END
```

---

## 4. Queue Types

### Local Queues

```
runmqsc QM1

* Application queue — persistent, triggered
DEFINE QLOCAL('APP.REQUEST.Q') +
  DEFPSIST(YES) +
  MAXDEPTH(50000) +
  MAXMSGL(4194304) +
  TRIGTYPE(FIRST) +
  TRIGGER +
  INITQ('SYSTEM.DEFAULT.INITIATION.QUEUE') +
  PROCESS('APP.PROCESS') +
  DESCR('Inbound application request queue')

* High-throughput queue — non-persistent, no trigger
DEFINE QLOCAL('APP.EVENT.Q') +
  DEFPSIST(NO) +
  MAXDEPTH(500000) +
  MAXMSGL(1048576) +
  DESCR('High-throughput event queue')

* Display queue and current depth
DISPLAY QLOCAL('APP.REQUEST.Q') CURDEPTH MAXDEPTH MAXMSGL DEFPSIST TRIGTYPE

END
```

### Remote Queues

Remote queue definitions point to a queue on another queue manager via a transmission queue.

```
runmqsc QM1

* Transmission queue for QM2
DEFINE QLOCAL('QM2.XMITQ') +
  USAGE(XMITQ) +
  DEFPSIST(YES) +
  MAXDEPTH(100000) +
  DESCR('Transmission queue to QM2')

* Remote queue definition — messages put here flow to QM2
DEFINE QREMOTE('REMOTE.TO.QM2.APPQ') +
  RNAME('APP.REQUEST.Q') +
  RQMNAME('QM2') +
  XMITQ('QM2.XMITQ') +
  DESCR('Remote definition pointing to APP.REQUEST.Q on QM2')

END
```

### Alias Queues

```
runmqsc QM1

* Alias to abstract the real queue name
DEFINE QALIAS('APP.INPUT') +
  TARGET('APP.REQUEST.Q') +
  TARGTYPE(QUEUE) +
  DESCR('Alias for application input — can retarget without client changes')

END
```

### Model Queues (Dynamic Queue Templates)

```
runmqsc QM1

* Permanent dynamic queue template (survives QM restart)
DEFINE QMODEL('APP.REPLY.MODEL') +
  DEFTYPE(PERMDYN) +
  DEFPSIST(NO) +
  MAXDEPTH(5000) +
  DESCR('Template for reply queues — permanent dynamic')

* Temporary dynamic queue template (deleted on disconnect)
DEFINE QMODEL('APP.TEMP.MODEL') +
  DEFTYPE(TEMPDYN) +
  DEFPSIST(NO) +
  MAXDEPTH(5000) +
  DESCR('Template for temporary reply queues')

END
```

### Backout Requeue Queue

```
runmqsc QM1

* Backout requeue queue for poison messages
DEFINE QLOCAL('APP.REQUEST.Q.BACKOUT') +
  DEFPSIST(YES) +
  MAXDEPTH(10000) +
  DESCR('Backout queue for APP.REQUEST.Q')

* Set backout threshold and requeue queue on the main queue
ALTER QLOCAL('APP.REQUEST.Q') +
  BOTHRESH(3) +
  BOQNAME('APP.REQUEST.Q.BACKOUT')

END
```

---

## 5. Channels

### Sender / Receiver Pair (QM1 -> QM2)

```
* --- On QM1 (sender side) ---
runmqsc QM1

DEFINE CHANNEL('QM1.TO.QM2') +
  CHLTYPE(SDR) +
  CONNAME('qm2-host.example.com(1414)') +
  XMITQ('QM2.XMITQ') +
  TRPTYPE(TCP) +
  BATCHSZ(50) +
  DISCINT(0) +
  DESCR('Sender channel to QM2')

END

* --- On QM2 (receiver side) ---
runmqsc QM2

DEFINE CHANNEL('QM1.TO.QM2') +
  CHLTYPE(RCVR) +
  TRPTYPE(TCP) +
  DESCR('Receiver channel from QM1')

END
```

### Server-Connection / Client-Connection (Application Access)

```
runmqsc QM1

* SVRCONN — server side for client applications
DEFINE CHANNEL('APP.SVRCONN') +
  CHLTYPE(SVRCONN) +
  TRPTYPE(TCP) +
  MCAUSER('app_svc_acct') +
  MAXMSGL(4194304) +
  SHARECNV(10) +
  DESCR('Application server-connection channel')

* CLNTCONN — optional client-side definition (stored in CCDT)
DEFINE CHANNEL('APP.SVRCONN') +
  CHLTYPE(CLNTCONN) +
  CONNAME('qm1-host.example.com(1414)') +
  QMNAME('QM1') +
  TRPTYPE(TCP) +
  DESCR('Client-connection for APP.SVRCONN')

END
```

### Channel Status and Management

```
runmqsc QM1

* Display channel status (running channels)
DISPLAY CHSTATUS('QM1.TO.QM2') ALL
DISPLAY CHSTATUS('APP.SVRCONN') ALL

* Start/stop a channel
START CHANNEL('QM1.TO.QM2')
STOP CHANNEL('QM1.TO.QM2')

* Reset a channel (resolve sequence number issues)
RESET CHANNEL('QM1.TO.QM2')

* Resolve an in-doubt channel (after communication failure)
RESOLVE CHANNEL('QM1.TO.QM2') ACTION(COMMIT)

END
```

### Channel Exits

Channel exits are custom programs that intercept channel I/O for security, compression, or transformation:
- **Security exit:** authentication/authorization at channel startup.
- **Message exit:** transform message data in transit.
- **Send/receive exit:** encrypt or compress data on the wire.

```
DEFINE CHANNEL('SECURE.SDR') +
  CHLTYPE(SDR) +
  CONNAME('remote-host(1414)') +
  XMITQ('REMOTE.XMITQ') +
  SCYEXIT('/opt/mqm/exits64/mysecexit(SecEntryPoint)') +
  MSGEXIT('/opt/mqm/exits64/mymsgexit(MsgEntryPoint)') +
  TRPTYPE(TCP)
```

---

