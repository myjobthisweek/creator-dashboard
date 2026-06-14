import requests
import os
from dotenv import load_dotenv

load_dotenv()

token = os.getenv("PATREON_ACCESS_TOKEN")
campaign_id = "16231121"

headers = {
    "Authorization": f"Bearer {token}"
}

response = requests.get(
    f"https://www.patreon.com/api/oauth2/v2/campaigns/{campaign_id}/members",
    headers=headers,
    params={
        "fields[member]": "full_name,patron_status,currently_entitled_amount_cents,lifetime_support_cents,email"
    }
)

data = response.json()

for member in data["data"]:
    attrs = member["attributes"]
    name = attrs.get("full_name", "Unknown")
    status = attrs.get("patron_status", "Unknown")
    monthly = attrs.get("currently_entitled_amount_cents", 0) / 100
    lifetime = attrs.get("lifetime_support_cents", 0) / 100
    print(f"{name} | {status} | ${monthly}/mo | ${lifetime} lifetime")