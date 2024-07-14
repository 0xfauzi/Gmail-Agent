# Provider configuration
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
    "cloudbuild.googleapis.com"
  ])
  project = var.project_id
  service = each.key
  disable_on_destroy = false
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

resource "google_pubsub_topic" "incoming_emails" {
  name                       = "incoming_emails"
  project                    = var.project_id
  message_retention_duration = "604800s"
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
    "roles/gmail.admin",
    "roles/datastore.user"
  ])
  project = var.project_id
  role    = each.key
  member  = "serviceAccount:${google_service_account.gmail_watcher.email}"
}

# Create a secret for storing the service account key
resource "google_secret_manager_secret" "sa_key" {
  secret_id = "email_updates_secret"
  project   = var.project_id
  replication {
  }
  depends_on = [google_project_service.apis]
}

# Store the service account key in the secret
resource "google_secret_manager_secret_version" "sa_key_version" {
  secret      = google_secret_manager_secret.sa_key.id
  secret_data = base64decode(google_service_account_key.gmail_watcher_key.private_key)
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
resource "google_cloudfunctions_function_v2" "gmail_watcher" {
  name        = "gmail-watcher"
  location    = var.region
  description = "Watches Gmail inbox and processes new emails"
  project     = var.project_id

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
  }

  event_trigger {
    trigger_region = var.region
    event_type     = "google.cloud.pubsub.topic.v1.messagePublished"
    pubsub_topic   = google_pubsub_topic.email_updates.id
  }

  environment_variables = {
    PROJECT_ID         = var.project_id
    SECRETS_PROJECT_ID = var.secrets_project_id
    SECRET_ID          = google_secret_manager_secret.sa_key.secret_id
  }

  service_account_email = google_service_account.gmail_watcher.email

  depends_on = [google_project_service.apis]
}

# Deploy the AI Agent Processor as a Cloud Run service
resource "google_cloud_run_service" "ai_agent_processor" {
  name     = "ai-agent-processor"
  location = var.region
  project  = var.project_id

  template {
    spec {
      containers {
        image = var.ai_agent_processor_image
        env {
          name  = "PROJECT_ID"
          value = var.project_id
        }
        env {
          name  = "SECRET_ID"
          value = google_secret_manager_secret.sa_key.secret_id
        }
      }
      service_account_name = google_service_account.gmail_watcher.email
    }
  }

  traffic {
    percent         = 100
    latest_revision = true
  }

  depends_on = [google_project_service.apis]
}

# Update IAM policy for the AI Agent Processor
resource "google_cloud_run_service_iam_member" "ai_agent_processor_invoker" {
  service  = google_cloud_run_service.ai_agent_processor.name
  location = google_cloud_run_service.ai_agent_processor.location
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.gmail_watcher.email}"
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
  name          = "gcf-v2-sources-${var.project_id}-${var.region}"
  location      = var.region
  project       = var.project_id
  force_destroy = false

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