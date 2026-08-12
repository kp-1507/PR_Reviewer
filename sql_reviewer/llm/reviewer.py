import os
from typing import Any, Dict, List, Optional

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


class LLMReviewer:
    """
    LLM Reviewer node using Google GenAI SDK.
    Interprets deterministic SQL findings and generates a human-readable review.
    Does NOT modify or fix SQL code.
    Fallback logic provides clean output if LLM fails or API key is absent.
    """

    def __init__(self, model_name: str = "gemini-2.5-flash"):
        self.model_name = model_name

    def review(self, context: str, violations: List[Dict[str, Any]]) -> str:
        load_dotenv()
        api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")

        if not api_key or "your_" in api_key.lower() or "placeholder" in api_key.lower():
            return self._generate_fallback_review(context, violations, reason="GEMINI_API_KEY not configured.")

        try:
            from google import genai
            client = genai.Client(api_key=api_key)

            prompt = (
                "You are an expert Senior Databricks SQL Code Reviewer.\n"
                "Your role is to perform a high-precision, professional review of the provided Databricks SQL code cells.\n\n"
                "INSTRUCTIONS FOR DETERMINISTIC FINDINGS:\n"
                "The context provided includes pre-computed deterministic violations (e.g., RULE-001 Keyword Uppercase). You MUST NOT re-evaluate these rules yourself. Simply incorporate these pre-computed findings accurately into your final report's Rule Violations Breakdown.\n\n"
                "SEMANTIC REVIEW CHECKLIST & RULES TO EVALUATE (You must evaluate these yourself):\n"
                "1. RULE-002 (Explicit Column Aliasing): Flag calculated or aggregated expressions (e.g., COUNT(*), SUM(col), DATE_FORMAT(...)) that lack an explicit AS alias.\n"
                "3. RULE-003 (Avoid SELECT *): Flag SELECT * on Delta/catalog tables. Explain memory waste and columnar storage scanning penalties.\n"
                "4. RULE-004 (Delta Lake Predicate Pushdown): Flag functions applied directly to filter columns in WHERE clauses (e.g. WHERE date_format(col, 'yyyy') = '2026') because they disable Delta Lake file pruning and metadata skipping; recommend SARGable range predicates (e.g. WHERE col >= '2026-01-01').\n"
                "5. RULE-005 (Join & Aggregation Efficiency): Flag implicit cross joins, filtering in HAVING instead of WHERE, or unoptimized subqueries.\n"
                "6. RULE-006 (CTE Readability): Encourage WITH clause Common Table Expressions (CTEs) over deeply nested inline subqueries.\n"
                "7. RULE-007 (Descriptive Naming / No Short-Forms): Flag cryptic short-form abbreviations in column aliases and identifiers (e.g., amt -> amount, txn -> transaction, cust -> customer, qty -> quantity, dt -> date). Require clear, full-word descriptive names for readability.\n\n"
                "REQUIRED RESPONSE STRUCTURE:\n"
                "### 1. Executive Summary & Health Score\n"
                "Provide a concise evaluation of overall notebook SQL quality, security, and rule adherence.\n\n"
                "### 2. Rule Violations Breakdown\n"
                "Cell-by-cell breakdown referencing Cell ID, line number, Rule ID, and detected issue.\n\n"
                "### 3. Databricks & Delta Lake Performance Coaching\n"
                "Explain Delta Lake predicate pushdown, file pruning, and columnar storage impacts for any identified performance anti-patterns.\n\n"
                "### 4. Actionable Recommendations\n"
                "Provide clear, concise guidance for developer resolution.\n\n"
                "CRITICAL INSTRUCTION: Do NOT output full rewritten SQL queries or complete code fixes.\n\n"
                f"{context}"
            )

            response = client.models.generate_content(
                model=self.model_name,
                contents=prompt
            )
            if response and response.text:
                return response.text.strip()
            else:
                return self._generate_fallback_review(context, violations, reason="Empty response from LLM.")

        except Exception as e:
            return self._generate_fallback_review(context, violations, reason=f"LLM execution error: {str(e)}")

    def _generate_fallback_review(
        self,
        context: str,
        violations: List[Dict[str, Any]],
        reason: str = ""
    ) -> str:
        lines = [
            "=== AUTOMATED DETERMINISTIC SQL REVIEW SUMMARY ===",
            f"Notice: {reason}" if reason else "",
            f"Total Rule Violations Detected: {len(violations)}",
            ""
        ]

        if not violations:
            lines.append("All analyzed SQL cells passed rule evaluation. No keyword casing violations found.")
        else:
            lines.append("Violations Breakdown (RULE-001: Keywords Must Be Uppercase):")
            for idx, v in enumerate(violations, start=1):
                lines.append(
                    f"  {idx}. Cell #{v['cell_id']} Line {v['line']}: "
                    f"Keyword '{v['current']}' -> Expected '{v['expected']}'"
                )
            lines.append("")
            lines.append("Recommendation: Update lowercase/mixed-case SQL keywords to uppercase to adhere to Databricks SQL coding standards.")

        return "\n".join(lines).strip()
