#!/usr/bin/env python3
"""
Phase 1 classifier test — aplikuje rule-based classification + post-processing
na výstupy z Phase 0 (ADI responses v _docint_out/).

Cíl:
    1. Ověřit že náš multi-signal classifier správně rozpoznává FP / ZP / PREDPIS
    2. Normalizovat extracted fields (strip \\n, IČO CZ-prefix, trailing punctuation)
    3. Spočítat flags (low confidence, missing critical field, potential duplicate)
    4. Vygenerovat baseline JSON který odpovídá našemu sidecar schema 1.0.0

Usage:
    python3 scripts/dev/test_classifier.py <out_dir>

    # Pokud existuje <out_dir>/_expected.json s {filename: expected_type}, spočítá
    # accuracy a confusion matrix.
"""

from __future__ import annotations

import json
import re
import sys
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


def nfc(s: str) -> str:
    """macOS HFS+ normalizuje filenames na NFD (decomposed unicode). JSON má NFC.
    Bez normalizace 'Plán záloh' z filename != 'Plán záloh' z JSON key."""
    return unicodedata.normalize("NFC", s)


# -----------------------------------------------------------------------------
# Configurable thresholds (mirror SOP-ACC-T002 sop_config defaults)
# -----------------------------------------------------------------------------

OCR_CONFIDENCE_DOC_THRESHOLD = 0.75
OCR_CONFIDENCE_FIELD_THRESHOLD_ICO = 0.85
OCR_CONFIDENCE_FIELD_THRESHOLD_TOTAL = 0.70  # snížené z 0.85 po Phase 0 findings
TYPE_CLASSIFIER_THRESHOLD = 0.70

# Klíčová pole co u plného daňového dokladu (FP) mají být přítomná
FP_EXPECTED_FIELDS = ["InvoiceId", "DueDate", "CustomerTaxId"]

# Keyword sady pro jednotlivé typy (všechny lowercase, match proti lowercased content)
KEYWORDS: dict[str, list[str]] = {
    "PREDPIS": [
        "předpis záloh",
        "plán záloh",
        "předpis k úhradě",
        "rozpis záloh",
        "zálohové platby",
    ],
    "ZP": [
        "zálohová faktura",
        "proforma",
        "není daňový doklad",
        "zálohový list",
    ],
    "FP": [
        "faktura - daňový doklad",
        "faktura/daňový doklad",
        "faktura / daňový doklad",
        "řádná faktura",
        "daňový doklad",
    ],
}


# -----------------------------------------------------------------------------
# Data structures
# -----------------------------------------------------------------------------


@dataclass
class ClassificationResult:
    file: str
    verdict: str  # FP | ZP | PREDPIS | OSTATNI
    confidence: float
    reasons: list[str] = field(default_factory=list)
    # Normalized, post-processed fields
    supplier_name: str | None = None
    supplier_ico: str | None = None
    customer_name: str | None = None
    customer_ico: str | None = None
    invoice_number: str | None = None
    invoice_date: str | None = None
    due_date: str | None = None
    total_amount: float | None = None
    currency: str | None = None
    iban: str | None = None
    variable_symbol: str | None = None
    # Field-level confidence snapshot
    confidence_doc: float | None = None
    confidence_supplier_ico: float | None = None
    confidence_customer_ico: float | None = None
    confidence_total: float | None = None
    # HITL flags
    flags: list[str] = field(default_factory=list)
    hitl_required: bool = False
    hitl_reason: str | None = None


# -----------------------------------------------------------------------------
# Field extraction helpers — bere ADI field dict a vytáhne hodnotu + confidence
# -----------------------------------------------------------------------------


def field_value(field_dict: dict | None) -> Any:
    """
    Extract value from an Azure field dict. Azure serializes to camelCase JSON:
    valueString, valueNumber, valueDate, valueCurrency{amount,currencyCode}.
    """
    if not field_dict:
        return None
    for key in ("valueString", "valueNumber", "valueDate", "valueInteger", "valueBoolean"):
        v = field_dict.get(key)
        if v is not None:
            return v
    # valueCurrency is nested
    vc = field_dict.get("valueCurrency")
    if isinstance(vc, dict):
        amount = vc.get("amount")
        if amount is not None:
            return amount
    # Fallback: raw content (OCR text)
    return field_dict.get("content")


def field_confidence(field_dict: dict | None) -> float | None:
    if not field_dict:
        return None
    return field_dict.get("confidence")


def field_currency(field_dict: dict | None) -> str | None:
    if not field_dict:
        return None
    vc = field_dict.get("valueCurrency")
    if isinstance(vc, dict):
        return vc.get("currencyCode") or vc.get("currencySymbol")
    return None


# -----------------------------------------------------------------------------
# Post-processing — cleanup OCR artifacts
# -----------------------------------------------------------------------------


def normalize_name(raw: str | None) -> str | None:
    """Strip newlines, collapse whitespace. OCR u PRAŽSKÁ\\nPLYNÁRENSKÁ apod."""
    if not raw:
        return None
    cleaned = re.sub(r"\s+", " ", raw).strip()
    return cleaned or None


def normalize_ico(raw: str | None) -> str | None:
    """
    Normalize IČO na přesně 8-číselný formát.

    - Pokud string začíná DIČ prefixem ([A-Z]{2}) následovaným 8 digits → vezme ty digits
    - Jinak hledá 8-digit sekvenci co není obklopená jinými digits (zabrání matchnutí
      8 digitů uvnitř delšího čísla)

    \\b nefunguje: v "CZ21296731" není word boundary mezi Z a 2 (oba word chars).

    Examples:
        'CZ02939053'      -> '02939053'
        'CZ60193492,'     -> '60193492'
        '24507318'        -> '24507318'
        'IČ: 02939053'    -> '02939053'
        'CZ123456789'     -> None  (9 digits ≠ IČO)
        'číslo účtu 123456789012' -> None  (12 digits, not IČO)
    """
    if not raw:
        return None
    s = raw.strip()
    # 1) Pattern: volitelný 2-písmenný prefix + přesně 8 digits + non-digit (nebo konec)
    m = re.match(r"^(?:[A-Za-z]{2})?(\d{8})(?!\d)", s)
    if m:
        return m.group(1)
    # 2) Fallback: 8-digit sekvence uvnitř stringu, nesurrounded by other digits
    m = re.search(r"(?<!\d)(\d{8})(?!\d)", s)
    return m.group(1) if m else None


def extract_iban_from_content(content: str) -> str | None:
    """Look for IBAN or CZ account number pattern in OCR content."""
    if not content:
        return None
    # Standard IBAN format (EU)
    iban_match = re.search(r"\b([A-Z]{2}\d{2}[A-Z0-9]{11,30})\b", content)
    if iban_match:
        return iban_match.group(1)
    # CZ account pattern: [prefix-]account/bankcode, e.g. 107-6130210257/0100
    cz_match = re.search(r"\b(\d{1,6}-)?(\d{2,10})/(\d{4})\b", content)
    if cz_match:
        prefix = cz_match.group(1) or ""
        return f"{prefix}{cz_match.group(2)}/{cz_match.group(3)}"
    return None


def extract_variable_symbol_from_content(content: str) -> str | None:
    """Najde 'Variabilní symbol: XYZ' pattern v content."""
    if not content:
        return None
    m = re.search(r"Variabiln[ií]\s*symbol[:\s]+(\S+)", content, re.IGNORECASE)
    return m.group(1) if m else None


# -----------------------------------------------------------------------------
# Classifier — multi-signal rule-based decision
# -----------------------------------------------------------------------------


def find_keywords(content: str, kws: list[str]) -> list[str]:
    if not content:
        return []
    content_l = content.lower()
    return [k for k in kws if k in content_l]


def classify(fields: dict, content: str) -> tuple[str, float, list[str]]:
    """
    Multi-signal klasifikace:
      1. Keywords v content text
      2. Presence/absence klíčových tax fields
      3. Decision tree

    Returns: (type, confidence, reasons[])
    """
    # Signal A: presence tax fields
    has_inv_id = bool(fields.get("InvoiceId"))
    has_due = bool(fields.get("DueDate"))
    has_customer_tax_id = bool(fields.get("CustomerTaxId"))
    has_total_tax = bool(fields.get("TotalTax"))
    tax_fields_present = sum(
        [has_inv_id, has_due, has_customer_tax_id, has_total_tax]
    )

    # Signal B: keywords
    kw_predpis = find_keywords(content, KEYWORDS["PREDPIS"])
    kw_zp = find_keywords(content, KEYWORDS["ZP"])
    kw_fp = find_keywords(content, KEYWORDS["FP"])

    reasons: list[str] = []

    # PŘEDPIS — silný keyword match nebo žádné tax fields
    if kw_predpis:
        reasons.append(f"kw_predpis:{kw_predpis}")
        return "PREDPIS", 0.95, reasons
    if tax_fields_present <= 1:
        reasons.append(f"negative_tax_fields:{tax_fields_present}/4")
        return "PREDPIS", 0.75, reasons

    # ZP — keyword match
    if kw_zp:
        reasons.append(f"kw_zp:{kw_zp}")
        return "ZP", 0.90, reasons

    # FP — tax fields + keyword, nebo jen tax fields (catch Uppercut case)
    if tax_fields_present >= 3 and kw_fp:
        reasons.append(f"tax_fields:{tax_fields_present}/4 + kw_fp:{kw_fp}")
        return "FP", 0.95, reasons
    if tax_fields_present >= 3:
        reasons.append(f"tax_fields:{tax_fields_present}/4 (no kw_fp match)")
        return "FP", 0.80, reasons

    # Nic jasně nepasuje
    reasons.append(f"no_clear_signal (tax:{tax_fields_present}/4, kws: PRED:{len(kw_predpis)} ZP:{len(kw_zp)} FP:{len(kw_fp)})")
    return "OSTATNI", 0.50, reasons


# -----------------------------------------------------------------------------
# Flag computation — co by v produkci vedlo k HITL
# -----------------------------------------------------------------------------


def compute_flags(res: ClassificationResult, doc_confidence: float | None) -> None:
    """Mutuje res — přidá flags a rozhodne o HITL."""
    # OCR confidence checks
    if doc_confidence is not None and doc_confidence < OCR_CONFIDENCE_DOC_THRESHOLD:
        res.flags.append(f"low_doc_confidence:{doc_confidence:.2f}")
        res.hitl_required = True
        res.hitl_reason = "low_ocr_confidence"

    if (
        res.confidence_supplier_ico is not None
        and res.confidence_supplier_ico < OCR_CONFIDENCE_FIELD_THRESHOLD_ICO
    ):
        res.flags.append(f"low_supplier_ico_confidence:{res.confidence_supplier_ico:.2f}")
    if (
        res.confidence_customer_ico is not None
        and res.confidence_customer_ico < OCR_CONFIDENCE_FIELD_THRESHOLD_ICO
    ):
        res.flags.append(f"low_customer_ico_confidence:{res.confidence_customer_ico:.2f}")
        res.hitl_required = True
        res.hitl_reason = res.hitl_reason or "low_ocr_confidence"
    if (
        res.confidence_total is not None
        and res.confidence_total < OCR_CONFIDENCE_FIELD_THRESHOLD_TOTAL
    ):
        res.flags.append(f"low_total_confidence:{res.confidence_total:.2f}")

    # Critical field presence (závisí na typu)
    if res.verdict == "FP":
        for fname, fval in [
            ("InvoiceId", res.invoice_number),
            ("CustomerTaxId", res.customer_ico),
            ("InvoiceTotal", res.total_amount),
        ]:
            if not fval:
                res.flags.append(f"missing_critical:{fname}")
                res.hitl_required = True
                res.hitl_reason = res.hitl_reason or "low_ocr_confidence"

    # IČO format validation (normalization should have caught this already)
    for ico_name, ico_val in [("supplier", res.supplier_ico), ("customer", res.customer_ico)]:
        if ico_val and not re.fullmatch(r"\d{8}", ico_val):
            res.flags.append(f"invalid_ico_format:{ico_name}:{ico_val}")

    # Classifier verdict confidence
    if res.confidence < TYPE_CLASSIFIER_THRESHOLD or res.verdict == "OSTATNI":
        res.flags.append(f"low_classifier_confidence:{res.confidence:.2f}")
        res.hitl_required = True
        res.hitl_reason = res.hitl_reason or "unknown_document_type"


# -----------------------------------------------------------------------------
# Main processing
# -----------------------------------------------------------------------------


def process_file(out_json_path: Path) -> ClassificationResult:
    data = json.loads(out_json_path.read_text(encoding="utf-8"))
    raw = data.get("raw", {})
    content = raw.get("content", "") or ""

    docs = raw.get("documents") or []
    doc = docs[0] if docs else {}
    fields = doc.get("fields") or {}
    doc_confidence = doc.get("confidence")

    # Classify
    verdict, conf, reasons = classify(fields, content)

    # Build result
    res = ClassificationResult(
        file=nfc(out_json_path.stem.replace(".out", "")),
        verdict=verdict,
        confidence=conf,
        reasons=reasons,
        supplier_name=normalize_name(field_value(fields.get("VendorName"))),
        supplier_ico=normalize_ico(field_value(fields.get("VendorTaxId"))),
        customer_name=normalize_name(field_value(fields.get("CustomerName"))),
        customer_ico=normalize_ico(field_value(fields.get("CustomerTaxId"))),
        invoice_number=field_value(fields.get("InvoiceId")),
        invoice_date=str(field_value(fields.get("InvoiceDate"))) if fields.get("InvoiceDate") else None,
        due_date=str(field_value(fields.get("DueDate"))) if fields.get("DueDate") else None,
        total_amount=field_value(fields.get("InvoiceTotal")),
        currency=field_currency(fields.get("InvoiceTotal")),
        iban=extract_iban_from_content(content),
        variable_symbol=extract_variable_symbol_from_content(content),
        confidence_doc=doc_confidence,
        confidence_supplier_ico=field_confidence(fields.get("VendorTaxId")),
        confidence_customer_ico=field_confidence(fields.get("CustomerTaxId")),
        confidence_total=field_confidence(fields.get("InvoiceTotal")),
    )

    compute_flags(res, doc_confidence)
    return res


def print_result(res: ClassificationResult) -> None:
    badge = {"FP": "💼", "ZP": "📥", "PREDPIS": "📋", "OSTATNI": "❓"}.get(res.verdict, "?")
    hitl = " 🚨 HITL" if res.hitl_required else ""
    print(f"\n{'=' * 80}")
    print(f"{badge}  {res.file}")
    print(f"   Verdict: {res.verdict}  (confidence {res.confidence:.2f}){hitl}")
    print(f"   Reasons: {', '.join(res.reasons)}")
    print(f"   Supplier:  {res.supplier_name or '—'}  (IČO {res.supplier_ico or '—'})")
    print(f"   Customer:  {res.customer_name or '—'}  (IČO {res.customer_ico or '—'})")
    inv_parts = [res.invoice_number or "—", res.invoice_date or "—"]
    if res.due_date:
        inv_parts.append(f"due {res.due_date}")
    print(f"   Invoice:   #{inv_parts[0]}  issued {inv_parts[1]}" + (f"  {inv_parts[2]}" if len(inv_parts) > 2 else ""))
    amount_str = f"{res.total_amount} {res.currency or ''}" if res.total_amount else "—"
    print(f"   Total:     {amount_str}")
    if res.iban:
        print(f"   Payment:   IBAN/Účet {res.iban}" + (f", VS {res.variable_symbol}" if res.variable_symbol else ""))
    if res.flags:
        print(f"   Flags:     {', '.join(res.flags)}")


def main() -> int:
    if len(sys.argv) < 2:
        sys.exit(f"Usage: {sys.argv[0]} <out_dir>  (e.g. test_data/_docint_out/)")

    out_dir = Path(sys.argv[1]).resolve()
    if not out_dir.is_dir():
        sys.exit(f"ERROR: not a directory: {out_dir}")

    json_files = sorted(
        p for p in out_dir.glob("*.out.json")
        if not p.name.startswith("_")
    )
    if not json_files:
        sys.exit(f"No *.out.json files in {out_dir}")

    print(f"→ Classifying {len(json_files)} files from {out_dir}")

    results: list[ClassificationResult] = []
    for p in json_files:
        try:
            res = process_file(p)
            results.append(res)
            print_result(res)
        except Exception as e:  # noqa: BLE001
            print(f"\n✗ ERROR processing {p.name}: {type(e).__name__}: {e}")

    # Summary
    print(f"\n{'=' * 80}")
    print("SUMMARY")
    print(f"{'=' * 80}")
    from collections import Counter
    verdict_counts = Counter(r.verdict for r in results)
    hitl_count = sum(1 for r in results if r.hitl_required)
    for vt in ["FP", "ZP", "PREDPIS", "OSTATNI"]:
        print(f"  {vt:10s} {verdict_counts.get(vt, 0)}")
    print(f"  HITL flag  {hitl_count}/{len(results)}")

    # Expected comparison if _expected.json exists
    expected_path = out_dir / "_expected.json"
    if expected_path.exists():
        expected_raw = json.loads(expected_path.read_text())
        # Normalize NFC pro bezpečný lookup (macOS filesystem NFD vs JSON NFC)
        expected = {nfc(k): v for k, v in expected_raw.items()}
        print(f"\n{'-' * 80}")
        print("ACCURACY vs _expected.json")
        print(f"{'-' * 80}")
        correct = 0
        total_with_expected = 0
        for r in results:
            exp = expected.get(r.file) or expected.get(r.file + ".pdf")
            if exp is None:
                continue
            total_with_expected += 1
            ok = r.verdict == exp
            if ok:
                correct += 1
            print(f"  {'✓' if ok else '✗'}  {r.file[:50]:<52} expected={exp}  got={r.verdict}")
        if total_with_expected:
            print(f"\n  Accuracy: {correct}/{total_with_expected} ({correct*100/total_with_expected:.0f}%)")
        else:
            print("  (no matches — check key encoding in _expected.json)")

    # Write results JSON
    results_path = out_dir / "_classifier_results.json"
    results_path.write_text(
        json.dumps(
            [
                {
                    "file": r.file,
                    "verdict": r.verdict,
                    "confidence": r.confidence,
                    "reasons": r.reasons,
                    "supplier": {"name": r.supplier_name, "ico": r.supplier_ico},
                    "customer": {"name": r.customer_name, "ico": r.customer_ico},
                    "invoice": {
                        "number": r.invoice_number,
                        "date": r.invoice_date,
                        "due_date": r.due_date,
                        "total": r.total_amount,
                        "currency": r.currency,
                    },
                    "payment": {"iban": r.iban, "variable_symbol": r.variable_symbol},
                    "ocr_confidence": {
                        "doc": r.confidence_doc,
                        "supplier_ico": r.confidence_supplier_ico,
                        "customer_ico": r.confidence_customer_ico,
                        "total": r.confidence_total,
                    },
                    "flags": r.flags,
                    "hitl_required": r.hitl_required,
                    "hitl_reason": r.hitl_reason,
                }
                for r in results
            ],
            indent=2,
            ensure_ascii=False,
            default=str,
        ),
        encoding="utf-8",
    )
    print(f"\n📄 Structured results: {results_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
