# Documentation

This directory contains comprehensive documentation for the ICT Options Agent project.

## Quick Links

- **[Main README](../README.md)** — Project overview and quick start
- **[Submission Guide](SUBMISSION_GUIDE.md)** — Complete submission documentation
- **[Diagram Usage](diagrams/README.md)** — How to use architecture diagrams

## Contents

### Architecture Diagrams (`diagrams/`)

Interactive HTML diagrams generated with [Archify](https://github.com/tt-a1i/archify):

| Diagram | File | Description |
|---------|------|-------------|
| Architecture | `agent-architecture.html` | Component map showing all system parts |
| Workflow | `agent-workflow.html` | Trading cycle workflow with lanes |
| Sequence | `agent-sequence.html` | Message sequence for one cycle |
| Data Flow | `agent-dataflow.html` | Data pipeline from sources to execution |

To regenerate diagrams:
```bash
node ../archify-diagrams.mjs
```

### Submission Guide (`SUBMISSION_GUIDE.md`)

Complete documentation for project submission including:
- Project summary and unique features
- Technical implementation details
- Code architecture explanation
- Demo evidence and screenshots
- Key innovations and contributions

## Usage

All HTML files are self-contained and can be opened directly in a browser:

```bash
# Open diagrams
start docs/diagrams/agent-architecture.html
start docs/diagrams/agent-workflow.html
start docs/diagrams/agent-sequence.html
start docs/diagrams/agent-dataflow.html

# View submission guide
start docs/SUBMISSION_GUIDE.md
```

## Generation Pipeline

Diagrams are generated from JSON specifications using the Archify toolchain:

```bash
# Validate diagram spec
node archify-diagrams.mjs --validate

# Generate all diagrams
node archify-diagrams.mjs

# Generate single diagram
node archify-diagrams.mjs architecture
```

JSON specs are stored alongside HTML files for easy editing and regeneration.
