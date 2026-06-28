---
id: SOP-ITOPS-T001
name: "RB konektor – onboarding firmy/účtu do bank-feedu (OP cert → CMA → feed)"
version: 0.3.0
status: draft
owner: petr@yeast-group.cz
business_owner: petr.kvasnica@yeast-group.cz
domain: it-ops
tenant:
  type: template
  parameterized:
    - firma_slug
    - ico
    - rb_account_numbers
    - flexibee_company_db
    - flexibee_bank_kod
    - feed_group
last_reviewed: 2026-06-28
reviewed_by: petr@yeast-group.cz
next_review: 2026-12-28
agent_suitable: false        # cert activate vyžaduje lidskou OIDC identitu (rb:activate); key custody
automation_level: assisted
required_tools:
  - internal:1password        # op CLI / Connect — vault Cortex-RB-Keys
  - internal:openssl          # PEM -> .p12 (-legacy!)
  - internal:kubectl          # port-forward na mcp-rb CMA
  - mcp:rb                     # CMA plane (companies/certs/test-call)
  - mcp:flexibee              # bankovni-ucet kod lookup
  - internal:git              # bank_feed.py PR
required_connectors:
  - rb
  - flexibee
  - onepassword
required_permissions:
  - read:op:Cortex-RB-Keys
  - write:mcp_rb:companies
  - write:mcp_rb:certs
  - execute:rb:activate        # OIDC scope rb:activate — NE admin-key
  - read:flexibee:bankovni-ucet
  - write:cortex-infra:bank_feed
trigger: manual
estimated_duration_min: 30
criticality: high
human_approval_required:
  - cert_activate              # OIDC rb:activate, single strong approver (Petr v cortex-ui Console)
  - feed_go_live              # po čistém FEED_DRY=1 dry-runu
success_criteria:
  - company_exists_with_ico
  - exactly_one_active_cert_per_company
  - test_call_accounts_http_200
  - consumer_key_allowedcompanies_covers_slug
  - feed_dry_run_zero_errors
  - no_booking_into_wrong_flexibee_company
tags:
  - rb
  - bank-feed
  - connector
  - cma
  - mtls
  - money
related_sops:
  - SOP-ACC-T001
references:
  - label: "RB API bridge seam (scope/CMA model)"
    url: "internal:cortex-infra/docs/mcp/rb-api-bridge-seam.md"
  - label: "rb-connector-ops (deploy + OP naming + gotchas)"
    url: "internal:cortex-infra/memory/rb-connector-ops.md"
  - label: "bank-feed wiring + RB/FIO limity"
    url: "internal:cortex-infra/memory/rb-fio-bankfeed-rates.md"
  - label: "bank_feed.py (ACCOUNTS hardcoded list)"
    url: "internal:cortex-infra/services/cortex-platform/k3s/30-celery-worker/bank_feed.py"
---

# RB konektor – onboarding firmy/účtu do bank-feedu

## Cíl (Goal)

Napojit novou firmu (její RB účet/účty) do automatického RB→FlexiBee bank-feedu: nahrát klientský
certifikát do mcp-rb přes CMA, aktivovat, ověřit, a přidat účet do `bank_feed.py`, aby se transakce
denně párovaly/účtovaly do FlexiBee `banka`.

## Kontext / Proč

RB Premium API se autentizuje **per-firma mTLS klientským certifikátem**. mcp-rb drží cert
envelope-encrypted v Postgresu (`mcp_rb.certs`, klíč pod master KEK z 1Password); na volání ho
rozbalí v paměti a postaví mTLS pool. Bank-feed (`bank_feed.py`, CronJob `cortex-bank-feed`, à 15 min
7–19) iteruje **hardcoded** seznam `ACCOUNTS` a každý účet pullne přes mcp-rb → spáruje proti FlexiBee
`banka` (dedup `cisObj` = RB entryReference) → zaúčtuje genuine mezery. Bez tohoto onboardingu RB účet
nikdo nevolá a pohyby se neúčtují. **Nejhorší chyba = zaúčtování do špatné FlexiBee firmy** (dedup to
nechytí) — proto se firma + bank kod nesou explicitně a validují dry-runem.

## Inputs

- **OP cert item** — `_rb_client_<firma>` ve vaultu `Cortex-RB-Keys`, obsahuje `<firma>_client-cert.pem`
  + `<firma>_client-key.pem` (PEM cert + privátní klíč). *(parameter: firma_slug)*
- **IČ firmy** — cross-system join key; cert nese `organizationIdentifier` = `NTRCZ-<IČO>`. *(ico)*
- **FlexiBee firma DB** — slugovaný název, např. `taf_estate_projects_s_r_o_`. *(flexibee_company_db)*
- **RB čísla účtů** — zjistí se až PO aktivaci certu (z accounts listu). *(rb_account_numbers)*
- **FlexiBee `bankovni-ucet` kod** — per účet; musí přesně odpovídat (read+write target). *(flexibee_bank_kod)*
- **Feed group** — picks `RB_KEY_<GROUP>` (sdílený scoped rbk_ feed key). *(feed_group, např. taf-estate)*

## Preconditions

- [ ] Cert je v OP (`op item get _rb_client_<firma> --vault Cortex-RB-Keys` → 2 PEM soubory). **Nikdy netiskni hodnoty.**
- [ ] FlexiBee firma DB existuje (`flexi_list_companies` → ověř slug).
- [ ] V FlexiBee firmě existuje `bankovni-ucet` s kódem `RB_<účet>` pro daný RB účet. **BLOKER:** nová firma má
  jen default placeholder (`kod="BANKOVNÍ ÚČET"`, prázdný IBAN); správný záznam (`kod`=`nazev`=`RB_<účet>`, IBAN,
  `buc`=číslo, banka 5500) **musí ručně založit účetní ve FlexiBee** — přes MCP to NELZE (`bankovni-ucet` není
  flexi_upsert agenda). RB čísla účtů pro něj dodáš z kroku 6 (lze tedy předřadit: aktivuj cert → vytáhni účty →
  účetní založí bankovni-ucet → pak feed). Bez přesného kódu feed nepáruje (krok 7).
- [ ] Máš heslo pro nový `.p12` (zvolíš při exportu) a `op://Cortex-Platform/mcp-rb-cma-admin/password` (CMA admin-key).
- [ ] Pro aktivaci: lidská OIDC identita se scope `rb:activate` (přístup do cortex-ui Console).

## Steps

### 1. Stáhni PEM z OP a slož do .p12  *(Tier 1 / ops)*

> **Kde to dělat:** `op` vidí vaulty `Cortex-RB-Keys`/`Cortex-Platform` **jen na Macu** (service account na
> controlu je omezený a nevidí je) → celý cert+CMA flow běž **z Macu**, na CMA sáhni přes SSH tunel (krok 2).

```bash
D=$(mktemp -d)
# Názvy PEM souborů se LIŠÍ (např. pivovarska-12_client-cert.pem) → vytáhni reálné, ne <firma>_…:
ITEM=_rb_client_<firma>
FILES=$(op item get "$ITEM" --vault Cortex-RB-Keys --format json | jq -r '.files[].name')
CERTF=$(echo "$FILES" | grep -i cert | head -1); KEYF=$(echo "$FILES" | grep -i key | head -1)
op read "op://Cortex-RB-Keys/$ITEM/$CERTF" --out-file "$D/cert.pem"
op read "op://Cortex-RB-Keys/$ITEM/$KEYF"  --out-file "$D/key.pem"
# IČ rovnou z certu (do kroku 2): NTRCZ-<ico>
ICO=$(openssl x509 -in "$D/cert.pem" -noout -subject -nameopt sep_multiline,utf8 | grep -iE "organizationIdentifier|2\.5\.4\.97" | grep -oE "[0-9]{6,}" | head -1)
# POZOR: OpenSSL 3 default (AES) forge/Go pkcs12 parser NEPŘEČTE → MUSÍ -legacy
openssl pkcs12 -export -legacy -inkey "$D/key.pem" -in "$D/cert.pem" -out "$D/<firma>.p12" -passout pass:"$(openssl rand -hex 12)"
```
**On failure:** špatný PEM/klíč → `openssl pkcs12` selže; ověř, že cert a key tvoří pár
(`openssl x509 -noout -modulus -in cert.pem | openssl md5` == `openssl rsa -noout -modulus -in key.pem | openssl md5`).
Po dokončení `shred`/smaž `$D`.

### 2. CMA: vytvoř firmu (idempotentní na slug)  *(Tier 1)*

```bash
# CMA je interní-only (ClusterIP). Z Macu tuneluj přes control na mcp-rb ClusterIP:5211:
ssh -f -N -L 15211:10.43.213.52:5211 claude@yeast-cortex-control
# admin-key NIKDY netiskni — ber přes curl config file (mimo argv/ps):
CFG=$(mktemp); chmod 600 "$CFG"; printf 'header = "X-CMA-Admin-Key: %s"\n' "$(op read 'op://Cortex-Platform/mcp-rb-cma-admin/password')" > "$CFG"
curl -sS -K "$CFG" -X POST localhost:15211/cma/v1/resources/companies \
  -H 'Content-Type: application/json' \
  -d "{\"slug\":\"<firma-slug>\",\"displayName\":\"<Název s.r.o.>\",\"ico\":\"$ICO\",\"clientGroup\":\"<group>\"}"
# -> vrátí company id (uuid). 409 = slug už existuje (reuse).
# Kontrola existujících:  curl -K "$CFG" "localhost:15211/cma/v1/resources/companies?size=200"
#   (klíč odpovědi = "items", NE "data"; size>200 -> HTTP 400)
# Po práci: shred -u "$CFG"
```
slug = lowercase `[a-z0-9_-]`, shodný s cert názvem (`_rb_client_<slug>`). `ico` z kroku 1 (NTRCZ-<ico> na certu).
**`clientGroup` nastav správně** — řídí pokrytí feed klíčem (krok 8) i `RB_KEY_<GROUP>` (krok 9).

### 3. CMA: nahraj .p12 → PENDING cert  *(Tier 1)*

```bash
curl -sS -X POST localhost:15211/cma/v1/resources/certs/<COMPANY_ID>/files/p12 \
  -H "X-CMA-Admin-Key: $ADMIN" \
  -F "file=@$D/<firma>.p12" -F "password=<P12_PASS>"
# -> cert METADATA (subjectCn, notAfter, fingerprint, org_identifier). Status=PENDING. Vrací CERT_ID.
```
POZOR na path param: zde `:id` = **COMPANY id**. Max 256 KB. Žádné klíčové bajty se nevracejí ani nelogují.

### N. Human approval gate — AKTIVACE certu  *(HITL — Petr, NE Tier 1)*

Platí podmínka `cert_activate`. **Admin-key je pro activate vždy 403** — aktivovat musí lidská OIDC
identita se scope `rb:activate` (single strong approver, `RB_ACTIVATE_APPROVERS=1`).

- **Cesta (doporučeno):** cortex-ui Console → Certs tab → vyber firmu → cert v PENDING → **„Aktivovat"**
  (tlačítko nese operátorův OIDC token). Atomicky PENDING→ACTIVE, supersede předchozí ACTIVE,
  auto-fire `refreshCompanyAccounts`.
- **Nepokračovat** dál, dokud cert není ACTIVE.
- Gotcha: Authentik `rb:activate` scope mapping musí reálně vracet `{"scp":["rb:activate","cma:read","cma:write"]}`,
  audience = OAuth client_id; jinak 403 INSUFFICIENT_SCOPE.
- Pozn.: od **cortex-ui 0.1.14** (`slugFromSubject` fix — odvozuje per-company slug z názvu, ne z tenantSlug)
  zakládá Console firmu se správným slugem → **celý cert lifecycle (create+upload+activate) lze udělat čistě
  v Console**; kroky 2–3 přes API jsou alternativa (např. pro hromadné napojení). Před 0.1.14 Console tvořil
  per-tenant kolize (mislabel `yeastfin`).

### 5. Ověř cert test-callem  *(Tier 1)*

```bash
curl -sS -X POST localhost:15211/cma/v1/actions/test-call \
  -H "X-CMA-Admin-Key: $ADMIN" -H 'Content-Type: application/json' \
  -d '{"company":"<firma-slug>","op":"accounts"}'
# -> {ok:true, result:{accountCount, totalPages, last}} (jen počty, žádné PII). HTTP 200 = mTLS OK.
```
**On failure:** `409 CERT_NOT_ACTIVE` (aktivuj — krok N), `403 INSUFFICIENT_RIGHTS` (cert neautorizuje účet),
`500 CERT_DECRYPT_FAILED` (KEK/AAD mismatch).

### 6. Zjisti RB čísla účtů  *(Tier 1)*

```bash
curl -sS localhost:15211/cma/v1/resources/accounts?parent=<COMPANY_ID> -H "X-CMA-Admin-Key: $ADMIN"
# -> čísla účtů / IBAN / měny autorizované certem (po aktivaci se naplní z refreshCompanyAccounts).
```
Tato čísla jdou do `rb_account` v ACCOUNTS tuple.

### 7. Najdi FlexiBee bankovni-ucet kod per účet  *(Tier 1)*

Přes mcp:flexibee pro `<flexibee_company_db>`:
```
flexi_query evidence="bankovni-ucet" detail="custom:kod,nazev,iban" limit=50
```
Vyber `kod` účtu odpovídajícího RB číslu. **Musí přesně sedět** — feed čte `banka@showAs` (před " (")
a porovnává s částí za `code:`. Mismatch → 0 existujících → vše vypadá jako mezera → re-book. Běžné
názvy: `code:RB_<acct>` (běžný), `code:RB_SPOR_<acct>` (spořicí) — ale formát NENÍ vynucený, opiš reálný kod.

### 8. Ověř/dodej feed consumer key allowedCompanies  *(Tier 1)*

`RB_KEY_<GROUP>` je scoped `rbk_` consumer key. Zkontroluj jeho pokrytí:
`curl -K "$CFG" localhost:15211/cma/v1/consumers?size=100` → consumer skupiny (`bank-feed-<group>`) →
`keys[].allowedGroups` / `allowedCompanies`. Dvě varianty:
- **`allowedGroups:["<group>"]`** (NÁŠ případ, např. `bank-feed-taf-estate`; `allowedCompanies` prázdné) →
  firma s `clientGroup=<group>` z kroku 2 je **automaticky pokrytá, NIC nedoplňuj**.
- **`allowedCompanies:[…]`** (per-slug) → musíš do klíče **dodat nový slug**, jinak feed dostane 403 na X-Company.

### 9. Přidej do bank_feed.py ACCOUNTS  *(Tier 1)*

`cortex-infra/services/cortex-platform/k3s/30-celery-worker/bank_feed.py` — per účet jeden 5-tuple:
```python
# group, rb_slug, rb_account, fb_company, banka_kod
("taf-estate", "<firma-slug>", "<rb_account>", "<flexibee_company_db>", "code:<flexibee_bank_kod>"),
```
Pokud je to nová group: přidej řádek do `KEYS` dictu (`"<group>": os.environ.get("RB_KEY_<GROUP>","")`)
a do CronJob env doplň secret `RB_KEY_<GROUP>` (1Password, ADR 0001). Jeden řádek **per účet** (běžný +
spořicí = 2 řádky, stejný slug+firma, jiné číslo+kod).

### 10. Human approval gate — DRY-RUN než to jede naživo  *(HITL — go-live)*

Platí `feed_go_live`. Nejdřív nasucho, per nová firma:
```bash
FEED_DRY=1 FEED_ONLY=<firma-slug> FEED_SRC=rb python3 bank_feed.py
```
Zkontroluj digest: žádné `*_err`, správná FlexiBee firma, rozumný počet mezer. **Nepouštět live**,
dokud dry-run není čistý. Teprve pak merge PR (ArgoCD nasadí).

### 11. PR + deploy + verify live  *(Tier 1)*

PR → `main` → ArgoCD (cortex-platform ApplicationSet) nasadí. Po prvním ostrém běhu zkontroluj Matrix
digest „🏦 Bank-feed" + FlexiBee `banka` daného `fb_company` (nové pohyby s `cisObj`).

### 12. Backfill historie účtu  *(Tier 1; doporučeno po každém novém napojení)*

Scheduled cron (`*/15 7-19`) tahá jen poslední `FEED_DAYS` (default 6). Nově napojený účet nemá
historii → doplň ji **jednorázovým backfillem až 88 dní zpět**.

- **Max okno = 88 dní.** Kód má `win = min(FEED_DAYS, 88)` — RB odmítne `from` starší než ~88 dní
  (HTTP 422 `DT01`). Takže `FEED_DAYS=88` je strop (ne 90).
- **Idempotentní** (dedup `cisObj` = RB `entryReference`) → bezpečné spustit opakovaně, nepřeúčtuje
  už zaúčtované pohyby. Ale i tak **nejdřív `FEED_DRY=1`** (preview počtů), pak commit.
- `FEED_ONLY` je **jeden slug** → backfill per firma (nešahá na ostatní). `FEED_SRC=rb` (jen RB).

Mechanismus = jednorázový **Job z CronJobu** `cortex-bank-feed` s env overrides (z nasazeného
ConfigMap skriptu — tj. AŽ po merge kroku 11 + ArgoCD sync):

```bash
# dry-run (preview), per firma. FEED_DRY=0 pro ostrý commit.
SLUG=taf-estate-projects; JOB=bf-$SLUG
kubectl -n cortex-platform get cronjob cortex-bank-feed -o json | python3 -c "
import json,sys
cj=json.load(sys.stdin); jspec=cj['spec']['jobTemplate']['spec']; c=jspec['template']['spec']['containers'][0]
ov={'FEED_DAYS':'88','FEED_SRC':'rb','FEED_ONLY':'$SLUG','FEED_DRY':'1'}   # FEED_DRY=0 = commit
c['env']=[e for e in c.get('env',[]) if e.get('name') not in ov]+[{'name':k,'value':v} for k,v in ov.items()]
print(json.dumps({'apiVersion':'batch/v1','kind':'Job','metadata':{'name':'$JOB','namespace':'cortex-platform'},'spec':{**jspec,'backoffLimit':0,'ttlSecondsAfterFinished':900}}))
" | kubectl apply -f -
kubectl -n cortex-platform wait --for=condition=complete job/$JOB --timeout=150s
kubectl -n cortex-platform logs job/$JOB   # digest: "<fb_company> acct=... -> {'book': N}" + TOTALS
```

**On failure:** `pull_err`/422 → okno >88 dní (sniž `FEED_DAYS`); 0 booked u dry-runu kde čekáš pohyby →
zkontroluj FlexiBee `bankovni-ucet` kod (krok 7) a feed řádek (krok 9). Po commitu ověř FlexiBee `banka`.
Joby uklidí `ttlSecondsAfterFinished`, nebo `kubectl delete job <name>`. *(Reálně 2026-06-28: 5 TAF firem,
88 dní → 10/10/6/11/28 = 65 pohybů, 0 chyb.)*

## Exception Handling

| Situace | Akce | Kdo to řeší |
|---|---|---|
| `.p12` parse fail v CMA | re-export s `-legacy` | Tier 1 |
| activate 403 ADMIN_KEY_FORBIDDEN | použij OIDC (Console), ne admin-key | Petr |
| activate 403 INSUFFICIENT_SCOPE | doplň `rb:activate` scope mapping v Authentiku | Petr |
| test-call 409 CERT_NOT_ACTIVE | dokonči aktivaci | Petr |
| feed 403 na X-Company | dodej slug do consumer key allowedCompanies | Tier 1 |
| dry-run boří se do špatné firmy / 0 match | oprav `fb_company` / `banka_kod` (přesný showAs) | Tier 1 |
| cert blízko expiraci | rotace (upload nový .p12 → `actions/rotate` → aktivace) | Tier 1 + Petr |

## Output

- mcp-rb: firma + **právě jeden ACTIVE** cert; accounts cache naplněná.
- `bank_feed.py`: nové ACCOUNTS řádky (PR mergnutý).
- Live: RB pohyby firmy se à 15 min párují/účtují do FlexiBee `banka`.

## Validation (Success criteria detail)

- `test-call accounts` HTTP 200 (mTLS chain funguje).
- `GET certs?parent=<id>` → přesně 1 ACTIVE.
- `FEED_DRY=1 FEED_ONLY=<slug>` digest bez `*_err` a do správné `fb_company`.
- Po live běhu: nové `banka` pohyby s `cisObj` v cílové firmě; žádné duplicity.

## Role mapping

- `ROLE-OPS-001` (Tier 1 infra) — kroky 1–3, 5–9, 11 (cert custody, CMA upload, feed PR, validace).
- `ROLE-OPS-APPROVER` (OIDC `rb:activate`, dnes Petr) — krok N (aktivace) + krok 10 (go-live).
- Cortex Tier 2 agent: NE (key custody + lidský OIDC activate to vylučují; `agent_suitable: false`).

## Changelog

- 0.1.0 (2026-06-28) — první verze; z reconu mcp-rb CMA + bank_feed.py při onboardingu 5 TAF firem.
- 0.2.0 (2026-06-28) — přidán krok 12 „Backfill historie účtu" (jednorázový Job z cronjobu, max 88 dní,
  `FEED_DAYS/FEED_ONLY/FEED_SRC/FEED_DRY`, idempotentní cisObj dedup); ověřeno na 5 TAF firmách (65 pohybů).
- 0.3.0 (2026-06-28) — kontrolní opravy z ostrého běhu: (1) krok 8 = feed klíč pokrývá přes `allowedGroups`
  (clientGroup), ne nutně per-company `allowedCompanies`; (2) precondition `bankovni-ucet` = ruční FlexiBee
  blocker (přes MCP nelze); (3) krok 1 = vytáhni reálné názvy PEM + IČ z certu; (4) CMA přes SSH tunel z Macu
  (op vidí vaulty jen na Macu), companies list klíč `items`/`size<=200`, admin-key přes curl `-K` config.
  Plus: od cortex-ui 0.1.14 jde cert lifecycle celý v Console.
