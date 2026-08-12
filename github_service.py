import os
import httpx
from typing import List, Optional

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
HEADERS = {
    "Authorization": f"Bearer {GITHUB_TOKEN}",
    "Accept": "application/vnd.github.v3+json"
}
BASE_URL = "https://api.github.com"


async def get_pr_files(repo_full_name: str, pr_number: int) -> List[dict]:
    """Fetch the list of changed files in a PR and filter for .ipynb."""
    url = f"{BASE_URL}/repos/{repo_full_name}/pulls/{pr_number}/files"
    async with httpx.AsyncClient() as client:
        response = await client.get(url, headers=HEADERS)
        response.raise_for_status()
        files = response.json()
        return [f for f in files if f["filename"].endswith(".ipynb")]


async def get_file_content(repo_full_name: str, file_path: str, ref: str) -> Optional[dict]:
    """Download the raw notebook JSON content from GitHub."""
    url = f"{BASE_URL}/repos/{repo_full_name}/contents/{file_path}?ref={ref}"
    async with httpx.AsyncClient() as client:
        # We use the raw media type to get the decoded content directly
        headers = {**HEADERS, "Accept": "application/vnd.github.v3.raw"}
        response = await client.get(url, headers=headers)
        if response.status_code == 200:
            return response.json()
        return None


async def post_pr_comment(repo_full_name: str, pr_number: int, review_body: str):
    """Post the review output back to the PR as a general comment."""
    url = f"{BASE_URL}/repos/{repo_full_name}/issues/{pr_number}/comments"
    async with httpx.AsyncClient() as client:
        response = await client.post(url, headers=HEADERS, json={"body": review_body})
        response.raise_for_status()
        return response.json()
