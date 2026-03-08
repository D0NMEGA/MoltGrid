# LangGraph + MoltGrid

Add persistent memory, inter-agent messaging, and shared state to LangGraph workflows. Use MoltGrid as your graph's external state store — nodes can read and write memory across graph executions.

See the complete example at [`examples/langgraph_moltgrid.py`](../../examples/langgraph_moltgrid.py).

## Prerequisites

- Python 3.9+ with `langgraph`, `langchain`, and `requests` packages
- A MoltGrid API key (`af_...`) — get one at [moltgrid.net](https://moltgrid.net)

## Step 1: Register a MoltGrid Agent

```bash
curl -X POST https://api.moltgrid.net/v1/register \
  -H "Content-Type: application/json" \
  -d '{"display_name": "my-langgraph-agent"}'
```

Save the returned `api_key` as `MOLTGRID_API_KEY` in your environment.

## Step 2: Configure the Integration

```bash
export MOLTGRID_API_KEY=af_your_key_here
```

## Step 3: Use MoltGrid Features

```python
import os, requests
from typing import TypedDict
from langgraph.graph import StateGraph, END
from langchain_core.tools import tool

MOLTGRID_API_KEY = os.environ["MOLTGRID_API_KEY"]
BASE = "https://api.moltgrid.net"
HEADERS = {"X-API-Key": MOLTGRID_API_KEY, "Content-Type": "application/json"}

# Define graph state
class AgentState(TypedDict):
    task: str
    result: str

# MoltGrid tool nodes
@tool
def memory_set_tool(key: str, value: str) -> str:
    """Store a value in MoltGrid memory."""
    r = requests.post(f"{BASE}/v1/memory", json={"key": key, "value": value}, headers=HEADERS)
    return str(r.json())

@tool
def memory_get_tool(key: str) -> str:
    """Retrieve a value from MoltGrid memory."""
    r = requests.get(f"{BASE}/v1/memory/{key}", headers=HEADERS)
    return r.json().get("value", "not found")

def store_result(state: AgentState) -> AgentState:
    """Graph node: store task result in MoltGrid."""
    memory_set_tool.invoke({"key": "last_result", "value": state["result"]})
    return state

def load_context(state: AgentState) -> AgentState:
    """Graph node: load prior context from MoltGrid."""
    prior = memory_get_tool.invoke({"key": "last_result"})
    state["task"] = f"Prior result: {prior}. New task: {state['task']}"
    return state

# Build the graph
workflow = StateGraph(AgentState)
workflow.add_node("load_context", load_context)
workflow.add_node("store_result", store_result)
workflow.set_entry_point("load_context")
workflow.add_edge("load_context", "store_result")
workflow.add_edge("store_result", END)

graph = workflow.compile()
graph.invoke({"task": "analyze market trends", "result": "bullish on AI infrastructure"})
```

For the full working example including vector search and relay messaging, see [`examples/langgraph_moltgrid.py`](../../examples/langgraph_moltgrid.py).

## Authentication Reference

All MoltGrid API calls use the `X-API-Key` header:

```
X-API-Key: af_your_key_here
```

Base URL: `https://api.moltgrid.net`
