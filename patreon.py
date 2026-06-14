import requests
import os
from dotenv import load_dotenv

load_dotenv()

token = os.getenv("PATREON_ACCESS_TOKEN")

headers = {
    "Authorization": f"Bearer {token}"
}

response = requests.get(
    "https://www.patreon.com/api/oauth2/v2/campaigns",
    headers=headers
)

print(response.json())