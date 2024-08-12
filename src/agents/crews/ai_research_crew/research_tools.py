from langchain.agents import Tool
from langchain.utilities import GoogleSerperAPIWrapper
from google.cloud import secretmanager
import os


PROJECT_ID = os.environ.get('PROJECT_ID')

# Setup API keys
def access_secret_version(secret_id, version_id="latest"):
    client = secretmanager.SecretManagerServiceClient()
    name = f"projects/{PROJECT_ID}/secrets/{secret_id}/versions/{version_id}"
    response = client.access_secret_version(request={"name": name})
    return response.payload.data.decode('UTF-8')

SERPER_API_KEY = access_secret_version('SERPER_API_KEY')


search = GoogleSerperAPIWrapper(serper_api_key=SERPER_API_KEY)

# Create and assign the search tool to an agent
serper_tool = Tool(
  name="Web search",
  func=search.run,
  description="Useful for search-based queries",
)

