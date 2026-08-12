from fastapi import FastAPI, Request
from github_service import get_pr_files, get_file_content, post_pr_comment
from sql_reviewer.graph.workflow import run_sql_review

app = FastAPI()

@app.post("/webhook/github")
async def github_webhook(request: Request):
    payload = await request.json()
    action = payload.get("action")
    pr_number = payload.get("number")
    
    # We only care about opened or synchronized (updated) PRs
    # Note: For simple testing with curl, we might want to bypass this check if we don't send valid payloads
    if action not in ["opened", "synchronize"]:
        return {"status": "ignored", "reason": f"action '{action}' not supported"}
        
    repo = payload.get("repository", {})
    repo_full_name = repo.get("full_name")
    
    if not repo_full_name or not pr_number:
        return {"status": "error", "reason": "Missing repo name or PR number"}

    print(f"Processing PR #{pr_number} for repo {repo_full_name}")

    try:
        # 1. Fetch modified files
        files = await get_pr_files(repo_full_name, pr_number)
        if not files:
            return {"status": "ignored", "reason": "No .ipynb files changed"}

        # 2. Process each notebook
        for file in files:
            file_path = file["filename"]
            # Use the PR branch's head SHA
            ref = payload.get("pull_request", {}).get("head", {}).get("sha", "")
            
            notebook_json = await get_file_content(repo_full_name, file_path, ref)
            if notebook_json:
                print(f"Running workflow for {file_path}")
                # 3. Invoke LangGraph workflow
                result = run_sql_review(notebook_json)
                final_output = result.get("llm_review", "Review generation failed.")
                
                # 4. Post review comment
                comment_body = f"## Databricks SQL Review for `{file_path}`\n\n{final_output}"
                await post_pr_comment(repo_full_name, pr_number, comment_body)
                print(f"Posted review for {file_path}")
                
        return {"status": "success", "processed_files": len(files)}
        
    except Exception as e:
        print(f"Error processing webhook: {e}")
        return {"status": "error", "reason": str(e)}