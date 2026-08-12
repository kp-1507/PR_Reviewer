
from fastapi import FastAPI, Request
import base64
import os
import requests
app = FastAPI()
from dotenv import load_dotenv

load_dotenv()

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
@app.post("/webhook/github")
async def github_webhook(request: Request):

    payload = await request.json()

    action = payload.get("action")

    if "pull_request" not in payload:
        return {"status": "ignored"}

    pr_number = payload["number"]

    repo_name = payload["repository"]["name"]
    owner = payload["repository"]["owner"]["login"]

    head_sha = payload["pull_request"]["head"]["sha"]

    print("====== PR EVENT ======")
    print("Action:", action)
    print("Owner:", owner)
    print("Repository:", repo_name)
    print("PR Number:", pr_number)
    print("Head SHA:", head_sha)

    # GitHub API
    url = f"https://api.github.com/repos/{owner}/{repo_name}/pulls/{pr_number}/files"

    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json"
    }

    response = requests.get(url, headers=headers)

    print("GitHub API Status:", response.status_code)

    files = response.json()

    for file in files:
        filename=file["filename"]
        content_url = (
                    f"https://api.github.com/repos/"
                    f"{owner}/{repo_name}/contents/{filename}"
        )
        params = {
            "ref": head_sha
        }
        content_response = requests.get(
        content_url,
        headers=headers,
        params=params
        )
        print("Content API Status:", content_response.status_code)

        content_data = content_response.json()

        print("FULL FILE:")
        print(content_data)

        # print("\n====================")
        # print("File:", file["filename"])
        # print("Status:", file["status"])
        # print("Additions:", file["additions"])
        # print("Deletions:", file["deletions"])
        # print("PATCH:")
        # print(file.get("patch"))
        
        encoded_content = content_data["content"]

        full_content = base64.b64decode(
        encoded_content
        ).decode("utf-8")

        print("FULL FILE CONTENT:")
        print(full_content)

    return {"status": "received"}