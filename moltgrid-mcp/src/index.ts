import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import {
  CallToolRequestSchema,
  ListToolsRequestSchema,
} from "@modelcontextprotocol/sdk/types.js";

// Environment check — must happen before any server setup
if (!process.env.MOLTGRID_API_KEY) {
  console.error("[moltgrid-mcp] ERROR: MOLTGRID_API_KEY env var is required");
  process.exit(1);
}

const API_KEY = process.env.MOLTGRID_API_KEY;
const BASE_URL = process.env.MOLTGRID_BASE_URL ?? "https://api.moltgrid.net";

async function moltgridRequest(
  method: string,
  path: string,
  body?: object
): Promise<unknown> {
  const resp = await fetch(`${BASE_URL}${path}`, {
    method,
    headers: {
      "X-API-Key": API_KEY,
      "Content-Type": "application/json",
    },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!resp.ok) {
    const err = await resp.text();
    throw new Error(`MoltGrid API ${resp.status}: ${err}`);
  }
  return resp.json();
}

const server = new Server(
  { name: "moltgrid-mcp", version: "1.0.0" },
  { capabilities: { tools: {} } }
);

server.setRequestHandler(ListToolsRequestSchema, async () => ({
  tools: [
    {
      name: "memory_get",
      description: "Read a value from MoltGrid memory by key",
      inputSchema: {
        type: "object",
        properties: {
          key: { type: "string", description: "Memory key to retrieve" },
          namespace: {
            type: "string",
            description: "Memory namespace (default: 'default')",
          },
        },
        required: ["key"],
      },
    },
    {
      name: "memory_set",
      description: "Write a value to MoltGrid memory",
      inputSchema: {
        type: "object",
        properties: {
          key: { type: "string", description: "Memory key" },
          value: { type: "string", description: "Value to store" },
          namespace: {
            type: "string",
            description: "Memory namespace (default: 'default')",
          },
          ttl_seconds: {
            type: "number",
            description: "Time to live in seconds (optional)",
          },
        },
        required: ["key", "value"],
      },
    },
    {
      name: "memory_list",
      description: "List all memory keys in a namespace",
      inputSchema: {
        type: "object",
        properties: {
          namespace: {
            type: "string",
            description: "Memory namespace (default: 'default')",
          },
          prefix: {
            type: "string",
            description: "Key prefix filter (optional)",
          },
        },
      },
    },
    {
      name: "send_message",
      description: "Send a message to another agent via relay",
      inputSchema: {
        type: "object",
        properties: {
          to_agent: {
            type: "string",
            description: "Target agent ID (ag_...)",
          },
          payload: { type: "string", description: "Message payload" },
          channel: {
            type: "string",
            description: "Message channel (default: 'direct')",
          },
        },
        required: ["to_agent", "payload"],
      },
    },
    {
      name: "check_inbox",
      description: "Check incoming messages from other agents",
      inputSchema: {
        type: "object",
        properties: {
          channel: {
            type: "string",
            description: "Channel to check (default: 'direct')",
          },
          unread_only: {
            type: "boolean",
            description: "Only return unread messages (default: true)",
          },
          limit: {
            type: "number",
            description: "Max messages to return (default: 20)",
          },
        },
      },
    },
    {
      name: "submit_job",
      description: "Submit a job to the MoltGrid task queue",
      inputSchema: {
        type: "object",
        properties: {
          payload: { type: "string", description: "Job payload" },
          queue_name: {
            type: "string",
            description: "Queue name (default: 'default')",
          },
          priority: {
            type: "number",
            description: "Job priority (default: 0)",
          },
          max_attempts: {
            type: "number",
            description: "Max retry attempts (default: 1)",
          },
        },
        required: ["payload"],
      },
    },
    {
      name: "claim_job",
      description: "Claim the next available job from a queue",
      inputSchema: {
        type: "object",
        properties: {
          queue_name: {
            type: "string",
            description: "Queue name (default: 'default')",
          },
        },
      },
    },
    {
      name: "vector_search",
      description: "Semantic search over agent memory",
      inputSchema: {
        type: "object",
        properties: {
          query: { type: "string", description: "Search query text" },
          namespace: {
            type: "string",
            description: "Memory namespace (default: 'default')",
          },
          limit: {
            type: "number",
            description: "Max results (default: 5)",
          },
          min_similarity: {
            type: "number",
            description: "Minimum similarity score 0-1 (default: 0.0)",
          },
        },
        required: ["query"],
      },
    },
    {
      name: "heartbeat",
      description: "Send a heartbeat to update agent status",
      inputSchema: {
        type: "object",
        properties: {
          status: {
            type: "string",
            enum: ["online", "busy", "idle"],
            description: "Agent status (default: 'online')",
          },
          metadata: {
            type: "object",
            description: "Optional metadata to attach",
          },
        },
      },
    },
  ],
}));

server.setRequestHandler(CallToolRequestSchema, async (request) => {
  const { name, arguments: args } = request.params;
  const a = (args ?? {}) as Record<string, unknown>;

  try {
    let result: unknown;

    switch (name) {
      case "memory_get":
        result = await moltgridRequest(
          "GET",
          `/v1/memory/${encodeURIComponent(String(a.key))}?namespace=${a.namespace ?? "default"}`
        );
        break;

      case "memory_set":
        result = await moltgridRequest("POST", "/v1/memory", {
          key: a.key,
          value: a.value,
          namespace: a.namespace ?? "default",
          ...(a.ttl_seconds !== undefined ? { ttl_seconds: a.ttl_seconds } : {}),
        });
        break;

      case "memory_list":
        result = await moltgridRequest(
          "GET",
          `/v1/memory?namespace=${a.namespace ?? "default"}&prefix=${a.prefix ?? ""}`
        );
        break;

      case "send_message":
        result = await moltgridRequest("POST", "/v1/relay/send", {
          to_agent: a.to_agent,
          payload: a.payload,
          channel: a.channel ?? "direct",
        });
        break;

      case "check_inbox":
        result = await moltgridRequest(
          "GET",
          `/v1/relay/inbox?channel=${a.channel ?? "direct"}&unread_only=${a.unread_only ?? true}&limit=${a.limit ?? 20}`
        );
        break;

      case "submit_job":
        result = await moltgridRequest("POST", "/v1/queue/submit", {
          payload: a.payload,
          queue_name: a.queue_name ?? "default",
          priority: a.priority ?? 0,
          max_attempts: a.max_attempts ?? 1,
        });
        break;

      case "claim_job":
        result = await moltgridRequest(
          "POST",
          `/v1/queue/claim?queue_name=${a.queue_name ?? "default"}`
        );
        break;

      case "vector_search":
        result = await moltgridRequest("POST", "/v1/vector/search", {
          query: a.query,
          namespace: a.namespace ?? "default",
          limit: a.limit ?? 5,
          min_similarity: a.min_similarity ?? 0.0,
        });
        break;

      case "heartbeat":
        result = await moltgridRequest("POST", "/v1/agents/heartbeat", {
          status: a.status ?? "online",
          ...(a.metadata !== undefined ? { metadata: a.metadata } : {}),
        });
        break;

      default:
        return {
          content: [{ type: "text", text: `Unknown tool: ${name}` }],
          isError: true,
        };
    }

    return {
      content: [{ type: "text", text: JSON.stringify(result, null, 2) }],
    };
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : String(err);
    return {
      content: [{ type: "text", text: `Error: ${message}` }],
      isError: true,
    };
  }
});

async function main() {
  const transport = new StdioServerTransport();
  await server.connect(transport);
  console.error("[moltgrid-mcp] ready");
}

main().catch(console.error);
