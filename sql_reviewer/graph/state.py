from typing import Any, Dict, List, Optional, TypedDict


class ReviewState(TypedDict):
    """
    Typed state for the SQL Code Review Agent LangGraph workflow.
    """
    notebook: Any
    sql_cells: List[Dict[str, Any]]
    ast_results: List[Dict[str, Any]]
    violations: List[Dict[str, Any]]
    context: str
    llm_review: str
    final_result: Dict[str, Any]
