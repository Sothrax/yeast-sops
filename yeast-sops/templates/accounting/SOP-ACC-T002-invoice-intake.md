---
id: SOP-ACC-T002
name: "Invoice Intake – SharePoint to Booking Queue"
version: 0.2.0
status: draft
owner: petr@yeast-group.cz
business_owner: petr.kvasnica@yeast-group.cz
domain: accounting
tenant:
  type: template
  parameterized: []
last_reviewed: 2026-04-23
reviewed_by: petr@yeast-group.cz
next_review: 2026-10-23
agent_suitable: true
automation_level: supervised
required_tools:
  - mcp:ms365-sharepoint
  - mcp:azure-doc-intelligence
  - mcp:ares-gateway
  - mcp:iban-validator
  - mcp:supabase
  - mcp:telegram
  - mcp:onepassword-connect
  - internal:pdf-text-extractor
required_connectors:
  - sharepoint
  - azure_docint
  - ares
  - iban_validator
  - supabase
  - telegram
  - onepassword_connect
required_permissions:
  - read:sharepoint_inbox
  - write:sharepoint_folders
  - delete:sharepoint_inbox_files
  - read:supabase_tenants
  - read:supabase_sop_config
  - write:supabase_intake_events
  - execute:azure_docint_invoice_model
  - execute:ares_ico_lookup
  - execute:iban_validation
  - notify:telegram_intake_review
  - notify:telegram_alerts
  - notify:telegram_intake_ready
  - read:onepassword_cortex_prod_core
trigger: scheduled
schedule: "*/15 * * * *"
estimated_duration_min: 5
criticality: high
human_approval_required:
  - low_ocr_confidence
  - unknown_document_type
  - unknown_tenant
  - ares_ico_not_found
  - processing_error
success_criteria:
  - no_unhandled_exceptions_in_run
  - all_inbox_files_processed_or_flagged_within_run
  - run_duration_under_10_min_for_50_files
  - each_file_routed_to_tenant_type_folder_or_review
  - each_file_has_valid_sidecar_json_matching_schema
  - each_source_archived_or_moved_to_review_not_left_in_inbox
  - document_type_in_allowed_set_or_hitl_flagged
  - tenant_resolved_or_hitl_flagged
  - every_extracted_ico_verified_via_ares_or_hitl_flagged
  - supplier_name_from_ares_canonical_when_ares_match
  - filename_matches_convention
  - intake_event_row_in_supabase_and_telegram_msg_sent
  - idempotent_no_duplicate_processing_of_same_file_hash
tags:
  - accounting
  - ap-automation
  - ocr
  - invoice-intake
  - sharepoint
  - azure-docint
  - yeastfin
related_sops: []
references:
  - label: "Azure AI Document Intelligence – prebuilt-invoice model"
    url: "https://learn.microsoft.com/en-us/azure/ai-services/document-intelligence/prebuilt/invoice"
  - label: "ARES (Administrativní registr ekonomických subjektů)"
    url: "https://ares.gov.cz/"
  - label: "Secrets & Config Conventions (yeast-sops)"
    url: "https://github.com/Sothrax/yeast-sops/blob/main/docs/secrets-conventions.md"
---

# Invoice Intake – SharePoint to Booking Queue

## Cíl

Stáhnout nově nahrané faktury ze sdílené SharePoint inbox složky, rozpoznat typ dokladu
(FP / ZP / PŘEDPIS), extrahovat klíčová pole (IČO stran, částka, IBAN, VS, data), ověřit
protistrany proti ARES a IBAN validátoru, identifikovat správný YEAST tenant podle IČO
odběratele a routovat fakturu (+ JSON metadata sidecar) do odpovídající booking složky
`<tenant>/<TYPE>/`. Originál archivovat. Výstup konzumuje SOP-ACC-T003 (booking).

## Kontext / Proč

Dnes účetní stahuje faktury z mailu / SharePoint, manuálně pojmenovává, rozřazuje podle
firem a ručně zadává do FlexiBee. Intake fáze (sortování, OCR, klasifikace typu) je
opakovatelná, ale chybová — překlepy v IČO, duplicitní faktury, špatné zařazení k
tenantovi. Tato SOPka tu část zautomatizuje a nechá člověka řešit jen edge cases
(nečitelný sken, neznámý tenant, corrupted file).

Intake **neúčtuje** — jen připraví soubory + strukturovaná metadata tak, aby na ně
mohl navázat T003 booking bez re-OCR a bez ruční klasifikace typu dokladu. JSON sidecar
je stabilní contract mezi T002 a T003.

## Design Note — prázdné `parameterized`

Template záměrně nemá žádné `{{ placeholder }}` parametry. Veškerý per-tenant config
(SharePoint paths, FlexiBee IDs, bankovní účty) žije v Supabase `tenants` tabulce a
resolvuje se runtime přes IČO odběratele extrahované z faktury. Jedna běžící instance
této SOPky obslouží všechny tenanty dynamicky, netřeba per-tenant `instances/` kopie.

## Inputs

- **SharePoint inbox složka** (globální) — fixní cesta `Shared Documents/Faktury/Inbox/`,
  obsahuje nově nahrané soubory z emailu, uploadů, Power Automate flows
- **Podporované file types** — `.pdf`, `.jpg`, `.jpeg`, `.png`, `.tiff`, `.heic`;
  ostatní formáty ignore + log
- **Supabase `tenants` tabulka** — mapa `ico → {slug, name, flexibee_*, sharepoint_root, ...}`
- **Supabase `sop_config`** — runtime knobs (thresholds, intervals) — viz Secrets & Config

## Secrets & Config

### From 1Password (`cortex-prod-core`)

| Name | Ref | Used in step |
|---|---|---|
| `SHAREPOINT_TENANT_ID` | `op://cortex-prod-core/sharepoint-yeast-prod/tenant_id` | 1,7,8 |
| `SHAREPOINT_CLIENT_ID` | `op://cortex-prod-core/sharepoint-yeast-prod/client_id` | 1,7,8 |
| `SHAREPOINT_CLIENT_SECRET` | `op://cortex-prod-core/sharepoint-yeast-prod/key_primary` | 1,7,8 |
| `AZURE_DOCINT_ENDPOINT` | `op://cortex-prod-core/azure-docint-prod/endpoint` | 2 |
| `AZURE_DOCINT_KEY` | `op://cortex-prod-core/azure-docint-prod/key_primary` | 2 |
| `ARES_API_KEY` | `op://cortex-prod-core/ares-gateway-prod/key_primary` | 3 |
| `IBAN_VALIDATOR_KEY` | `op://cortex-prod-core/iban-validator-prod/key_primary` | 4 |
| `SUPABASE_URL` | `op://cortex-prod-core/supabase-yeastfin-prod/endpoint` | 5,9 |
| `SUPABASE_SERVICE_KEY` | `op://cortex-prod-core/supabase-yeastfin-prod/key_primary` | 5,9 |
| `TELEGRAM_BOT_TOKEN` | `op://cortex-prod-core/telegram-bot-yeast-prod/token` | 9, HITL |
| `TELEGRAM_CHAT_INTAKE_REVIEW` | `op://cortex-prod-core/telegram-bot-yeast-prod/chat_id_intake_review` | HITL |
| `TELEGRAM_CHAT_ALERTS` | `op://cortex-prod-core/telegram-bot-yeast-prod/chat_id_alerts` | HITL |
| `TELEGRAM_CHAT_INTAKE_READY` | `op://cortex-prod-core/telegram-bot-yeast-prod/chat_id_intake_ready` | 9 |

### From Supabase (`sop_config` table, sop_id = `SOP-ACC-T002`)

| Name | Key | Default | Used in step |
|---|---|---|---|
| polling interval | `polling_interval_min` | `15` | 1 |
| OCR confidence doc threshold | `ocr_confidence_doc_threshold` | `0.75` | 2, HITL |
| OCR confidence — IČO fields | `ocr_confidence_field_threshold_ico` | `0.85` | 2, HITL |
| OCR confidence — InvoiceTotal | `ocr_confidence_field_threshold_total` | `0.70` | 2, HITL |
| OCR confidence — other key fields | `ocr_confidence_field_threshold_default` | `0.85` | 2, HITL |
| Type classifier threshold | `type_classifier_threshold` | `0.70` | 2, HITL |
| Tenant fuzzy IČO match threshold | `tenant_fuzzy_ico_threshold` | `0.90` | 5, HITL |
| Tenant fuzzy name match threshold | `tenant_fuzzy_name_threshold` | `0.85` | 5, HITL |
| Max retries per step | `max_retries` | `3` | all |
| Archive retention days | `archive_retention_days` | `90` | 8 |
| Duplicate detection window days | `duplicate_detection_window_days` | `90` | 1 |

**Poznámka k thresholdům:** rozdělení per-field vychází z Phase 0 empirického testu na 9
reálných CZ fakturách. InvoiceTotal má ~33% rate pod 0.85 kvůli komplexním layoutům
(multi-row totals, DPH breakdown, zálohy) — proto nižší práh 0.70; IČO fields drží 0.85,
ARES lookup (step 3) je authoritative safety net pro detekci OCR chyb v IČO.

## Preconditions

- [ ] Azure Doc Intelligence resource provisioned, klíče v 1P `azure-docint-prod`
- [ ] SharePoint app registration s Sites.ReadWrite.All permission, credentials v 1P
- [ ] Supabase `tenants` tabulka obsahuje aspoň jeden `active=true` záznam s platným IČO
- [ ] Supabase `intake_events` tabulka existuje (schema viz T003 contract)
- [ ] Telegram bot pozván do chatů `YEAST Intake Review`, `YEAST Alerts`, `YEAST Intake Ready`
- [ ] 1Password Connect dostupný, read token platný (rotation < 30 dní)
- [ ] Předchozí run dokončený (žádný running lock v Supabase `intake_run_locks`)

## Steps

### 1. Poll & lock inbox (idempotence check)

Seznam souborů v `Shared Documents/Faktury/Inbox/`, filtruj na supported file types a
exclude hidden / temp souborů (`~$*`, `.DS_Store`, `Thumbs.db`).

```
files = sharepoint.list(
    path="/Shared Documents/Faktury/Inbox/",
    filter_extensions=[".pdf", ".jpg", ".jpeg", ".png", ".tiff", ".heic"],
)
```

Pro každý soubor:

1. Spočítej SHA256 hash obsahu
2. Dotaz do Supabase `intake_events`: existuje row s `file_hash == <sha>` za posledních
   `duplicate_detection_window_days` dní?
3. Pokud ano → skip + log záznam s `status=duplicate_source`, pokračuj dalším souborem
4. Jinak → acquire lock (insert do `intake_run_locks` s `file_hash` jako key), pokračuj

**On failure:**
- SharePoint 5xx → retry 3× exponential backoff (1s, 4s, 16s)
- SharePoint 401/403 → STOP, notify `TELEGRAM_CHAT_ALERTS`, flag `sharepoint_auth_failed`
- Lock already held → skip (jiný paralelní run), log

### 2. Extract & classify document

Sub-kroky: (a) extract fields + OCR text → (b) post-processing normalizace → (c) multi-signal klasifikace typu.

#### 2a. Extract fields

Nejdřív pokus o native PDF text extraction (levnější, instant):

```
native_text = pdf_text_extractor.extract(file_bytes)
if native_text.length >= 200 and native_text.looks_like_invoice():
    text_source = "native"
else:
    text_source = "ocr"
```

Pokud `text_source == "ocr"`, zavolej Azure Doc Intelligence `prebuilt-invoice`:

```
result = azure_docint.analyze(
    model_id="prebuilt-invoice",
    document=file_bytes,
    locale="cs-CZ",
)
fields = result.documents[0].fields
confidence_doc = result.documents[0].confidence
content = result.content
```

#### 2b. Post-processing — normalizace OCR artefaktů

Reálné OCR výstupy z Phase 0 obsahují consistent quirks. Před klasifikací a validací
všechna extrahovaná pole projít následujícími normalizátory:

**`normalize_name(s)`** — strip newlines & collapse whitespace:
- `"PRAŽSKÁ\nPLYNÁRENSKÁ"` → `"PRAŽSKÁ PLYNÁRENSKÁ"`
- `"NNarosel\nOPTIFLOW"` → `"NNarosel OPTIFLOW"` (OCR error v prefixu zůstává, ARES step 3 to opraví)

**`normalize_ico(s)`** — extract čistě 8-digit IČO:
- `"CZ02939053"` → `"02939053"` (strip DIČ prefix)
- `"CZ60193492,"` → `"60193492"` (trailing punctuation)
- `"IČ: 02939053"` → `"02939053"` (prefix cleanup)
- `"24507318"` → `"24507318"` (no-op)

Implementace: regex `^(?:[A-Za-z]{2})?(\d{8})(?!\d)` s fallback na `(?<!\d)(\d{8})(?!\d)`.

**`extract_iban_from_content(content)`** — fallback když field chybí:
- Standard IBAN: `[A-Z]{2}\d{2}[A-Z0-9]{11,30}`
- CZ account: `[prefix-]account/bankcode` (např. `107-6130210257/0100`)

**`extract_variable_symbol_from_content(content)`** — fallback (Azure prebuilt-invoice VS nevrací spolehlivě):
- Pattern: `Variabiln[ií]\s*symbol[:\s]+(\S+)`

#### 2c. Multi-signal klasifikace typu dokladu

Klasifikace není triviální keyword matching — některé faktury nemají `"daňový doklad"` string,
ale stále jsou FP (Uppercut layout). Pravidla postupují odshora, první match vítězí:

| Priorita | Podmínka | Verdict | Confidence |
|---|---|---|---|
| 1 | Content contains `"předpis záloh"`, `"plán záloh"`, `"předpis k úhradě"`, `"rozpis záloh"`, `"zálohové platby"` | `PREDPIS` | 0.95 |
| 2 | Tax field count `∈ {0, 1}` (z polí: InvoiceId, DueDate, CustomerTaxId, TotalTax) | `PREDPIS` | 0.75 |
| 3 | Content contains `"zálohová faktura"`, `"proforma"`, `"není daňový doklad"`, `"zálohový list"` | `ZP` | 0.90 |
| 4 | Tax field count `>= 3` **AND** FP keyword match (`"faktura - daňový doklad"`, `"řádná faktura"`, `"daňový doklad"`, `"faktura"`) | `FP` | 0.95 |
| 5 | Tax field count `>= 3`, no keyword match | `FP` | 0.80 |
| 6 | Jinak | `OSTATNI` → HITL gate `unknown_document_type` | 0.50 |

**Phase 1 empirická validace:** 9/9 accuracy na reálném sample (8× FP + 1× PŘEDPIS).

**On failure:**
- Azure Doc Intelligence 5xx / timeout → retry 2×, pak HITL gate `processing_error`
- File cannot be parsed / corrupted → HITL gate `processing_error`
- Rate limit (429) → backoff podle `Retry-After` header, retry
- Native PDF extraction crash → log, fallback na OCR path

### 3. Validate IČO via ARES (authoritative source)

ARES je **authoritative source** pro canonical název firmy a existenci IČO. Tento krok
funguje jako safety net proti OCR chybám:

1. **Garbled IČO** — OCR přečte nonsense 8-digit string (Vodafone case: `24745371` nebo podobné),
   ARES vrátí `not_found` → HITL gate `ares_ico_not_found`.
2. **Garbled vendor name** — OCR přečte `"PIRE"` místo `"PRE"`, `"NNarosel OPTIFLOW"` místo
   `"NAROSEL OPTI-FLOW s.r.o."`. ARES vrátí canonical název, který zapíšeme do sidecaru
   místo OCR verze.

Volání:

```
for ico_role in ["supplier", "customer"]:
    ico = extracted[ico_role + "_ico"]   # z post-processing 2b, už normalizovaný na 8 digits
    if not ico:
        # CustomerTaxId často chybí u PŘEDPIS — to je OK, netriggeruj ares_ico_not_found
        if ico_role == "customer" and document_type in {"PREDPIS", "ZP"}:
            flag.append(f"{ico_role}_ico_missing_accepted_for_{document_type}")
            continue
        flag.append(f"{ico_role}_ico_missing")
        continue

    ares_result = ares.lookup(ico=ico)
    if not ares_result.exists:
        # HITL gate — garbled IČO, nelze booking
        flag.append(f"ares_not_found:{ico_role}:{ico}")
        trigger_gate("ares_ico_not_found", reason=f"{ico_role} IČO {ico} neexistuje v ARES")
        return

    # Override: ARES canonical name má přednost před OCR name
    sidecar[ico_role]["name_on_invoice"] = extracted[ico_role + "_name"]
    sidecar[ico_role]["name_in_ares"] = ares_result.name         # canonical
    sidecar[ico_role]["name_canonical"] = ares_result.name       # použít v rename + Supabase
    sidecar[ico_role]["ares_verified"] = True

    # Soft flag pokud OCR název zásadně odlišný od ARES
    if fuzzy_match(ares_result.name, extracted[ico_role + "_name"]) < 0.70:
        flag.append(f"ares_name_mismatch:{ico_role}:ocr='{extracted[ico_role+'_name']}'_ares='{ares_result.name}'")
```

**Důsledky pro downstream:**
- Step 5 (Resolve tenant) používá ARES canonical name pro name fuzzy match, ne OCR verzi
- Step 6 (Rename) používá ARES name slug (reproducible, stabilní) — žádné `NNarosel`
- Sidecar JSON drží oba — `name_on_invoice` (pro audit) a `name_in_ares` (pro booking)

**On failure:**
- ARES 5xx → retry 2× exp backoff, pak STOP + HITL gate `processing_error` (ARES je hard dependency teď)
- ARES timeout > 5s → retry, pak STOP
- ARES vrátí `not_found` na validní-vypadající IČO → HITL gate `ares_ico_not_found`, ne skip
- Chybějící CustomerTaxId u `FP` typu → flag `customer_ico_missing`, pokud fuzzy name match
  taky selže v step 5 → HITL gate `unknown_tenant`

### 4. Validate IBAN

Pokud faktura obsahuje IBAN (field `PaymentDetails` z Doc Intelligence):

```
iban_result = iban_validator.validate(iban)
payment = {
    "iban": iban,
    "iban_valid": iban_result.valid,
    "bank_code": iban_result.bank_code,
    "bank_name": iban_result.bank_name,
}
```

Pokud IBAN chybí úplně:
- Pro `FP` — flag `missing_iban: true` (podivné, ale ne block — booking řeší)
- Pro `ZP`, `PREDPIS` — OK (předpis/záloha často bez bankovních údajů)

Invalid IBAN = flag `iban_valid: false`, NE HITL (T003 to řeší při párování platby).

### 5. Resolve tenant (Supabase lookup — 4-step fallback)

Cílem je najít YEAST tenant, kterému faktura patří. Pro všechny aktuálně podporované
typy (`FP`, `ZP`, `PREDPIS`) je tenant = **odběratel**.

**Resolution chain — první match vítězí:**

**(1) Exact IČO match**

```
tenant = supabase.query("""
    SELECT slug, name, flexibee_company, sharepoint_root, default_iban
    FROM tenants
    WHERE ico = $1 AND active = true
""", customer_ico)
if tenant: return tenant  # matched_by = "ico_exact"
```

**(2) Fuzzy IČO match** (tolerance pro OCR typo — 1 digit swap/omit)

```
# Levenshtein distance <= 1 na 8-digit string
tenant = fuzzy_ico_match(customer_ico, threshold=0.90)
if tenant: return tenant  # matched_by = "ico_fuzzy"
```

**(3) Fuzzy name match** — primary path pro PŘEDPIS (Plán záloh nemá CustomerTaxId)

```
# Preferuj ARES canonical name z Step 3, fallback na OCR extracted name
candidate_name = sidecar.customer.name_in_ares or sidecar.customer.name_on_invoice
tenant = fuzzy_name_match(
    candidate_name,
    threshold=0.85,  # tenant_fuzzy_name_threshold
)
if tenant: return tenant  # matched_by = "name_fuzzy"
```

**(4) HITL gate** — žádná strategie netrefila

```
trigger_gate("unknown_tenant", reason={
    "extracted_ico": customer_ico,
    "extracted_name": candidate_name,
    "ares_canonical": sidecar.customer.name_in_ares,
    "attempted_strategies": ["ico_exact", "ico_fuzzy", "name_fuzzy"],
})
```

**Zapsat do sidecaru** (pro audit a booking):

```
sidecar.tenant.matched_by = "ico_exact" | "ico_fuzzy" | "name_fuzzy" | "hitl" | null
sidecar.tenant.match_confidence = 1.0 | 0.90-0.99 | 0.85-0.99 | null
```

**On failure:**
- Supabase unreachable → retry 2×, pak HITL gate `processing_error`
- Multiple rows pro jeden IČO (data integrity) → STOP, alert, `processing_error`
- Multiple fuzzy name matches se stejnou confidence → preferuj nejvyšší, v případě
  shody → HITL gate `unknown_tenant` s kandidáty

### 6. Rename & write sidecar

Konvence názvu souboru:

```
<ISO-date>_<TYPE>_<supplier-slug>_<invoice-number>.pdf
```

Příklady:
- `2026-04-21_FP_abc-dodavatel-sro_2026-0123.pdf`
- `2026-04-15_PREDPIS_innogy-energie-as_SIPO-20260415.pdf`
- `2026-04-10_ZP_xyz-sro_ZAL-2026-0042.pdf`

`supplier-slug` = lowercase, kebab-case, diakritika stripped, suffixy `s.r.o.`, `a.s.`
ponechány jako `sro` / `as` bez teček.

JSON sidecar `<same-basename>.meta.json` vedle PDF, schema verze `1.0.0` (viz
příloha níže — _Output sidecar schema_).

### 7. Route to target folder

Target path sestaven z Supabase `tenants.sharepoint_root` + typ dokladu:

```
target = f"{tenant.sharepoint_root}/{doc_type}/"
```

Příklad: `/Shared Documents/Faktury/K-zauctovani/pq-group/FP/`

Move PDF + JSON jako atomic operation (sharepoint API podporuje move v jedné call).

**On failure:**
- Target folder neexistuje → auto-create, pak retry
- Permission denied → HITL gate `processing_error`
- Partial move (PDF moved, JSON not) → rollback: move PDF zpět do inboxu, alert

### 8. Archive source

Move originální soubor z `Inbox/` do `Inbox/_processed/<YYYY-MM>/<sha-prefix>_<original-name>`:

```
archive_path = f"/Shared Documents/Faktury/Inbox/_processed/{year_month}/{sha[:8]}_{original_name}"
sharepoint.move(source=inbox_file, destination=archive_path)
```

Prefix SHA256 v názvu = ochrana před kolizí při re-uploadu stejného jména.

Retention `archive_retention_days` (default 90) — cleanup zajistí samostatný
scheduled job (mimo scope této SOPky).

**On failure:**
- Archive folder neexistuje → auto-create
- Move fails → NE rollback routed file (ten už je v T003 queue), jen alert + flag v
  JSON sidecar `source_archive_failed: true`. Manuální cleanup later.

### 9. Emit intake event

Duplikace do dvou míst (event sourcing + human notification):

**a) Supabase `intake_events` row** (machine consumer — trigger pro T003):

```sql
INSERT INTO intake_events (
    sop_id, run_id, file_hash, tenant_slug, document_type,
    routed_path, supplier_ico, invoice_number, total_amount, currency,
    hitl_required, hitl_reason, duration_ms, status, created_at
) VALUES (
    'SOP-ACC-T002', $run_id, $sha, $tenant, $type,
    $routed_path, $supplier_ico, $invoice_number, $total, $currency,
    false, null, $duration_ms, 'success', now()
);
```

**b) Telegram message** do `TELEGRAM_CHAT_INTAKE_READY`:

```
✅ Nová faktura připravená k zaúčtování
   Tenant: {tenant.name}
   Typ: {doc_type}
   Dodavatel: {supplier_name} (IČO {supplier_ico})
   Částka: {total_amount} {currency}
   Cesta: {routed_path}
```

Pokud je HITL flag set, zpráva jde místo toho do `TELEGRAM_CHAT_INTAKE_REVIEW` s
action buttons (pokud Telegram inline keyboard podporován), jinak plain text.

**On failure:**
- Supabase insert fails → retry 3×, pak STOP (bez event není T003 triggered)
- Telegram send fails → retry 2×, pak pokračuj (event v Supabase je canonical, Telegram
  je notification layer). Flag `telegram_notify_failed` v Supabase row pro later review.

## Human approval gates

### Gate `low_ocr_confidence`

- **Podmínka:** `confidence_doc < ocr_confidence_doc_threshold` (default 0.75) **NEBO**
  confidence některého klíčového pole (IČO odběratele, IČO dodavatele, total amount,
  invoice date, IBAN) `< ocr_confidence_field_threshold` (default 0.85)
- **Akce:**
  1. Move soubor do `/Shared Documents/Faktury/Inbox/_REVIEW/ocr_low/`
  2. Write preliminary JSON sidecar (to co se povedlo extrahovat) vedle
  3. Telegram do `TELEGRAM_CHAT_INTAKE_REVIEW`: thumbnail první strany + extracted
     fields + confidence per field, link na SharePoint file
- **Timeout:** 24h → re-ping + eskalace na `business_owner` email

### Gate `unknown_document_type`

- **Podmínka:** type classifier verdict = `OSTATNI` **NEBO** `type_confidence <
  type_classifier_threshold` (default 0.70)
- **Akce:**
  1. Move soubor do `/Shared Documents/Faktury/Inbox/_REVIEW/unknown_type/`
  2. Write preliminary JSON sidecar s `document.type: "OSTATNI"`,
     `hitl_required: true`, `hitl_reason: "unknown_document_type"`
  3. Telegram do `TELEGRAM_CHAT_INTAKE_REVIEW`: nabídka manuálního tagu (FP/ZP/PREDPIS)
- **Timeout:** 24h → re-ping

### Gate `unknown_tenant`

- **Podmínka:** Všechny 3 strategie step 5 selhaly: (1) exact IČO match, (2) fuzzy IČO
  match `< tenant_fuzzy_ico_threshold` (default 0.90), (3) fuzzy name match
  `< tenant_fuzzy_name_threshold` (default 0.85)
- **Akce:**
  1. Move soubor do `/Shared Documents/Faktury/Inbox/_REVIEW/unknown_tenant/`
  2. Write JSON sidecar s extracted supplier + customer info + ARES canonical name
  3. Telegram do `TELEGRAM_CHAT_INTAKE_REVIEW`: "Faktura pro IČO `{customer_ico}`
     (OCR `{name_on_invoice}`, ARES `{name_in_ares}`). Není v registru tenantů.
     Přidat tenant, nebo discard?"
- **Timeout:** 48h → re-ping; po 72h auto-move do `_REVIEW/unknown_tenant/_stale/`

### Gate `ares_ico_not_found`

- **Podmínka:** Extracted IČO (supplier nebo customer) **neexistuje v ARES** (step 3
  `ares_result.exists == false`). Typicky OCR garbled 8-digit číslo (např. Vodafone
  Phase 0 finding: extracted `CZ24745371` co v ARES neexistuje).
- **Akce:**
  1. Move soubor do `/Shared Documents/Faktury/Inbox/_REVIEW/ares_not_found/`
  2. Write partial sidecar s `ares_verified: false` + všemi extracted poli
  3. Telegram do `TELEGRAM_CHAT_INTAKE_REVIEW`: "IČO `{ico}` ({role}) na faktuře
     `{filename}` neexistuje v ARES. Pravděpodobně OCR chyba. Oprav manuálně
     nebo odmítni."
  4. Nabídnout re-lookup po manuální korekci IČO (ideálně akční tlačítko v Telegramu)
- **Timeout:** 24h → re-ping + eskalace na `business_owner`

### Gate `processing_error`

- **Podmínka:** Jakýkoli unhandled exception z předchozích kroků (corrupted PDF,
  Azure API 5xx po retry, Supabase unreachable po retry, SharePoint permission denied)
- **Akce:**
  1. Move soubor do `/Shared Documents/Faktury/Inbox/_REVIEW/errors/`
  2. Write error.json vedle s stack trace, failing step, retry count
  3. Telegram do `TELEGRAM_CHAT_ALERTS` (ne intake-review — systemic issue) s
     stacktrace + run_id pro investigaci
- **Timeout:** 4h — kratší, protože systemic issues blokují celý pipeline

## Exception Handling

| Situace | Akce | Kdo řeší |
|---|---|---|
| SharePoint 5xx | Retry 3× exp backoff, pak alert | Agent |
| SharePoint auth expired | STOP, critical alert | Human (IT ops) |
| Azure Doc Intelligence 5xx | Retry 2× | Agent |
| Azure Doc Intelligence rate limit | Honor Retry-After, retry | Agent |
| ARES 5xx po retry | STOP + HITL gate `processing_error` (ARES je authoritative) | Human (IT ops) |
| ARES not_found na extracted IČO | Gate `ares_ico_not_found` | Human (accountant) |
| ARES name mismatch (fuzzy < 0.70) | Soft flag, booking T003 decides | Agent |
| Supabase unreachable | Retry 2×, pak gate `processing_error` | Agent → Human |
| Corrupted PDF | Gate `processing_error` | Human (accountant) |
| Low OCR confidence | Gate `low_ocr_confidence` | Human (accountant) |
| Unknown doc type | Gate `unknown_document_type` | Human (accountant) |
| Unknown tenant | Gate `unknown_tenant` | Human (accountant + admin) |
| Duplicate source file (SHA match) | Skip + log, pokračovat | Agent |
| Target folder missing | Auto-create, retry | Agent |
| Partial move (PDF yes, JSON no) | Rollback, alert | Agent → Human |
| Archive move fails | Flag, keep routed file, alert | Agent → Human |
| Telegram send fails | Flag in Supabase, continue | Agent |

## Output

Per úspěšně zpracovanou fakturu:

- **Routed PDF** v `<tenant.sharepoint_root>/<TYPE>/<renamed>.pdf`
- **JSON sidecar** v `<tenant.sharepoint_root>/<TYPE>/<renamed>.meta.json`
- **Archive originál** v `Inbox/_processed/<YYYY-MM>/<sha-prefix>_<orig-name>`
- **Supabase row** v `intake_events`
- **Telegram msg** do `YEAST Intake Ready`

Per HITL gate faktura:

- **Review PDF + JSON** v `Inbox/_REVIEW/<gate>/<file>`
- **Supabase row** v `intake_events` s `hitl_required=true`, `hitl_reason=<gate>`
- **Telegram msg** do `YEAST Intake Review` nebo `YEAST Alerts`

## Output sidecar schema (JSON, version 1.0.0)

```json
{
  "schema_version": "1.0.0",
  "intake": {
    "source_path": "string",
    "source_sha256": "string",
    "renamed_to": "string",
    "target_path": "string",
    "processed_at": "ISO8601 datetime",
    "sop_version": "SOP-ACC-T002:0.1.0",
    "run_id": "uuid"
  },
  "ocr": {
    "engine": "azure-doc-intelligence | native-pdf",
    "model": "prebuilt-invoice | null",
    "text_source": "native | ocr",
    "confidence_doc": "number (0-1)",
    "confidence_key_fields": { "ico_customer": 0.0, "ico_supplier": 0.0, "total_amount": 0.0, "iban": 0.0 }
  },
  "document": {
    "type": "FP | ZP | PREDPIS | OSTATNI",
    "type_confidence": "number (0-1)",
    "type_detection_method": "ocr_keywords | docint_classifier | hitl",
    "is_tax_document": "boolean"
  },
  "tenant": {
    "slug": "string | null",
    "name": "string | null",
    "ico": "string | null",
    "matched_by": "ico_exact | fuzzy_name | hitl | null",
    "match_confidence": "number (0-1) | null",
    "supabase_tenant_id": "uuid | null"
  },
  "supplier": {
    "ico": "string | null",
    "name_on_invoice": "string | null",
    "name_in_ares": "string | null",
    "dic": "string | null",
    "address": "string | null",
    "ares_verified": "boolean"
  },
  "invoice": {
    "number": "string | null",
    "variable_symbol": "string | null",
    "issue_date": "ISO8601 date | null",
    "taxable_supply_date": "ISO8601 date | null",
    "due_date": "ISO8601 date | null",
    "total_amount": "number | null",
    "base_amount": "number | null",
    "vat_amount": "number | null",
    "vat_rate": "number | null",
    "currency": "string | null"
  },
  "payment": {
    "iban": "string | null",
    "iban_valid": "boolean | null",
    "bank_code": "string | null",
    "bank_name": "string | null",
    "account_number": "string | null"
  },
  "flags": "array of strings",
  "hitl_required": "boolean",
  "hitl_reason": "low_ocr_confidence | unknown_document_type | unknown_tenant | processing_error | null"
}
```

## Validation

- `no_unhandled_exceptions_in_run` — run completion záznam v `intake_events` má
  `status ∈ {success, partial}`, nikdy `failed`
- `all_inbox_files_processed_or_flagged_within_run` — po runu platí
  `count(inbox/*) == count(processed + routed + review)` za tento run_id
- `run_duration_under_10_min_for_50_files` — `intake_events.duration_ms` aggregated per
  run_id < 600s při 50 souborech
- `each_file_routed_to_tenant_type_folder_or_review` — filesystem check: žádný soubor
  ze run_id nezůstal v `Inbox/` (root level)
- `each_file_has_valid_sidecar_json_matching_schema` — JSON Schema validace proti
  `schema_version: 1.0.0`
- `each_source_archived_or_moved_to_review_not_left_in_inbox` — originální file_hash
  má záznam o archivaci nebo _REVIEW move
- `document_type_in_allowed_set_or_hitl_flagged` — `document.type ∈ {FP, ZP, PREDPIS}`
  OR `hitl_required == true`
- `tenant_resolved_or_hitl_flagged` — `tenant.slug != null` OR `hitl_required == true`
- `filename_matches_convention` — regex `^\d{4}-\d{2}-\d{2}_(FP|ZP|PREDPIS)_[a-z0-9-]+_[A-Za-z0-9-]+\.(pdf|jpg|jpeg|png|tiff|heic)$`
- `intake_event_row_in_supabase_and_telegram_msg_sent` — pro každý successfully routed
  file existuje `intake_events` row AND buď `telegram_msg_id` není null, nebo
  `telegram_notify_failed` flag set (explicit failure, ne missing)
- `idempotent_no_duplicate_processing_of_same_file_hash` — žádné dva rows v
  `intake_events` s `status=success` a stejným `file_hash` v window
  `duplicate_detection_window_days`

## Role mapping

_Doplníme až vzniknou role `ROLE-ACC-*` pokrývající invoice workflow. Kandidáti:
junior accountant (execute, respond na HITL gates), senior accountant (override gates),
admin (config změna v `sop_config`, přidání tenantu)._

## Changelog

- 2026-04-23 — v0.2.0 — refine podle Phase 0+1 empirických testů na 9 reálných CZ fakturách (100% classifier accuracy): (1) per-field OCR thresholds — IČO 0.85, InvoiceTotal snížen na 0.70 (reálné layouty to potřebují); (2) step 2 rozšířen o explicit post-processing normalizaci (normalize_name, normalize_ico) a multi-signal klasifikační tabulku pravidel; (3) step 3 upgrade — ARES je teď mandatory authoritative source, canonical name override pro OCR garbled vendor names (PIRE→PRE case); (4) step 5 4-step tenant fallback chain (exact IČO → fuzzy IČO → fuzzy name → HITL), fuzzy name je primary path pro PŘEDPIS; (5) nový HITL gate `ares_ico_not_found` pro OCR-garbled IČO (Vodafone 24745371 case); (6) success criteria rozšířeny o ARES verification + canonical naming (petr@yeast-group.cz)
- 2026-04-23 — v0.1.0 — initial draft, intake pipeline pro SharePoint inbox → tenant/typ routing s OCR, klasifikací, ARES/IBAN validací a JSON sidecar contractem pro T003 booking (petr@yeast-group.cz)
