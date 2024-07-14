# AI Email Assistant

This project implements an AI-powered email assistant that automatically processes incoming emails, generates responses using AI agents, and sends replies. The system is built on Google Cloud Platform (GCP) and uses various GCP services for scalability and reliability.

## Architecture

The system consists of the following components:

1. Gmail Watcher: A Cloud Function that monitors a Gmail inbox for new emails.
2. AI Agent Processor: A Cloud Run service that processes emails using AI agents.
3. Pub/Sub Topics: For message passing between components.
4. Firestore: For storing processed email data.
5. Secret Manager: For securely storing sensitive information.

## Flow Diagram
<antArtifact identifier="flow-diagram" type="application/vnd.ant.mermaid" title="AI Email Assistant Flow Diagram">
graph TD
    A[Gmail Inbox] -->|New Email| B(Gmail Watcher Cloud Function)
    B -->|Extract & Process| C{Pub/Sub: email-processing topic}
    C -->|Push| D[AI Agent Processor Cloud Run Service]
    D -->|Generate Response| E[CrewAI Agents]
    E -->|Return Response| D
    D -->|Send Reply| A
    D -->|Store Result| F[(Firestore)]

## Prerequisites

- A Google Cloud Platform account
- A Gmail account (for the monitored inbox)
- Terraform 0.14+
- Google Cloud SDK
- Docker

## Setup

1. Clone this repository
2. Update `terraform.tfvars` with your project ID and region
3. Set up Google Cloud authentication:
   ```
   gcloud auth application-default login
   ```
4. Build and push the AI Agent Processor Docker image:
   ```
   docker build -t gcr.io/your-project-id/ai-agent-processor:latest .
   docker push gcr.io/your-project-id/ai-agent-processor:latest
   ```
5. Initialize Terraform:
   ```
   terraform init
   ```
6. Apply the Terraform configuration:
   ```
   terraform apply
   ```

## Post-Deployment Steps

1. Set up domain-wide delegation for the service account in your Google Workspace admin console.
2. Manually trigger the Gmail Watcher function once to set up the initial Gmail watch.

## CI/CD

This project uses GitHub Actions for CI/CD. On push to the main branch, it automatically:

1. Builds and pushes the Docker image
2. Runs Terraform to update the infrastructure

To set this up, add the following secrets to your GitHub repository:
- `GCP_PROJECT_ID`: Your Google Cloud project ID
- `GCP_SA_KEY`: The JSON key of a service account with necessary permissions

## Local Development

To run the AI Agent Processor locally:

1. Set up environment variables:
   ```
   export PROJECT_ID=your-project-id
   export SERVICE_ACCOUNT_SECRET_ID=email_updates_secret
   ```
2. Run the Flask app:
   ```
   python app.py
   ```

## Testing

To test the system:

1. Send an email to the monitored Gmail account.
2. Check the Cloud Function logs to ensure the email was processed.
3. Verify that a response was sent back to the original sender.

## Monitoring

- Use Cloud Monitoring to set up dashboards and alerts for the Cloud Function, Cloud Run service, and Pub/Sub topics.
- Check Firestore for records of processed emails.

## Troubleshooting

- If emails are not being processed, check the Gmail Watcher Cloud Function logs.
- If AI responses are not being generated, check the AI Agent Processor Cloud Run logs.
- Ensure all necessary APIs are enabled in your Google Cloud project.

## Contributing

Please read CONTRIBUTING.md for details on our code of conduct and the process for submitting pull requests.

## License

This project is licensed under the MIT License - see the LICENSE.md file for details.