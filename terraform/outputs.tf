output "gmail_watcher_function_name" {
  value       = google_cloudfunctions_function_v2.gmail_watcher.name
  description = "The name of the deployed Gmail Watcher Cloud Function"
}

output "ai_agent_processor_url" {
  value       = google_cloud_run_service.ai_agent_processor.status[0].url
  description = "The URL of the deployed AI Agent Processor Cloud Run service"
}

output "service_account_email" {
  value       = google_service_account.gmail_watcher.email
  description = "The email of the created service account"
}

output "gmail_updates_topic" {
  value       = google_pubsub_topic.gmail_updates.name
  description = "The name of the Pub/Sub topic for Gmail updates"
}

output "email_processing_topic" {
  value       = google_pubsub_topic.email_processing.name
  description = "The name of the Pub/Sub topic for email processing"
}