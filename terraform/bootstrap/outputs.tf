output "workload_identity_provider" {
  description = "Full provider resource name, for google-github-actions/auth (repo variable GCP_WIF_PROVIDER)."
  value       = google_iam_workload_identity_pool_provider.github.name
}

output "plan_service_account" {
  description = "Service account the plan workflow impersonates (repo variable GCP_PLAN_SA)."
  value       = google_service_account.github_plan.email
}
