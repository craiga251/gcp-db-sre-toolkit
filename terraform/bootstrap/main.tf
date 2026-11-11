# -----------------------------------------------------------------------------
# Bootstrap root: long-lived identity for CI.
#
# Kept separate from the main stack (../) on purpose. The main stack is applied
# and destroyed every session to control cost; CI must still be able to sign in
# and run `terraform plan` while it's destroyed. Everything here is free and
# persists. Separate state (prefix .../bootstrap), so destroying the main stack
# can never touch it.
#
# GitHub Actions --(OIDC token)--> Workload Identity Federation pool/provider
#   --(attribute_condition: this repo only)--> impersonate sa-github-plan
#   --> short-lived Google credentials. No service account keys (blocked by
#   org policy iam.disableServiceAccountKeyCreation anyway).
# -----------------------------------------------------------------------------

terraform {
  required_version = ">= 1.5.0"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
  }

  backend "gcs" {
    bucket = "gcp-db-sre-toolkit-514321-tfstate"
    prefix = "gcp-db-sre-toolkit/bootstrap"
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

data "google_project" "this" {}

locals {
  state_bucket = "gcp-db-sre-toolkit-514321-tfstate"
  # The main stack's admin-password secret. CI needs to read it because
  # refreshing google_secret_manager_secret_version during plan calls
  # AccessSecretVersion. The value is in the state file anyway, which CI can
  # already read.
  sql_secret_name = "projects/${data.google_project.this.number}/secrets/sql-sre-toolkit-euw2-sqlserver-password"
}

resource "google_project_service" "apis" {
  for_each = toset([
    "iam.googleapis.com",
    "iamcredentials.googleapis.com",
    "sts.googleapis.com",
    "cloudresourcemanager.googleapis.com",
  ])

  service            = each.value
  disable_on_destroy = false
}

# --- Workload Identity Federation --------------------------------------------

resource "google_iam_workload_identity_pool" "github" {
  workload_identity_pool_id = "github-actions"
  display_name              = "GitHub Actions"
  description               = "OIDC federation for GitHub Actions workflows"

  depends_on = [google_project_service.apis]
}

resource "google_iam_workload_identity_pool_provider" "github" {
  workload_identity_pool_id          = google_iam_workload_identity_pool.github.workload_identity_pool_id
  workload_identity_pool_provider_id = "github-oidc"
  display_name                       = "GitHub OIDC"

  attribute_mapping = {
    "google.subject"          = "assertion.sub"
    "attribute.repository"    = "assertion.repository"
    "attribute.repository_id" = "assertion.repository_id"
    "attribute.ref"           = "assertion.ref"
    "attribute.event_name"    = "assertion.event_name"
  }

  # Only tokens from this repository are accepted at all. Matching the numeric
  # repository_id as well as the name means a repo deleted and re-created under
  # the same name (by anyone) can't use this trust.
  attribute_condition = "assertion.repository == '${var.github_repository}' && assertion.repository_id == '${var.github_repository_id}'"

  oidc {
    issuer_uri = "https://token.actions.githubusercontent.com"
  }
}

# --- CI identity: plan only --------------------------------------------------

resource "google_service_account" "github_plan" {
  account_id   = "sa-github-plan"
  display_name = "GitHub Actions: terraform plan (read-only)"
}

# Lets workflows from this repo impersonate the plan SA.
resource "google_service_account_iam_member" "github_plan_wif" {
  service_account_id = google_service_account.github_plan.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "principalSet://iam.googleapis.com/${google_iam_workload_identity_pool.github.name}/attribute.repository/${var.github_repository}"
}

# Read everything plan needs to refresh: resource config (viewer) and IAM
# policies on resources (securityReviewer). Neither grants write.
resource "google_project_iam_member" "github_plan_read" {
  for_each = toset([
    "roles/viewer",
    "roles/iam.securityReviewer",
  ])

  project = var.project_id
  role    = each.value
  member  = google_service_account.github_plan.member
}

# Read the one secret the main stack manages, and nothing else. Granted at
# project level with a condition because the secret is created and destroyed
# with the main stack, so a binding on the secret itself wouldn't survive.
resource "google_project_iam_member" "github_plan_secret" {
  project = var.project_id
  role    = "roles/secretmanager.secretAccessor"
  member  = google_service_account.github_plan.member

  condition {
    title       = "sql-admin-secret-only"
    description = "Only the main stack's SQL admin password secret"
    expression  = "resource.name.startsWith(\"${local.sql_secret_name}\")"
  }
}

# Plan takes the state lock, which means writing and deleting a lock object.
# Scoped to the state bucket only.
resource "google_storage_bucket_iam_member" "github_plan_state" {
  bucket = local.state_bucket
  role   = "roles/storage.objectAdmin"
  member = google_service_account.github_plan.member
}
