import re
from typing import Any, Dict, List, Set


class ContextBuilder:
    """
    Constructs a compact context payload for the LLM review node.
    Includes relevant SQL, active rules, violations, and cell metadata.
    Excludes raw AST details and non-SQL notebook content.
    Filters content to only show modified SQL cells and lines when a diff is provided.
    """

    def _get_modified_lines_python(self, patch: str) -> Set[int]:
        """Parses a unified diff for .py files and returns modified line numbers."""
        modified_lines = set()
        if not patch:
            return modified_lines

        hunk_re = re.compile(r'^@@ -\d+,?\d* \+(\d+),?(\d*) @@')
        current_line = 0
        in_hunk = False

        for line in patch.splitlines():
            match = hunk_re.match(line)
            if match:
                current_line = int(match.group(1))
                in_hunk = True
            elif in_hunk:
                if line.startswith('+') and not line.startswith('+++'):
                    modified_lines.add(current_line)
                    current_line += 1
                elif line.startswith('-'):
                    pass
                else:
                    current_line += 1
        return modified_lines

    def _get_modified_content_ipynb(self, patch: str) -> Set[str]:
        """Extracts normalized added lines from a unified diff of a .ipynb JSON file."""
        added_lines = set()
        if not patch:
            return added_lines

        for line in patch.splitlines():
            if line.startswith('+') and not line.startswith('+++'):
                cleaned = line[1:].strip()
                # If wrapped in JSON string quotes
                if cleaned.startswith('"'):
                    if cleaned.endswith('",'):
                        cleaned = cleaned[1:-2]
                    elif cleaned.endswith('"'):
                        cleaned = cleaned[1:-1]
                    cleaned = cleaned.replace('\\"', '"').replace('\\n', '').replace('\\t', ' ').replace('\\\\', '\\')
                normalized = re.sub(r'\s+', ' ', cleaned).strip()
                if normalized:
                    added_lines.add(normalized)
        return added_lines

    def build_context(
        self,
        notebook_id: str,
        sql_cells: List[Dict[str, Any]],
        ast_results: List[Dict[str, Any]],
        violations: List[Dict[str, Any]],
        diff: str = ""
    ) -> str:
        has_diff = bool(diff and diff.strip())
        is_python_file = notebook_id.endswith(".py")

        if is_python_file:
            modified_lines_py = self._get_modified_lines_python(diff)
            ipynb_added_lines = set()
        else:
            modified_lines_py = set()
            ipynb_added_lines = self._get_modified_content_ipynb(diff)

        ast_map = {res["cell_id"]: res for res in ast_results}
        violations_by_cell: Dict[int, List[Dict[str, Any]]] = {}

        for v in violations:
            c_id = v["cell_id"]
            violations_by_cell.setdefault(c_id, []).append(v)

        lines = [
            "=== DATABRICKS SQL CODE REVIEW CONTEXT ===",
            f"Notebook ID: {notebook_id}",
            f"Total Analyzed SQL Cells: {len(sql_cells)}",
            f"Total Deterministic Violations: {len(violations)}",
            "",
            "--- ACTIVE CODING STANDARDS RULES ---",
            "RULE-001: All SQL keywords MUST be uppercase (e.g., SELECT, FROM, WHERE, JOIN, GROUP BY, ORDER BY, HAVING, USE, CATALOG, SCHEMA).",
            "RULE-002: Prohibit abbreviated/short-form column aliases and identifiers (e.g., use 'amount' instead of 'amt', 'transaction' instead of 'txn', 'customer' instead of 'cust', 'quantity' instead of 'qty', 'date' instead of 'dt').",
            ""
        ]

        included_cells_count = 0

        for cell in sql_cells:
            cell_id = cell["cell_id"]
            ast_res = ast_map.get(cell_id, {})
            cell_violations = violations_by_cell.get(cell_id, [])
            parse_error = ast_res.get("error")

            sql_lines = cell["sql_content"].splitlines()
            start_line = cell.get("line_offset", 0) + 1
            end_line = start_line + len(sql_lines) - 1
            cell_line_set = set(range(start_line, end_line + 1))

            # Determine which lines in this cell are modified
            modified_in_this_cell: Set[int] = set()
            if has_diff:
                if is_python_file:
                    modified_in_this_cell = cell_line_set.intersection(modified_lines_py)
                else:
                    for line_idx, line_str in enumerate(sql_lines):
                        norm_str = re.sub(r'\s+', ' ', line_str).strip()
                        if norm_str and norm_str in ipynb_added_lines:
                            modified_in_this_cell.add(line_idx + start_line)

                # Skip cell if no modified lines are found in this cell
                if not modified_in_this_cell:
                    continue

            included_cells_count += 1

            if is_python_file:
                lines.append(f"--- FILE: {notebook_id} Line {cell_id} ---")
            else:
                lines.append(f"--- CELL #{cell_id} ---")
            lines.append("SQL Code:")

            # Prefix each line with its absolute line number
            for line_idx, line in enumerate(sql_lines):
                abs_line = line_idx + start_line
                prefix = "[Line " + str(abs_line) + "]"
                if has_diff and abs_line in modified_in_this_cell:
                    prefix = "[Line " + str(abs_line) + "][MODIFIED]"
                lines.append(f"{prefix} {line}")
            lines.append("")

            if parse_error:
                lines.append(f"[PARSE ERROR]: {parse_error}")

            # Filter violations to only modified lines if diff is present
            if has_diff:
                cell_violations = [v for v in cell_violations if v["line"] in modified_in_this_cell]

            if cell_violations:
                lines.append(f"Detected Deterministic Violations ({len(cell_violations)}):")
                for v in cell_violations:
                    lines.append(
                        f"  - Line {v['line']}: Keyword '{v['current']}' must be uppercase ('{v['expected']}')"
                    )
            elif not parse_error:
                lines.append("Deterministic Check: Passed RULE-001 keyword uppercase check.")

            lines.append("")

        if has_diff:
            lines.insert(3, f"Total Modified/Changed SQL Cells Included: {included_cells_count}")

        lines.append("=== END OF CONTEXT ===")
        return "\n".join(lines)

