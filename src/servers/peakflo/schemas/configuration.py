"""Input contracts for tenant configuration tools.

The billing API validates policy, rule and custom-field payloads. Keep their
nested structures intact here so new server-side fields remain available.
"""

_id = {
    "type": "string",
    "minLength": 1,
    "description": "ID returned by a list or create tool",
}
_payload = {
    "type": "object",
    "description": "Complete resource body accepted by the Peakflo API",
}
_coa_account = {
    "type": "object",
    "properties": {
        "name": {"type": "string", "minLength": 1, "maxLength": 200},
        "code": {"type": "string", "minLength": 1, "maxLength": 100},
        "type": {
            "type": "string",
            "enum": [
                "asset",
                "equity",
                "expense",
                "liability",
                "revenue",
                "bank",
                "other",
            ],
        },
        "paymentAllowed": {"type": "boolean"},
    },
    "required": ["name", "code", "type", "paymentAllowed"],
    "additionalProperties": False,
}


def schema(required=(), **properties):
    return {
        "type": "object",
        "properties": properties,
        "required": list(required),
        "additionalProperties": False,
    }


configuration_schemas = {
    "list_approval_policies": schema(),
    "get_approval_policy": schema(("id",), id=_id),
    "create_approval_policy": schema(("payload",), payload=_payload),
    "update_approval_policy": schema(("id", "payload"), id=_id, payload=_payload),
    "delete_approval_policy": schema(("id",), id=_id),
    "list_rules": schema(
        objectType={
            "type": "string",
            "description": "Optional rule object type, such as bill or approval",
        }
    ),
    "get_rule": schema(("id",), id=_id),
    "create_rule": schema(("payload",), payload=_payload),
    "update_rule": schema(("id", "payload"), id=_id, payload=_payload),
    "delete_rule": schema(("id",), id=_id),
    "list_custom_fields": schema(
        page={"type": "integer", "minimum": 1},
        limit={"type": "integer", "minimum": 1, "maximum": 200},
    ),
    "create_custom_field": schema(("payload",), payload=_payload),
    "update_custom_field": schema(("id", "payload"), id=_id, payload=_payload),
    "delete_custom_field": schema(("id",), id=_id),
    "invite_user": schema(
        ("email", "displayName"),
        email={"type": "string", "format": "email", "maxLength": 254},
        displayName={"type": "string", "minLength": 1, "maxLength": 200},
        role={
            "type": "string",
            "minLength": 1,
            "description": "Optional role ID; API credentials can use only the tenant default role",
        },
    ),
    "list_chart_of_accounts": schema(
        search={"type": "string"},
        page={"type": "integer", "minimum": 1},
        limit={"type": "integer", "minimum": 1, "maximum": 100},
    ),
    "get_chart_of_account": schema(("id",), id=_id),
    "create_chart_of_account": schema(("account",), account=_coa_account),
    "update_chart_of_account": schema(("id", "account"), id=_id, account=_coa_account),
    "delete_chart_of_account": schema(("id",), id=_id),
}
