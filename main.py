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


def get_merge_base_sha(owner: str, repo_name: str, base_sha: str, head_sha: str, headers: dict) -> str | None:
    """Call GitHub Compare API to find the true merge base SHA between base and head branches."""
    compare_url = f"https://api.github.com/repos/{owner}/{repo_name}/compare/{base_sha}...{head_sha}"
    response = requests.get(compare_url, headers=headers)
    if response.status_code == 200:
        merge_base_sha = response.json().get("merge_base_commit", {}).get("sha")
        print(f"Merge base SHA resolved: {merge_base_sha}")
        return merge_base_sha
    print(f"Failed to resolve merge base SHA. Status: {response.status_code}")
    return None


def process_pr_review(owner: str, repo_name: str, pr_number: int, head_sha: str, base_sha: str, before_sha: str | None = None):
    """Processes PR files and executes SQL review in the background to prevent webhook timeout."""
    print("====== PR EVENT (Processing in Background) ======")
    print("Owner:", owner)
    print("Repository:", repo_name)
    print("PR Number:", pr_number)
    print("Head SHA:", head_sha)
    print("Base SHA (tip of main):", base_sha)
    if before_sha:
        print("Before SHA (previous push):", before_sha)

    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json"
    }

    # Step 1: Resolve the true merge base SHA via GitHub Compare API
    # The patch in PR files is relative to the merge base, NOT base_sha (tip of main)
    merge_base_sha = get_merge_base_sha(owner, repo_name, base_sha, head_sha, headers)
    if not merge_base_sha:
        print("Could not resolve merge base SHA. Aborting review.")
        return

    # Step 2: Fetch changed files
    # If synchronize event, compare before_sha...head_sha to review ONLY files touched in this push
    files = []
    if before_sha:
        print(f"🔍 Incremental push detected! Comparing {before_sha[:8]}...{head_sha[:8]} for changed files...")
        compare_url = f"https://api.github.com/repos/{owner}/{repo_name}/compare/{before_sha}...{head_sha}"
        compare_response = requests.get(compare_url, headers=headers)
        if compare_response.status_code == 200:
            files = compare_response.json().get("files", [])
            print(f"📦 Files modified in this push ({len(files)}): {[f.get('filename') for f in files]}")
        else:
            print(f"⚠️ Compare API returned {compare_response.status_code}, falling back to full PR files list.")

    # Initial PR open or fallback: fetch full list of changed files in this PR
    if not files:
        url = f"https://api.github.com/repos/{owner}/{repo_name}/pulls/{pr_number}/files"
        response = requests.get(url, headers=headers)
        print("GitHub PR Files API Status:", response.status_code)

        if response.status_code != 200:
            print("Error fetching PR files:", response.json())
            return

        files = response.json()

    from code_store import get_stored_file, save_file
    from patch_utility import apply_patch

    repo_full_name = f"{owner}/{repo_name}"

    for file in files:
        filename = file["filename"]
        if not filename.endswith((".ipynb", ".py")):
            continue

        # Skip deleted files — nothing to review
        status = file.get("status")
        if status == "removed":
            print(f"⏭️ Skipping deleted file {filename}")
            continue

        # Skip files with no actual code changes (e.g. files touched during merge conflict resolution)
        patch = file.get("patch", "")
        if not patch or not patch.strip():
            print(f"⏭️ Skipping {filename} — no diff/patch (unchanged or binary)")
            continue

        print("--------------------------------------------------")
        print("File:", filename)
        print("Patch:\n", patch)

        # Step 3: Look up merge_base_sha in SQLite
        stored_base = get_stored_file(repo_full_name, filename, merge_base_sha)

        if not stored_base:
            # Bootstrap: first time we see this merge base, download it from GitHub
            print(f"merge_base_sha ({merge_base_sha[:8]}) not in cache. Downloading base version of {filename}...")
            content_url = f"https://api.github.com/repos/{owner}/{repo_name}/contents/{filename}"
            content_response = requests.get(content_url, headers=headers, params={"ref": merge_base_sha})

            if content_response.status_code == 200:
                content_data = content_response.json()
                if "content" in content_data:
                    stored_base = base64.b64decode(content_data["content"]).decode("utf-8")
                    # Cache the merge base content so future PRs with the same base skip this download
                    save_file(repo_full_name, filename, merge_base_sha, stored_base)
                    print(f"✅ Cached merge base of {filename} at {merge_base_sha[:8]}")
            else:
                # Brand new file added in this PR — no base content exists
                print(f"File {filename} is new in this PR (no base content).")
                stored_base = ""

        # Step 4: Apply patch on merge base content to reconstruct developer's code
        full_content = None
        if patch:
            try:
                full_content = apply_patch(stored_base, patch)
                print(f"✅ Patch applied for {filename} (no full file download!)")
            except Exception as patch_err:
                print(f"⚠️  Patch failed for {filename}: {patch_err}. Falling back to GitHub download.")
        else:
            full_content = stored_base

        # Step 5: Fallback — download head version if patch failed
        if not full_content:
            print(f"📥 Downloading full file {filename} from GitHub (ref: {head_sha})...")
            content_url = f"https://api.github.com/repos/{owner}/{repo_name}/contents/{filename}"
            content_response = requests.get(content_url, headers=headers, params={"ref": head_sha})
            print(f"Content API Status for {filename}:", content_response.status_code)

            if content_response.status_code != 200:
                print(f"Error fetching content for {filename}:", content_response.json())
                continue

            content_data = content_response.json()
            if "content" in content_data:
                full_content = base64.b64decode(content_data["content"]).decode("utf-8")

        # NOTE: We do NOT save head content to SQLite. Unmerged code stays out of the database.

        if full_content:
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

                    # Post review comment to GitHub PR
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



def process_pr_merge(owner: str, repo_name: str, pr_number: int, merge_commit_sha: str, head_sha: str):
    """Downloads merged files and saves them to the SQLite database memory under both merge_commit_sha and head_sha."""
    print("====== PR MERGE (Updating Database Memory) ======")
    print("Merge Commit SHA:", merge_commit_sha)
    print("Head SHA (before merge):", head_sha)
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

        # Skip deleted files
        status = file.get("status")
        if status == "removed":
            continue

        print(f"Downloading merged version of {filename} (ref: {merge_commit_sha})...")
        content_url = f"https://api.github.com/repos/{owner}/{repo_name}/contents/{filename}"
        params = {"ref": merge_commit_sha}
        content_response = requests.get(content_url, headers=headers, params=params)
        
        if content_response.status_code == 200:
            content_data = content_response.json()
            if "content" in content_data:
                encoded_content = content_data["content"]
                full_content = base64.b64decode(encoded_content).decode("utf-8")
                
                repo_full_name = f"{owner}/{repo_name}"
                # Save under merge_commit_sha (the new commit on main)
                save_file(repo_full_name, filename, merge_commit_sha, full_content)
                print(f"✅ Successfully stored merged file {filename} at merge SHA {merge_commit_sha} in SQLite database.")
                
                # Save under head_sha (the commit where subsequent branches may have diverged)
                save_file(repo_full_name, filename, head_sha, full_content)
                print(f"✅ Successfully stored merged file {filename} at head SHA {head_sha} in SQLite database.")
        else:
            print(f"Error downloading merged content for {filename}:", content_response.json())


@app.post("/webhook/github")
async def github_webhook(request: Request, background_tasks: BackgroundTasks):
    payload = await request.json()

    if "pull_request" not in payload:
        return {"status": "ignored"}

    action = payload.get("action")
    print("ACTION:", action)
    merged = payload["pull_request"].get("merged", False)
    merge_commit_sha = payload["pull_request"].get("merge_commit_sha")

    # 1. PR MERGED: Save files to memory under both merge_commit_sha and head_sha
    if action == "closed" and merged and merge_commit_sha:
        pr_number = payload["number"]
        repo_name = payload["repository"]["name"]
        owner = payload["repository"]["owner"]["login"]
        head_sha = payload["pull_request"]["head"]["sha"]
        print(f"PR merged! Scheduling database memory update for merge commit {merge_commit_sha} and head commit {head_sha}...")
        background_tasks.add_task(process_pr_merge, owner, repo_name, pr_number, merge_commit_sha, head_sha)
        return {"status": "received", "message": "PR merge registered, database update scheduled"}

    # 2. PR OPENED / UPDATED: Run review
    elif action in ["opened", "synchronize", "reopened"]:
        pr_number = payload["number"]
        repo_name = payload["repository"]["name"]
        owner = payload["repository"]["owner"]["login"]
        head_sha = payload["pull_request"]["head"]["sha"]
        base_sha = payload["pull_request"]["base"]["sha"]
        before_sha = payload.get("before") if action == "synchronize" else None

        print(f"PR {action}! Scheduling review (before_sha: {before_sha[:8] if before_sha else 'None'})...")
        background_tasks.add_task(process_pr_review, owner, repo_name, pr_number, head_sha, base_sha, before_sha)
        return {"status": "received", "message": "Review processing in background"}

    return {"status": "ignored", "action": action}