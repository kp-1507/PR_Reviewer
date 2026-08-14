from abc import ABC, abstractmethod
from typing import Any, Dict, List


class BaseRule(ABC):
    """
    Abstract Base Class for deterministic SQL review rules.
    """

    def __init__(self, rule_id: str, description: str):
        self.rule_id = rule_id
        self.description = description

    @abstractmethod
    def evaluate(self, sql_cell: Dict[str, Any], ast_result: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Evaluate rule against a SQL cell and its AST result.
        Returns a list of structured violation dicts.
        """
        pass
