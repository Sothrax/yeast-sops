# yeast-sops

Standard Operating Procedures pro YEAST Group a klientské projekty.

## Co je to

Strojově i lidsky čitelné SOPky, které slouží jako **single source of truth** pro:

1. **Lidské čtení** — jak se ten proces dělá, proč existuje, kdo je zodpovědný
2. **Agent deployment** — Cortex a Claude Code / Cowork z toho generují agenty a konfigurace
3. **Audit a compliance** — kdo to schválil, kdy naposledy bylo reviewováno, co je deprecated

## Struktura

```
templates/    Tenant-agnostic master verze SOPek (parameterized).
              Vytváří se nové procesy. Mění se tady.

instances/    Konkrétní nasazení pro konkrétní tenant.
              Vygenerované z template přes scripts/instantiate.py.

roles/        Bundle SOPek + permissions, ze kterého se deployuje
              agent nebo se konfiguruje Claude Code / Cowork role.

schemas/      JSON schemas. Jediný zdroj pravdy pro strukturu.
              Měníš schema → CI validuje všechny SOPky znova.

scripts/      Python tooling: validate, instantiate, to_agent, stale_check.
```

## Workflow

### 1. Vytvořit novou template SOPku

Primárně přes Claude skill `/sop:create`. Manuálně:

```bash
cp templates/_template.md templates/accounting/SOP-ACC-T002-nazev-procesu.md
# edituj, vyplň frontmatter a body
python scripts/validate.py --sop SOP-ACC-T002
```

### 2. Instancovat template pro tenant

```bash
# params.yaml obsahuje hodnoty pro parameterized placeholders
cat > /tmp/params.yaml <<EOF
bank_account_iban: "CZ65 0300 0000 0001 2345 6789"
company_flexibee_code: "TAF_ESTATE_SRO"
notification_channel: "slack:#taf-accounting"
unmatched_threshold_czk: 10000
EOF

python scripts/instantiate.py \
    --template SOP-ACC-T001 \
    --tenant taf-estate \
    --instance-id SOP-ACC-I001 \
    --params /tmp/params.yaml
```

### 3. Vygenerovat Cortex agent skeleton

```bash
python scripts/to_agent.py --sop SOP-ACC-I001 \
    -o ../cortex-agents/agents/bank-rec-taf.yaml
```

### 4. Validovat před PR

```bash
python scripts/validate.py            # vše
python scripts/validate.py --strict   # fail na warning
python scripts/validate.py --stale    # najdi expired next_review
```

## Konvence

### ID formát

- **SOP**: `SOP-<DOMAIN>-<T|I><NNN>` — `T` = template, `I` = instance
- **Role**: `ROLE-<DOMAIN>-<NNN>`
- **Domény**: `ACC` (accounting), `HR`, `LEG` (legal), `OPS`, `IT` (it-ops), `FIN` (finance)

### Tenants

Slug konvence (kebab-case):

- `yeast-holding` — YEAST Holding s.r.o.
- `pq-group` — PQ GROUP s.r.o.
- `taf-estate` — TAF ESTATE
- `ave-medical` — AVE Medical Group

### Jazyk

- **YAML frontmatter keys + enum values**: angličtina
- **Body SOPky (nadpisy, popis, kontext, kroky)**: čeština
- **Success criteria, HITL gate names, permission strings**: angličtina (strojově čitelné)
- **Machine-readable references, URL, tool names**: angličtina

### Placeholders v template

`{{ parameter_name }}` — musí být deklarováno ve frontmatteru pod `tenant.parameterized`.

## Automation level — kdy je co vhodné

| Level | Co to znamená | Kdy použít |
|---|---|---|
| `manual` | Lidský proces, AI pomáhá max. sumarizací | Právní rozhodnutí, personální |
| `assisted` | Člověk řídí, AI dělá těžkou práci | Draft smluv, analýza dat |
| `supervised` | AI řídí, člověk schvaluje v HITL branách | Bank rec, invoice processing |
| `autonomous` | AI end-to-end bez člověka | Notifikace, reporty, low-risk data pulls |

**Pravidlo:** začni o jeden level níž, než si myslíš, že bys potřeboval. Promotovat
SOPku nahoru (assisted → supervised → autonomous) se děje po measure & validate cyklech,
ne prvotním vibe-check.

## Review cadence

Každá SOPka má `next_review` datum. CI workflow `stale-report.yml` generuje GitHub
issue s expired SOPkami. Výchozí interval: **6 měsíců** od posledního review.

Při reviewu se:
1. Projdou kroky a ověří, že odpovídají realitě
2. Zkontrolují reference (URL live, MCP tools existují)
3. Updatuje `last_reviewed`, `reviewed_by`, `next_review`
4. Bump `version` pokud se obsah změnil

## CI

- **Na každý PR**: `scripts/validate.py --strict` (schema + cross-refs)
- **Týdně** (neděle): `scripts/validate.py --stale` → vytvoří/updatuje issue s expired SOPkami

## Licence

Internal – YEAST Group. Klientské instance jsou duševní vlastnictví klienta.
