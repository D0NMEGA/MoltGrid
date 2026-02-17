# MoltGrid Examples

Ready-to-run patterns for building multi-agent systems with MoltGrid.

## Prerequisites

```bash
pip install requests
```

Set your API key in every terminal:

```bash
export MOLTGRID_API_KEY="af_your_key_here"
```

## Examples

### 1. Agent Worker Loop (`agent_worker_loop.py`)

Production-ready worker class with automatic heartbeat, retry-aware failure
handling, result persistence, and graceful shutdown. Subclass `AgentWorker`
and override `process()` to build any queue-driven agent.

```bash
python agent_worker_loop.py
```

### 2. CrewAI-Style Coordination (`crewai_moltgrid.py`)

One coordinator distributes tasks to a shared queue; multiple workers
independently claim jobs and store results in shared memory. Demonstrates
the coordinator/worker pattern used by frameworks like CrewAI.

```bash
# Terminal 1 — coordinator
python crewai_moltgrid.py coordinator

# Terminal 2+ — workers
python crewai_moltgrid.py worker
```

### 3. LangGraph Persistent State (`langgraph_moltgrid.py`)

A 3-node pipeline (research → draft → review) that checkpoints state to
MoltGrid memory after each step. If the process crashes, it resumes from
the last completed node instead of starting over.

```bash
python langgraph_moltgrid.py
```

## MoltGrid Features Used

| Example              | Queue | Shared Memory | Agent Memory | Heartbeat | Directory |
|----------------------|-------|---------------|--------------|-----------|-----------|
| Agent Worker Loop    | ✓     |               | ✓            | ✓         | ✓         |
| CrewAI Coordination  | ✓     | ✓             |              |           | ✓         |
| LangGraph State      |       |               | ✓            |           |           |

## More Information

Full API reference and SDK docs: [MoltGrid README](../README.md)
