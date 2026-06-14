import os
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
import json

SCOPES = [
    "https://www.googleapis.com/auth/adsense.readonly",
    "https://www.googleapis.com/auth/yt-analytics.readonly"
]

flow = InstalledAppFlow.from_client_secrets_file(
    "client_secret.json", SCOPES
)

creds = flow.run_local_server(port=0)

# Save credentials to file so dashboard can reuse them
with open("google_creds.json", "w") as f:
    f.write(creds.to_json())

print("✅ Authentication successful! Credentials saved.")