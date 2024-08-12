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
from google.auth.exceptions import RefreshError
from googleapiclient.errors import HttpError
from tenacity import retry, stop_after_attempt, wait_exponential
from google.cloud import datastore
from watcher_cloud_logging_helper import setup_logging


SCOPES = ['https://mail.google.com/']
project_id = os.environ.get('PROJECT_ID')
secrets_project_id = os.environ.get('SECRETS_PROJECT_ID')
secret_id = os.environ.get('SECRET_ID')
pull_topic_name = os.environ.get('PULL_TOPIC_NAME')
push_topic_name = os.environ.get('PUSH_TOPIC_NAME').split('/')[-1]  # Extract only the topic name

# Set this environment variable to suppress the Abseil warning
os.environ['ABSL_LOGGING_MODULE_INTERCEPT_LEVEL'] = 'fatal'

logger = setup_logging()


def get_last_history_id(user_email):
    client = datastore.Client()
    key = client.key('LastProcessedHistoryId', user_email)
    entity = client.get(key)
    if entity:
        return entity['history_id']
    return None

def update_last_history_id(user_email, history_id):
    client = datastore.Client()
    key = client.key('LastProcessedHistoryId', user_email)
    entity = datastore.Entity(key=key)
    entity['history_id'] = history_id
    client.put(entity)

def access_secret_version(version_id="latest"):
    logging.info(f"Accessing secret version: {secret_id}")
    client = secretmanager.SecretManagerServiceClient()
    name = f"projects/{secrets_project_id}/secrets/{secret_id}/versions/{version_id}"
    response = client.access_secret_version(request={"name": name})
    logger.info("Secret accessed successfully")
    return response.payload.data.decode('UTF-8')

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
def get_gmail_service(user_email):
    logger.info(f"Getting Gmail service for user: {user_email}")
    try:
        service_account_info = json.loads(access_secret_version())
        
        creds = service_account.Credentials.from_service_account_info(
            service_account_info,
            scopes=SCOPES
        )
        delegated_creds = creds.with_subject(user_email)
        service = build('gmail', 'v1', credentials=delegated_creds)
        logger.info("Gmail service created successfully")
        return service
    except RefreshError as e:
        logger.error(f"RefreshError: {str(e)}")
        logger.error("This error suggests issues with token refresh. Check service account permissions and domain-wide delegation.")
        raise
    except Exception as e:
        logger.error(f"Failed to create Gmail service: {str(e)}")
        raise

def setup_gmail_watch(service, user_email):
    logger.info(f"Setting up Gmail watch for user: {user_email}")
    topic_name = f'projects/{project_id}/topics/{pull_topic_name}'
    request = {
        'labelIds': ['INBOX'],
        'topicName': topic_name
    }
    try:
        response = service.users().watch(userId='me', body=request).execute()
        logger.info(f"Watch setup successful. Expires at: {response.get('expiration')}")
        return response
    except HttpError as e:
        logger.error(f"HttpError in setup_gmail_watch: {e.resp.status} {e.resp.reason}")
        logger.error(f"Error content: {e.content}")
        raise
    except Exception as e:
        logger.error(f"Failed to set up watch: {str(e)}")
        raise

def check_and_renew_watch(service, user_email):
    logger.info(f"Checking Gmail watch status for user: {user_email}")
    try:
        response = service.users().getProfile(userId='me').execute()
        logger.info(f"Get Profile response: {response}")
        if 'historyId' in response:
            logger.info("Gmail watch is active")
            return True
        else:
            logger.info("Gmail watch is not active, setting up a new watch")
            setup_gmail_watch(service, user_email)
            return True
    except HttpError as e:
        logger.error(f"HttpError in check_and_renew_watch: {e.resp.status} {e.resp.reason}")
        logger.error(f"Error content: {e.content}")
        return False
    except Exception as e:
        logger.error(f"Failed to check watch status: {str(e)}")
        return False

def process_email(message_id, user_email):
    logger.info(f"Processing email with ID: {message_id} for user: {user_email}")
    service = get_gmail_service(user_email)
    msg = service.users().messages().get(userId='me', id=message_id, format='full').execute()
    email_content = extract_email_content(msg)
    email_data = {
        'id': msg['id'],
        'user_email': user_email,
        'subject': next((header['value'] for header in msg['payload']['headers'] if header['name'].lower() == 'subject'), 'No Subject'),
        'from': next((header['value'] for header in msg['payload']['headers'] if header['name'].lower() == 'from'), 'Unknown Sender'),
        'body': email_content
    }
    publish_message(email_data)
    logger.info(f"Email {message_id} processed and published")

def extract_email_content(msg):
    logger.info("Extracting email content")
    
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
    
    logger.info("Email content extracted and cleaned successfully")
    return content

def publish_message(message):
    logger.info("Publishing message to Pub/Sub")
    publisher = pubsub_v1.PublisherClient()
    topic_path = publisher.topic_path(project_id, push_topic_name)
    future = publisher.publish(topic_path, json.dumps(message).encode('utf-8'))
    logger.info(f'Published message ID: {future.result()}')

def fetch_changes(history_id, user_email):
    logger.info(f"Fetching changes since history ID: {history_id} for user: {user_email}")
    service = get_gmail_service(user_email)
    try:
        last_processed_history_id = get_last_history_id(user_email)
        if last_processed_history_id:
            history_id = last_processed_history_id

        profile = service.users().getProfile(userId='me').execute()
        current_history_id = profile['historyId']
        logger.info(f"Current history ID: {current_history_id}")
        
        if int(current_history_id) > int(history_id):
            logger.info("Current history ID is greater than the last processed history ID. Fetching changes...")
            
            while True:
                changes = service.users().history().list(userId='me', startHistoryId=history_id).execute()
                logger.info(f"Response from history().list(): {changes}")
                
                history_list = changes.get('history', [])
                logger.info(f"Found {len(history_list)} changes")
                
                for change in history_list:
                    logger.info(f"Processing change: {change}")
                    for message in change.get('messagesAdded', []):
                        process_email(message['message']['id'], user_email)
                
                if 'nextPageToken' not in changes:
                    break
                history_id = changes['historyId']
            
            update_last_history_id(user_email, current_history_id)
            logger.info("All changes processed successfully")
        else:
            logger.info("No new changes to process.")
    except Exception as e:
        logger.error(f"Failed to fetch or process changes: {str(e)}")
        raise

def pubsub_push(event, context):
    print("Function started", file=sys.stderr)
    logger.info("Function started")
    try:
        pubsub_message = base64.b64decode(event['data']).decode('utf-8')
        data = json.loads(pubsub_message)
        logger.info(f"Received Pub/Sub message data: {data}")
        
        user_email = data.get('emailAddress')
        history_id = data.get('historyId')
        
        if not user_email or not history_id:
            logger.error("User email or history ID not found in the Pub/Sub message")
            return    

        logger.info(f"Received history ID: {history_id} for user: {user_email}")
        fetch_changes(history_id, user_email)
        logger.info("Pub/Sub push processing completed")
    except Exception as e:
        logger.error(f"Error in pubsub_push: {str(e)}")
        raise