---
name: docker-cicd
description: Use when building Docker images in CI/CD pipelines — GitHub Actions Docker workflows, GitLab CI Docker builds, Jenkins Docker agents, multi-platform builds with buildx, registry authentication and push workflows, image tagging strategies (semver, git SHA, branch), layer cache optimization in CI, Docker-in-Docker vs socket mount vs daemonless builders (rootless BuildKit, Buildah; Kaniko is archived/legacy), automated image scanning in pipelines, and deployment patterns. Part of the docker-* skill family. OS-agnostic.
family: docker
disambiguation: Building images in a PIPELINE — Actions, GitLab CI, Jenkins, caching, multi-platform, registry push. Local container and Dockerfile basics are docker-fundamentals; hardening is docker-security.
---

# Docker in CI/CD Pipelines

OS-agnostic Docker CI/CD patterns. For core Docker concepts, Dockerfile patterns, and BuildKit features, see parent skill `docker-fundamentals`. For Compose-based workflows, see `docker-compose-patterns`. For image hardening and runtime security, see `docker-security`.

<HARD-RULE>
Never store registry credentials in Dockerfiles, build args, or image layers. Use CI/CD platform secrets (GitHub Actions secrets, GitLab CI variables, Jenkins credentials). Credentials baked into images or build history are extractable by anyone with image access.
</HARD-RULE>

<HARD-RULE>
Always pin action versions to full SHA in GitHub Actions, not mutable tags. Tags like `@v4` or `@latest` can be hijacked via tag reassignment. Use `@<commit-sha>` for supply-chain security. Example: `docker/build-push-action@4f58ea79222b3b9dc585cd0ca6fc9cb5c7da2c48`.
</HARD-RULE>

<HARD-RULE>
Mounting the Docker socket (`/var/run/docker.sock`) in CI gives the job full root-level control over the host Docker daemon. Any compromised build step can escape the container, read other containers' data, or pivot to the host. Prefer rootless BuildKit (`buildkitd` via `moby/buildkit:rootless`) or Buildah in untrusted environments; rootless DinD is the fallback when the job genuinely needs the `docker` CLI. Do NOT reach for Kaniko in new pipelines — Google archived it in June 2025 (see Section 8 legacy note).
</HARD-RULE>

---

## 1. GitHub Actions — Build and Push

### Basic Build and Push to GHCR

```yaml
# .github/workflows/docker-publish.yml
name: Build and Push Docker Image

on:
  push:
    branches: [main]
    tags: ['v*']
  pull_request:
    branches: [main]

env:
  REGISTRY: ghcr.io
  IMAGE_NAME: ${{ github.repository }}

jobs:
  build:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      packages: write
      security-events: write   # for SARIF upload

    steps:
      - name: Checkout
        uses: actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683  # v4.2.2

      - name: Set up Docker Buildx
        uses: docker/setup-buildx-action@b5ca514318bd6ebac0fb2aedd5d36ec1b5c232a2  # v3.10.0

      - name: Log in to GHCR
        if: github.event_name != 'pull_request'
        uses: docker/login-action@74a5d142397b4f367a81961eba4e8cd7edddf772  # v3.4.0
        with:
          registry: ${{ env.REGISTRY }}
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}

      - name: Extract metadata (tags, labels)
        id: meta
        uses: docker/metadata-action@902fa8ec7d6ecbf8d84d538b9b233a880e428804  # v5.7.0
        with:
          images: ${{ env.REGISTRY }}/${{ env.IMAGE_NAME }}
          tags: |
            type=semver,pattern={{version}}
            type=semver,pattern={{major}}.{{minor}}
            type=sha,prefix=
            type=ref,event=branch
            type=ref,event=pr

      - name: Build and push
        uses: docker/build-push-action@4f58ea79222b3b9dc585cd0ca6fc9cb5c7da2c48  # v6.4.0
        with:
          context: .
          push: ${{ github.event_name != 'pull_request' }}
          tags: ${{ steps.meta.outputs.tags }}
          labels: ${{ steps.meta.outputs.labels }}
          cache-from: type=gha
          cache-to: type=gha,mode=max
```

### Multi-Platform Build

```yaml
      - name: Set up QEMU
        uses: docker/setup-qemu-action@29109295f81e9208d7d86ff1c6c12d2833863392  # v3.6.0

      - name: Set up Docker Buildx
        uses: docker/setup-buildx-action@b5ca514318bd6ebac0fb2aedd5d36ec1b5c232a2  # v3.10.0

      - name: Build and push multi-platform
        uses: docker/build-push-action@4f58ea79222b3b9dc585cd0ca6fc9cb5c7da2c48  # v6.4.0
        with:
          context: .
          platforms: linux/amd64,linux/arm64
          push: true
          tags: ${{ steps.meta.outputs.tags }}
          cache-from: type=gha
          cache-to: type=gha,mode=max
```

### Matrix Build for Multiple Images

```yaml
jobs:
  build:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        include:
          - image: api
            dockerfile: ./services/api/Dockerfile
            context: ./services/api
          - image: worker
            dockerfile: ./services/worker/Dockerfile
            context: ./services/worker
          - image: frontend
            dockerfile: ./web/Dockerfile
            context: ./web
    steps:
      - uses: actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683  # v4.2.2
      - uses: docker/setup-buildx-action@b5ca514318bd6ebac0fb2aedd5d36ec1b5c232a2  # v3.10.0
      - uses: docker/login-action@74a5d142397b4f367a81961eba4e8cd7edddf772  # v3.4.0
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}
      - uses: docker/build-push-action@4f58ea79222b3b9dc585cd0ca6fc9cb5c7da2c48  # v6.4.0
        with:
          context: ${{ matrix.context }}
          file: ${{ matrix.dockerfile }}
          push: true
          tags: ghcr.io/${{ github.repository }}/${{ matrix.image }}:${{ github.sha }}
          cache-from: type=gha,scope=${{ matrix.image }}
          cache-to: type=gha,scope=${{ matrix.image }},mode=max
```

### Security Scanning Step (Trivy + SARIF)

```yaml
      - name: Run Trivy vulnerability scanner
        uses: aquasecurity/trivy-action@18f2510ee396bbf400402947e7f3a8f37e4e6e04  # v0.28.0
        with:
          image-ref: ${{ env.REGISTRY }}/${{ env.IMAGE_NAME }}:${{ github.sha }}
          format: sarif
          output: trivy-results.sarif
          severity: CRITICAL,HIGH
          exit-code: '1'            # fail the build on HIGH/CRITICAL

      - name: Upload Trivy scan to GitHub Security tab
        uses: github/codeql-action/upload-sarif@v3
        if: always()
        with:
          sarif_file: trivy-results.sarif
```

---

## 2. GitLab CI — Docker Build

### Basic Build with DinD

```yaml
# .gitlab-ci.yml
stages:
  - build
  - scan
  - deploy

variables:
  DOCKER_TLS_CERTDIR: "/certs"
  IMAGE_TAG: $CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA

build:
  stage: build
  image: docker:27
  services:
    - docker:27-dind
  before_script:
    - docker login -u $CI_REGISTRY_USER -p $CI_REGISTRY_PASSWORD $CI_REGISTRY
  script:
    - docker build
        --cache-from $CI_REGISTRY_IMAGE:latest
        --tag $IMAGE_TAG
        --tag $CI_REGISTRY_IMAGE:latest
        --build-arg BUILDKIT_INLINE_CACHE=1
        .
    - docker push $IMAGE_TAG
    - docker push $CI_REGISTRY_IMAGE:latest
  rules:
    - if: $CI_COMMIT_BRANCH == "main"

scan:
  stage: scan
  image:
    name: aquasec/trivy:latest
    entrypoint: [""]
  script:
    - trivy image --exit-code 1 --severity HIGH,CRITICAL $IMAGE_TAG
  allow_failure: true
```

### Rootless BuildKit Alternative (No Docker Daemon, No Privileged)

GitLab's recommended daemonless build path (replaces the removed Kaniko docs; syntax verified against GitLab docs 2026-06).

```yaml
build-rootless:
  stage: build
  image:
    name: moby/buildkit:rootless
    entrypoint: [""]
  variables:
    BUILDKITD_FLAGS: --oci-worker-no-process-sandbox
  before_script:
    - mkdir -p ~/.docker
    - echo "{\"auths\":{\"$CI_REGISTRY\":{\"username\":\"$CI_REGISTRY_USER\",\"password\":\"$CI_REGISTRY_PASSWORD\"}}}" > ~/.docker/config.json
  script:
    - |
      buildctl-daemonless.sh build \
        --frontend dockerfile.v0 \
        --local context=$CI_PROJECT_DIR \
        --local dockerfile=$CI_PROJECT_DIR \
        --output type=image,name=$CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA,push=true \
        --export-cache type=registry,ref=$CI_REGISTRY_IMAGE/cache \
        --import-cache type=registry,ref=$CI_REGISTRY_IMAGE/cache
  rules:
    - if: $CI_COMMIT_BRANCH == "main"
```

### Buildah Alternative (Daemonless, Podman Family)

```yaml
build-buildah:
  stage: build
  image: quay.io/buildah/stable
  variables:
    STORAGE_DRIVER: vfs        # avoids needing fuse/overlay privileges in CI
    BUILDAH_FORMAT: docker     # emit Docker-format images, not OCI, if consumers require it
  before_script:
    - echo "$CI_REGISTRY_PASSWORD" | buildah login -u "$CI_REGISTRY_USER" --password-stdin $CI_REGISTRY
  script:
    - buildah build -t $CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA .
    - buildah push $CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA
  rules:
    - if: $CI_COMMIT_BRANCH == "main"
```

> **Legacy — Kaniko (archived June 2025).** Google archived `GoogleContainerTools/kaniko` on 2025-06-03 (repo read-only, maintainers retired the project), and GitLab removed its Kaniko docs in favor of BuildKit/Buildah. Do not start new pipelines on `gcr.io/kaniko-project/executor` — it no longer receives security patches. If a pipeline is already committed to Kaniko, switch to the Chainguard-maintained fork (`chainguard-dev/kaniko` on GitHub) as a stopgap and plan migration to rootless BuildKit or Buildah.

### GitLab Auto Deploy with Tagging

```yaml
deploy-staging:
  stage: deploy
  image: docker:27
  services:
    - docker:27-dind
  before_script:
    - docker login -u $CI_REGISTRY_USER -p $CI_REGISTRY_PASSWORD $CI_REGISTRY
  script:
    - docker pull $CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA
    - docker tag $CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA $CI_REGISTRY_IMAGE:staging
    - docker push $CI_REGISTRY_IMAGE:staging
  environment:
    name: staging
  rules:
    - if: $CI_COMMIT_BRANCH == "main"

deploy-production:
  stage: deploy
  image: docker:27
  services:
    - docker:27-dind
  before_script:
    - docker login -u $CI_REGISTRY_USER -p $CI_REGISTRY_PASSWORD $CI_REGISTRY
  script:
    - docker pull $CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA
    - docker tag $CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA $CI_REGISTRY_IMAGE:production
    - docker push $CI_REGISTRY_IMAGE:production
  environment:
    name: production
  rules:
    - if: $CI_COMMIT_TAG =~ /^v\d+\.\d+\.\d+$/
  when: manual
```

---

## 3. Jenkins — Docker Agent and Builds

### Jenkinsfile with Docker Build/Push

```groovy
// Jenkinsfile (Declarative Pipeline)
pipeline {
    agent any

    environment {
        REGISTRY     = 'registry.example.com'
        IMAGE_NAME   = 'myorg/myapp'
        REGISTRY_CRED = credentials('docker-registry-cred')  // Jenkins credential ID
    }

    stages {
        stage('Build') {
            steps {
                script {
                    def gitSha = sh(returnStdout: true, script: 'git rev-parse --short HEAD').trim()
                    def img = docker.build("${REGISTRY}/${IMAGE_NAME}:${gitSha}")
                    docker.withRegistry("https://${REGISTRY}", 'docker-registry-cred') {
                        img.push()
                        img.push('latest')
                    }
                }
            }
        }

        stage('Scan') {
            steps {
                sh """
                    docker run --rm \
                      -v /var/run/docker.sock:/var/run/docker.sock \
                      aquasec/trivy:latest image \
                      --exit-code 1 --severity HIGH,CRITICAL \
                      ${REGISTRY}/${IMAGE_NAME}:latest
                """
            }
        }

        stage('Deploy') {
            when { branch 'main' }
            steps {
                sh """
                    docker pull ${REGISTRY}/${IMAGE_NAME}:latest
                    docker stop myapp || true
                    docker rm myapp || true
                    docker run -d --name myapp \
                      --restart unless-stopped \
                      -p 8080:8080 \
                      ${REGISTRY}/${IMAGE_NAME}:latest
                """
            }
        }
    }

    post {
        always { sh 'docker image prune -f' }
    }
}
```

### Docker-Outside-of-Docker Pattern (Jenkins)

```groovy
// Use the host's Docker daemon by mounting the socket
// The Jenkins agent container must have Docker CLI installed
pipeline {
    agent {
        docker {
            image 'docker:27-cli'
            args '-v /var/run/docker.sock:/var/run/docker.sock'
            // WARNING: This gives the build job full host Docker access.
            // See the DinD vs Socket vs Daemonless comparison below.
        }
    }
    stages {
        stage('Build') {
            steps {
                sh 'docker build -t myapp:${BUILD_NUMBER} .'
            }
        }
    }
}
```

---

## 4. Multi-Platform Builds with buildx

### Setup and Create Builder

```bash
# Install QEMU emulation for cross-platform builds
docker run --privileged --rm tonistiigi/binfmt --install all

# Create a new buildx builder instance
docker buildx create --name multiplatform --driver docker-container --bootstrap --use

# Verify available platforms
docker buildx inspect --bootstrap
# Platforms: linux/amd64, linux/arm64, linux/arm/v7, linux/386, ...

# List builders
docker buildx ls
```

### Build Multi-Platform Image

```bash
# Build and push (multi-platform requires push or local export)
docker buildx build \
  --platform linux/amd64,linux/arm64 \
  --tag registry.example.com/myapp:v1.2.3 \
  --push \
  .

# Build and load into local daemon (single platform only)
docker buildx build \
  --platform linux/amd64 \
  --tag myapp:v1.2.3 \
  --load \
  .

# Build with cache backend
docker buildx build \
  --platform linux/amd64,linux/arm64 \
  --tag registry.example.com/myapp:v1.2.3 \
  --cache-from type=registry,ref=registry.example.com/myapp:cache \
  --cache-to type=registry,ref=registry.example.com/myapp:cache,mode=max \
  --push \
  .
```

### Native Cross-Compilation (No Emulation Needed)

```dockerfile
# syntax=docker/dockerfile:1
FROM --platform=$BUILDPLATFORM golang:1.23-alpine AS builder
ARG TARGETPLATFORM TARGETOS TARGETARCH

WORKDIR /app
COPY go.mod go.sum ./
RUN go mod download
COPY . .

# Cross-compile natively — much faster than QEMU emulation
RUN CGO_ENABLED=0 GOOS=${TARGETOS} GOARCH=${TARGETARCH} \
    go build -ldflags="-s -w" -o /server .

FROM scratch
COPY --from=builder /etc/ssl/certs/ca-certificates.crt /etc/ssl/certs/
COPY --from=builder /server /server
ENTRYPOINT ["/server"]
```

### buildx Cache Backends

```bash
# GitHub Actions cache backend
docker buildx build \
  --cache-from type=gha \
  --cache-to type=gha,mode=max \
  --push -t myapp:latest .

# Registry cache backend (works in any CI)
docker buildx build \
  --cache-from type=registry,ref=registry.example.com/myapp:cache \
  --cache-to type=registry,ref=registry.example.com/myapp:cache,mode=max \
  --push -t myapp:latest .

# Local directory cache (useful for self-hosted runners)
docker buildx build \
  --cache-from type=local,src=/tmp/.buildx-cache \
  --cache-to type=local,dest=/tmp/.buildx-cache-new,mode=max \
  --push -t myapp:latest .

# S3 cache backend (requires BuildKit 0.12+)
docker buildx build \
  --cache-from type=s3,region=us-east-1,bucket=my-cache-bucket,name=myapp \
  --cache-to type=s3,region=us-east-1,bucket=my-cache-bucket,name=myapp,mode=max \
  --push -t myapp:latest .
```

---

## 5. Registry Workflows

### Docker Hub

```bash
# Login
echo "$DOCKERHUB_TOKEN" | docker login -u "$DOCKERHUB_USERNAME" --password-stdin

# Tag and push
docker tag myapp:latest dockerhubuser/myapp:v1.2.3
docker push dockerhubuser/myapp:v1.2.3
```

### GitHub Container Registry (GHCR)

```bash
# Login with PAT or GITHUB_TOKEN (in Actions)
echo "$GITHUB_TOKEN" | docker login ghcr.io -u "$GITHUB_ACTOR" --password-stdin

# Images are scoped to repo or user
docker tag myapp:latest ghcr.io/myorg/myapp:v1.2.3
docker push ghcr.io/myorg/myapp:v1.2.3
```

### AWS ECR

```bash
# Login (valid for 12 hours)
aws ecr get-login-password --region us-east-1 | \
  docker login --username AWS --password-stdin 123456789012.dkr.ecr.us-east-1.amazonaws.com

# Create repository (if first push)
aws ecr create-repository --repository-name myapp --image-scanning-configuration scanOnPush=true

# Push
docker tag myapp:latest 123456789012.dkr.ecr.us-east-1.amazonaws.com/myapp:v1.2.3
docker push 123456789012.dkr.ecr.us-east-1.amazonaws.com/myapp:v1.2.3

# Lifecycle policy — keep only last 10 untagged images
aws ecr put-lifecycle-policy --repository-name myapp --lifecycle-policy-text '{
  "rules": [
    {
      "rulePriority": 1,
      "description": "Remove untagged images older than 7 days",
      "selection": {
        "tagStatus": "untagged",
        "countType": "sinceImagePushed",
        "countUnit": "days",
        "countNumber": 7
      },
      "action": { "type": "expire" }
    }
  ]
}'
```

### Google Artifact Registry (GCR successor)

```bash
# Authenticate with gcloud
gcloud auth configure-docker us-docker.pkg.dev

# Tag and push
docker tag myapp:latest us-docker.pkg.dev/my-project/my-repo/myapp:v1.2.3
docker push us-docker.pkg.dev/my-project/my-repo/myapp:v1.2.3

# Cleanup policy (via gcloud)
gcloud artifacts repositories set-cleanup-policies my-repo \
  --project=my-project \
  --location=us \
  --policy=cleanup-policy.json
```

### Self-Hosted Registry

```bash
# Deploy a self-hosted registry
docker run -d -p 5000:5000 --restart=always --name registry \
  -v /opt/registry-data:/var/lib/registry \
  registry:2

# Tag and push to self-hosted
docker tag myapp:latest localhost:5000/myapp:v1.2.3
docker push localhost:5000/myapp:v1.2.3

# List catalog
curl -s http://localhost:5000/v2/_catalog | jq
```

---

## 6. Image Tagging Strategies

### Recommended Tagging Scheme

```bash
# Semantic version from git tag
VERSION=$(git describe --tags --abbrev=0 2>/dev/null || echo "0.0.0")
docker tag myapp:build "myapp:${VERSION}"

# Git SHA for exact traceability
SHA=$(git rev-parse --short=8 HEAD)
docker tag myapp:build "myapp:sha-${SHA}"

# Branch name (sanitized for Docker tag rules)
BRANCH=$(git rev-parse --abbrev-ref HEAD | sed 's/[^a-zA-Z0-9._-]/-/g')
docker tag myapp:build "myapp:${BRANCH}"

# Timestamp for uniqueness
TIMESTAMP=$(date +%Y%m%d%H%M%S)
docker tag myapp:build "myapp:${VERSION}-${TIMESTAMP}"
```

### Tag Promotion (Staging to Production)

```bash
# Step 1: Build once, tag with SHA
docker build -t registry.example.com/myapp:sha-abc12345 .
docker push registry.example.com/myapp:sha-abc12345

# Step 2: Promote to staging
docker tag registry.example.com/myapp:sha-abc12345 registry.example.com/myapp:staging
docker push registry.example.com/myapp:staging

# Step 3: After validation, promote to production (same image, new tag)
docker tag registry.example.com/myapp:sha-abc12345 registry.example.com/myapp:production
docker tag registry.example.com/myapp:sha-abc12345 registry.example.com/myapp:v1.2.3
docker push registry.example.com/myapp:production
docker push registry.example.com/myapp:v1.2.3
```

### Tagging Best Practices

| Pattern | Example | Use Case |
|---|---|---|
| Semver | `myapp:1.2.3` | Releases, external consumers |
| Semver major.minor | `myapp:1.2` | Auto-patch-update consumers |
| Git SHA | `myapp:sha-abc1234` | Exact commit traceability |
| Branch | `myapp:main`, `myapp:feature-x` | Dev/preview environments |
| Environment | `myapp:staging`, `myapp:production` | Deployment targets |
| Timestamp | `myapp:20260324-143022` | Uniqueness guarantee |
| Immutable combo | `myapp:1.2.3-sha-abc1234` | Audit-friendly, traceable |

**`latest` tag policy**: Avoid relying on `latest` in production. It is mutable, ambiguous, and not pulled when a local copy exists. Use explicit version tags for deployments. Only push `latest` as a convenience alias alongside a versioned tag.

---

## 7. Layer Cache Optimization in CI

### GitHub Actions Cache (GHA Backend)

```yaml
# Fastest option for GitHub-hosted runners
- uses: docker/build-push-action@4f58ea79222b3b9dc585cd0ca6fc9cb5c7da2c48
  with:
    context: .
    push: true
    tags: myapp:latest
    cache-from: type=gha
    cache-to: type=gha,mode=max
# mode=max caches all layers (including intermediate), not just final image layers
```

### Registry Cache (Cross-CI Compatible)

```yaml
# Works in any CI system — stores cache as an image in the registry
- uses: docker/build-push-action@4f58ea79222b3b9dc585cd0ca6fc9cb5c7da2c48
  with:
    context: .
    push: true
    tags: ghcr.io/myorg/myapp:latest
    cache-from: type=registry,ref=ghcr.io/myorg/myapp:cache
    cache-to: type=registry,ref=ghcr.io/myorg/myapp:cache,mode=max
```

### Inline Cache (Simplest, Limited)

```bash
# Embed cache metadata in the image itself
docker build \
  --build-arg BUILDKIT_INLINE_CACHE=1 \
  --tag registry.example.com/myapp:latest \
  .
docker push registry.example.com/myapp:latest

# On next build, pull previous image as cache source
docker build \
  --cache-from registry.example.com/myapp:latest \
  --tag registry.example.com/myapp:latest \
  .
# Limitation: only caches final-stage layers, not intermediate build stages
```

### Local Cache with Move Workaround (GitHub Actions)

```yaml
# Avoid ever-growing cache by swapping directories
- name: Build
  uses: docker/build-push-action@4f58ea79222b3b9dc585cd0ca6fc9cb5c7da2c48
  with:
    context: .
    push: true
    tags: myapp:latest
    cache-from: type=local,src=/tmp/.buildx-cache
    cache-to: type=local,dest=/tmp/.buildx-cache-new,mode=max

- name: Rotate cache
  run: |
    rm -rf /tmp/.buildx-cache
    mv /tmp/.buildx-cache-new /tmp/.buildx-cache
```

### Cache Strategy Decision Table

| Backend | Speed | Cross-runner | Setup | Best For |
|---|---|---|---|---|
| `type=gha` | Fast | Yes (same repo) | None | GitHub Actions (default choice) |
| `type=registry` | Medium | Yes (any CI) | Registry access | GitLab CI, Jenkins, multi-CI |
| `type=local` | Fastest | No (same runner) | Directory path | Self-hosted runners |
| `type=s3` | Medium | Yes (any CI) | S3 bucket + creds | AWS-centric pipelines |
| Inline | Slow | Yes (any CI) | None | Simple setups, single-stage |

---

## 8. DinD vs Socket Mount vs Daemonless (Rootless BuildKit / Buildah)

### Comparison Table

| Aspect | Docker-in-Docker (DinD) | Socket Mount | Rootless BuildKit | Buildah |
|---|---|---|---|---|
| **How it works** | Runs a full Docker daemon inside a container | Mounts host Docker socket into build container | `buildkitd` + `buildctl` in userspace, no Docker daemon | Daemonless OCI/Docker image builder in userspace |
| **Requires privileged** | Yes (`--privileged`) | No | No (rootless mode) | No (rootless mode) |
| **Layer cache** | Lost between runs (unless external cache) | Shared with host daemon | Registry / local / GHA / S3 cache backends | Registry or local storage cache |
| **Security risk** | Container escape via privileged | Full host daemon access | Low — no daemon socket, runs unprivileged | Low — no daemon socket, runs unprivileged |
| **Build speed** | Moderate | Fast (uses host cache) | Fast (full BuildKit engine) | Moderate (vfs storage is slow; overlay needs fuse) |
| **Multi-stage support** | Full | Full | Full | Full |
| **Multi-platform** | Yes (buildx) | Yes (buildx) | Yes (QEMU or native workers) | Yes (`--platform` + `buildah manifest`) |
| **Best for** | Isolated CI jobs that need the `docker` CLI | Jenkins, trusted environments | Kubernetes CI, untrusted environments, GitLab CI | Podman/RHEL/OpenShift-aligned shops, untrusted environments |

> **Kaniko (legacy — archived June 2025).** Kaniko used to be the standard daemonless answer in this comparison. Google archived `GoogleContainerTools/kaniko` on 2025-06-03 — the repo is read-only and the maintainers retired it. GitLab removed its Kaniko documentation and recommends BuildKit (rootless) or Buildah instead. A Chainguard-maintained fork (`chainguard-dev/kaniko`) exists for teams already committed to Kaniko, but new pipelines should use rootless BuildKit or Buildah.

### Docker-in-Docker (DinD)

```yaml
# GitLab CI example
build:
  image: docker:27
  services:
    - docker:27-dind
  variables:
    DOCKER_TLS_CERTDIR: "/certs"
    DOCKER_HOST: tcp://docker:2376
    DOCKER_TLS_VERIFY: "1"
    DOCKER_CERT_PATH: "/certs/client"
  script:
    - docker build -t myapp .
```

### Rootless DinD (Improved Security)

```yaml
# GitLab CI with rootless DinD — no --privileged on the host
build:
  image: docker:27
  services:
    - name: docker:27-dind-rootless
      command: ["--storage-driver", "fuse-overlayfs"]
  variables:
    DOCKER_HOST: tcp://docker:2375
    DOCKER_TLS_CERTDIR: ""
  script:
    - docker build -t myapp .
```

### Socket Mount

```bash
# Bind-mount the host Docker socket
docker run --rm \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v $(pwd):/workspace \
  -w /workspace \
  docker:27-cli \
  docker build -t myapp .

# WARNING: Any process in this container can run arbitrary Docker commands
# on the host, including accessing other containers, volumes, and networks.
```

### Rootless BuildKit (Daemonless)

```bash
# One-shot daemonless build — buildctl-daemonless.sh starts buildkitd for the
# duration of the build (works in any container environment, e.g. Kubernetes pod).
docker run --rm \
  --security-opt seccomp=unconfined --security-opt apparmor=unconfined \
  -e BUILDKITD_FLAGS=--oci-worker-no-process-sandbox \
  -v $(pwd):/workspace \
  -v ~/.docker/config.json:/home/user/.docker/config.json:ro \
  moby/buildkit:rootless \
  buildctl-daemonless.sh build \
    --frontend dockerfile.v0 \
    --local context=/workspace \
    --local dockerfile=/workspace \
    --output type=image,name=registry.example.com/myapp:latest,push=true \
    --export-cache type=registry,ref=registry.example.com/myapp/cache \
    --import-cache type=registry,ref=registry.example.com/myapp/cache
```

### Buildah (Daemonless)

```bash
# Build with Buildah in a container — vfs storage avoids fuse/overlay privileges
docker run --rm \
  -v $(pwd):/workspace -w /workspace \
  -e STORAGE_DRIVER=vfs -e BUILDAH_FORMAT=docker \
  quay.io/buildah/stable \
  sh -c 'buildah build -t registry.example.com/myapp:latest . &&
         buildah push registry.example.com/myapp:latest'
# Authenticate first with: buildah login registry.example.com
# (or mount an existing containers/auth.json)
```

### Kaniko (LEGACY — archived June 2025, do not adopt)

`GoogleContainerTools/kaniko` was archived 2025-06-03 (read-only, unmaintained, no security patches). Only relevant if you inherit an existing Kaniko pipeline: point it at the Chainguard fork (`chainguard-dev/kaniko`) as a stopgap, then migrate to rootless BuildKit or Buildah using the GitLab examples in Section 2.

### When to Use Each

- **Rootless BuildKit**: Kubernetes-based CI (Tekton, Argo Workflows), environments where privileged containers are prohibited, security-sensitive pipelines, GitLab CI daemonless builds. The default replacement for Kaniko.
- **Buildah**: Podman-aligned environments (RHEL, OpenShift), pipelines that also use `skopeo`/`podman`, multi-arch manifest workflows, untrusted environments.
- **DinD**: GitLab CI jobs that genuinely need the `docker` CLI (compose-based integration tests, testcontainers), isolated builds where each job needs a clean daemon. Prefer the rootless DinD variant.
- **Socket Mount**: Jenkins (Docker-Outside-of-Docker pattern), trusted CI environments where build speed matters, local dev CI simulation. Never in untrusted environments (see HARD-RULE).
- **Kaniko**: legacy pipelines only — archived June 2025; migrate.

---

## 9. Automated Scanning in Pipelines

### Trivy (Recommended for Most Pipelines)

```bash
# Scan a local image
trivy image --severity HIGH,CRITICAL --exit-code 1 myapp:latest

# Scan and output SARIF for GitHub Security tab
trivy image --format sarif --output trivy.sarif myapp:latest

# Scan a remote image (no docker pull needed)
trivy image --severity CRITICAL registry.example.com/myapp:v1.2.3

# Scan with ignore file for accepted CVEs
trivy image --ignorefile .trivyignore --exit-code 1 myapp:latest

# .trivyignore format:
# CVE-2024-12345
# CVE-2024-67890  # accepted risk — low-priority library
```

### Docker Scout (Docker-Native)

```bash
# Analyze image vulnerabilities
docker scout cves myapp:latest

# Compare two images
docker scout compare --to myapp:v1.2.2 myapp:v1.2.3

# Quick overview
docker scout quickview myapp:latest

# CI integration — fail on critical
docker scout cves --exit-code --only-severity critical myapp:latest
```

### Snyk

```bash
# Scan container image
snyk container test myapp:latest --severity-threshold=high

# Monitor (track new vulnerabilities)
snyk container monitor myapp:latest

# Output SARIF
snyk container test myapp:latest --sarif-file-output=snyk.sarif
```

### Scanning in GitHub Actions (Full Example)

```yaml
      - name: Build image
        uses: docker/build-push-action@4f58ea79222b3b9dc585cd0ca6fc9cb5c7da2c48
        with:
          context: .
          load: true
          tags: myapp:scan

      - name: Trivy scan (fail on HIGH/CRITICAL)
        uses: aquasecurity/trivy-action@18f2510ee396bbf400402947e7f3a8f37e4e6e04
        with:
          image-ref: myapp:scan
          format: table
          exit-code: '1'
          severity: HIGH,CRITICAL

      - name: Trivy SARIF (always upload, even on failure)
        uses: aquasecurity/trivy-action@18f2510ee396bbf400402947e7f3a8f37e4e6e04
        if: always()
        with:
          image-ref: myapp:scan
          format: sarif
          output: trivy-results.sarif

      - name: Upload to GitHub Security
        uses: github/codeql-action/upload-sarif@v3
        if: always()
        with:
          sarif_file: trivy-results.sarif
```

### Scanning Best Practices

| Practice | Why |
|---|---|
| Fail builds on CRITICAL/HIGH | Prevent vulnerable images from shipping |
| Upload SARIF to GitHub Security | Centralized vulnerability dashboard |
| Scan on PR builds (don't just scan on push) | Catch issues before merge |
| Use `.trivyignore` for accepted risks | Avoid blocking builds on known-accepted CVEs |
| Scan base images separately | Distinguish app vulns from OS vulns |
| Schedule periodic re-scans of deployed images | Catch newly discovered CVEs in running images |

---

## 10. Deployment Patterns

### Tag-Based Deployment

```bash
# Deployment script triggered by CI after push
#!/usr/bin/env bash
set -euo pipefail

REGISTRY="registry.example.com"
IMAGE="${REGISTRY}/myapp"
TAG="${1:?Usage: deploy.sh <tag>}"

docker pull "${IMAGE}:${TAG}"
docker stop myapp 2>/dev/null || true
docker rm myapp 2>/dev/null || true
docker run -d \
  --name myapp \
  --restart unless-stopped \
  -p 8080:8080 \
  --env-file /etc/myapp/.env \
  "${IMAGE}:${TAG}"

# Verify health
for i in $(seq 1 30); do
  if curl -sf http://localhost:8080/health > /dev/null; then
    echo "Deployment successful: ${TAG}"
    exit 0
  fi
  sleep 2
done
echo "Health check failed after deploy" >&2
exit 1
```

### Image Promotion Pipeline

```
                Build         Test         Staging         Production
               ┌──────┐    ┌──────┐     ┌────────┐      ┌───────────┐
  push main ──>│ Build │───>│ Scan │────>│ Deploy │─────>│  Deploy   │
               │ :sha  │    │ Trivy│     │ :staging│ ok  │ :prod     │
               └──────┘    └──────┘     └────────┘      └───────────┘
                                                 ▲ manual gate
```

```bash
# Promote image without rebuilding
promote() {
  local src_tag=$1 dest_tag=$2
  docker pull "registry.example.com/myapp:${src_tag}"
  docker tag "registry.example.com/myapp:${src_tag}" "registry.example.com/myapp:${dest_tag}"
  docker push "registry.example.com/myapp:${dest_tag}"
}

# Staging -> Production promotion
promote "sha-abc12345" "production"
promote "sha-abc12345" "v1.2.3"
```

### Watchtower for Auto-Update

```bash
# Watchtower watches running containers and updates them when new images are pushed
docker run -d \
  --name watchtower \
  --restart unless-stopped \
  -v /var/run/docker.sock:/var/run/docker.sock \
  containrrr/watchtower \
  --interval 300 \
  --cleanup \
  --label-enable

# Only auto-update containers with the label
docker run -d \
  --name myapp \
  --label com.centurylinklabs.watchtower.enable=true \
  registry.example.com/myapp:latest

# WARNING: Watchtower pulls :latest — only use in staging/dev.
# In production, use explicit version tags with controlled promotion.
```

### Webhook Trigger Deployment

```yaml
# GitHub Actions — deploy on tag push
name: Deploy
on:
  push:
    tags: ['v*']
jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - name: Deploy via SSH
        uses: appleboy/ssh-action@029f5b4aeeeb58fdfe1410a5d17f801b1d77f7e0  # v1.2.0
        with:
          host: ${{ secrets.DEPLOY_HOST }}
          username: ${{ secrets.DEPLOY_USER }}
          key: ${{ secrets.DEPLOY_SSH_KEY }}
          script: |
            docker pull ghcr.io/${{ github.repository }}:${{ github.ref_name }}
            cd /opt/myapp && docker compose up -d
```

### Blue-Green Deployment with Docker

```bash
#!/usr/bin/env bash
set -euo pipefail

IMAGE="registry.example.com/myapp:${1:?tag required}"
BLUE_PORT=8081
GREEN_PORT=8082
NGINX_CONF="/etc/nginx/conf.d/myapp.conf"

# Determine which slot is live
if docker ps --format '{{.Names}}' | grep -q myapp-blue; then
  LIVE=blue; NEW=green; NEW_PORT=$GREEN_PORT
else
  LIVE=green; NEW=blue; NEW_PORT=$BLUE_PORT
fi

# Start new version
docker pull "$IMAGE"
docker rm -f "myapp-${NEW}" 2>/dev/null || true
docker run -d --name "myapp-${NEW}" --restart unless-stopped \
  -p "${NEW_PORT}:8080" "$IMAGE"

# Wait for health
for i in $(seq 1 30); do
  curl -sf "http://localhost:${NEW_PORT}/health" > /dev/null && break
  sleep 2
done

# Switch traffic (update nginx upstream)
sed -i "s/localhost:[0-9]*/localhost:${NEW_PORT}/" "$NGINX_CONF"
nginx -s reload

# Stop old version
docker stop "myapp-${LIVE}" 2>/dev/null || true
docker rm "myapp-${LIVE}" 2>/dev/null || true

echo "Deployed ${IMAGE} on ${NEW} (port ${NEW_PORT})"
```

---

---

## Anti-Patterns

| Anti-Pattern | Why It Fails | Correct Approach |
|---|---|---|
| Using `latest` tag in CI/CD pipelines | Non-deterministic builds; what worked yesterday breaks today; impossible to reproduce or rollback | Tag images with git SHA, semver, or build number; pin exact versions in deployment manifests |
| Building images without layer caching in CI | Every build starts from scratch; 10-minute builds that could be 30 seconds; wasted CI compute | Use BuildKit cache mounts, GitHub Actions cache, or registry-based caching (--cache-from/--cache-to) |
| Storing secrets in Dockerfile ARG or ENV | Build args appear in image history; anyone with `docker history` can extract secrets | Use BuildKit secret mounts (--mount=type=secret) or multi-stage builds that discard secret layers |
| Not scanning images before pushing to registry | Vulnerable images reach production; CVEs discovered after deployment require emergency patching | Add Trivy/Scout/Snyk scan as a CI gate; fail the pipeline on HIGH/CRITICAL vulnerabilities |
| Single-platform builds for multi-arch deployments | ARM-based servers (Graviton, Apple Silicon) cannot run amd64 images; crashes or emulation overhead | Use `docker buildx build --platform linux/amd64,linux/arm64` for all production images |

---

## Related Skills

| Topic | Skill |
|---|---|
| Core Docker concepts, Dockerfile, BuildKit | `docker-fundamentals` |
| Docker Compose orchestration patterns | `docker-compose-patterns` |
| Docker networking (bridge, overlay, DNS) | `docker-networking` |
| Volumes, bind mounts, storage drivers | `docker-storage` |
| Image scanning, rootless, CIS benchmark | `docker-security` |
| Operational gotchas, cross-platform issues | `docker-admin` |
| Docker on Ubuntu 24.04 | `ubuntu-docker-host` |
| Podman/Docker on RHEL 9 | `rhel-docker-host` |

<!-- FRESHNESS:v1
anchors:
  - kind: ecosystem
    subject: container-build-tools
    verified_against: "Kaniko archived 2025-06-03 (GoogleContainerTools/kaniko read-only; Chainguard fork chainguard-dev/kaniko); GitLab docs recommend rootless BuildKit (moby/buildkit:rootless, buildctl-daemonless.sh) or Buildah (quay.io/buildah/stable)"
    verified_on: "2026-06-10"
-->

