#!/usr/bin/env python3
"""Seed the DEMO tenant with fixtures (never his real memory). Idempotent.

    env -u PYTHONPATH .venv/bin/python fixtures/seed_demo.py [--db PATH] [--tenant kint-demo]

The rows are what a coding agent would have learned over a few sessions: a release rule the
climax hinges on, people, priorities, a runbook, and journal events.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from kint import store  # noqa: E402


def seed(client) -> int:
    n = 0
    client.set_entity("rules", "release-gate", {
        "rule": "never ship on a Friday; every release needs a green deadlift test and a second reviewer",
        "since": "2026-05-01", "owner": "elpabl0", "source": "postmortem of the May 19 incident",
    }, status="active"); n += 1
    client.set_entity("rules", "destructive-commands", {
        "rule": "never rm -rf a shared path; ask what processes anchor there first",
        "since": "2026-04-28",
    }, status="active"); n += 1
    client.set_entity("people", "elpabl0", {"role": "founder", "tz": "WIB", "prefers": "short answers, no walls of text"}); n += 1
    client.set_entity("people", "reviewer-a", {"role": "second reviewer", "reachable": "attn"}); n += 1
    client.set_entity("projects", "kint", {"what": "Sibyl Memory that outlives the laptop", "chain": "Base", "status": "hackathon build"}); n += 1
    client.set_entity("projects", "sigil", {"what": "compliance layer for the agentic economy", "status": "paused"}); n += 1
    client.set_entity("facts", "deploy-window", {"window": "Tue to Thu, 09:00 to 17:00 WIB", "why": "support coverage"}); n += 1
    client.set_state("priorities", {"top": ["kint submission", "sigil audit"], "updated": "2026-09-09"}); n += 1
    client.set_state("session", {"last_task": "wire the harnesses to kint-server", "open_questions": ["OpenClaw MCP config"]}); n += 1
    client.set_reference("runbook-release", "# Release runbook\n\n1. Green tests.\n2. Second reviewer signs off.\n3. Never on a Friday.\n4. Tag, seal, announce.\n",
                         metadata={"format": "markdown", "version": 3}); n += 1
    client.set_reference("glossary", "epoch: one anchored change set. space: keccak of the tenant id. leaf: hash of a stored row.",
                         metadata={"format": "text"}); n += 1
    client.write_event(acted={"kind": "decision", "body": {"what": "adopted the Friday release rule after the May 19 incident"}},
                       extra={"category": "rules", "name": "release-gate"}, ts="2026-05-01T09:00:00.000Z"); n += 1
    client.write_event(evaluated={"q": "ship the hotfix tonight?"}, acted={"kind": "refusal", "body": {"why": "Friday"}},
                       forward={"next": "Monday 09:00 WIB"}, ts="2026-08-28T15:30:00.000Z"); n += 1
    client.write_event(acted={"kind": "observation", "body": {"what": "kura send --wallet is ignored; switch the default wallet first"}},
                       ts="2026-09-09T08:05:00.000Z"); n += 1
    return n


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--db")
    p.add_argument("--tenant", default=os.environ.get("KINT_TENANT", "kint-demo"))
    a = p.parse_args()
    client = store.open_client(a.db, a.tenant)
    n = seed(client)
    print(f"seeded {n} rows into tenant {a.tenant} at {client.storage.db_path}")


if __name__ == "__main__":
    main()
