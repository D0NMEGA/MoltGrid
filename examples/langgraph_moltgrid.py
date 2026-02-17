"""
LangGraph + MoltGrid — Persistent state that survives restarts.

This example shows a 3-node graph (research -> draft -> review) where each
node's output is checkpointed to MoltGrid memory. On restart, the graph
resumes from the last completed node instead of starting over.

Prerequisites:
    pip install requests
    # Copy moltgrid.py to your project or: pip install moltgrid (coming soon)

Usage:
    export MOLTGRID_API_KEY="af_your_key_here"
    python langgraph_moltgrid.py
"""

import os
import json
from moltgrid import MoltGrid

API_KEY = os.environ["MOLTGRID_API_KEY"]
mg = MoltGrid(api_key=API_KEY)

NAMESPACE = "langgraph"
WORKFLOW_ID = "news-pipeline-001"

# ── Node functions (replace with your LLM calls) ─────────────────────────────

def research(state):
    print("[research] Gathering sources...")
    state["sources"] = ["arxiv.org/1234", "news.ycombinator.com/5678"]
    state["last_node"] = "research"
    return state

def draft(state):
    print("[draft] Writing summary from sources...")
    state["draft"] = f"Summary of {len(state['sources'])} sources: ..."
    state["last_node"] = "draft"
    return state

def review(state):
    print("[review] Reviewing draft...")
    state["approved"] = True
    state["last_node"] = "review"
    return state

# ── Checkpoint helpers ────────────────────────────────────────────────────────

NODES = [("research", research), ("draft", draft), ("review", review)]

def save_checkpoint(node_name, state):
    """Persist state after each node completes."""
    mg.memory_set(f"{WORKFLOW_ID}:{node_name}", json.dumps(state), namespace=NAMESPACE)
    mg.memory_set(f"{WORKFLOW_ID}:latest", node_name, namespace=NAMESPACE)
    print(f"  -> Checkpoint saved: {node_name}")

def restore_checkpoint():
    """Load the last completed node and its state. Returns (resume_index, state)."""
    try:
        latest = mg.memory_get(f"{WORKFLOW_ID}:latest", namespace=NAMESPACE)
        node_name = latest["value"]
        state_raw = mg.memory_get(f"{WORKFLOW_ID}:{node_name}", namespace=NAMESPACE)
        state = json.loads(state_raw["value"])
        resume_after = [name for name, _ in NODES].index(node_name) + 1
        print(f"Resuming after '{node_name}' (step {resume_after}/{len(NODES)})")
        return resume_after, state
    except Exception:
        print("No checkpoint found — starting fresh.")
        return 0, {}

# ── Run the graph ─────────────────────────────────────────────────────────────

def run():
    start_idx, state = restore_checkpoint()

    for i, (name, fn) in enumerate(NODES):
        if i < start_idx:
            continue
        state = fn(state)
        save_checkpoint(name, state)

    print(f"\nPipeline complete. Approved: {state.get('approved')}")

if __name__ == "__main__":
    run()
