variable "project_id" {
  description = "The ID of the Google Cloud project"
  type        = string
  default     = "research-assistant-424819"
}

variable "region" {
  description = "The region to deploy resources to"
  type        = string
  default     = "europe-west2"
}

variable "image_tag" {
  description = "The tag of the Docker image to deploy"
  type        = string
}

variable "secrets_project_id" {
  description = "The ID of the project containing secrets"
  type        = string
  default     = "99383323365"
}

variable "ai_agent_processor_image" {
  description = "The full image name of the AI agent processor"
  type        = string
}

variable "watcher_service_account_id" {
  description = "The ID of the service account for the Gmail watcher"
  type        = string
  default     = "service-99383323365"
}