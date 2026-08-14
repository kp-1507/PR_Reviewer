from typing import Any, Dict, List
from sql_reviewer.sql_engine.rules.base import BaseRule
from sql_reviewer.sql_engine.rules.rule_001 import Rule001KeywordsUppercase


class RuleEngine:
    """
    Modular Rule Engine that executes registered SQL review rules against SQL cells.
    """

    def __init__(self, rules: List[BaseRule] = None):
        if rules is None:
            self.rules = [Rule001KeywordsUppercase()]
        else:
            self.rules = rules

    def add_rule(self, rule: BaseRule):
        self.rules.append(rule)

    def evaluate_cell(self, sql_cell: Dict[str, Any], ast_result: Dict[str, Any]) -> List[Dict[str, Any]]:
        cell_violations: List[Dict[str, Any]] = []
        for rule in self.rules:
            findings = rule.evaluate(sql_cell, ast_result)
            cell_violations.extend(findings)
        return cell_violations

    def evaluate_all(
        self,
        sql_cells: List[Dict[str, Any]],
        ast_results: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        ast_map = {res["cell_id"]: res for res in ast_results}
        all_violations: List[Dict[str, Any]] = []

        for cell in sql_cells:
            cell_id = cell["cell_id"]
            ast_res = ast_map.get(cell_id, {"status": "error", "ast": None, "error": "AST missing"})
            violations = self.evaluate_cell(cell, ast_res)
            all_violations.extend(violations)

        return all_violations
