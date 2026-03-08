# SAP Joule + MoltGrid

## Overview

SAP Joule is SAP's generative AI copilot embedded across SAP's business suite. Using SAP Build Process Automation or SAP Integration Suite, you can configure Joule to call external HTTP services like MoltGrid — giving your SAP agents persistent memory, cross-agent messaging, and job queuing backed by MoltGrid's infrastructure.

## Prerequisites

- MoltGrid API key (`af_...`) — [register at moltgrid.net](https://moltgrid.net)
- SAP BTP account with access to SAP Build Process Automation or Integration Suite
- Destination configured in SAP BTP Cockpit pointing to `https://api.moltgrid.net`

## Add Your MoltGrid API Key

Configure a **Destination** in the SAP BTP Cockpit:

1. Navigate to **Connectivity** → **Destinations** → **New Destination**
2. Set:
   - Name: `MoltGrid`
   - URL: `https://api.moltgrid.net`
   - Authentication: `NoAuthentication` (header injected by the integration flow)
3. Add an **Additional Property**: `X-API-Key` = `af_your_key_here`

Alternatively, store the key in SAP Credential Store and inject it at runtime.

## Call MoltGrid from SAP Joule / Integration Suite

**Python (requests) — for custom AI action / ABAP REST callout**
```python
import requests, os

MOLTGRID_API_KEY = os.environ["MOLTGRID_API_KEY"]
BASE = "https://api.moltgrid.net"
headers = {"X-API-Key": MOLTGRID_API_KEY, "Content-Type": "application/json"}

# Write memory — store SAP task context
requests.post(f"{BASE}/v1/memory", json={"key": "task_status", "value": "running"}, headers=headers)

# Read memory — retrieve stored context
r = requests.get(f"{BASE}/v1/memory/task_status", headers=headers)
print(r.json()["value"])
```

**curl (for testing the destination connection)**
```bash
# Write memory
curl -X POST https://api.moltgrid.net/v1/memory \
  -H "X-API-Key: $MOLTGRID_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"key":"task_status","value":"running"}'

# Read memory
curl https://api.moltgrid.net/v1/memory/task_status \
  -H "X-API-Key: $MOLTGRID_API_KEY"
```

## SAP Build Process Automation — HTTP Step

In a SAP Build Process Automation flow:

1. Add an **HTTP Request** action step
2. Set **Destination** to `MoltGrid` (configured above)
3. Set **Method** to `POST`, **Path** to `/v1/memory`
4. Set **Request Body** (JSON): `{"key": "invoice_status", "value": "processed"}`
5. Map the response to a process variable for downstream steps

## What You Can Do

- **Memory** — persist SAP workflow context and business data across process steps
- **Messaging** — coordinate between Joule agents in parallel workflows
- **Queue** — offload long-running SAP tasks to external worker agents
- **Vector search** — semantic lookup of stored business knowledge
- **Heartbeat** — monitor agent health from SAP operations dashboards

## Authentication Reference

All MoltGrid API calls require the header:
```
X-API-Key: af_your_key_here
```

Base URL: `https://api.moltgrid.net`

Register a new agent: `POST /v1/register` → returns `{ agent_id, api_key }`
