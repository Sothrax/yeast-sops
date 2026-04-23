#!/usr/bin/env python3
"""
yeast-sops instantiator
=======================

Turns a template SOP into a tenant-specific instance.

Usage:
  python scripts/instantiate.py \
      --template SOP-ACC-T001 \
      --tenant taf-estate \
      --instance-id SOP-ACC-I001 \
      --params params.yaml

Where params.yaml contains values for parameters declared in the template's
`tenant.parameterized` list, e.g.:

  bank_account_id: "2700123456/2010"
  company_flexibee_id: "TAF_ESTATE_SRO"
  notification_channel: "slack:#taf-accounting"
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import date
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.exit("Missing dependency: pip install pyyaml")


REPO_ROOT = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = REPO_ROOT / "templates"
INSTANCES_DIR = REPO_ROOT / "instances"

FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
PLACEHOLDER_RE = re.compile(r"\{\{\s*([a-z0-9_]+)\s*\}\}")


def find_template(template_id: str) -> Path:
    for md in TEMPLATES_DIR.rglob("*.md"):
        if md.name.startswith(template_id):
            return md
    sys.exit(f"Template {template_id} not found under templates/")


def parse_frontmatter(text: str) -> tuple[dict, str]:
    m = FRONTMATTER_RE.match(text)
    if not m:
        sys.exit("Template has no frontmatter")
    data = yaml.safe_load(m.group(1))
    body = text[m.end():]
    return data, body


def substitute(text: str, params: dict[str, str]) -> tuple[str, set[str]]:
    """Replace {{ param }} placeholders. Returns (text, set_of_unresolved)."""
    unresolved: set[str] = set()

    def replace(match: re.Match) -> str:
        key = match.group(1)
        if key not in params:
            unresolved.add(key)
            return match.group(0)
        return str(params[key])

    return PLACEHOLDER_RE.sub(replace, text), unresolved


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--template", required=True, help="Template SOP id, e.g. SOP-ACC-T001")
    ap.add_argument("--tenant", required=True, help="Tenant slug, e.g. taf-estate")
    ap.add_argument("--instance-id", required=True, help="New instance id, e.g. SOP-ACC-I001")
    ap.add_argument("--params", type=Path, required=True, help="Path to YAML with parameter values")
    ap.add_argument("--force", action="store_true", help="Overwrite if output exists")
    args = ap.parse_args()

    template_path = find_template(args.template)
    text = template_path.read_text(encoding="utf-8")
    fm, body = parse_frontmatter(text)

    declared_params = (fm.get("tenant") or {}).get("parameterized") or []
    with args.params.open(encoding="utf-8") as f:
        param_values = yaml.safe_load(f) or {}

    missing = [p for p in declared_params if p not in param_values]
    if missing:
        sys.exit(f"Missing parameter values: {missing}")

    # Substitute body
    new_body, unresolved = substitute(body, param_values)
    if unresolved:
        sys.exit(f"Unresolved placeholders in body: {unresolved}")

    # Build new frontmatter
    new_fm = dict(fm)
    new_fm["id"] = args.instance_id
    new_fm["tenant"] = {
        "type": "instance",
        "scope": args.tenant,
        "derived_from": args.template,
        "parameter_values": param_values,
    }
    new_fm["version"] = "0.1.0"
    new_fm["status"] = "draft"
    new_fm["last_reviewed"] = date.today().isoformat()

    # Substitute frontmatter values too (only string fields)
    def walk(obj):
        if isinstance(obj, str):
            s, _ = substitute(obj, param_values)
            return s
        if isinstance(obj, dict):
            return {k: walk(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [walk(v) for v in obj]
        return obj

    new_fm = walk(new_fm)

    # Build output path
    slug_part = template_path.stem.split("-", 3)[-1] if "-" in template_path.stem else template_path.stem
    out_name = f"{args.instance_id}-{slug_part}.md"
    domain = fm.get("domain", "accounting")
    out_dir = INSTANCES_DIR / args.tenant / domain
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / out_name

    if out_path.exists() and not args.force:
        sys.exit(f"Output exists: {out_path} (use --force)")

    # Write
    yaml_text = yaml.safe_dump(new_fm, sort_keys=False, allow_unicode=True).rstrip()
    out_path.write_text(f"---\n{yaml_text}\n---\n{new_body}", encoding="utf-8")
    print(f"Created: {out_path.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
