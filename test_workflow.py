from sql_reviewer.graph.workflow import run_sql_review

if __name__ == "__main__":
    # Test valid SQL
    print("--- Test 1: Valid SQL ---")
    mock_notebook = {
        "cells": [
            {
                "cell_type": "code",
                "source": ["%sql\n", "SELECT * FROM users;"]
            }
        ]
    }
    res = run_sql_review(mock_notebook)
    print("Final Output:", res.get("llm_review"))
    print("Parse Errors:", res.get("total_ast_parse_errors"))

