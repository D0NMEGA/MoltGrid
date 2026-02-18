#!/usr/bin/env python3
"""MoltGrid CLI - Command-line interface for MoltGrid agent platform."""

import argparse
import json
import os
import sys
from pathlib import Path

try:
    from moltgrid import MoltGrid
except ImportError:
    print("Error: moltgrid module not found. Install with: pip install moltgrid", file=sys.stderr)
    sys.exit(1)

# ANSI color codes
RED = "\033[91m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
RESET = "\033[0m"

CONFIG_PATH = Path.home() / ".moltgrid" / "config.json"


def load_config():
    """Load configuration from ~/.moltgrid/config.json."""
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH) as f:
            return json.load(f)
    return {}


def save_config(config):
    """Save configuration to ~/.moltgrid/config.json."""
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_PATH, "w") as f:
        json.dump(config, f, indent=2)


def get_client(args):
    """Get MoltGrid client from config or env var."""
    api_key = os.getenv("MOLTGRID_API_KEY")
    base_url = None

    if not api_key:
        config = load_config()
        api_key = config.get("api_key")
        base_url = config.get("base_url")

    if not api_key:
        error("No API key found. Run 'moltgrid config --api-key KEY' or set MOLTGRID_API_KEY")
        sys.exit(1)

    return MoltGrid(api_key=api_key, base_url=base_url)


def success(msg):
    """Print success message in green."""
    print(f"{GREEN}{msg}{RESET}")


def error(msg):
    """Print error message in red."""
    print(f"{RED}Error: {msg}{RESET}", file=sys.stderr)


def print_json(data):
    """Print data as formatted JSON."""
    print(json.dumps(data, indent=2))


def print_table(headers, rows):
    """Print data as a formatted table."""
    if not rows:
        print("(empty)")
        return

    col_widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            col_widths[i] = max(col_widths[i], len(str(cell)))

    header_row = "  ".join(h.ljust(w) for h, w in zip(headers, col_widths))
    print(header_row)
    print("-" * len(header_row))

    for row in rows:
        print("  ".join(str(cell).ljust(w) for cell, w in zip(row, col_widths)))


def cmd_register(args):
    """Register a new agent."""
    name = args.name or "cli-agent"
    result = MoltGrid.register(name=name, description="Agent registered via CLI")

    if args.json:
        print_json(result)
    else:
        api_key = result.get("api_key", result.get("apiKey"))
        agent_id = result.get("agent_id", result.get("agentId"))
        success(f"Registered agent: {agent_id}")
        print(f"API Key: {api_key}")

        config = load_config()
        config["api_key"] = api_key
        save_config(config)
        print(f"Saved to {CONFIG_PATH}")


def cmd_config(args):
    """Configure API credentials."""
    config = load_config()

    if args.api_key:
        config["api_key"] = args.api_key
    if args.base_url:
        config["base_url"] = args.base_url

    save_config(config)
    success(f"Configuration saved to {CONFIG_PATH}")


def cmd_status(args):
    """Show agent status and stats."""
    mg = get_client(args)
    stats = mg.get_stats()

    if args.json:
        print_json(stats)
    else:
        print(f"Agent ID: {stats.get('agent_id', stats.get('agentId'))}")
        print(f"Uptime: {stats.get('uptime_seconds', 0)}s")
        print(f"Jobs Completed: {stats.get('jobs_completed', 0)}")
        print(f"Messages Received: {stats.get('messages_received', 0)}")


def cmd_memory(args):
    """Handle memory operations."""
    mg = get_client(args)

    if args.memory_cmd == "set":
        mg.memory_set(args.key, args.value, namespace=args.namespace, ttl_seconds=args.ttl)
        if not args.json:
            success(f"Stored {args.key}")

    elif args.memory_cmd == "get":
        result = mg.memory_get(args.key, namespace=args.namespace)
        if args.json:
            print_json(result)
        else:
            print(result.get("value", ""))

    elif args.memory_cmd == "list":
        items = mg.memory_list(namespace=args.namespace, prefix=args.prefix)
        if args.json:
            print_json(items)
        else:
            rows = [[item["key"], item.get("value", "")[:50]] for item in items]
            print_table(["Key", "Value"], rows)

    elif args.memory_cmd == "delete":
        mg.memory_delete(args.key, namespace=args.namespace)
        if not args.json:
            success(f"Deleted {args.key}")


def cmd_queue(args):
    """Handle queue operations."""
    mg = get_client(args)

    if args.queue_cmd == "submit":
        result = mg.queue_submit(args.payload, priority=args.priority, max_attempts=args.max_attempts)
        if args.json:
            print_json(result)
        else:
            success(f"Submitted job: {result.get('job_id', result.get('jobId'))}")

    elif args.queue_cmd == "claim":
        result = mg.queue_claim(queue_name=args.queue)
        if args.json:
            print_json(result)
        else:
            if result:
                print(f"Claimed job: {result.get('job_id', result.get('jobId'))}")
                print(f"Payload: {result.get('payload')}")
            else:
                print("No jobs available")

    elif args.queue_cmd == "complete":
        mg.queue_complete(args.job_id, result=args.result)
        if not args.json:
            success(f"Completed job: {args.job_id}")

    elif args.queue_cmd == "fail":
        mg.queue_fail(args.job_id, reason=args.reason)
        if not args.json:
            success(f"Failed job: {args.job_id}")

    elif args.queue_cmd == "list":
        jobs = mg.queue_list(queue_name=args.queue, status=args.status)
        if args.json:
            print_json(jobs)
        else:
            rows = [[job.get("job_id", job.get("jobId")), job.get("status"), job.get("priority")] for job in jobs]
            print_table(["Job ID", "Status", "Priority"], rows)

    elif args.queue_cmd == "dead-letter":
        jobs = mg.queue_dead_letter(queue_name=args.queue)
        if args.json:
            print_json(jobs)
        else:
            rows = [[job.get("job_id", job.get("jobId")), job.get("error", "")[:50]] for job in jobs]
            print_table(["Job ID", "Error"], rows)

    elif args.queue_cmd == "replay":
        result = mg.queue_replay(args.job_id)
        if args.json:
            print_json(result)
        else:
            success(f"Replayed job: {args.job_id}")


def cmd_send(args):
    """Send message to another agent."""
    mg = get_client(args)
    result = mg.send_message(args.agent_id, args.payload, channel=args.channel)

    if args.json:
        print_json(result)
    else:
        success(f"Sent message to {args.agent_id}")


def cmd_inbox(args):
    """Get inbox messages."""
    mg = get_client(args)
    messages = mg.get_inbox(channel=args.channel, unread_only=not args.all)

    if args.json:
        print_json(messages)
    else:
        rows = [[msg.get("from_agent_id", msg.get("fromAgentId")), msg.get("payload", "")[:50]] for msg in messages]
        print_table(["From", "Payload"], rows)


def cmd_heartbeat(args):
    """Send heartbeat."""
    mg = get_client(args)
    mg.heartbeat(status=args.status)

    if not args.json:
        success("Heartbeat sent")


def cmd_health(args):
    """Check system health."""
    mg = get_client(args)
    health = mg.get_health()

    if args.json:
        print_json(health)
    else:
        print(f"Status: {health.get('status')}")
        print(f"Version: {health.get('version')}")


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(description="MoltGrid CLI")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # register
    p_register = subparsers.add_parser("register", help="Register new agent")
    p_register.add_argument("--name", help="Agent name")

    # config
    p_config = subparsers.add_parser("config", help="Configure credentials")
    p_config.add_argument("--api-key", help="API key")
    p_config.add_argument("--base-url", help="Base URL")

    # status
    subparsers.add_parser("status", help="Show agent status")

    # memory
    p_memory = subparsers.add_parser("memory", help="Memory operations")
    memory_sub = p_memory.add_subparsers(dest="memory_cmd", required=True)
    memory_set = memory_sub.add_parser("set")
    memory_set.add_argument("key")
    memory_set.add_argument("value")
    memory_set.add_argument("--namespace")
    memory_set.add_argument("--ttl", type=int)
    memory_get = memory_sub.add_parser("get")
    memory_get.add_argument("key")
    memory_get.add_argument("--namespace")
    memory_list = memory_sub.add_parser("list")
    memory_list.add_argument("--namespace")
    memory_list.add_argument("--prefix")
    memory_del = memory_sub.add_parser("delete")
    memory_del.add_argument("key")
    memory_del.add_argument("--namespace")

    # queue
    p_queue = subparsers.add_parser("queue", help="Queue operations")
    queue_sub = p_queue.add_subparsers(dest="queue_cmd", required=True)
    queue_submit = queue_sub.add_parser("submit")
    queue_submit.add_argument("payload")
    queue_submit.add_argument("--priority", type=int, default=5)
    queue_submit.add_argument("--max-attempts", type=int, default=3)
    queue_claim = queue_sub.add_parser("claim")
    queue_claim.add_argument("--queue")
    queue_complete = queue_sub.add_parser("complete")
    queue_complete.add_argument("job_id")
    queue_complete.add_argument("--result")
    queue_fail = queue_sub.add_parser("fail")
    queue_fail.add_argument("job_id")
    queue_fail.add_argument("--reason")
    queue_list = queue_sub.add_parser("list")
    queue_list.add_argument("--queue")
    queue_list.add_argument("--status")
    queue_dl = queue_sub.add_parser("dead-letter")
    queue_dl.add_argument("--queue")
    queue_replay = queue_sub.add_parser("replay")
    queue_replay.add_argument("job_id")

    # send
    p_send = subparsers.add_parser("send", help="Send message")
    p_send.add_argument("agent_id")
    p_send.add_argument("payload")
    p_send.add_argument("--channel")

    # inbox
    p_inbox = subparsers.add_parser("inbox", help="Get messages")
    p_inbox.add_argument("--channel")
    p_inbox.add_argument("--all", action="store_true", help="Include read messages")

    # heartbeat
    p_heartbeat = subparsers.add_parser("heartbeat", help="Send heartbeat")
    p_heartbeat.add_argument("--status")

    # health
    subparsers.add_parser("health", help="Check system health")

    args = parser.parse_args()

    try:
        if args.command == "register":
            cmd_register(args)
        elif args.command == "config":
            cmd_config(args)
        elif args.command == "status":
            cmd_status(args)
        elif args.command == "memory":
            cmd_memory(args)
        elif args.command == "queue":
            cmd_queue(args)
        elif args.command == "send":
            cmd_send(args)
        elif args.command == "inbox":
            cmd_inbox(args)
        elif args.command == "heartbeat":
            cmd_heartbeat(args)
        elif args.command == "health":
            cmd_health(args)
    except Exception as e:
        error(str(e))
        sys.exit(1)


if __name__ == "__main__":
    main()
