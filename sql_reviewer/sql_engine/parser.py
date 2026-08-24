from typing import Any, Dict, List, Optional
import sqlglot
from sqlglot.errors import ParseError


class SQLParser:
    """
    SQLGlot-based parser for Databricks SQL dialect.
    Parses SQL code into AST expressions and records parse failures safely.
    """

    def __init__(self, dialect: str = "databricks"):
        self.dialect = dialect

    def parse_cell(self, sql_cell: Dict[str, Any]) -> Dict[str, Any]:
        cell_id = sql_cell.get("cell_id")
        sql_content = sql_cell.get("sql_content", "")

        try:
            expressions = sqlglot.parse(sql_content, read=self.dialect)
            # Filter out None expressions if any
            valid_expressions = [exp for exp in expressions if exp is not None]
            return {
                "cell_id": cell_id,
                "status": "success",
                "ast": [repr(exp) for exp in valid_expressions],
                "expressions": valid_expressions,
                "error": None
            }
        except Exception as e:
            return {
                "cell_id": cell_id,
                "status": "error",
                "ast": None,
                "expressions": [],
                "error": str(e)
            }


def parse_sql_cell(sql_cell: Dict[str, Any], dialect: str = "databricks") -> Dict[str, Any]:
    parser = SQLParser(dialect=dialect)
    return parser.parse_cell(sql_cell)
