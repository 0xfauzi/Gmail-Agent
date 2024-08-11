import os
import json
from google.cloud import secretmanager, datastore
from googleapiclient.discovery import build
from google.oauth2 import service_account
import logging
from absl import app
from absl import logging as absl_logging

PROJECT_ID = os.environ.get('PROJECT_ID')
SECRETS_PROJECT_ID = os.environ.get('SECRETS_PROJECT_ID')
SECRET_ID = os.environ.get('SECRET_ID')
USER_EMAIL = os.environ.get('USER_EMAIL')

def access_secret_version(version_id="latest"):
    client = secretmanager.SecretManagerServiceClient()
    name = f"projects/{SECRETS_PROJECT_ID}/secrets/{SECRET_ID}/versions/{version_id}"
    response = client.access_secret_version(request={"name": name})
    return response.payload.data.decode('UTF-8')

def get_gmail_service():
    service_account_info = json.loads(access_secret_version())
    creds = service_account.Credentials.from_service_account_info(
        service_account_info,
        scopes=['https://mail.google.com/']
    )
    delegated_creds = creds.with_subject(USER_EMAIL)
    return build('gmail', 'v1', credentials=delegated_creds)

def setup_gmail_watch():
    service = get_gmail_service()
    topic_name = f'projects/{PROJECT_ID}/topics/email_updates'
    request = {
        'labelIds': ['INBOX'],
        'topicName': topic_name
    }
    try:
        response = service.users().watch(userId='me', body=request).execute()
        logging.info(f"Watch setup successful. Expires at: {response.get('expiration')}")
        
        # Store the historyId
        client = datastore.Client()
        key = client.key('LastProcessedHistoryId', USER_EMAIL)
        entity = datastore.Entity(key=key)
        entity['history_id'] = response['historyId']
        client.put(entity)
        
        logging.info(f"Stored initial historyId: {response['historyId']}")
    except Exception as e:
        logging.error(f"Failed to set up watch: {str(e)}")
        raise

def initialize_logging():
    logging.getLogger().setLevel(logging.INFO)
    absl_logging.use_absl_handler()


if __name__ == "__main__":
    initialize_logging()
    setup_gmail_watch()