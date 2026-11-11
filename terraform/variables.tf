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

variable "sql_instance_prefix" {
  description = "Cloud SQL instance name prefix. A random suffix is appended because Cloud SQL reserves deleted instance names for up to about a week."
  type        = string
  default     = "sql-sre-toolkit-euw2"
}

variable "sql_database_version" {
  description = "Cloud SQL SQL Server version. Web is the cheapest edition that supports Query Insights and SQL Server Agent (Express has neither)."
  type        = string
  default     = "SQLSERVER_2022_WEB"
}

variable "sql_tier" {
  description = "Machine type, db-custom-<vCPUs>-<memory MB>. Smallest viable for SQL Server Express."
  type        = string
  default     = "db-custom-1-3840"
}

variable "sql_database_name" {
  description = "Name of the application database created on the instance."
  type        = string
  default     = "sredb"
}
