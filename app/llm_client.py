"""
Wraps the LLM call that turns free text into a structured action guess.

Important: this file only produces a *guess*. It does not decide what's
allowed - that's validator.py's job. If GEMINI_API_KEY isn't set, or
MOCK_MODE is on, we fall back to canned responses for the known test
phrases so the app is runnable and testable without burning API credits.
"""

import json
import os
import re

from dotenv import load_dotenv

load_dotenv()

MOCK_MODE = os.getenv("MOCK_MODE", "true").lower() == "true"
API_KEY = os.getenv("GEMINI_API_KEY")

SYSTEM_PROMPT = """You convert facility-monitoring instructions into structured JSON.

Output ONLY valid JSON. No markdown fences, no explanation, no prose.

You must output an object matching exactly one of these shapes:

CREATE_ALERT_RULE:
{"type": "CREATE_ALERT_RULE", "device_id": string, "metric": string,
 "condition": "ABOVE" | "BELOW" | "EQUALS", "threshold": number,
 "duration_minutes": number, "notify_via": ["EMAIL" | "SMS" | "PUSH", ...]}

QUERY_STATUS:
{"type": "QUERY_STATUS", "device_id": string, "metric": string or null}

LIST_RULES:
{"type": "LIST_RULES", "device_id": string or null}

UNSUPPORTED:
{"type": "UNSUPPORTED", "reason": string}

Rules:
- device_id should be exactly as mentioned in the text (e.g. "warehouse-3"), don't invent or guess new devices.
- If duration isn't mentioned for an alert rule, and the instruction implies a state
  change (e.g. "goes offline", "stops responding") rather than a sustained numeric
  threshold, still produce CREATE_ALERT_RULE but use a conservative default of
  duration_minutes=1, and pick a sensible boolean-style metric/condition
  (e.g. metric "connectivity", condition "EQUALS", threshold 0 for offline).
- If notify_via isn't specified, default to ["EMAIL"].
- If the instruction has nothing to do with monitoring/alerting/querying devices
  (e.g. controlling lights, unrelated smalltalk), output UNSUPPORTED with a clear reason.
- Never invent a device_id that wasn't mentioned in the text.

Examples:

Text: "Alert me if warehouse-3 temperature stays above 40 for more than 10 minutes"
Output: {"type": "CREATE_ALERT_RULE", "device_id": "warehouse-3", "metric": "temperature", "condition": "ABOVE", "threshold": 40, "duration_minutes": 10, "notify_via": ["EMAIL"]}

Text: "what's the humidity in cold-storage-1 right now"
Output: {"type": "QUERY_STATUS", "device_id": "cold-storage-1", "metric": "humidity"}

Text: "turn off all the lights in building 7"
Output: {"type": "UNSUPPORTED", "reason": "This system monitors and alerts on device metrics, it does not control building equipment like lighting."}
"""


_INJECTION_PATTERNS = [
    r"ignore (all )?(previous|prior|above) instructions",
    r"disregard (all )?(previous|prior|above) instructions",
    r"you are now",
    r"system prompt",
    r"delete all rules",
    r"drop table",
    r"act as",
]


def _looks_like_injection(text: str) -> bool:
    normalized = text.lower()
    return any(re.search(pattern, normalized) for pattern in _INJECTION_PATTERNS)


_MOCK_RESPONSES = {
    "alert me if warehouse-3 temperature stays above 40°c for more than 10 minutes": {
        "type": "CREATE_ALERT_RULE",
        "device_id": "warehouse-3",
        "metric": "temperature",
        "condition": "ABOVE",
        "threshold": 40,
        "duration_minutes": 10,
        "notify_via": ["EMAIL"],
    },
    "what's the humidity in cold-storage-1 right now": {
        "type": "QUERY_STATUS",
        "device_id": "cold-storage-1",
        "metric": "humidity",
    },
    "notify security if the front-gate camera goes offline": {
        "type": "CREATE_ALERT_RULE",
        "device_id": "front-gate-camera",
        "metric": "connectivity",
        "condition": "EQUALS",
        "threshold": 0,
        "duration_minutes": 1,
        "notify_via": ["EMAIL", "SMS"],
    },
    "turn off all the lights in building 7": {
        "type": "UNSUPPORTED",
        "reason": "This system monitors and alerts on device metrics, it does not control building equipment like lighting.",
    },
    "alert me if the reactor-core pressure exceeds 9000": {
        "type": "CREATE_ALERT_RULE",
        "device_id": "reactor-core",
        "metric": "pressure",
        "condition": "ABOVE",
        "threshold": 9000,
        "duration_minutes": 1,
        "notify_via": ["EMAIL"],
    },
}


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def parse_command(text: str) -> dict:
    """
    Returns a raw dict parsed from the LLM's output. Never raises for
    "the LLM said something weird" - callers should still validate the
    result against models.py before trusting it.
    """
    if _looks_like_injection(text):
        return {
            "type": "UNSUPPORTED",
            "reason": "This instruction looks like it's trying to override system behavior rather than describe a monitoring request, so it was not processed.",
        }

    if MOCK_MODE or not API_KEY:
        return _mock_parse(text)

    return _real_parse(text)


def _mock_parse(text: str) -> dict:
    normalized = _normalize(text)
    if normalized in _MOCK_RESPONSES:
        return dict(_MOCK_RESPONSES[normalized])

    return {
        "type": "UNSUPPORTED",
        "reason": "Could not map this instruction to a supported action.",
    }


def _real_parse(text: str) -> dict:
    import google.generativeai as genai

    genai.configure(api_key=API_KEY)

    model = genai.GenerativeModel(
        model_name="gemini-2.5-flash",
        system_instruction=SYSTEM_PROMPT,
        generation_config={"response_mime_type": "application/json"},
    )

    response = model.generate_content(text)

    raw_text = response.text.strip()
    raw_text = re.sub(r"^```(json)?|```$", "", raw_text, flags=re.MULTILINE).strip()

    try:
        return json.loads(raw_text)
    except json.JSONDecodeError as e:
        return {
            "type": "UNSUPPORTED",
            "reason": f"Could not parse a structured action from the model's response: {e}",
        }
