# CLAUDE.md — yeast-sops repository

Tento soubor definuje chování Claude Code / Cowork při práci v tomto repu.

## Účel repa

Single source of truth pro Standard Operating Procedures (SOP) YEAST Group.
Konzumenty jsou: lidi (účetní, právníci, ops), Cortex agent compiler, Claude skills
pro `/sop:*` workflow.

## Claude pravidla při práci v tomto repu

### Vždy

- **Validuj před commitem.** Když upravíš SOPku nebo roli, spusť `python scripts/validate.py`
  na daný soubor a ověř že je čistý.
- **Zachovávej strukturu template.** Neodstraňuj sekce z SOPky. Pokud sekce nemá obsah,
  napiš `_Nerelevantní pro tento proces._` místo vymazání.
- **Bump version** pokud měníš obsah. `0.1.0` → `0.2.0` pro nové kroky nebo změnu logiky,
  `0.1.1` pro opravy typo / formátování.
- **Update changelog** v body SOPky při každé netriviální změně.
- **Update `last_reviewed` a `reviewed_by`** pokud jsi proces skutečně projel s ownerem.
  Neměň tato pole sám od sebe jen proto, že jsi upravil formulaci.

### Nikdy

- **Nevkládej secrets** (credentials, API keys, osobní údaje) do SOPek.
- **Needituj schema** (`schemas/*.json`) bez explicitního požadavku a diskuse o dopadu
  na existující SOPky.
- **Negeneruj instance SOPky ručním copy-paste.** Používej `scripts/instantiate.py`.
- **Nepromoť SOPku ze `status: draft` do `active`** bez explicitního pokynu od ownera.
- **Neměň ID** existující SOPky — ID je kanonický identifikátor, měnit ho znamená
  všude v downstream konzumentech rozbít reference.

## Jazyk

- Keys ve frontmatteru: angličtina
- Values enum (`trigger: scheduled`, `status: active`): angličtina
- Body SOPky (nadpisy, popis, kroky): čeština
- Success criteria, HITL gate názvy, permission strings: angličtina (strojově čitelné)
- Komentáře v YAML: podle toho, co dává kontextu smysl

## Pravidla pro interview flow (když Claude vede `/sop:create`)

1. **Jedna otázka per turn.** Ne 5 najednou.
2. **Navrhni default.** Místo "Jaký je trigger?" řekni "Předpokládám `manual`, souhlas?
   Nebo to běží na rozvrh / event?"
3. **Přijmi odmítnutí.** Když uživatel řekne "později", polož si to do "TODO" sekce
   v draft SOPce a pokračuj dál.
4. **Když je něco vágní, dotazuj se.** "Pošli do Slacku" → "Do kterého kanálu?
   Formát `slack:#channel-name`."
5. **Na konci shrni** to, co jsi pochopil, a nabídni save nebo revize.

## Pravidla pro refine flow (když Claude upravuje existující SOPku)

1. **Nejdřív přečti celou SOPku včetně kontextu.** Neskákej rovnou do editace.
2. **Navrhni změnu jako diff.** Ne jako nový soubor. Uživatel má vidět přesně co se mění.
3. **Pokud změna vyžaduje bump version, řekni to explicitně.**
4. **Pokud refine odhalí nejasnost v kontextu**, nehaluzit — zeptej se ownera.

## Jak Claude interaguje s dalšími tooly v tomto repu

- **validate.py** — spouští se přes bash, výstup se parsuje pro errors
- **instantiate.py** — Claude ho volá, když uživatel chce vytvořit instanci
- **to_agent.py** — Claude ho volá pro export do Cortex, ale výsledek ukáže uživateli
  před commitem (může vyžadovat manuální úpravy)

## Tone of voice

Stručně, technicky, přímo. Pokud owner repa řekne, že chce odlišný styl pro konkrétní
SOPku (např. klientský onboarding dokument, kde je potřeba formálnější tón), respektuj
to v body, ale frontmatter + strukturu drž stejně.
