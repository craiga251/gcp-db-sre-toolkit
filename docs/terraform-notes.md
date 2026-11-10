# Day 0 — Why GCP, and What Carries Over from Azure

## Context for the switch

The Azure free trial's 30-day credit expired before Phase 1 of `azure-db-sre-toolkit` was finished (only the resource group, remote state storage account, and Log Analytics workspace had actually been applied). GCP offers 60 days of trial credit, so this repo picks up the same project goals on Google Cloud rather than letting that runway go unused.

The Azure subscription itself was checked and is not locked (`state: Enabled`) — this is a deliberate choice to use the fresh runway productively, not a reaction to being blocked.

## What carries over unchanged

These are platform-agnostic and don't need to be relearned:

- **Core Terraform concepts** — providers, state, plan vs apply, the `.terraform/` folder vs the state file. See the Azure repo's Day 1 notes.
- **Remote state discipline** — state must live somewhere durable, access-controlled, and separate from a single laptop. GCP's equivalent is a GCS bucket instead of Azure Storage, but the reasoning (durability, locking, no secrets on a laptop) is identical.
- **DRY / locals for tags** — GCP calls the same concept "labels" instead of "tags," but the `locals` pattern for defining them once still applies.
- **Plan-before-apply as a review gate** — same value proposition, same CI/CD implications for Phase 2.
- **The instinct to keep environment-specific values (like `owner`) out of hardcoded resource definitions and into variables.**

## What's genuinely different on GCP — to learn during Phase 0/1

- **Resource hierarchy.** Azure has subscription → resource group → resource. GCP has organization → folder → project → resource, and nearly everything (including billing) is scoped to a *project* rather than a resource group. There's no direct GCP equivalent of "resource group" as a free-floating container — the project itself plays that role.
- **IAM model.** Azure RBAC assigns roles scoped to management groups/subscriptions/resource groups/resources. GCP IAM assigns roles scoped to organization/folder/project/resource, and service identities are "service accounts" (comparable to Azure managed identities, but created and keyed differently).
- **Terraform backend.** `backend "gcs"` instead of `backend "azurerm"` — bucket must be bootstrapped out-of-band first, same chicken-and-egg problem as Day 3 on Azure.
- **Database choice.** Using Cloud SQL for SQL Server to keep the database engine consistent with prior SQL Server operational experience — Cloud SQL doesn't have Azure SQL Database's serverless auto-pause-to-zero model, so cost/idle behavior will need to be revisited when Phase 1 defines the actual instance tier.
- **Naming conventions.** GCP resource names are typically globally unique per resource *type*, not just per project, for some services (similar to Azure storage accounts). Needs checking per-resource rather than assuming Azure's CAF-style prefixing maps directly.

# Day 1 — Phase 0 complete: project, identity, and remote state on GCP (2026-11-10)

## What was built

- **GCP project** `gcp-db-sre-toolkit-514321` created via the console under organization `craigandersonbus1-org`, linked to the free-trial billing account (£226 credit, expires 2027-02-09).
- **A dedicated gcloud configuration** (`gcp-sre-toolkit`) holding this project's account, project ID, and default region (`europe-west2`).
- **APIs enabled:** Cloud SQL Admin, Resource Manager, IAM, IAM Credentials, Compute, Service Networking, Billing Budgets (Logging, Monitoring, and Storage were already on by default).
- **Terraform state bucket** `gs://gcp-db-sre-toolkit-514321-tfstate`, created out-of-band with `gcloud`: versioning on, uniform bucket-level access, public access prevention enforced, labeled `managed_by=bootstrap`.
- **`backend "gcs"`** enabled in `main.tf`. `terraform init` / `validate` / `plan` all clean, and `default.tfstate` confirmed present in the bucket. Provider locked at `hashicorp/google` 5.45.2.

## Design decisions

**Separate gcloud configurations, not a single global login.** This machine already has another Google account and project in the `default` gcloud configuration. Rather than overwrite it, a named configuration (`gcloud config configurations create gcp-sre-toolkit`) scopes the account, project, and region for this toolkit, and switching is one command. It's the gcloud equivalent of `az account set --subscription`, except it bundles *account + project + defaults* together, which makes accidentally running a command against the wrong project much less likely.

The catch: **Application Default Credentials (ADC) are not per-configuration.** `gcloud auth login` authenticates the CLI; `gcloud auth application-default login` writes a single machine-wide credentials file that Terraform and client libraries use. Those are two separate identities, and it's easy to have the CLI pointed at one account while Terraform silently uses another. Worth knowing for any multi-project or multi-tenant workstation, and a big part of why CI should never rely on a person's ADC.

**State bucket bootstrapped outside Terraform.** Same chicken-and-egg as Azure Day 3: the backend has to exist before `terraform init` can use it. Kept as a deliberate, documented manual step rather than a separate "bootstrap" Terraform root, because it's one bucket and doesn't change. Unlike the rest of the stack, this bucket is **not** torn down at the end of each session. It costs pennies and holds the state history that makes apply → verify → destroy cycles safe.

**What's simpler on GCP than Azure:** the GCS backend locks state natively (it writes a lock object into the bucket). On Azure that came from blob leases, and on AWS you'd traditionally pair S3 with a DynamoDB lock table. Here there's nothing extra to provision.

**Object versioning on the state bucket** is the recovery plan for a corrupted or badly-edited state file: roll back to a prior object generation. Cheap insurance, and the GCS equivalent of soft delete/versioning on the Azure storage account.

## Things that were different from expected

**The project landed inside an organization, and that brings policy with it.** Creating a project from a personal Gmail account on a new trial now produces an organization resource (`craigandersonbus1-org`) with Google's "secure by default" org policies attached. Checking the effective policies on the project:

| Constraint | Effect | Impact on this project |
|---|---|---|
| `iam.disableServiceAccountKeyCreation` | **Enforced:** no downloadable JSON keys for service accounts | Phase 2 GitHub Actions must use **Workload Identity Federation** (OIDC), not a stored key. This is the better pattern anyway. |
| `storage.uniformBucketLevelAccess` | **Enforced:** IAM only on buckets, no per-object ACLs | No impact; the state bucket was created with UBLA on. |
| `sql.restrictPublicIp`, `sql.restrictAuthorizedNetworks` | Not enforced | Cloud SQL public IP is allowed, but private IP is still the target design for Phase 1. |

The SRE takeaway: **org policy is a guardrail layer above IAM.** IAM answers "who can do this?" and org policy answers "can anyone do this here at all?" A project owner still can't create an SA key, because the constraint is evaluated at the org/folder level and inherited. The closest Azure analogue is Azure Policy assigned at the management group: deny effects you can't get around with RBAC alone. Checking effective org policy is now step one when something "should work but returns permission denied."

## Next up (Phase 1)

- Cloud SQL for SQL Server instance: pick the smallest viable edition/tier (Express or Web), work out private IP vs public IP, and confirm hourly cost before applying. There's no auto-pause, so it gets an apply → verify → destroy cycle in every session.
- A budget alert on the billing account as a cost guardrail.
- Decide on the serverless compute piece (Cloud Run vs Cloud Functions).

# Day 2 — Phase 1: Cloud SQL for SQL Server, three API rejections, and an in-place edition upgrade (2026-11-10)

## What was built

All Terraform-managed, in `terraform/main.tf`:

- **Cloud SQL for SQL Server 2022, Web edition**: instance `sql-sre-toolkit-euw2`, `db-custom-1-3840` (1 vCPU / 3.75 GB), zonal, 10 GB SSD with autoresize capped at 20 GB, automated backups (7 retained), Sunday 03:00 UTC maintenance window, Query Insights on.
- **Application database** `sredb`.
- **Admin password** generated by `random_password` and stored in **Secret Manager**, not typed and not in `tfvars`.
- **APIs managed in Terraform** (`google_project_service`) for Cloud SQL Admin, Secret Manager, and Cloud Trace, with `disable_on_destroy = false`.
- **A budget guardrail** (outside Terraform, like the state bucket): £25/month on the project, alerting at 50%, 90%, 100%, and a forecast of 100%. It measures spend *before* trial credits, otherwise it would show £0 and never fire.
- **`scripts/python/verify_connection.py`**: a smoke test that connects through the Cloud SQL Python Connector, reads the password from Secret Manager, and reports server, version, edition, database, and whether the connection is encrypted.

Verified output after the final apply:

```
               version: 16.0.4262.2
               edition: Web Edition (64-bit)
      current_database: sredb
  encrypted_connection: TRUE
        user_databases: gcloud_cloudsqladmin, sredb, gcloud_db_insights
```

A direct TCP connection to the public IP on 1433 was refused, which is the intended result.

## Cost: pricing from the source

Instead of the pricing calculator, prices came from the **Cloud Billing Catalog API**, which returns every SKU for a service in the billing account's currency (GBP here). For Cloud SQL for SQL Server, zonal, London:

| Component | Rate |
|---|---|
| vCPU | £0.0373 / hour |
| RAM | £0.0063 / GB-hour |
| SSD storage | £0.153 / GB-month |
| IP address | £0.009 / hour |

On top of that is the **SQL Server licence**. Express is free, Web is $0.011 per core-hour, Standard is $0.13 and Enterprise is $0.47. The key detail: **instances with fewer than 4 vCPUs are billed the licence for 4 cores.** On a 1-vCPU instance that makes Standard about £0.48/hour in total, roughly 7× Web. Left running for a month, Standard would use up the whole £226 trial credit in under three weeks.

| Edition | ~£/hour all-in | ~£/month if forgotten |
|---|---|---|
| Express | 0.07 | 50 |
| **Web (chosen)** | **0.11** | **75** |
| Standard | 0.48 | 350 |

Web is the cheapest edition with Query Insights and SQL Server Agent (Express has neither). One caveat to know about: Microsoft licenses Web edition for public-facing web workloads only. That's irrelevant for a lab, but it rules Web out for a real line-of-business system.

## Design decisions

**Public IP with no authorized networks, plus connectors, instead of private IP.** The Day 1 notes leaned towards private IP. That was reconsidered:

- Private IP needs a VPC, an allocated IP range, and a Service Networking peering connection. Reaching it from a laptop then also needs a bastion VM or VPN.
- Deleting a Service Networking connection is a well-known source of failed Terraform destroys: the peering can't be removed until Google's side has finished cleaning up after the instance. In a stack that's destroyed every session, that's a recurring problem.
- A public IP with **zero authorized networks** accepts no direct connections, which was tested above. The only way in is through the Cloud SQL Auth Proxy or a language connector. Those authenticate the caller with **IAM** (`cloudsql.instances.connect`) before any SQL login happens, and wrap the session in TLS using a short-lived client certificate. That gives two separate checks, IAM and then the SQL login, and no firewall rules to manage.

Private IP is still the right answer for production, where workloads already live in a VPC. That's noted as a possible stretch goal.

**Two layers of encryption, deliberately.** `ssl_mode = ENCRYPTED_ONLY` makes SQL Server itself require TDS encryption, even inside the connector's TLS tunnel. This caught the first connection attempt: `Client does not have encryption enabled but it is required by server`. The client fix is what ODBC Driver 18 and recent SSMS do by default (`Encrypt=Mandatory`): negotiate TLS using the instance's server CA, which is fetched from the Admin API. Host name validation is off because the client is connecting to a local tunnel endpoint, not the server's name. The SQL Server-native check, `sys.dm_exec_connections.encrypt_option`, returns `TRUE`.

**Secrets never touch a file in the repo.** The password exists in Terraform state (a private, versioned bucket) and in Secret Manager. Anything that needs it, such as the smoke test or later Phase 3 automation, reads it from Secret Manager using its own IAM identity. Saved plan files (`tfplan`) are gitignored because they contain the password in plain text.

**Two separate deletion protections, both off on purpose.** `deletion_protection` on the resource is a Terraform-side guard. `settings.deletion_protection_enabled` is enforced by the Cloud SQL API itself, so it also stops the console and gcloud. Both are off because this stack is destroyed every session. In a real environment, both would be on.

## Things that went wrong, and why they're useful

The first `terraform apply` needed **four attempts**. Every failure was a 400 from the API at validation time, so nothing was half-built and nothing was billed:

1. **`sslMode ENCRYPTED_ONLY and requireSsl false are conflicting`.** Provider 5.x sends the deprecated `require_ssl = false` unless it's set explicitly, and the API checks the two fields for consistency. Fix: set `require_ssl = true` alongside `ssl_mode`. The deprecation warning is the cost of using 5.x, and moving to provider 6.x removes it.
2. **`Query Insights features are not supported for instances with automatic storage resize disabled`.** Autoresize was turned off for cost predictability. Fix: turn it on with `disk_autoresize_limit = 20`. Arguably the better setting anyway, because a full disk stops a SQL Server instance accepting writes.
3. **`Query Insights features are not supported for SQL Server Express instances`.** This wasn't on the instance-settings page; it's on the Query Insights page. Express was applied without Insights, then upgraded (below).

The takeaway: **`terraform validate` and `terraform plan` only check the provider schema, not the cloud API's rules about how fields combine.** "Plan succeeded" doesn't mean "apply will succeed." That gap is why Phase 2's CI should run plans against a real project, and why a cheap, disposable environment is worth having.

## In-place edition upgrade: Express → Web

Changing `database_version` from `SQLSERVER_2022_EXPRESS` to `SQLSERVER_2022_WEB` showed in the plan as an **in-place update, not a replacement**. That matters because Cloud SQL instance names can't be reused for about a week after deletion. Cloud SQL ran it as one long `UPDATE` operation (10m49s in total):

1. Pre-upgrade backup (about 1 min)
2. Edition switch with a SQL Server restart. The instance reported `SQLSERVER_2022_WEB` / `RUNNABLE` partway through.
3. Post-upgrade backup
4. Then the Query Insights setting was applied

Watching `gcloud sql operations list --instance=...` during the apply showed each step. That's the Cloud SQL equivalent of watching an Azure SQL scale operation, and the first place to look when Terraform just says "Still modifying...".

After the upgrade, `terraform plan` showed **no changes**: the code and the real instance match.

## Workload test: Query Insights and a missing index

`scripts/python/generate_load.py` builds `dbo.customers` (20k rows) and `dbo.orders` (500k rows) with **no index on `orders.customer_id`**, then runs a weighted mix of six queries from 4 concurrent workers. Two of them are deliberately bad: a missing-index lookup, and a non-sargable `WHERE LOWER(email) = @p`. The run was 5 minutes of load, then `CREATE INDEX`, then another 5 minutes.

Query Store shows the before and after plans for the same query:

| `orders_by_customer` | Before index | After index |
|---|---|---|
| Plan | Clustered Index Scan | Index Seek (`IX_orders_customer_id`) |
| Server avg duration | 129 ms | **0.35 ms** |
| Logical reads per execution | 2,731 | **3** |
| Client-measured avg / p95 | 200 / 451 ms | 76 / 177 ms |
| Total throughput (all queries) | 28.7/s | **37.3/s (+30%)** |

What it shows:

- **Server time and client time measure different things.** After the fix, the query costs 0.35 ms inside SQL Server, but the client still sees about 76 ms. That remainder is the network round trip from the laptop to London through the connector tunnel; even a primary-key lookup costs about 65 ms from the client. Phase 4 SLIs need both views: server-side time shows how healthy the database is, and client-side time shows what users experience.
- **One bad query slows everything.** On a 1-vCPU instance the scans were using most of the CPU. Fixing one query raised total throughput by 30% and made unrelated queries faster too (`revenue_by_region` went from 346 to 261 ms server-side).
- **An index can't fix a non-sargable predicate.** `LOWER(email)` scanned before and after, unchanged at about 110 ms. The fix is rewriting the query, or a persisted computed column with an index on it, not another index.
- **The driver introduced an implicit conversion.** `pytds` sends Python `str` parameters as `NVARCHAR(MAX)`. Comparing that to a `varchar` column puts `CONVERT_IMPLICIT` in the plan, visible in Query Store for both string-parameter queries. It's the same issue as .NET's `SqlCommand.Parameters.AddWithValue`. It's harmless here, but on an indexed varchar column it can turn a seek into a scan. The fix is on the client: declare parameter types explicitly, or match column and parameter types.

**Query Insights vs native tooling.** Insights showed the load, execution counts and rows per query within minutes. The `sredb` rows initially said "Query text is not available", even though the text was in `sys.dm_exec_sql_text` and Query Store. The probable cause is that Insights shows execution metrics before the normalised query text, but the docs don't confirm this. Insights also recorded Cloud SQL's own activity that is normally hidden: SQL Server Agent jobs in `msdb` being set up straight after the Express → Web upgrade, and a `master.dbo.patch_action_execution_state` merge from the patching agent. Takeaway: Insights is good for "what's hot right now" across a fleet, while Query Store and the DMVs are still where you prove *why*, comparing plans before and after.

## Next up

- Destroy at end of session; rebuild from scratch next session to prove the whole stack applies cleanly in one pass.
- **Instance names can't be reused for up to about a week after deletion**, so a fixed name would make next session's rebuild fail with "already exists". The instance name now ends in a `random_id` suffix (`sql-sre-toolkit-euw2-<hex>`), which is new each time the stack is rebuilt and stable while it exists. Scripts take the name from `terraform output sql_connection_name`, so nothing else changes. The Secret Manager secret keeps a fixed name, because secret names are reusable immediately.
- Remaining Phase 1: serverless compute (Cloud Run vs Cloud Functions), log/metric sinks, architecture diagram.
- Consider upgrading to the `hashicorp/google` 6.x provider, which drops `require_ssl`.
