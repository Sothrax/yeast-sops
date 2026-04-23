---
name: sop-validate
description: Run validation checks on the yeast-sops repository. Use when user asks to validate, check, or verify SOPs, roles, or the entire repo. Use when user says "validate", "zkontroluj SOPky", "/sop:validate", "jsou SOPky OK", or after making edits to SOPs.
---

# sop-validate

Pustí `scripts/validate.py` s vhodnými argumenty a reportuje výsledek.

Načti `sop-shared` pro cestu k repu.

## Jak to funguje

### Výchozí režim: validate everything

```bash
python scripts/validate.py
```

Pokud user nespecifikuje nic, spusť toto.

### Cílené validace

| User říká | Spusť |
|---|---|
| "valiadte SOP X" | `python scripts/validate.py --sop <ID>` |
| "validate role X" | `python scripts/validate.py --role <ID>` |
| "check stale" | `python scripts/validate.py --stale` |
| "strict check" | `python scripts/validate.py --strict` |
| "everything + stale + strict" | `python scripts/validate.py --stale --strict` |

### Parsing výstupu

Výstup má format:
```
[ERROR] path: message
[WARN ] path: message
Checked N files: E errors, W warnings
```

**Reportuj uživateli:**

1. Pokud `0 errors, 0 warnings` → stručně "Vše čisté, N souborů zkontrolováno."
2. Pokud errors → vyjmenuj je, seskupené podle souboru, nabídni help s opravou.
3. Pokud warnings (a není strict) → upozorni, ale necommituj panic. Warnings jsou
   hlavně stale SOPs a filename mismatches.

## Pre-commit hook use case

Když uživatel říká "před commitem" nebo "před PR":

1. `python scripts/validate.py --strict`
2. Pokud fail → **blokuj commit**, ukaž errors
3. Pokud OK → potvrď, ať user commitne

## Interpretace typických chyb

- `id: does not match pattern` → ID má špatný format, zkontroluj konvenci `SOP-<DOM>-<T|I><NNN>`
- `required_tools is a required property` → pokud `agent_suitable: true`, musí být vyplněné tools
- `File is in templates/ but tenant.type is 'instance'` → soubor je ve špatné složce
- `derived_from references unknown template` → instance ukazuje na neexistující template
- `SOP is N days past next_review` → review expired, owner by měl projet a updatovat

## Output format

Stručný bullet report. Konkrétní chyby jako:

```
❌ templates/accounting/SOP-ACC-T003-invoice.md
   - id: does not match pattern '^SOP-(ACC|HR|LEG|OPS|IT|FIN)-(T|I)[0-9]{3}$'
   - required_permissions: missing required field

⚠️  templates/hr/SOP-HR-T001-onboarding.md
   - 45 days past next_review (2026-03-08)
```

Ne dlouhý výpis, ale actionable items.
