---
name: python-debugpy
description: Use for Python breakpoints and debugpy inspection.
version: 1.0.0
author: ARK Infrastructure
license: Proprietary
platforms: [linux]
metadata:
  hermes:
    tags: [python, debugger, debugpy, pdb]
    related_skills: [spike, tmux]
---

# Python Debugging

Use native terminal and code execution with `pdb`, `breakpoint`, post-mortem
inspection, or `debugpy` as appropriate. Reproduce narrowly, avoid exposing a
debug listener beyond the intended interface, and do not leave listeners or
workers running after the investigation. Capture the stack and state that
prove the mechanism before editing.

