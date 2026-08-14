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

    DATABRICKS_ADDITIONAL_KEYWORDS = {
        "CATALOG", "CATALOGS", "SCHEMA", "SCHEMAS", "DATABASE", "DATABASES",
        "TABLE", "TABLES", "VIEW", "VIEWS", "FUNCTION", "FUNCTIONS",
        "USE", "SET", "UNSET", "SHOW", "DESCRIBE", "EXPLAIN", "GRANT", "REVOKE",
        "OPTIMIZE", "VACUUM", "ZORDER", "BY", "CLUSTER", "CLUSTERED",
        "LOCATION", "FORMAT", "USING", "OPTIONS", "TBLPROPERTIES",
        "PARTITIONED", "MERGE", "INTO", "MATCHED", "THEN", "WHEN",
        "UPDATE", "DELETE", "INSERT", "OVERWRITE", "TRUNCATE", "REORG",
        "STREAMING", "WATERMARK", "DELAY", "OF"
    }

    NON_KEYWORD_TYPES = {
        TokenType.STRING,
        TokenType.RAW_STRING,
        TokenType.HEREDOC_STRING,
        TokenType.NATIONAL_STRING,
        TokenType.HEX_STRING,
        TokenType.BYTE_STRING,
        TokenType.BIT_STRING,
        TokenType.COMMENT,
        TokenType.IDENTIFIER,
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
    }

    def __init__(self):
        super().__init__(
            rule_id="RULE-001",
            description="All SQL keywords must be uppercase."
        )
        self.dialect = Dialect.get("databricks")()
        self.tokenizer = self.dialect.Tokenizer()
        self.all_keywords = set(self.tokenizer.KEYWORDS.keys()) | self.DATABRICKS_ADDITIONAL_KEYWORDS

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
            if not token.text:
                continue

            if token.token_type in self.NON_KEYWORD_TYPES:
                continue

            # Extract the raw source text to preserve original casing of compound keywords (like "order by")
            raw_text = sql_content[token.start : token.end + 1]
            text_upper = raw_text.upper()

            if text_upper in self.all_keywords:
                if raw_text != text_upper:
                    line_no = token.line + line_offset
                    violations.append({
                        "rule_id": self.rule_id,
                        "cell_id": cell_id,
                        "line": line_no,
                        "current": raw_text,
                        "expected": text_upper,
                        "message": f"SQL keyword '{raw_text}' must be uppercase ('{text_upper}')"
                    })

        return violations


