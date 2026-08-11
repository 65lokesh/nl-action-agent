"""
Pydantic schemas for the structured actions our system can execute.

These are the contract between the LLM output and everything downstream.
The LLM's job is to produce something that *fits* one of these shapes.
Our job (in validator.py) is to check that the values inside actually
make sense given the real device registry.
"""

from typing import Literal, Optional, Union
from pydantic import BaseModel, Field


class CreateAlertRule(BaseModel):
    type: Literal["CREATE_ALERT_RULE"]
    device_id: str
    metric: str
    condition: Literal["ABOVE", "BELOW", "EQUALS"]
    threshold: float
    duration_minutes: int
    notify_via: list[Literal["EMAIL", "SMS", "PUSH"]] = Field(default_factory=lambda: ["EMAIL"])


class QueryStatus(BaseModel):
    type: Literal["QUERY_STATUS"]
    device_id: str
    metric: Optional[str] = None


class ListRules(BaseModel):
    type: Literal["LIST_RULES"]
    device_id: Optional[str] = None


class Unsupported(BaseModel):
    type: Literal["UNSUPPORTED"]
    reason: str


Action = Union[CreateAlertRule, QueryStatus, ListRules, Unsupported]


def parse_action(raw: dict) -> Action:
    """
    Takes a raw dict (usually straight from the LLM's JSON output) and
    tries to fit it into one of our known action types.

    Raises ValueError if the shape is nonsense - the caller is expected
    to catch this and turn it into an UNSUPPORTED response rather than
    letting it blow up the request.
    """
    action_type = raw.get("type")

    model_map = {
        "CREATE_ALERT_RULE": CreateAlertRule,
        "QUERY_STATUS": QueryStatus,
        "LIST_RULES": ListRules,
        "UNSUPPORTED": Unsupported,
    }

    model = model_map.get(action_type)
    if model is None:
        raise ValueError(f"Unknown action type from LLM: {action_type!r}")

    return model(**raw)
