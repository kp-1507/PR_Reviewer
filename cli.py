import sys
import os
import json
import argparse
from dotenv import load_dotenv

load_dotenv()

from sql_reviewer.graph.workflow import run_sql_review


def main():
    parser = argparse.ArgumentParser(description="Databricks SQL Code Review Agent (V1)")
    parser.add_argument(
        "notebook",
        nargs="?",
        default="notebooks/sample_databricks_notebook.ipynb",
        help="Path to the Databricks .ipynb notebook file (default: notebooks/sample_databricks_notebook.ipynb)"
    )
    args = parser.parse_args()

    notebook_path = os.path.abspath(args.notebook)
    if not os.path.exists(notebook_path):
        print(f"Error: Notebook file not found at '{notebook_path}'")
        sys.exit(1)

    print("=" * 70)
    print("      DATABRICKS SQL CODE REVIEW AGENT (V1)")
    print("=" * 70)
    print(f"Analyzing Notebook: {notebook_path}\n")

    result = run_sql_review(notebook_path)

    print("=== REVIEW SUMMARY METRICS ===")
    print(f"Notebook ID           : {result.get('notebook_id')}")
    print(f"Total SQL Cells       : {result.get('total_sql_cells')}")
    print(f"AST Parse Errors      : {result.get('total_ast_parse_errors')}")
    print(f"Total Violations      : {result.get('total_violations')}")
    print("=" * 70 + "\n")

    if result.get("violations"):
        print("=== STRUCTURED VIOLATIONS (RULE-001) ===")
        print(json.dumps(result["violations"], indent=2))
        print("\n" + "=" * 70 + "\n")

    if result.get("parse_errors"):
        print("=== AST PARSE ERRORS ===")
        print(json.dumps(result["parse_errors"], indent=2))
        print("\n" + "=" * 70 + "\n")

    print("=== LLM REVIEW OUTPUT ===")
    print(result.get("llm_review"))
    print("\n" + "=" * 70)


if __name__ == "__main__":
    main()
