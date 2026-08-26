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

    def __init__(self, model_name: str = "gemini-3.6-flash"):
        self.model_name = model_name

    def review(self, context: str, violations: List[Dict[str, Any]]) -> str:
        load_dotenv()
        api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")

        is_python_file = False
        for line in context.splitlines()[:5]:
            if "Notebook ID:" in line and line.strip().endswith(".py"):
                is_python_file = True
                break

        if not api_key or "your_" in api_key.lower() or "placeholder" in api_key.lower():
            return self._generate_fallback_review(context, violations, reason="GEMINI_API_KEY not configured.", is_python_file=is_python_file)

        try:
            from google import genai
            client = genai.Client(api_key=api_key)

            if is_python_file:
                format_requirements = (
                    "- Output ONLY line-by-line error highlights.\n"
                    "- Use this exact format per query:\n"
                    "  📍 Line [Line Number]\n"
                    "  • [RULE-ID] Title: Direct 1-line description of the error.\n"
                    "    Target Snippet: `<problematic sql snippet>`\n"
                    "- If a line has no violations for these two rules, do NOT list that line."
                )
            else:
                format_requirements = (
                    "- Output ONLY cell-by-cell error highlights.\n"
                    "- Use this exact format per cell:\n"
                    "  📍 Cell #[Cell Number] Line [Line Number]\n"
                    "  • [RULE-ID] Title: Direct 1-line description of the error.\n"
                    "    Target Snippet: `<problematic sql snippet>`\n"
                    "- If a cell has no violations for these two rules, do NOT list that cell."
                )

            prompt = (
                "You are an expert Senior Databricks SQL Code Reviewer.\n"
                "Your role is to HIGHLIGHT ERRORS AND VIOLATIONS ONLY in a clean, concise bulleted list.\n"
                "DO NOT write long multi-paragraph explanations, background tutorials, or performance coaching essays.\n\n"
                "RULES TO EVALUATE (ONLY CHECK THESE TWO RULES):\n"
                "1. RULE-001 (Keyword Uppercase): Flag any SQL keywords (e.g., select, from, where, join, group by, order by, use, catalog, schema) written in lowercase or mixed-case.\n"
                "2. RULE-002 (Descriptive Naming / No Cryptic Short-Forms): Flag short-form or cryptic abbreviations in column aliases and identifiers (e.g., cust, amt, txn, qty, cnt, dt). Require full, descriptive names (e.g., customer, amount, transaction, quantity, count, date).\n\n"
                "CRITICAL OUTPUT FORMAT REQUIREMENTS:\n"
                "The SQL Code lines provided in the context are prefixed with `[Line X]`. If a line is marked with `[MODIFIED]`, you MUST ONLY evaluate and review that line. DO NOT review or output violations for lines that do not have the `[MODIFIED]` tag.\n"
                f"{format_requirements}\n"
                "- Do NOT output full rewritten SQL queries.\n"
                "- Do NOT include executive summaries or long narrative paragraphs.\n"
                "- If NO violations are found for the modified lines, respond with exactly: '✅ No SQL violations found in the modified code.'\n\n"
                f"{context}"
            )
            print(f"🤖 Sending {len(prompt)} chars to LLM ({self.model_name})...")
            response = client.models.generate_content(
                model=self.model_name,
                contents=prompt
            )

            # Check for blocked responses (safety filters, quota, etc.)
            if not response:
                return self._generate_fallback_review(context, violations, reason="LLM returned None response (possible API quota exhaustion)", is_python_file=is_python_file)

            # Check if response was blocked by safety filters
            if hasattr(response, 'candidates') and response.candidates:
                candidate = response.candidates[0]
                if hasattr(candidate, 'finish_reason') and candidate.finish_reason and str(candidate.finish_reason) not in ('STOP', 'FinishReason.STOP', '1'):
                    reason = f"LLM response blocked. Finish reason: {candidate.finish_reason}"
                    if hasattr(candidate, 'safety_ratings'):
                        reason += f" | Safety ratings: {candidate.safety_ratings}"
                    print(f"⚠️ {reason}")
                    return self._generate_fallback_review(context, violations, reason=reason, is_python_file=is_python_file)

            # Extract text — handle empty content (model finished with STOP but no output text)
            response_text = None
            try:
                response_text = response.text
            except (ValueError, AttributeError):
                pass

            if response_text and response_text.strip():
                print(f"✅ LLM review received ({len(response_text)} chars)")
                return response_text.strip()
            else:
                # finish_reason=STOP + empty content = model found no violations
                print("✅ LLM found no violations (empty response with STOP)")
                return "✅ No SQL violations found in the modified code."

        except Exception as e:
            return self._generate_fallback_review(context, violations, reason=f"LLM execution error: {str(e)}", is_python_file=is_python_file)

    def _generate_fallback_review(
        self,
        context: str,
        violations: List[Dict[str, Any]],
        reason: str = "",
        is_python_file: bool = False
    ) -> str:
        lines = [
            "=== AUTOMATED DETERMINISTIC SQL REVIEW SUMMARY ===",
            f"Notice: {reason}" if reason else "",
            f"Total Rule Violations Detected: {len(violations)}",
            ""
        ]

        if not violations:
            unit = "queries" if is_python_file else "cells"
            lines.append(f"All analyzed SQL {unit} passed rule evaluation. No keyword casing violations found.")
        else:
            lines.append("Violations Breakdown (RULE-001: Keywords Must Be Uppercase):")
            for idx, v in enumerate(violations, start=1):
                if is_python_file:
                    lines.append(
                        f"  {idx}. Line {v['line']}: "
                        f"Keyword '{v['current']}' -> Expected '{v['expected']}'"
                    )
                else:
                    lines.append(
                        f"  {idx}. Cell #{v['cell_id']} Line {v['line']}: "
                        f"Keyword '{v['current']}' -> Expected '{v['expected']}'"
                    )
            lines.append("")
            unit_recom = "queries" if is_python_file else "keywords"
            lines.append(f"Recommendation: Update lowercase/mixed-case SQL {unit_recom} to uppercase to adhere to Databricks SQL coding standards.")

        return "\n".join(lines).strip()
