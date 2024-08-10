provider "google" {
  project = var.project_id
  region  = var.region
}

# Enable required APIs
resource "google_project_service" "apis" {
  for_each = toset([
    "gmail.googleapis.com",
    "pubsub.googleapis.com",
    "secretmanager.googleapis.com",
    "cloudfunctions.googleapis.com",
    "run.googleapis.com",
    "firestore.googleapis.com",
    "artifactregistry.googleapis.com",
    "cloudtrace.googleapis.com",
    "monitoring.googleapis.com",
    "logging.googleapis.com",
    "cloudresourcemanager.googleapis.com",
    "servicemanagement.googleapis.com",
    "serviceusage.googleapis.com",
    "storage.googleapis.com",
    "cloudbuild.googleapis.com",
    "cloudscheduler.googleapis.com"
  ])
  project = var.project_id
  service = each.key
  disable_on_destroy = false
  disable_dependent_services = true
  timeouts {
    create = "30m"
    update = "40m"
  }
}

# Create Pub/Sub topics
resource "google_pubsub_topic" "email_updates" {
  name    = "email_updates"
  project = var.project_id
}

resource "google_pubsub_topic" "parsed_emails" {
  name    = "parsed_emails"
  project = var.project_id
}

# Create Pub/Sub subscriptions
resource "google_pubsub_subscription" "parsed_emails_sub" {
  name                       = "parsed_emails-sub"
  topic                      = google_pubsub_topic.parsed_emails.name
  project                    = var.project_id
  ack_deadline_seconds       = 10
  message_retention_duration = "604800s"
  expiration_policy {
    ttl = "2678400s"
  }
}

resource "google_pubsub_subscription" "email_updates_sub" {
  name                       = "email_updates-sub"
  topic                      = google_pubsub_topic.email_updates.name
  project                    = var.project_id
  ack_deadline_seconds       = 10
  message_retention_duration = "604800s"
  expiration_policy {
    ttl = "2678400s"
  }
}

# Create service account
resource "google_service_account" "gmail_watcher" {
  account_id   = var.watcher_service_account_id
  display_name = "Gmail Watcher Service Account"
  project      = var.project_id
}

# Grant necessary roles to the service account
resource "google_project_iam_member" "service_account_roles" {
  for_each = toset([
    "roles/secretmanager.secretAccessor",
    "roles/pubsub.publisher",
    "roles/pubsub.subscriber",
    "roles/datastore.user",
    "roles/logging.logWriter"
  ])
  project = var.project_id
  role    = each.key
  member  = "serviceAccount:${google_service_account.gmail_watcher.email}"
}


# Create a secret for storing the service account key
resource "google_secret_manager_secret" "email_updates_secret" {
  secret_id = "email_updates_secret"
  project   = var.project_id
  replication {
    auto {}
  }

  depends_on = [google_project_service.apis]
}

data "google_secret_manager_secret_version" "email_updates_secret" {
  project = var.secrets_project_id
  secret  = "email_updates_secret"
  version = "latest"
}

# Store the service account key in the secret
resource "google_secret_manager_secret_version" "email_updates_secret_version" {
  secret      = google_secret_manager_secret.email_updates_secret.id
  secret_data = data.google_secret_manager_secret_version.email_updates_secret.secret_data
}

# Generate a key for the service account
resource "google_service_account_key" "gmail_watcher_key" {
  service_account_id = google_service_account.gmail_watcher.name
}

# Create a Cloud Storage bucket for the function source code
resource "google_storage_bucket" "function_bucket" {
  name     = "${var.project_id}-function-source"
  location = var.region
  project  = var.project_id
}

# Create a zip of the function source code
data "archive_file" "function_source" {
  type        = "zip"
  source_dir  = "${path.module}/../src/gmail_watcher"
  output_path = "${path.module}/function.zip"
}

# Upload the function source code to the bucket
resource "google_storage_bucket_object" "function_source" {
  name   = "function-${data.archive_file.function_source.output_md5}.zip"
  bucket = google_storage_bucket.function_bucket.name
  source = data.archive_file.function_source.output_path
}

# Deploy the Cloud Function
resource "google_cloudfunctions2_function" "gmail_watcher" {
  name        = "email_updates_fn"
  location    = var.region
  description = "Watches Gmail inbox and processes new emails"

  build_config {
    runtime     = "python39"
    entry_point = "pubsub_push"
    source {
      storage_source {
        bucket = google_storage_bucket.function_bucket.name
        object = google_storage_bucket_object.function_source.name
      }
    }
  }

  service_config {
    max_instance_count = 1
    available_memory   = "256M"
    timeout_seconds    = 60
    environment_variables = {
      PROJECT_ID         = var.project_id
      SECRETS_PROJECT_ID = var.project_id
      SECRET_ID          = google_secret_manager_secret.email_updates_secret.secret_id
      PULL_TOPIC_NAME    = google_pubsub_topic.email_updates.id
      PUSH_TOPIC_NAME    = google_pubsub_topic.parsed_emails.id
    }
    service_account_email = google_service_account.gmail_watcher.email
  }

  event_trigger {
    trigger_region = var.region
    event_type     = "google.cloud.pubsub.topic.v1.messagePublished"
    pubsub_topic   = google_pubsub_topic.email_updates.id
  }

  depends_on = [google_project_service.apis]
}

# Update IAM policy for the AI Agent Processor
resource "google_cloud_run_service" "ai_agent_processor" {
  name     = "ai-agent-fn"
  location = var.region
  project  = var.project_id

  template {
    spec {
      containers {
        image = "${var.region}-docker.pkg.dev/${var.project_id}/ai-agent-processor/ai-agent-processor:${var.image_tag}"        
        env {
          name  = "LOG_EXECUTION_ID"
          value = "true"
        }
        env {
          name  = "PROJECT_ID"
          value = var.project_id
        }
        env {
          name  = "SECRETS_PROJECT_ID"
          value = var.project_id
        }
        env {
          name  = "SECRET_ID"
          value = "email_updates_secret"
        }    
        ports {
          container_port = 8080
          name           = "http1"
        }
        
        resources {
          limits = {
            cpu    = "1"
            memory = "512Mi"
          }
        }
      }
      
      container_concurrency = 1
      timeout_seconds       = 60
      service_account_name  = google_service_account.gmail_watcher.email
    }
    
    metadata {
      annotations = {
        "autoscaling.knative.dev/maxScale"                        = "1"
        "cloudfunctions.googleapis.com/trigger-type"              = "google.cloud.pubsub.topic.v1.messagePublished"
        "run.googleapis.com/client-name"                          = "console-cloud"
        "run.googleapis.com/startup-cpu-boost"                    = "true"
      }
      labels = {
        "run.googleapis.com/startupProbeType" = "Default"
      }
    }
  }

  traffic {
    percent         = 100
    latest_revision = true
  }

  metadata {
    annotations = {
      "run.googleapis.com/ingress"         = "all"
      "run.googleapis.com/ingress-status"  = "all"
    }
    labels = {
      "cloud.googleapis.com/location"       = var.region
      "goog-cloudfunctions-runtime"         = "python39"
      "goog-managed-by"                     = "cloudfunctions"
      "run.googleapis.com/satisfiesPzs"     = "true"
    }
  }

  lifecycle {
    ignore_changes = [
      metadata.0.annotations["run.googleapis.com/operation-id"],
      metadata.0.annotations["serving.knative.dev/creator"],
      metadata.0.annotations["serving.knative.dev/lastModifier"],
      metadata.0.annotations["client.knative.dev/user-image"],
      metadata.0.annotations["run.googleapis.com/client-name"],
      metadata.0.annotations["run.googleapis.com/client-version"],
      template.0.metadata.0.annotations["client.knative.dev/user-image"],
      template.0.metadata.0.annotations["run.googleapis.com/client-name"],
      template.0.metadata.0.annotations["run.googleapis.com/client-version"],
      template.0.metadata.0.name,
      template.0.spec.0.containers.0.image,
    ]
  }
}

# Create a Pub/Sub subscription for the AI Agent Processor
resource "google_pubsub_subscription" "ai_agent_processor_subscription" {
  name  = "ai-agent-processor-subscription"
  topic = google_pubsub_topic.parsed_emails.name
  project = var.project_id

  push_config {
    push_endpoint = google_cloud_run_service.ai_agent_processor.status[0].url
    oidc_token {
      service_account_email = google_service_account.gmail_watcher.email
    }
  }

  depends_on = [google_cloud_run_service.ai_agent_processor]
}

# Create Firestore database
resource "google_firestore_database" "database" {
  project     = var.project_id
  name        = "(default)"
  location_id = var.region
  type        = "FIRESTORE_NATIVE"

  depends_on = [google_project_service.apis]
}

# Create Artifact Registry repository
resource "google_artifact_registry_repository" "gcf_artifacts" {
  location      = var.region
  repository_id = "gcf-artifacts"
  description   = "This repository is created and used by Cloud Functions for storing function docker images."
  format        = "DOCKER"
  project       = var.project_id

  labels = {
    goog-managed-by = "cloudfunctions"
  }
}

# Create Cloud Storage buckets
resource "google_storage_bucket" "gcf_v2_uploads" {
  name          = "gcf-v2-uploads-${var.project_id}-${var.region}"
  location      = var.region
  project       = var.project_id
  force_destroy = false

  uniform_bucket_level_access = true

  lifecycle_rule {
    condition {
      age = 1
    }
    action {
      type = "Delete"
    }
  }

  labels = {
    goog-managed-by = "cloudfunctions"
  }
}

resource "google_storage_bucket" "gcf_v2_sources" {
  name          = "gcf-v2-sources-99383323365-europe-west2"
  location      = var.region
  project       = var.project_id
  force_destroy = true

  uniform_bucket_level_access = true

  versioning {
    enabled = true
  }

  lifecycle_rule {
    condition {
      num_newer_versions = 3
    }
    action {
      type = "Delete"
    }
  }

  labels = {
    goog-managed-by = "cloudfunctions"
  }
}

resource "google_artifact_registry_repository" "watcher_renewal" {
  location      = var.region
  repository_id = "watcher-renewal"
  description   = "Docker repository for watcher renewal images"
  format        = "DOCKER"
  project       = var.project_id
}


resource "google_cloud_run_v2_job" "watcher_renewal_job" {
  name     = "watcher-renewal-job"
  location = var.region

  template {
    template {
      containers {
        image = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.watcher_renewal.repository_id}/watcher-renewal:latest"
        
        env {
          name  = "PROJECT_ID"
          value = var.project_id
        }
        env {
          name  = "SECRETS_PROJECT_ID"
          value = var.secrets_project_id
        }
        env {
          name  = "SECRET_ID"
          value = google_secret_manager_secret.email_updates_secret.secret_id
        }
        env {
          name  = "USER_EMAIL"
          value = "fauzi@0xfauzi.com"
        }
      }
      
      service_account = google_service_account.gmail_watcher.email
    }
  }

  depends_on = [google_artifact_registry_repository.watcher_renewal]
}

resource "google_cloud_scheduler_job" "run_watcher_renewal_job" {
  name             = "run-watcher-renewal-job"
  description      = "Triggers the watcher renewal Cloud Run job"
  schedule         = "0 */6 * * *"  # Run every 6 hours
  time_zone        = "UTC"
  attempt_deadline = "320s"

  http_target {
    http_method = "POST"
    uri         = "https://${var.region}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${var.project_id}/jobs/watcher-renewal-job:run"
    
    oauth_token {
      service_account_email = google_service_account.gmail_watcher.email
    }
  }
}