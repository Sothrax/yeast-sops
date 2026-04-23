# Secrets & Config Conventions

Závazné pro všechny SOPky a role v tomto repu. Pokud SOP volá externí službu / API /
databázi, řídí se **tímto dokumentem**. Cíl: single source of truth pro secrets, žádná
hodnota v repu, jeden standard reference napříč celým projektem.

---

## Core pravidlo — tří-vrstvý model

| Vrstva | Kde žije | Co tam patří | Příklad |
|---|---|---|---|
| **Secrets** | 1Password Connect | credentials, API keys, tokens, hesla | `azure_docint_key_primary`, `flexibee_password` |
| **Sensitive config** | 1Password Connect *(bundled ve stejném itemu jako secret)* | tenant-specific endpointy, subscription IDs, company IDs | `azure_docint_endpoint`, `flexibee_base_url`, `flexibee_company_id` |
| **Operational config** | Supabase (`sop_config` / `tenants` tabulka) | non-sensitive knobs, intervaly, thresholds, flagy | `polling_interval_min`, `ocr_confidence_threshold`, `max_retries` |

**Co se do repa ani commit historie nesmí dostat:**

- Skutečné hodnoty secrets (hesla, klíče, tokeny)
- Tenant-specific endpointy / IDs s citlivým kontextem
- `.env` soubory s production hodnotami
- 1P Connect tokeny v jakékoli formě

Gitignore je poslední linie obrany, ne první. Secrets do gitu vůbec nemíří.

---

## 1Password Connect — setup

### Vaulty

| Vault | Účel |
|---|---|
| `cortex-prod-core` | **Production** secrets pro SOPky, Cortex agenty, automation runtime |
| `cortex-dev-core` | Dev / staging |
| `cortex-sandbox-core` | Experimentální, throwaway credentials |

SOPka běžící v prod **nikdy** nesáhne do dev vaultu a naopak. Separace je vynucena 1P Connect tokeny — každé prostředí má svůj.

### Item naming convention

Pattern: `<service>-<env>` nebo `<service>-<tenant>-<env>`

| Příklad | Co to je |
|---|---|
| `azure-docint-prod` | Azure Document Intelligence, sdílený napříč tenanty |
| `ares-gateway-prod` | ARES MCP gateway |
| `iban-validator-prod` | IBAN validator service |
| `flexibee-pq-group-prod` | FlexiBee instance pro PQ Group |
| `flexibee-taf-estate-prod` | FlexiBee instance pro TAF Estate |
| `supabase-yeastfin-prod` | Supabase projekt yeastfin |
| `sharepoint-yeast-prod` | SharePoint / MS365 API |
| `slack-yeast-prod` | Slack bot token |

**Pravidla:**

- lowercase kebab-case
- žádné mezery, diakritika, speciální znaky (kromě `-`)
- `env` sufix vždy (`prod` / `dev` / `sandbox`)
- pokud je služba tenant-specific → tenant slug v názvu (musí odpovídat `tenants.slug` v Supabase)

### Item field layout

Typický field set pro "externí API" item:

| Field | Type | Poznámka |
|---|---|---|
| `endpoint` | URL | main API endpoint |
| `key_primary` | Password (masked) | primary rotovací klíč |
| `key_secondary` | Password (masked) | backup pro zero-downtime rotation |
| `username` | Text | pokud je relevantní (basic auth) |
| `tenant_id` / `subscription_id` / `company_id` | Text | služba-specific identifikátor |
| `region` / `environment` | Text | např. `westeurope` |
| `rotation_due_date` | Text (ISO date) | termín další rotace |
| Notes | — | owner, DPA link, created_at, kontakt na admin konzoli |

**Tags:** service type (`azure`, `flexibee`, `slack`), SOP ID (`sop-acc-t002`), prostředí (`production`), tenant (`pq-group`).

---

## Reference scheme — `op://` URI

V SOPkách, rolích a agent YAMLech se secrety **nikdy** neukládají jako hodnoty, jen jako reference:

```
op://<vault>/<item>/<field>
```

### Příklady

```
op://cortex-prod-core/azure-docint-prod/endpoint
op://cortex-prod-core/azure-docint-prod/key_primary
op://cortex-prod-core/flexibee-pq-group-prod/endpoint
op://cortex-prod-core/flexibee-pq-group-prod/key_primary
op://cortex-prod-core/ares-gateway-prod/key_primary
```

Resolution provádí runtime (Cortex agent, Claude worker, Python script) přes 1Password
Connect SDK. Runtime má v env `OP_CONNECT_HOST` + `OP_CONNECT_TOKEN`, při startupu
resolví všechny `op://` refs a drží plaintext values jen v paměti.

---

## Jak zapsat secrets do SOPky

Ve frontmatteru **ne**. Secrets patří do dedikované sekce v body:

```markdown
## Secrets & Config

### From 1Password (`cortex-prod-core`)

| Name | Ref | Used in step |
|---|---|---|
| `AZURE_DOCINT_ENDPOINT` | `op://cortex-prod-core/azure-docint-prod/endpoint` | 2 |
| `AZURE_DOCINT_KEY` | `op://cortex-prod-core/azure-docint-prod/key_primary` | 2 |
| `ARES_API_KEY` | `op://cortex-prod-core/ares-gateway-prod/key_primary` | 3 |
| `SUPABASE_URL` | `op://cortex-prod-core/supabase-yeastfin-prod/endpoint` | 5 |
| `SUPABASE_SERVICE_KEY` | `op://cortex-prod-core/supabase-yeastfin-prod/key_primary` | 5 |

### From Supabase (`sop_config` table)

| Name | Key | Default | Used in step |
|---|---|---|---|
| `polling_interval_min` | `SOP-ACC-T002.polling_interval_min` | `15` | 1 |
| `ocr_confidence_threshold` | `SOP-ACC-T002.ocr_confidence_threshold` | `0.85` | 3 |
| `max_retries` | `SOP-ACC-T002.max_retries` | `3` | 1 |
```

**Pravidla:**

- Environment variable name (`AZURE_DOCINT_KEY`) = UPPER_SNAKE_CASE, co runtime očekává
- `op://` ref = exakt URI, lze ho copy-paste přímo do Cortex runtime
- Sloupec "Used in step" mapuje na číslo kroku v **Steps** sekci SOPky (auditovatelnost)

---

## Rotation cadence

| Secret type | Default | Critical |
|---|---|---|
| API keys (OCR, ARES, IBAN, …) | 90 dní | 30 dní |
| Database passwords | 60 dní | 30 dní |
| OAuth client secrets | 180 dní | 90 dní |
| Service account tokens | 90 dní | 30 dní |
| 1P Connect tokens (`agents-read`) | 30 dní | — |
| 1P Connect tokens (`admin`) | ad-hoc | — |

"Critical" = secret kde kompromitace znamená finanční / compliance dopad (FlexiBee prod,
bankovní API, payment gateway).

### Zero-downtime rotation — general pattern

1. V provideru (Azure, FlexiBee, …) vygeneruj nový key → zapíše se jako `key_secondary`
2. V 1P updateni field `key_secondary`
3. Deploy / restart agentů, ověř že čtou obě (primary + secondary funkční)
4. V provideru regenerate `key_primary` → starý primary zneplatněn
5. V 1P updateni `key_primary` na novou hodnotu (posun secondary → primary)
6. V 1P nastav nový `rotation_due_date` (today + cadence)

Agenty pořád běží, žádný restart mezi kroky 2 a 5 není potřeba, pokud kód načítá secret
při každém volání (doporučeno pro agenty s dlouhou životností).

---

## 1P Connect access

### Tokeny

| Token | Scope | Rotation |
|---|---|---|
| `op-connect-token-agents-read` | read-only, vault `cortex-prod-core` | 30 dní |
| `op-connect-token-admin` | full access, všechny vaulty | ad-hoc, jen správce |

Agenty a SOP runtime **nikdy** nedostanou admin token. Vždy read-only scope na konkrétní
vault.

### Deploy pattern

Runtime environment:

```bash
OP_CONNECT_HOST=https://op-connect.yeast.internal
OP_CONNECT_TOKEN=<read-only-token>
```

Injected přes:

- Docker secrets / Kubernetes secrets pro containerized workloady
- Systemd service `EnvironmentFile=` pro bare-metal
- CI/CD pipeline env (GitHub Actions secrets → runtime env) pro scheduled jobs

**Never** v `.env` souboru v repu, ani v `.env.example`. Ani v docker-compose.yml
committed do gitu.

---

## Supabase `sop_config` tabulka

Schema:

```sql
create table sop_config (
  sop_id       text not null,             -- "SOP-ACC-T002"
  key          text not null,             -- "polling_interval_min"
  value        jsonb not null,            -- 15
  description  text,
  tenant_slug  text,                      -- null = global default, non-null = per-tenant override
  updated_at   timestamptz default now(),
  updated_by   text,
  primary key (sop_id, key, tenant_slug)
);
```

**Lookup pattern** v SOPce:

```sql
select coalesce(
  (select value from sop_config where sop_id = $1 and key = $2 and tenant_slug = $3),
  (select value from sop_config where sop_id = $1 and key = $2 and tenant_slug is null)
) as value;
```

Per-tenant override má přednost, fallback na global default.

---

## Checklist před mergem SOPky

- [ ] Žádná literal hodnota secretu v textu SOPky (`grep -E '[a-zA-Z0-9]{32,}'` nic nenajde)
- [ ] Všechna externí volání mají `op://` referenci v sekci **Secrets & Config**
- [ ] 1P item existuje ve vaultu `cortex-prod-core` a má vyplněné všechny referenced fields
- [ ] `rotation_due_date` nastaveno v 1P itemu (ne později než default cadence)
- [ ] Non-sensitive config v Supabase `sop_config`, ne hardcoded v SOPce
- [ ] Permissions v frontmatter (`required_permissions`) odrážejí co SOP skutečně dělá
  (read/write na externí službu → explicitně uveden)

Pokud cokoli z těchto neprošlo → **reject PR**, ne merge.

---

## FAQ

**Q: Proč ne `.env` soubory?**
A: Verzovat se nedají (nebo dají, ale pak jsou secrets v gitu), nemají audit log, nemají
rotation workflow, nejdou rychle revoke. 1P má všechno out-of-the-box.

**Q: Proč ne Azure Key Vault / HashiCorp Vault / AWS Secrets Manager?**
A: Protože už máme 1P Connect nasazený. Více secret storů = rozdělená pozornost,
více auditů, více rotation workflows. Pokud někdy migrujeme, je to jednorázová akce
a konvence drží — mění se jen backend za `op://` URI scheme.

**Q: Co když potřebuju secret pro lokální dev?**
A: `cortex-dev-core` vault + vlastní dev Connect token. Developer si natáhne secrets
přes 1P CLI (`op inject` / `op run`). Nikdy nekopíruj z `cortex-prod-core` do `.env`.

**Q: Supabase anon key je secret, nebo config?**
A: **Anon key je public-safe** (určený pro frontend s RLS), ale mi ho stejně dáváme do
1P jako `supabase-yeastfin-prod/key_anon`, protože:
1. Konzistence (všechny Supabase credentials na jednom místě)
2. Rotation workflow je stejný
3. Změna Supabase projektu = jeden item update, ne grep napříč repem

**Service_role key** je plně sensitive (bypass RLS) a musí být v 1P se striktním access.

---

## Historie změn

- 2026-04-23 — v1.0 — initial conventions, zavedení 1P Connect vault `cortex-prod-core` jako single source of truth pro secrets napříč yeast-sops projektem (petr@yeast-group.cz)
