# wsadmin, Liberty, and RHEL-Specific Configuration

Reference file for the `ibm-websphere` skill. Covers wsadmin scripting (Jython), WebSphere Liberty/Open Liberty configuration, and RHEL-specific setup.

## 10. wsadmin Scripting (Jython)

### Core Objects

| Object | Purpose | Common methods |
|---|---|---|
| **AdminApp** | Application lifecycle | `install()`, `uninstall()`, `update()`, `list()`, `export()` |
| **AdminConfig** | Configuration management | `getid()`, `create()`, `modify()`, `remove()`, `list()`, `save()`, `showAttribute()` |
| **AdminControl** | Runtime operations | `queryNames()`, `invoke()`, `getAttribute()`, `startServer()`, `stopServer()` |
| **AdminTask** | High-level admin tasks | `createCluster()`, `createDatasource()`, `createJDBCProvider()`, `help()` |

### Running wsadmin

```bash
WAS_HOME=/opt/IBM/WebSphere/AppServer

# Interactive mode (connected to dmgr)
$WAS_HOME/profiles/Dmgr01/bin/wsadmin.sh -lang jython \
  -username wasadmin -password 'Str0ngP@ss!'

# Script mode
$WAS_HOME/profiles/Dmgr01/bin/wsadmin.sh -lang jython \
  -username wasadmin -password 'Str0ngP@ss!' \
  -f /opt/scripts/deploy_app.py

# Conntype: default SOAP (8879), or use RMI
$WAS_HOME/profiles/Dmgr01/bin/wsadmin.sh -lang jython \
  -conntype SOAP -host dmgr01.example.com -port 8879 \
  -username wasadmin -password 'Str0ngP@ss!' \
  -f /opt/scripts/deploy_app.py

# Use encrypted credentials file (soap.client.props or sas.client.props)
# Edit $PROFILE_HOME/properties/soap.client.props:
#   com.ibm.SOAP.securityEnabled=true
#   com.ibm.SOAP.loginUserid=wasadmin
#   com.ibm.SOAP.loginPassword={xor}encoded_password
# Then run without inline credentials:
$WAS_HOME/profiles/Dmgr01/bin/wsadmin.sh -lang jython -f /opt/scripts/deploy_app.py
```

### Common Automation Patterns

```python
# --- List all servers in cell ---
servers = AdminConfig.list('Server').split('\n')
for s in servers:
    name = AdminConfig.showAttribute(s, 'name')
    sType = AdminConfig.showAttribute(s, 'serverType')
    print('%s [%s]' % (name, sType))

# --- Start / stop server ---
AdminControl.startServer('server1', 'AppNode01')
AdminControl.stopServer('server1', 'AppNode01', 'immediate')

# --- Start / stop cluster ---
cluster = AdminControl.queryNames('type=Cluster,name=AppCluster,*')
AdminControl.invoke(cluster, 'rippleStart')   # rolling restart
AdminControl.invoke(cluster, 'stop')

# --- Update application (full replace) ---
AdminApp.update('MyWebApp', 'app', [
    '-operation', 'update',
    '-contents', '/tmp/MyWebApp_v2.ear',
    '-usedefaultbindings'
])
AdminConfig.save()

# --- Uninstall application ---
AdminApp.uninstall('MyWebApp')
AdminConfig.save()

# --- Export application EAR ---
AdminApp.export('MyWebApp', '/tmp/MyWebApp_export.ear')

# --- List all data sources ---
dsList = AdminConfig.list('DataSource').split('\n')
for ds in dsList:
    dsName = AdminConfig.showAttribute(ds, 'name')
    jndi = AdminConfig.showAttribute(ds, 'jndiName')
    print('%s -> %s' % (dsName, jndi))

# --- Sync all nodes ---
dmgr = AdminControl.queryNames('type=DeploymentManager,*')
AdminControl.invoke(dmgr, 'multiSync', '[nodes=* rolloutUpdate=false]')

# --- Check server status ---
serverStatus = AdminControl.queryNames('type=Server,name=server1,node=AppNode01,*')
if serverStatus:
    state = AdminControl.getAttribute(serverStatus, 'state')
    print('server1 state: %s' % state)
else:
    print('server1 is not running')
```

---

## 11. Liberty / Open Liberty

### server.xml Configuration

```xml
<?xml version="1.0" encoding="UTF-8"?>
<server description="Liberty Application Server">

    <!-- Feature Manager -->
    <featureManager>
        <feature>javaee-8.0</feature>
        <!-- Or granular features: -->
        <!-- <feature>servlet-4.0</feature> -->
        <!-- <feature>jsp-2.3</feature> -->
        <!-- <feature>cdi-2.0</feature> -->
        <!-- <feature>jaxrs-2.1</feature> -->
        <feature>jdbc-4.3</feature>
        <feature>jms-2.0</feature>
        <feature>microProfile-6.0</feature>
        <feature>monitor-1.0</feature>
        <feature>transportSecurity-1.0</feature>
    </featureManager>

    <!-- HTTP Endpoints -->
    <httpEndpoint id="defaultHttpEndpoint"
        host="*" httpPort="9080" httpsPort="9443">
        <accessLogging filepath="${server.output.dir}/logs/access.log"
            logFormat='%h %u %t "%r" %s %b %D' />
    </httpEndpoint>

    <!-- SSL/TLS -->
    <keyStore id="defaultKeyStore"
        location="${server.config.dir}/resources/security/key.p12"
        password="keystorePass" type="PKCS12" />

    <!-- Data Source -->
    <library id="db2lib">
        <fileset dir="/opt/IBM/db2/java" includes="db2jcc4.jar db2jcc_license_cisuz.jar" />
    </library>

    <dataSource id="AppDB" jndiName="jdbc/AppDB" type="javax.sql.ConnectionPoolDataSource">
        <jdbcDriver libraryRef="db2lib" />
        <properties.db2.jcc databaseName="APPDB" serverName="db2server.example.com"
            portNumber="50000" user="db2app" password="Db2@ppP@ss!" />
        <connectionManager minPoolSize="5" maxPoolSize="30"
            connectionTimeout="30s" reapTime="3m" agedTimeout="30m" />
    </dataSource>

    <!-- JMS (embedded messaging or MQ) -->
    <jmsConnectionFactory id="mqCF" jndiName="jms/MQCF">
        <properties.wmqJms transportType="CLIENT"
            hostName="mqserver.example.com" port="1414"
            channel="APP.SVRCONN" queueManager="QM01" />
    </jmsConnectionFactory>

    <!-- Application -->
    <application id="myapp" location="MyWebApp.war"
        name="MyWebApp" context-root="/myapp" type="war" />

    <!-- Logging -->
    <logging traceSpecification="*=info:com.mycompany.*=debug"
        maxFileSize="50" maxFiles="10"
        consoleLogLevel="INFO" />

</server>
```

### Config Dropins

```bash
# Drop-in configuration fragments (merged automatically)
/opt/IBM/wlp/usr/servers/myServer/configDropins/
  defaults/    # lowest priority — overridden by server.xml
  overrides/   # highest priority — overrides server.xml

# Example: overrides/datasource.xml
cat > /opt/IBM/wlp/usr/servers/myServer/configDropins/overrides/datasource.xml << 'EOF'
<server>
    <dataSource id="AppDB">
        <properties.db2.jcc serverName="db2-prod.example.com" />
    </dataSource>
</server>
EOF
```

### Dev Mode

```bash
# Start Liberty in dev mode (hot reload, test runner)
/opt/IBM/wlp/bin/server run myServer

# With Maven Liberty plugin
mvn liberty:dev

# With Gradle Liberty plugin
gradle libertyDev
```

### Docker Packaging

```dockerfile
FROM icr.io/appcafe/open-liberty:full-java17-openj9-ubi

COPY --chown=1001:0 server.xml /config/server.xml
COPY --chown=1001:0 target/MyWebApp.war /config/apps/

# Optimize startup with InstantOn (Open Liberty 23.0.0.3+)
RUN configure.sh
```

```bash
# Build and run
docker build -t myapp-liberty .
docker run -d -p 9080:9080 -p 9443:9443 --name myapp myapp-liberty
```

### Liberty Operator on OpenShift

```yaml
# OpenLibertyApplication CR
apiVersion: apps.openliberty.io/v1
kind: OpenLibertyApplication
metadata:
  name: myapp
  namespace: myproject
spec:
  replicas: 3
  applicationImage: registry.example.com/myapp-liberty:latest
  service:
    port: 9080
  expose: true
  route:
    termination: edge
  resources:
    requests:
      cpu: 500m
      memory: 512Mi
    limits:
      cpu: 2000m
      memory: 1Gi
  probes:
    liveness:
      httpGet:
        path: /health/live
        port: 9080
    readiness:
      httpGet:
        path: /health/ready
        port: 9080
```

---

## 12. RHEL-Specific

### SELinux Contexts for WAS Directories

```bash
# Label WAS install directory
sudo semanage fcontext -a -t usr_t "/opt/IBM/WebSphere(/.*)?"
sudo restorecon -Rv /opt/IBM/WebSphere

# Label Liberty install directory
sudo semanage fcontext -a -t usr_t "/opt/IBM/wlp(/.*)?"
sudo restorecon -Rv /opt/IBM/wlp

# Label WAS log directories (allow write)
sudo semanage fcontext -a -t var_log_t "/opt/IBM/WebSphere/AppServer/profiles/.*/logs(/.*)?"
sudo restorecon -Rv /opt/IBM/WebSphere/AppServer/profiles/

# If WAS needs to bind to non-standard ports
sudo semanage port -a -t http_port_t -p tcp 9080
sudo semanage port -a -t http_port_t -p tcp 9443
sudo semanage port -a -t http_port_t -p tcp 9060
sudo semanage port -a -t http_port_t -p tcp 9043

# Troubleshoot SELinux denials
sudo ausearch -m AVC --start recent | grep -i websphere
sudo sealert -a /var/log/audit/audit.log
```

### Firewalld Rules

```bash
# Deployment Manager ports
sudo firewall-cmd --permanent --add-rich-rule='rule family="ipv4" source address="10.0.1.0/24" port port="9060" protocol="tcp" accept'
sudo firewall-cmd --permanent --add-rich-rule='rule family="ipv4" source address="10.0.1.0/24" port port="9043" protocol="tcp" accept'
sudo firewall-cmd --permanent --add-rich-rule='rule family="ipv4" source address="10.0.1.0/24" port port="8879" protocol="tcp" accept'
sudo firewall-cmd --permanent --add-rich-rule='rule family="ipv4" source address="10.0.1.0/24" port port="8880" protocol="tcp" accept'

# Application server ports
sudo firewall-cmd --permanent --add-rich-rule='rule family="ipv4" source address="10.0.1.0/24" port port="9080" protocol="tcp" accept'
sudo firewall-cmd --permanent --add-rich-rule='rule family="ipv4" source address="10.0.1.0/24" port port="9443" protocol="tcp" accept'

# Node agent ports
sudo firewall-cmd --permanent --add-rich-rule='rule family="ipv4" source address="10.0.1.0/24" port port="2809" protocol="tcp" accept'
sudo firewall-cmd --permanent --add-rich-rule='rule family="ipv4" source address="10.0.1.0/24" port port="9809" protocol="tcp" accept'

# SIBus messaging
sudo firewall-cmd --permanent --add-rich-rule='rule family="ipv4" source address="10.0.1.0/24" port port="7276" protocol="tcp" accept'
sudo firewall-cmd --permanent --add-rich-rule='rule family="ipv4" source address="10.0.1.0/24" port port="7286" protocol="tcp" accept'

# Apply and verify
sudo firewall-cmd --reload
sudo firewall-cmd --list-rich-rules
```

### Systemd Services for WAS Traditional

`/etc/systemd/system/was-dmgr.service`:

```ini
[Unit]
Description=IBM WebSphere Deployment Manager
After=network.target

[Service]
Type=forking
User=wasadmin
Group=wasgrp
ExecStart=/opt/IBM/WebSphere/AppServer/profiles/Dmgr01/bin/startManager.sh
ExecStop=/opt/IBM/WebSphere/AppServer/profiles/Dmgr01/bin/stopManager.sh -username wasadmin -password Str0ngP@ss!
PIDFile=/opt/IBM/WebSphere/AppServer/profiles/Dmgr01/logs/dmgr/dmgr.pid
LimitNOFILE=65536
LimitNPROC=16384
TimeoutStartSec=300
TimeoutStopSec=120
Restart=on-failure
RestartSec=30

[Install]
WantedBy=multi-user.target
```

`/etc/systemd/system/was-nodeagent.service`:

```ini
[Unit]
Description=IBM WebSphere Node Agent
After=network.target was-dmgr.service
Wants=was-dmgr.service

[Service]
Type=forking
User=wasadmin
Group=wasgrp
ExecStart=/opt/IBM/WebSphere/AppServer/profiles/AppSrv01/bin/startNode.sh
ExecStop=/opt/IBM/WebSphere/AppServer/profiles/AppSrv01/bin/stopNode.sh -username wasadmin -password Str0ngP@ss!
PIDFile=/opt/IBM/WebSphere/AppServer/profiles/AppSrv01/logs/nodeagent/nodeagent.pid
LimitNOFILE=65536
LimitNPROC=16384
TimeoutStartSec=300
TimeoutStopSec=120
Restart=on-failure
RestartSec=30

[Install]
WantedBy=multi-user.target
```

```bash
# Enable and start services
sudo systemctl daemon-reload
sudo systemctl enable --now was-dmgr
sudo systemctl enable --now was-nodeagent

# Check status
sudo systemctl status was-dmgr
sudo systemctl status was-nodeagent

# Tail logs
journalctl -u was-dmgr -f
journalctl -u was-nodeagent -f
```

### Systemd Service for Liberty

`/etc/systemd/system/liberty-myserver.service`:

```ini
[Unit]
Description=IBM Liberty Server - myServer
After=network.target

[Service]
Type=simple
User=wasadmin
Group=wasgrp
Environment="JAVA_HOME=/opt/IBM/java/8.0"
Environment="WLP_USER_DIR=/opt/IBM/wlp/usr"
ExecStart=/opt/IBM/wlp/bin/server run myServer
ExecStop=/opt/IBM/wlp/bin/server stop myServer
LimitNOFILE=65536
TimeoutStartSec=120
TimeoutStopSec=60
Restart=on-failure
RestartSec=15

[Install]
WantedBy=multi-user.target
```

### Ulimits and File Descriptor Tuning

```bash
# /etc/security/limits.d/99-websphere.conf
wasadmin soft nofile 65536
wasadmin hard nofile 65536
wasadmin soft nproc  16384
wasadmin hard nproc  16384
wasadmin soft core   unlimited
wasadmin hard core   unlimited

# Verify (as wasadmin)
su - wasadmin -c 'ulimit -a'
```

---

## Related Skills

| Workload | Skill |
|---|---|
| Core RHEL admin (dnf, SELinux, firewalld, LVM) | `rhel-server-admin` |
| Web servers (Nginx, Apache/IHS, Caddy) | `rhel-web-servers` |
| Databases (PostgreSQL, MySQL, Redis) | `rhel-databases` |
| DB2 LUW on RHEL | `db2-rhel` |
| DB2 on z/OS | `db2-mainframe` |
| IBM Mainframe (JCL, TSO, ISPF) | `ibm-mainframe` |
| Cognos Analytics administration | `cognos-admin` |
| Docker / Podman containers | `rhel-docker-host` |
| Monitoring (Prometheus, Grafana, PCP) | `rhel-monitoring` |
