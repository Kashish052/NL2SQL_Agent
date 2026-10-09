import requests
import os

api_key = "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" # os.environ.get("GROQ_API_KEY")
url = "https://api.groq.com/openai/v1/models"

headers = {
    "Authorization": f"Bearer {api_key}",
    "Content-Type": "application/json"
}

response = requests.get(url, headers=headers)

print(response.json())
with open("models.json", "w") as f:
    f.write(response.text)