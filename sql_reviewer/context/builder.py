import re
from typing import Any, Dict, List, Set


class ContextBuilder:
    """
    Constructs a compact context payload for the LLM review node.
    Includes relevant SQL, active rules, violations, and cell metadata.
    Excludes raw AST details and non-SQL notebook content.
    Filters content to only show modified SQL cells and lines when a diff is provided.
    """

    def _get_modified_lines(self, patch: str) -> Set[int]:
        """Parses a unified diff and returns line numbers modified in the new file."""
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
                if line.startswith('+'):
                    modified_lines.add(current_line)
                    current_line += 1
                elif line.startswith('-'):
                    pass
                else:
                    current_line += 1
        return modified_lines

    def build_context(
        self,
        notebook_id: str,
        sql_cells: List[Dict[str, Any]],
        ast_results: List[Dict[str, Any]],
        violations: List[Dict[str, Any]],
        diff: str = ""
    ) -> str:
        has_diff = bool(diff and diff.strip())
        modified_lines = self._get_modified_lines(diff)

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

        is_python_file = notebook_id.endswith(".py")
        included_cells_count = 0

        for cell in sql_cells:
            cell_id = cell["cell_id"]
            ast_res = ast_map.get(cell_id, {})
            cell_violations = violations_by_cell.get(cell_id, [])
            parse_error = ast_res.get("error")

            # Check if this cell overlaps with modified lines
            sql_lines = cell["sql_content"].splitlines()
            start_line = cell.get("line_offset", 0) + 1
            end_line = start_line + len(sql_lines) - 1
            cell_line_set = set(range(start_line, end_line + 1))

            if has_diff and not cell_line_set.intersection(modified_lines):
                # Skip unmodified cells entirely to save tokens
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
                # Mark modified lines with a '+' to help the LLM identify changes
                prefix = "[Line " + str(abs_line) + "]"
                if has_diff and abs_line in modified_lines:
                    prefix = "[Line " + str(abs_line) + "][MODIFIED]"
                lines.append(f"{prefix} {line}")
            lines.append("")

            if parse_error:
                lines.append(f"[PARSE ERROR]: {parse_error}")

            # Filter violations to only modified lines if diff is present
            if has_diff:
                cell_violations = [v for v in cell_violations if v["line"] in modified_lines]

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

