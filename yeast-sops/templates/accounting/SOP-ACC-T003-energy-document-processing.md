---
id: SOP-ACC-T003
name: "Energie – zpracování energetických dokladů (zálohy, vyúčtování, zápočty)"
version: 0.1.0
status: draft
owner: petr@yeast-group.cz
business_owner: petr.kvasnica@yeast-group.cz
domain: accounting
tenant:
  type: template
  parameterized:
    - energy_vendor_ico_whitelist
    - om_to_stredisko_map
    - account_map
last_reviewed: 2026-06-03
reviewed_by: petr@yeast-group.cz
next_review: 2026-12-03
agent_suitable: true
automation_level: supervised
required_tools:
  - mcp:flexibee
  - mcp:ares-gateway
  - internal:doc-ocr
  - internal:litellm-extract
  - external:cnb-fx
required_connectors:
  - flexibee
  - ares
  - doc_ocr
  - litellm
required_permissions:
  - read:document_invoices
  - write:document_invoices
  - read:tenant_subjects
  - read:flexibee_cleneni_dph
  - write:flexibee_faktura_prijata
  - execute:ares_ico_lookup
  - execute:cnb_rate_lookup
trigger: event
estimated_duration_min: 3
criticality: high
human_approval_required:
  - predpis_zaloh
  - uvitaci_dopis
  - vyuctovani
  - vyuctovani_konecne
  - zalohovy_danovy_doklad
  - zapocet
  - overpayment_detected
  - vat_does_not_reconcile
  - om_unmatched
success_criteria:
  - energy_subtype_classified
  - no_advance_schedule_booked_as_invoice
  - no_overpayment_booked_as_positive_payable
  - vat_reconciles_or_held
  - subject_matched_by_8digit_ico
tags:
  - energie
  - dph
  - taf-estate
related_sops:
  - SOP-ACC-T002
  - SOP-ACC-T001
references:
  - label: "Zákon o DPH §92e (přenesení DPH – stavební práce)"
    url: "https://www.zakonyprolidi.cz/cs/2004-235"
  - label: "Sandbox analýza (workflow taf-energy-sop)"
    url: "internal:cortex-infra/memory/invoice-energy-sop.md"
---

# Energie – zpracování energetických dokladů

## Cíl (Goal)

Rozpoznat energetický doklad (elektřina/plyn/teplo) v invoice pipeline, klasifikovat jeho
sub-typ v rámci životního cyklu (zálohy → vyúčtování → zápočet) a každý zpracovat správným
účetním postupem — zejména **nepřipustit** chybné zaúčtování, které u energií hrozí víc než
u běžné faktury.

## Kontext / Proč

Energetické doklady tvoří **řetězec na jedno odběrné místo (OM)**, ne izolované faktury, a
standardní model „1 faktura → 1 přijatý doklad" na ně nesedí. Sandbox analýza 11 reálných
dokladů TAF Estate (2026-06-03) odhalila **3 kritická rizika**, kvůli kterým musí mít energie
vlastní flow:

1. **Fiktivní závazky** — „předpis/plán záloh" a „uvítací dopis s rozpisem záloh" jsou
   *rozpisy* (ne daňové doklady, bez DPH a DUZP). Naivní zaúčtování `total` jako faktury
   vytvoří neexistující dluh (12 000 / 2 500 / 3 000 Kč).
2. **Obrácený cashflow** — „konečné/mimořádné vyúčtování při ukončení smlouvy" obvykle končí
   **přeplatkem** (pohledávka/vratka). `total` je mezisoučet spotřeby, ne částka k úhradě.
   Zaúčtování jako kladný závazek = peníze, které ve skutečnosti dostáváme zpět (PRE: total
   3 640, výsledek +6 440 vratka; innogy plyn vratka 10 594).
3. **Dvojí DPH** — „vyúčtování" se zápočtem záloh: zálohy už měly odpočet (zálohové daňové
   doklady), vyúčtování ukazuje DPH z celé spotřeby → dvojí odpočet (EPE Milíčova: total 880,
   ale DPH 534 z plné spotřeby 3 080).

Navíc: jeden vlastník (s.r.o.) má **více odběrných míst** (Dům Vršovická 44 = byt 32 + byt 34,
různé zákaznické účty), takže párování jen na subjekt (IČ) nestačí — je potřeba úroveň OM.

## Inputs

- **Vytěžený doklad** (`document_invoices` řádek) — z SOP-ACC-T002 (intake + extrakce): dodavatel,
  IČ/DIČ, odběratel, total, datum, DPH pásma, OCR obsah.
- **OCR text dokladu** — pro deterministickou detekci sub-typu (klíčová slova).
- **`energy_vendor_ico_whitelist`** *(tenant param)* — IČ energetických dodavatelů (PPAS 60193492,
  PRE 60193913, innogy 49903209, EP ENERGY 27386643, ČEZ Prodej 27232433, E.ON 26078201, …).
- **`om_to_stredisko_map`** *(tenant param)* — mapování odběrné místo (EAN / smluvní účet) → nemovitost / středisko.
- **`account_map`** *(tenant param)* — účtová osnova (502/504 spotřeba, 314 poskytnuté zálohy per OM, 343 DPH, 321 závazek, 311/315 pohledávka).

## Preconditions

- [ ] Doklad prošel intake + extrakcí (SOP-ACC-T002), existuje `document_invoices` řádek.
- [ ] Odběratel je napárovaný na `tenant_subject` přes **8místné IČ** (ne zákaznický účet dodavatele!).
- [ ] FlexiBee firma odběratele má seedované `cleneni-dph` kódy (pro budoucí samovyměření).

## Steps

### 1. Rozpoznání „energie" (router)

Doklad je energetický, pokud **vendor IČ ∈ `energy_vendor_ico_whitelist`** (nejspolehlivější,
odolné vůči OCR — „Gpet."→EP ENERGY, „PIRE"→PRE) **NEBO** OCR obsahuje silné klíčové slovo
(`odběrné místo`, `zúčtovací období`, `silová elektřina`, `zemní plyn`, `distribuce`, `EAN`).

```
is_energy = vendor_ico in ENERGY_VENDOR_ICO or any(kw in ocr.lower() for kw in ENERGY_KEYWORDS)
```

**On failure:** není-li energie → pokračuj standardním invoice flow (SOP-ACC-T002 navazující kroky).

### 2. Klasifikace sub-typu

`doc_subtype` z LLM extrakce, ale s **deterministickým override** (LLM nespolehlivě odliší
vyúčtování od faktury — obojí je „daňový doklad"). Klíčové pravidlo: **slovo „záloha" samo
o sobě nerozhoduje** — rozhoduje přítomnost základu daně + DPH + DUZP.

| Sub-typ | Signály (override z OCR) | Daňový doklad? |
|---|---|---|
| `predpis_zaloh` | „PŘEDPIS/PLÁN/ROZPIS ZÁLOH", tabulka období, bez DPH a DUZP | NE |
| `uvitaci_dopis` | „POTVRZENÍ ZAHÁJENÍ DODÁVKY", uvítací dopis | NE |
| `vyuctovani` | „zúčtovací období", „zúčtované/vyúčtované zálohy", „rozdíl ke zdanění" | ANO |
| `vyuctovani_konecne` | „UKONČENÍ smlouvy", „KONEČNÁ/MIMOŘÁDNÁ", „přeplatek", „B-poukázka" | ANO (přeplatek!) |
| `zalohovy_danovy_doklad` (`danovy_doklad_zaloha`) | „daňový doklad k přijaté úplatě", „Neplaťte", datum přijetí úplaty, MÁ DPH | ANO |
| `zapocet` (`vzajemny_zapocet`) | „OZNÁMENÍ O ZÁPOČTU", rozpis ≥2 původních dokladů | NE (sám o sobě) |
| `faktura` | běžná energetická faktura s DPH, bez zápočtu záloh / přeplatku | ANO |

**On failure / nejistota:** → `vyuctovani` (drženo) — radši false-positive review než chybné auto.

### 3. Odběrné místo (OM) → nemovitost / středisko

- Subjekt (s.r.o.) **výhradně přes 8místné IČ**. Zákaznický/smluvní účet (10 číslic) **NENÍ IČ** → odmítnout.
- OM přes **EAN** (primární) → fallback smluvní/zákaznický účet → fallback adresa+jednotka, mapuj přes `om_to_stredisko_map`.
- Zálohový účet 314 je veden **per OM** (ne per s.r.o.), aby zápočet ve vyúčtování sedl.

### 4. Handling per sub-typ

**P0 (implementováno, c2f6b4c/a41f4a8): všechny lifecycle typy → HOLD (needs_mapping / review) s jasným důvodem. Jen prostá `faktura` se zaúčtuje (přes existující guardraily B3 DPH-sum + confidence). Plné zpracování níže = P1/P2.**

- **`predpis_zaloh` / `uvitaci_dopis`** → 0 účetních dokladů. Extrahovat celou tabulku plánu
  (N řádků: částka + splatnost), založit `plan_zaloh(om_id, radky[])`. `total` NIKDY jako závazek.
- **`zalohovy_danovy_doklad`** → 1 doklad, rozdělit total na základ+DPH, odpočet DPH MD 343 / D 314,
  DUZP = datum přijetí úplaty, do KH. `due_date=null` + „Neplaťte" → negenerovat příkaz.
- **`vyuctovani`** → 1 doklad. Sečíst **celou daňovou rekapitulaci** (komodita + distribuce + stálý plat),
  ne jeden dílčí řádek. Je-li „zúčtované zálohy" ≠ 0 → zápočet záloh (314) + **anti-dvojí-odpočet**
  (doodpočítat jen rozdíl DPH spotřeba − DPH už uplatněná na zálohách).
- **`vyuctovani_konecne`** → směr = **pohledávka** (přeplatek 311/315), ne závazek. NEbrat `total` verbatim.
  Uzavřít zálohový účet OM. Znaménka DPH mohou být záporná.
- **`zapocet`** → 0 nákladových dokladů; 1 zápočtový zápis MD 321 / D 311(315), linkovat na původní doklady.

### 5. Human approval gate

Pokud `doc_subtype` ∈ {predpis_zaloh, uvitaci_dopis, vyuctovani, vyuctovani_konecne,
zalohovy_danovy_doklad, zapocet} **nebo** detekován přeplatek **nebo** DPH nesedí na total
**nebo** OM/subjekt nenapárován:

- Doklad → `_NeedsReview` (drženo, **nezaúčtovat automaticky**), `review_reason` vyplněn.
- Notifikace do Matrix `#cortex-ops` (digest) jako 🟠 s důvodem.
- Účetní dokončí ve FlexiBee, nebo schválí přes `review_action` (až bude P1/P2 handling).

## Exception Handling

| Situace | Akce | Kdo |
|---|---|---|
| Energie, ale nejednoznačný sub-typ | → `vyuctovani` (hold) | Agent → Human |
| Přeplatek / konečné vyúčtování | hold, nikdy kladný závazek | Human |
| DPH pásma nesedí na total | hold (B3 guard) | Human |
| Subjekt jen přes zákaznický účet (10 číslic) | odmítnout match → unmatched | Human |
| OM nenalezeno (chybí EAN i účet) | hold + dotáhnout mapování | Human |

## Output

- **P0:** `document_invoices.flexibee_status = needs_mapping` + `review_reason`; doklad v `_NeedsReview`; digest do `#cortex-ops`.
- **P1/P2 (cíl):** zaúčtovaný doklad (FlexiBee faktura-prijata) se správným režimem DPH / zápočtem záloh / evidencí OM + plánu záloh; přeplatky jako pohledávky.

## Validation (Success criteria detail)

- `energy_subtype_classified` — každý energetický doklad má přiřazený jeden ze sub-typů.
- `no_advance_schedule_booked_as_invoice` — `predpis_zaloh`/`uvitaci_dopis` se NIKDY nezaúčtuje jako faktura.
- `no_overpayment_booked_as_positive_payable` — `vyuctovani_konecne` s přeplatkem se nezaúčtuje jako kladný závazek.
- `vat_reconciles_or_held` — buď Σ(DPH pásma) == total (±1 Kč), nebo doklad držen.
- `subject_matched_by_8digit_ico` — odběratel napárován jen přes platné 8místné IČ.

## TODO — rozhodnutí účetní / Petr (blokují P1/P2)

- [ ] **Účtová osnova energií** — 502 vs 504 (plyn/elektřina), 314 per OM, 343, 321, 311 vs 315 pro přeplatky.
- [ ] **Odpočet DPH ze záloh** — průběžně ze zálohových daňových dokladů, nebo až ve vyúčtování? (řídí anti-dvojí-odpočet logiku)
- [ ] **Plán záloh** — vede ho FlexiBee (otevřené předpisy), nebo jen evidenčně + zálohy z bankovního výpisu?
- [ ] **Přeplatky / B-poukázky** — účtovat jako pohledávku a čekat na vratku? jak párovat B-poukázku?
- [ ] **Středisková alokace** — náklad per OM/jednotka, nebo stačí per s.r.o.?
- [ ] **Energetická daň** (daň z plynu/elektřiny) — samostatný účet, nebo součást nákladu?

## Role mapping

- `ROLE-ACC-001` (Accountant Junior) — review držených energetických dokladů
- `ROLE-ACC-002` (Accountant Senior) — finalizace vyúčtování, zápočtů, přeplatků

## Changelog

- 2026-06-03 — v0.1.0 — initial draft z sandbox analýzy TAF Estate (P0 safety implementováno, P1/P2 + účetní rozhodnutí TODO) (petr@yeast-group.cz)
