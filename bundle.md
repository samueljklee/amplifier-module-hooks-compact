---
bundle:
  name: hooks-compact
  version: 0.1.0
  description: Compress verbose bash output before it enters the LLM context window

includes:
  - bundle: hooks-compact:behaviors/compact.yaml
---

# hooks-compact

Compresses bash tool output by 60-90% before it enters the LLM context window.
Inspired by [RTK (Rust Token Killer)](https://github.com/rtk-ai/rtk).

See [README.md](README.md) for installation and configuration.
