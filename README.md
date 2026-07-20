# GCP Database SRE Toolkit

A practical toolkit demonstrating Site Reliability Engineering practices applied to database operations on Google Cloud. Built to showcase modern SRE skills — Infrastructure as Code, observability, automation, and AI-augmented engineering — combined with deep database operational experience.

## Why This Project

This is the GCP counterpart to [`azure-db-sre-toolkit`](https://github.com/craiga251/azure-db-sre-toolkit), which covered the same ground on Azure. The move to GCP followed the Azure free trial expiring while a 60-day GCP credit was still available — rather than let that runway go unused, this repo applies the same IaC discipline (remote state, plan/apply review, DRY, tagging/labeling) to Google Cloud's platform and IAM model.

Terraform fundamentals (providers, state, plan vs apply) are not re-explained here — see the Azure repo's `docs/terraform-notes.md` Day 1 entry for that groundwork. This repo's notes focus on what's actually different on GCP: resource hierarchy, IAM, and service-specific configuration.

## Architecture

> _Architecture diagram to be added during Phase 1._

## Tech Stack

- **Cloud:** Google Cloud Platform (free trial credit)
- **Infrastructure as Code:** Terraform
- **CI/CD:** GitHub Actions
- **Compute:** Cloud Run / Cloud Functions (serverless — TBD during Phase 1)
- **Database:** Cloud SQL for SQL Server
- **Observability:** Cloud Monitoring, Cloud Logging, Grafana Cloud
- **Scripting:** PowerShell, Python
- **AI tooling:** GitHub Copilot, LLM APIs for log analysis

## Project Status

| Phase | Status | Description |
|-------|--------|-------------|
| 0 | 🟡 In progress | Foundations and tooling setup (gcloud CLI, project, Terraform provider) |
| 1 | ⬜ Not started | Terraform infrastructure provisioning |
| 2 | ⬜ Not started | Git workflow and CI/CD |
| 3 | ⬜ Not started | SRE automation scripts |
| 4 | ⬜ Not started | Observability and SLIs |
| 5 | ⬜ Not started | AI-augmented operations |
| 6 | ⬜ Not started | Documentation and publishing |

## Repository Structure

```
gcp-db-sre-toolkit/
├── terraform/              # Infrastructure as Code (Phase 1)
│   ├── main.tf
│   ├── variables.tf
│   ├── outputs.tf
│   └── terraform.tfvars.example
├── scripts/
│   ├── powershell/         # PowerShell automation scripts (Phase 3)
│   └── python/             # Python automation scripts (Phase 3)
├── .github/
│   └── workflows/          # GitHub Actions CI/CD pipelines (Phase 2)
├── docs/
│   └── terraform-notes.md  # Design decisions and reflections
├── README.md
└── .gitignore
```

## Prerequisites

- Google Cloud account with billing/trial credit active
- `gcloud` CLI installed and authenticated (`gcloud auth login`)
- A GCP project created for this toolkit (`gcloud projects create ...`)
- Terraform CLI (>= 1.5)
- Git and GitHub account
- VS Code with Terraform and PowerShell extensions
- Python 3.10+
- PowerShell 7+

## Getting Started

> _Full setup instructions will be expanded once Phase 0/1 (project setup and infrastructure provisioning) are complete._

**Current state:** Phase 0 in progress. No infrastructure provisioned yet.

Planned bootstrap sequence (mirroring the Azure repo's Day 3 pattern):

1. Clone this repository
2. Authenticate: `gcloud auth login` and `gcloud auth application-default login`
3. Create or select a GCP project and note its project ID
4. Bootstrap a GCS bucket for Terraform remote state (out-of-band, before first `terraform init`)
5. In the `terraform/` folder, copy `terraform.tfvars.example` to `terraform.tfvars` and set `project_id` and `owner`
6. Run `terraform init`, `terraform plan`, then `terraform apply`

## Infrastructure Provisioned

Nothing yet — Phase 0 (tooling and project setup) is in progress.

## Design Decisions

Key architectural and tooling decisions are documented as they are made in [`docs/terraform-notes.md`](docs/terraform-notes.md), including where GCP's approach diverges from the Azure repo's.

## What I Learned

Reflections captured per phase in [`docs/terraform-notes.md`](docs/terraform-notes.md), focused on what's genuinely new versus what carried over from the Azure project.

## License

MIT
