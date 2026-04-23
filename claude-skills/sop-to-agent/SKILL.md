---
name: sop-to-agent
description: Compile an SOP into a Cortex agent YAML skeleton for deployment. Use when the user wants to generate an agent from an SOP, deploy a process as an automated agent, or create Cortex configuration from a procedure. Trigger on "/sop:to-agent", "compile to agent", "vytvoř agenta", "nasaď jako agent".
---

# sop-to-agent

Zkompiluje SOPku (obvykle **instance**, ne template) do Cortex agent YAML skeletu.
Output je **startovací bod**, ne finální agent — vždy vyžaduje manuální review
před nasazením.

Načti `sop-shared` SKILL.md pro konvence a cesty.

## Preflight checks

Před spuštěním compilace ověř **5 věcí**:

### 1. SOP existuje a je validní

```bash
python scripts/validate.py --sop <ID>
```

Pokud errors → STOP, řekni uživateli:
> "SOPka má validation errors, nebudu ji kompilovat. Oprav je nejdřív přes `/sop:refine`."

### 2. SOP je agent-suitable

V frontmatteru musí být `agent_suitable: true`. Pokud ne:
> "Tahle SOPka má `agent_suitable: false` — je explicitně označená jako nevhodná pro automatizaci.
> Pokud chceš přesto kompilovat, změň to nejdřív (ale promysli proč tam to `false` bylo)."

### 3. Status není `draft`

Pokud `status: draft`:
> "SOPka je `draft`. Nemělo by se z ní kompilovat produkční agent.
> Možnosti: (a) projet promote-to-active checklist přes `/sop:refine`,
> (b) kompilovat s warning (jen pro dev/test), (c) stop."

### 4. Je to instance, ne template

Template = parameterized, nelze z něj přímo deployovat bez instance.

Pokud je to template:
> "Tohle je template, ne instance. Agent se deployuje z konkrétní tenant instance.
> Chceš napřed vytvořit instanci přes `python scripts/instantiate.py`?"

### 5. Automation level sanity

- `manual` → agent nedává smysl, STOP
- `assisted` → nedává smysl pro scheduled agent, jen pro dispatch use case, warn
- `supervised` → OK, s HITL gates
- `autonomous` → OK

## Compilation

```bash
python scripts/to_agent.py --sop <ID> -o <output-path>
```

Default output path:
```
../cortex-agents/agents/<tenant>/<agent-name>.yaml
```

Kde `<tenant>` je `tenant.scope` z SOPky a `<agent-name>` je derived z SOP ID.

Pokud uživatel nemá `cortex-agents` repo nabok (zkontroluj `ls ../cortex-agents`),
vypiš na stdout a nech uživatele rozhodnout kam to dát.

## Post-compilation review

Po kompilaci **vždy** projdi výstupní YAML a upozorni uživatele na sekce, které
potřebují manuální doplnění:

| Pole | Co zkontrolovat |
|---|---|
| `spec.trigger.source` | Pokud `event` typ, je nastaveno "TODO" — doplnit event source |
| `spec.system_prompt_ref` | Ukazuje na `sops://...` — Cortex compiler musí umět resolvovat |
| `spec.tools` | Jsou všechny tools reálně dostupné v Cortex runtime? |
| `spec.connectors` | Jsou credentials připravené v Vault / secrets store? |
| `spec.escalation` | Jsou uvedené emaily správné? Má Slack kanál bot access? |

Ukaž uživateli **TODO list** pro manuální kroky:

```
✅ Vygenerováno: cortex-agents/agents/taf-estate/bank-rec-csob.yaml

TODO před deploymentem:
1. [ ] Ověř, že `csob_api` connector má platné credentials ve Vaultu
2. [ ] Přidej event source pokud SOPka má trigger=event (aktuálně TODO)
3. [ ] Cortex compiler musí umět resolve `sops://instances/taf-estate/...`
4. [ ] V `#accounting-alerts` přizvi Cortex bot
5. [ ] Dry-run deployment → measure → promote
```

## Re-compilation

Pokud agent YAML už existuje a SOPka se změnila:

1. Zjisti stávající `metadata.version` v agent YAML
2. Porovnej s `version` v SOPce
3. Pokud SOP je novější:
   > "Source SOPka je v0.3.0, deployed agent je v0.2.1. Chceš:
   > (a) přegenerovat (overwrite s novým skeletem — ztratíš manuální úpravy agenta),
   > (b) generovat jen diff stub, kterým patchneš agent ručně,
   > (c) stop — zvládne se to přes refine existujícího agenta?"

## Edge cases

- **SOP nemá required_tools** → v Cortex agent YAML bude prázdné pole. To je legální
  pro agents které volají jen built-in (sumarizace), ale obvykle chyba. Warn.
- **SOP má human_approval_required, ale automation_level=autonomous** → contradiction,
  flagni to, autonomous nemá HITL gates z definice.
- **Output path už existuje** → neoverwrite bez potvrzení. Ukaž diff.

## Output format

```
[Preflight checks]
✅ Validation: clean
✅ agent_suitable: true
✅ status: active
✅ tenant.type: instance
✅ automation_level: supervised

[Compilation]
<output z to_agent.py>

[Manual review needed]
1. ...
2. ...
```

Nezaboč do vlastní interpretace — prvních 5 checků je buď pass/fail, output je
strojový, TODO list je konkrétní. Žádné vyprávění.
