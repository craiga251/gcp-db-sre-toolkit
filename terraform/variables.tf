variable "project_id" {
  description = "GCP project ID that this configuration deploys into. Set via terraform.tfvars (gitignored)."
  type        = string
}

variable "region" {
  description = "GCP region for created resources."
  type        = string
  default     = "europe-west2" # London
}

variable "owner" {
  description = "Owner label value for created resources. Set via terraform.tfvars (gitignored)."
  type        = string
}
