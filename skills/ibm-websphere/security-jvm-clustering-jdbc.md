# Security, JVM Tuning, Clustering, and Data Sources

Reference file for the `ibm-websphere` skill. Covers security configuration, JVM tuning, clustering/HA, JDBC data sources, and JMS/MQ integration.

## 5. Security

### Global Security (Admin Console / wsadmin)

```python
# Enable administrative security
securityId = AdminConfig.getid('/Security:/')
AdminConfig.modify(securityId, [
    ['enabled', 'true'],
    ['appEnabled', 'true'],
    ['enforceJava2Security', 'false'],  # enable only if app is Java 2 security-compliant
    ['cacheTimeout', '600']
])
AdminConfig.save()
```

### LTPA Token Management

```python
# Export LTPA keys (for SSO across cells)
AdminTask.exportLTPAKeys([
    '-ltpaKeyFile', '/tmp/ltpa.keys',
    '-password', 'LTPAKeyP@ss!'
])

# Import LTPA keys (on another cell)
AdminTask.importLTPAKeys([
    '-ltpaKeyFile', '/tmp/ltpa.keys',
    '-password', 'LTPAKeyP@ss!'
])

# Set LTPA timeout (seconds)
ltpa = AdminConfig.getid('/LTPAMechanism:/')
AdminConfig.modify(ltpa, [['timeout', '7200']])
AdminConfig.save()
```

### LDAP / Active Directory Federated Repositories

```python
# Configure LDAP repository
AdminTask.createIdMgrLDAPRepository([
    '-id', 'CORP_AD',
    '-ldapServerType', 'AD',
    '-primaryHostName', 'dc01.corp.example.com',
    '-ldapServerPort', '636',
    '-sslEnabled', 'true',
    '-bindDN', 'CN=wasldap,OU=ServiceAccounts,DC=corp,DC=example,DC=com',
    '-bindPassword', 'LdapBind@Pass!',
    '-searchTimeout', '120',
    '-baseDN', 'DC=corp,DC=example,DC=com'
])

# Add repository to federated repositories realm
AdminTask.addIdMgrRepositoryBaseEntry([
    '-id', 'CORP_AD',
    '-name', 'DC=corp,DC=example,DC=com',
    '-nameInRepository', 'DC=corp,DC=example,DC=com'
])

AdminConfig.save()
```

### SSL/TLS Certificate Management

```bash
# List keystores
WAS_HOME=/opt/IBM/WebSphere/AppServer
$WAS_HOME/profiles/Dmgr01/bin/wsadmin.sh -lang jython -c \
  "print AdminTask.listKeyStores()"

# Extract certificate from remote host (wsadmin)
# AdminTask.retrieveSignerFromPort(['-keyStoreName', 'NodeDefaultTrustStore',
#   '-keyStoreScope', '(cell):MyCell:(node):AppNode01',
#   '-host', 'ldap.example.com', '-port', '636',
#   '-certificateAlias', 'ldap_cert'])
```

```python
# wsadmin Jython — add signer certificate
AdminTask.retrieveSignerFromPort([
    '-keyStoreName', 'NodeDefaultTrustStore',
    '-keyStoreScope', '(cell):MyCell:(node):AppNode01',
    '-host', 'db2server.example.com',
    '-port', '50001',
    '-certificateAlias', 'db2_ssl_cert'
])

# Create self-signed certificate
AdminTask.createSelfSignedCertificate([
    '-keyStoreName', 'NodeDefaultKeyStore',
    '-keyStoreScope', '(cell):MyCell:(node):AppNode01',
    '-certificateAlias', 'myapp_cert',
    '-cn', 'appnode01.example.com',
    '-keySize', '2048',
    '-validity', '365'
])

AdminConfig.save()
```

### iKeyman (CLI for certificate management)

```bash
# Create a new key database
$WAS_HOME/java/bin/ikeycmd -keydb -create \
  -db /opt/IBM/WebSphere/AppServer/profiles/AppSrv01/config/cells/MyCell/nodes/AppNode01/key.p12 \
  -pw changeit -type pkcs12

# Import a CA certificate
$WAS_HOME/java/bin/ikeycmd -cert -add \
  -db /opt/IBM/WebSphere/AppServer/profiles/AppSrv01/config/cells/MyCell/nodes/AppNode01/trust.p12 \
  -pw changeit -label "CorpCA" -file /tmp/corp-ca.crt -format ascii

# List certificates
$WAS_HOME/java/bin/ikeycmd -cert -list \
  -db /opt/IBM/WebSphere/AppServer/profiles/AppSrv01/config/cells/MyCell/nodes/AppNode01/key.p12 \
  -pw changeit -type pkcs12
```

### SAML / OIDC for Liberty

```xml
<!-- server.xml — SAML 2.0 Web SSO -->
<featureManager>
    <feature>samlWeb-2.0</feature>
</featureManager>

<samlWebSso20 id="defaultSP"
    idpMetadata="/opt/IBM/wlp/usr/servers/myServer/resources/security/idp-metadata.xml"
    keyStoreRef="samlKeyStore"
    keyAlias="samlsp"
    signatureMethodAlgorithm="SHA256"
    wantAssertionsSigned="true"
    authnRequestsSigned="true" />

<keyStore id="samlKeyStore"
    location="${server.config.dir}/resources/security/saml-keystore.p12"
    password="keystorePass" type="PKCS12" />
```

```xml
<!-- server.xml — OpenID Connect Client (OIDC) -->
<featureManager>
    <feature>openidConnectClient-1.0</feature>
    <feature>ssl-1.0</feature>
</featureManager>

<openidConnectClient id="oidcClient"
    clientId="was-liberty-client"
    clientSecret="${oidc.client.secret}"
    discoveryEndpointUrl="https://idp.example.com/.well-known/openid-configuration"
    signatureAlgorithm="RS256"
    scope="openid profile email"
    mapIdentityToRegistryUser="true"
    httpsRequired="true" />
```

### Application Security Role Mapping

```python
# Map security roles to groups
AdminApp.edit(appName, [
    '-MapRolesToUsers', [
        ['AdminRole', 'No', 'No', '', 'cn=WASAdmins,ou=Groups,dc=corp,dc=example,dc=com'],
        ['UserRole', 'No', 'No', '', 'cn=AppUsers,ou=Groups,dc=corp,dc=example,dc=com'],
        ['ManagerRole', 'No', 'No', '', 'cn=Managers,ou=Groups,dc=corp,dc=example,dc=com']
    ]
])
AdminConfig.save()
```

---

## 6. JVM Tuning

### Heap Sizing

```python
# wsadmin Jython — set JVM heap
serverName = 'server1'
nodeName = 'AppNode01'

jvm = AdminConfig.getid('/Node:%s/Server:%s/JavaProcessDef:/JavaVirtualMachine:/' % (nodeName, serverName))
AdminConfig.modify(jvm, [
    ['initialHeapSize', '2048'],     # -Xms in MB
    ['maximumHeapSize', '4096'],     # -Xmx in MB
    ['genericJvmArguments', '-Xmn1024m -XX:+UseCompressedOops']
])
AdminConfig.save()
```

### GC Policies (IBM J9 JVM)

| Policy | Use case | JVM argument |
|---|---|---|
| **gencon** (default) | General workloads, low pause times | `-Xgcpolicy:gencon` |
| **balanced** | Large heaps (>4 GB), consistent pause times | `-Xgcpolicy:balanced` |
| **metronome** | Real-time, predictable pause times | `-Xgcpolicy:metronome` |
| **optthruput** | Batch processing, max throughput | `-Xgcpolicy:optthruput` |
| **optavgpause** | Minimize average pause time | `-Xgcpolicy:optavgpause` |

```python
# Set GC policy via genericJvmArguments
jvm = AdminConfig.getid('/Node:AppNode01/Server:server1/JavaProcessDef:/JavaVirtualMachine:/')
currentArgs = AdminConfig.showAttribute(jvm, 'genericJvmArguments')
newArgs = currentArgs + ' -Xgcpolicy:gencon -Xmn1024m -verbose:gc -Xverbosegclog:/opt/IBM/WebSphere/AppServer/profiles/AppSrv01/logs/server1/verbosegc.log,20,50000'
AdminConfig.modify(jvm, [['genericJvmArguments', newArgs]])
AdminConfig.save()
```

### Verbose GC Analysis

```bash
# Enable verbose GC (if not set via genericJvmArguments above)
# Analyze GC logs with IBM Garbage Collection and Memory Visualizer (GCMV)
# Download from: https://www.ibm.com/support/pages/garbage-collection-and-memory-visualizer

# Quick analysis — check GC frequency and pause times
grep '<gc-end' /opt/IBM/WebSphere/AppServer/profiles/AppSrv01/logs/server1/verbosegc.log | tail -20

# Monitor heap usage in real time (wsadmin)
# AdminControl.getAttribute(AdminControl.queryNames('type=JVM,process=server1,*'), 'heapSize')
```

### Thread Pool Tuning

```python
# WebContainer thread pool (handles HTTP requests)
server = AdminConfig.getid('/Node:AppNode01/Server:server1/')
tpList = AdminConfig.list('ThreadPool', server).split('\n')
for tp in tpList:
    tpName = AdminConfig.showAttribute(tp, 'name')
    if tpName == 'WebContainer':
        AdminConfig.modify(tp, [
            ['minimumSize', '50'],
            ['maximumSize', '200'],
            ['inactivityTimeout', '5000'],
            ['isGrowable', 'true']
        ])
    elif tpName == 'Default':
        AdminConfig.modify(tp, [
            ['minimumSize', '20'],
            ['maximumSize', '50']
        ])
    elif tpName == 'ORB.thread.pool':
        AdminConfig.modify(tp, [
            ['minimumSize', '10'],
            ['maximumSize', '50']
        ])

AdminConfig.save()
```

---

## 7. Clustering & HA

### WAS ND Cluster Creation

```python
# wsadmin Jython — create cluster
clusterName = 'AppCluster'

# Create cluster
AdminTask.createCluster([
    '-clusterConfig', '[-clusterName %s]' % clusterName
])

# Create first cluster member on node AppNode01
AdminTask.createClusterMember([
    '-clusterName', clusterName,
    '-memberConfig', '[-memberNode AppNode01 -memberName AppSrv01 -memberWeight 2]'
])

# Create second cluster member on node AppNode02
AdminTask.createClusterMember([
    '-clusterName', clusterName,
    '-memberConfig', '[-memberNode AppNode02 -memberName AppSrv02 -memberWeight 2]'
])

AdminConfig.save()

# Sync nodes
dmgr = AdminControl.queryNames('type=DeploymentManager,*')
AdminControl.invoke(dmgr, 'multiSync', '[nodes=* rolloutUpdate=false]')
```

### Session Replication (Memory-to-Memory)

```python
# Configure DRS (Data Replication Service) for session persistence
server = AdminConfig.getid('/Server:AppSrv01/')
smList = AdminConfig.list('SessionManager', server)
tuningParams = AdminConfig.showAttribute(smList, 'tuningParams')

# Enable memory-to-memory replication
AdminConfig.modify(smList, [
    ['sessionPersistenceMode', 'DATA_REPLICATION'],
    ['enable', 'true']
])

# Configure DRS settings
drs = AdminConfig.showAttribute(smList, 'sessionDatabasePersistence')
if drs:
    AdminConfig.remove(drs)
drs = AdminConfig.create('DRSSettings', smList, [
    ['dataReplicationMode', 'BOTH'],
    ['messageBrokerDomainName', clusterName]
])

AdminConfig.save()
```

### Session Replication (Database)

```python
# Configure database session persistence
smList = AdminConfig.list('SessionManager', server)
AdminConfig.modify(smList, [['sessionPersistenceMode', 'DATABASE']])

dbPersistence = AdminConfig.create('SessionDatabasePersistence', smList, [
    ['datasourceJNDIName', 'jdbc/SessionDS'],
    ['db2RowSize', 'ROW_SIZE_32KB'],
    ['tableSpaceName', 'SESSIONS'],
    ['userId', 'sessuser'],
    ['password', '{xor}encoded_password']
])

AdminConfig.save()
```

### HTTP Plugin Generation & Propagation

```python
# Generate plugin-cfg.xml
AdminControl.invoke(
    AdminControl.queryNames('type=PluginCfgGenerator,*'),
    'generate',
    '[/opt/IBM/WebSphere/Plugins /opt/IBM/WebSphere/Plugins/config/webserver1 webserver1 MyCell AppNode01]'
)

# Propagate plugin to web server
AdminControl.invoke(
    AdminControl.queryNames('type=PluginCfgGenerator,*'),
    'propagate',
    '[/opt/IBM/WebSphere/Plugins/config/webserver1 MyCell AppNode01 webserver1]'
)
```

### IHS / Nginx Frontend Config

```apache
# IBM HTTP Server (IHS) — httpd.conf plugin stanza
LoadModule was_ap24_module /opt/IBM/WebSphere/Plugins/bin/64bits/mod_was_ap24_http.so
WebSpherePluginConfig /opt/IBM/WebSphere/Plugins/config/webserver1/plugin-cfg.xml
```

```nginx
# Nginx reverse proxy to WAS cluster
upstream was_cluster {
    server appnode01.example.com:9080 weight=2;
    server appnode02.example.com:9080 weight=2;
    keepalive 32;
}

server {
    listen 443 ssl;
    server_name app.example.com;

    ssl_certificate     /etc/pki/tls/certs/app.example.com.crt;
    ssl_certificate_key /etc/pki/tls/private/app.example.com.key;

    location / {
        proxy_pass http://was_cluster;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_connect_timeout 30s;
        proxy_read_timeout 300s;
    }
}
```

---

## 8. JDBC & Data Sources

### JDBC Provider Creation

```python
# wsadmin Jython — create DB2 JDBC provider
nodeName = 'AppNode01'
serverName = 'server1'
scopeId = AdminConfig.getid('/Node:%s/Server:%s/' % (nodeName, serverName))

# DB2 Universal JDBC Driver
AdminTask.createJDBCProvider([
    '-scope', scopeId,
    '-databaseType', 'DB2',
    '-providerType', 'DB2 Universal JDBC Driver Provider',
    '-implementationType', 'Connection pool data source',
    '-name', 'DB2 Universal JDBC Driver',
    '-classpath', '/opt/IBM/db2/java/db2jcc4.jar;/opt/IBM/db2/java/db2jcc_license_cisuz.jar',
    '-nativePath', ''
])

# Oracle JDBC Provider
AdminTask.createJDBCProvider([
    '-scope', scopeId,
    '-databaseType', 'Oracle',
    '-providerType', 'Oracle JDBC Driver',
    '-implementationType', 'Connection pool data source',
    '-name', 'Oracle JDBC Driver',
    '-classpath', '/opt/oracle/ojdbc11.jar',
    '-nativePath', ''
])

# PostgreSQL JDBC Provider
AdminTask.createJDBCProvider([
    '-scope', scopeId,
    '-databaseType', 'User-defined',
    '-providerType', 'User-defined JDBC Provider',
    '-implementationType', 'Connection pool data source',
    '-name', 'PostgreSQL JDBC Driver',
    '-classpath', '/opt/jdbc/postgresql-42.7.1.jar',
    '-implementationClassName', 'org.postgresql.ds.PGConnectionPoolDataSource',
    '-nativePath', ''
])

AdminConfig.save()
```

### J2C Authentication Alias

```python
# Create J2C authentication alias (encrypted credential store)
security = AdminConfig.getid('/Security:/')
AdminConfig.create('JAASAuthData', security, [
    ['alias', 'DB2AppAuth'],
    ['userId', 'db2app'],
    ['password', 'Db2@ppP@ss!'],
    ['description', 'DB2 application database credentials']
])

AdminConfig.create('JAASAuthData', security, [
    ['alias', 'OracleAppAuth'],
    ['userId', 'oraapp'],
    ['password', 'Or@cleP@ss!'],
    ['description', 'Oracle application database credentials']
])

AdminConfig.save()
```

### Data Source Configuration

```python
# Create DB2 data source
providerId = AdminConfig.getid('/Node:%s/Server:%s/JDBCProvider:DB2 Universal JDBC Driver/' % (nodeName, serverName))

AdminTask.createDatasource(providerId, [
    '-name', 'AppDB',
    '-jndiName', 'jdbc/AppDB',
    '-dataStoreHelperClassName', 'com.ibm.websphere.rsadapter.DB2UniversalDataStoreHelper',
    '-componentManagedAuthenticationAlias', 'DB2AppAuth',
    '-containerManagedPersistence', 'true',
    '-configureResourceProperties', '[[databaseName java.lang.String APPDB] [driverType java.lang.Integer 4] [serverName java.lang.String db2server.example.com] [portNumber java.lang.Integer 50000]]'
])

AdminConfig.save()
```

### Connection Pool Tuning

```python
# Get data source and configure connection pool
dsId = AdminConfig.getid('/Node:%s/Server:%s/JDBCProvider:DB2 Universal JDBC Driver/DataSource:AppDB/' % (nodeName, serverName))
poolId = AdminConfig.showAttribute(dsId, 'connectionPool')

AdminConfig.modify(poolId, [
    ['minConnections', '10'],
    ['maxConnections', '50'],
    ['connectionTimeout', '30'],          # seconds to wait for connection
    ['reapTime', '180'],                  # seconds between pool maintenance runs
    ['unusedTimeout', '1800'],            # seconds before idle connection is removed
    ['agedTimeout', '3600'],              # seconds before ANY connection is removed (stale protection)
    ['purgePolicy', 'EntirePool'],        # FailingConnectionOnly or EntirePool
    ['stuckTimerTime', '30'],             # seconds before detecting stuck connection
    ['stuckTime', '300'],                 # seconds before marking connection as stuck
    ['stuckThreshold', '5'],              # stuck connections before pool purge
    ['surgeCreationInterval', '0'],
    ['surgeThreshold', '-1'],
    ['testConnection', 'true'],
    ['testConnectionInterval', '180']     # seconds between test connections
])

# Statement cache
AdminConfig.modify(dsId, [['statementCacheSize', '60']])

AdminConfig.save()
```

### Test Connection

```python
# Test data source connection
dsId = AdminConfig.getid('/Node:%s/Server:%s/JDBCProvider:DB2 Universal JDBC Driver/DataSource:AppDB/' % (nodeName, serverName))
result = AdminControl.testConnection(dsId)
print('Connection test result: %s' % result)
```

---

## 9. JMS & MQ Integration

### JMS Provider Setup (Built-in SIBus)

```python
# Create SIBus
AdminTask.createSIBus(['-bus', 'AppBus', '-description', 'Application messaging bus'])

# Add cluster as bus member
AdminTask.addSIBusMember([
    '-bus', 'AppBus',
    '-cluster', 'AppCluster',
    '-fileStore', '',
    '-logSize', '100',
    '-minPermanentStoreSize', '200',
    '-maxPermanentStoreSize', '500'
])

# Create SIBus queue destination
AdminTask.createSIBDestination([
    '-bus', 'AppBus',
    '-name', 'RequestQueue',
    '-type', 'Queue',
    '-cluster', 'AppCluster',
    '-description', 'Inbound request queue'
])

# Create JMS connection factory
AdminTask.createSIBJMSConnectionFactory([
    '-name', 'AppCF',
    '-jndiName', 'jms/AppCF',
    '-busName', 'AppBus',
    '-type', 'QueueConnectionFactory',
    '-scope', 'Node=%s' % nodeName
])

# Create JMS queue
AdminTask.createSIBJMSQueue([
    '-name', 'RequestJMSQueue',
    '-jndiName', 'jms/RequestQueue',
    '-busName', 'AppBus',
    '-queueName', 'RequestQueue'
])

AdminConfig.save()
```

### MQ Resource Adapter (WebSphere MQ / IBM MQ)

```python
# Install MQ resource adapter
AdminTask.installResourceAdapter([
    '-rarPath', '/opt/mqm/java/lib/jca/wmq.jmsra.rar',
    '-rar.name', 'IBM MQ Resource Adapter',
    '-scope', 'Node=%s' % nodeName
])

# Create MQ connection factory
AdminTask.createWMQConnectionFactory([
    '-name', 'MQ_CF',
    '-jndiName', 'jms/MQCF',
    '-type', 'QCF',
    '-scope', 'Node=%s' % nodeName,
    '-host', 'mqserver.example.com',
    '-port', '1414',
    '-channel', 'APP.SVRCONN',
    '-queueManager', 'QM01',
    '-transportType', 'CLIENT',
    '-sslType', 'TLS_RSA_WITH_AES_256_CBC_SHA256'
])

# Create MQ queue
AdminTask.createWMQQueue([
    '-name', 'MQ_RequestQueue',
    '-jndiName', 'jms/MQRequestQueue',
    '-scope', 'Node=%s' % nodeName,
    '-queueName', 'APP.REQUEST.Q',
    '-queueManager', 'QM01'
])

# Create activation specification (for MDBs)
AdminTask.createWMQActivationSpec([
    '-name', 'MQ_ActivationSpec',
    '-jndiName', 'jms/MQActivationSpec',
    '-scope', 'Node=%s' % nodeName,
    '-destinationJndiName', 'jms/MQRequestQueue',
    '-destinationType', 'javax.jms.Queue',
    '-host', 'mqserver.example.com',
    '-port', '1414',
    '-channel', 'APP.SVRCONN',
    '-queueManager', 'QM01',
    '-transportType', 'CLIENT',
    '-maxPoolDepth', '10'
])

AdminConfig.save()
```

### Listener Ports (Legacy — for older MDB patterns)

```python
# Create listener port (traditional WAS, pre-activation spec)
server = AdminConfig.getid('/Node:%s/Server:%s/' % (nodeName, serverName))
msgListener = AdminConfig.getid('/Node:%s/Server:%s/MessageListenerService:/' % (nodeName, serverName))

AdminConfig.create('ListenerPort', msgListener, [
    ['name', 'RequestLP'],
    ['connectionFactoryJNDIName', 'jms/MQCF'],
    ['destinationJNDIName', 'jms/MQRequestQueue'],
    ['maxMessages', '10'],
    ['maxRetries', '3'],
    ['maxSessions', '5']
])

AdminConfig.save()
```

---

