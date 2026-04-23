---
name: sop-refine
description: Iterate on an existing SOP in the yeast-sops repo. Use when user wants to edit, improve, update, or refine a Standard Operating Procedure. Use when user mentions a specific SOP ID and asks to change something, or says "upravit SOPku", "refine SOP", "vylepšit proces", "/sop:refine".
---

# sop-refine

Upravuje existující SOPku. Primární use case: doplnit detaily po initial `/sop:create`,
opravit chyby, promote status, zachytit změnu v reálném procesu.

Nejdřív načti `sop-shared` SKILL.md pro konvence.

## Workflow

### 1. Identify target

Z uživatelova zadání extrahuj SOP ID. Pokud není jasné:

> "Kterou SOPku upravujeme? Řekni ID (např. `SOP-ACC-T001`) nebo krátce popiš, najdu ji."

### 2. Read full context

**Vždy načti celý soubor**, včetně frontmatteru a body. Ne jen relevantní sekci.
Bez kontextu uděláš změnu, která rozbije logiku jinde.

### 3. Diagnose scope

Podle typu požadavku vyber strategii:

| Typ změny | Strategie | Version bump |
|---|---|---|
| Typo, formátování | Direct edit, show diff | patch (0.1.0 → 0.1.1) |
| Přidání kroku, úprava logiky | Proposal s diffem, čekat na approval | minor (0.1.0 → 0.2.0) |
| Změna trigger, tools, schema breaking | Proposal + diskuse s ownerem | major (1.0.0 → 2.0.0) |
| Status promotion (draft → active) | Verify checklist před bump | minor + status change |
| Routine review (zaktualizovat `last_reviewed`) | Direct edit | žádný bump |

### 4. Propose change as diff

**Vždy** ukaž uživateli změnu jako unified diff, ne jako celý nový soubor.

```diff
-version: 0.1.0
+version: 0.2.0
...
 ### 5. Human approval gate – unmatched nad threshold
+
+**Timeout changed from 4 to 2 hours** — proces nesmí viset přes noc.
```

### 5. Wait for approval before writing

> "Tohle je návrh změny. Commit?"

Pokud yes → zapiš, bump version, update changelog, validuj.

### 6. Update changelog

Každá netriviální změna **musí** přidat řádek do `## Changelog` v body:

```
- 2026-04-23 — v0.2.0 — zkrácen timeout HITL gate ze 4 na 2 hodiny (petr@yeast-group.cz)
```

### 7. Validate

```bash
python scripts/validate.py --sop <ID>
```

Pokud errors → oprav a znova.

## Pravidla pro promote do `active`

Když uživatel chce `status: draft → active`, **vždy** projdi checklist před změnou:

- [ ] Všechny kroky mají konkrétní popis (žádné "nějak se zpracuje")
- [ ] Všechny HITL gates mají podmínku + akci + timeout
- [ ] Success criteria jsou strojově kontrolovatelná
- [ ] Exception handling tabulka je vyplněná
- [ ] Minimálně jedna instance už byla naplánovaná nebo existuje
- [ ] Owner / business_owner vyplněni
- [ ] Žádné TODO sekce neukazují na kritické díry

Pokud něco chybí → **odmítni promote**, report co chybí, nabídni že to doplníš.

## Edge cases

- **Uživatel chce změnit ID** → NE. ID je kanonický identifikátor. Pokud je opravdu špatné,
  udělej nový ID, změň status starého na `deprecated`, v body reference na nový.
- **Uživatel chce změnit frontmatter podle schematu, který už není platný** → validator
  to zachytí, ale upozorni na to hned.
- **Breaking change pro existující instance** → varuj:
  > "Tahle změna mění parameter list templatu. Existující instance budou rozbité.
  > Chceš: (a) přegenerovat všechny instance, (b) manuální migrace, (c) zastavit?"

## Output format

- Diffy: `diff` syntax code block
- Rationale pro změnu: krátký odstavec nad diffem
- Po save: výstup z validatoru + navržený commit message
