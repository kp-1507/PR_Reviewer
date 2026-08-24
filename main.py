import argparse
import base64
import json
import os
import sys
import requests
from dotenv import load_dotenv

from sql_reviewer.graph.workflow import run_sql_review

load_dotenv()

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")


def get_pr_head_sha(owner: str, repo_name: str, pr_number: int) -> str:
    """Fetch the head SHA of a Pull Request from GitHub API."""
    url = f"https://api.github.com/repos/{owner}/{repo_name}/pulls/{pr_number}"
    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json"
    }
    response = requests.get(url, headers=headers)
    if response.status_code != 200:
        print(f"Error fetching PR #{pr_number}: {response.status_code} - {response.json().get('message', '')}")
        sys.exit(1)
    return response.json()["head"]["sha"]


def process_pr_review(owner: str, repo_name: str, pr_number: int):
    """Fetches PR files from GitHub and runs the SQL review workflow on each."""
    print("=" * 70)
    print("      DATABRICKS SQL CODE REVIEW AGENT — PR MODE")
    print("=" * 70)
    print(f"Repository : {owner}/{repo_name}")
    print(f"PR Number  : #{pr_number}")

    head_sha = get_pr_head_sha(owner, repo_name, pr_number)
    print(f"Head SHA   : {head_sha}\n")

    url = f"https://api.github.com/repos/{owner}/{repo_name}/pulls/{pr_number}/files"
    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json"
    }

    response = requests.get(url, headers=headers)

    if response.status_code != 200:
        print("Error fetching PR files:", response.json())
        sys.exit(1)

    files = response.json()
    reviewable_files = [f for f in files if f["filename"].endswith((".ipynb", ".py"))]

    if not reviewable_files:
        print("No .ipynb or .py files found in this PR.")
        return

    print(f"Found {len(reviewable_files)} reviewable file(s): {[f['filename'] for f in reviewable_files]}\n")

    file_reports = []
    for file in reviewable_files:
        filename = file["filename"]

        content_url = f"https://api.github.com/repos/{owner}/{repo_name}/contents/{filename}"
        params = {"ref": head_sha}

        content_response = requests.get(content_url, headers=headers, params=params)

        if content_response.status_code != 200:
            print(f"Error fetching content for {filename}: {content_response.json()}")
            continue

        content_data = content_response.json()

        if "content" not in content_data:
            print(f"No content found for {filename}, skipping.")
            continue

        encoded_content = content_data["content"]
        full_content = base64.b64decode(encoded_content).decode("utf-8")

        try:
            input_payload = None
            if filename.endswith(".ipynb"):
                notebook_dict = json.loads(full_content)
                notebook_dict["path"] = filename
                input_payload = notebook_dict
            else:
                input_payload = {"path": filename, "content": full_content}

            print(f"==================================================")
            print(f"  RUNNING SQL REVIEW FOR: {filename}")
            print(f"==================================================")

            review_result = run_sql_review(input_payload)

            unit_label = "SQL Queries" if filename.endswith(".py") else "SQL Cells"

            print(f"\n=== REVIEW SUMMARY: {filename} ===")
            print(f"{unit_label}: {review_result.get('total_sql_cells')} | AST Errors: {review_result.get('total_ast_parse_errors')} | Rule Violations: {review_result.get('total_violations')}")
            print("=" * 50)

            violations = review_result.get("violations", [])
            if violations:
                print("\nDETERMINISTIC KEYWORD & AST VIOLATIONS:")
                for v in violations:
                    if filename.endswith(".py"):
                        cell_label = f"Line {v.get('line')}"
                    else:
                        cell_label = f"Cell #{v.get('cell_id')} Line {v.get('line')}"
                    print(f"  - {cell_label}: [{v.get('rule_id')}] Keyword '{v.get('current')}' must be uppercase ('{v.get('expected')}')")

            llm_review = review_result.get("llm_review")
            if llm_review:
                print("\nSEMANTIC & PERFORMANCE FINDINGS (LLM):")
                print(llm_review)

            # Build markdown block for this file's PR comment report
            file_report_lines = [f"## File: `{filename}`\n"]
            file_report_lines.append("### Deterministic Violations:")
            if violations:
                for v in violations:
                    if filename.endswith(".py"):
                        cell_label = f"Line {v.get('line')}"
                    else:
                        cell_label = f"Cell #{v.get('cell_id')} Line {v.get('line')}"
                    file_report_lines.append(f"- {cell_label}: [{v.get('rule_id')}] Keyword '{v.get('current')}' must be uppercase ('{v.get('expected')}')")
            else:
                file_report_lines.append("No deterministic violations found.")

            if llm_review:
                if review_result.get("total_ast_parse_errors", 0) > 0:
                    file_report_lines.append("\n### Syntax Errors:")
                else:
                    file_report_lines.append("\n### LLM Review Findings:")
                file_report_lines.append(llm_review)

            file_reports.append("\n".join(file_report_lines))
            print("\n" + "=" * 70 + "\n")
        except Exception as e:
            print(f"Error parsing or reviewing file {filename}: {e}")

    if file_reports:
        combined_report = "# SQL Code Review Report\n\n" + "\n\n---\n\n".join(file_reports)
        
        # Post review report to the GitHub PR
        review_url = f"https://api.github.com/repos/{owner}/{repo_name}/pulls/{pr_number}/reviews"
        review_payload = {
            "body": combined_report,
            "event": "COMMENT"
        }
        post_response = requests.post(review_url, headers=headers, json=review_payload)
        print(f"\nPosted combined review to PR. Status code: {post_response.status_code}")


def main():
    parser = argparse.ArgumentParser(
        description="Databricks SQL Code Review Agent — Manual PR Review"
    )
    parser.add_argument(
        "pr_number",
        type=int,
        help="Pull Request number to review"
    )
    parser.add_argument(
        "--owner",
        default=os.getenv("GITHUB_OWNER"),
        help="GitHub repository owner (default: GITHUB_OWNER from .env)"
    )
    parser.add_argument(
        "--repo",
        default=os.getenv("GITHUB_REPO"),
        help="GitHub repository name (default: GITHUB_REPO from .env)"
    )
    args = parser.parse_args()

    if not args.owner:
        print("Error: GitHub owner not specified. Pass --owner or set GITHUB_OWNER in .env")
        sys.exit(1)
    if not args.repo:
        print("Error: GitHub repo not specified. Pass --repo or set GITHUB_REPO in .env")
        sys.exit(1)
    if not GITHUB_TOKEN:
        print("Error: GITHUB_TOKEN not set in .env")
        sys.exit(1)

    process_pr_review(args.owner, args.repo, args.pr_number)


if __name__ == "__main__":
    main()