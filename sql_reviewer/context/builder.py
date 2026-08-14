from typing import Any, Dict, List


class ContextBuilder:
    """
    Constructs a compact context payload for the LLM review node.
    Includes relevant SQL, active rules, violations, and cell metadata.
    Excludes raw AST details and non-SQL notebook content.
    """

    def build_context(
        self,
        notebook_id: str,
        sql_cells: List[Dict[str, Any]],
        ast_results: List[Dict[str, Any]],
        violations: List[Dict[str, Any]]
    ) -> str:
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

        for cell in sql_cells:
            cell_id = cell["cell_id"]
            sql_text = cell["sql_content"].strip()
            ast_res = ast_map.get(cell_id, {})
            cell_violations = violations_by_cell.get(cell_id, [])
            parse_error = ast_res.get("error")

            lines.append(f"--- CELL #{cell_id} ---")
            lines.append("SQL Code:")
            lines.append(sql_text)
            lines.append("")

            if parse_error:
                lines.append(f"[PARSE ERROR]: {parse_error}")

            if cell_violations:
                lines.append(f"Detected Deterministic Violations ({len(cell_violations)}):")
                for v in cell_violations:
                    lines.append(
                        f"  - Line {v['line']}: Keyword '{v['current']}' must be uppercase ('{v['expected']}')"
                    )
            elif not parse_error:
                lines.append("Deterministic Check: Passed RULE-001 keyword uppercase check.")

            lines.append("")

        lines.append("=== END OF CONTEXT ===")
        return "\n".join(lines)
