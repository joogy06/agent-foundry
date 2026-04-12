# Backup, JCasC, and Declarative Pipelines

Reference file for the `jenkins` skill. Covers backup/disaster recovery, Jenkins Configuration as Code (JCasC), and declarative pipeline syntax and patterns.

## 6. Backup & Disaster Recovery

### What to Back Up

| Path | Contents | Critical? |
|---|---|---|
| `$JENKINS_HOME/config.xml` | Global configuration | Yes |
| `$JENKINS_HOME/credentials.xml` | Encrypted credentials | Yes |
| `$JENKINS_HOME/secrets/` | Encryption keys | CRITICAL |
| `$JENKINS_HOME/jobs/` | Job configs and build history | Yes |
| `$JENKINS_HOME/nodes/` | Agent definitions | Yes |
| `$JENKINS_HOME/users/` | User accounts | Yes |
| `$JENKINS_HOME/plugins/` | Installed plugins | Recommended |
| `$JENKINS_HOME/*.xml` | Various config files | Yes |
| `$JENKINS_HOME/userContent/` | User-published files | If used |

**Do NOT back up:** `$JENKINS_HOME/war/`, `$JENKINS_HOME/caches/`, `$JENKINS_HOME/workspace/` (rebuild from SCM).

### Scripted Backup

```bash
#!/bin/bash
set -euo pipefail
JENKINS_HOME="/var/lib/jenkins"
BACKUP_DIR="/backup/jenkins"
RETENTION=14
TS=$(date +%Y%m%d_%H%M%S)
ARCHIVE="$BACKUP_DIR/jenkins_${TS}.tar.gz"

mkdir -p "$BACKUP_DIR"

# Backup critical files (exclude workspace, war, caches)
tar czf "$ARCHIVE" \
  --exclude="$JENKINS_HOME/workspace" \
  --exclude="$JENKINS_HOME/war" \
  --exclude="$JENKINS_HOME/caches" \
  --exclude="$JENKINS_HOME/.cache" \
  -C "$(dirname "$JENKINS_HOME")" \
  "$(basename "$JENKINS_HOME")"

# Retention
find "$BACKUP_DIR" -name "jenkins_*.tar.gz" -mtime +$RETENTION -delete

echo "Backup complete: $ARCHIVE ($(du -sh "$ARCHIVE" | cut -f1))"
```

### Systemd Timer for Automated Backup

`/etc/systemd/system/jenkins-backup.service`:
```ini
[Unit]
Description=Jenkins daily backup
After=jenkins.service

[Service]
Type=oneshot
ExecStart=/usr/local/bin/jenkins-backup.sh
```

`/etc/systemd/system/jenkins-backup.timer`:
```ini
[Unit]
Description=Jenkins backup daily 03:00

[Timer]
OnCalendar=*-*-* 03:00:00
Persistent=true
RandomizedDelaySec=300

[Install]
WantedBy=timers.target
```

```bash
sudo chmod +x /usr/local/bin/jenkins-backup.sh
sudo systemctl daemon-reload
sudo systemctl enable --now jenkins-backup.timer
```

### Restore Procedure

```bash
sudo systemctl stop jenkins
sudo tar xzf /backup/jenkins/jenkins_20260331_030000.tar.gz -C /var/lib/
sudo chown -R jenkins:jenkins /var/lib/jenkins
sudo systemctl start jenkins
```

### HA Patterns

- **Active/Passive with shared storage:** Two Jenkins controllers, shared $JENKINS_HOME on NFS or GlusterFS, failover via keepalived/Pacemaker. Only one controller active at a time.
- **CloudBees CI (commercial):** Managed controllers, HA, horizontal scaling.
- **Stateless controller + JCasC:** Rebuild controller from JCasC + SCM. All job definitions in Jenkinsfiles. Fastest recovery approach.

---

## 7. JCasC (Jenkins Configuration as Code)

### jenkins.yaml Structure

Place at `$JENKINS_HOME/jenkins.yaml` or set `CASC_JENKINS_CONFIG` environment variable.

```yaml
jenkins:
  systemMessage: "Jenkins — configured by JCasC"
  numExecutors: 0  # No builds on controller
  mode: EXCLUSIVE
  quietPeriod: 5

  securityRealm:
    ldap:
      configurations:
        - server: "ldaps://ldap.example.com:636"
          rootDN: "dc=example,dc=com"
          userSearchBase: "ou=People"
          userSearch: "uid={0}"
          groupSearchBase: "ou=Groups"
          managerDN: "cn=jenkins-svc,ou=Service,dc=example,dc=com"
          managerPasswordSecret: "${LDAP_MANAGER_PASSWORD}"

  authorizationStrategy:
    roleBased:
      roles:
        global:
          - name: "admin"
            permissions:
              - "Overall/Administer"
            entries:
              - group: "jenkins-admins"
          - name: "developer"
            permissions:
              - "Overall/Read"
              - "Job/Build"
              - "Job/Read"
              - "Job/Workspace"
              - "Job/Cancel"
            entries:
              - group: "developers"
          - name: "viewer"
            permissions:
              - "Overall/Read"
              - "Job/Read"
            entries:
              - group: "viewers"

  nodes:
    - permanent:
        name: "build-agent-01"
        remoteFS: "/var/lib/jenkins"
        numExecutors: 4
        labelString: "linux docker maven"
        launcher:
          ssh:
            host: "10.0.2.10"
            port: 22
            credentialsId: "agent-ssh-key"
            sshHostKeyVerificationStrategy:
              manuallyTrustedKeyVerificationStrategy:
                requireInitialManualTrust: false

  clouds:
    - kubernetes:
        name: "kubernetes"
        serverUrl: "https://kubernetes.default"
        namespace: "jenkins"
        jenkinsUrl: "http://jenkins.jenkins.svc:8080"
        jenkinsTunnel: "jenkins-agent.jenkins.svc:50000"
        podLabels:
          - key: "app"
            value: "jenkins-agent"
        templates:
          - name: "default"
            label: "k8s"
            containers:
              - name: "jnlp"
                image: "jenkins/inbound-agent:latest"
                workingDir: "/home/jenkins/agent"
                resourceRequestCpu: "500m"
                resourceRequestMemory: "512Mi"

credentials:
  system:
    domainCredentials:
      - credentials:
          - usernamePassword:
              scope: GLOBAL
              id: "docker-registry-creds"
              username: "deploy-svc"
              password: "${DOCKER_REGISTRY_PASSWORD}"
          - basicSSHUserPrivateKey:
              scope: GLOBAL
              id: "agent-ssh-key"
              username: "jenkins"
              privateKeySource:
                directEntry:
                  privateKey: "${readFile:/var/lib/jenkins/secrets/agent-key}"
          - string:
              scope: GLOBAL
              id: "slack-webhook"
              secret: "${SLACK_WEBHOOK_URL}"

tool:
  git:
    installations:
      - name: "Default"
        home: "/usr/bin/git"
  jdk:
    installations:
      - name: "JDK17"
        home: "/usr/lib/jvm/java-17-openjdk"
      - name: "JDK21"
        home: "/usr/lib/jvm/java-21-openjdk"
  maven:
    installations:
      - name: "Maven3"
        properties:
          - installSource:
              installers:
                - maven:
                    id: "3.9.6"
  nodejs:
    installations:
      - name: "NodeJS20"
        properties:
          - installSource:
              installers:
                - nodeJSInstaller:
                    id: "20.11.1"

unclassified:
  location:
    url: "https://jenkins.example.com/"
    adminAddress: "jenkins-admin@example.com"
  slackNotifier:
    teamDomain: "myteam"
    tokenCredentialId: "slack-webhook"
    room: "#ci-cd"
```

### Secrets Management

```bash
# Environment variables (preferred for JCasC secrets)
# Set in systemd override or /etc/sysconfig/jenkins
Environment="LDAP_MANAGER_PASSWORD=SecretPass123"
Environment="DOCKER_REGISTRY_PASSWORD=RegistryPass456"
Environment="SLACK_WEBHOOK_URL=https://hooks.slack.com/services/XXX"

# HashiCorp Vault integration (via hashicorp-vault-plugin)
# Reference in JCasC:
#   password: "${vault-path/to/secret#key}"
```

### Bootstrap from Scratch

```bash
# 1. Install Jenkins + JCasC plugin
sudo dnf install -y jenkins
sudo systemctl start jenkins
# Install configuration-as-code plugin via CLI or init.groovy.d

# 2. Place jenkins.yaml
sudo cp jenkins.yaml /var/lib/jenkins/jenkins.yaml
sudo chown jenkins:jenkins /var/lib/jenkins/jenkins.yaml

# 3. Set environment variable and restart
sudo systemctl edit jenkins
# Add: Environment="CASC_JENKINS_CONFIG=/var/lib/jenkins/jenkins.yaml"
sudo systemctl restart jenkins

# 4. Reload JCasC without restart
# Manage Jenkins > Configuration as Code > Reload existing configuration
```

---

## 8. Declarative Pipelines

### Full Jenkinsfile Structure

```groovy
pipeline {
    agent {
        label 'linux && docker'
    }

    options {
        timeout(time: 30, unit: 'MINUTES')
        timestamps()
        disableConcurrentBuilds()
        buildDiscarder(logRotator(numToKeepStr: '20'))
        retry(2)
    }

    parameters {
        string(name: 'BRANCH', defaultValue: 'main', description: 'Branch to build')
        choice(name: 'ENVIRONMENT', choices: ['dev', 'staging', 'prod'], description: 'Deploy target')
        booleanParam(name: 'SKIP_TESTS', defaultValue: false, description: 'Skip test stage')
        password(name: 'DEPLOY_TOKEN', description: 'Deployment token')
    }

    environment {
        APP_NAME    = 'my-application'
        REGISTRY    = 'registry.example.com'
        IMAGE_TAG   = "${env.BUILD_NUMBER}-${env.GIT_COMMIT?.take(7)}"
        DEPLOY_CRED = credentials('deploy-credentials')
    }

    triggers {
        pollSCM('H/5 * * * *')           // poll every 5 minutes
        cron('H 2 * * 1-5')              // nightly build weekdays at ~2am
        upstream(upstreamProjects: 'lib-build', threshold: hudson.model.Result.SUCCESS)
    }

    stages {
        stage('Checkout') {
            steps {
                checkout scm
                script {
                    env.GIT_AUTHOR = sh(script: 'git log -1 --format="%an"', returnStdout: true).trim()
                }
            }
        }

        stage('Build') {
            steps {
                sh 'mvn clean compile -DskipTests'
            }
        }

        stage('Test') {
            when {
                not { expression { params.SKIP_TESTS } }
            }
            parallel {
                stage('Unit Tests') {
                    steps {
                        sh 'mvn test'
                    }
                    post {
                        always {
                            junit 'target/surefire-reports/*.xml'
                            jacoco(execPattern: 'target/jacoco.exec')
                        }
                    }
                }
                stage('Integration Tests') {
                    steps {
                        sh 'mvn verify -Pintegration'
                    }
                    post {
                        always {
                            junit 'target/failsafe-reports/*.xml'
                        }
                    }
                }
            }
        }

        stage('Docker Build & Push') {
            steps {
                withCredentials([usernamePassword(
                    credentialsId: 'docker-registry-creds',
                    usernameVariable: 'REG_USER',
                    passwordVariable: 'REG_PASS'
                )]) {
                    sh """
                        docker build -t ${REGISTRY}/${APP_NAME}:${IMAGE_TAG} .
                        echo \$REG_PASS | docker login -u \$REG_USER --password-stdin ${REGISTRY}
                        docker push ${REGISTRY}/${APP_NAME}:${IMAGE_TAG}
                    """
                }
            }
        }

        stage('Deploy to Staging') {
            when {
                branch 'main'
                environment name: 'ENVIRONMENT', value: 'staging'
            }
            steps {
                sh "./deploy.sh staging ${IMAGE_TAG}"
            }
        }

        stage('Approval') {
            when {
                branch 'main'
                environment name: 'ENVIRONMENT', value: 'prod'
            }
            steps {
                input message: 'Deploy to production?', ok: 'Deploy',
                      submitter: 'admin,release-managers'
            }
        }

        stage('Deploy to Production') {
            when {
                branch 'main'
                environment name: 'ENVIRONMENT', value: 'prod'
            }
            steps {
                sh "./deploy.sh prod ${IMAGE_TAG}"
            }
        }
    }

    post {
        always {
            cleanWs()
        }
        success {
            slackSend(channel: '#ci-cd', color: 'good',
                      message: "SUCCESS: ${APP_NAME} #${BUILD_NUMBER} by ${env.GIT_AUTHOR}")
        }
        failure {
            slackSend(channel: '#ci-cd', color: 'danger',
                      message: "FAILED: ${APP_NAME} #${BUILD_NUMBER} — ${BUILD_URL}")
            emailext(
                subject: "FAILED: ${APP_NAME} #${BUILD_NUMBER}",
                body: '${DEFAULT_CONTENT}',
                recipientProviders: [culprits(), developers()]
            )
        }
        unstable {
            slackSend(channel: '#ci-cd', color: 'warning',
                      message: "UNSTABLE: ${APP_NAME} #${BUILD_NUMBER}")
        }
        cleanup {
            sh 'docker rmi ${REGISTRY}/${APP_NAME}:${IMAGE_TAG} || true'
        }
    }
}
```

### Matrix Builds

```groovy
pipeline {
    agent none
    stages {
        stage('Test Matrix') {
            matrix {
                axes {
                    axis {
                        name 'JDK_VERSION'
                        values '17', '21'
                    }
                    axis {
                        name 'OS'
                        values 'linux', 'windows'
                    }
                }
                excludes {
                    exclude {
                        axis { name 'JDK_VERSION'; values '21' }
                        axis { name 'OS'; values 'windows' }
                    }
                }
                stages {
                    stage('Test') {
                        agent { label "${OS}" }
                        steps {
                            sh "java -version && mvn test -Djdk=${JDK_VERSION}"
                        }
                    }
                }
            }
        }
    }
}
```

---

## 9. Scripted Pipelines

Use scripted syntax only when declarative cannot express the logic (dynamic stage generation, complex flow control, programmatic parallelism).

```groovy
node('linux') {
    def modules = ['auth', 'api', 'web', 'worker']

    stage('Checkout') {
        checkout scm
    }

    stage('Build') {
        try {
            sh 'mvn clean compile'
        } catch (Exception e) {
            currentBuild.result = 'FAILURE'
            throw e
        }
    }

    // Dynamic parallel stages
    stage('Test Modules') {
        def parallelStages = [:]
        for (mod in modules) {
            def moduleName = mod  // capture for closure
            parallelStages["Test ${moduleName}"] = {
                node('linux') {
                    checkout scm
                    sh "mvn test -pl ${moduleName}"
                    junit "${moduleName}/target/surefire-reports/*.xml"
                }
            }
        }
        parallel parallelStages
    }

    stage('Deploy') {
        if (env.BRANCH_NAME == 'main') {
            input message: 'Deploy to production?'
            sh './deploy.sh prod'
        } else {
            echo "Skipping deploy for branch ${env.BRANCH_NAME}"
        }
    }
}
```

### When to Use Scripted vs Declarative

| Use Case | Recommendation |
|---|---|
| Standard build/test/deploy | Declarative |
| Dynamic stage generation from list/map | Scripted |
| Complex try/catch with custom error handling | Scripted (or `script {}` blocks) |
| Matrix builds with exclusions | Declarative `matrix` |
| New pipelines (default choice) | Declarative |

---

