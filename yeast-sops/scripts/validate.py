#!/usr/bin/env python3
"""
yeast-sops validator
====================

Validates SOP markdown files and role YAML files against JSON schemas.
Also runs cross-reference checks (related_sops exist, instances point
to valid templates, roles reference existing SOPs).

Usage:
  python scripts/validate.py                        # validate everything
  python scripts/validate.py --sop <id>             # validate single SOP
  python scripts/validate.py --role <id>            # validate single role
  python scripts/validate.py --strict               # fail on warnings too
  python scripts/validate.py --stale                # also check stale SOPs
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:
    sys.exit("Missing dependency: pip install pyyaml")

try:
    from jsonschema import Draft7Validator
except ImportError:
    sys.exit("Missing dependency: pip install jsonschema")


REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMAS_DIR = REPO_ROOT / "schemas"
TEMPLATES_DIR = REPO_ROOT / "templates"
INSTANCES_DIR = REPO_ROOT / "instances"
ROLES_DIR = REPO_ROOT / "roles"

FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


@dataclass
class ValidationIssue:
    level: str  # "error" or "warning"
    file: Path
    message: str


@dataclass
class ValidationResult:
    issues: list[ValidationIssue] = field(default_factory=list)
    files_checked: int = 0

    def error(self, file: Path, msg: str) -> None:
        self.issues.append(ValidationIssue("error", file, msg))

    def warn(self, file: Path, msg: str) -> None:
        self.issues.append(ValidationIssue("warning", file, msg))

    @property
    def errors(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.level == "error"]

    @property
    def warnings(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.level == "warning"]


def load_schema(name: str) -> dict[str, Any]:
    path = SCHEMAS_DIR / f"{name}.schema.json"
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def _stringify_dates(obj: Any) -> Any:
    """Recursively convert date/datetime objects to ISO strings for JSON Schema."""
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, date):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {k: _stringify_dates(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_stringify_dates(v) for v in obj]
    return obj


def parse_frontmatter(md_path: Path) -> tuple[dict[str, Any] | None, str]:
    """Extract YAML frontmatter from a markdown file. Returns (data, body)."""
    text = md_path.read_text(encoding="utf-8")
    match = FRONTMATTER_RE.match(text)
    if not match:
        return None, text
    try:
        data = yaml.safe_load(match.group(1))
    except yaml.YAMLError as e:
        raise ValueError(f"Invalid YAML frontmatter in {md_path}: {e}") from e
    data = _stringify_dates(data)
    body = text[match.end():]
    return data, body


def find_sops(only_id: str | None = None) -> list[Path]:
    """Return all SOP markdown files under templates/ and instances/ except template stubs."""
    files: list[Path] = []
    for root in (TEMPLATES_DIR, INSTANCES_DIR):
        if not root.exists():
            continue
        for md in root.rglob("*.md"):
            if md.name.startswith("_"):
                continue
            if only_id and only_id not in md.name:
                continue
            files.append(md)
    return sorted(files)


def find_roles(only_id: str | None = None) -> list[Path]:
    files: list[Path] = []
    if not ROLES_DIR.exists():
        return files
    for yml in ROLES_DIR.rglob("*.yaml"):
        if yml.name.startswith("_"):
            continue
        if only_id and only_id not in yml.name:
            continue
        files.append(yml)
    return sorted(files)


def validate_sop_file(path: Path, validator: Draft7Validator, result: ValidationResult) -> dict[str, Any] | None:
    try:
        data, _body = parse_frontmatter(path)
    except ValueError as e:
        result.error(path, str(e))
        return None
    if data is None:
        result.error(path, "Missing YAML frontmatter")
        return None

    errors = sorted(validator.iter_errors(data), key=lambda e: e.path)
    for err in errors:
        loc = "/".join(str(p) for p in err.path) or "<root>"
        result.error(path, f"{loc}: {err.message}")

    # Filename consistency check
    expected_prefix = data.get("id", "")
    if expected_prefix and not path.name.startswith(expected_prefix):
        result.warn(path, f"Filename should start with id '{expected_prefix}'")

    # Path consistency: template vs instance
    is_in_templates = TEMPLATES_DIR in path.parents
    is_in_instances = INSTANCES_DIR in path.parents
    tenant_type = data.get("tenant", {}).get("type") if isinstance(data.get("tenant"), dict) else None

    if is_in_templates and tenant_type != "template":
        result.error(path, f"File is in templates/ but tenant.type is '{tenant_type}', expected 'template'")
    if is_in_instances and tenant_type != "instance":
        result.error(path, f"File is in instances/ but tenant.type is '{tenant_type}', expected 'instance'")

    # ID prefix T vs I check
    sop_id = data.get("id", "")
    if sop_id:
        if tenant_type == "template" and "-T" not in sop_id:
            result.error(path, f"Template SOP id must contain '-T', got '{sop_id}'")
        if tenant_type == "instance" and "-I" not in sop_id:
            result.error(path, f"Instance SOP id must contain '-I', got '{sop_id}'")

    return data


def validate_role_file(path: Path, validator: Draft7Validator, result: ValidationResult) -> dict[str, Any] | None:
    try:
        with path.open(encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError as e:
        result.error(path, f"Invalid YAML: {e}")
        return None
    data = _stringify_dates(data)

    errors = sorted(validator.iter_errors(data), key=lambda e: e.path)
    for err in errors:
        loc = "/".join(str(p) for p in err.path) or "<root>"
        result.error(path, f"{loc}: {err.message}")
    return data


def cross_ref_checks(sops: dict[str, tuple[Path, dict]], roles: dict[str, tuple[Path, dict]], result: ValidationResult) -> None:
    """Check that references between SOPs and roles all resolve."""
    for sop_id, (path, data) in sops.items():
        # related_sops must exist
        for related in data.get("related_sops", []) or []:
            if related not in sops:
                result.warn(path, f"related_sops references unknown SOP '{related}'")
        # instance must point to existing template
        tenant = data.get("tenant", {}) or {}
        if tenant.get("type") == "instance":
            derived = tenant.get("derived_from")
            if derived and derived not in sops:
                result.error(path, f"derived_from references unknown template '{derived}'")

    for role_id, (path, data) in roles.items():
        for sop_ref in data.get("sops", []) or []:
            sop_id = sop_ref.get("sop_id") if isinstance(sop_ref, dict) else None
            if sop_id and sop_id not in sops:
                result.error(path, f"Role references unknown SOP '{sop_id}'")


def stale_check(sops: dict[str, tuple[Path, dict]], result: ValidationResult, today: date | None = None) -> None:
    today = today or date.today()
    for sop_id, (path, data) in sops.items():
        nr = data.get("next_review")
        if nr is None:
            continue
        try:
            nr_date = nr if isinstance(nr, date) else datetime.strptime(str(nr), "%Y-%m-%d").date()
        except ValueError:
            result.warn(path, f"Invalid next_review date: {nr}")
            continue
        if nr_date < today:
            days = (today - nr_date).days
            result.warn(path, f"SOP is {days} days past next_review ({nr_date})")


def print_report(result: ValidationResult, strict: bool) -> int:
    for issue in result.issues:
        prefix = "ERROR" if issue.level == "error" else "WARN "
        rel = issue.file.relative_to(REPO_ROOT) if REPO_ROOT in issue.file.parents else issue.file
        print(f"[{prefix}] {rel}: {issue.message}")

    n_err = len(result.errors)
    n_warn = len(result.warnings)
    print(f"\nChecked {result.files_checked} files: {n_err} errors, {n_warn} warnings")

    if n_err > 0:
        return 1
    if strict and n_warn > 0:
        return 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate yeast-sops repository")
    parser.add_argument("--sop", help="Validate only SOP with this id substring")
    parser.add_argument("--role", help="Validate only role with this id substring")
    parser.add_argument("--strict", action="store_true", help="Fail on warnings too")
    parser.add_argument("--stale", action="store_true", help="Include stale SOP check")
    args = parser.parse_args()

    sop_schema = load_schema("sop")
    role_schema = load_schema("role")
    sop_validator = Draft7Validator(sop_schema)
    role_validator = Draft7Validator(role_schema)

    result = ValidationResult()
    sops: dict[str, tuple[Path, dict]] = {}
    roles: dict[str, tuple[Path, dict]] = {}

    if not args.role:
        for path in find_sops(args.sop):
            result.files_checked += 1
            data = validate_sop_file(path, sop_validator, result)
            if data and "id" in data:
                sops[data["id"]] = (path, data)

    if not args.sop:
        for path in find_roles(args.role):
            result.files_checked += 1
            data = validate_role_file(path, role_validator, result)
            if data and "id" in data:
                roles[data["id"]] = (path, data)

    if not (args.sop or args.role):
        cross_ref_checks(sops, roles, result)

    if args.stale:
        stale_check(sops, result)

    return print_report(result, args.strict)


if __name__ == "__main__":
    sys.exit(main())
