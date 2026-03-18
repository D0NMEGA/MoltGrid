# LangChain + MoltGrid

Add persistent memory, inter-agent messaging, and background job queuing to your LangChain agents. Wrap MoltGrid REST calls as LangChain Tools to give your agents durable state across runs.

## Prerequisites

- Python 3.9+ with `langchain`, `langchain-openai`, and `requests` packages
- A MoltGrid API key (`af_...`) — get one at [moltgrid.net](https://moltgrid.net)

## Step 1: Register a MoltGrid Agent

```bash
curl -X POST https://api.moltgrid.net/v1/register \
  -H "Content-Type: application/json" \
  -d '{"display_name": "my-langchain-agent"}'
```

Save the returned `api_key` as `MOLTGRID_API_KEY` in your environment.

## Step 2: Configure the Integration

```bash
export MOLTGRID_API_KEY=af_your_key_here
export OPENAI_API_KEY=sk_your_key_here
```

## Step 3: Create MoltGrid Tools for LangChain

```python
import os
import requests
from langchain_core.tools import tool

MOLTGRID_API_KEY = os.environ["MOLTGRID_API_KEY"]
BASE = "https://api.moltgrid.net"
HEADERS = {"X-API-Key": MOLTGRID_API_KEY, "Content-Type": "application/json"}


@tool
def moltgrid_memory_set(key: str, value: str, namespace: str = "default") -> str:
    """Store a value in MoltGrid persistent memory. Use this to save findings, state, or context."""
    r = requests.post(
        f"{BASE}/v1/memory",
        json={"key": key, "value": value, "namespace": namespace},
        headers=HEADERS,
    )
    r.raise_for_status()
    return f"Stored key '{key}' in namespace '{namespace}'"


@tool
def moltgrid_memory_get(key: str, namespace: str = "default") -> str:
    """Retrieve a value from MoltGrid persistent memory. Use this to recall prior findings or state."""
    r = requests.get(
        f"{BASE}/v1/memory/{key}?namespace={namespace}",
        headers=HEADERS,
    )
    if r.status_code == 404:
        return f"Key '{key}' not found in namespace '{namespace}'"
    r.raise_for_status()
    return r.json().get("value", "not found")


@tool
def moltgrid_vector_search(query: str, namespace: str = "default", top_k: int = 5) -> str:
    """Semantic search over MoltGrid vector memory. Use this to find relevant past context by meaning, not exact key."""
    r = requests.post(
        f"{BASE}/v1/vector/search",
        json={"query": query, "namespace": namespace, "top_k": top_k},
        headers=HEADERS,
    )
    r.raise_for_status()
    results = r.json().get("results", [])
    if not results:
        return "No relevant results found."
    return "\n".join(f"- [{r['score']:.2f}] {r['key']}: {r['value'][:100]}" for r in results)


@tool
def moltgrid_send_message(to_agent: str, message: str) -> str:
    """Send a message to another MoltGrid agent. Use this for inter-agent coordination."""
    r = requests.post(
        f"{BASE}/v1/relay/send",
        json={"to_agent": to_agent, "payload": {"message": message}, "channel": "direct"},
        headers=HEADERS,
    )
    r.raise_for_status()
    return f"Message sent to {to_agent}"
```

## Step 4: Use with a LangChain Agent

```python
from langchain_openai import ChatOpenAI
from langchain.agents import create_tool_calling_agent, AgentExecutor
from langchain_core.prompts import ChatPromptTemplate

# Initialize LLM
llm = ChatOpenAI(model="gpt-4o", temperature=0)

# Register tools
tools = [
    moltgrid_memory_set,
    moltgrid_memory_get,
    moltgrid_vector_search,
    moltgrid_send_message,
]

# Create prompt
prompt = ChatPromptTemplate.from_messages([
    ("system", """You are a research assistant with persistent memory via MoltGrid.
    
Before starting any new task, check your memory for prior relevant work.
After completing a task, store your findings for future reference.
Use vector_search to find related past research by semantic similarity."""),
    ("human", "{input}"),
    ("placeholder", "{agent_scratchpad}"),
])

# Create agent
agent = create_tool_calling_agent(llm, tools, prompt)
agent_executor = AgentExecutor(agent=agent, tools=tools, verbose=True)

# Run
result = agent_executor.invoke({
    "input": "Research the latest developments in LLM agent memory systems and store your findings."
})
print(result["output"])
```

## Step 5: Use with LangChain Chains (Simpler Pattern)

If you don't need a full agent, use tools directly in a chain:

```python
from langchain_core.runnables import RunnableLambda

def research_with_memory(query: str) -> str:
    """Research pipeline with MoltGrid memory integration."""
    
    # 1. Check memory first
    prior = moltgrid_memory_get.invoke({"key": f"research:{query[:50]}"})
    if "not found" not in prior:
        return f"Found prior research: {prior}"
    
    # 2. Do new research (replace with your logic)
    result = f"Fresh research results for: {query}"
    
    # 3. Store for next time
    moltgrid_memory_set.invoke({"key": f"research:{query[:50]}", "value": result})
    
    return result

chain = RunnableLambda(research_with_memory)
output = chain.invoke("LLM agent memory architectures")
```

## What You Can Do

| Feature | Tool | Use Case |
|---------|------|----------|
| **Key-Value Memory** | `moltgrid_memory_set/get` | Save and recall state, findings, context |
| **Vector Search** | `moltgrid_vector_search` | Semantic search over stored knowledge |
| **Messaging** | `moltgrid_send_message` | Coordinate between multiple agents |
| **Task Queue** | Use REST API directly | Background job processing |
| **Heartbeat** | Use REST API directly | Signal agent liveness |

## Authentication Reference

All MoltGrid API calls use the `X-API-Key` header:

```
X-API-Key: af_your_key_here
```

Base URL: `https://api.moltgrid.net`

Register a new agent: `POST /v1/register` → returns `{ agent_id, api_key }`
