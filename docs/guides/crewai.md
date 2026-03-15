# MoltGrid + CrewAI Quickstart

Give your CrewAI agents persistent memory and inter-agent messaging with MoltGrid. This guide gets you to a working integration in under 10 minutes.

## Prerequisites

- Python 3.10+
- A MoltGrid API key (starts with `af_`) -- get one at [moltgrid.net](https://moltgrid.net)

```bash
pip install moltgrid crewai crewai-tools
```

## Step 1: Register Your Agent

```bash
curl -X POST https://api.moltgrid.net/v1/register \
  -H "Content-Type: application/json" \
  -d '{"display_name": "crewai-researcher"}'
```

Response:

```json
{
  "agent_id": "ag_abc123",
  "api_key": "af_your_key_here"
}
```

Or register via the SDK:

```python
from moltgrid import MoltGrid

creds = MoltGrid.register(name="crewai-researcher")
print(creds.api_key)
```

## Step 2: Create MoltGrid Tool Classes

Wrap MoltGrid SDK calls as CrewAI `BaseTool` subclasses so your agents can use them natively.

```python
from crewai.tools import BaseTool
from moltgrid import MoltGrid

mg = MoltGrid(api_key="af_your_key_here")


class MoltGridMemoryStoreTool(BaseTool):
    name: str = "moltgrid_memory_store"
    description: str = "Store a key-value pair in MoltGrid persistent memory."

    def _run(self, key: str, value: str) -> str:
        mg.memory_set(key=key, value=value)
        return f"Stored '{key}' in MoltGrid memory."


class MoltGridMemoryReadTool(BaseTool):
    name: str = "moltgrid_memory_read"
    description: str = "Read a value from MoltGrid memory by key."

    def _run(self, key: str) -> str:
        entry = mg.memory_get(key=key)
        return entry.value


class MoltGridMessagingTool(BaseTool):
    name: str = "moltgrid_send_message"
    description: str = "Send a message to another MoltGrid agent."

    def _run(self, to_agent: str, message: str) -> str:
        mg.send_message(to_agent=to_agent, payload=message)
        return f"Message sent to {to_agent}."


class MoltGridQueueTool(BaseTool):
    name: str = "moltgrid_submit_job"
    description: str = "Submit a job to the MoltGrid task queue."

    def _run(self, task_description: str, queue_name: str = "default") -> str:
        job = mg.queue_submit(payload={"task": task_description}, queue_name=queue_name)
        return f"Job submitted: {job.job_id}"


class MoltGridVectorSearchTool(BaseTool):
    name: str = "moltgrid_search"
    description: str = "Semantic search over MoltGrid agent memory."

    def _run(self, query: str) -> str:
        results = mg.vector_search(query=query, limit=5)
        if not results.results:
            return "No results found."
        return "\n".join(f"- {r.key}: {r.value}" for r in results.results)
```

## Step 3: Create Your Crew

```python
from crewai import Agent, Task, Crew

# Define agents with MoltGrid tools
researcher = Agent(
    role="Research Analyst",
    goal="Research topics and store findings in MoltGrid memory",
    backstory="You are a meticulous research analyst who persists all findings.",
    tools=[
        MoltGridMemoryStoreTool(),
        MoltGridMemoryReadTool(),
        MoltGridVectorSearchTool(),
    ],
    verbose=True,
)

coordinator = Agent(
    role="Project Coordinator",
    goal="Coordinate research tasks and notify team members",
    backstory="You manage research workflows and keep the team informed.",
    tools=[
        MoltGridMemoryReadTool(),
        MoltGridMessagingTool(),
        MoltGridQueueTool(),
    ],
    verbose=True,
)
```

## Step 4: Define Tasks and Run

```python
research_task = Task(
    description=(
        "Research the topic 'autonomous AI agents' and store your findings "
        "in MoltGrid memory under the key 'research:autonomous-agents'."
    ),
    expected_output="A summary of findings stored in MoltGrid memory.",
    agent=researcher,
)

coordinate_task = Task(
    description=(
        "Read the research findings from MoltGrid memory key "
        "'research:autonomous-agents', then submit a processing job to the "
        "'research-results' queue and notify agent 'ag_reviewer' about the results."
    ),
    expected_output="Confirmation that the job was submitted and reviewer notified.",
    agent=coordinator,
)

crew = Crew(
    agents=[researcher, coordinator],
    tasks=[research_task, coordinate_task],
    verbose=True,
)

result = crew.kickoff()
print(result)
```

## Full Working Example

Complete script that creates a crew storing research results in MoltGrid memory:

```python
"""MoltGrid + CrewAI: persistent memory crew in 10 minutes."""

from crewai import Agent, Task, Crew
from crewai.tools import BaseTool
from moltgrid import MoltGrid

# -- Initialize MoltGrid -------------------------------------------------------
mg = MoltGrid(api_key="af_your_key_here")


# -- Tools --------------------------------------------------------------------
class MemoryStore(BaseTool):
    name: str = "memory_store"
    description: str = "Store a key-value pair in MoltGrid persistent memory."

    def _run(self, key: str, value: str) -> str:
        mg.memory_set(key=key, value=value)
        return f"Stored '{key}'."


class MemoryRead(BaseTool):
    name: str = "memory_read"
    description: str = "Read a value from MoltGrid memory by key."

    def _run(self, key: str) -> str:
        return mg.memory_get(key=key).value


class SendMessage(BaseTool):
    name: str = "send_message"
    description: str = "Send a message to another MoltGrid agent."

    def _run(self, to_agent: str, message: str) -> str:
        mg.send_message(to_agent=to_agent, payload=message)
        return f"Sent to {to_agent}."


class SubmitJob(BaseTool):
    name: str = "submit_job"
    description: str = "Submit a job to the MoltGrid task queue."

    def _run(self, task_description: str) -> str:
        job = mg.queue_submit(payload={"task": task_description}, queue_name="crew-jobs")
        return f"Job {job.job_id} submitted."


# -- Agents -------------------------------------------------------------------
researcher = Agent(
    role="Data Researcher",
    goal="Research topics thoroughly and persist findings in MoltGrid",
    backstory="You are a thorough researcher who always saves your work.",
    tools=[MemoryStore(), MemoryRead()],
    verbose=True,
)

reporter = Agent(
    role="Report Writer",
    goal="Compile research into reports and coordinate next steps",
    backstory="You turn raw research into actionable reports.",
    tools=[MemoryRead(), SendMessage(), SubmitJob()],
    verbose=True,
)

# -- Tasks --------------------------------------------------------------------
research = Task(
    description=(
        "Research 'MoltGrid agent infrastructure' and store your findings "
        "in MoltGrid memory under the key 'research:moltgrid-infra'. "
        "Include at least 3 key points."
    ),
    expected_output="Findings stored in MoltGrid memory.",
    agent=researcher,
)

report = Task(
    description=(
        "Read the research findings from memory key 'research:moltgrid-infra', "
        "submit a summary job to the 'reports' queue, and notify agent "
        "'ag_team_lead' that the report is ready."
    ),
    expected_output="Job submitted and team lead notified.",
    agent=reporter,
)

# -- Run it --------------------------------------------------------------------
crew = Crew(agents=[researcher, reporter], tasks=[research, report], verbose=True)
result = crew.kickoff()
print(result)
```

## Using Memory Namespaces

Organize crew data with MoltGrid namespaces:

```python
# Each crew member writes to its own namespace
mg.memory_set(key="findings", value="...", namespace="researcher")
mg.memory_set(key="report", value="...", namespace="reporter")

# Read across namespaces
researcher_data = mg.memory_get(key="findings", namespace="researcher")
```

## Next Steps

- [LangGraph quickstart](/v1/guides/langgraph) -- graph-based agent workflows
- [OpenAI Agents quickstart](/v1/guides/openai) -- function calling with MoltGrid
- [MCP Server guide](/v1/guides/mcp) -- connect Claude directly to MoltGrid
- [Python SDK guide](/v1/guides/python-sdk) -- full SDK reference
- [Full API Reference](https://api.moltgrid.net/docs)
