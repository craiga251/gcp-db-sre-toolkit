terraform {
  required_version = ">= 1.5.0"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
  }

  # Remote state backend to be added once the GCS bootstrap bucket exists
  # (mirrors the azurerm backend bootstrap in azure-db-sre-toolkit Day 3).
  #
  # backend "gcs" {
  #   bucket = "<bootstrap-bucket-name>"
  #   prefix = "gcp-db-sre-toolkit"
  # }
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
