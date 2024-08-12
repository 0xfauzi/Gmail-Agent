import os
import base64
from flask import Flask, request, jsonify
from google.cloud import firestore
from googleapiclient.discovery import build
from google.oauth2 import service_account
from google.cloud import secretmanager
import json
import sys
from cloud_logging_helper import setup_logging
from crews.ai_research_crew.research_crew import AIResearchCrew

app = Flask(__name__)

# Set up logging
logger = setup_logging()

# Initialize Firestore client
db = firestore.Client()

PROJECT_ID = os.environ.get('PROJECT_ID')
SECRET_ID = os.environ.get('SECRET_ID')

def access_secret_version(secret_id, version_id="latest"):
    client = secretmanager.SecretManagerServiceClient()
    name = f"projects/{PROJECT_ID}/secrets/{secret_id}/versions/{version_id}"
    response = client.access_secret_version(request={"name": name})
    return response.payload.data.decode('UTF-8')

OPENAI_API_KEY = access_secret_version('OPENAI_API_KEY')
ANTHROPIC_API_KEY = access_secret_version('ANTHROPIC_API_KEY')


def get_gmail_service(user_email):
    service_account_info = json.loads(access_secret_version(SECRET_ID))
    credentials = service_account.Credentials.from_service_account_info(
        service_account_info,
        scopes=['https://www.googleapis.com/auth/gmail.send']
    )
    delegated_credentials = credentials.with_subject(user_email)
    return build('gmail', 'v1', credentials=delegated_credentials)

@app.route('/health', methods=['GET'])
def health_check():
    logger.info("Health check called")
    return jsonify({"status": "healthy"}), 200

@app.route('/', methods=['POST'])
def process_email():
    print("Function started", file=sys.stderr)
    logger.info("Function started")
    try:
        envelope = request.get_json()
        if not envelope:
            msg = "no Pub/Sub message received"
            logger.error(f"error: {msg}")
            return f"Bad Request: {msg}", 400

        if not isinstance(envelope, dict) or "message" not in envelope:
            msg = "invalid Pub/Sub message format"
            logger.error(f"error: {msg}")
            return f"Bad Request: {msg}", 400

        pubsub_message = envelope["message"]

        if isinstance(pubsub_message, dict) and "data" in pubsub_message:
            data = base64.b64decode(pubsub_message["data"]).decode("utf-8").strip()
            logger.info(f"Received message: {data}")
            
            # Process the email data
            process_email_data(json.loads(data))
            
            return ("", 204)
        else:
            msg = "invalid Pub/Sub message format"
            logger.error(f"error: {msg}")
            return f"Bad Request: {msg}", 400

    except Exception as e:
        logger.exception(f"Error processing request: {str(e)}")
        return "Internal Server Error", 500

def process_email_data(email_data):
    try:
        logger.info(f"Processing email for user: {email_data['user_email']}")
        
        # Ensure all required fields are present
        required_fields = ['subject', 'body', 'from', 'user_email', 'id']
        for field in required_fields:
            if field not in email_data:
                raise ValueError(f"Missing required field: {field}")

        # Create the AIResearchCrew instance with the email details
        crew = AIResearchCrew(
            email_subject=email_data['subject'],
            email_body=email_data['body'],
            email_from=email_data['from']
        )
        result = crew.run()
        logger.info(f"Result: {result}")
        result_content = result.tasks_output[2].research_report # Index 2 is the rewrite_the_report task

        # Send the response email
        send_email(email_data['user_email'], email_data['from'], email_data['subject'], result_content)

        # Update Firestore with the result
        db.collection('processed_emails').add({
            'user_email': email_data['user_email'],
            'email_id': email_data['id'],
            'subject': email_data['subject'],
            'from': email_data['from'],
            'response': result_content
        })

        logger.info(f"Email processed successfully for user: {email_data['user_email']}")
    except Exception as e:
        logger.error(f"Error processing email: {e}")
        raise

def send_email(user_email, to_email, subject, content):
    try:
        service = get_gmail_service(user_email)
        message = create_message(user_email, to_email, subject, content)
        sent_message = service.users().messages().send(userId='me', body=message).execute()
        logger.info(f"Response email sent. Message Id: {sent_message['id']}")
    except Exception as e:
        logger.error(f"An error occurred while sending email: {e}")

def create_message(sender, to, subject, message_text):
    message = {
        'raw': base64.urlsafe_b64encode(
            f"From: {sender}\n"
            f"To: {to}\n"
            f"Subject: Re: {subject}\n\n"
            f"{message_text}".encode('utf-8')
        ).decode('utf-8')
    }
    return message

if __name__ == '__main__':
    logger.info("Application starting...")
    app.run(debug=True, host='0.0.0.0', port=int(os.environ.get('PORT', 8080)))