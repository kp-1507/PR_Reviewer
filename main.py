import base64
import json
import os
import requests
from fastapi import FastAPI, Request, BackgroundTasks
from dotenv import load_dotenv

from sql_reviewer.graph.workflow import run_sql_review

app = FastAPI()

load_dotenv()

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")


def process_pr_review(owner: str, repo_name: str, pr_number: int, head_sha: str):
    """Processes PR files and executes SQL review in the background to prevent webhook timeout."""
    print("====== PR EVENT (Processing in Background) ======")
    print("Owner:", owner)
    print("Repository:", repo_name)
    print("PR Number:", pr_number)
    print("Head SHA:", head_sha)

    url = f"https://api.github.com/repos/{owner}/{repo_name}/pulls/{pr_number}/files"
    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json"
    }

    response = requests.get(url, headers=headers)
    print("GitHub API Status:", response.status_code)

    if response.status_code != 200:
        print("Error fetching PR files:", response.json())
        return

    files = response.json()

    for file in files:
        filename = file["filename"]
        content_url = f"https://api.github.com/repos/{owner}/{repo_name}/contents/{filename}"
        params = {"ref": head_sha}

        content_response = requests.get(content_url, headers=headers, params=params)
        print(f"Content API Status for {filename}:", content_response.status_code)

        if content_response.status_code != 200:
            print(f"Error fetching content for {filename}:", content_response.json())
            continue

        content_data = content_response.json()

        if "content" in content_data:
            encoded_content = content_data["content"]
            full_content = base64.b64decode(encoded_content).decode("utf-8")

            if filename.endswith(".ipynb"):
                try:
                    notebook_dict = json.loads(full_content)
                    notebook_dict["path"] = filename

                    print(f"\n==================================================")
                    print(f"🚀 RUNNING SQL REVIEW WORKFLOW FOR: {filename}")
                    print(f"==================================================")

                    review_result = run_sql_review(notebook_dict)

                    print("\n==================================================")
                    print(f"📊 REVIEW SUMMARY: {filename}")
                    print(f"SQL Cells: {review_result.get('total_sql_cells')} | AST Errors: {review_result.get('total_ast_parse_errors')} | Rule Violations: {review_result.get('total_violations')}")
                    print("==================================================")

                    violations = review_result.get("violations", [])
                    if violations:
                        print("\n🔴 DETERMINISTIC KEYWORD & AST VIOLATIONS:")
                        for v in violations:
                            print(f"  • Cell #{v.get('cell_id')} Line {v.get('line')}: [{v.get('rule_id')}] Keyword '{v.get('current')}' must be uppercase ('{v.get('expected')}')")

                    llm_review = review_result.get("llm_review")
                    if llm_review:
                        print("\n🔍 SEMANTIC & PERFORMANCE FINDINGS (LLM):")
                        print(llm_review)

                    print("\n==================================================\n")
                except Exception as e:
                    print(f"Error parsing or reviewing notebook {filename}: {e}")


@app.post("/webhook/github")
async def github_webhook(request: Request, background_tasks: BackgroundTasks):
    payload = await request.json()

    action = payload.get("action")
    print("ACTION", action)
    if "pull_request" not in payload:
        return {"status": "ignored"}

    pr_number = payload["number"]
    repo_name = payload["repository"]["name"]
    owner = payload["repository"]["owner"]["login"]
    head_sha = payload["pull_request"]["head"]["sha"]

    background_tasks.add_task(process_pr_review, owner, repo_name, pr_number, head_sha)

    return {"status": "received", "message": "Review processing in background"}