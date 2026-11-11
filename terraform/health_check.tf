# -----------------------------------------------------------------------------
# Scheduled database health check
#
# Cloud Scheduler --(OIDC token)--> Cloud Function (gen2, Python)
#                                     --(Cloud SQL connector, IAM + TLS)--> SQL Server
#                                     --(structured JSON on stdout)--> Cloud Logging
#
# The GCP equivalent of the Azure repo's Azure Functions + storage account.
# Three service accounts, each with only what its job needs:
#   sa-db-health-check   runtime identity: connect to Cloud SQL, read one secret
#   sa-function-build    builds the function image (default build SAs get no
#                        roles here: iam.automaticIamGrantsForDefaultServiceAccounts)
#   sa-scheduler-invoker the identity granted permission to call the function
# -----------------------------------------------------------------------------

locals {
  health_check_name = "db-health-check"
  health_check_src  = "${path.module}/../functions/db_health_check"
}

# --- Service accounts --------------------------------------------------------

resource "google_service_account" "health_check" {
  account_id   = "sa-db-health-check"
  display_name = "DB health check function (runtime)"
}

resource "google_service_account" "function_build" {
  account_id   = "sa-function-build"
  display_name = "Cloud Functions build"
}

resource "google_service_account" "scheduler" {
  account_id   = "sa-scheduler-invoker"
  display_name = "Cloud Scheduler invoker for the DB health check"
}

# Runtime: connect through the Cloud SQL connector (also covers instances.get,
# used to fetch the server CA), and read only the admin password secret.
resource "google_project_iam_member" "health_check_sql_client" {
  project = var.project_id
  role    = "roles/cloudsql.client"
  member  = google_service_account.health_check.member
}

resource "google_secret_manager_secret_iam_member" "health_check_secret" {
  secret_id = google_secret_manager_secret.sqlserver_admin.id
  role      = "roles/secretmanager.secretAccessor"
  member    = google_service_account.health_check.member
}

# Build: Cloud Build needs to write logs, read the source zip, and push the image.
resource "google_project_iam_member" "function_build" {
  project = var.project_id
  role    = "roles/cloudbuild.builds.builder"
  member  = google_service_account.function_build.member
}

# --- Source and image storage ------------------------------------------------

# The "storage account" equivalent: holds the zipped function source.
resource "google_storage_bucket" "function_source" {
  name                        = "${var.project_id}-function-source"
  location                    = var.region
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  force_destroy               = true # destroyed every session along with its objects
  labels                      = local.common_labels

  depends_on = [google_project_service.apis]
}

data "archive_file" "health_check" {
  type        = "zip"
  source_dir  = local.health_check_src
  output_path = "${path.module}/.build/${local.health_check_name}.zip"
  excludes    = ["__pycache__", ".venv"]
}

# Object name includes the hash, so a code change forces a redeploy.
resource "google_storage_bucket_object" "health_check_source" {
  name   = "${local.health_check_name}-${data.archive_file.health_check.output_md5}.zip"
  bucket = google_storage_bucket.function_source.name
  source = data.archive_file.health_check.output_path
}

# Managed here (rather than the auto-created gcf-artifacts repo) so that
# terraform destroy removes the built images too.
resource "google_artifact_registry_repository" "functions" {
  repository_id = "cloud-functions"
  location      = var.region
  format        = "DOCKER"
  description   = "Built images for Cloud Functions in this toolkit"
  labels        = local.common_labels

  cleanup_policies {
    id     = "keep-latest-3"
    action = "KEEP"
    most_recent_versions {
      keep_count = 3
    }
  }

  depends_on = [google_project_service.apis]
}

# --- Function ----------------------------------------------------------------

resource "google_cloudfunctions2_function" "health_check" {
  name     = local.health_check_name
  location = var.region
  labels   = local.common_labels

  build_config {
    runtime           = "python312"
    entry_point       = "health_check"
    service_account   = google_service_account.function_build.id
    docker_repository = google_artifact_registry_repository.functions.id

    source {
      storage_source {
        bucket = google_storage_bucket.function_source.name
        object = google_storage_bucket_object.health_check_source.name
      }
    }
  }

  service_config {
    available_memory      = "512M"
    timeout_seconds       = 60
    min_instance_count    = 0 # scale to zero between runs
    max_instance_count    = 1
    ingress_settings      = "ALLOW_ALL" # Cloud Scheduler calls over the internet; IAM still required
    service_account_email = google_service_account.health_check.email

    environment_variables = {
      INSTANCE_CONNECTION_NAME = google_sql_database_instance.sqlserver.connection_name
      DB_NAME                  = google_sql_database.app.name
      DB_USER                  = "sqlserver"
    }

    # The platform reads the secret at start-up using the runtime SA; the
    # password never appears in Terraform config, env var listings, or code.
    secret_environment_variables {
      key        = "DB_PASSWORD"
      project_id = var.project_id
      secret     = google_secret_manager_secret.sqlserver_admin.secret_id
      version    = "latest"
    }
  }

  depends_on = [
    google_project_iam_member.function_build,
    google_project_iam_member.health_check_sql_client,
    google_secret_manager_secret_iam_member.health_check_secret,
    google_secret_manager_secret_version.sqlserver_admin,
  ]
}

# No allUsers binding: anonymous calls get 403. The scheduler SA is the only
# identity granted invoker explicitly. Project Owners/Editors can also invoke,
# because their broad roles include run.routes.invoke (tested: owner gets 200).
resource "google_cloud_run_service_iam_member" "scheduler_invoker" {
  location = var.region
  service  = google_cloudfunctions2_function.health_check.name
  role     = "roles/run.invoker"
  member   = google_service_account.scheduler.member
}

# --- Schedule ----------------------------------------------------------------

resource "google_cloud_scheduler_job" "health_check" {
  name             = "${local.health_check_name}-every-5m"
  region           = var.region
  description      = "Runs the DB health check every 5 minutes"
  schedule         = "*/5 * * * *"
  time_zone        = "Etc/UTC"
  attempt_deadline = "90s"

  # No retries: a failed check is a data point, not something to retry. That's
  # the API default (retry_count = 0); setting it explicitly causes a permanent
  # plan diff because the API omits zero values from its response.

  http_target {
    http_method = "POST"
    uri         = google_cloudfunctions2_function.health_check.service_config[0].uri

    oidc_token {
      service_account_email = google_service_account.scheduler.email
      audience              = google_cloudfunctions2_function.health_check.service_config[0].uri
    }
  }

  depends_on = [google_cloud_run_service_iam_member.scheduler_invoker]
}
