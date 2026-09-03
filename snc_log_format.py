#!/usr/bin/env -S uv run --quiet --script
# /// script
# dependencies = ["pyyaml"]
# ///
"""Format SNC study-log JSON lines for reading in a terminal.

    tail -f <session>.jsonl | ./snc_log_format.py

Each record prints as its event type, then its payload as YAML.
"""

import json
import sys

import yaml

for line in sys.stdin:
    if not line.strip():
        continue
    rec = json.loads(line)
    kind = rec.get("type", "")
    if kind.startswith(("run.", "app.")) or kind == "widget.mouseMove":
        continue
    payload = rec.get("payload")
    if kind == "vis.update" and isinstance(payload, dict):
        payload = {k: v for k, v in payload.items() if k not in ("modelBefore", "modelAfter")}
    print(kind)
    body = yaml.safe_dump(payload, sort_keys=False, allow_unicode=True, width=120)
    print("".join("  " + l for l in body.splitlines(True)), flush=True)
