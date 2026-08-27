import os
from typing import Any, Dict, List
from sql_reviewer.parser.notebook_parser import extract_sql_from_python_code, extract_sql_from_wrappers, SQLCell


class PythonParser:
    """
    Parser for standalone Python files (.py).
    Extracts SQL queries from spark.sql("...") calls using AST.
    """

    def __init__(self, file_path_or_str: Any):
        if isinstance(file_path_or_str, str):
            if os.path.exists(file_path_or_str):
                self.file_path = file_path_or_str
                self.file_id = os.path.basename(file_path_or_str)
                with open(file_path_or_str, "r", encoding="utf-8") as f:
                    self.file_content = f.read()
            else:
                self.file_path = "in_memory_file.py"
                self.file_id = "in_memory_file.py"
                self.file_content = file_path_or_str
        elif isinstance(file_path_or_str, dict):
            # Support dict from webhook payload or similar
            self.file_path = file_path_or_str.get("path", "in_memory_file.py")
            self.file_id = os.path.basename(self.file_path)
            self.file_content = file_path_or_str.get("content", "")
        else:
            raise ValueError("Invalid Python parser input. Expected file path/string or dict.")
        self.notebook_id = self.file_id

    def extract_sql_cells(self) -> List[Dict[str, Any]]:
        sql_cells: List[Dict[str, Any]] = []
        extracted = extract_sql_from_python_code(self.file_content)
        extracted.extend(extract_sql_from_wrappers(self.file_content))

        for q in extracted:
            lineno = q["line_number"]
            # For standalone files, we represent the "cell_id" as the line number of spark.sql call
            cell_obj = SQLCell(
                cell_id=lineno,
                notebook_id=self.file_id,
                sql_content=q["sql_content"],
                original_source=self.file_content,
                line_offset=lineno - 1
            )
            sql_cells.append(cell_obj.to_dict())

        return sql_cells
