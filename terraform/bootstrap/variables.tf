variable "project_id" {
  description = "GCP project ID."
  type        = string
  default     = "gcp-db-sre-toolkit-514321"
}

variable "region" {
  description = "Default region."
  type        = string
  default     = "europe-west2"
}

variable "github_repository" {
  description = "GitHub repository (owner/name) allowed to federate."
  type        = string
  default     = "craiga251/gcp-db-sre-toolkit"
}

variable "github_repository_id" {
  description = "Numeric GitHub repository ID (gh api repos/OWNER/REPO --jq .id). Pins trust to this exact repo even if the name is reused."
  type        = string
  default     = "1306402255"
}
