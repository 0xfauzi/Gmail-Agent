variable "project_id" {
  description = "The ID of the Google Cloud project"
  type        = string
}

variable "secrets_project_id" {
  description = "The ID of the secrets manager"
  type = string
}

variable "region" {
  description = "The region to deploy resources to"
  type        = string
  default     = "europe-west2"
}

variable "ai_agent_processor_image" {
  description = "The Docker image for the AI Agent Processor"
  type        = string
}

variable "watcher_service_account_id" {
  description = "Service account ID for the gmail watcher"
  type = string
}

variable "image_tag" {
  description = "The tag of the AI Agent Processor image to deploy"
  type        = string
}