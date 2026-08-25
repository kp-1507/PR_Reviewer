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


def process_pr_review(owner: str, repo_name: str, pr_number: int, head_sha: str, base_sha: str):
    """Processes PR files and executes SQL review in the background to prevent webhook timeout."""
    print("====== PR EVENT (Processing in Background) ======")
    print("Owner:", owner)
    print("Repository:", repo_name)
    print("PR Number:", pr_number)
    print("Head SHA:", head_sha)
    print("Base SHA:", base_sha)

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
    

    from code_store import get_stored_file, save_file
    from patch_utility import apply_patch

    for file in files:
        filename = file["filename"]
        if not filename.endswith((".ipynb", ".py")):
            continue
            
        patch = file.get("patch", "")
        print("--------------------------------------------------")
        print("printing patch or diff for file:", filename)
        print(patch)
        
        repo_full_name = f"{owner}/{repo_name}"
        
        # 1. Fetch base_sha content from SQLite
        stored_base = get_stored_file(repo_full_name, filename, base_sha)
        
        if not stored_base:
            # First time seeing this base file, download the clean base version from GitHub
            print(f"base_sha ({base_sha}) not found in cache. Downloading base version of {filename}...")
            content_url = f"https://api.github.com/repos/{owner}/{repo_name}/contents/{filename}"
            params = {"ref": base_sha}
            content_response = requests.get(content_url, headers=headers, params=params)
            
            if content_response.status_code == 200:
                content_data = content_response.json()
                if "content" in content_data:
                    encoded_content = content_data["content"]
                    stored_base = base64.b64decode(encoded_content).decode("utf-8")
                    # Save the clean base version to SQLite
                    save_file(repo_full_name, filename, base_sha, stored_base)
            else:
                # If base_sha does not exist (e.g. file is brand new in the PR), base content is empty
                stored_base = ""
                
        # 2. Apply patch to base content to get head content
        full_content = None
        if patch:
            try:
                full_content = apply_patch(stored_base, patch)
                print(f"Applied patch to base content for {filename}")
            except Exception as patch_err:
                print(f"Error applying patch to base content for {filename}: {patch_err}. Falling back to GitHub download.")
        else:
            full_content = stored_base
                    
        # 3. Fallback: Download from GitHub if patch application failed
        if not full_content:
            print(f"Downloading full file {filename} from GitHub (ref: {head_sha})...")
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

        # NOTE: We do NOT save full_content (head_sha) to SQLite during the review loop!
        # Unmerged code remains local to the review session.

        if full_content and filename.endswith((".ipynb", ".py")):
            try:
                input_payload = None
                if filename.endswith(".ipynb"):
                    notebook_dict = json.loads(full_content)
                    notebook_dict["path"] = filename
                    notebook_dict["diff"] = patch
                    input_payload = notebook_dict
                else:
                    input_payload = {"path": filename, "content": full_content, "diff": patch}

                print(f"\n==================================================")
                print(f"🚀 RUNNING SQL REVIEW WORKFLOW FOR: {filename}")
                print(f"==================================================")

                review_result = run_sql_review(input_payload)

                unit_label = "SQL Queries" if filename.endswith(".py") else "SQL Cells"

                print("\n==================================================")
                print(f"📊 REVIEW SUMMARY: {filename}")
                print(f"{unit_label}: {review_result.get('total_sql_cells')} | AST Errors: {review_result.get('total_ast_parse_errors')} | Rule Violations: {review_result.get('total_violations')}")
                print("==================================================")

                violations = review_result.get("violations", [])
                if violations:
                    print("\n🔴 DETERMINISTIC KEYWORD & AST VIOLATIONS:")
                    for v in violations:
                        if filename.endswith(".py"):
                            cell_label = f"Line {v.get('line')}"
                        else:
                            cell_label = f"Cell #{v.get('cell_id')} Line {v.get('line')}"
                        print(f"  • {cell_label}: [{v.get('rule_id')}] Keyword '{v.get('current')}' must be uppercase ('{v.get('expected')}')")

                llm_review = review_result.get("llm_review")
                if llm_review:
                    print("\n🔍 SEMANTIC & PERFORMANCE FINDINGS (LLM):")
                    print(llm_review)

                    # Post review report to the GitHub PR
                    review_url = f"https://api.github.com/repos/{owner}/{repo_name}/pulls/{pr_number}/reviews"
                    review_payload = {
                        "body": f"### 📊 SQL Code Review Report for `{filename}`\n\n{llm_review}",
                        "event": "COMMENT"
                    }
                    post_response = requests.post(review_url, headers=headers, json=review_payload)
                    print(f"Posted review to PR. Status code: {post_response.status_code}")

                print("\n==================================================\n")
            except Exception as e:
                print(f"Error parsing or reviewing file {filename}: {e}")
                    

def process_pr_merge(owner: str, repo_name: str, pr_number: int, head_sha: str):
    """Downloads merged files and saves them to the SQLite database memory."""
    print("====== PR MERGE (Updating Database Memory) ======")
    url = f"https://api.github.com/repos/{owner}/{repo_name}/pulls/{pr_number}/files"
    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json"
    }

    response = requests.get(url, headers=headers)
    if response.status_code != 200:
        print("Error fetching merged files:", response.json())
        return

    files = response.json()
    from code_store import save_file

    for file in files:
        filename = file["filename"]
        if not filename.endswith((".ipynb", ".py")):
            continue

        print(f"Downloading merged version of {filename} (ref: {head_sha})...")
        content_url = f"https://api.github.com/repos/{owner}/{repo_name}/contents/{filename}"
        params = {"ref": head_sha}
        content_response = requests.get(content_url, headers=headers, params=params)
        
        if content_response.status_code == 200:
            content_data = content_response.json()
            if "content" in content_data:
                encoded_content = content_data["content"]
                full_content = base64.b64decode(encoded_content).decode("utf-8")
                
                repo_full_name = f"{owner}/{repo_name}"
                save_file(repo_full_name, filename, head_sha, full_content)
                print(f"✅ Successfully stored merged file {filename} at SHA {head_sha} in SQLite database.")
        else:
            print(f"Error downloading merged content for {filename}:", content_response.json())


@app.post("/webhook/github")
async def github_webhook(request: Request, background_tasks: BackgroundTasks):
    payload = await request.json()

    action = payload.get("action")
    print("ACTION:", action)
    if "pull_request" not in payload:
        return {"status": "ignored"}

    pr_number = payload["number"]
    repo_name = payload["repository"]["name"]
    owner = payload["repository"]["owner"]["login"]
    head_sha = payload["pull_request"]["head"]["sha"]
    base_sha = payload["pull_request"]["base"]["sha"]
    merged = payload["pull_request"].get("merged", False)
    merge_commit_sha = payload["pull_request"].get("merge_commit_sha")

    # 1. PR MERGED: Save files to memory under the merge_commit_sha
    if action == "closed" and merged and merge_commit_sha:
        print(f"PR merged! Scheduling database memory update for merge commit {merge_commit_sha}...")
        background_tasks.add_task(process_pr_merge, owner, repo_name, pr_number, merge_commit_sha)
        return {"status": "received", "message": "PR merge registered, database update scheduled"}

    # 2. PR OPENED / UPDATED: Run review
    elif action in ["opened", "synchronize", "reopened"]:
        print("PR opened/updated! Scheduling review...")
        background_tasks.add_task(process_pr_review, owner, repo_name, pr_number, head_sha, base_sha)
        return {"status": "received", "message": "Review processing in background"}

    return {"status": "ignored", "action": action}