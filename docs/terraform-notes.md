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

## Day 1 — (to be filled in once gcloud CLI setup and first `terraform apply` happen)
