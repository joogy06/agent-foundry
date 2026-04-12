# Shared Libraries, Multibranch, Pipeline Patterns, and Job DSL

Reference file for the `jenkins` skill. Covers shared libraries, multibranch pipelines, advanced pipeline patterns (parallel, matrix, docker agents), and Job DSL.

## 10. Shared Libraries

### Directory Structure

```
(root)
  vars/
    myStep.groovy          # custom pipeline step — call() method
    myStep.txt             # help text (shown in Pipeline Syntax)
  src/
    com/example/
      BuildUtils.groovy    # Groovy classes (full OOP)
  resources/
    templates/
      Dockerfile.template  # text resources (loaded via libraryResource)
```

### Configuring Shared Libraries

**Global:** Manage Jenkins > System > Global Pipeline Libraries.

**Folder-scoped:** Configure on a folder item for team-specific libraries.

```yaml
# JCasC
unclassified:
  globalLibraries:
    libraries:
      - name: "my-shared-lib"
        defaultVersion: "main"
        implicit: false
        retriever:
          modernSCM:
            scm:
              git:
                remote: "https://github.com/myorg/jenkins-shared-lib.git"
                credentialsId: "github-creds"
```

### Custom Steps (vars/)

`vars/buildDockerImage.groovy`:

```groovy
def call(Map config = [:]) {
    def imageName = config.image ?: error("image parameter required")
    def tag = config.tag ?: env.BUILD_NUMBER
    def registry = config.registry ?: 'registry.example.com'
    def dockerfile = config.dockerfile ?: 'Dockerfile'

    withCredentials([usernamePassword(
        credentialsId: config.credentialsId ?: 'docker-registry-creds',
        usernameVariable: 'REG_USER',
        passwordVariable: 'REG_PASS'
    )]) {
        sh """
            docker build -t ${registry}/${imageName}:${tag} -f ${dockerfile} .
            echo \$REG_PASS | docker login -u \$REG_USER --password-stdin ${registry}
            docker push ${registry}/${imageName}:${tag}
        """
    }

    return "${registry}/${imageName}:${tag}"
}
```

Usage in Jenkinsfile:

```groovy
@Library('my-shared-lib') _

pipeline {
    agent { label 'docker' }
    stages {
        stage('Build & Push') {
            steps {
                script {
                    def fullTag = buildDockerImage(
                        image: 'my-app',
                        tag: "${BUILD_NUMBER}",
                        credentialsId: 'docker-registry-creds'
                    )
                    echo "Pushed: ${fullTag}"
                }
            }
        }
    }
}
```

### Using Classes from src/

`src/com/example/BuildUtils.groovy`:

```groovy
package com.example

class BuildUtils implements Serializable {
    def steps

    BuildUtils(steps) {
        this.steps = steps
    }

    def notifySlack(String channel, String message, String color = 'good') {
        steps.slackSend(channel: channel, color: color, message: message)
    }

    def getGitInfo() {
        return [
            commit: steps.sh(script: 'git rev-parse HEAD', returnStdout: true).trim(),
            branch: steps.env.BRANCH_NAME,
            author: steps.sh(script: 'git log -1 --format="%an"', returnStdout: true).trim()
        ]
    }
}
```

```groovy
// In Jenkinsfile
@Library('my-shared-lib') _
import com.example.BuildUtils

node {
    def utils = new BuildUtils(this)
    def gitInfo = utils.getGitInfo()
    echo "Building commit ${gitInfo.commit} by ${gitInfo.author}"
}
```

### Loading Resources

```groovy
// vars/generateDockerfile.groovy
def call(Map config) {
    def template = libraryResource('templates/Dockerfile.template')
    def rendered = template
        .replace('{{BASE_IMAGE}}', config.baseImage)
        .replace('{{APP_PORT}}', config.port.toString())
    writeFile(file: 'Dockerfile', text: rendered)
}
```

### Versioning

```groovy
// Pin to a specific branch or tag
@Library('my-shared-lib@v2.1.0') _

// Use a feature branch
@Library('my-shared-lib@feature/new-deploy') _
```

---

## 11. Multibranch Pipelines

### Configuration

New Item > Multibranch Pipeline:

```
Branch Sources:
  Git:
    Project Repository: https://github.com/myorg/my-app.git
    Credentials: github-creds
    Behaviours:
      - Discover branches (all branches / only branches with PRs)
      - Discover pull requests from origin
      - Discover pull requests from forks (trust: contributors)
      - Filter by name (regex): (main|develop|feature/.*)

Build Configuration:
  Script Path: Jenkinsfile    # path in repo root

Scan Triggers:
  Periodically if not otherwise run: 1 minute
  # Or use webhooks (preferred)

Orphaned Item Strategy:
  Discard old items: days=30, max=50
```

### Webhook Triggers

**GitHub:** Repository Settings > Webhooks > Add:
```
Payload URL: https://jenkins.example.com/github-webhook/
Content type: application/json
Events: Push, Pull request
```

**GitLab:** Project > Settings > Webhooks:
```
URL: https://jenkins.example.com/project/my-multibranch-job
Trigger: Push events, Merge request events
```

**Bitbucket:** Repository Settings > Webhooks:
```
URL: https://jenkins.example.com/bitbucket-hook/
Events: Repository push
```

### Organization Folders

Automatically discover and create multibranch pipeline jobs for every repository in a GitHub/GitLab organization:

New Item > GitHub Organization / GitLab Group:

```
GitHub Organization:
  API endpoint: https://api.github.com
  Credentials: github-org-token
  Owner: myorg
  Behaviours:
    - Discover repositories (all / matching regex)
    - Repository name filter: (app-.*|service-.*)
```

### Branch-Specific Pipeline Logic

```groovy
pipeline {
    agent any
    stages {
        stage('Build') {
            steps {
                sh 'mvn clean package'
            }
        }
        stage('Deploy to Dev') {
            when { branch 'develop' }
            steps {
                sh './deploy.sh dev'
            }
        }
        stage('Deploy to Staging') {
            when { branch 'main' }
            steps {
                sh './deploy.sh staging'
            }
        }
        stage('Deploy PR Preview') {
            when { changeRequest() }
            steps {
                sh "./deploy-preview.sh pr-${env.CHANGE_ID}"
            }
        }
    }
}
```

---

## 12. Pipeline Patterns

### Docker-Based Build

```groovy
pipeline {
    agent { label 'docker' }
    stages {
        stage('Build in Container') {
            steps {
                script {
                    docker.image('node:20-alpine').inside('-v npm-cache:/root/.npm') {
                        sh 'npm ci'
                        sh 'npm run build'
                        sh 'npm test'
                    }
                }
            }
        }
        stage('Build Docker Image') {
            steps {
                script {
                    def image = docker.build("myapp:${BUILD_NUMBER}")
                    docker.withRegistry('https://registry.example.com', 'docker-registry-creds') {
                        image.push()
                        image.push('latest')
                    }
                }
            }
        }
    }
}
```

### Artifact Archiving and Test Reporting

```groovy
post {
    always {
        // Test reports
        junit allowEmptyResults: true, testResults: '**/target/surefire-reports/*.xml'
        jacoco(execPattern: '**/target/jacoco.exec',
               classPattern: '**/target/classes',
               sourcePattern: '**/src/main/java')

        // Archive artifacts
        archiveArtifacts artifacts: 'target/*.jar', fingerprint: true

        // Publish HTML report
        publishHTML(target: [
            reportName: 'Test Report',
            reportDir: 'target/site',
            reportFiles: 'index.html',
            keepAll: true
        ])
    }
}
```

### Multi-Environment Deployment with Approval Gates

```groovy
pipeline {
    agent any
    stages {
        stage('Build') {
            steps { sh 'mvn clean package' }
        }
        stage('Deploy Dev') {
            steps { sh './deploy.sh dev' }
        }
        stage('Integration Tests') {
            steps { sh './run-integration-tests.sh dev' }
        }
        stage('Approve Staging') {
            steps {
                input message: 'Deploy to staging?',
                      submitter: 'qa-team,release-managers',
                      parameters: [
                          string(name: 'REASON', defaultValue: '', description: 'Approval reason')
                      ]
            }
        }
        stage('Deploy Staging') {
            steps { sh './deploy.sh staging' }
        }
        stage('Approve Production') {
            steps {
                timeout(time: 24, unit: 'HOURS') {
                    input message: 'Deploy to production?',
                          submitter: 'release-managers',
                          parameters: [
                              string(name: 'CHANGE_TICKET', description: 'Change ticket number')
                          ]
                }
            }
        }
        stage('Deploy Production') {
            steps {
                sh './deploy.sh prod'
            }
            post {
                failure {
                    sh './rollback.sh prod'
                    slackSend(channel: '#ops', color: 'danger',
                              message: "PROD DEPLOY FAILED — rollback triggered: ${BUILD_URL}")
                }
            }
        }
    }
}
```

### Parallel Testing Across Multiple Agents

```groovy
pipeline {
    agent none
    stages {
        stage('Parallel Tests') {
            parallel {
                stage('Unit Tests') {
                    agent { label 'linux' }
                    steps {
                        sh 'mvn test -Punit'
                    }
                    post { always { junit '**/surefire-reports/*.xml' } }
                }
                stage('E2E Tests') {
                    agent { label 'linux && chrome' }
                    steps {
                        sh 'mvn test -Pe2e'
                    }
                    post { always { junit '**/failsafe-reports/*.xml' } }
                }
                stage('Security Scan') {
                    agent { label 'linux' }
                    steps {
                        sh 'trivy image myapp:${BUILD_NUMBER}'
                    }
                }
            }
        }
    }
}
```

### Rollback Pattern

```groovy
// vars/deployWithRollback.groovy (shared library)
def call(Map config) {
    def environment = config.environment
    def version = config.version
    def previousVersion = config.previousVersion

    try {
        sh "./deploy.sh ${environment} ${version}"
        sh "./health-check.sh ${environment}"
        echo "Deployment successful: ${version} to ${environment}"
    } catch (Exception e) {
        echo "Deployment failed, rolling back to ${previousVersion}"
        sh "./deploy.sh ${environment} ${previousVersion}"
        sh "./health-check.sh ${environment}"
        error("Deployment of ${version} to ${environment} failed. Rolled back to ${previousVersion}.")
    }
}
```

### GitOps Integration

```groovy
stage('Update GitOps Repo') {
    steps {
        withCredentials([usernamePassword(
            credentialsId: 'gitops-creds',
            usernameVariable: 'GIT_USER',
            passwordVariable: 'GIT_TOKEN'
        )]) {
            sh """
                git clone https://\$GIT_USER:\$GIT_TOKEN@github.com/myorg/gitops-config.git
                cd gitops-config
                sed -i 's|image:.*|image: registry.example.com/myapp:${IMAGE_TAG}|' \
                    environments/production/deployment.yaml
                git add .
                git commit -m "Update myapp to ${IMAGE_TAG}"
                git push
            """
        }
    }
}
```

---

## 13. Job DSL

### Seed Job Configuration

Create a freestyle or pipeline job that runs DSL scripts to generate other jobs.

```groovy
// Seed job — Pipeline
pipeline {
    agent any
    stages {
        stage('Generate Jobs') {
            steps {
                checkout scm
                jobDsl(
                    targets: 'jobs/**/*.groovy',
                    removedJobAction: 'DISABLE',
                    removedViewAction: 'DELETE',
                    removedConfigFilesAction: 'IGNORE',
                    lookupStrategy: 'SEED_JOB'
                )
            }
        }
    }
}
```

### DSL Script Examples

`jobs/microservices.groovy`:

```groovy
def services = ['auth-service', 'api-gateway', 'user-service', 'order-service']
def environments = ['dev', 'staging', 'prod']

// Create a multibranch pipeline for each service
services.each { service ->
    multibranchPipelineJob("microservices/${service}") {
        displayName(service.replaceAll('-', ' ').capitalize())
        description("CI/CD pipeline for ${service}")

        branchSources {
            github {
                id("${service}-github")
                repoOwner('myorg')
                repository(service)
                scanCredentialsId('github-creds')
                buildForkPRMerge(true)
            }
        }

        orphanedItemStrategy {
            discardOldItems {
                numToKeep(30)
                daysToKeep(60)
            }
        }

        triggers {
            periodicFolderTrigger {
                interval('2m')
            }
        }
    }
}

// Create deployment jobs for each environment
environments.each { env ->
    pipelineJob("deploy/${env}-deploy") {
        displayName("Deploy to ${env.capitalize()}")
        description("Deployment pipeline for ${env} environment")

        parameters {
            choiceParam('SERVICE', services, 'Service to deploy')
            stringParam('VERSION', 'latest', 'Version/tag to deploy')
        }

        definition {
            cpsScm {
                scm {
                    git {
                        remote {
                            url('https://github.com/myorg/deploy-pipelines.git')
                            credentials('github-creds')
                        }
                        branch('main')
                    }
                }
                scriptPath("pipelines/${env}-deploy.Jenkinsfile")
            }
        }
    }
}

// Create a dashboard view
listView('Microservices') {
    description('All microservice pipelines')
    jobs {
        regex('microservices/.*')
    }
    columns {
        status()
        weather()
        name()
        lastSuccess()
        lastFailure()
        lastDuration()
        buildButton()
    }
}
```

### Template Pattern

`jobs/templates/standardPipeline.groovy`:

```groovy
def createStandardPipeline(Map config) {
    def jobName = config.name
    def repo = config.repo
    def jenkinsfilePath = config.jenkinsfile ?: 'Jenkinsfile'

    multibranchPipelineJob(jobName) {
        displayName(config.displayName ?: jobName)
        description(config.description ?: "Pipeline for ${jobName}")

        branchSources {
            github {
                id("${jobName}-src")
                repoOwner(config.org ?: 'myorg')
                repository(repo)
                scanCredentialsId('github-creds')
            }
        }

        factory {
            workflowBranchProjectFactory {
                scriptPath(jenkinsfilePath)
            }
        }

        orphanedItemStrategy {
            discardOldItems { numToKeep(20) }
        }
    }
}

// Usage
createStandardPipeline(
    name: 'services/payment-api',
    repo: 'payment-api',
    displayName: 'Payment API',
    description: 'Payment processing microservice'
)

createStandardPipeline(
    name: 'services/notification-api',
    repo: 'notification-api',
    displayName: 'Notification API'
)
```

---

## Related Skills

| Topic | Skill |
|---|---|
| Docker agent patterns, Dockerfile best practices | `docker-admin`, `docker-cicd` |
| Docker networking, storage, security | `docker-networking`, `docker-storage`, `docker-security` |
| Docker Compose for local Jenkins stacks | `docker-compose-patterns` |
| Reverse proxy (Nginx/Apache) for Jenkins | `rhel-web-servers`, `ubuntu-web-servers` |
| RHEL system admin (systemd, firewalld, SELinux) | `rhel-server-admin` |
| Kubernetes cluster management | (kubernetes skill — planned) |
| LDAP/AD/SSO configuration | `windows-sso`, `linux-centrify` |
| Git workflows and branching strategies | (git skill — planned) |
| IBM WebSphere deployments from Jenkins | `ibm-websphere` |
| IBM MQ integration in pipelines | `ibm-mq` |
| BMC Control-M job scheduling alongside Jenkins | `control-m` |
