# CONTRIBUTING

## Jak se tvoří nová SOPka

### Přes Claude skill (preferováno)

V Claude Code nebo Cowork spusť:

```
/sop:create
```

Claude tě provede interview:

1. Jednou větou popiš proces
2. Odpověz na otázky o trigger, inputs, steps, HITL gates
3. Projdi draft, commitni

### Manuálně

1. Zkopíruj `templates/_template.md` do správné domény
2. Pojmenuj podle konvence `SOP-<DOMAIN>-T<NNN>-<kebab-name>.md`
3. Vyplň frontmatter (viz `schemas/sop.schema.json` pro povinné položky)
4. Vyplň body podle struktury z template
5. Zvaliduj: `python scripts/validate.py --sop SOP-XXX-TNNN`

## Pravidla pro frontmatter

- **ID musí být unique** napříč celým repem (templates + instances)
- **Version** začíná na `0.1.0`, bumpe se podle semver když se obsah mění
- **Status**:
  - `draft` — rozpracováno, nesmí se z něj generovat produkční agent
  - `active` — v provozu
  - `deprecated` — má náhradu, nová instancování blokovaná
  - `archived` — historické, read-only

- **next_review** — default +6 měsíců od `last_reviewed`. Kratší (3 měsíce) pro
  kritické procesy (bank ops, audit-sensitive).

## Pravidla pro body SOPky

- **Cíl** — max. 2 věty, co proces dělá
- **Kontext** — 1 odstavec, proč existuje
- **Steps** — očíslované, každý krok má popis + on failure
- **HITL gates** — explicitní, s podmínkou, akcí, a timeoutem
- **Exception handling** — tabulka `Situace | Akce | Kdo řeší`

Pokud něco zůstane vágní ("pak se to nějak zpracuje"), **není to SOP**. Rozepiš to.

## Pull request workflow

1. Branch: `sop/<ID>-<krátký-popis>` nebo `role/<ID>-<krátký-popis>`
2. Commit message: `Add SOP-ACC-T005: invoice matching` (nebo `Update SOP-ACC-T001: bump to 0.2.0`)
3. CI musí projít (`validate.py --strict`)
4. PR review: minimálně 1 reviewer z dev-owners nebo business-owner
5. Merge → main → automaticky trigger pro downstream konzumenty (Cortex compiler)

## Changelog discipline

Každý SOP má sekci `## Changelog` v body. Při každé změně přidej řádek:

```
- 2026-04-23 — v0.2.0 — přidán step 5 (validace counterparty), zkrácen timeout (petr@yeast-group.cz)
```

Důvod: strojově čitelný changelog je v Gitu. Lidsky čitelný je v SOPce, aby stakeholder
nemusel umět `git log`.

## Co do repa NEpatří

- **Secrets** (credentials, API keys) — nikdy. Jsou v Vault / sops-age.
- **Osobní data** konkrétních zaměstnanců / klientů (jména, čísla účtů) — pokud to není
  tenant-specific instance, kde to má být explicitně.
- **Draft procesů, které ještě neexistují v realitě** — SOPka popisuje stávající
  praxi. Future-state plány jsou v jiném repu / projektu.
