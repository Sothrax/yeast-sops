#!/usr/bin/env python3
"""
Phase 0 smoke test — Azure Document Intelligence na reálných CZ fakturách.

Pro každý PDF/JPG/PNG v daném adresáři zavolá prebuilt-invoice model, uloží raw
response JSON vedle vstupního souboru a vypíše přehled extrahovaných polí.

Usage:
    export AZURE_DOCINT_ENDPOINT="https://yeast-docint-prod.cognitiveservices.azure.com/"
    export AZURE_DOCINT_KEY="..."
    python scripts/dev/test_docint.py test_data/

Env vars:
    AZURE_DOCINT_ENDPOINT  (required)
    AZURE_DOCINT_KEY       (required)
    DOCINT_LOCALE          (optional, default "cs-CZ")
"""

from __future__ import annotations

import json
import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

try:
    from azure.ai.documentintelligence import DocumentIntelligenceClient
    from azure.ai.documentintelligence.models import AnalyzeDocumentRequest
    from azure.core.credentials import AzureKeyCredential
    from azure.core.exceptions import HttpResponseError
except ImportError:
    sys.exit(
        "Missing dependency. Install with:\n"
        "    pip install -r scripts/dev/requirements.txt\n"
        "    (nebo: pip install azure-ai-documentintelligence)"
    )


SUPPORTED_EXT = {".pdf", ".jpg", ".jpeg", ".png", ".tiff", ".tif", ".heic"}


def log(msg: str, *, prefix: str = "•") -> None:
    """Prints to stderr so stdout stays JSON-parseable if needed."""
    print(f"{prefix} {msg}", file=sys.stderr, flush=True)


def require_env(name: str) -> str:
    val = os.environ.get(name)
    if not val:
        sys.exit(f"ERROR: Env var {name} not set. See script docstring.")
    return val


def serialize(obj: Any) -> Any:
    """Convert Azure SDK response objects to JSON-friendly structures."""
    if hasattr(obj, "as_dict"):
        return obj.as_dict()
    if isinstance(obj, dict):
        return {k: serialize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [serialize(v) for v in obj]
    if hasattr(obj, "__dict__"):
        return {k: serialize(v) for k, v in vars(obj).items() if not k.startswith("_")}
    # date MUST come before datetime fallback — date is NOT subclass of datetime,
    # but datetime IS subclass of date. Both have .isoformat().
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    return obj


def field_value(field: Any) -> Any:
    """Extract the 'value' from an Azure DocumentField regardless of type."""
    if field is None:
        return None
    # Různé field types mají různé value attributes
    for attr in (
        "value_string",
        "value_number",
        "value_date",
        "value_currency",
        "value_address",
        "value_boolean",
        "value_integer",
        "value_phone_number",
        "value_country_region",
        "content",
    ):
        v = getattr(field, attr, None)
        if v is not None:
            if hasattr(v, "amount"):  # currency
                return f"{v.amount} {getattr(v, 'currency_code', '')}".strip()
            if hasattr(v, "as_dict"):
                return v.as_dict()
            return v
    return None


def field_confidence(field: Any) -> float | None:
    return getattr(field, "confidence", None) if field else None


def summarize_invoice(doc: Any) -> dict[str, Any]:
    """Extract key fields from a prebuilt-invoice document."""
    f = doc.fields or {}
    summary = {}
    key_fields = [
        "InvoiceId",
        "InvoiceDate",
        "DueDate",
        "VendorName",
        "VendorAddress",
        "VendorTaxId",
        "CustomerName",
        "CustomerAddress",
        "CustomerTaxId",
        "InvoiceTotal",
        "SubTotal",
        "TotalTax",
        "PaymentDetails",
        "ServiceAddress",
        "BillingAddress",
        "ShippingAddress",
        "PurchaseOrder",
        "Items",
    ]
    for key in key_fields:
        fld = f.get(key)
        summary[key] = {
            "value": field_value(fld),
            "confidence": field_confidence(fld),
        }
    return summary


def analyze_file(client: DocumentIntelligenceClient, path: Path, locale: str) -> dict[str, Any]:
    log(f"Analyzing: {path.name}  ({path.stat().st_size / 1024:.1f} KB)")
    with path.open("rb") as fh:
        data = fh.read()

    poller = client.begin_analyze_document(
        model_id="prebuilt-invoice",
        body=AnalyzeDocumentRequest(bytes_source=data),
        locale=locale,
    )
    result = poller.result()

    raw = serialize(result)

    documents = []
    for idx, doc in enumerate(result.documents or []):
        documents.append(
            {
                "doc_index": idx,
                "doc_type": doc.doc_type,
                "confidence": doc.confidence,
                "summary": summarize_invoice(doc),
            }
        )

    return {
        "file": path.name,
        "analyzed_at": datetime.now(timezone.utc).isoformat(),
        "model_id": "prebuilt-invoice",
        "locale": locale,
        "page_count": len(result.pages or []),
        "documents": documents,
        "raw": raw,
    }


def print_summary_row(res: dict[str, Any]) -> None:
    """Compact stdout summary for quick eyeballing."""
    print("=" * 80)
    print(f"📄 {res['file']}")
    print(f"   pages: {res['page_count']}  |  documents: {len(res['documents'])}")

    for doc in res["documents"]:
        s = doc["summary"]
        print(f"\n   Document #{doc['doc_index']}  (confidence: {doc['confidence']:.2f})")
        for k in [
            "InvoiceId",
            "InvoiceDate",
            "DueDate",
            "VendorName",
            "VendorTaxId",
            "CustomerName",
            "CustomerTaxId",
            "InvoiceTotal",
            "TotalTax",
        ]:
            val = s.get(k, {})
            v = val.get("value")
            c = val.get("confidence")
            if v is not None:
                c_str = f" [{c:.2f}]" if c is not None else ""
                print(f"     {k:18s} {v}{c_str}")


def main() -> int:
    if len(sys.argv) < 2:
        sys.exit(f"Usage: {sys.argv[0]} <dir-with-pdfs>")

    target_dir = Path(sys.argv[1]).resolve()
    if not target_dir.is_dir():
        sys.exit(f"ERROR: not a directory: {target_dir}")

    endpoint = require_env("AZURE_DOCINT_ENDPOINT")
    key = require_env("AZURE_DOCINT_KEY")
    locale = os.environ.get("DOCINT_LOCALE", "cs-CZ")

    files = sorted(
        p for p in target_dir.iterdir() if p.suffix.lower() in SUPPORTED_EXT
    )
    if not files:
        sys.exit(f"No supported files in {target_dir}. Expected: {SUPPORTED_EXT}")

    log(f"Endpoint: {endpoint}")
    log(f"Locale: {locale}")
    log(f"Files to analyze: {len(files)}")
    log("")

    client = DocumentIntelligenceClient(
        endpoint=endpoint,
        credential=AzureKeyCredential(key),
    )

    out_dir = target_dir / "_docint_out"
    out_dir.mkdir(exist_ok=True)

    results = []
    for i, f in enumerate(files, 1):
        log(f"[{i}/{len(files)}] {f.name}", prefix="→")
        try:
            res = analyze_file(client, f, locale)
            out_path = out_dir / f"{f.stem}.out.json"
            # default=str as safety net pro edge typy (Decimal, custom objekty), nepoškodí date/datetime
            out_path.write_text(
                json.dumps(res, indent=2, ensure_ascii=False, default=str),
                encoding="utf-8",
            )
            results.append(res)  # append AŽ po úspěšném write, ne před
            log(f"  saved: {out_path.relative_to(target_dir.parent)}", prefix="  ")
            print_summary_row(res)
        except HttpResponseError as e:
            log(f"  API ERROR: {e.status_code} — {e.message}", prefix="✗")
            results.append({"file": f.name, "error": str(e), "status_code": e.status_code})
        except Exception as e:  # noqa: BLE001
            log(f"  ERROR: {type(e).__name__}: {e}", prefix="✗")
            results.append({"file": f.name, "error": str(e)})

    # Aggregate summary file
    summary_path = out_dir / "_summary.json"
    summary_path.write_text(
        json.dumps(
            {
                "run_at": datetime.now(timezone.utc).isoformat(),
                "endpoint": endpoint,
                "locale": locale,
                "total_files": len(files),
                "successful": sum(1 for r in results if "error" not in r),
                "failed": sum(1 for r in results if "error" in r),
                "files": [
                    {
                        "file": r["file"],
                        "documents": len(r.get("documents", [])),
                        "error": r.get("error"),
                    }
                    for r in results
                ],
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    print("\n" + "=" * 80)
    print(f"✅ Done. Processed {len(files)} files.")
    print(f"   Successful: {sum(1 for r in results if 'error' not in r)}")
    print(f"   Failed:     {sum(1 for r in results if 'error' in r)}")
    print(f"   Output dir: {out_dir}")
    print(f"   Summary:    {summary_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
