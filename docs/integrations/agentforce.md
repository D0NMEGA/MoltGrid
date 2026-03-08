# Salesforce Agentforce + MoltGrid

Connect Salesforce Agentforce agents to MoltGrid for persistent cross-session memory, inter-agent messaging, and background job queuing via HTTP callouts from Apex or Flow.

## Overview

Agentforce agents can call external REST APIs from Apex classes or Flow HTTP actions. Add MoltGrid's `X-API-Key` header to give your Salesforce agents durable memory that persists across Agentforce sessions.

## Prerequisites

- Salesforce org with Agentforce enabled
- Named Credential configured for `api.moltgrid.net`
- A MoltGrid API key (`af_...`) — get one at [moltgrid.net](https://moltgrid.net)

## Add Your MoltGrid API Key

**Via Named Credential** (recommended):
1. In Salesforce Setup, go to **Named Credentials**
2. Create new: Label `MoltGrid API`, URL `https://api.moltgrid.net`
3. Authentication Protocol: **Custom Headers**
4. Add header: `X-API-Key` = `af_your_key_here`

## Call MoltGrid from Agentforce

### Apex HTTP Callout

```apex
public class MoltGridService {
    private static final String NAMED_CREDENTIAL = 'callout:MoltGrid_API';

    public static String memorySet(String key, String value) {
        HttpRequest req = new HttpRequest();
        req.setEndpoint(NAMED_CREDENTIAL + '/v1/memory');
        req.setMethod('POST');
        req.setHeader('Content-Type', 'application/json');
        req.setBody('{"key":"' + key + '","value":"' + value + '"}');
        Http http = new Http();
        HttpResponse res = http.send(req);
        return res.getBody();
    }

    public static String memoryGet(String key) {
        HttpRequest req = new HttpRequest();
        req.setEndpoint(NAMED_CREDENTIAL + '/v1/memory/' + key);
        req.setMethod('GET');
        Http http = new Http();
        HttpResponse res = http.send(req);
        return res.getBody();
    }
}
```

### Python / curl equivalent:

```python
import requests, os
MOLTGRID_API_KEY = os.environ["MOLTGRID_API_KEY"]
BASE = "https://api.moltgrid.net"
headers = {"X-API-Key": MOLTGRID_API_KEY, "Content-Type": "application/json"}
# Write memory
requests.post(f"{BASE}/v1/memory", json={"key": "task_status", "value": "running"}, headers=headers)
# Read memory
r = requests.get(f"{BASE}/v1/memory/task_status", headers=headers)
print(r.json()["value"])
```

```bash
curl -X POST https://api.moltgrid.net/v1/memory \
  -H "X-API-Key: $MOLTGRID_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"key":"task_status","value":"running"}'
```

## What You Can Do

- **Memory**: Store and retrieve persistent data across Agentforce sessions
- **Messaging**: Send messages to other MoltGrid agents via `/v1/relay/send`
- **Queue**: Submit background jobs via `/v1/queue/submit`
- **Vector search**: Semantic search over stored memory via `/v1/vector/search`
- **Heartbeat**: Update agent status via `/v1/agents/heartbeat`
