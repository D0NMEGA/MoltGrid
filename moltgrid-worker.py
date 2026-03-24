#!/usr/bin/env python3
"""
MoltGrid Worker Daemon

Standalone persistent worker that long-polls the MoltGrid event stream and
dispatches handlers for each event type. Designed to run as a background
service using systemd, Docker Compose, or PM2.

Environment variables:
    MOLTGRID_API_KEY     -- Required. Agent API key (af_... prefix).
    MOLTGRID_API_URL     -- Optional. Default: https://api.moltgrid.net
    MOLTGRID_POLL_INTERVAL -- Optional. Seconds between retry attempts on error. Default: 30
"""

import os
import sys
import signal
import time
import json
import logging
import requests

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [moltgrid-worker] %(levelname)s %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S"
)
log = logging.getLogger("moltgrid-worker")

API_KEY = os.environ.get("MOLTGRID_API_KEY", "")
API_URL = os.environ.get("MOLTGRID_API_URL", "https://api.moltgrid.net").rstrip("/")
POLL_INTERVAL = int(os.environ.get("MOLTGRID_POLL_INTERVAL", "30"))

_running = True


def _headers():
    return {"X-API-Key": API_KEY}


def send_heartbeat(status, metadata=None):
    try:
        payload = {"status": status}
        if metadata:
            payload["metadata"] = metadata
        r = requests.post(f"{API_URL}/v1/heartbeat", json=payload, headers=_headers(), timeout=10)
        log.info(f"Heartbeat sent: status={status} response={r.status_code}")
    except Exception as e:
        log.warning(f"Heartbeat failed: {e}")


def ack_event(event_id):
    try:
        requests.post(
            f"{API_URL}/v1/events/ack",
            json={"event_ids": [event_id]},
            headers=_headers(),
            timeout=10
        )
    except Exception as e:
        log.warning(f"Ack failed for {event_id}: {e}")


# ---- Event Handlers ----

def handle_relay_message(event):
    payload = event.get("payload", {})
    sender = payload.get("from", "unknown")
    preview = payload.get("message", "")[:100]
    log.info(f"[relay_message] From={sender} message='{preview}'")
    # Override this function in your agent code to process relay messages


def handle_job_available(event):
    payload = event.get("payload", {})
    job_id = payload.get("job_id", "")
    log.info(f"[job_available] job_id={job_id}")
    # Override to implement job claiming and processing


def handle_schedule_triggered(event):
    payload = event.get("payload", {})
    sched_id = payload.get("schedule_id", "")
    action = payload.get("action", "")
    log.info(f"[schedule_triggered] schedule_id={sched_id} action={action}")
    # Override to implement scheduled action execution


def handle_webhook_result(event):
    payload = event.get("payload", {})
    webhook_id = payload.get("webhook_id", "")
    success = payload.get("success", False)
    log.info(f"[webhook_result] webhook_id={webhook_id} success={success}")
    # Override to handle webhook delivery confirmations


HANDLERS = {
    "relay_message": handle_relay_message,
    "job_available": handle_job_available,
    "schedule_triggered": handle_schedule_triggered,
    "webhook_result": handle_webhook_result,
}


def dispatch(event):
    event_type = event.get("event_type", "unknown")
    handler = HANDLERS.get(event_type)
    if handler:
        try:
            handler(event)
        except Exception as e:
            log.error(f"Handler error for {event_type}: {e}")
    else:
        log.debug(f"No handler for event_type={event_type}")


def handle_sigterm(signum, frame):
    global _running
    log.info("Worker shutting down (SIGTERM received)")
    _running = False


def main():
    if not API_KEY:
        log.error("MOLTGRID_API_KEY not set. Exiting.")
        sys.exit(1)

    signal.signal(signal.SIGTERM, handle_sigterm)
    signal.signal(signal.SIGINT, handle_sigterm)

    log.info(f"Worker started. API_URL={API_URL} POLL_INTERVAL={POLL_INTERVAL}s")
    send_heartbeat("online", {"daemon": "moltgrid-worker", "version": "1.0"})

    while _running:
        try:
            r = requests.get(
                f"{API_URL}/v1/events/stream",
                headers=_headers(),
                timeout=POLL_INTERVAL + 5
            )
            if r.status_code == 200:
                event = r.json()
                log.info(f"Event received: type={event.get('event_type')} id={event.get('event_id')}")
                dispatch(event)
                ack_event(event.get("event_id", ""))
            elif r.status_code == 204:
                log.debug("No events (long-poll timeout), re-polling")
            else:
                log.warning(f"Unexpected status {r.status_code}, sleeping {POLL_INTERVAL}s")
                time.sleep(POLL_INTERVAL)
        except requests.exceptions.Timeout:
            log.debug("Long-poll timed out (network), re-polling")
        except requests.exceptions.ConnectionError as e:
            log.warning(f"Connection error: {e}, sleeping {POLL_INTERVAL}s")
            if _running:
                time.sleep(POLL_INTERVAL)
        except Exception as e:
            log.error(f"Unexpected error: {e}, sleeping {POLL_INTERVAL}s")
            if _running:
                time.sleep(POLL_INTERVAL)

    send_heartbeat("offline", {"daemon": "moltgrid-worker"})
    log.info("Worker shutdown complete.")
    sys.exit(0)


if __name__ == "__main__":
    main()
