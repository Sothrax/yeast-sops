---
name: sop-role
description: Create or update role definitions that bundle SOPs together with permissions and deployment targets. Use when the user wants to define a role (e.g. "accountant junior", "document processor"), bundle SOPs for an agent, or set up a Cortex agent role configuration. Trigger on "/sop:role", "create role", "nová role", "definuj roli".
---

# sop-role

Vytváří nebo upravuje role definition (`roles/<domain>/<name>.yaml`). Role =
bundle SOPek + permissions + deployment target. Ze zkompilované role se deployují
agenti v Cortex, Claude Code nebo Cowork konfiguraci.

Načti `sop-shared` SKILL.md pro konvence.

## Workflow

### 1. Intake

> "OK, nová role. Řekni mi jménem — co tahle role dělá v jedné větě?
> Např. 'Junior účetní, který denně stahuje banky a importuje faktury'."

Z odpovědi odvoď:
- **Doménu** (accounting / hr / legal / it-ops / finance / operations)
- **Seniority** (junior / senior / lead / manager)
- **Pravděpodobné SOPky** — najdi v `templates/<domain>/` kandidáty

### 2. Generate next ID

Scanni `roles/<domain>/` pro nejvyšší `ROLE-<DOMAIN>-<NNN>`, použij `+1`.

### 3. SOP selection interview

Nabídni seznam SOPek ve stejné doméně:

> "Tady je co máme v `<domain>`:
>
> - `SOP-ACC-T001` — Bank Reconciliation ČSOB
> - `SOP-ACC-T002` — Invoice Incoming
> - `SOP-ACC-T005` — Monthly Closing
>
> Kterou z nich tahle role dělá? Můžeš říct `všechny`, `1,2`, nebo `první dvě`."

Pro každou vybranou SOPku se zeptej:

> "`SOP-ACC-T001` — frequency? (daily/weekly/monthly/quarterly/ad-hoc) Required, nebo optional?"

### 4. Permissions inference

Automaticky posbírej `required_permissions` ze všech vybraných SOPek (union).
Ukaž uživateli:

> "Z SOPek vyplývají tyhle permissions:
> - `read:bank_statements`
> - `write:flexibee_transactions`
> - `notify:slack`
>
> Chceš přidat ještě něco nad rámec (např. `execute:override_hitl_gates` pro senior role)?"

### 5. Tenant scope

> "Pro které tenanty tahle role funguje? Default `all`. Nebo jmenovitě: yeast-holding,
> pq-group, taf-estate, ave-medical."

### 6. Deployment target

> "Kde tahle role poběží? Možnosti:
> - `claude-code` — interaktivní Claude Code session (dev, ad-hoc tasks)
> - `cowork` — Cowork desktop app (knowledge work, dispatch od uživatele)
> - `cortex-agent` — produkční agent v Cortex orchestraci
> - `manual` — zatím jen dokumentace, žádný deployment"

### 7. Escalation path

> "Kam eskalovat při chybě / nutnosti schválení?
> Default: `petr@yeast-group.cz` + `slack:#<domain>-alerts`."

### 8. Generate draft

Použij `roles/_template.yaml` jako kostru, vyplň všemi odpověďmi.

**Vždy:**
- `version: 0.1.0`
- `claude_constitution_ref: "constitutions/<role-slug>.md"` (i když soubor ještě neexistuje —
  uživatel ho dopíše později, reference je placeholder)

### 9. Review & save

Ukaž celou role YAML. Zeptej se na commit.

Po save:

```bash
python scripts/validate.py --role <ROLE-ID>
```

Pokud errors → oprav.

## Pravidla

- **Role nedefinuje procesy, jen je konzumuje.** Pokud user popisuje co se v procesu dělá,
  tohle je sop-create use case, ne sop-role. Přesměruj.
- **Role neobsahuje SOPky, které neexistují.** Pokud user chce SOPku, která není v repu,
  buď ji napřed vytvořte přes `/sop:create`, nebo ji dej do `sops: []` jako TODO
  (s varováním, že role nebude funkční bez ní).
- **Permission union musí sedět.** Pokud role obsahuje jen SOPky, které potřebují
  `read:` permissions, ale v roli je `write:` — flag to jako warning:
  > "⚠️ `write:flexibee_transactions` není potřeba pro žádnou ze zvolených SOPek.
  > Je to záměr, nebo overkill?"

## Edge cases

- **Role bez jediného `required: true` SOP** → warning, role bez povinných SOPek
  obvykle nedává smysl.
- **Cross-domain role** (např. ops role která spouští accounting SOPky) → OK, ale
  zpochybni to: "Tohle je ops role s accounting SOPkou — záměr? Nebo má být v accounting?"
- **Cortex-agent deployment + automation_level v SOPce = `manual`** → contradiction,
  upozorni.

## Output format

Role YAML v code bloku, pak komentář co bylo odvozeno a co user výslovně zvolil.
