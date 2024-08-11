import os
import base64
from flask import Flask, request
from google.cloud import firestore
from crewai import Agent, Task, Crew
from googleapiclient.discovery import build
from google.oauth2 import service_account
from google.cloud import secretmanager
import json
import logging
from tenacity import retry, stop_after_attempt, wait_exponential
from cloud_logging_helper import setup_logging

app = Flask(__name__)

# Set up logging
logger = setup_logging()

# Initialize Firestore client
db = firestore.Client()

PROJECT_ID = os.environ.get('PROJECT_ID')
SECRET_ID = os.environ.get('SECRET_ID')

def access_secret_version(version_id="latest"):
    client = secretmanager.SecretManagerServiceClient()
    name = f"projects/{PROJECT_ID}/secrets/{SECRET_ID}/versions/{version_id}"
    response = client.access_secret_version(request={"name": name})
    return response.payload.data.decode('UTF-8')

def get_gmail_service(user_email):
    service_account_info = json.loads(access_secret_version())
    credentials = service_account.Credentials.from_service_account_info(
        service_account_info,
        scopes=['https://www.googleapis.com/auth/gmail.send']
    )
    delegated_credentials = credentials.with_subject(user_email)
    return build('gmail', 'v1', credentials=delegated_credentials)

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
def process_email(email_data):
    try:
        logger.info(f"Processing email for user: {email_data['user_email']}")
        
        # Create your AI agents here
        researcher = Agent(
            role='Researcher',
            goal='Research and gather relevant information',
            backstory='You are an AI research assistant'
        )
        writer = Agent(
            role='Writer',
            goal='Write concise and informative responses',
            backstory='You are an AI writing assistant'
        )

        # Define tasks
        research_task = Task(
            description=f"Research information related to: {email_data['subject']}",
            agent=researcher
        )
        write_task = Task(
            description=f"Write a response to the email: {email_data['content']}",
            agent=writer
        )

        # Create and run the crew
        crew = Crew(
            agents=[researcher, writer],
            tasks=[research_task, write_task]
        )
        result = crew.kickoff()

        # Send the response email
        send_email(email_data['user_email'], email_data['from'], email_data['subject'], result)

        # Update Firestore with the result
        db.collection('processed_emails').add({
            'user_email': email_data['user_email'],
            'email_id': email_data['id'],
            'response': result
        })

        logger.info(f"Email processed successfully for user: {email_data['user_email']}")
    except Exception as e:
        logger.error(f"Error processing email: {e}")
        raise

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

def send_email(user_email, to_email, subject, content):
    try:
        service = get_gmail_service(user_email)
        message = create_message(user_email, to_email, subject, content)
        sent_message = service.users().messages().send(userId='me', body=message).execute()
        logger.info(f"Response email sent. Message Id: {sent_message['id']}")
    except Exception as e:
        logger.error(f"An error occurred while sending email: {e}")

@app.route('/', methods=['POST'])
def index():
    envelope = request.get_json()
    if not envelope:
        msg = 'no Pub/Sub message received'
        logger.error(f'error: {msg}')
        return f'Bad Request: {msg}', 400

    if not isinstance(envelope, dict) or 'message' not in envelope:
        msg = 'invalid Pub/Sub message format'
        logger.error(f'error: {msg}')
        return f'Bad Request: {msg}', 400

    pubsub_message = envelope['message']

    if isinstance(pubsub_message, dict) and 'data' in pubsub_message:
        data = json.loads(base64.b64decode(pubsub_message['data']).decode('utf-8'))
        process_email(data)

    return '', 204

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=int(os.environ.get('PORT', 8080)))