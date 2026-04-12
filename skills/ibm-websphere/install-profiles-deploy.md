# Architecture, Installation, Profiles, and Deployment

Reference file for the `ibm-websphere` skill. Covers WAS architecture, RHEL 9 installation, profile management, and application deployment (WAR/EAR).

## 1. Architecture

### WAS Traditional (8.5.5 / 9.0)

Cell/Node/Server topology:

- **Cell** — top-level administrative grouping; contains one or more nodes. A cell has one Deployment Manager.
- **Node** — a logical grouping of servers on a single OS instance; managed by a Node Agent.
- **Server** — a single JVM running applications (e.g., `server1`).

Key processes:

| Process | Role | Default ports |
|---|---|---|
| Deployment Manager (dmgr) | Central admin for the cell | 9060 (HTTP console), 9043 (HTTPS console), 8879 (SOAP), 8880 (SOAP connector) |
| Node Agent (nodeagent) | Manages servers on a node, syncs config from dmgr | 2809 (BOOTSTRAP), 9809 (SOAP) |
| Application Server | Runs applications | 9080 (HTTP), 9443 (HTTPS), 9081 (WC_defaulthost_secure) |

### WAS Network Deployment (ND) Clustering

- Multiple application servers grouped into a **cluster** for HA and workload distribution.
- Cluster members can span multiple nodes (physical/virtual hosts).
- Workload management (WLM) distributes requests; HTTP plugin (`plugin-cfg.xml`) routes from IHS/web server to cluster members.
- Session replication (memory-to-memory or database) maintains state across cluster members.

### WebSphere Liberty / Open Liberty

- **Liberty** — lightweight, composable runtime; feature-based configuration via `server.xml`.
- **Open Liberty** — open-source upstream of Liberty; same runtime, community-driven features.
- Ideal for microservices, cloud-native, and containerized deployments.
- No cell/node topology; each server is standalone or managed via Liberty Admin Center / Liberty Collective.

---

## 2. Installation on RHEL 9

### Prerequisites

```bash
# Required packages (64-bit)
sudo dnf install -y glibc.i686 glibc.x86_64 libstdc++.i686 libstdc++.x86_64 \
  gtk2.x86_64 gtk3.x86_64 libXtst.x86_64 nss.x86_64 \
  ksh unzip tar

# Verify RHEL version
cat /etc/redhat-release

# Create WAS user and group
sudo groupadd wasgrp
sudo useradd -g wasgrp -d /home/wasadmin -m wasadmin

# Create installation directories
sudo mkdir -p /opt/IBM/InstallationManager
sudo mkdir -p /opt/IBM/WebSphere/AppServer
sudo mkdir -p /opt/IBM/IMShared
sudo chown -R wasadmin:wasgrp /opt/IBM
```

### RHEL Kernel Tuning

```bash
# /etc/sysctl.d/99-websphere.conf
net.ipv4.tcp_keepalive_time = 300
net.ipv4.tcp_keepalive_intvl = 60
net.ipv4.tcp_keepalive_probes = 5
net.ipv4.ip_local_port_range = 1024 65535
net.core.somaxconn = 4096
net.core.netdev_max_backlog = 5000
vm.swappiness = 10

# Apply
sudo sysctl --system
```

### IBM Installation Manager (imcl) — Silent Install

```bash
# Extract Installation Manager
su - wasadmin
cd /tmp
unzip agent.installer.linux.gtk.x86_64_*.zip -d /tmp/im_installer

# Silent install of Installation Manager
/tmp/im_installer/installc -acceptLicense \
  -installationDirectory /opt/IBM/InstallationManager/eclipse \
  -dataLocation /opt/IBM/IMData \
  -showProgress

# Set up repository (local or remote)
# Local: extract WAS packages to /tmp/was_repo
# Remote: use IBM Passport Advantage URL

# Silent install of WAS 9.0 ND
/opt/IBM/InstallationManager/eclipse/tools/imcl install \
  com.ibm.websphere.ND.v90 \
  -repositories /tmp/was_repo/repository.config \
  -installationDirectory /opt/IBM/WebSphere/AppServer \
  -sharedResourcesDirectory /opt/IBM/IMShared \
  -acceptLicense \
  -showProgress \
  -properties user.wasjava=java8

# Verify installation
/opt/IBM/WebSphere/AppServer/bin/versionInfo.sh
```

### Response File Install (fully automated)

```bash
# Generate response file from a reference install
/opt/IBM/InstallationManager/eclipse/tools/imcl listInstalledPackages

# Create response file: /tmp/was_install_response.xml
# Then install using response file
/opt/IBM/InstallationManager/eclipse/tools/imcl input /tmp/was_install_response.xml \
  -acceptLicense -showProgress -log /tmp/was_install.log
```

### Fix Pack Application

```bash
# List installed packages and versions
/opt/IBM/InstallationManager/eclipse/tools/imcl listInstalledPackages -long

# Apply fix pack (stop all servers first)
/opt/IBM/WebSphere/AppServer/bin/stopServer.sh server1 -username wasadmin -password <pass>

/opt/IBM/InstallationManager/eclipse/tools/imcl install \
  com.ibm.websphere.ND.v90 \
  -repositories /tmp/fixpack_repo/repository.config \
  -installationDirectory /opt/IBM/WebSphere/AppServer \
  -acceptLicense -showProgress

# Verify
/opt/IBM/WebSphere/AppServer/bin/versionInfo.sh
```

### Liberty / Open Liberty Install (unzip-based)

```bash
# Liberty — download from IBM Fix Central or Passport Advantage
cd /opt/IBM
unzip /tmp/wlp-javaee8-*.zip
# Result: /opt/IBM/wlp/

# Open Liberty — download from openliberty.io
wget https://openliberty.io/api/artefact/LATEST/wlp-javaee8.zip
unzip wlp-javaee8.zip -d /opt/IBM/
# Result: /opt/IBM/wlp/

# Verify
/opt/IBM/wlp/bin/server version

# Create a server instance
/opt/IBM/wlp/bin/server create myServer
# Config: /opt/IBM/wlp/usr/servers/myServer/server.xml
```

---

## 3. Profile Management

### Create Profiles (manageprofiles.sh)

```bash
WAS_HOME=/opt/IBM/WebSphere/AppServer

# Create Deployment Manager profile
$WAS_HOME/bin/manageprofiles.sh -create \
  -profileName Dmgr01 \
  -profilePath $WAS_HOME/profiles/Dmgr01 \
  -templatePath $WAS_HOME/profileTemplates/management \
  -serverType DEPLOYMENT_MANAGER \
  -cellName MyCell \
  -nodeName DmgrNode \
  -hostName dmgr01.example.com \
  -enableAdminSecurity true \
  -adminUserName wasadmin \
  -adminPassword 'Str0ngP@ss!'

# Create Custom profile (for federation into ND cell)
$WAS_HOME/bin/manageprofiles.sh -create \
  -profileName AppSrv01 \
  -profilePath $WAS_HOME/profiles/AppSrv01 \
  -templatePath $WAS_HOME/profileTemplates/managed \
  -hostName appnode01.example.com \
  -nodeName AppNode01 \
  -cellName AppNode01Cell

# Create Standalone profile (no dmgr needed)
$WAS_HOME/bin/manageprofiles.sh -create \
  -profileName Standalone01 \
  -profilePath $WAS_HOME/profiles/Standalone01 \
  -templatePath $WAS_HOME/profileTemplates/default \
  -hostName standalone01.example.com \
  -nodeName StandaloneNode \
  -cellName StandaloneCell \
  -enableAdminSecurity true \
  -adminUserName wasadmin \
  -adminPassword 'Str0ngP@ss!'

# List all profiles
$WAS_HOME/bin/manageprofiles.sh -listProfiles

# Delete a profile
$WAS_HOME/bin/manageprofiles.sh -delete -profileName AppSrv01
```

### Federation (addNode.sh)

```bash
# Start dmgr first
$WAS_HOME/profiles/Dmgr01/bin/startManager.sh

# Federate a custom profile node into the cell
$WAS_HOME/profiles/AppSrv01/bin/addNode.sh dmgr01.example.com 8879 \
  -username wasadmin \
  -password 'Str0ngP@ss!' \
  -includeapps

# Remove node from cell (run from the node)
$WAS_HOME/profiles/AppSrv01/bin/removeNode.sh \
  -username wasadmin \
  -password 'Str0ngP@ss!'
```

### Port Assignments

Default ports increment by profile. Check assignments:

```bash
cat $WAS_HOME/profiles/Dmgr01/properties/portdef.props
cat $WAS_HOME/profiles/AppSrv01/properties/portdef.props
```

Key ports to know:

| Port | Service |
|---|---|
| 9060 | Admin console HTTP |
| 9043 | Admin console HTTPS |
| 8879/8880 | SOAP connector |
| 9080 | HTTP transport (WC_defaulthost) |
| 9443 | HTTPS transport (WC_defaulthost_secure) |
| 2809 | Bootstrap/RMI |
| 9809 | SOAP (node agent) |
| 7276/7286 | SIBus messaging |
| 9100 | ORB listener |

---

## 4. Application Deployment

### Admin Console Deployment

1. Log in to `https://dmgr01.example.com:9043/ibm/console`
2. Navigate: Applications > New Application > New Enterprise Application
3. Upload EAR/WAR, map modules to servers/clusters, configure context root, map security roles
4. Save to master configuration; sync nodes

### wsadmin Scripting for Deployment

```python
# deploy_app.py — Run with: wsadmin.sh -lang jython -f deploy_app.py

appName = 'MyWebApp'
earPath = '/tmp/MyWebApp.ear'
clusterName = 'AppCluster'
contextRoot = '/myapp'

# Install application
AdminApp.install(earPath, [
    '-appname', appName,
    '-cluster', clusterName,
    '-contextroot', contextRoot,
    '-MapModulesToServers', [
        ['.*', '.*', 'WebSphere:cell=MyCell,cluster=' + clusterName]
    ],
    '-usedefaultbindings',
    '-defaultbinding.virtual.host', 'default_host'
])

# Save configuration
AdminConfig.save()

# Sync all nodes
dmgr = AdminControl.queryNames('type=DeploymentManager,*')
AdminControl.invoke(dmgr, 'multiSync', '[nodes=* rolloutUpdate=false]')

# Start application
appManager = AdminControl.queryNames('type=ApplicationManager,process=server1,*')
AdminControl.invoke(appManager, 'startApplication', appName)

print('Application %s deployed successfully.' % appName)
```

### Class Loader Policies

```python
# Set class loader policy to PARENT_LAST (application classes take precedence)
deployment = AdminConfig.getid('/Deployment:%s/' % appName)
depObject = AdminConfig.showAttribute(deployment, 'deployedObject')

# WAR module class loader
modules = AdminConfig.showAttribute(depObject, 'modules')
for module in modules[1:-1].split(' '):
    moduleType = AdminConfig.showAttribute(module, 'uri')
    if moduleType.endswith('.war'):
        AdminConfig.modify(module, [['classloaderMode', 'PARENT_LAST']])

# Application-level class loader
AdminConfig.modify(depObject, [['warClassLoaderPolicy', 'SINGLE']])

AdminConfig.save()
```

### Shared Libraries

```python
# Create shared library
cellId = AdminConfig.getid('/Cell:MyCell/')
AdminConfig.create('Library', cellId, [
    ['name', 'CommonLib'],
    ['classPath', '/opt/IBM/shared/lib/commons-lang3.jar;/opt/IBM/shared/lib/guava.jar'],
    ['nativePath', '']
])

# Associate shared library with application
deployment = AdminConfig.getid('/Deployment:%s/' % appName)
depObject = AdminConfig.showAttribute(deployment, 'deployedObject')
classloader = AdminConfig.showAttribute(depObject, 'classloader')
AdminConfig.create('LibraryRef', classloader, [['libraryName', 'CommonLib'], ['sharedClassloader', 'true']])

AdminConfig.save()
```

---

