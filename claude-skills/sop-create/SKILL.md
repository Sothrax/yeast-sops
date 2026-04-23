---
name: sop-create
description: Create a new SOP in the yeast-sops repository via a structured interview. Use when the user wants to document a process, create a new Standard Operating Procedure, formalize a workflow, or capture a procedure for potential agent automation. Also use when user types /sop:create or says "new SOP", "create SOP", "nová SOPka", "udělej SOPku".
---

# sop-create

Vede uživatele strukturovaným interview k vytvoření nové template SOPky.
Výstup: commit-ready markdown v `templates/<domain>/SOP-<DOMAIN>-T<NNN>-<slug>.md`.

Než začneš, načti `sop-shared` SKILL.md pro konvence a strukturu repa.

## Workflow

### 1. Quick intake (1 otázka)

Začni jednou otázkou, ne formulářem:

> "OK, nová SOPka. Řekni mi jednou větou, co ten proces dělá."

Z odpovědi odhadni:
- **Doménu** (accounting / hr / legal / it-ops / finance / operations)
- **Zda je to template** (99 % případů ano — SOPka vzniká jako template)

Pokud odhad doménu není jednoznačný, zeptej se.

### 2. Generate next ID

Projdi `templates/<domain>/` a najdi nejvyšší `T<NNN>`. Nové ID = `+1`.

Pokud je to první SOPka v doméně: `T001`.

### 3. Structured interview

**Klíčové pravidlo: jedna otázka per turn, s default návrhem.**

Otázky v pořadí — přeskoč ty, kde odpověď už zaznívala nebo je zřejmá:

#### Q1: Trigger
> "Kdy se ten proces spouští? Default: `manual` (někdo ho ručně odstartuje). Nebo je to `scheduled` (cron), `event` (něco se stane), `webhook` (přijde volání zvenčí)?"

Pokud `scheduled`: follow-up "Jak často? Potřebuju cron expression nebo aspoň česky popiš (3× denně v pracovní dny)."

#### Q2: Inputs
> "Co ten proces potřebuje na vstupu? Řekni mi 2-5 klíčových věcí. Např. u bank rec to bylo IBAN, FlexiBee kód, threshold."

Z odpovědi:
- Identifikuj **tenant-variable** hodnoty → půjdou do `tenant.parameterized`
- Identifikuj **runtime** hodnoty → popíšou se v sekci Inputs v body

#### Q3: Tools & connectors
> "Jaké systémy / API to bude používat? FlexiBee? Toggl? ClickUp? Bank API? Slack? Vlastní služba?"

Mapuj na `required_tools` (prefix `mcp:` / `internal:` / `external:`) a `required_connectors`.

#### Q4: Steps — high level
> "Teď hlavní kostra — 3 až 10 kroků v pořadí. Klidně česky, jednou větou každý. Vylaďujeme to později."

Z odpovědi vygeneruj sekci `## Steps` s vyplněnými názvy kroků. Každý jako `### N. <název>` + krátký popis. **Detaily se dořeší v refine fázi.**

#### Q5: HITL gates
> "Kde chceš, aby se AI agent zastavil a čekal na lidské schválení? Např. 'unmatched > 10k CZK', 'nový klient', 'změna fakturačních údajů'. Když nic, default bude jen na error."

Mapuj na `human_approval_required` seznam + jednotlivé `### Human approval gate` sekce v body.

#### Q6: Success criteria
> "Jak **strojově** poznáš, že úkol proběhl OK? Musí to být kontrolovatelné podmínky, ne feel-good fráze."

Příklady dobrých: `balance_matches`, `all_rows_imported`, `no_duplicates`.
Příklady špatných: `"process completed successfully"`, `"user happy"`.

#### Q7: Criticality & automation level
> "Poslední dva: jak kritický to je (low/medium/high/critical) a jaký automation level navrhuješ (manual/assisted/supervised/autonomous)?"

Default podle criticality:
- `critical` + nový proces → **navrhni `supervised`** (AI s HITL, nikdy ne autonomous pro first release)
- `high` → `supervised` nebo `assisted`
- `medium` → `assisted`
- `low` → může být `autonomous` hned

### 4. Generate draft

Vygeneruj kompletní markdown s frontmatterem a body. Použij `templates/_template.md` jako kostru, ale naplň ji odpověďmi.

**Nezapomeň:**
- `status: draft` (vždy, nikdy `active` při vytvoření)
- `version: 0.1.0`
- `owner`: email ownera repa (default `petr@yeast-group.cz`, pokud neví jinak)
- `last_reviewed: <today>`
- `next_review: <today + 6 měsíců>` (nebo 3 měsíce pro `critical`)
- Changelog entry: `YYYY-MM-DD — v0.1.0 — initial draft (<owner>)`

### 5. Review & save

Ukaž draft uživateli. Zeptej se:

> "Tady je draft. Chceš: (a) uložit rovnou, (b) projít kroky detailněji, (c) něco konkrétního upravit?"

Pokud (a) — zapiš soubor do `templates/<domain>/SOP-<DOMAIN>-T<NNN>-<slug>.md`, spusť
`python scripts/validate.py --sop <ID>`, report výsledek.

Pokud validace projde → commit message návrh:

> `Add SOP-XXX-TNNN: <name>`

Pokud (b) — přepni do refine módu pro jednotlivé kroky.

Pokud (c) — přijmi změnu, regeneruj, zpátky na review.

## Edge cases

- **Uživatel řekne "tohle nevím teď"** → přidej do body `## TODO` sekci s otázkou,
  pokračuj dál. SOPka může být commitnuta jako `status: draft` s TODO.
- **Uživatel popíše proces, který už existuje jako SOPka** → nabídni refine existující
  místo vytvoření nové. Pro jistotu udělej `grep -r "klíčová slova" templates/` než začneš.
- **Uživatel chce instanci, ne template** → přesměruj: "To je instance, ne template.
  Nejdřív potřebujeme template. Máme už template pro tento proces, nebo vytváříme nový?"

## Output format

Draft markdown **vždy** v code blocku s jazykem `markdown`. Ne jako inline text.

## Po save vždy

1. `python scripts/validate.py --sop <new-id>`
2. Pokud errors → oprav → znova validuj
3. Ukaž `git status` / `git diff` pro viditelnost
4. Nabídni commit message
