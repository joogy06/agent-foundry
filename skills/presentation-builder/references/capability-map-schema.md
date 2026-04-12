# Capability Map Schema

The parent skill runs environment detection ONCE per session and caches the result.

## Detection Script (Bash)

```bash
#!/bin/bash
# Presentation Builder Environment Detection
# Outputs JSON capability map to stdout

cap='{}'

# Runtimes
py=$(python3 --version 2>/dev/null | grep -oP '[\d.]+' || echo "null")
node=$(node --version 2>/dev/null | tr -d 'v' || echo "null")
java=$(java --version 2>/dev/null | head -1 | grep -oP '[\d.]+' || echo "null")
ps=$(pwsh --version 2>/dev/null | grep -oP '[\d.]+' || powershell -Command '$PSVersionTable.PSVersion.ToString()' 2>/dev/null || echo "null")

# Python libraries
pptx_ver=$(python3 -c "import pptx; print(pptx.__version__)" 2>/dev/null || echo "null")
mpl_ver=$(python3 -c "import matplotlib; print(matplotlib.__version__)" 2>/dev/null || echo "null")
sns_ver=$(python3 -c "import seaborn; print(seaborn.__version__)" 2>/dev/null || echo "null")

# Node tools
marp_ver=$(marp --version 2>/dev/null | head -1 || echo "null")
mmdc_ver=$(mmdc --version 2>/dev/null || echo "null")

# Standalone tools
dot_ver=$(dot -V 2>&1 | grep -oP '[\d.]+' || echo "null")
plantuml=$(which plantuml 2>/dev/null && echo "available" || echo "null")

# Image generation
banana=$(gemini extensions list 2>/dev/null | grep -i banana && echo "available" || echo "null")

# Connectivity
online=$(ping -c1 -W2 8.8.8.8 >/dev/null 2>&1 && echo "true" || echo "false")

# Can we install packages?
pip_ok=$(python3 -m pip --version >/dev/null 2>&1 && echo "true" || echo "false")
npm_ok=$(npm --version >/dev/null 2>&1 && echo "true" || echo "false")

cat << EOF
{
  "runtimes": {
    "python": "$py",
    "node": "$node",
    "java": "$java",
    "powershell": "$ps"
  },
  "pptx_engines": [
    $([ "$pptx_ver" != "null" ] && echo '"python-pptx"')
    $([ "$java" != "null" ] && echo ', "apache-poi"')
    $([ "$ps" != "null" ] && echo ', "powershell-com"')
    $([ "$marp_ver" != "null" ] && echo ', "marp-pptx"')
  ],
  "html_engines": [
    $([ "$node" != "null" ] && echo '"reveal.js"')
    $([ "$marp_ver" != "null" ] && echo ', "marp"')
    "raw-html"
  ],
  "chart_tools": [
    $([ "$mpl_ver" != "null" ] && echo '"matplotlib"')
    $([ "$sns_ver" != "null" ] && echo ', "seaborn"')
  ],
  "diagram_tools": [
    $([ "$banana" != "null" ] && echo '"nanobanana"')
    $([ "$mmdc_ver" != "null" ] && echo ', "mermaid-cli"')
    $([ "$dot_ver" != "null" ] && echo ', "graphviz"')
    $([ "$plantuml" != "null" ] && echo ', "plantuml"')
  ],
  "image_gen": [
    $([ "$banana" != "null" ] && echo '"nanobanana"')
  ],
  "online": $online,
  "install_capable": { "pip": $pip_ok, "npm": $npm_ok },
  "python_pptx_version": "$pptx_ver",
  "matplotlib_version": "$mpl_ver",
  "marp_version": "$marp_ver",
  "mermaid_version": "$mmdc_ver",
  "graphviz_version": "$dot_ver"
}
EOF
```

## Fallback Chains

### PPTX Generation
1. **python-pptx** (preferred — native editable PPTX, template support)
2. **Apache POI XSLF** (Java fallback — verbose but capable)
3. **PowerShell COM** (Windows-only, requires PowerPoint installed)
4. **Marp `--pptx-editable`** (experimental, lower fidelity)
5. **HTML only** (if no PPTX engine available)

### HTML Slides
1. **reveal.js** (best agent-controlled HTML, offline capable)
2. **Marp** (fastest markdown-to-slides, CLI driven)
3. **Raw HTML** (always available — single file, inline CSS)

### Diagrams
1. **nano-banana / Gemini** (AI-generated, best for creative/illustrative visuals)
2. **Mermaid CLI** (deterministic, best for flowcharts/sequence/ER/Gantt)
3. **Graphviz / dot** (deterministic, best for architecture/network topology)
4. **PlantUML** (deterministic, best for UML-specific diagrams)
5. **ASCII art** (always works, zero dependencies)

### Charts
1. **matplotlib / seaborn** (Python — publication quality)
2. **Mermaid Gantt/pie** (limited chart types but zero Python needed)
3. **ASCII/text table** (always works)

## Priority Rules

- Use **deterministic renderers** (code-generated) for diagrams and charts — predictable, repeatable
- Use **AI image generation** (banana) only for: cover art, illustrations, icons, decorative visuals
- Never use AI image gen for: architecture diagrams, data charts, flowcharts, or anything with precise labels/numbers
- If a tool is missing but installable (`pip install python-pptx`), offer to install BEFORE falling back
