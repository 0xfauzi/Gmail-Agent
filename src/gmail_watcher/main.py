import base64
import re
import html
import json
from google.cloud import pubsub_v1
from googleapiclient.discovery import build
from google.oauth2 import service_account
from google.cloud import secretmanager
import os
import logging
import sys
from absl import app
from absl import logging as absl_logging
from google.auth.exceptions import RefreshError
from googleapiclient.errors import HttpError
from tenacity import retry, stop_after_attempt, wait_exponential


os.environ['ABSL_LOGGING_MODULE_INTERCEPT_LEVEL'] = 'fatal'
SCOPES = ['https://mail.google.com/']
project_id = os.environ.get('PROJECT_ID')
secrets_project_id = os.environ.get('SECRETS_PROJECT_ID')
secret_id = os.environ.get('SECRET_ID')
pull_topic_name = os.environ.get('PULL_TOPIC_NAME')
push_topic_name = os.environ.get('PUSH_TOPIC_NAME')

def access_secret_version(version_id="latest"):
    logging.info(f"Accessing secret version: {secret_id}")
    client = secretmanager.SecretManagerServiceClient()
    name = f"projects/{secrets_project_id}/secrets/{secret_id}/versions/{version_id}"
    response = client.access_secret_version(request={"name": name})
    logging.info("Secret accessed successfully")
    return response.payload.data.decode('UTF-8')

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
def get_gmail_service(user_email):
    logging.info(f"Getting Gmail service for user: {user_email}")
    try:
        service_account_info = json.loads(access_secret_version())
        
        creds = service_account.Credentials.from_service_account_info(
            service_account_info,
            scopes=SCOPES
        )
        delegated_creds = creds.with_subject(user_email)
        service = build('gmail', 'v1', credentials=delegated_creds)
        logging.info("Gmail service created successfully")
        return service
    except RefreshError as e:
        logging.error(f"RefreshError: {str(e)}")
        logging.error("This error suggests issues with token refresh. Check service account permissions and domain-wide delegation.")
        raise
    except Exception as e:
        logging.error(f"Failed to create Gmail service: {str(e)}")
        raise

def setup_gmail_watch(service, user_email):
    logging.info(f"Setting up Gmail watch for user: {user_email}")
    topic_name = f'projects/{project_id}/topics/{pull_topic_name}'
    request = {
        'labelIds': ['INBOX'],
        'topicName': topic_name
    }
    try:
        response = service.users().watch(userId='me', body=request).execute()
        logging.info(f"Watch setup successful. Expires at: {response.get('expiration')}")
        return response
    except HttpError as e:
        logging.error(f"HttpError in setup_gmail_watch: {e.resp.status} {e.resp.reason}")
        logging.error(f"Error content: {e.content}")
        raise
    except Exception as e:
        logging.error(f"Failed to set up watch: {str(e)}")
        raise

def check_and_renew_watch(service, user_email):
    logging.info(f"Checking Gmail watch status for user: {user_email}")
    try:
        response = service.users().getProfile(userId='me').execute()
        logging.info(f"Get Profile response: {response}")
        if 'historyId' in response:
            logging.info("Gmail watch is active")
            return True
        else:
            logging.info("Gmail watch is not active, setting up a new watch")
            setup_gmail_watch(service, user_email)
            return True
    except HttpError as e:
        logging.error(f"HttpError in check_and_renew_watch: {e.resp.status} {e.resp.reason}")
        logging.error(f"Error content: {e.content}")
        return False
    except Exception as e:
        logging.error(f"Failed to check watch status: {str(e)}")
        return False

def process_email(message_id, user_email):
    logging.info(f"Processing email with ID: {message_id} for user: {user_email}")
    service = get_gmail_service(user_email)
    msg = service.users().messages().get(userId='me', id=message_id, format='full').execute()
    email_content = extract_email_content(msg)
    email_data = {
        'id': msg['id'],
        'user_email': user_email,
        'subject': next((header['value'] for header in msg['payload']['headers'] if header['name'].lower() == 'subject'), 'No Subject'),
        'from': next((header['value'] for header in msg['payload']['headers'] if header['name'].lower() == 'from'), 'Unknown Sender'),
        'content': email_content
    }
    publish_message(email_data)
    logging.info(f"Email {message_id} processed and published")

def extract_email_content(msg):
    logging.info("Extracting email content")
    
    def decode_part(part):
        if part.get('body') and part['body'].get('data'):
            return base64.urlsafe_b64decode(part['body']['data']).decode('utf-8')
        return ''

    def get_text_parts(payload, content_type='text/plain'):
        if 'parts' in payload:
            return [part for part in payload['parts'] if part['mimeType'] == content_type]
        elif payload['mimeType'] == content_type:
            return [payload]
        return []

    text_parts = get_text_parts(msg['payload'])
    if not text_parts:
        # Fallback to HTML if no plain text
        text_parts = get_text_parts(msg['payload'], 'text/html')

    content = ' '.join(decode_part(part) for part in text_parts)
    
    # If content was HTML, convert to plain text
    if text_parts and text_parts[0]['mimeType'] == 'text/html':
        content = html.unescape(content)
        content = re.sub('<[^<]+?>', '', content)  # Remove HTML tags
    
    # Clean up the content
    content = re.sub(r'\r\n|\r|\n', ' ', content)  # Replace newlines with spaces
    content = re.sub(r'\s+', ' ', content)  # Replace multiple spaces with single space
    content = content.strip()  # Remove leading/trailing whitespace
    
    logging.info("Email content extracted and cleaned successfully")
    return content

def publish_message(message):
    logging.info("Publishing message to Pub/Sub")
    publisher = pubsub_v1.PublisherClient()
    topic_path = publisher.topic_path(project_id, push_topic_name)
    future = publisher.publish(topic_path, json.dumps(message).encode('utf-8'))
    logging.info(f'Published message ID: {future.result()}')

def fetch_changes(history_id, user_email):
    logging.info(f"Fetching changes since history ID: {history_id} for user: {user_email}")
    service = get_gmail_service(user_email)
    try:
        # First, get the current history ID
        profile = service.users().getProfile(userId='me').execute()
        current_history_id = profile['historyId']
        logging.info(f"Current history ID: {current_history_id}")

        if int(current_history_id) > int(history_id):
            logging.info("Current history ID is greater than the received history ID. Fetching changes...")
            changes = service.users().history().list(userId='me', startHistoryId=history_id).execute()
            logging.info(f"Response from history().list(): {changes}")
            
            if 'historyId' in changes:
                logging.info(f"New history ID in changes: {changes['historyId']}")
            else:
                logging.warning("No new history ID in the response")
            
            history_list = changes.get('history', [])
            logging.info(f"Found {len(history_list)} changes")
            
            for change in history_list:
                logging.info(f"Processing change: {change}")
                for message in change.get('messages', []):
                    process_email(message['id'], user_email)
            
            logging.info("All changes processed successfully")
        else:
            logging.info("Current history ID is not greater than the received history ID. No new changes to process.")
    except Exception as e:
        logging.error(f"Failed to fetch or process changes: {str(e)}")
        raise

def initialize_logging():
    logging.getLogger().setLevel(logging.INFO)
    absl_logging.use_absl_handler()

def pubsub_push(event, context):
    initialize_logging()
    print("Function started", file=sys.stderr)
    logging.error("This is an error log")
    logging.warning("This is a warning log")
    logging.info("This is an info log")
    logging.debug("This is a debug log")
    print(f"Event: {event}", file=sys.stdout)
    print(f"Context: {context}", file=sys.stdout)
    try:
        pubsub_message = base64.b64decode(event['data']).decode('utf-8')
        data = json.loads(pubsub_message)
        logging.info(f"Received Pub/Sub message data: {data}")
        
        user_email = data.get('emailAddress')
        history_id = data['historyId']
        
        if not user_email:
            logging.error("User email not found in the Pub/Sub message")
            return    

        logging.info(f"Received history ID: {history_id} for user: {user_email}")
        fetch_changes(history_id, user_email)
        logging.info("Pub/Sub push processing completed")
    except Exception as e:
        logging.error(f"Error in pubsub_push: {str(e)}")
        raise