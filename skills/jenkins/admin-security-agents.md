# Architecture, Installation, Security, and Agents

Reference file for the `jenkins` skill. Covers architecture overview, RHEL 9 installation, security (RBAC, LDAP/AD, credentials), and agent management (SSH, Docker, Kubernetes).

## 1. Architecture

**Controller (master):** Orchestrates builds, serves the web UI, stores configuration, manages plugins, schedules jobs. Runs on a single JVM. Should NOT execute builds directly.

**Agents (formerly slaves):** Execute build steps delegated by the controller. Each agent runs a `remoting.jar` process that communicates with the controller.

**Executors:** Threads on an agent (or controller) that run builds. Each executor handles one build at a time. Configure 1-2 executors per CPU core on agents; set controller executors to 0.

**Communication Protocols:**
- **SSH (outbound):** Controller initiates SSH connection to agent. Preferred for permanent Linux agents. Controller needs SSH credentials for the agent host.
- **JNLP/Inbound (TCP or WebSocket):** Agent initiates connection to controller. Required for agents behind NAT/firewalls, Docker agents, Kubernetes pods. Uses the Jenkins agent port (default 50000).

**File System Layout ($JENKINS_HOME):**

```
$JENKINS_HOME/                         # default: /var/lib/jenkins
  config.xml                           # global configuration
  credentials.xml                      # encrypted credentials store
  secrets/                             # encryption keys (CRITICAL — back up)
  jobs/
    <job-name>/
      config.xml                       # job definition
      builds/                          # build history, logs, artifacts
  nodes/                               # agent definitions
  plugins/                             # installed plugin .jpi/.hpi files
  users/                               # user accounts and API tokens
  userContent/                         # files served at /userContent/
  logs/                                # Jenkins application logs
  war/                                 # exploded WAR (managed by Jenkins)
  updates/                             # plugin update center cache
  workspace/                           # build workspaces (controller — should be empty)
```

---

## 2. Installation on RHEL 9

### LTS Repository Setup

```bash
# Import Jenkins GPG key
sudo rpm --import https://pkg.jenkins.io/redhat-stable/jenkins.io-2023.key

# Add Jenkins LTS repo
sudo tee /etc/yum.repos.d/jenkins.repo <<'EOF'
[jenkins]
name=Jenkins-stable
baseurl=https://pkg.jenkins.io/redhat-stable/
gpgcheck=1
gpgkey=https://pkg.jenkins.io/redhat-stable/jenkins.io-2023.key
enabled=1
EOF

# Install Java 17 (required) and Jenkins
sudo dnf install -y java-17-openjdk java-17-openjdk-devel
sudo dnf install -y jenkins

# Or Java 21 (supported from Jenkins 2.426.1+)
sudo dnf install -y java-21-openjdk java-21-openjdk-devel
```

### Systemd Service

```bash
# Enable and start
sudo systemctl daemon-reload
sudo systemctl enable --now jenkins

# Check status
sudo systemctl status jenkins

# View logs
journalctl -u jenkins -f

# Default port: 8080, agent port: 50000
# Config overrides: /usr/lib/systemd/system/jenkins.service (do not edit directly)
# Override file: /etc/sysconfig/jenkins or systemd override
```

### Systemd Override (Memory / Port / Java Options)

```bash
sudo systemctl edit jenkins
```

```ini
[Service]
Environment="JAVA_OPTS=-Djava.awt.headless=true -Xms1g -Xmx4g -XX:+UseG1GC"
Environment="JENKINS_PORT=8080"
Environment="JENKINS_LISTEN_ADDRESS=127.0.0.1"
```

```bash
sudo systemctl daemon-reload
sudo systemctl restart jenkins
```

### Initial Setup Wizard

```bash
# Retrieve initial admin password
sudo cat /var/lib/jenkins/secrets/initialAdminPassword

# Browse to http://<host>:8080 and complete wizard
# Install suggested plugins or select custom
# Create first admin user (replace the default admin)
```

### Firewalld Rules

```bash
# Jenkins web UI (restrict to admin subnet)
sudo firewall-cmd --permanent --add-rich-rule='rule family="ipv4" source address="10.0.1.0/24" port port="8080" protocol="tcp" accept'

# Agent inbound port (restrict to agent subnet)
sudo firewall-cmd --permanent --add-rich-rule='rule family="ipv4" source address="10.0.2.0/24" port port="50000" protocol="tcp" accept'

sudo firewall-cmd --reload
```

### Reverse Proxy — Nginx with WebSocket Support

```nginx
upstream jenkins {
    server 127.0.0.1:8080 fail_timeout=0;
    keepalive 32;
}

server {
    listen 443 ssl http2;
    server_name jenkins.example.com;

    ssl_certificate     /etc/pki/tls/certs/jenkins.crt;
    ssl_certificate_key /etc/pki/tls/private/jenkins.key;

    # Security headers
    add_header X-Content-Type-Options nosniff;
    add_header X-Frame-Options SAMEORIGIN;
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;

    location / {
        proxy_pass http://jenkins;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # WebSocket support (required for agents and CLI)
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";

        proxy_read_timeout 90s;
        proxy_buffering off;
        proxy_request_buffering off;
        client_max_body_size 100m;
    }
}

server {
    listen 80;
    server_name jenkins.example.com;
    return 301 https://$host$request_uri;
}
```

Set Jenkins URL in Manage Jenkins > System:

```
Jenkins URL: https://jenkins.example.com/
```

Also configure the `--prefix` if running under a subpath:

```ini
# systemd override
Environment="JENKINS_PREFIX=/jenkins"
```

---

## 3. Security

### Matrix-Based Security

Manage Jenkins > Security > Authorization > Matrix-based security. Assign per-user or per-group permissions (Overall/Read, Job/Build, Job/Configure, etc.).

### Role-Based Strategy (Role Strategy Plugin)

```
# Install Role Strategy plugin, then:
# Manage Jenkins > Security > Authorization > Role-Based Strategy
# Manage Jenkins > Manage and Assign Roles

# Global roles:
#   admin    — all permissions
#   developer — Overall/Read, Job/Build, Job/Read, Job/Workspace
#   viewer   — Overall/Read, Job/Read

# Project roles (regex pattern matching):
#   team-alpha-.*  — full Job/* permissions for team-alpha members
#   release-.*     — Job/Build, Job/Read for release managers
```

### LDAP / Active Directory Integration

Manage Jenkins > Security > Security Realm > LDAP.

```
Server:            ldaps://ldap.example.com:636
Root DN:           dc=example,dc=com
User search base:  ou=People
User search filter: uid={0}
Group search base: ou=Groups
Group membership:  Search for LDAP groups containing user
                   Group membership filter: (| (member={0}) (uniqueMember={0}) (memberUid={1}))
Manager DN:        cn=jenkins-svc,ou=Service,dc=example,dc=com
Manager Password:  (stored as credential)
```

For Active Directory: use the Active Directory plugin instead. Configure domain, domain controller, bind DN.

### SAML / OIDC SSO

- **SAML:** Install `saml` plugin. Configure IdP metadata URL, SP entity ID, username/email/group attributes.
- **OIDC:** Install `oic-auth` plugin. Configure client ID, client secret, authorization/token/userinfo endpoints, scopes (`openid email profile`).

### Credentials Management

Types of credentials:
- **Username with password** — Git, Docker registries, API keys
- **SSH Username with private key** — SSH agents, Git over SSH
- **Secret text** — API tokens, webhooks, single-value secrets
- **Secret file** — Certificates, kubeconfig, service account keys
- **Certificate (PKCS#12)** — Client certificates

```groovy
// Using credentials in a pipeline
pipeline {
    agent any
    environment {
        // Binds credentials to environment variables
        DOCKER_CREDS = credentials('docker-registry-creds')  // _USR and _PSW
        API_TOKEN    = credentials('my-api-token')            // secret text
    }
    stages {
        stage('Build') {
            steps {
                // Username/password credential
                withCredentials([usernamePassword(
                    credentialsId: 'docker-registry-creds',
                    usernameVariable: 'DOCKER_USER',
                    passwordVariable: 'DOCKER_PASS'
                )]) {
                    sh 'docker login -u $DOCKER_USER -p $DOCKER_PASS registry.example.com'
                }

                // SSH key credential
                withCredentials([sshUserPrivateKey(
                    credentialsId: 'deploy-ssh-key',
                    keyFileVariable: 'SSH_KEY',
                    usernameVariable: 'SSH_USER'
                )]) {
                    sh 'ssh -i $SSH_KEY $SSH_USER@prod-server "deploy.sh"'
                }

                // Secret file credential
                withCredentials([file(credentialsId: 'kubeconfig', variable: 'KUBECONFIG')]) {
                    sh 'kubectl --kubeconfig=$KUBECONFIG get pods'
                }
            }
        }
    }
}
```

**Credential Domains:** Scope credentials to specific URLs/hosts so they auto-bind only where needed.

### Script Security

- **Sandbox:** Groovy scripts in pipelines run in a restricted sandbox by default. Only whitelisted methods are allowed.
- **Script Approval:** Unapproved method calls trigger approval requests in Manage Jenkins > In-Process Script Approval. An admin must review and approve or deny each signature.
- **Shared libraries:** Libraries loaded with `@Library` annotation execute outside the sandbox. Review library code carefully — it has full access.

### CSRF Protection

Enabled by default (crumb issuer). Do not disable. For API calls, obtain a crumb first:

```bash
CRUMB=$(curl -s -u admin:API_TOKEN 'https://jenkins.example.com/crumbIssuer/api/json' | jq -r '.crumb')
curl -X POST -u admin:API_TOKEN -H "Jenkins-Crumb:$CRUMB" \
  'https://jenkins.example.com/job/my-job/build'
```

Or use API tokens (recommended over password+crumb).

### Agent-to-Controller Security

Manage Jenkins > Security > Agent > Agent-to-Controller Access Control. Restrict which directories and commands agents can access on the controller. Enable and keep the default deny-all policy; whitelist only what is strictly necessary.

---

## 4. Agent Management

### SSH Agents (Permanent)

Manage Jenkins > Nodes > New Node:

```
Name:          build-agent-01
Remote root:   /var/lib/jenkins
Labels:        linux docker maven
# of executors: 4
Launch method: Launch agents via SSH
  Host:        10.0.2.10
  Credentials: (SSH key credential)
  Host Key Verification Strategy: Known hosts file (or Manually trusted)
```

Prepare the agent host:

```bash
# On the agent machine
sudo useradd -m -d /var/lib/jenkins -s /bin/bash jenkins
sudo mkdir -p /var/lib/jenkins
sudo chown jenkins:jenkins /var/lib/jenkins

# Install Java (same version as controller)
sudo dnf install -y java-17-openjdk

# Ensure SSH access from controller
# Add controller's public key to /var/lib/jenkins/.ssh/authorized_keys
```

### JNLP / Inbound Agents

Manage Jenkins > Security > Agents > TCP port for inbound agents: Fixed (50000) or Random.

Manage Jenkins > Nodes > New Node:

```
Launch method: Launch agent by connecting it to the controller
```

On the agent machine:

```bash
# Download agent.jar from controller
curl -sO https://jenkins.example.com/jnlpJars/agent.jar

# Launch agent (secret from node configuration page)
java -jar agent.jar \
  -url https://jenkins.example.com/ \
  -secret <agent-secret> \
  -name build-agent-02 \
  -workDir /var/lib/jenkins
```

Systemd service for inbound agent:

```ini
[Unit]
Description=Jenkins Inbound Agent
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=jenkins
ExecStart=/usr/bin/java -jar /opt/jenkins/agent.jar \
  -url https://jenkins.example.com/ \
  -secret @/opt/jenkins/secret-file \
  -name build-agent-02 \
  -webSocket \
  -workDir /var/lib/jenkins
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

### Docker Agents

Use the Docker plugin or docker-workflow (Pipeline) plugin.

```groovy
// Jenkinsfile — agent runs inside a Docker container
pipeline {
    agent {
        docker {
            image 'maven:3.9-eclipse-temurin-17'
            args '-v $HOME/.m2:/root/.m2'
            label 'docker'   // run on agent with Docker installed
        }
    }
    stages {
        stage('Build') {
            steps {
                sh 'mvn clean package'
            }
        }
    }
}
```

Docker Cloud configuration (Manage Jenkins > Clouds > Docker):

```
Docker Host URI:  tcp://docker-host:2376  (or unix:///var/run/docker.sock)
Server credentials: (X.509 client cert for TLS)
Docker Agent templates:
  Labels:     docker-agent
  Docker Image: jenkins/inbound-agent:latest
  Remote FS:  /home/jenkins/agent
  Connect method: Attach Docker container
```

### Kubernetes Agents (Kubernetes Plugin)

Manage Jenkins > Clouds > Kubernetes:

```
Kubernetes URL:      https://kubernetes.default
Jenkins URL:         https://jenkins.example.com
Jenkins tunnel:      jenkins-agent.jenkins.svc:50000
Namespace:           jenkins
```

Pod template in Jenkinsfile:

```groovy
pipeline {
    agent {
        kubernetes {
            yaml '''
apiVersion: v1
kind: Pod
metadata:
  labels:
    app: jenkins-agent
spec:
  containers:
  - name: maven
    image: maven:3.9-eclipse-temurin-17
    command: ['sleep']
    args: ['infinity']
    volumeMounts:
    - name: maven-cache
      mountPath: /root/.m2
  - name: docker
    image: docker:24-dind
    securityContext:
      privileged: true
    volumeMounts:
    - name: docker-sock
      mountPath: /var/run/docker.sock
  volumes:
  - name: maven-cache
    persistentVolumeClaim:
      claimName: maven-cache-pvc
  - name: docker-sock
    hostPath:
      path: /var/run/docker.sock
'''
        }
    }
    stages {
        stage('Build') {
            steps {
                container('maven') {
                    sh 'mvn clean package'
                }
            }
        }
        stage('Docker Build') {
            steps {
                container('docker') {
                    sh 'docker build -t myapp:${BUILD_NUMBER} .'
                }
            }
        }
    }
}
```

### Labels and Node Selection

```groovy
// Run on any agent with the 'linux' and 'docker' labels
agent { label 'linux && docker' }

// Run on any agent with either label
agent { label 'linux || macos' }
```

---

## 5. Plugin Management

### Installation

```bash
# CLI installation
java -jar jenkins-cli.jar -s https://jenkins.example.com/ -auth admin:TOKEN \
  install-plugin pipeline-stage-view docker-workflow kubernetes blueocean job-dsl \
  configuration-as-code role-strategy

# Restart after install
java -jar jenkins-cli.jar -s https://jenkins.example.com/ -auth admin:TOKEN safe-restart
```

Via JCasC (see section 7).

### Essential Plugins

| Plugin | Purpose |
|---|---|
| `workflow-aggregator` | Pipeline (Declarative + Scripted) |
| `git` | Git SCM integration |
| `credentials-binding` | Bind credentials to variables in pipelines |
| `docker-workflow` | Docker agent support in pipelines |
| `kubernetes` | Kubernetes cloud agents with pod templates |
| `blueocean` | Modern pipeline visualization UI |
| `job-dsl` | Programmatic job creation via Groovy DSL |
| `configuration-as-code` | Jenkins Configuration as Code (JCasC) |
| `role-strategy` | Role-based authorization |
| `pipeline-stage-view` | Stage-level pipeline visualization |
| `pipeline-utility-steps` | readJSON, readYaml, writeFile, zip, etc. |
| `timestamper` | Timestamps in console output |
| `ws-cleanup` | Workspace cleanup |
| `email-ext` | Extended email notifications |
| `slack` | Slack notifications |
| `htmlpublisher` | Publish HTML reports |
| `jacoco` | Code coverage reports |
| `warnings-ng` | Static analysis warnings aggregation |

### Update Strategy

- Subscribe to Jenkins security advisories: https://www.jenkins.io/security/advisories/
- Update plugins in batches, test on a staging Jenkins first
- Pin critical plugins to known-good versions in production
- Check plugin compatibility matrix before upgrading Jenkins core
- Use `plugin-installation-manager-tool` for reproducible installs:

```bash
# Download the tool
curl -fL -o jenkins-plugin-manager.jar \
  https://github.com/jenkinsci/plugin-installation-manager-tool/releases/latest/download/jenkins-plugin-manager-*.jar

# Install from a plugins.txt file
java -jar jenkins-plugin-manager.jar \
  --war /usr/share/java/jenkins.war \
  --plugin-file plugins.txt \
  --plugin-download-directory /var/lib/jenkins/plugins
```

`plugins.txt`:
```
workflow-aggregator:latest
git:latest
configuration-as-code:latest
kubernetes:latest
docker-workflow:latest
role-strategy:latest
job-dsl:latest
```

---

