import json
from google.cloud import pubsub_v1
from googleapiclient.discovery import build
from google.oauth2 import service_account
from google.cloud import secretmanager
import os
import logging
from google.auth.exceptions import RefreshError
from googleapiclient.errors import HttpError
from tenacity import retry, stop_after_attempt, wait_exponential

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

SCOPES = ['https://mail.google.com/']
project_id = os.environ.get('PROJECT_ID')
secrets_project_id = os.environ.get('SECRETS_PROJECT_ID')
secret_id = os.environ.get('SECRET_ID')
pull_topic_name = os.environ.get('PULL_TOPIC_NAME')
user_email = os.environ.get('USER_EMAIL')

def access_secret_version(version_id="latest"):
    logger.info(f"Accessing secret version: {secret_id}")
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

def check_and_renew_watch(request):
    logger.info(f"Checking and renewing Gmail watch for user: {user_email}")
    try:
        service = get_gmail_service(user_email)
        response = service.users().getProfile(userId='me').execute()
        logger.info(f"Get Profile response: {response}")
        if 'historyId' in response:
            logger.info("Gmail watch is active")
        else:
            logger.info("Gmail watch is not active, setting up a new watch")
            setup_gmail_watch(service, user_email)
        return "Watch checked and renewed if necessary", 200
    except Exception as e:
        logger.error(f"Failed to check and renew watch: {str(e)}")
        return f"Error: {str(e)}", 500

# Cloud Function entry point
def watcher_function(request):
    return check_and_renew_watch(request)