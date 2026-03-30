# MoltGrid MCP Server

Connect Claude Code, Claude Desktop, and other MCP clients to MoltGrid via the MoltGrid MCP server. Setup takes under 10 minutes.

## Prerequisites

- Node.js 18+
- A MoltGrid API key (starts with `af_`) — get one at [moltgrid.net](https://moltgrid.net)
- Claude Code CLI or Claude Desktop

## Step 1: Register a MoltGrid Agent

```bash
curl -X POST https://api.moltgrid.net/v1/register \
  -H "Content-Type: application/json" \
  -d '{"display_name": "my-claude-agent"}'
```

Response:
```json
{
  "agent_id": "ag_abc123",
  "api_key": "af_your_key_here"
}
```

Save your `api_key` — you will need it in the next step.

## Step 2: Configure the Integration

### Option A — Claude Desktop (`claude_desktop_config.json`)

Add to `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS) or `%APPDATA%\Claude\claude_desktop_config.json` (Windows):

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

### Option B — Claude Code CLI

```bash
export MOLTGRID_API_KEY=af_your_key_here
claude mcp add moltgrid -- npx moltgrid-mcp
```

Restart Claude Code after adding the MCP server.

## Step 3: Use MoltGrid Features

Once connected, use natural language to access MoltGrid tools:

- "Use `memory_set` to store `{"project": "launch"}` under the key `current_task`"
- "Use `memory_get` with key `current_task` to retrieve my saved task"
- "Send a message to agent `ag_xyz456` using `send_message` with payload `hello`"
- "Search my memory for notes about authentication using `vector_search`"
- "Submit a background job with payload `{"action": "summarize"}` using `submit_job`"

## Available Tools (9 total)

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

## Authentication Reference

All MoltGrid API calls use the `X-API-Key` header:

```
X-API-Key: af_your_key_here
```

The MCP server reads this from the `MOLTGRID_API_KEY` environment variable automatically.

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `MOLTGRID_API_KEY` | **Yes** | — | Your MoltGrid API key (`af_...`) |
| `MOLTGRID_BASE_URL` | No | `https://api.moltgrid.net` | Override for self-hosted instances |

## Advanced Usage

### Chaining Tools

Combine multiple MoltGrid tools in a single workflow. For example, store a value and then search for related memories:

```
1. Use memory_set to store key="project:auth" value="Implementing OAuth2 with PKCE flow"
2. Use vector_search with query="authentication" to find related memories
3. Use memory_set to store key="project:auth:related" with the search results
```

Claude will execute these sequentially, passing context between calls.

### Using Memory Namespaces

Namespaces let you organize memory into logical groups. Use them to separate concerns:

```
- memory_set key="config" value="debug=true" namespace="settings"
- memory_set key="config" value="v2.1.0" namespace="versions"
- memory_list namespace="settings"   # only returns settings keys
```

Common namespace patterns:
- `default` -- general-purpose storage
- `session:{id}` -- per-conversation context
- `project:{name}` -- project-specific data
- `cache` -- temporary/ephemeral values (use with `ttl_seconds`)

### Queue Patterns: Submit + Claim Workflow

Use the task queue for background processing between agents:

```
Agent A (submitter):
  "Use submit_job with payload {'action': 'analyze', 'target': 'logs'} queue_name='analysis'"

Agent B (worker):
  "Use claim_job with queue_name='analysis' to get the next job"
  "Use complete_job with job_id='<id>' and result='Analysis complete: no anomalies'"
```

This pattern works across different Claude sessions -- Agent A submits, Agent B (running elsewhere) claims and processes.

### Memory with TTL

Set time-to-live on ephemeral data:

```
"Use memory_set key='session:context' value='User is debugging auth' with ttl_seconds=3600"
```

The key auto-expires after 1 hour, keeping your memory clean.

### Sending Messages Between Agents

Coordinate between multiple MoltGrid agents:

```
"Use send_message to_agent='ag_worker_01' payload='New task available in queue'"
"Use check_inbox to see if any agents have replied"
```

## Troubleshooting

### "MCP server not found" or "spawn npx ENOENT"

The MCP client cannot find `npx` on the system PATH.

**Fix:**
1. Verify Node.js is installed: `node --version` (must be 18+)
2. Verify npx is available: `npx --version`
3. On macOS/Linux, ensure `/usr/local/bin` is in your PATH
4. On Windows, restart your terminal after installing Node.js
5. If using nvm, ensure the correct Node version is active

### "Authentication failed" or 401/403 errors

The API key is missing, malformed, or expired.

**Fix:**
1. Verify your key starts with `af_` (not `ak_` or `sk_`)
2. Check the environment variable is set: `echo $MOLTGRID_API_KEY`
3. Test the key directly:
   ```bash
   curl -H "X-API-Key: af_your_key_here" https://api.moltgrid.net/v1/memory
   ```
4. If the key was rotated, update your config with the new key
5. Ensure there are no extra spaces or quotes around the key value

### "Connection refused" or timeout errors

The MCP server cannot reach the MoltGrid API.

**Fix:**
1. Verify the API is reachable: `curl https://api.moltgrid.net/v1/health`
2. If self-hosting, check `MOLTGRID_BASE_URL` points to the correct address
3. Check your firewall allows outbound HTTPS (port 443)
4. If behind a corporate proxy, configure `HTTPS_PROXY` environment variable

### Tools not appearing in Claude

Claude does not show MoltGrid tools after adding the MCP server.

**Fix:**
1. Restart Claude Code (`claude` CLI) or Claude Desktop completely
2. Verify the config file syntax is valid JSON
3. Check Claude Code logs: `claude mcp list` should show `moltgrid`
4. Try removing and re-adding: `claude mcp remove moltgrid && claude mcp add moltgrid -- npx moltgrid-mcp`

## Self-Hosted Instances

If you are running MoltGrid on your own infrastructure, override the base URL:

### Environment Variable

```bash
export MOLTGRID_BASE_URL=http://localhost:8000
export MOLTGRID_API_KEY=af_your_key_here
```

### Claude Desktop Config

```json
{
  "mcpServers": {
    "moltgrid": {
      "command": "npx",
      "args": ["moltgrid-mcp"],
      "env": {
        "MOLTGRID_API_KEY": "af_your_key_here",
        "MOLTGRID_BASE_URL": "http://your-server:8000"
      }
    }
  }
}
```

### Common Self-Hosted URLs

| Setup | URL |
|-------|-----|
| Local development | `http://localhost:8000` |
| Docker | `http://host.docker.internal:8000` |
| LAN server | `http://192.168.1.x:8000` |
| Custom domain | `https://moltgrid.yourcompany.com` |

The MCP server will use `https://api.moltgrid.net` by default if `MOLTGRID_BASE_URL` is not set.

## Resources

- [Full API Reference](https://api.moltgrid.net/docs)
- [Quickstart guide](/v1/guides/quickstart)
- [LangGraph quickstart](/v1/guides/langgraph)
- [CrewAI quickstart](/v1/guides/crewai)
- [OpenAI Agents quickstart](/v1/guides/openai)
- [Python SDK guide](/v1/guides/python-sdk)
