# Config Schema: ~/.knowledge-grounding.yaml

Optional user config file. Missing = auto-detect local sources only, no enterprise endpoints, no errors.

## Full Schema

```yaml
# Enterprise knowledge sources (user-configured, not auto-detected)
endpoints:
  confluence:
    url: "https://wiki.corp.net"       # required if section present
    auth: "token"                       # token | basic | pat
    spaces: ["DEV", "OPS"]             # optional: limit search to these spaces
  jira:
    url: "https://jira.corp.net"       # required if section present
    auth: "token"                       # token | basic | pat
    projects: ["PLAT"]                 # optional: limit search to these projects
  vector_store:
    type: "chromadb"                   # chromadb | faiss | pgvector
    url: "http://chroma.internal:8000" # required if section present
    collections: ["codebase", "docs"]  # optional: limit to these collections

# Local paths to scan for documentation (glob-expanded)
doc_paths:
  - "/path/to/projects/*/docs"
  - "/path/to/projects/*/PROJECT.md"

# Shared drive mounts
shared_drives:
  - path: "/mnt/shared/engineering-docs"
    label: "Engineering shared drive"
  - path: "/mnt/shared/runbooks"
    label: "Operations runbooks"

# Air-gap behavior
strict_airgap: false  # true = refuse training-only answers without user override
```

## Field Reference

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `endpoints` | map | `{}` | Enterprise endpoints (Confluence, Jira, vector stores) |
| `endpoints.<name>.url` | string | -- | Base URL for the endpoint (required) |
| `endpoints.<name>.auth` | string | `"token"` | Authentication method |
| `endpoints.vector_store.type` | string | -- | Vector store engine type |
| `endpoints.vector_store.collections` | list | all | Collections to search |
| `doc_paths` | list | `[]` | Glob paths to scan for local docs |
| `shared_drives` | list | `[]` | Shared drive mount points |
| `shared_drives[].path` | string | -- | Mount point path (required) |
| `shared_drives[].label` | string | `""` | Human-readable label |
| `strict_airgap` | bool | `false` | Require user override for training-only answers |

## Behavior When Missing

- No config file = no error
- Wikis discovered via `~/.wiki-registry.yaml` and `.wiki-link` files (always auto-detected)
- Project docs discovered via CWD scan (always auto-detected)
- Internet reachability via DNS canary (always auto-detected)
- Enterprise endpoints require explicit config (not auto-detected)
