output "sql_instance_name" {
  description = "Cloud SQL instance name."
  value       = google_sql_database_instance.sqlserver.name
}

output "sql_connection_name" {
  description = "Instance connection name (project:region:instance), used by the Cloud SQL Auth Proxy and connectors."
  value       = google_sql_database_instance.sqlserver.connection_name
}

output "sql_public_ip" {
  description = "Public IP. Not directly reachable: no authorized networks are configured."
  value       = google_sql_database_instance.sqlserver.public_ip_address
}

output "sql_admin_secret_id" {
  description = "Secret Manager secret holding the sqlserver admin password."
  value       = google_secret_manager_secret.sqlserver_admin.secret_id
}
