import json
from pathlib import Path

from fastapi import FastAPI
from pydantic import BaseModel, ValidationError

from app import llm_client, store
from app.models import parse_action
from app.validator import validate_action

app = FastAPI(title="NL Action Agent")

REGISTRY_PATH = Path(__file__).parent / "device_registry.json"
with open(REGISTRY_PATH) as f:
    DEVICE_REGISTRY = json.load(f)


class CommandRequest(BaseModel):
    text: str


@app.post("/command")
def handle_command(payload: CommandRequest):
    text = payload.text.strip()

    if not text:
        return {
            "understood": None,
            "status": "REJECTED",
            "reason": "Empty instruction text.",
            "result": None,
        }

    raw = llm_client.parse_command(text)

    try:
        action = parse_action(raw)
    except (ValueError, ValidationError) as e:
        return {
            "understood": raw,
            "status": "UNSUPPORTED",
            "reason": f"Model output didn't match a known action shape: {e}",
            "result": None,
        }

    if action.type == "UNSUPPORTED":
        return {
            "understood": action.model_dump(),
            "status": "UNSUPPORTED",
            "reason": action.reason,
            "result": None,
        }

    is_valid, reason = validate_action(action, DEVICE_REGISTRY)
    if not is_valid:
        return {
            "understood": action.model_dump(),
            "status": "REJECTED",
            "reason": reason,
            "result": None,
        }

    if action.type == "CREATE_ALERT_RULE":
        created = store.add_rule(action.model_dump())
        return {
            "understood": action.model_dump(),
            "status": "EXECUTED",
            "reason": "Rule created successfully.",
            "result": created,
        }

    if action.type == "QUERY_STATUS":
        return {
            "understood": action.model_dump(),
            "status": "EXECUTED",
            "reason": "Status query resolved (mock data - no live telemetry backend).",
            "result": {
                "device_id": action.device_id,
                "metric": action.metric,
                "value": "mock-value",
                "note": "This is a stub reading; no live sensor feed is wired up.",
            },
        }

    if action.type == "LIST_RULES":
        rules = store.get_rules(action.device_id)
        return {
            "understood": action.model_dump(),
            "status": "EXECUTED",
            "reason": f"Found {len(rules)} rule(s).",
            "result": rules,
        }

    return {
        "understood": action.model_dump(),
        "status": "UNSUPPORTED",
        "reason": f"No execution handler implemented for action type '{action.type}'.",
        "result": None,
    }


@app.get("/rules")
def list_all_rules():
    return store.get_rules()
