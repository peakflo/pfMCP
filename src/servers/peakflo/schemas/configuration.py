"""Input contracts for tenant configuration tools.

The billing API validates policy, rule and custom-field payloads. Keep their
nested structures intact here so new server-side fields remain available.
"""

_id = {"type": "string", "minLength": 1, "description": "ID returned by a list or create tool"}
_payload = {"type": "object", "description": "Complete resource body accepted by the Peakflo API"}


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
    "list_rules": schema(objectType={"type": "string", "description": "Optional rule object type, such as bill or approval"}),
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
}
