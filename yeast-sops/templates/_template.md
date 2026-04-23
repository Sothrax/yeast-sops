---
id: SOP-XXX-TNNN
name: "<Name of the process>"
version: 0.1.0
status: draft
owner: petr@yeast-group.cz
business_owner: petr@yeast-group.cz
domain: accounting    # accounting | hr | legal | it-ops | finance | operations
tenant:
  type: template
  parameterized:
    - parameter_1
    - parameter_2
last_reviewed: 2026-04-23
reviewed_by: petr@yeast-group.cz
next_review: 2026-10-23
agent_suitable: true
automation_level: assisted    # manual | assisted | supervised | autonomous
required_tools:
  - mcp:flexibee
required_connectors:
  - example_connector
required_permissions:
  - read:example_resource
  - write:example_resource
trigger: manual    # manual | scheduled | event | webhook
# schedule: "0 8 * * *"    # uncomment if trigger=scheduled
estimated_duration_min: 5
criticality: medium    # low | medium | high | critical
human_approval_required:
  - condition_name_1
success_criteria:
  - machine_verifiable_condition_1
tags: []
related_sops: []
references:
  - label: "Example reference"
    url: "https://example.com"
---

# <Nadpis SOPky — srozumitelný název v češtině>

## Cíl (Goal)

Stručně (1–2 věty): co tento proces dělá a jaký výsledek přináší.

## Kontext / Proč

Proč tato SOPka existuje. Co se stane, když se proces neudělá. Historické souvislosti.
Tato sekce je pro lidi — pomáhá pochopit smysl, ne jen kroky.

## Inputs

Co proces potřebuje na vstupu:

- **Input 1** — popis, typ, odkud se bere
- **Input 2** — popis, typ, odkud se bere

## Preconditions

Podmínky, které musí být splněné před spuštěním:

- [ ] Podmínka 1
- [ ] Podmínka 2

## Steps

### 1. <Název kroku>

Popis co se v kroku dělá. Pokud je to agent-suitable, zde jsou **konkrétní volání toolů**.

```
# Příklad volání (pseudokód)
result = mcp.flexibee.list_evidence(evidence="faktura-prijata", filter=...)
```

**On failure:** co dělat při selhání (retry, skip, escalate).

### 2. <Další krok>

...

### N. Human approval gate (pokud je potřeba)

Pokud platí podmínka `<human_approval_required condition>`:

- Pošli do Slacku `<channel>` s detaily: `<co poslat>`
- **Nepokračovat** bez explicitní human confirmation
- Timeout: <doba> → eskalace na `<email>`

## Exception Handling

| Situace | Akce | Kdo to řeší |
|---|---|---|
| Příklad 1 | Retry 3× s backoff | Agent |
| Příklad 2 | STOP + notify | Human |

## Output

Co proces produkuje:

- Výstup 1 (kde, v jakém formátu)
- Výstup 2

## Validation (Success criteria detail)

Jak poznám, že je to OK:

- Kritérium 1 — jak se ověří
- Kritérium 2 — jak se ověří

## Role mapping

Tato SOPka je součástí následujících rolí:

- `ROLE-ACC-001` (Accountant Junior)
- `ROLE-ACC-002` (Accountant Senior)

## Changelog

- 2026-04-23 — v0.1.0 — initial draft (petr@yeast-group.cz)
