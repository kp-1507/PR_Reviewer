from typing import Any, Dict, List
import langchain
# if not hasattr(langchain, "debug"):
#     langchain.debug = False
# if not hasattr(langchain, "verbose"):
#     langchain.verbose = False
# if not hasattr(langchain, "llm_cache"):
#     langchain.llm_cache = None

from langgraph.graph import StateGraph, START, END

from sql_reviewer.parser.notebook_parser import NotebookParser
from sql_reviewer.parser.python_parser import PythonParser
from sql_reviewer.sql_engine.parser import SQLParser
from sql_reviewer.sql_engine.engine import RuleEngine
from sql_reviewer.context.builder import ContextBuilder
from sql_reviewer.llm.reviewer import LLMReviewer
from sql_reviewer.graph.state import ReviewState


def get_parser(notebook_input: Any):
    path = ""
    if isinstance(notebook_input, str):
        path = notebook_input
    elif isinstance(notebook_input, dict):
        path = notebook_input.get("path", "")
        
    if path.endswith(".py"):
        return PythonParser(notebook_input)
    return NotebookParser(notebook_input)


def extract_sql_func(state: ReviewState) -> Dict[str, Any]:
    notebook_input = state["notebook"]
    parser = get_parser(notebook_input)
    sql_cells = parser.extract_sql_cells()
    return {"sql_cells": sql_cells}


def parse_sql_func(state: ReviewState) -> Dict[str, Any]:
    sql_cells = state.get("sql_cells", [])
    sql_parser = SQLParser(dialect="databricks")
    ast_results = [sql_parser.parse_cell(cell) for cell in sql_cells]
    return {"ast_results": ast_results}


def evaluate_rules_func(state: ReviewState) -> Dict[str, Any]:
    sql_cells = state.get("sql_cells", [])
    ast_results = state.get("ast_results", [])
    rule_engine = RuleEngine()
    violations = rule_engine.evaluate_all(sql_cells, ast_results)
    return {"violations": violations}


def build_context_func(state: ReviewState) -> Dict[str, Any]:
    notebook_input = state["notebook"]
    parser = get_parser(notebook_input)
    notebook_id = parser.notebook_id
    sql_cells = state.get("sql_cells", [])
    ast_results = state.get("ast_results", [])
    violations = state.get("violations", [])

    builder = ContextBuilder()
    context = builder.build_context(notebook_id, sql_cells, ast_results, violations)
    return {"context": context}


def should_run_llm(state: ReviewState) -> str:
    """
    Early exit condition: If AST parsing failed for any cell,
    bypass LLM review to save LLM tokens.
    """
    ast_results = state.get("ast_results", [])
    has_ast_errors = any(res.get("status") == "error" for res in ast_results)

    if has_ast_errors:
        return "compile_final_result"
    return "run_llm_review"


def llm_review_func(state: ReviewState) -> Dict[str, Any]:
    context = state.get("context", "")
    violations = state.get("violations", [])
    reviewer = LLMReviewer()
    llm_review = reviewer.review(context, violations)
    return {"llm_review": llm_review}


def final_result_func(state: ReviewState) -> Dict[str, Any]:
    notebook_input = state["notebook"]
    parser = get_parser(notebook_input)
    notebook_id = parser.notebook_id
    sql_cells = state.get("sql_cells", [])
    ast_results = state.get("ast_results", [])
    violations = state.get("violations", [])
    context = state.get("context", "")
    llm_review = state.get("llm_review", "")

    parse_errors = [res for res in ast_results if res.get("status") == "error"]

    if parse_errors and not llm_review:
        llm_review = (
            "=== LLM REVIEW SKIPPED ===\n"
            f"Notice: Skipped LLM review due to {len(parse_errors)} AST parsing error(s) in notebook cells. "
            "Resolve syntax errors before generating LLM summary."
        )

    final_result = {
        "notebook_id": notebook_id,
        "total_sql_cells": len(sql_cells),
        "total_ast_parse_errors": len(parse_errors),
        "total_violations": len(violations),
        "parse_errors": parse_errors,
        "violations": violations,
        "context": context,
        "llm_review": llm_review,
        "status": "completed"
    }

    return {"final_result": final_result}


def create_sql_review_workflow():
    workflow = StateGraph(ReviewState)

    # Add Nodes (distinct names from state keys)
    workflow.add_node("extract_sql", extract_sql_func)
    workflow.add_node("parse_sql", parse_sql_func)
    workflow.add_node("evaluate_rules", evaluate_rules_func)
    workflow.add_node("build_context", build_context_func)
    workflow.add_node("run_llm_review", llm_review_func)
    workflow.add_node("compile_final_result", final_result_func)

    # Build Edges
    workflow.add_edge(START, "extract_sql")
    workflow.add_edge("extract_sql", "parse_sql")
    workflow.add_edge("parse_sql", "evaluate_rules")
    workflow.add_edge("evaluate_rules", "build_context")

    # Conditional edge after build_context
    workflow.add_conditional_edges(
        "build_context",
        should_run_llm,
        {
            "run_llm_review": "run_llm_review",
            "compile_final_result": "compile_final_result"
        }
    )

    workflow.add_edge("run_llm_review", "compile_final_result")
    workflow.add_edge("compile_final_result", END)

    return workflow.compile()


def run_sql_review(notebook_path_or_dict: Any) -> Dict[str, Any]:
    app = create_sql_review_workflow()
    initial_state: ReviewState = {
        "notebook": notebook_path_or_dict,
        "sql_cells": [],
        "ast_results": [],
        "violations": [],
        "context": "",
        "llm_review": "",
        "final_result": {}
    }
    result_state = app.invoke(initial_state)
    return result_state.get("final_result", {})
