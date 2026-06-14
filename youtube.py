import requests
import os
from dotenv import load_dotenv

load_dotenv()

api_key = os.getenv("YOUTUBE_API_KEY")
channel_id = os.getenv("YOUTUBE_CHANNEL_ID")

response = requests.get(
    "https://www.googleapis.com/youtube/v3/channels",
    params={
        "part": "snippet,statistics",
        "id": channel_id,
        "key": api_key
    }
)

channel = response.json()["items"][0]
stats = channel["statistics"]

print(f"Channel: {channel['snippet']['title']}")
print(f"Subscribers: {stats['subscriberCount']}")
print(f"Total Views: {stats['viewCount']}")
print(f"Videos: {stats['videoCount']}")