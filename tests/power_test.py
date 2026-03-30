"""4x2 Agent Power Test - 8 agents across 2 accounts exercising all core features."""
import psycopg, hashlib, uuid, json, requests, sys

BASE = "http://localhost:8000"
DB_URL = "postgresql://moltgrid:JWf0yg5axfOLSpGMzZut1YXfTzx7rL64az1OR83r@127.0.0.1:5432/moltgrid"

def h(k):
    return {"X-API-Key": k, "Content-Type": "application/json"}

def main():
    conn = psycopg.connect(DB_URL)
    cur = conn.cursor()
    agents = []
    for email in ["test1@test.com", "test2@test.com"]:
        cur.execute(
            "SELECT a.agent_id, a.name FROM agents a JOIN users u ON a.owner_id=u.user_id "
            "WHERE u.email=%s AND a.name LIKE %s ORDER BY a.name", (email, "%Test%")
        )
        for r in cur.fetchall():
            nk = "mg_" + uuid.uuid4().hex
            cur.execute("UPDATE agents SET api_key_hash=%s WHERE agent_id=%s",
                       (hashlib.sha256(nk.encode()).hexdigest(), r[0]))
            agents.append({"id": r[0], "nm": r[1], "key": nk, "ow": email})
    conn.commit()
    cur.close()
    conn.close()

    print(f"POWER TEST: {len(agents)} agents across 2 accounts\n")
    p, f = 0, 0

    def ck(lb, ok, dt):
        nonlocal p, f
        tag = "PASS" if ok else "FAIL"
        if ok: p += 1
        else: f += 1
        print(f"  [{tag}] {lb}: {dt}")

    # 1. Heartbeats
    print("1. Heartbeats")
    for a in agents:
        r = requests.post(BASE + "/v1/heartbeat", headers=h(a["key"]))
        ck("hb:" + a["nm"], r.status_code == 200, r.status_code)

    # 2. Memory store
    print("\n2. Memory Store")
    for a in agents:
        r = requests.post(BASE + "/v1/memory", headers=h(a["key"]),
                         json={"key": "pw_test", "value": "hello from " + a["nm"]})
        ck("ms:" + a["nm"], r.status_code == 200, r.status_code)

    # 3. Cross-agent relay
    print("\n3. Cross-Agent Relay")
    for i in range(0, len(agents), 2):
        s, rv = agents[i], agents[i + 1]
        r = requests.post(BASE + "/v1/relay/send", headers=h(s["key"]),
                         json={"to_agent": rv["id"], "channel": "test", "payload": "msg from " + s["nm"]})
        ck(s["nm"] + " -> " + rv["nm"], r.status_code == 200, r.status_code)

    # 4. Inbox check
    print("\n4. Inbox Check")
    for i in range(1, len(agents), 2):
        a = agents[i]
        r = requests.get(BASE + "/v1/relay/inbox", headers=h(a["key"]))
        mc = len(r.json().get("messages", [])) if r.status_code == 200 else 0
        ck("inbox:" + a["nm"], r.status_code == 200 and mc > 0, f"{mc} msgs")

    # 5. Job submit + claim
    print("\n5. Job Submit + Claim")
    for i in [0, 4]:
        s, c = agents[i], agents[i + 1]
        r1 = requests.post(BASE + "/v1/queue/submit", headers=h(s["key"]),
                          json={"payload": {"task": "power_test"}, "reward": 5})
        if r1.status_code == 200:
            jid = r1.json().get("job_id")
            r2 = requests.post(BASE + "/v1/queue/claim", headers=h(c["key"]),
                              json={"job_id": jid})
            ck(f"job:{s['nm']}->{c['nm']}", r2.status_code == 200,
               f"sub:{r1.status_code} cl:{r2.status_code}")
        else:
            ck(f"job:{s['nm']}", False, f"sub failed:{r1.status_code} {r1.text[:80]}")

    # 6. Infrastructure
    print("\n6. Infrastructure")
    r = requests.get(BASE + "/v1/directory/search?q=Test")
    n = len(r.json().get("agents", [])) if r.status_code == 200 else 0
    ck("directory", r.status_code == 200 and n >= 8, f"{n} agents found")

    r = requests.get(BASE + "/v1/health")
    ck("health", r.json().get("status") == "operational", r.json().get("status"))

    r = requests.get(BASE + "/metrics")
    ck("metrics", r.status_code == 200, r.status_code)

    # 7. Memory read-back
    print("\n7. Memory Read-back")
    for a in agents:
        r = requests.get(BASE + "/v1/memory/pw_test", headers=h(a["key"]))
        hv = bool(r.json().get("value")) if r.status_code == 200 else False
        ck("mg:" + a["nm"], r.status_code == 200 and hv, r.status_code)

    # Summary
    t = p + f
    sep = "=" * 50
    print(f"\n{sep}")
    print(f"POWER TEST: {p}/{t} passed ({f} failed)")
    print(f"{sep}")
    return 0 if f == 0 else 1

if __name__ == "__main__":
    sys.exit(main())
