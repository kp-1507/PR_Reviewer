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
        "file_path",
        nargs="?",
        default="notebooks/sample_databricks_notebook.ipynb",
        help="Path to the Databricks .ipynb notebook file or .py python script (default: notebooks/sample_databricks_notebook.ipynb)"
    )
    args = parser.parse_args()

    input_path = os.path.abspath(args.file_path)
    if not os.path.exists(input_path):
        print(f"Error: File not found at '{input_path}'")
        sys.exit(1)

    is_py = input_path.endswith(".py")
    file_label = "Python File" if is_py else "Notebook"
    unit_label = "SQL Queries" if is_py else "SQL Cells"

    print("=" * 70)
    print("      DATABRICKS SQL CODE REVIEW AGENT (V1)")
    print("=" * 70)
    print(f"Analyzing {file_label}: {input_path}\n")

    result = run_sql_review(input_path)

    print("=== REVIEW SUMMARY METRICS ===")
    print(f"{file_label} ID           : {result.get('notebook_id')}")
    print(f"Total {unit_label}       : {result.get('total_sql_cells')}")
    print(f"AST Parse Errors      : {result.get('total_ast_parse_errors')}")
    print(f"Total Violations      : {result.get('total_violations')}")
    print("=" * 70 + "\n")

    if result.get("violations"):
        print("=== STRUCTURED VIOLATIONS (RULE-001) ===")
        print(json.dumps(result["violations"], indent=2))
        print("\n" + "=" * 70 + "\n")



    print("=== LLM REVIEW OUTPUT ===")
    print(result.get("llm_review"))
    print("\n" + "=" * 70)


if __name__ == "__main__":
    main()
