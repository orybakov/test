#!/usr/bin/env python3
"""Send a notification using only Python's standard library."""
import argparse
import json
import os
from pathlib import Path
from urllib.request import Request, urlopen

parser = argparse.ArgumentParser(description="Send event to Voice Sentinel")
parser.add_argument("source")
parser.add_argument("title")
parser.add_argument("message", nargs="?", default="")
parser.add_argument("--level", choices=["auto", "critical", "important", "normal", "silent"], default="auto")
parser.add_argument("--event-id", default=None)
parser.add_argument("--url", default="http://127.0.0.1:8099")
args = parser.parse_args()
key = os.environ.get("SENTINEL_API_KEY", "")
if not key and Path(".env").exists():
    for line in Path(".env").read_text().splitlines():
        if line.startswith("SENTINEL_API_KEY="):
            key = line.split("=", 1)[1]
if not key:
    parser.error("Missing SENTINEL_API_KEY or .env; run from project directory")
payload = {"source": args.source, "title": args.title, "message": args.message,
           "level": args.level, "event_id": args.event_id}
req = Request(args.url.rstrip("/") + "/api/events", data=json.dumps(payload).encode(),
              headers={"X-API-Key": key, "Content-Type": "application/json"}, method="POST")
with urlopen(req, timeout=10) as r:
    print(r.read().decode())
