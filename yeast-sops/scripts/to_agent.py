#!/usr/bin/env python3
"""
yeast-sops → Cortex agent compiler
==================================

Takes an SOP (typically an instance) and generates a skeleton Cortex
agent YAML. The output is a starting point — not a finished agent.

Usage:
  python scripts/to_agent.py --sop SOP-ACC-I001 > ../cortex-agents/agents/bank-rec-taf.yaml
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.exit("Missing dependency: pip install pyyaml")


REPO_ROOT = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = REPO_ROOT / "templates"
INSTANCES_DIR = REPO_ROOT / "instances"

FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def find_sop(sop_id: str) -> Path:
    for root in (INSTANCES_DIR, TEMPLATES_DIR):
        for md in root.rglob("*.md"):
            if md.name.startswith(sop_id):
                return md
    sys.exit(f"SOP {sop_id} not found")


def parse(md_path: Path) -> tuple[dict, str]:
    text = md_path.read_text(encoding="utf-8")
    m = FRONTMATTER_RE.match(text)
    if not m:
        sys.exit(f"{md_path}: missing frontmatter")
    return yaml.safe_load(m.group(1)), text[m.end():]


def to_agent_yaml(sop: dict, body: str, source_path: Path) -> dict:
    """Map SOP frontmatter to Cortex agent skeleton."""
    sop_id = sop["id"]
    agent_id = "agent-" + sop_id.lower().replace("sop-", "")

    trigger = sop.get("trigger", "manual")
    cortex_trigger: dict
    if trigger == "scheduled":
        cortex_trigger = {"type": "schedule", "cron": sop.get("schedule")}
    elif trigger == "webhook":
        cortex_trigger = {"type": "webhook"}
    elif trigger == "event":
        cortex_trigger = {"type": "event", "source": "TODO"}
    else:
        cortex_trigger = {"type": "manual"}

    agent = {
        "apiVersion": "cortex.yeast-group.cz/v1",
        "kind": "Agent",
        "metadata": {
            "id": agent_id,
            "name": sop.get("name"),
            "tenant": (sop.get("tenant") or {}).get("scope", "template"),
            "source_sop": sop_id,
            "version": sop.get("version"),
        },
        "spec": {
            "description": sop.get("name"),
            "automation_level": sop.get("automation_level"),
            "criticality": sop.get("criticality"),
            "trigger": cortex_trigger,
            "tools": sop.get("required_tools") or [],
            "permissions": sop.get("required_permissions") or [],
            "connectors": sop.get("required_connectors") or [],
            "success_criteria": sop.get("success_criteria") or [],
            "hitl_gates": sop.get("human_approval_required") or [],
            "system_prompt_ref": f"sops://{source_path.as_posix()}",
            "escalation": {
                "on_error": sop.get("owner"),
                "on_approval_needed": sop.get("business_owner") or sop.get("owner"),
            },
        },
    }
    return agent


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sop", required=True)
    ap.add_argument("-o", "--output", type=Path, help="Output file (default: stdout)")
    args = ap.parse_args()

    path = find_sop(args.sop)
    fm, body = parse(path)
    agent = to_agent_yaml(fm, body, path.relative_to(REPO_ROOT))

    text = yaml.safe_dump(agent, sort_keys=False, allow_unicode=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
        print(f"Wrote: {args.output}", file=sys.stderr)
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
