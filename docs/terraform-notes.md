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
