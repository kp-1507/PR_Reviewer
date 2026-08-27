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

    def review(self, context: str, violations: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        import json
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
            from google.genai import types
            client = genai.Client(api_key=api_key)

            if is_python_file:
                format_requirements = (
                    "- Output a strict JSON array of objects. Do NOT wrap the JSON in Markdown blocks like ```json.\n"
                    "- Each object must have these exact keys:\n"
                    '  - "line": the absolute file line number (integer)\n'
                    '  - "body": the markdown formatted comment starting with `[RULE-ID]`\n'
                    'Example:\n'
                    '[\n'
                    '  {"line": 42, "body": "[RULE-002] Descriptive Naming: `cust` should be `customer`"}\n'
                    ']'
                )
            else:
                format_requirements = (
                    "- Output a strict JSON array of objects. Do NOT wrap the JSON in Markdown blocks like ```json.\n"
                    "- Each object must have these exact keys:\n"
                    '  - "cell_id": the notebook cell number (integer)\n'
                    '  - "line_within_cell": the line number within that cell (integer)\n'
                    '  - "body": the markdown formatted comment starting with `[RULE-ID]`\n'
                    'Example:\n'
                    '[\n'
                    '  {"cell_id": 3, "line_within_cell": 2, "body": "[RULE-002] Descriptive Naming: `amt` should be `amount`"}\n'
                    ']'
                )

            prompt = (
                "You are an expert Senior Databricks SQL Code Reviewer.\n"
                "Your role is to HIGHLIGHT ERRORS AND VIOLATIONS ONLY in a JSON array format.\n"
                "DO NOT write explanations or background tutorials.\n\n"
                "RULES TO EVALUATE (ONLY CHECK THESE TWO RULES):\n"
                "1. RULE-001 (Keyword Uppercase): Flag any SQL keywords (e.g., select, from, where, join, group by, order by, use, catalog, schema) written in lowercase or mixed-case.\n"
                "2. RULE-002 (Descriptive Naming / No Cryptic Short-Forms): Flag short-form or cryptic abbreviations in column aliases and identifiers (e.g., cust, amt, txn, qty, cnt, dt). Require full, descriptive names (e.g., customer, amount, transaction, quantity, count, date).\n\n"
                "CRITICAL OUTPUT FORMAT REQUIREMENTS:\n"
                "The SQL Code lines provided in the context are prefixed with `[Line X]`. Use these prefixes to determine the exact absolute line number for any violation. Do not guess or do math.\n"
                f"{format_requirements}\n"
                "- If there are no violations, output an empty JSON array: `[]`\n\n"
                f"{context}"
            )
            response = client.models.generate_content(
                model=self.model_name,
                contents=prompt,
                config=types.GenerateContentConfig(response_mime_type="application/json")
            )
            if response and response.text:
                raw_text = response.text.strip()
                if raw_text.startswith("```json"):
                    raw_text = raw_text[7:]
                if raw_text.endswith("```"):
                    raw_text = raw_text[:-3]
                return json.loads(raw_text.strip())
            else:
                return self._generate_fallback_review(context, violations, reason="Empty response from LLM.", is_python_file=is_python_file)

        except Exception as e:
            return self._generate_fallback_review(context, violations, reason=f"LLM execution error: {str(e)}", is_python_file=is_python_file)

    def _generate_fallback_review(
        self,
        context: str,
        violations: List[Dict[str, Any]],
        reason: str = "",
        is_python_file: bool = False
    ) -> List[Dict[str, Any]]:
        # Fallback returns empty list; deterministic rules already handled natively by main.py
        if reason:
            print(f"Fallback triggered: {reason}")
        return []
