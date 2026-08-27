import argparse
import base64
import json
import os
import re
import sys
import requests
from dotenv import load_dotenv

from sql_reviewer.graph.workflow import run_sql_review, convert_ansi_to_carets

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


def get_diff_lines(patch: str) -> set:
    """Parse a unified diff patch string and return the set of line numbers on the RIGHT side."""
    if not patch:
        return set()
    diff_lines = set()
    current_line = 0
    for line in patch.splitlines():
        # Hunk header: @@ -old_start,old_count +new_start,new_count @@
        hunk_match = re.match(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@", line)
        if hunk_match:
            current_line = int(hunk_match.group(1))
            continue
        if line.startswith("+"):
            diff_lines.add(current_line)
            current_line += 1
        elif line.startswith("-"):
            # Deleted lines don't advance the new-file line counter
            pass
        else:
            # Context line (unchanged)
            diff_lines.add(current_line)
            current_line += 1
    return diff_lines


def map_notebook_cell_to_json_line(raw_json: str, cell_id: int, line_within_cell: int) -> int:
    """
    Map a notebook cell_id and line number within that cell to the absolute
    line number in the raw JSON file.
    
    cell_id is 1-based (cell 1 = first cell).
    line_within_cell is 1-based.
    Returns the 1-based JSON line number, or -1 if not found.
    """
    json_lines = raw_json.splitlines()
    cells_found = 0
    in_source = False
    source_start_line = -1

    for i, jline in enumerate(json_lines):
        stripped = jline.strip()
        # Detect cell boundaries by looking for "cell_type"
        if '"cell_type"' in stripped:
            cells_found += 1
            in_source = False
            continue
        # Detect the "source" array start within the current cell
        if '"source"' in stripped and not in_source:
            in_source = True
            source_start_line = -1
            # Check if the source array starts on this same line (e.g., "source": ["..."])
            if "[" in stripped:
                # The first source line is the next JSON line (or this line if inline)
                source_start_line = i + 1  # next line (0-based)
            continue
        if in_source and source_start_line == -1:
            # The "[" is on the next line
            if stripped.startswith("["):
                source_start_line = i + 1  # first content line after "["
                continue
        if in_source and source_start_line >= 0:
            if stripped.startswith("]"):
                # End of source array
                in_source = False
                continue
            if cells_found == cell_id:
                # We're inside the target cell's source array
                # Count source lines from source_start_line
                source_line_index = i - source_start_line
                if source_line_index == line_within_cell - 1:
                    return i + 1  # Convert to 1-based
    return -1


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

    inline_comments_dict = {}
    fallback_items_dict = {}

    for file in reviewable_files:
        filename = file["filename"]
        patch = file.get("patch", "")
        diff_lines = get_diff_lines(patch)

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
            parse_errors = review_result.get("parse_errors", [])
            
            if violations or parse_errors:
                print("\nDETERMINISTIC KEYWORD & AST VIOLATIONS:")
                for v in violations:
                    if filename.endswith(".py"):
                        cell_label = f"Line {v.get('line')}"
                    else:
                        cell_label = f"Cell #{v.get('cell_id')} Line {v.get('line')}"
                    print(f"  - {cell_label}: [{v.get('rule_id')}] Keyword '{v.get('current')}' must be uppercase ('{v.get('expected')}')")
                
                for pe in parse_errors:
                    if filename.endswith(".py"):
                        cell_label = f"Line {pe.get('line')}"
                    else:
                        cell_label = f"Cell #{pe.get('cell_id')} Line {pe.get('line')}"
                    first_line_err = (pe.get("error") or "AST parse error").splitlines()[0].strip()
                    print(f"  - {cell_label}: [AST-ERROR] {first_line_err}")

            llm_review = review_result.get("llm_review")
            if llm_review and isinstance(llm_review, list):
                print("\nSEMANTIC & PERFORMANCE FINDINGS (LLM):")
                for lr in llm_review:
                    if filename.endswith(".py"):
                        cell_label = f"Line {lr.get('line')}"
                    else:
                        cell_label = f"Cell #{lr.get('cell_id')} Line {lr.get('line_within_cell')}"
                    print(f"  - {cell_label}: {lr.get('body')}")

            # --- Build inline comments for this file ---
            for v in violations:
                body = f"[{v.get('rule_id')}] Keyword `{v.get('current')}` must be uppercase (`{v.get('expected')}`)"
                if filename.endswith(".py"):
                    target_line = v.get("line")
                else:
                    target_line = map_notebook_cell_to_json_line(
                        full_content, v.get("cell_id"), v.get("line")
                    )

                if target_line and target_line > 0 and target_line in diff_lines:
                    key = (filename, target_line, "RIGHT")
                    if key not in inline_comments_dict:
                        inline_comments_dict[key] = []
                    inline_comments_dict[key].append(body)
                else:
                    if filename.endswith(".py"):
                        loc = f"**{filename}** Line {v.get('line')}"
                    else:
                        loc = f"**{filename}** Cell #{v.get('cell_id')} Line {v.get('line')}"
                    if loc not in fallback_items_dict:
                        fallback_items_dict[loc] = []
                    fallback_items_dict[loc].append(body)

            # --- Build inline comments for parse errors ---
            parse_errors = review_result.get("parse_errors", [])
            for pe in parse_errors:
                raw_err = pe.get("error") or "AST parse error"
                clean_err = convert_ansi_to_carets(raw_err)

                if filename.endswith(".py"):
                    target_line = pe.get("line") or pe.get("file_line")
                    # Replace query-level line number with absolute file-level line number
                    clean_err = re.sub(r"Line \d+", f"Line {target_line}", clean_err, count=1)
                    body = f"⚠️ **AST Parse Error:**\n```text\n{clean_err}\n```"
                else:
                    cell_line = pe.get("line", 1)
                    # Replace query-level line number with absolute cell-level line number
                    clean_err = re.sub(r"Line \d+", f"Line {cell_line}", clean_err, count=1)
                    body = f"⚠️ **AST Parse Error:**\n```text\n{clean_err}\n```"
                    target_line = map_notebook_cell_to_json_line(
                        full_content, pe.get("cell_id"), cell_line
                    )

                if target_line and target_line > 0 and target_line in diff_lines:
                    key = (filename, target_line, "RIGHT")
                    if key not in inline_comments_dict:
                        inline_comments_dict[key] = []
                    inline_comments_dict[key].append(body)
                else:
                    if filename.endswith(".py"):
                        loc = f"**{filename}** Line {target_line}"
                    else:
                        loc = f"**{filename}** Cell #{pe.get('cell_id')} Line {pe.get('line', 1)}"
                    if loc not in fallback_items_dict:
                        fallback_items_dict[loc] = []
                    fallback_items_dict[loc].append(body)

            # --- Build inline comments for LLM Review ---
            llm_reviews = review_result.get("llm_review", [])
            if isinstance(llm_reviews, list) and review_result.get("total_ast_parse_errors", 0) == 0:
                for lr in llm_reviews:
                    body = f"🤖 **LLM Review:** {lr.get('body')}"
                    
                    if filename.endswith(".py"):
                        target_line = lr.get("line")
                    else:
                        target_line = map_notebook_cell_to_json_line(
                            full_content, lr.get("cell_id"), lr.get("line_within_cell", 1)
                        )
                        
                    if target_line and target_line > 0 and target_line in diff_lines:
                        key = (filename, target_line, "RIGHT")
                        
                        # Duplicate filtering
                        is_duplicate = False
                        if "[RULE-001]" in body:
                            existing_bodies = inline_comments_dict.get(key, [])
                            if any("[RULE-001]" in b for b in existing_bodies):
                                is_duplicate = True
                                
                        if not is_duplicate:
                            if key not in inline_comments_dict:
                                inline_comments_dict[key] = []
                            inline_comments_dict[key].append(body)
                    else:
                        if filename.endswith(".py"):
                            loc = f"**{filename}** Line {lr.get('line')}"
                        else:
                            loc = f"**{filename}** Cell #{lr.get('cell_id')} Line {lr.get('line_within_cell', 1)}"
                            
                        # Duplicate filtering
                        is_duplicate = False
                        if "[RULE-001]" in body:
                            existing_bodies = fallback_items_dict.get(loc, [])
                            if any("[RULE-001]" in b for b in existing_bodies):
                                is_duplicate = True
                                
                        if not is_duplicate:
                            if loc not in fallback_items_dict:
                                fallback_items_dict[loc] = []
                            fallback_items_dict[loc].append(body)

            print("\n" + "=" * 70 + "\n")
        except Exception as e:
            print(f"Error parsing or reviewing file {filename}: {e}")

    # --- Convert dicts to lists ---
    all_inline_comments = []
    for (path, line, side), bodies in inline_comments_dict.items():
        all_inline_comments.append({
            "path": path,
            "line": line,
            "side": side,
            "body": "\n".join(f"- {b}" for b in bodies)
        })

    fallback_items = []
    for loc, bodies in fallback_items_dict.items():
        if loc.startswith("### LLM"):
            fallback_items.append(f"{loc}:\n" + "\n".join(bodies))
        else:
            fallback_items.append(f"{loc}:\n" + "\n".join(f"  - {b}" for b in bodies))

    # --- Post single review with inline comments + fallback summary ---
    if all_inline_comments or fallback_items:
        summary_body = ""
        if fallback_items:
            summary_body = "# SQL Code Review Report\n\nThe following items could not be posted as inline comments (lines not in the PR diff):\n\n" + "\n\n".join(fallback_items)
        else:
            summary_body = "# SQL Code Review Report\n\nAll violations posted as inline comments."

        review_url = f"https://api.github.com/repos/{owner}/{repo_name}/pulls/{pr_number}/reviews"
        review_payload = {
            "commit_id": head_sha,
            "event": "COMMENT",
            "body": summary_body,
            "comments": all_inline_comments
        }
        post_response = requests.post(review_url, headers=headers, json=review_payload)
        print(f"\nPosted review to PR. Status code: {post_response.status_code}")
        if post_response.status_code != 200:
            print(f"Response: {post_response.json()}")
        else:
            inline_count = len(all_inline_comments)
            fallback_count = len(fallback_items)
            print(f"  → {inline_count} inline comment(s), {fallback_count} fallback item(s)")


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