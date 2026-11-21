# JANICE: Just-in-time Analytics for Network Improvement and Clinical Evaluation — Design Document

Nov 19, 2026 · @Franklin Okech

## Overview

JANICE (Just-in-time Analytics for Network Improvement and Clinical Evaluation) is a chat assistant that lets clinical teams and hospital administrators ask questions of their quality improvement (QI) data in plain language and get back trustworthy numbers, tables and charts. It sits on top of the pooled Clinical Information Network (CIN) data and answers only from curated, pre-defined QI indicators, so every answer can be traced to a governed metric.

### Problem

QI teams in maternity, neonatal and paediatric units collect rich data, but drilling into it today needs an analyst, a REDCap export or a static report. Questions such as "how did our neonatal sepsis case fatality change after the new protocol?" take days to answer, so the data rarely drives the next Plan-Do-Study-Act (PDSA) cycle.

### Goals

1. A clinician or administrator gets an answer to a QI question in under a minute, without writing SQL.
2. Every number JANICE shows comes from a named, versioned indicator definition and can be reproduced.
3. Users see only the sites and units they are authorised for.
4. Answers show time trends with annotations for when interventions started, so teams can evaluate change.

### Non-goals

- Clinical decision support for individual patients.
- Writing back to REDCap or correcting source data.
- Free-form SQL generation against raw tables (see the MCP section for why).
- Replacing the existing CIN reports and data quality processes.

### Users

| User | Typical question | Needs |
| --- | --- | --- |
| Unit QI team (nurses, clinicians) | "Did partograph use improve since we started audits in March?" | Own unit, monthly trends, intervention markers |
| Hospital administrator | "Which units are below target on admission vitals completeness?" | All units at own hospital, targets, rankings |
| County or network lead | "How does our site compare with the network median?" | Cross-site comparison, de-identified benchmarks |
| CIN data team (KWTRP) | "Which sites have incomplete data this quarter?" | Data completeness, pipeline health |

## Decisions

Seventeen design questions were settled on 19 Nov 2026; the rest of this document reflects them.

| Topic | Decision | Section |
| --- | --- | --- |
| Data access | KWTRP exposes the pooled CIN data through the REDCap API; the data is not de-identified | Data ingestion |
| De-identification | JANICE hashes every field flagged as an identifier in the REDCap metadata before the data reaches the warehouse | Data ingestion |
| Load strategy | One full refresh, then incremental runs using REDCap's `dateRangeBegin` | Data ingestion |
| Access model | Role-based access plus row-level security over a network, country, county, site, unit scope hierarchy | Access control |
| Small numbers | Suppression follows a recommended default policy; every threshold is configurable | Access control |
| API | Versioned (`/api/v1/`) | API |
| Inference | Hosted LLM: Claude API for the pilot | MCP server |
| Hosting | KWTRP servers, operated by the CIN data managers | Deployment and operations |
| Packaging | Every component runs in Docker containers | Deployment and operations |
| Pilot scope | All three units (maternity, neonatal, paediatrics), five indicators | Transformation |
| Research | A JANICE evaluation paper will follow the pilot | Evaluation and roadmap |
| Orchestration | Dagster (open source, self-hosted) runs the pipeline | Data ingestion |
| Ways of working | Agile, two-week sprints; CI/CD, TDD, security-first | Engineering practices |
| Branching | Git flow: feature, develop, release, hotfix, main | Engineering practices |
| Environments | Laptop for development, your server for staging, KWTRP for production | Engineering practices |
| Sign-in | Keycloak: KWTRP LDAP for staff, invite-only accounts with two-factor for everyone else | Access control |
| Production deployment | Follows KWTRP IT's own deployment processes | Deployment and operations |

## Data sources

The pooled CIN dataset held by the KEMRI-Wellcome Trust Research Programme (KWTRP) is the single source of truth; JANICE never reads from site-level REDCap projects.

At each site, unit staff transcribe paper forms (maternity, neonatal, paediatrics) into a structured REDCap project. These projects sync to KWTRP, which pools and manages the data for the Clinical Information Network. JANICE reads only from the pooled copy, so all users see the same numbers that CIN reports use.

| Property | Status | Detail |
| --- | --- | --- |
| Access method | Confirmed | KWTRP exposes the pooled data through the REDCap API |
| Identifiers | Confirmed | Not de-identified; JANICE hashes fields flagged as identifiers in the metadata |
| Units in scope | Confirmed | Maternity, neonatal and paediatrics, all in the pilot |
| Record grain | Confirmed | Three pooled classic projects, one per unit (paediatrics, neonatal, maternity); maternity has repeating instruments such as previous pregnancies |
| Refresh cadence | Confirmed | Sites sync manually once a day, at no fixed time; freshness is measured per site from the REDCap audit log |
| Data dictionary | Confirmed source | Exported on every run and versioned by JANICE |
| Identifier flags | Trusted; neonatal corrected | JANICE hashes the fields REDCap flags. Neonatal (21 Nov 2026): weight, length and head circumference were wrongly flagged and have been unflagged in REDCap; location fields remain flagged. Still to confirm: whether any names, inpatient numbers or dates of birth exist unflagged, and the paediatric and maternity flags |

### Implications for the design

- **Latency is days, not minutes.** Paper-to-REDCap transcription means JANICE should show a "data complete up to" date per site and unit on every answer.
- **Form changes break indicators.** The REDCap data dictionary must be ingested and versioned alongside the data, so dbt tests catch renamed or recoded fields.
- **Completeness varies by site.** Indicators need a denominator and a completeness measure, or the chat will confidently report rates built on partial data.

### Working with three projects

- **Three tokens, three extracts.** Each project has its own read-only API token, stored as a separate secret. Dagster runs the extract as three partitions (`paediatrics`, `neonatal`, `maternity`), each with its own watermark, so a failure in one does not hold up the others.
- **Repeating instruments.** REDCap exports repeating rows with `redcap_repeat_instrument` and `redcap_repeat_instance`. Staging splits them into one table per repeating instrument (e.g. `stg_maternity_previous_pregnancy`), keyed on record ID and instance; non-repeating rows form the main delivery table. Classic projects have no events, so the load key is record ID, repeating instrument and instance.
- **Site identifier, configured in the Django admin.** Each pooled project carries a `hosp_id` field. Data managers maintain two things in the admin, so a new hospital or a renamed field needs no code change or release:

  | Admin model | Fields | Rules |
  | --- | --- | --- |
  | REDCap project | Unit, API URL, name of the secret holding the token (never the token itself), site field name (default `hosp_id`), identifier allowlist (flagged fields kept in clear text, such as the site field), active | One per unit; changes take effect at the next pipeline run |
  | Hospital | `hosp_id` value, hospital name, county, country, active, date joined CIN | `hosp_id` unique per project; county must exist in the access hierarchy |

  Saving a hospital creates or updates its node in the access hierarchy, so RLS, indicators and the admin all use one list. dbt reads the hospital table as a source to build `dim_site`; a Dagster sensor rebuilds the affected models when the table changes. A dbt test fails if a record arrives with a site value missing from the list, and the run alerts the data managers to add it. Every change is in the audit log. If `hosp_id` is ever flagged as an identifier, the allowlist keeps it in clear text, because hashing it would break site filtering.
- **Linking mother and baby.** Because all three projects are hashed with the same key, maternity and neonatal records could be linked on a shared identifier. That raises re-identification risk, so it stays off until the data governance group approves it.

### Freshness with manual daily syncs

- Sites sync once a day at different times, so the 02:00 EAT run picks up everything synced the previous day. Monthly QI indicators do not need anything faster.
- Each site and unit gets a "data synced up to" time: the latest record change for that site in the REDCap audit log. JANICE shows it with every answer.
- A site with no sync for 3 days (configurable) is flagged on the data managers' dashboard, and answers covering that site carry a warning.
- The current month is marked provisional until every site has synced past month end.

## Architecture

A nightly pipeline builds governed indicator tables; at question time, the LLM can only reach those tables through scoped MCP tools.

&#91;embedded content: system architecture · 9 components\]

The top row runs on a schedule and ends in the `qi` schema. The bottom row runs per question: Vue sends it to Django, Django's chat loop asks the LLM, the LLM calls MCP tools, and the query service returns scoped, suppressed rows. DRF also calls the query service directly for non-chat indicator pages.

| Layer | Original choice | Refined choice |
| --- | --- | --- |
| Extract | Python REDCap client (httpx) → DuckDB | Own tested Python client instead of redquack; full load once, then incremental by `dateRangeBegin`; identifiers hashed in DuckDB |
| Load | Airbyte → Postgres | DuckDB `postgres` extension (Airbyte has no DuckDB source) |
| Transform | dbt | Keep, plus an indicator catalogue and `fct_indicator_monthly` |
| API | Django REST Framework | Keep, versioned under `/api/v1/`, ASGI for streaming |
| Access | (not specified) | Role-based access plus Postgres row-level security over a network-to-unit hierarchy |
| AI access | MCP server (open) | Typed read-only tools in Django via django-mcp-server |
| Inference | (not specified) | Claude API, with zero data retention requested |
| Front end | Vue | Keep: Vue 3, ECharts, SSE |
| Hosting | (not specified) | Docker Compose on KWTRP servers, run by CIN data managers |

## Data ingestion

JANICE loads the pooled CIN data once in full, then pulls only records created or changed since the last successful run, and hashes every flagged identifier before anything reaches Postgres. Airbyte is dropped: it supports DuckDB only as a destination, so DuckDB's own `postgres` extension does the load.

&#91;embedded content: ingestion data flow · identifiers hashed before the warehouse\]

Only the transient DuckDB staging file ever holds cleartext identifiers; it sits on an encrypted volume and is deleted once the hashed load succeeds.

**REDCap server time.** REDCap reads `dateRangeBegin` in its server's local time, with no time zone attached. The KWTRP REDCap server runs on UTC (confirmed in the Control Center, 21 Nov 2026), while Nairobi is UTC+3. The pipeline keeps every watermark as a time-zone-aware datetime and converts it to the zone in `REDCAP_SERVER_TIMEZONE` (default `UTC`) before sending it; a time with no zone is refused, because a wrong conversion would silently skip hours of changes. Times in REDCap's own logs are UTC too.

### Run types

| Run | When | What it pulls | How |
| --- | --- | --- | --- |
| Initial full load | Once, at go-live | Every record, the data dictionary, the audit log | `RedcapClient` (`janice_pipeline.redcap`): record IDs first, then records in batches of 500 |
| Incremental | Nightly (e.g. 02:00 EAT) | Records created or modified since the last watermark | `datetime_range_begin` (passed to REDCap's `dateRangeBegin`) set to the last successful run's start minus a 1-hour overlap |
| Deletion sweep | With every incremental | Records deleted since the watermark | `record_delete` events from the REDCap audit log, exported with the same client; matching rows are tombstoned |
| Reconciliation | Weekly | The full list of record IDs only | Compare with `raw`; anything missing is flagged and tombstoned |
| Full refresh | On demand, or when the data dictionary changes a field an indicator uses | Everything | Same as the initial load, into a new schema, then swapped in |

The watermark is the run's start time in the REDCap server's time zone, stored in `ingest_runs` only after the load and `dbt build` both succeed, so a failed night is retried from the same point. The 1-hour overlap means some records arrive twice; the load is an upsert, so that is harmless.

### Identifier hashing

1. **Find identifiers.** Each run exports the data dictionary and takes every field where REDCap's `identifier` flag is set. The flags are maintained in REDCap by the CIN data managers, who are the single source of truth for them.
2. **Hash.** In DuckDB, replace each identifier value with `HMAC-SHA256(key, normalised value)`. Normalise first (trim, lower-case, strip spaces from phone numbers) so the same person hashes the same way across admissions.
3. **Keep the key out of the data.** The HMAC key lives in the secrets store, never in the database or the repository. A plain SHA-256 hash is not enough: names, phone numbers and inpatient numbers come from small sets of possible values and can be reversed by trying them all, which a secret key prevents.
4. **Drop what has no analytic use.** Hashed free text is useless, so free-text identifier fields are dropped rather than hashed. Dates of birth become age at admission in `stg`.
5. **Load.** Upsert into `raw`, keyed on project, record ID, repeating instrument and instance.

If a field's identifier flag changes between runs, the run stops and alerts the data managers rather than loading a newly unflagged field in cleartext.

**Before real data is loaded:** the CIN data managers check the flags in REDCap. In the neonatal dictionary, weight, length and head circumference were wrongly flagged and were unflagged in REDCap on 21 Nov 2026. No names, inpatient numbers or dates of birth are flagged; confirm whether any such fields exist, and check the paediatric and maternity dictionaries the same way.

### Orchestration with Dagster

Use open-source Dagster, self-hosted, from the first sprint. It models the pipeline as data assets rather than tasks, so the CIN data managers can see in one UI which tables are fresh, which checks failed and what to re-run, which cron cannot show.

| Asset or check | Runs | Implementation |
| --- | --- | --- |
| `redcap_metadata` | Each run | Python asset; exports and versions the data dictionary |
| Identifier-flag check | Each run | Asset check; fails and blocks the run if identifier flags changed |
| `redcap_extract` | Each run | The Python REDCap client (`janice_pipeline.redcap`), called directly from Dagster assets, so its logs and status show in Dagster |
| `hashed_staging` and `raw_*` | Each run | Python asset: DuckDB hashing, then the load into Postgres |
| dbt models | Each run | `dagster-dbt`: every dbt model becomes an asset, and dbt tests show as asset checks |
| `qi` indicators | Each run | dbt assets; freshness check against the agreed threshold |

**Schedules and jobs.** Nightly incremental at 02:00 EAT; weekly reconciliation on Sunday; full refresh as a manual job. Ingestion runs one at a time; REDCap calls retry with backoff.

**Alerts.** A run-failure sensor emails the data managers (and posts to a team channel if KWTRP uses one).

**Deployment.** Three containers: `dagster-webserver` (UI), `dagster-daemon` (schedules, sensors) and `pipeline` (the code location, with Python, DuckDB and dbt). Dagster keeps its run history in its own Postgres database.

**Access.** Dagster's open-source UI has no login of its own, so it is published only inside the KWTRP network, behind nginx with single sign-on or at least basic authentication.

**Vendor note.** Prefect announced in July 2026 that it is acquiring Dagster Labs, and has said Dagster keeps its name, open-source licence and roadmap. Low risk for a self-hosted pilot, but worth reviewing at each major upgrade.

`ingest_runs` stays the source of truth for watermarks, so the pipeline logic does not depend on Dagster's internal storage.

## Transformation

dbt turns raw REDCap tables into one governed table of QI indicators per site, unit and month; that table, not the raw data, is what the chat queries.

### Layers

| Layer | Schema | Contents | Example models |
| --- | --- | --- | --- |
| Staging | `stg` | One model per REDCap form: rename, cast types, decode choice codes using the ingested data dictionary | `stg_neonatal_admission`, `stg_maternity_delivery` |
| Intermediate | `int` | Joined, cleaned admission episodes with derived flags | `int_admissions`, `int_neonatal_outcomes` |
| Marts | `marts` | Facts and dimensions for analysis | `fct_admissions`, `dim_site`, `dim_unit`, `dim_month` |
| Indicators | `qi` | Pre-aggregated numerator, denominator and completeness per indicator, site, unit and month | `fct_indicator_monthly` |

### The indicator catalogue

Each QI indicator is defined once, in a dbt seed or YAML file reviewed by the clinical lead, with: `indicator_id`, name, plain-language definition, numerator rule, denominator rule, unit(s), target, desired direction (higher or lower is better), version and owner. dbt builds `fct_indicator_monthly` from it. The MCP server reads the same catalogue to tell the model what exists, so a new indicator becomes askable as soon as it is merged.

### Pilot indicators

Five indicators are recommended for the pilot. Together they cover all three units, mix process and outcome measures, and build on care processes CIN already audits ([adherence indicators](https://gh.bmj.com/content/2/4/e000468.abstract), [neonatal prescribing and data quality](https://econpapers.repec.org/RePEc:plo:pgph00:0000673)). Each needs its source fields confirmed against the current CIN data dictionary before it is built.

| # | Indicator | Unit | Type | Numerator | Denominator | Desired direction |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | Core admission signs documented | Paediatrics | Process | Admissions with all agreed core signs recorded (e.g. temperature, respiratory rate, pulse, oxygen saturation, level of consciousness) | Admissions aged 2 to 59 months | Higher |
| 2 | Pneumonia treated to guideline | Paediatrics | Process | Pneumonia cases given the antibiotic regimen recommended for their severity class in the Kenyan paediatric guidelines | Pneumonia cases aged 2 to 59 months with a severity class recorded | Higher |
| 3 | Hypothermia on admission | Neonatal | Process and outcome | Neonates with admission temperature below 36.5 °C | Neonates with admission temperature recorded | Lower |
| 4 | Neonatal case fatality by birth weight | Neonatal | Outcome | Deaths, per birth-weight band (under 1000 g, 1000 to 1499 g, 1500 to 2499 g, 2500 g and over) | Admissions with known outcome in that band | Lower |
| 5 | Uterotonic given in third stage | Maternity | Process | Vaginal deliveries where a uterotonic (e.g. oxytocin) is recorded for the third stage | Vaginal deliveries | Higher |

Each indicator also reports its documentation completeness (share of the denominator where the numerator field was recorded), so a fall in performance can be told apart from a fall in recording. If the maternity form does not capture uterotonic use reliably, partograph use is the fallback for indicator 5.

**Sign-off.** An indicator review group (the CIN clinical lead for each unit, one QI lead from a pilot hospital and a CIN data manager) approves each definition and version. dbt builds only indicators marked approved in the catalogue.

### QI context tables

- **Interventions:** QI teams record when a change started ("daily vitals audit, NBU, from 2026-03-01") through the Django admin. Charts mark these dates, and the model can compare before and after periods.
- **Targets:** per indicator and optionally per site, versioned by date.

### Quality gates

- dbt tests on keys, accepted values and referential integrity, plus custom tests that numerator ≤ denominator.
- A source freshness check that fails the run if the extract is older than the agreed threshold.
- A test that fails when the REDCap data dictionary changes a field an indicator depends on.
- Statistical process control (SPC) limits computed in dbt (e.g. p-chart limits per indicator), so the chat can say whether a change is a signal or noise.

**Unvalidated dates.** About 120 date and time fields in the neonatal dictionary (for example `amikacin_date`, `date_1` to `date_18`, `cpap_start_time`) are free-text fields with no REDCap validation, so they can hold anything. Staging models parse them explicitly, and a dbt test reports the share of values that do not parse, per site and month. Report this to the CIN data managers, so validation can be added at the source.

A full semantic layer (dbt MetricFlow) is not needed for the pilot: a pre-aggregated indicator table plus a catalogue gives the same safety with less to run. Revisit if users need ad hoc slicing by many dimensions.

## API (Django REST Framework)

Django is the application backbone: it owns users and permissions, the QI context tables, conversation history and the chat loop that calls the LLM; it never lets the LLM touch the database directly.

### Responsibilities

| Area | Endpoints (all under `/api/v1/`) | Notes |
| --- | --- | --- |
| Auth | `auth/login`, `auth/token/refresh`, `auth/logout` | JWT for the Vue app; OAuth2 (django-oauth-toolkit) for MCP clients |
| Me | `me`, `me/scopes` | The caller's roles and the scopes they cover |
| Indicators | `indicators`, `indicators/{id}`, `indicators/{id}/series`, `indicators/{id}/compare` | Same query service the MCP tools use |
| QI context | `interventions`, `targets` | Write access by role (see Access control) |
| Chat | `conversations`, `conversations/{id}/messages` (POST streams) | Runs the chat loop; server-sent events |
| Feedback | `messages/{id}/feedback` | Thumbs up or down plus a comment |
| Admin | `users`, `roles`, `scopes`, `suppression-rules` | Data managers only |
| Health | `health`, `freshness` | For monitoring and the UI's data-as-of line |

### Design notes

- **One query service.** Indicator queries live in a plain Python module (`janice/queries.py`) that both DRF views and MCP tools call. Scope checks and suppression live there, once.
- **Two databases.** Django's own tables in an `app` schema; the warehouse read through a separate read-only Postgres role limited to `qi` and `marts`.
- **Streaming.** Serve Django under ASGI (uvicorn) and use an async view returning server-sent events for the chat endpoint.
- **Background work.** Exports and heavy requests go to a task queue (Celery with Redis) rather than the request cycle.

### Versioning

- **URL path versions.** DRF's `URLPathVersioning` with `ALLOWED_VERSIONS = ["v1"]`. The version is in every URL, so it shows in logs and is obvious to integrators.
- **What counts as breaking.** Removing or renaming a field, endpoint or parameter, or changing a type or meaning. Adding optional fields or endpoints is not breaking and stays in `v1`.
- **Deprecation.** When `v2` ships, `v1` keeps working for at least six months and returns `Deprecation` and `Sunset` headers.
- **Contract.** drf-spectacular publishes an OpenAPI schema per version; the Vue app's TypeScript client is generated from it, so a breaking change fails the front-end build.
- **Other versioned things.** MCP tools are versioned by name (a breaking change ships as a new tool, the old one is retired later) and the server reports its version on connect. Indicator definitions carry their own version in the catalogue, independent of the API.

### API gateway: not for the pilot

JANICE does not need a separate API gateway product (Kong, Tyk or similar): nginx and Django already do the gateway's jobs, and one more service would add another component for the data managers to run.

| Gateway job | Where JANICE does it |
| --- | --- |
| TLS, routing (`/api/v1/`, `/mcp`, the admin) | nginx |
| Request size limits, security headers, coarse rate limits | nginx (`limit_req`) |
| Authentication and token checks | Django, against Keycloak (OIDC) |
| Per-user and per-role throttling | DRF throttle classes |
| Versioning | DRF URL path versioning |
| Request logging | nginx and Django logs to Loki, with a request ID |
| Edge firewall, WAF | KWTRP IT's existing gateway in front of the server |

Revisit in Phase 3 if outside organisations call the API or MCP server with their own keys and quotas, or if JANICE splits into several backend services.

## Access control

Every user holds one or more role grants, each a pair of a role (what they can do) and a scope node (which data they see); access to a node covers everything beneath it, and Postgres row-level security enforces the scope even if application code has a bug.

&#91;embedded content: scope hierarchy and roles · 5 levels\]

The hierarchy is network, country, county, site (hospital), unit. Country is included now, with only Kenya populated, so a future expansion needs no schema change.

### Sign-in and account provisioning

Everyone signs in through one Keycloak server: KWTRP staff with their existing LDAP credentials, everyone else with an invite-only Keycloak account protected by two-factor authentication. Keycloak proves who someone is; JANICE's own role grants still decide what they can see.

| User group | How they sign in | Who creates the account | Two-factor |
| --- | --- | --- | --- |
| KWTRP staff (data managers, analysts, researchers) | KWTRP LDAP username and password, through Keycloak's LDAP federation (read-only) | Nobody: the account exists in LDAP; a data manager only adds a JANICE role grant | Required for data managers and admins; recommended for others |
| County health leads, programme leads | Keycloak local account | CIN data manager sends an invite | Required |
| Hospital administrators | Keycloak local account | CIN data manager sends an invite | Required |
| Unit QI leads and members | Keycloak local account | Their hospital administrator sends an invite, within their own hospital; data managers can too | Required |

**No open self sign-up.** Anyone can reach a "request access" form, but it creates nothing until an administrator with authority over that hospital approves it. Open self-registration would let anyone who finds the URL into a system holding health data.

**Invite flow.**

1. An administrator invites a user by email and picks a role and scope node at or below their own (a hospital administrator can grant unit roles in their hospital only).
2. The invitee gets a link valid for 72 hours, sets a password and enrols an authenticator app (or a security key).
3. On first sign-in, Django creates the user from the Keycloak identity and applies the pending role grant.
4. Every invite, grant and removal is written to the audit log.

**Keeping accounts current.**

- KWTRP staff disabled in LDAP lose access automatically at their next sign-in or within one sync cycle.
- Accounts with no sign-in for 90 days are disabled; grants expire after 12 months unless renewed.
- Hospital administrators and data managers review their users quarterly from a list in the admin.
- Self-service password reset and authenticator reset by email, with an administrator able to force a reset.

**Integration.** Django uses OpenID Connect (mozilla-django-oidc) against Keycloak; access tokens for MCP clients come from the same server. Dagster, Grafana and GlitchTip sit behind oauth2-proxy with the same Keycloak login, limited to the data manager and developer groups, so there is one sign-in for every admin screen.

If KWTRP already runs an identity provider (Keycloak, Microsoft Entra ID or similar), JANICE should federate to it instead of running its own Keycloak; check with KWTRP IT in Sprint 0.

### Roles (RBAC)

| Role | Granted at | Read indicators | Named comparison with other sites | Log interventions and targets | Manage users | Manage catalogue, suppression, pipeline |
| --- | --- | --- | --- | --- | --- | --- |
| CIN data manager | Network | Yes | Yes | Yes | Yes | Yes |
| Network analyst | Network or country | Yes | Yes | No | No | No |
| Programme lead | Country | Yes | Yes, within the country | No | No | No |
| County health lead | County | Yes | Yes, within the county | No | County users | No |
| Hospital administrator | Site | Yes | No (anonymised benchmarks only) | Yes | Site users | No |
| Unit QI lead | Unit | Yes | No (anonymised benchmarks only) | Yes | No | No |
| Unit member | Unit | Yes | No (anonymised benchmarks only) | No | No | No |

Roles map to Django groups and permissions, checked by DRF permission classes and by each MCP tool. A user can hold several grants (a clinician who leads QI in two units, say).

### Row-level security (RLS)

1. `app.scope_node` holds the hierarchy (id, level, parent); `app.role_grant` links users, roles and nodes; a view `app.user_visible_units` expands each user's grants to the units beneath them.
2. The `qi` and `marts` tables carry `unit_id`. Each has an RLS policy allowing a row only when its `unit_id` is in `user_visible_units` for `current_setting('janice.user_id')`.
3. The app connects as `janice_app`, which owns no tables and lacks `BYPASSRLS`. Each request runs in a transaction that starts with `SET LOCAL janice.user_id = <id>`, which also works behind PgBouncer in transaction mode.
4. The query service still filters by scope, so the two checks back each other up. Automated tests log in as each role and assert which rows come back.

Anonymised benchmarks (network or county median) come from a separate `qi.benchmark_monthly` table that holds only aggregates across sites, readable by all roles.

### Small-number suppression

Small counts are suppressed outside a user's own scope, using rules stored in a `suppression_rule` table that data managers edit in the admin, versioned so any past answer can be reproduced. The defaults below follow common practice in health statistics; tune them with the KWTRP data protection officer.

| Rule | Default | Applies to |
| --- | --- | --- |
| Minimum cell count | Counts from 1 to 4 shown as "<5" | Data outside the user's scope, exports, anything shared across sites |
| Zero counts | Shown | All |
| Minimum denominator for a rate | 10; below it the rate shows as "too few" | All, including own scope |
| Small-numbers warning | Flag rates with a denominator under 20 | Own scope |
| Complementary suppression | If one cell in a set is suppressed, also suppress the next smallest, so it cannot be worked out from a total | Tables with totals |
| Minimum sites for a benchmark | 5 contributing sites | Network and county medians |
| SPC signals | Not computed with fewer than 12 monthly points or a rate denominator under 10 | All |

A care team sees its own unit's exact counts, because they already know these patients and need the numbers for QI. Suppression is applied in the query service, before results reach the UI or the LLM.

## MCP server

The MCP server exposes a small set of typed, read-only tools over the indicator catalogue and `fct_indicator_monthly`; it offers no free-form SQL tool. The LLM decides which tool to call and how to explain the result, but every number comes from a tool, and the server, not the model, enforces who can see what.

### Why MCP here

The Vue app could use plain LLM function calling with no MCP at all. MCP earns its place because the same tools then work, unchanged, from other MCP clients: CIN analysts in an AI desktop app, a future reporting agent, or a different LLM vendor. If the Vue chat is the only client for the first year, MCP is optional, but cheap, since the tools have to exist anyway.

### Where it runs

| Option | How | Trade-off |
| --- | --- | --- |
| **Mounted in Django (recommended for the pilot)** | `django-mcp-server` serves `/mcp` from the same ASGI app, using DRF auth classes | One deployment, reuses Django users and the query service; ties MCP releases to Django releases |
| Separate service | Official MCP Python SDK (FastMCP), streamable HTTP, imports `janice/queries.py` | Scales and deploys independently; needs its own auth (OAuth2 token validated against Django) |

Either way, use the streamable HTTP transport and OAuth2 bearer tokens, as the MCP spec recommends for remote servers. The Django chat loop calls the MCP server with the signed-in user's token, so the same permission checks apply to chat and to external clients.

### Tools

| Tool | Inputs | Returns |
| --- | --- | --- |
| `list_scope` | none | Sites and units the caller may see |
| `list_indicators` | `unit?`, `search?` | Indicator IDs, names, one-line definitions |
| `get_indicator_definition` | `indicator_id` | Full definition, numerator, denominator, target, direction, version |
| `get_indicator_series` | `indicator_id`, `site`, `unit`, `from`, `to`, `granularity` (month or quarter) | Rows of period, numerator, denominator, rate, completeness, SPC limits |
| `compare_sites` | `indicator_id`, `period`, `sites?` | One row per site with rate and network median; other sites anonymised unless the caller may see them |
| `get_interventions` | `site`, `unit`, `from?`, `to?` | QI changes with start dates and descriptions |
| `get_spc_signals` | `indicator_id`, `site`, `unit` | Points outside control limits and runs, with plain-language rule names |
| `get_data_freshness` | `site?`, `unit?` | Last extract time and latest complete month per site and unit |

Every result also carries: the indicator definition version, a data-as-of date, any suppressed cells, and a `query_id` that the UI uses to cite and reproduce the answer.

Resources (read-only context the client can load): the indicator catalogue and a glossary of QI terms. Prompts (reusable templates): "monthly unit QI review" and "before and after an intervention".

```python
@mcp.tool()
def get_indicator_series(
    indicator_id: IndicatorId,  # enum built from the catalogue
    site: SiteCode,
    unit: Unit,
    date_from: date,
    date_to: date,
    granularity: Literal["month", "quarter"] = "month",
) -> SeriesResult:
    """Monthly numerator, denominator and rate for one QI indicator."""
    user = current_user()
    require_scope(user, site, unit)  # raises if not allowed
    return queries.indicator_series(...)  # suppression applied inside
```

### Guardrails

- **Scope in the server.** Site and unit access is checked in every tool from the caller's token; the prompt never carries permissions.
- **Typed inputs.** Indicator IDs, sites and units are enums generated from the catalogue; dates are bounded; unknown values fail with a helpful error the model can recover from.
- **Aggregates only.** Tools return counts and rates, never patient rows. Small counts are suppressed by the configurable rules in Access control.
- **Limits.** Row caps, a query timeout and the read-only database role.
- **Audit.** Each call logs user, tool, arguments, row count and `query_id`.

### The chat loop

1. Vue sends the user's message to Django.
2. Django calls the LLM with the conversation, a system prompt (role, QI framing, "only state numbers returned by tools") and the MCP tool list.
3. The LLM calls one or more tools; Django runs them through the MCP client and returns results to the LLM.
4. The LLM writes the answer. Django streams text to Vue and, separately, the tool results as structured data.
5. Vue draws charts and tables from the tool results, never from numbers the LLM typed, so a misread number in prose cannot change the chart.

&#91;embedded content: chat request sequence · 10 steps\]

Django is the only MCP client, so the MCP server and the database stay inside the KWTRP network; only steps 2, 3, 8 and 9 cross the network boundary.

### Inference: Claude API for the pilot

Call Claude directly through Anthropic's API for the pilot, ask Anthropic for zero data retention (ZDR), and keep the model behind one adapter in Django so the provider can change later.

| Option | For | Against |
| --- | --- | --- |
| **Anthropic API, direct (recommended)** | Simplest setup; new features (tool use, prompt caching) arrive first; commercial terms exclude training on API data; ZDR available on request | Billing and data processing agreement directly with Anthropic; traffic leaves Kenya |
| Claude through AWS or Google Cloud | Useful if KWTRP or Wellcome already has a cloud agreement, billing and DPA there | Another account to run; feature timing can differ |
| Self-hosted open model | Data never leaves KWTRP | GPU hardware and operations; weaker tool use; not needed while only aggregates are sent |

**Model choice.** Use a Sonnet-class model as the default for chat, which balances tool-use quality, speed and cost. A Haiku-class model can handle light work such as conversation titles. Pin exact model IDs in config and re-run the golden question set before changing them.

**Cost and speed.** Cache the system prompt, indicator catalogue and tool definitions with prompt caching, since they repeat on every turn. Set monthly spend limits and per-user rate limits in Django.

**What leaves KWTRP.** The user's question, the conversation so far and suppressed aggregates. Patient-level rows never do. Users could still type a patient's name or phone number into a question, so the UI tells them not to, and Django masks phone numbers and ID-like patterns before the call and logs that it did.

**Network.** The KWTRP firewall allows outbound HTTPS from the Django container to the Anthropic API only; nothing calls into JANICE from outside.

**Approvals.** Record the provider, data flow and retention terms in the data protection impact assessment, and confirm the hosted API with the KWTRP data protection officer before go-live.

Text-to-SQL over `marts` is a possible later phase for analysts only, with a read-only role and row limits; it is out of scope for clinical users.

## Front end (Vue)

The Vue app is a chat that answers with charts: each reply pairs a short written explanation with a run chart or table drawn from the tool results, plus the definition and data-as-of date.

### Key screens

- **Chat.** A message thread with streamed replies. Each answer card shows the chart, a "how this was calculated" panel (indicator definition, version, numerator and denominator) and a data-as-of line. Starter questions are shown for the user's unit.
- **Indicator view.** A plain page per indicator and unit, reachable from a chat answer, for users who prefer to browse.
- **Interventions.** A simple form for QI teams to log a change and its start date.

### Choices

| Concern | Choice | Why |
| --- | --- | --- |
| Framework | Vue 3 + Vite + TypeScript | Matches the existing plan; typed tool-result schemas shared with the API |
| State | Pinia | Conversations, user scope |
| Charts | Apache ECharts (vue-echarts) | Run charts with control limits and intervention markers |
| Streaming | Server-sent events from Django | Simpler than WebSockets for one-way streaming |
| UI kit | One component library (e.g. PrimeVue or Vuetify) | Accessible defaults, less custom CSS |

### Usability for clinical settings

- Works on a mid-range Android phone and on slow, intermittent connections: small bundle, charts rendered from compact JSON, retry on drop.
- Plain language first; statistical terms (control limits, special cause) explained on tap.
- Every chart exportable as an image for ward meetings and QI reports.

## Engineering practices

Every change reaches production the same way: test first on the laptop, merge through a pull request that CI must pass, deploy automatically to staging, and promote only a tagged release to the KWTRP server.

&#91;embedded content: git flow branches mapped to environments\]

### Environments

| Environment | Where | Data | Deploys | Purpose |
| --- | --- | --- | --- | --- |
| Local | Your laptop, `docker compose` | Synthetic data only, generated from the REDCap data dictionary | Manually | Feature work, TDD |
| CI | GitHub Actions runners | Synthetic fixtures | Every push and pull request | Tests, scans, image builds |
| Staging | Your staging server | Synthetic by default; hashed real data only if the server is covered by the KWTRP data agreement | Automatically from `develop` and `release/*` | Integration, user acceptance, golden-set evaluation |
| Production | KWTRP server | Real data, hashed at ingest | Tag on `main`, after manual approval | Live service |

Real patient data never sits on a laptop. Confirm with KWTRP whether the staging server may hold hashed real data; if not, staging stays synthetic and user acceptance testing happens on a KWTRP-hosted pre-production stack.

### Git flow rules

- `main` holds only released code; every merge is a tagged semantic version (`v1.2.0`).
- `develop` is the integration branch, always deployable to staging.
- `feature/<ticket>-<short-name>` branches from `develop` and returns by pull request.
- `release/<version>` branches from `develop` at the end of a release sprint; only fixes go in; it merges to `main` and back to `develop`.
- `hotfix/<version>` branches from `main` for urgent production fixes and merges to both.
- Branch protection on `main` and `develop`: no direct pushes, CI must pass, and at least one review once a second developer joins (a self-review checklist until then).
- Conventional commit messages (`feat:`, `fix:`, `chore:`), so changelogs and version bumps can be generated.

### CI/CD pipeline (GitHub Actions)

| Stage | Runs on | Checks |
| --- | --- | --- |
| Lint and format | Every push | ruff, black, mypy (Python); ESLint, vue-tsc (Vue); lintr (R); sqlfluff (dbt) |
| Unit tests | Every push | pytest, Vitest, testthat, dbt unit tests; coverage at least 80% on new code |
| Security scans | Every push | gitleaks (secrets), Semgrep and Bandit (code), pip-audit and npm audit (dependencies) |
| Integration tests | Pull requests | Full stack in Docker with Postgres: RLS per role, API contract, MCP tool schemas, pipeline on synthetic REDCap data |
| Build and scan images | Merge to `develop`, `release/*`, `main` | Docker builds, Trivy image scan, SBOM, images pushed to the registry with the commit and version tags |
| Deploy to staging | Merge to `develop` or `release/*` | Pull images, migrate, run smoke tests and Playwright end-to-end tests |
| Release checks | `release/*` | Golden question set against Claude, OWASP ZAP baseline scan of staging |
| Deploy to production | Tag on `main` + manual approval | Tagged images and release notes handed to KWTRP IT's deployment process; smoke tests after each deploy, rollback to the previous tag if they fail |

### Test-driven development

- Write the failing test first for every story; the pull request shows test and code together.
- **Python:** pytest with pytest-django and factory\_boy; one test module per role proving which rows RLS returns.
- **Data:** dbt unit tests for indicator logic on hand-built inputs, plus data tests; testthat for the R extract and the hashing step.
- **Front end:** Vitest for components, Playwright for the main user journeys.
- **LLM:** the golden question set runs as a pytest suite with a marker, nightly on staging and on every release branch; tool-call choices are asserted, prose is scored.
- **Contracts:** OpenAPI and MCP tool schemas are snapshot-tested, so an accidental breaking change fails CI.

### Security-first development

- **Threat model** in Sprint 0 (STRIDE over the data flow diagram), revisited each release.
- **OWASP ASVS Level 2** as the security checklist for the API and front end.
- **Supply chain:** pinned dependencies with lock files, Renovate or Dependabot updates, image scanning, SBOMs.
- **Containers:** non-root users, read-only file systems where possible, minimal base images, no secrets baked in.
- **Secrets:** never in git; SOPS-encrypted files or Docker secrets per environment.
- **Before go-live:** an external penetration test and a review of the threat model with KWTRP IT.

### Maintainable codebase

```text
janice/
  backend/       Django project: accounts, indicators, chat, mcp, audit apps
  frontend/      Vue 3 + TypeScript app
  pipeline/      Dagster code location, R extract, dbt project
  deploy/        compose files, nginx, Ansible playbooks, runbooks
  docs/          architecture decision records (ADRs), how-tos
  .github/       CI workflows, PR template, CODEOWNERS
```

- One repository, so a change to an indicator, its API and its UI ships in one pull request.
- Architecture decision records for every significant choice (start with the ones in the Decisions table).
- Typed code throughout (Python type hints, TypeScript), formatters enforced by pre-commit hooks.
- `make dev`, `make test` and `make deploy-staging` as the only commands a new developer needs to learn first.
- README per component and a CONTRIBUTING guide covering git flow, commit style and the definition of done.

## Deployment and operations

JANICE ships as one Docker Compose stack on a KWTRP server, built and tested in CI, and run day to day by the CIN data managers with a written runbook.

&#91;embedded content: deployment · 6 containers on a KWTRP server\]

Users reach JANICE over HTTPS through nginx. The only outbound connection is from Django to the Claude API. The pipeline reads the pooled REDCap project over the internal network.

### Containers

| Service | Compose project | Purpose | Persistent volume |
| --- | --- | --- | --- |
| `nginx` | app | TLS, built Vue app, reverse proxy | Certificates |
| `django` | app | DRF API (`/api/v1/`), chat loop, MCP endpoint, admin | None |
| `worker` | app | Celery tasks: exports, scheduled checks | None |
| `redis` | app | Celery broker, cache, rate limits | None |
| `postgres` | app | App database, warehouse (`raw`, `stg`, `marts`, `qi`), Dagster run storage | Data volume, WAL archive |
| `pipeline` | pipeline | Dagster code location: Python, DuckDB, dbt | Encrypted staging volume, cleared after each run |
| `dagster-webserver`, `dagster-daemon` | pipeline | Dagster UI, schedules, sensors | None (state in Postgres) |
| `grafana`, `prometheus`, `loki`, `alloy`, exporters | observability | Dashboards, metrics, logs, alerts | Metrics and log volumes (not backed up) |
| `glitchtip` | observability | Error tracking for Django, Vue and the pipeline | Its own small database |
| keycloak | app | Sign-in: LDAP federation, invite-only accounts, two-factor, OIDC for Django and admin tools | Its own Postgres database (backed up with the app database) |

Three Compose projects (app, pipeline, observability) on the same host for the pilot, so each can be redeployed without restarting the others.

### Server provisioning

Ansible playbooks in `deploy/` set up each server the same way (Docker, firewall, users, log rotation, backup agent), so staging and production differ only in their inventory and secrets, and a lost server can be rebuilt from scratch. Environments, branching and release steps are in Engineering practices.

### Network exposure

Production follows KWTRP IT's own deployment and network processes; JANICE supplies versioned images, the Compose files and a release note, and KWTRP IT decides how the service is published to users.

- **Production:** KWTRP IT's existing gateway, firewall and certificate process. Confirm in Sprint 0 how county hospital staff will reach it and whether their process can run a self-hosted CI runner or prefers to pull tagged releases themselves.
- **Staging (your server):** expose only HTTPS (443). Allow SSH by key only, from known IP addresses, with password login disabled; everything else blocked by the host firewall.

### Operations by the CIN data managers

| Task | How often | Where |
| --- | --- | --- |
| Check the nightly run and data freshness | Daily | Dagster UI, Grafana and failure alerts |
| Add users and role grants | As needed | Django admin |
| Publish approved indicator versions | As needed | Catalogue pull request, then release |
| Review suppression rules and access logs | Monthly | Django admin |
| Apply updates and rotate secrets | Monthly, or for security fixes | Runbook |
| Restore test | Quarterly | Runbook |

Code changes, model upgrades and new tools still need a developer. Agree who that is after the pilot, and how the data managers request changes.

## Observability

All monitoring runs self-hosted inside the KWTRP network, because logs and LLM traces contain users' questions; nothing is sent to a third-party monitoring service.

| Signal | Tool | What is collected | Retention |
| --- | --- | --- | --- |
| Metrics | Prometheus with node, cAdvisor and Postgres exporters; `django-prometheus` | CPU, memory, disk, container health, request rates and latency, database connections | 30 days |
| Logs | Loki, shipped by Grafana Alloy | Structured JSON logs from every container, with a request ID and a pseudonymous user ID; no patient data | 30 days |
| Errors | GlitchTip (Sentry-compatible, self-hosted) | Exceptions from Django, Vue and the pipeline, with stack traces | 90 days |
| Pipeline and data | Dagster asset checks, dbt tests, freshness checks | Run status, row counts, failed tests, data age | Dagster history |
| LLM usage | JANICE's own audit tables, charted in Grafana | Per answer: model ID, prompt version, tools called, tokens, cost, latency, user feedback | Per the audit policy |
| Uptime | Blackbox probes run from the staging server | Is production reachable from outside KWTRP | 30 days |
| Traces (Phase 2) | OpenTelemetry to Grafana Tempo | One trace across Vue, Django, the Claude call, MCP tools and SQL | 7 days |

A dedicated LLM tracing tool such as Langfuse can come later; its self-hosted version needs several more services, which is too much to run during the pilot.

### Service level objectives

| Objective | Target (proposed) |
| --- | --- |
| Availability, 07:00 to 19:00 EAT on weekdays | 99.5% per month |
| Chat: time to first streamed words | Under 5 s for 95% of requests |
| Chat: complete answer | Under 20 s for 95% of requests |
| Data freshness | `qi` updated by 06:00 EAT on 95% of days |
| Chat errors | Under 1% of requests |
| Golden question set | At least 95% correct before any release |

### Alerts

- **Page the developer and data managers (email and phone notification):** production down, nightly pipeline failed, identifier-flag check failed, disk over 85%, backup job failed.
- **Daily digest:** SLO burn, Claude API spend against budget, rising error rate, slow queries.
- **Security dashboard:** failed logins, permission denials, rate-limit hits, unusual export volumes.

## Disaster recovery and backups

Only the app database holds data that exists nowhere else, so it gets continuous backups and point-in-time recovery; the warehouse can always be rebuilt from REDCap, and everything else from git and the image registry.

### Recovery targets

| What | Recovery point objective (data loss) | Recovery time objective (downtime) | Why |
| --- | --- | --- | --- |
| App database: users, grants, conversations, interventions, targets, audit log | 15 minutes | 4 hours | Not recoverable from anywhere else; audit log feeds the evaluation paper |
| Warehouse: `raw` to `qi` | 24 hours | 8 hours | Rebuilt by a Dagster full refresh from REDCap |
| Code, configuration, dashboards | None | 1 hour | In git; images in the registry |
| Secrets, including the HMAC key | None | 1 hour | Encrypted copies held offline |
| Whole server lost | 15 minutes (app data) | 1 working day | Rebuild with Ansible, restore, full refresh |

### Volume-by-volume strategy

| Volume | Backed up? | Method | Frequency | Retention |
| --- | --- | --- | --- | --- |
| `postgres-data` | Yes | pgBackRest: weekly full, daily differential, continuous WAL archiving, encrypted | Continuous | 4 weekly fulls, then monthly for 12 months |
| `pipeline-staging` (cleartext) | **Never** | Excluded on purpose; wiped after each run | n/a | n/a |
| `redis` | No | Cache and queue only; rebuilt on start | n/a | n/a |
| `dagster` state | Via Postgres | Lives in the Postgres backup | n/a | n/a |
| Prometheus, Loki | No | Accept loss; dashboards are code in git | n/a | n/a |
| GlitchTip database | Yes | Nightly `pg_dump` | Daily | 30 days |
| Certificates, nginx config | No | Re-issued; config in git | n/a | n/a |
| Secrets | Yes | SOPS-encrypted in git; decryption key in two offline copies held by two named custodians | On change | All versions |

**3-2-1 rule.** Three copies of the database backups on two kinds of storage, one off the production server's site (a second KWTRP location or encrypted object storage approved by KWTRP). Make the off-site copy append-only so ransomware on the server cannot delete it.

**The HMAC key.** Losing it is recoverable: generate a new key and run a full refresh, which re-hashes everything consistently. A leaked key is the bigger risk, and the response is the same: rotate the key, then run a full refresh.

### Restore drills

- Before go-live, then quarterly: restore the latest production backup to a KWTRP-hosted scratch server (never to the laptop or a non-KWTRP staging server), time it against the RTO and record the result.
- Once a year: rebuild the whole stack from nothing on a fresh server using only the runbook.

### Incidents

A runbook covers outage, data error and security breach. For a personal data breach, KWTRP as data controller must notify the Office of the Data Protection Commissioner within 72 hours of becoming aware of it, so the runbook names who decides and who notifies.

## Security, privacy and compliance

JANICE handles health data, which Kenya's Data Protection Act 2019 treats as sensitive personal data, so the design keeps identifiable data out of every layer above the warehouse's `raw` and `stg` schemas.

| Control | Where | Detail |
| --- | --- | --- |
| Identifier hashing | Pipeline (DuckDB staging) | HMAC-SHA256 with a secret key on every metadata-flagged identifier; free-text identifiers dropped; run stops if flags change (see Data ingestion) |
| Cleartext exposure | Pipeline | Staging file on an encrypted volume, deleted after each successful load, never backed up |
| Least privilege | Postgres | Separate roles: loader (write `raw`), dbt (write `stg` to `qi`), `janice_app` (read `qi` and `marts`, no `BYPASSRLS`) |
| Role-based access | Django, MCP tools | Seven roles; permissions checked on every endpoint and tool (see Access control) |
| Row-level security | Postgres | Policies on `qi` and `marts` tied to the user's scope grants |
| Small-number suppression | Query service | Configurable rules, applied before data reaches the UI or the LLM |
| Secrets | Deployment | Docker secrets or an environment file outside the repository |
| Transport and storage | Infrastructure | TLS at nginx; encrypted disks and backups |
| Audit | Django | Questions, tool calls, arguments, rows returned and model ID, retained for an agreed period |
| LLM data flow | Chat loop | Claude API under commercial terms with zero data retention requested; only questions and suppressed aggregates are sent; ID-like patterns masked |

### Approvals to line up

- [x] Data sharing agreement with KWTRP and participating counties covering this new use of CIN data
- [x] Ethics committee review, if JANICE outputs feed research as well as QI
- [x] Data protection impact assessment and registration with the Office of the Data Protection Commissioner, as required
- [x] Decision on hosting location (KWTRP servers, a Kenyan cloud region, or elsewhere)

## Delivery plan

With a 30 November 2026 start, two-week sprints and one full-time developer, JANICE can go live in production on 31 March 2027, run a three-month pilot to the end of June, and have the evaluation paper submitted by the end of September 2027.

&#91;embedded content: delivery timeline · 7 phases, 6 milestones\]

Approvals run alongside the build, because the DPIA, ethics review and Anthropic's zero data retention request decide the go-live date more than code does. The plan allows for the Christmas and New Year holidays in Sprint 1 and Easter just before go-live.

### How the team works

- **Sprints:** two weeks, starting Mondays. Planning on day 1, a demo on staging to the CIN data managers and a QI lead on the last day, then a short retrospective.
- **Backlog:** GitHub Projects, one issue per user story, linked to its `feature/` branch and pull request. Epics match the work breakdown below.
- **Releases:** a `release/` branch at the end of every second sprint during the build, then each sprint during the pilot.
- **Definition of done:** tests written first and passing, CI green including security scans, reviewed, documented, deployed to staging and demoed.
- **People (assumed):** you as lead developer; a CIN data manager about 20% of the time; a clinical lead and one QI lead for indicator sign-off and testing; the KWTRP data protection officer and IT for approvals and the server.

### Milestones and gates

| Milestone | Done when | Sign-off |
| --- | --- | --- |
| CI/CD and staging live | A "hello world" stack deploys from `develop` to staging with every CI stage passing | You |
| Gate 1: indicators match CIN | The five indicators from a full hashed load match CIN's own reports for three recent months | Clinical lead, data manager |
| MVP on staging | A user in each role can ask about any pilot indicator and get a correct, scoped chart | Data manager, QI lead |
| Production go-live | Pen test fixed, DPIA approved, ZDR agreed, restore drill passed, users trained | KWTRP DPO and IT, CIN lead |
| Gate 2: pilot review | Pilot SLOs met, golden set at least 95%, user feedback reviewed | CIN lead |
| Paper submitted | Manuscript reporting against TRIPOD-LLM submitted | Authors |

### Work breakdown

| Epic | Key deliverables | Sprints |
| --- | --- | --- |
| E1 Platform and DevOps | Monorepo, pre-commit, CI/CD workflows, Docker Compose projects, Ansible, registry, staging server, self-hosted runner at KWTRP | S0, S1, then ongoing |
| E2 Data pipeline | Dagster project, Python REDCap client extract, identifier hashing, Postgres load, incremental and deletion sweeps, reconciliation | S1 to S3 |
| E3 Indicators | dbt project, staging models, five pilot indicators with unit tests, catalogue, SPC limits, completeness measures | S2 to S4 |
| E4 Access and security | Scope hierarchy, roles, RLS policies and tests, suppression engine, threat model, ASVS checklist, pen test fixes | S0, S3 to S5, S7 |
| E5 API | DRF `v1` endpoints, OpenAPI schema, auth, interventions and targets, admin | S3 to S5 |
| E6 MCP and LLM | Query service, MCP tools, chat loop, Claude adapter, prompt caching, masking, golden question set | S4 to S6 |
| E7 Front end | Vue app shell, chat with streamed answers, ECharts run charts, indicator pages, intervention form | S4 to S6 |
| E8 Observability and DR | Grafana stack, GlitchTip, alerts, SLO dashboards, pgBackRest, off-site copies, restore drill | S5 to S7 |
| E9 Governance | Data sharing agreement, DPIA, ODPC registration check, ethics protocol, ZDR and DPA with Anthropic | S0 to S7, in parallel |
| E10 Training and handover | User guide, short videos, data manager runbook, training sessions at pilot sites | S6 to S8 |
| E11 Evaluation | Study protocol, research data export, SUS surveys, interviews, analysis, manuscript | S0, S8 onwards |

### Sprint 0 checklist

- [ ] Create the repository, branch protection, and the git flow and commit conventions
- [ ] CI skeleton with lint, test and security-scan stages green on an empty app
- [ ] Docker Compose stack running locally and on the staging server
- [ ] Synthetic data generator built from the REDCap data dictionary
- [ ] Threat model workshop and first ADRs written
- [ ] Approvals started: DPIA, ethics protocol, Anthropic ZDR request, KWTRP server request
- [ ] Indicator review group named; field check for the five indicators started

## Evaluation and roadmap

JANICE is judged on whether its numbers are right and whether QI teams use them in their meetings; both are measured from the pilot onward.

### Evaluation

- **Golden question set.** Collect 50 to 100 real questions from QI teams across all three units, each with the expected tool, parameters and answer. Run it on every change to prompts, tools or model, and block releases that regress.
- **Correctness checks.** Right indicator and filters chosen; every number in the prose matches a tool result (checked automatically); unanswerable or out-of-scope questions get a clear refusal rather than a guess.
- **Usage.** Weekly active users per site and unit, questions per QI meeting, thumbs-up rate, median time to answer.
- **Human review.** A clinical lead reviews a weekly sample of real conversations during the pilot.

### Preparing for the evaluation paper

The paper is easier and more credible if the study is designed before the pilot starts, not reconstructed from logs afterwards.

| Element | Recommendation |
| --- | --- |
| Approvals | Protocol and ethics approval (e.g. KEMRI Scientific and Ethics Review Unit) before pilot data is used for research; user information sheet and consent for interviews |
| Reporting guideline | [TRIPOD-LLM](https://pubmed.ncbi.nlm.nih.gov/39779929/) for the LLM components, which emphasises transparency, human oversight and task-specific performance; RE-AIM to structure reach, adoption and implementation findings |
| Technical accuracy | Golden set scored for tool choice, parameters, numeric fidelity and appropriate refusal; a blinded clinician panel rates a random sample of real answers, with agreement between raters reported |
| Usability | System Usability Scale at months 1 and 3; semi-structured interviews with QI leads, administrators and data managers |
| Use in QI practice | Usage logs; whether JANICE outputs appear in QI meeting minutes and PDSA cycles; time to answer compared with the current route (analyst request or report) |
| Reproducibility | Pin the model ID, prompt version, tool versions and indicator versions for each study window, and log them with every answer |
| Research data | A pseudonymised export of conversations and tool calls, user IDs replaced by study codes, built into the audit log from day one |

Treat changes in the indicators themselves as exploratory: a pilot of this size cannot show that JANICE caused an improvement in care.

### Roadmap

&#91;embedded content: phased roadmap · 4 phases, 3 gates\]

Each phase starts only when the gate before it is met; dates are in the Delivery plan.

### Open questions

- [x] Is the pooled data one REDCap project or one per unit, and classic or longitudinal?
- [x] Site is recorded in the hosp\_id field (confirmed)
- [ ] Should maternity and neonatal records be linked (mother and baby)? Needs governance approval
- [ ] Are all direct identifiers, including free-text fields, flagged in the metadata? (audit with the CIN data managers)
- [ ] Do the current forms capture the fields the five pilot indicators need, especially uterotonic use in maternity?
- [ ] Who sits on the indicator review group?
- [ ] Which sites take part in the pilot, and who holds each role there?
- [ ] Suppression defaults agreed with the KWTRP data protection officer
- [ ] Anthropic zero data retention request and data processing agreement in place
- [ ] Who maintains the code after the pilot, and how data managers request changes

## Gaps and risks

The design now covers the system end to end, but twelve topics are still open; the first three can change the architecture and should be settled in Sprint 0.

### What the design does not yet cover

| # | Gap | Why it matters | Recommendation |
| --- | --- | --- | --- |
| 1 | How hospital staff reach a KWTRP server | Decides whether JANICE is on the public internet, behind a VPN or a KWTRP gateway, and whether phones work | Follow KWTRP IT's deployment and network process; confirm in Sprint 0 how county staff will reach the service |
| 2 | Sign-in and account lifecycle | Local passwords are weak and accounts outlive staff moves | Settled: Keycloak with KWTRP LDAP federation plus invite-only accounts with two-factor (see Access control) |
| 3 | Server sizing | Users, concurrency and data volume set CPU, memory and disk | Estimate users per site; load-test with k6 or Locust on staging before go-live |
| 4 | AI safety policy | Users may ask for clinical advice, and free text (intervention notes) can carry prompt injection | Written scope policy, refusal tests and injection cases in the golden set; never pass free text to tools as instructions |
| 5 | Retention and data subject rights | Conversations and audit logs are personal data about staff | Set retention periods per table; a process for access and erasure requests |
| 6 | Cross-border transfer | The Data Protection Act restricts transfers outside Kenya without safeguards | Cover the Claude API flow explicitly in the DPIA, even though only aggregates are sent |
| 7 | Budget | Claude API, servers, pen test and staff time are unknown | A cost model per month; API spend caps in Django |
| 8 | Training and adoption | A correct tool nobody uses fails the pilot | A champion per hospital, a user guide, JANICE built into monthly QI meetings |
| 9 | Support model | Users need someone to contact | First line: CIN data managers; second line: developer; published support hours |
| 10 | Accessibility and language | Clinical users vary in device, vision and language | WCAG 2.1 AA for the UI; confirm whether a Swahili interface is needed |
| 11 | Feedback to sites on data quality | JANICE will surface missing data that sites should fix | A monthly completeness report back through the existing CIN channels |
| 12 | Code ownership and licence | Affects handover, reuse and publishing code with the paper | Agree IP with KWTRP; consider an open-source licence |

### Risk register

| Risk | Likelihood | Impact | Mitigation | Owner |
| --- | --- | --- | --- | --- |
| Approvals (DPIA, ethics, ZDR) delay go-live | High | High | Start in Sprint 0; go-live gated on them, build continues | Project lead |
| One developer: limited capacity and no backup | High | High | Documentation, ADRs and runbooks from day one; recruit a second developer or code-review partner by Sprint 4 | Project lead |
| Indicator fields missing or poorly recorded | Medium | High | Field check in Sprint 0; completeness reported with every indicator; fallback indicators | Clinical lead |
| LLM misstates a number or over-interprets | Medium | High | Numbers only from tools, charts from tool rows, golden set gate, definitions shown with every answer | Developer |
| Re-identification through small cells or linkage | Low | High | Suppression rules, keyed hashing, RLS, DPO review | Data protection officer |
| KWTRP server lacks outbound internet or a CI runner | Medium | Medium | Confirm in Sprint 0; fall back to a pull-based deploy script run by data managers | KWTRP IT |
| Low adoption by QI teams | Medium | High | Co-design demos each sprint, champions, starter questions per unit | CIN lead |
| Claude API outage or cost overrun | Low | Medium | Spend caps; indicator pages keep working without chat | Developer |
| Staging server not approved for real data | Medium | Low | Synthetic staging; KWTRP pre-production stack for user acceptance testing | Developer |
| Tool or model changes (Dagster ownership, model retirements) | Low | Low | Pinned versions, golden set before upgrades | Developer |
| Wrong identifier flags in REDCap (measurements hashed, identifiers loaded in clear text) | High (seen in neonatal) | High | Data managers correct the flags in REDCap before the first real load; pipeline stops if flags change | CIN data managers |

## Sources

- [redquack on CRAN](https://cran.r-project.org/web/packages/redquack/refman/redquack.html): chunked REDCap transfer to a database, optimised for DuckDB
- [redquack overview, R Consortium](https://r-consortium.org/posts/redquack-an-r-package-for-memory-efficient-redcap-to-duckdb-workflows)
- [Airbyte DuckDB connector](https://airbyte.com/integrations/duckdb): DuckDB is supported as a destination
- [django-mcp-server](https://pypi.org/project/django-mcp-server): MCP endpoint inside Django, DRF auth, OAuth2 guidance
- [django-rest-mcp](https://pypi.org/project/django-rest-mcp/): alternative that exposes DRF views as MCP tools
- [Anthropic API and data retention](https://platform.claude.com/docs/en/build-with-claude/api-and-data-retention): zero data retention and HIPAA-ready arrangements
- [REDCapR news](https://search.r-project.org/CRAN/packages/REDCapR/news/news.html): `dateRangeBegin` filters records by last modified date
- [TRIPOD-LLM reporting guideline](https://pubmed.ncbi.nlm.nih.gov/39779929/), Nature Medicine 2025
- [CIN adherence indicators and audit and feedback](https://gh.bmj.com/content/2/4/e000468.abstract), BMJ Global Health
- [CIN neonatal data quality and prescribing](https://econpapers.repec.org/RePEc:plo:pgph00:0000673), PLOS Global Public Health
- [Dagster dbt integration](https://dagster.io/integrations/dagster-dbt): dbt models as Dagster assets
- [dagsterpipes for R](https://joekirincic.github.io/dagsterpipes/): R scripts run as Dagster Pipes subprocesses
- [Dagster customer FAQ on the Prefect acquisition](https://dagster.io/dagster-customer-faq)
- [ODPC data controller compliance card](https://www.odpc.go.ke/wp-content/uploads/2025/07/Data-Controllers-360-Degrees-Compliance-Requirements.-Z-Card.pdf): 72-hour breach reporting
