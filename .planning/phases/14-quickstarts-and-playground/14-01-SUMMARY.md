---
phase: 14-quickstarts-and-playground
plan: 01
subsystem: documentation
tags: [guides, dx, langgraph, crewai, openai, mcp]
dependency_graph:
  requires: []
  provides: [langgraph-guide, crewai-guide, openai-guide, mcp-advanced]
  affects: [routers/integrations.py]
tech_stack:
  added: []
  patterns: [markdown-guides, code-first-docs]
key_files:
  created:
    - docs/guides/langgraph.md
    - docs/guides/crewai.md
    - docs/guides/openai.md
  modified:
    - docs/guides/mcp.md
    - routers/integrations.py
decisions:
  - Used actual SDK method names (memory_set, memory_get, etc.) not dot-notation aliases
  - All guides use MoltGrid class import (not MoltGridClient) matching SDK source
  - MCP guide expanded with 5 new sections while preserving all original content
metrics:
  duration: 3min
  completed: "2026-03-15T07:49:00Z"
  tasks_completed: 2
  tasks_total: 2
requirements_completed: [DX-05, DX-06, DX-07]
---

# Phase 14 Plan 01: Framework Quickstart Guides Summary

3 framework-specific quickstart guides (LangGraph, CrewAI, OpenAI Agents) plus expanded MCP guide with advanced usage, troubleshooting, and self-hosted sections. All guides use real SDK method signatures and copy-paste-ready code.

## One-Liner

Framework quickstart guides for LangGraph/CrewAI/OpenAI with real SDK calls, plus MCP advanced usage and troubleshooting

## What Was Built

### Task 1: Write 3 Framework Quickstart Guides + Expand MCP Guide
- **docs/guides/langgraph.md** (237 lines): StateGraph with MoltGrid tool nodes, full working example with research-enqueue-report pipeline, worker claim pattern
- **docs/guides/crewai.md** (275 lines): BaseTool subclasses wrapping MoltGrid SDK, full crew with researcher+reporter agents, namespace usage patterns
- **docs/guides/openai.md** (362 lines): Function calling tool schemas, execute_tool dispatcher, conversation loop with tool_calls handling, persistent memory across sessions
- **docs/guides/mcp.md** (256 lines, was 102): Added Advanced Usage (tool chaining, namespaces, queue patterns, TTL, messaging), Troubleshooting (4 common issues), Self-Hosted section with config examples

### Task 2: Register New Guide Slugs
- GUIDE_PLATFORMS updated from 5 to 8 slugs: added `langgraph`, `crewai`, `openai`
- GET /v1/guides/{slug} resolves all 8 guides via existing path resolution

## Commits

| Commit | Description |
|--------|-------------|
| 097870f | feat(14-01): write 3 framework quickstart guides and expand MCP guide |
| dfca925 | feat(14-01): register langgraph, crewai, openai slugs in GUIDE_PLATFORMS |

## Deviations from Plan

None -- plan executed exactly as written.

## Verification

- All 4 guide files validated: exist, meet minimum line counts, contain API URL and key placeholder
- All 3 new slugs confirmed present in GUIDE_PLATFORMS
- Pushed to main and deployed to VPS successfully
