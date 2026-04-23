---
name: sop-shared
description: Shared templates, schemas, and conventions for yeast-sops workflow. This skill is loaded as foundation by other sop-* skills. Do not invoke directly — use sop-create, sop-refine, sop-validate, sop-role, or sop-to-agent instead.
---

# sop-shared

Základní znalost pro celou `sop-*` rodinu skillů. Tento skill se **nespouští samostatně**,
slouží jako sdílený kontext.

## Repo, se kterým pracujeme

- Git: `git@github.com:Sothrax/yeast-sops.git`
- Default clone location: `~/code/yeast-sops`
- Claude Code obvykle pracuje přímo v tomto repu; Cowork má přístup přes lokální filesystem

## Konvence, které si musíš pamatovat

### ID formáty

| Typ | Formát | Příklad |
|---|---|---|
| SOP template | `SOP-<DOMAIN>-T<NNN>` | `SOP-ACC-T001` |
| SOP instance | `SOP-<DOMAIN>-I<NNN>` | `SOP-ACC-I001` |
| Role | `ROLE-<DOMAIN>-<NNN>` | `ROLE-ACC-003` |

Domény: `ACC` (accounting), `HR`, `LEG` (legal), `OPS`, `IT` (it-ops), `FIN` (finance).

### Tenant slugy

- `yeast-holding`, `pq-group`, `taf-estate`, `ave-medical`
- Pro klienty přidávat po domluvě s ownerem repa

### Jazyk

- Frontmatter klíče + enum hodnoty: **angličtina**
- Body SOPky: **čeština**
- Strojově čitelné (success_criteria, permission strings, tool names): **angličtina**

### Placeholders v template

`{{ parameter_name }}` — snake_case, musí být deklarováno v `tenant.parameterized`.

## Adresářová struktura repa

```
yeast-sops/
├── templates/<domain>/SOP-*-T*.md     (master verze, parameterized)
├── instances/<tenant>/<domain>/       (per-tenant instance, vygenerované)
├── roles/<domain>/                    (role bundle = SOPs + perms)
├── schemas/*.json                     (JSON Schema, single source of truth)
├── scripts/                           (validate, instantiate, to_agent, stale_check)
└── .github/workflows/                 (CI validace, weekly stale check)
```

## Hlavní tooly v repu (vždy volej z root repa)

```bash
python scripts/validate.py [--sop ID | --role ID] [--strict] [--stale]
python scripts/instantiate.py --template <T-ID> --tenant <slug> --instance-id <I-ID> --params <params.yaml>
python scripts/to_agent.py --sop <ID> [-o <path>]
```

## Automation levels — kdy co

| Level | Význam |
|---|---|
| `manual` | Jen lidi, AI max. sumarizace |
| `assisted` | Člověk řídí, AI těžká práce |
| `supervised` | AI řídí, člověk schvaluje v HITL bránách |
| `autonomous` | AI end-to-end |

**Start low.** První verze nové SOPky je typicky `assisted`. Promote až po measure & validate.

## Commit message konvence

- `Add SOP-ACC-T005: invoice matching`
- `Update SOP-ACC-T001: bump to 0.2.0`
- `Instantiate SOP-ACC-T001 → SOP-ACC-I003 for pq-group`
- `Add role ROLE-ACC-002: accountant-senior`

## Pravidla chování pro všechny sop-* skilly

1. **Read before write.** Vždy nejdřív projdi existující SOPky ve stejné doméně — ať
   neduplikuješ ID, jazyk, style.
2. **Validuj před commitem.** Každá změna → `python scripts/validate.py` na dotčený soubor.
3. **Neměň schema** bez explicitního povolení ownera repa.
4. **Změny v template = bump version.** Patch (0.1.0 → 0.1.1) pro typo, minor
   (0.1.0 → 0.2.0) pro novou logiku, major (1.0.0 → 2.0.0) pro breaking change interface.
5. **Changelog sekce v body** dostane nový řádek při každé netriviální změně.
6. **Pokud je něco nejasné — ptej se.** Nehaluzit. Raději 3 otázky navíc než vymyšlený step.
