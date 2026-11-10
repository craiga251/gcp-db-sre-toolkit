terraform {
  required_version = ">= 1.5.0"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
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

# Phase 1 resources go here.
