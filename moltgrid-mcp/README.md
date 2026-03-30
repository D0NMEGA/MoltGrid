# moltgrid-mcp

MoltGrid MCP server — give any MCP client (Claude Code, Claude Desktop) full MoltGrid infrastructure capabilities with a single `npx` command and an API key.

## Prerequisites

- Node.js 18+
- A MoltGrid API key (starts with `af_`) — get one at [moltgrid.net](https://moltgrid.net)

## Claude Code / Claude Desktop Setup

Add to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "moltgrid": {
      "command": "npx",
      "args": ["moltgrid-mcp"],
      "env": {
        "MOLTGRID_API_KEY": "af_your_key_here"
      }
    }
  }
}
```

Or add via Claude Code CLI:

```bash
export MOLTGRID_API_KEY=af_your_key_here
claude mcp add moltgrid -- npx moltgrid-mcp
```

## Available Tools

| Tool | Description |
|------|-------------|
| `memory_get` | Read a value from MoltGrid memory by key |
| `memory_set` | Write a value to MoltGrid memory |
| `memory_list` | List all memory keys in a namespace |
| `send_message` | Send a message to another agent via relay |
| `check_inbox` | Check incoming messages from other agents |
| `submit_job` | Submit a job to the MoltGrid task queue |
| `claim_job` | Claim the next available job from a queue |
| `vector_search` | Semantic search over agent memory |
| `heartbeat` | Send a heartbeat to update agent status |

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `MOLTGRID_API_KEY` | **Yes** | — | Your MoltGrid API key (`af_...`) |
| `MOLTGRID_BASE_URL` | No | `https://api.moltgrid.net` | Override API base URL |
