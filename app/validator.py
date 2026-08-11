from app.models import Action, CreateAlertRule, QueryStatus, ListRules


def validate_action(action: Action, registry: dict) -> tuple[bool, str | None]:
    if isinstance(action, CreateAlertRule):
        return _validate_create_alert_rule(action, registry)

    if isinstance(action, QueryStatus):
        return _validate_query_status(action, registry)

    if isinstance(action, ListRules):
        return _validate_list_rules(action, registry)

    return True, None


def _validate_create_alert_rule(action: CreateAlertRule, registry: dict) -> tuple[bool, str | None]:
    if action.device_id not in registry:
        return False, f"Device '{action.device_id}' does not exist in the registry."

    valid_metrics = registry[action.device_id]["metrics"]
    if action.metric not in valid_metrics:
        return False, (
            f"Metric '{action.metric}' is not valid for device '{action.device_id}'. "
            f"Valid metrics are: {', '.join(valid_metrics)}."
        )

    if action.duration_minutes <= 0:
        return False, "duration_minutes must be a positive number."

    return True, None


def _validate_query_status(action: QueryStatus, registry: dict) -> tuple[bool, str | None]:
    if action.device_id not in registry:
        return False, f"Device '{action.device_id}' does not exist in the registry."

    if action.metric is not None:
        valid_metrics = registry[action.device_id]["metrics"]
        if action.metric not in valid_metrics:
            return False, (
                f"Metric '{action.metric}' is not valid for device '{action.device_id}'. "
                f"Valid metrics are: {', '.join(valid_metrics)}."
            )

    return True, None


def _validate_list_rules(action: ListRules, registry: dict) -> tuple[bool, str | None]:
    if action.device_id is not None and action.device_id not in registry:
        return False, f"Device '{action.device_id}' does not exist in the registry."

    return True, None
