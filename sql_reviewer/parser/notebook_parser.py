import json
import os
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, asdict


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
            has_other_magic = False
            cleaned_sql = source_text

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
                elif first_line.startswith("%"):
                    # Other magic command (%py, %python, %sh, %md, %r, etc.)
                    is_sql_cell = False
                    has_other_magic = True

            if not is_sql_cell and not has_other_magic and (language_meta == "sql" or vscode_lang == "sql" or nb_lang == "sql"):
                is_sql_cell = True

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

        return sql_cells

