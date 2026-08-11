from itertools import count
from typing import Optional

_rules: list[dict] = []
_id_counter = count(1)


def add_rule(rule: dict) -> dict:
    rule_with_id = {"id": next(_id_counter), **rule}
    _rules.append(rule_with_id)
    return rule_with_id


def get_rules(device_id: Optional[str] = None) -> list[dict]:
    if device_id is None:
        return list(_rules)
    return [r for r in _rules if r.get("device_id") == device_id]


def _reset():
    global _rules, _id_counter
    _rules = []
    _id_counter = count(1)
