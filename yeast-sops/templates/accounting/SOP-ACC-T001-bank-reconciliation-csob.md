---
id: SOP-ACC-T001
name: "Bank Reconciliation – ČSOB"
version: 0.1.0
status: draft
owner: petr@yeast-group.cz
business_owner: petr@yeast-group.cz
domain: accounting
tenant:
  type: template
  parameterized:
    - bank_account_iban
    - company_flexibee_code
    - notification_channel
    - unmatched_threshold_czk
last_reviewed: 2026-04-23
reviewed_by: petr@yeast-group.cz
next_review: 2026-10-23
agent_suitable: true
automation_level: supervised
required_tools:
  - mcp:flexibee
  - internal:bank-sync-service
required_connectors:
  - csob_api
required_permissions:
  - read:bank_statements
  - write:flexibee_transactions
  - notify:slack
trigger: scheduled
schedule: "0 8,12,18 * * 1-5"
estimated_duration_min: 5
criticality: high
human_approval_required:
  - unmatched_transactions_over_threshold
  - balance_mismatch
  - new_counterparty_detected
success_criteria:
  - all_transactions_imported
  - flexibee_balance_matches_bank_closing_balance
  - no_duplicate_entries
  - no_unmatched_over_threshold_without_approval
tags:
  - accounting
  - bank
  - csob
  - recurring
  - reconciliation
related_sops: []
references:
  - label: "ČSOB Přímý kanál documentation"
    url: "https://www.csob.cz/portal/firmy/platebni-sluzby/primy-kanal"
  - label: "FlexiBee MCP – flexi_load_bank_statement"
    url: "https://mcp.yeast-group.cz/flexibee/mcp"
---

# Bank Reconciliation – ČSOB

## Cíl

Stáhnout denní pohyby z ČSOB účtu `{{ bank_account_iban }}`, naimportovat je do FlexiBee
(společnost `{{ company_flexibee_code }}`), provést primární spárování proti otevřeným
pohledávkám/závazkům a eskalovat nepárované položky nad limit `{{ unmatched_threshold_czk }} CZK`
do kanálu `{{ notification_channel }}`.

## Kontext / Proč

Bez denního reconcile se rychle rozpadne cash-flow přehled a manuální dohánění na konci
měsíce stojí účetní desítky hodin. Klient si navíc často plete "vidím to v bance" s
"je to zaúčtované". Automatický import 3× denně (ráno, poledne, večer) udržuje FlexiBee
max. 4 hodiny za realitou.

Pozn.: u ČSOB se ABO/GPC typicky generuje 1–2× denně, takže 3× denně polling je zde
dostatečný a nevyvolá 429 na API.

## Inputs

- **`bank_account_iban`** (string) — IBAN účtu, ze kterého stahujeme
- **`company_flexibee_code`** (string) — dbNazev ve FlexiBee, kam se transakce vkládají
- **`notification_channel`** (string) — Slack kanál pro alerty, formát `slack:#channel-name`
- **`unmatched_threshold_czk`** (number) — nad tuto částku (absolutní hodnota) se jednotlivá
  nepárovaná transakce eskaluje
- **Date range** (implicit) — od posledního úspěšného importu do `now`

## Preconditions

- [ ] ČSOB API credentials platné (cert vyprší alespoň za 14 dní)
- [ ] FlexiBee instance `{{ company_flexibee_code }}` dostupná
- [ ] Předchozí běh dokončený (žádný running lock)
- [ ] Bank sync service healthcheck OK

## Steps

### 1. Zjisti, odkud navazuje import

Přečti poslední úspěšný `last_imported_payment_id` z FlexiBee (custom field na bank účtu).
Pokud neexistuje (první spuštění), vezmi `date - 7 days` jako start.

```
last_ok = flexibee.get_custom_field(
    evidence="bankovni-ucet",
    code="{{ company_flexibee_code }}",
    field="last_imported_payment_id",
)
```

### 2. Fetch transactions z ČSOB

Zavolej bank-sync service s adaptérem pro ČSOB.

```
txs = bank_sync.fetch(
    adapter="csob",
    iban="{{ bank_account_iban }}",
    since=last_ok or (today - 7d),
)
```

**On failure:**
- HTTP 5xx → retry 3× s exponenciálním backoffem (1s, 4s, 16s)
- HTTP 4xx (auth) → STOP, notify `{{ notification_channel }}`, open issue "ČSOB auth failed"
- Timeout → retry 1×, pak STOP

### 3. Deduplikace

Pro každou transakci zkontroluj, zda `payment_id` už ve FlexiBee existuje.

```
for tx in txs:
    if flexibee.query(
        evidence="banka",
        filter=f"varSym='{tx.payment_id}' and typPohybuK='in' and bankUcet='{{ bank_account_iban }}'",
    ):
        skip(tx, reason="duplicate")
```

### 4. Match to invoices

Pro každou zbývající transakci:

1. Match podle `VS` → najdi otevřenou fakturu se stejným VS
2. Pokud ne, match podle `částka + účet protistrany + ±3 dny`
3. Pokud ne, match podle `účet protistrany + částka` (pozor na false positives)
4. Pokud ne → flag jako `unmatched`

### 5. Human approval gate – unmatched nad threshold

Pokud existují transakce s `abs(amount) >= {{ unmatched_threshold_czk }}` a `matched=false`:

- Pošli do `{{ notification_channel }}` strukturovanou zprávu s:
  - Počet unmatched, suma unmatched
  - Top 5 s detaily: datum, částka, protistrana, VS, note
  - Odkaz na FlexiBee queue pro manuální párování
- **STOP import pro tyto transakce**, uloží se do "pending approval" stavu
- Ostatní transakce (pod threshold nebo matched) pokračují

Timeout: 4 hodiny → eskalace na `business_owner`.

### 6. Human approval gate – nová protistrana

Pokud transakce odkazuje na bankovní účet, který ještě není v adresáři firem (`flexi_find_firma`):

- Flag jako `new_counterparty`
- Vytvoř návrh záznamu v adresáři (draft status)
- Notifikuj do `{{ notification_channel }}` s přímým odkazem

### 7. Commit do FlexiBee

Pro schválené a zmatchované transakce:

```
flexibee.upsert_record(
    evidence="banka",
    data={...},
    dry_run=false,
)
```

Aktualizuj `last_imported_payment_id` na nejvyšší úspěšně importované.

### 8. Validace po importu

- Spočítej zůstatek ve FlexiBee po importu
- Porovnej s `closing_balance` z ČSOB statement
- Pokud se liší o více než 1 Kč → STOP, notify, flag `balance_mismatch`

### 9. Report

Pošli do `{{ notification_channel }}` shrnutí:

```
✅ Bank reconciliation ČSOB — {{ company_flexibee_code }}
   Period: 2026-04-22 12:00 → 2026-04-23 08:00
   Imported: 12 tx
   Matched: 11
   Unmatched: 1 (under threshold)
   Balance: 1 234 567,89 CZK (matches)
```

## Exception Handling

| Situace | Akce | Kdo řeší |
|---|---|---|
| ČSOB API 5xx | Retry 3× exp backoff, pak notify | Agent |
| ČSOB cert expired | STOP, critical alert | Human (IT ops) |
| FlexiBee unreachable | Retry 2×, pak STOP + alert | Human (IT ops) |
| Balance mismatch | STOP, přepnout do supervised mode | Human (accountant senior) |
| Duplicate VS | Skip + log, pokračovat | Agent |
| Unmatched nad threshold | Gate → Slack approval | Human (accountant) |
| Nová protistrana | Gate → draft + Slack notify | Human (accountant) |

## Output

- FlexiBee `banka` záznamy (stav: schváleno nebo pending)
- Slack report do `{{ notification_channel }}`
- Aktualizovaný `last_imported_payment_id`
- Audit log záznam do Cortex audit stream

## Validation

- `flexibee_balance_matches_bank_closing_balance` — ověřeno v kroku 8
- `all_transactions_imported` — count(ČSOB txs) == count(FlexiBee new) + count(skipped duplicates) + count(pending approval)
- `no_duplicate_entries` — ověřeno v kroku 3
- `no_unmatched_over_threshold_without_approval` — žádná transakce s amount >= threshold a status=active bez approval flagu

## Role mapping

- `ROLE-ACC-001` (Accountant Junior) — může spouštět manuálně, nemůže overridovat HITL gates
- `ROLE-ACC-002` (Accountant Senior) — může spouštět, může overridovat gates s audit zdůvodněním
- `ROLE-ACC-003` (Head of Accounting) — full control včetně template modifikace

## Changelog

- 2026-04-23 — v0.1.0 — initial draft, template for YEAST Group ČSOB accounts (petr@yeast-group.cz)
