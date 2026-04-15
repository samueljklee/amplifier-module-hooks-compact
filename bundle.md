---
bundle:
  name: hooks-compact
  version: 0.1.0
  description: Compress verbose bash output before it enters the LLM context window

includes:
  - bundle: hooks-compact:behaviors/compact
---

# hooks-compact

Compresses bash tool output by 60-90% before it enters the LLM context window.
Inspired by [RTK (Rust Token Killer)](https://github.com/rtk-ai/rtk).

## Quick Start

Add to your app bundle:

```
amplifier bundle add git+https://github.com/samueljklee/amplifier-module-hooks-compact@main --app
```

Or include just the behavior in your bundle YAML:

```yaml
includes:
  - bundle: git+https://github.com/samueljklee/amplifier-module-hooks-compact@main#subdirectory=behaviors/compact.yaml
```

## Configuration

```yaml
hooks:
  - module: hooks-compact
    source: git+https://github.com/samueljklee/amplifier-module-hooks-compact@main
    config:
      enabled: true        # set false to disable entirely
      min_lines: 20        # skip compression for short output
      strip_ansi: true     # strip color codes before filtering
      show_savings: true   # show "compressed: X → Y chars (Z%)" message
      debug: false         # show before/after comparison (development only)
```
