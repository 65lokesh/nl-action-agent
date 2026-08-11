import json
from pathlib import Path

from app.models import CreateAlertRule, QueryStatus
from app.validator import validate_action

REGISTRY = json.loads((Path(__file__).parent.parent / "app" / "device_registry.json").read_text())


def test_valid_create_alert_rule_passes():
    action = CreateAlertRule(
        type="CREATE_ALERT_RULE", device_id="warehouse-3", metric="temperature",
        condition="ABOVE", threshold=40, duration_minutes=10, notify_via=["EMAIL"]
    )
    is_valid, reason = validate_action(action, REGISTRY)
    assert is_valid
    assert reason is None


def test_unknown_device_fails():
    action = CreateAlertRule(
        type="CREATE_ALERT_RULE", device_id="reactor-core", metric="pressure",
        condition="ABOVE", threshold=9000, duration_minutes=1, notify_via=["EMAIL"]
    )
    is_valid, reason = validate_action(action, REGISTRY)
    assert not is_valid
    assert "reactor-core" in reason


def test_invalid_metric_for_known_device_fails():
    action = CreateAlertRule(
        type="CREATE_ALERT_RULE", device_id="warehouse-3", metric="pressure",
        condition="ABOVE", threshold=10, duration_minutes=5, notify_via=["EMAIL"]
    )
    is_valid, reason = validate_action(action, REGISTRY)
    assert not is_valid
    assert "pressure" in reason


def test_zero_or_negative_duration_fails():
    action = CreateAlertRule(
        type="CREATE_ALERT_RULE", device_id="warehouse-3", metric="temperature",
        condition="ABOVE", threshold=40, duration_minutes=0, notify_via=["EMAIL"]
    )
    is_valid, reason = validate_action(action, REGISTRY)
    assert not is_valid


def test_query_status_with_valid_metric_passes():
    action = QueryStatus(type="QUERY_STATUS", device_id="cold-storage-1", metric="humidity")
    is_valid, reason = validate_action(action, REGISTRY)
    assert is_valid
