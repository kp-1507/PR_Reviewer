from typing import Any, Dict, List
import sqlglot
from sqlglot import TokenType
from sqlglot.dialects import Dialect
from sql_reviewer.sql_engine.rules.base import BaseRule


class Rule001KeywordsUppercase(BaseRule):
    """
    RULE-001: All SQL keywords must be uppercase.
    Differentiates keywords from string literals, comments, identifiers, table names, and column names.
    """

    NON_KEYWORD_TYPES = {
        TokenType.VAR,
        TokenType.IDENTIFIER,
        TokenType.STRING,
        TokenType.RAW_STRING,
        TokenType.HEREDOC_STRING,
        TokenType.NATIONAL_STRING,
        TokenType.HEX_STRING,
        TokenType.BYTE_STRING,
        TokenType.BIT_STRING,
        TokenType.NUMBER,
        TokenType.INT,
        TokenType.FLOAT,
        TokenType.COMMA,
        TokenType.SEMICOLON,
        TokenType.DOT,
        TokenType.L_PAREN,
        TokenType.R_PAREN,
        TokenType.L_BRACKET,
        TokenType.R_BRACKET,
        TokenType.EQ,
        TokenType.NEQ,
        TokenType.PLUS,
        TokenType.DASH,
        TokenType.STAR,
        TokenType.SLASH,
        TokenType.COLON,
        TokenType.AMP,
        TokenType.COMMENT,
    }

    def __init__(self):
        super().__init__(
            rule_id="RULE-001",
            description="All SQL keywords must be uppercase."
        )
        self.dialect = Dialect.get("databricks")()
        self.tokenizer = self.dialect.Tokenizer()

    def evaluate(self, sql_cell: Dict[str, Any], ast_result: Dict[str, Any]) -> List[Dict[str, Any]]:
        violations: List[Dict[str, Any]] = []
        cell_id = sql_cell.get("cell_id", 0)
        sql_content = sql_cell.get("sql_content", "")
        line_offset = sql_cell.get("line_offset", 0)

        if not sql_content.strip():
            return violations

        try:
            tokens = self.tokenizer.tokenize(sql_content)
        except Exception:
            # Tokenization failure handled as parse error by SQLParser
            return violations

        for token in tokens:
            text = token.text
            if not text:
                continue

            text_upper = text.upper()
            is_in_kw_dict = text_upper in self.tokenizer.KEYWORDS

            # Check if token is a true keyword
            if token.token_type not in self.NON_KEYWORD_TYPES and is_in_kw_dict:
                if text != text_upper:
                    line_no = token.line + line_offset
                    violations.append({
                        "rule_id": self.rule_id,
                        "cell_id": cell_id,
                        "line": line_no,
                        "current": text,
                        "expected": text_upper,
                        "message": f"SQL keyword '{text}' must be uppercase ('{text_upper}')"
                    })

        return violations
