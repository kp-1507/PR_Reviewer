import json
import os
import ast
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, asdict


def resolve_ast_string(node, variables) -> tuple[Optional[str], int]:
    """Recursively resolves AST nodes into strings, returning (resolved_text, line_number)."""
    lineno = getattr(node, "lineno", 1)
    
    # Resolve variable references
    if isinstance(node, ast.Name) and node.id in variables:
        return resolve_ast_string(variables[node.id], variables)
        
    # Resolve method calls (e.g., string.format() or string.replace())
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        return resolve_ast_string(node.func.value, variables)
        
    # Resolve static constants (Python 3.8+)
    if isinstance(node, ast.Constant):
        return str(node.value), lineno
    elif hasattr(ast, "Str") and isinstance(node, ast.Str):  # Fallback for older Python
        return node.s, lineno
        
    # Resolve f-strings (JoinedStr)
    if isinstance(node, ast.JoinedStr):
        parts = []
        for val in node.values:
            if isinstance(val, ast.Constant) and isinstance(val.value, str):
                parts.append(val.value)
            elif hasattr(ast, "Str") and isinstance(val, ast.Str):
                parts.append(val.s)
            elif isinstance(val, ast.FormattedValue):
                resolved_str, _ = resolve_ast_string(val.value, variables)
                if resolved_str is not None:
                    parts.append(str(resolved_str))
                else:
                    parts.append("__IDENTIFIER_PLACEHOLDER__")
            else:
                parts.append("__IDENTIFIER_PLACEHOLDER__")
        return "".join(parts), lineno
        
    # Resolve string concatenation (BinOp with Add)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left_str, left_line = resolve_ast_string(node.left, variables)
        right_str, _ = resolve_ast_string(node.right, variables)
        
        left_str = left_str if left_str is not None else "__IDENTIFIER_PLACEHOLDER__"
        right_str = right_str if right_str is not None else "__IDENTIFIER_PLACEHOLDER__"
        
        return left_str + right_str, left_line or lineno
        
    return None, lineno


def extract_sql_from_python_code(python_code: str) -> list[dict]:
    """Parses Python source code and extracts all spark.sql(...) queries."""
    extracted_queries = []
    try:
        tree = ast.parse(python_code)
    except Exception as e:
        print(f"AST Parse Error: {e}")
        return []

    # Map variable assignments: x = "SELECT ..."
    variables = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    variables[target.id] = node.value

    # Find and extract spark.sql(...) arguments
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "sql"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "spark"
            and node.args
        ):
            sql_text, lineno = resolve_ast_string(node.args[0], variables)
            if sql_text and sql_text.strip():
                extracted_queries.append({
                    "sql_content": sql_text,
                    "line_number": lineno
                })
                
    return extracted_queries


def extract_sql_from_wrappers(python_code: str) -> list[dict]:
    """Parses Python code to dynamically detect and extract SQL from custom wrapper functions."""
    extracted_queries = []
    try:
        tree = ast.parse(python_code)
        
        # 1. Track variables
        variables = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        variables[target.id] = node.value

        # 2. Find SQL Wrapper Functions
        sql_wrappers = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                for child in ast.walk(node):
                    if (
                        isinstance(child, ast.Call)
                        and isinstance(child.func, ast.Attribute)
                        and child.func.attr == "sql"
                        and isinstance(child.func.value, ast.Name)
                        and child.func.value.id == "spark"
                        and child.args
                    ):
                        arg = child.args[0]
                        if isinstance(arg, ast.Name):
                            for idx, param in enumerate(node.args.args):
                                if param.arg == arg.id:
                                    sql_wrappers[node.name] = idx
                                    break

        # 3. Extract calls to those wrappers
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in sql_wrappers:
                param_idx = sql_wrappers[node.func.id]
                if len(node.args) > param_idx:
                    passed_arg = node.args[param_idx]
                    sql_text, lineno = resolve_ast_string(passed_arg, variables)
                    if sql_text and sql_text.strip():
                        extracted_queries.append({
                            "sql_content": sql_text,
                            "line_number": getattr(node, "lineno", lineno)
                        })
                        
    except Exception:
        pass
        
    return extracted_queries

@dataclass
class SQLCell:
    cell_id: int
    notebook_id: str
    sql_content: str
    original_source: str
    line_offset: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class NotebookParser:
    """
    Parser for Databricks Jupyter Notebooks (.ipynb).
    Extracts SQL cells while preserving cell IDs, line offsets, and metadata.
    Ignores non-SQL cells (Python, Markdown, Shell, etc.).
    """

    def __init__(self, notebook_path_or_dict: Any):
        if isinstance(notebook_path_or_dict, str):
            self.notebook_path = notebook_path_or_dict
            self.notebook_id = os.path.basename(notebook_path_or_dict)
            with open(notebook_path_or_dict, "r", encoding="utf-8") as f:
                self.notebook_data = json.load(f)
        elif isinstance(notebook_path_or_dict, dict):
            self.notebook_path = notebook_path_or_dict.get("path", "in_memory_notebook.ipynb")
            self.notebook_id = os.path.basename(self.notebook_path)
            self.notebook_data = notebook_path_or_dict
        else:
            raise ValueError("Invalid notebook input. Expected file path (str) or loaded dict.")
        
        # print(f"[System Log] Exact JSON Payload:\n{json.dumps(self.notebook_data, indent=2)}")

    def extract_sql_cells(self) -> List[Dict[str, Any]]:
        sql_cells: List[Dict[str, Any]] = []
        cells = self.notebook_data.get("cells", [])
        
        # Check notebook-level default language metadata
        nb_metadata = self.notebook_data.get("metadata", {})
        nb_lang = (
            nb_metadata.get("language_info", {}).get("name", "") or
            nb_metadata.get("language", "") or
            nb_metadata.get("databricks", {}).get("language", "")
        ).lower()

        sql_cell_count = 0
        for idx, cell in enumerate(cells, start=1):
            cell_type = cell.get("cell_type", "")
            if cell_type != "code":
                continue

            raw_source = cell.get("source", "")
            if isinstance(raw_source, list):
                source_text = "".join(raw_source)
            else:
                source_text = str(raw_source)

            if not source_text.strip():
                continue

            metadata = cell.get("metadata", {})
            language_meta = metadata.get("language", "").lower()
            vscode_lang = metadata.get("vscode", {}).get("languageId", "").lower()

            is_sql_cell = False
            is_python_cell = False
            has_other_magic = False
            cleaned_sql = source_text
            cleaned_python = source_text

            lines = source_text.splitlines(keepends=True)
            first_non_empty_line_idx = -1
            for line_i, line_content in enumerate(lines):
                if line_content.strip():
                    first_non_empty_line_idx = line_i
                    break

            if first_non_empty_line_idx != -1:
                first_line = lines[first_non_empty_line_idx].strip()
                if first_line.startswith("%sql"):
                    is_sql_cell = True
                    # Replace %sql line with blank line to preserve line numbers 1:1
                    lines[first_non_empty_line_idx] = "\n"
                    cleaned_sql = "".join(lines)
                elif first_line.startswith("%python") or first_line.startswith("%py"):
                    is_python_cell = True
                    # Replace %python line with blank line to preserve line numbers 1:1
                    lines[first_non_empty_line_idx] = "\n"
                    
                    for i in range(len(lines)):
                        stripped = lines[i].strip()
                        if stripped.startswith("!") or stripped.startswith("%"):
                            lines[i] = "# " + lines[i]
                            
                    cleaned_python = "".join(lines)
                elif first_line.startswith("%"):
                    # Other magic command (%sh, %md, %r, etc.)
                    has_other_magic = True

            if not is_sql_cell and not is_python_cell and not has_other_magic:
                if language_meta == "sql" or vscode_lang == "sql" or nb_lang == "sql":
                    is_sql_cell = True
                else:
                    is_python = (
                        language_meta in ("python", "py") or
                        vscode_lang in ("python", "py") or
                        nb_lang in ("python", "py") or
                        not (language_meta or vscode_lang or nb_lang)
                    )
                    if is_python:
                        is_python_cell = True
                        for i in range(len(lines)):
                            stripped = lines[i].strip()
                            if stripped.startswith("!") or stripped.startswith("%"):
                                lines[i] = "# " + lines[i]
                        cleaned_python = "".join(lines)

            if is_sql_cell and cleaned_sql.strip():
                sql_cell_count += 1
                cell_obj = SQLCell(
                    cell_id=idx,
                    notebook_id=self.notebook_id,
                    sql_content=cleaned_sql,
                    original_source=source_text,
                    line_offset=0
                )
                sql_cells.append(cell_obj.to_dict())

            elif is_python_cell:
                extracted = extract_sql_from_python_code(cleaned_python)
                extracted.extend(extract_sql_from_wrappers(cleaned_python))
                for q in extracted:
                    cell_obj = SQLCell(
                        cell_id=idx,
                        notebook_id=self.notebook_id,
                        sql_content=q["sql_content"],
                        original_source=source_text,
                        line_offset=q["line_number"] - 1
                    )
                    sql_cells.append(cell_obj.to_dict())

        return sql_cells

