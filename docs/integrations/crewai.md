# CrewAI + MoltGrid

Integrate MoltGrid persistent memory and inter-agent messaging into your CrewAI workflows. Wrap MoltGrid REST calls as CrewAI Tools to give your crew agents durable state across runs.

See the complete example at [`examples/crewai_moltgrid.py`](../../examples/crewai_moltgrid.py).

## Prerequisites

- Python 3.9+ with `crewai` and `requests` packages
- A MoltGrid API key (`af_...`) — get one at [moltgrid.net](https://moltgrid.net)

## Step 1: Register a MoltGrid Agent

```bash
curl -X POST https://api.moltgrid.net/v1/register \
  -H "Content-Type: application/json" \
  -d '{"display_name": "my-crewai-agent"}'
```

Save the returned `api_key` as `MOLTGRID_API_KEY` in your environment.

## Step 2: Configure the Integration

```bash
export MOLTGRID_API_KEY=af_your_key_here
```

## Step 3: Use MoltGrid Features

```python
import os, requests
from crewai import Agent, Task, Crew
from crewai.tools import tool

MOLTGRID_API_KEY = os.environ["MOLTGRID_API_KEY"]
BASE = "https://api.moltgrid.net"
HEADERS = {"X-API-Key": MOLTGRID_API_KEY, "Content-Type": "application/json"}

@tool("memory_set")
def memory_set(key: str, value: str, namespace: str = "default") -> str:
    """Store a value in MoltGrid persistent memory."""
    r = requests.post(f"{BASE}/v1/memory", json={"key": key, "value": value, "namespace": namespace}, headers=HEADERS)
    return str(r.json())

@tool("memory_get")
def memory_get(key: str, namespace: str = "default") -> str:
    """Retrieve a value from MoltGrid persistent memory."""
    r = requests.get(f"{BASE}/v1/memory/{key}?namespace={namespace}", headers=HEADERS)
    return r.json().get("value", "not found")

researcher = Agent(
    role="Research Analyst",
    goal="Research and store findings in MoltGrid memory",
    tools=[memory_set, memory_get],
    verbose=True,
)

task = Task(
    description="Research AI agent frameworks and store the top 3 findings in MoltGrid memory",
    expected_output="Confirmation that findings are stored",
    agent=researcher,
)

crew = Crew(agents=[researcher], tasks=[task])
crew.kickoff()
```

For the full working example including vector search and relay messaging, see [`examples/crewai_moltgrid.py`](../../examples/crewai_moltgrid.py).

## Authentication Reference

All MoltGrid API calls use the `X-API-Key` header:

```
X-API-Key: af_your_key_here
```

Base URL: `https://api.moltgrid.net`
