terraform {
  required_version = ">= 1.5.0"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.4"
    }
  }

  # Remote state in a GCS bucket bootstrapped out-of-band with gcloud
  # (versioned, uniform bucket-level access, public access prevention enforced).
  # Mirrors the azurerm backend bootstrap in azure-db-sre-toolkit Day 3.
  # GCS backend provides native state locking - no separate lock table needed.
  backend "gcs" {
    bucket = "gcp-db-sre-toolkit-514321-tfstate"
    prefix = "gcp-db-sre-toolkit"
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

locals {
  common_labels = {
    project    = "gcp-db-sre-toolkit"
    managed_by = "terraform"
    owner      = var.owner
  }
}

# -----------------------------------------------------------------------------
# APIs
# disable_on_destroy = false: the stack is destroyed every session, but turning
# APIs off and on again is slow and can break other things in the project.
# -----------------------------------------------------------------------------
resource "google_project_service" "apis" {
  for_each = toset([
    "sqladmin.googleapis.com",
    "secretmanager.googleapis.com",
    "cloudtrace.googleapis.com", # Query Insights uses it for query plans
    # Health check function (health_check.tf)
    "cloudfunctions.googleapis.com",
    "cloudbuild.googleapis.com",
    "run.googleapis.com",
    "artifactregistry.googleapis.com",
    "cloudscheduler.googleapis.com",
  ])

  service            = each.value
  disable_on_destroy = false
}

# -----------------------------------------------------------------------------
# Cloud SQL for SQL Server
# -----------------------------------------------------------------------------
# Cloud SQL reserves a deleted instance's name for up to about a week, so a
# fixed name breaks the apply-verify-destroy-rebuild cycle. A random suffix
# gives each rebuild a fresh name; it stays stable for the life of the stack.
resource "random_id" "sql_suffix" {
  byte_length = 2

  keepers = {
    prefix = var.sql_instance_prefix
  }
}

resource "google_sql_database_instance" "sqlserver" {
  name             = "${var.sql_instance_prefix}-${random_id.sql_suffix.hex}"
  database_version = var.sql_database_version
  region           = var.region

  # Generated, never typed: lives in Secret Manager (below) and in state.
  root_password = random_password.sqlserver_admin.result

  # Terraform-level guard. Off because this stack is applied and destroyed
  # every session to control cost. In a real environment this would be true.
  deletion_protection = false

  settings {
    edition           = "ENTERPRISE" # Cloud SQL edition (not the SQL Server edition)
    tier              = var.sql_tier
    availability_type = "ZONAL" # Regional HA doubles compute cost; not needed for a lab
    disk_type         = "PD_SSD"
    disk_size         = 10
    # Grow rather than fill up and stop accepting writes; capped so cost stays bounded.
    disk_autoresize       = true
    disk_autoresize_limit = 20

    # API-level guard, separate from the Terraform one above.
    deletion_protection_enabled = false

    user_labels = local.common_labels

    ip_configuration {
      # Public IP with no authorized networks: nothing can connect directly.
      # Every connection must come through the Cloud SQL Auth Proxy or a
      # Cloud SQL language connector, which authenticate with IAM and
      # encrypt the connection. See Day 2 notes for why not private IP.
      ipv4_enabled = true
      ssl_mode     = "ENCRYPTED_ONLY"
      # Provider 5.x sends require_ssl=false unless set, which the API rejects
      # alongside ENCRYPTED_ONLY. Deprecated field, but must agree with ssl_mode.
      require_ssl = true
    }

    backup_configuration {
      enabled    = true
      start_time = "02:00" # UTC

      backup_retention_settings {
        retained_backups = 7
      }
    }

    maintenance_window {
      day          = 7 # Sunday
      hour         = 3 # UTC
      update_track = "stable"
    }

    # Query Insights: not supported on SQL Server Express (the reason this
    # instance runs Web edition), and needs disk_autoresize = true.
    insights_config {
      query_insights_enabled = true
    }
  }

  depends_on = [google_project_service.apis]
}

# -----------------------------------------------------------------------------
# Admin credential
# -----------------------------------------------------------------------------
resource "random_password" "sqlserver_admin" {
  length           = 24
  special          = true
  override_special = "!#%*-_=+"
}

resource "google_secret_manager_secret" "sqlserver_admin" {
  # Secret names are reusable immediately, so no suffix needed here.
  secret_id = "${var.sql_instance_prefix}-sqlserver-password"
  labels    = local.common_labels

  replication {
    user_managed {
      replicas {
        location = var.region
      }
    }
  }

  depends_on = [google_project_service.apis]
}

resource "google_secret_manager_secret_version" "sqlserver_admin" {
  secret      = google_secret_manager_secret.sqlserver_admin.id
  secret_data = random_password.sqlserver_admin.result
}

# -----------------------------------------------------------------------------
# Application database
# -----------------------------------------------------------------------------
resource "google_sql_database" "app" {
  name     = var.sql_database_name
  instance = google_sql_database_instance.sqlserver.name
}
