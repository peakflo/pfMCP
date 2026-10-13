from peakflo.schemas.purchase_order import (
    ap_attachment_file_types,
    custom_field_details_schema,
)

# Canonical value of CustomFieldType.MultiFile in the real
# @peakflo/peakflo-schema package (both v4.x used by the api repo and the
# v5.x used by upload-functions). The api repo's __mocks__/peakflo-schema.ts
# mock ("MUltifile") is a test artifact only and does NOT reflect the real
# contract.
MULTIFILE_CUSTOM_FIELD_TYPE = "multiFile"


def normalize_multifile_custom_field_type(custom_field_type: str) -> str:
    """
    Normalize a multi-file custom-field type to the canonical "multiFile" value.

    The API-side customFieldDetails schemas accept any non-empty string and
    persist it verbatim into bill/payment customFields, so a caller sending a
    casing variant (e.g. the legacy "MUltifile" seen in old data, or
    "MultiFile") would store a type that strict downstream consumers (UI
    rendering, accounting sync, schema customFieldTypeValidation) do not
    recognize. Case-insensitive multifile variants are collapsed to the
    canonical value; anything else is passed through unchanged.
    """
    if (custom_field_type or "").strip().lower() == "multifile":
        return MULTIFILE_CUSTOM_FIELD_TYPE
    return custom_field_type


def build_ap_attachment_schema(
    *,
    id_field: str,
    id_description: str,
    entity_label: str,
    route_hint: str,
) -> dict:
    """
    Shared Peakflo public-API attachment schema — mirrors api ApAttachmentInput
    including optional customFieldDetails for multi-file CF targeting.
    """
    return {
        "type": "object",
        "description": (
            f"Add an attachment to an existing {entity_label}. Supply the file "
            "via exactly one of: a signed 'file_url' (the server downloads it, "
            "base64-encodes the content and computes fileSize), or directly via "
            "'base64' (in which case 'fileSize' must also be provided). "
            "Providing both is rejected. Files over 10MB are rejected. "
            "Optional customFieldDetails targets a Pixel multi-file CF "
            f"({route_hint}): customFieldNumber is REQUIRED inside it; "
            "customFieldId, customFieldName, customFieldType and "
            "customFieldSourceId are optional (the API resolves the field by "
            "number and checks any optional value given)."
        ),
        "properties": {
            id_field: {
                "type": "string",
                "description": id_description,
            },
            "tenantId": {
                "type": "string",
                "description": "Tenant ID",
            },
            "id": {
                "type": "string",
                "description": "Attachment id",
            },
            "name": {
                "type": "string",
                "description": "Attachment file name, e.g. ENOVA-ACCLIVIS-170326-1.pdf",
            },
            "contentType": {
                "type": "string",
                "description": "MIME type of the attachment (e.g., application/pdf)",
            },
            "fileSize": {
                "type": "number",
                "minimum": 0,
                "description": (
                    "Byte size of the attachment. Computed automatically when "
                    "file_url is provided; required when supplying base64 directly."
                ),
            },
            "file_url": {
                "type": "string",
                "description": (
                    "Signed URL to download the file. The server fetches the file, "
                    "base64-encodes its content, and computes fileSize before "
                    "forwarding to the Peakflo API."
                ),
            },
            "base64": {
                "type": "string",
                "description": (
                    "Base64-encoded file content (a data URI or raw base64). "
                    "Provide this, or file_url, to supply the file. When provided "
                    "directly, fileSize is required."
                ),
            },
            "fileType": {
                "type": "string",
                "enum": ap_attachment_file_types,
                "description": (
                    "Type of file being attached: transaction, statement, cabinet, "
                    "invoice, other, paymentProof, incomingFile, customFieldFile, "
                    "fakturPajak, payerReceipt, whtFile, eStampFile, shippingList, "
                    "or dscSigned. When customFieldDetails is set, the API coerces "
                    "this to customFieldFile."
                ),
            },
            "customFieldDetails": custom_field_details_schema,
        },
        "required": [id_field, "id", "name", "contentType", "fileType"],
        # Mirrors the api Joi rule: customFieldDetails is required when
        # fileType is customFieldFile.
        "if": {
            "properties": {"fileType": {"const": "customFieldFile"}},
            "required": ["fileType"],
        },
        "then": {"required": ["customFieldDetails"]},
        "oneOf": [
            {"required": ["file_url"], "not": {"required": ["base64"]}},
            {"required": ["base64", "fileSize"], "not": {"required": ["file_url"]}},
        ],
        "additionalProperties": False,
    }


add_bill_attachment_schema = build_ap_attachment_schema(
    id_field="billExternalId",
    id_description="External ID of the bill to attach the file to (used in URL path)",
    entity_label="bill",
    route_hint="PUT /v1/bill/:billExternalId/attachments",
)


# Mirrors ApAttachment.validationDetails and suggestedFieldOverwrites in the
# shared backend response contract. This tool saves proposals for user review;
# it never applies a proposed value to the bill.
_validation_issue_schema = {
    "type": "object",
    "properties": {
        "ruleId": {"type": "string", "minLength": 1},
        "code": {"type": "string", "minLength": 1},
        "message": {"type": "string", "minLength": 1},
        "dedupeKey": {"type": "string", "minLength": 1},
        "fieldPath": {"type": "string", "minLength": 1},
        "details": {"type": "object"},
    },
    "required": ["ruleId", "code", "message"],
    "additionalProperties": False,
}

_validation_check_schema = {
    **_validation_issue_schema,
    "properties": {
        **_validation_issue_schema["properties"],
        "outcome": {"type": "string", "enum": ["success", "warning", "error", "skipped"]},
    },
    "required": [*_validation_issue_schema["required"], "outcome"],
}

_field_overwrite_schema = {
    "type": "object",
    "properties": {
        "id": {"type": "string", "minLength": 1},
        "ruleId": {"type": "string", "minLength": 1},
        "target": {
            "oneOf": [
                {
                    "type": "object",
                    "properties": {
                        "scope": {"const": "apObject"},
                        "fieldPath": {"type": "string", "minLength": 1},
                    },
                    "required": ["scope", "fieldPath"],
                    "additionalProperties": False,
                },
                {
                    "type": "object",
                    "properties": {
                        "scope": {"const": "lineItem"},
                        "lineIndex": {"type": "integer", "minimum": 1},
                        "fieldPath": {"type": "string", "minLength": 1},
                    },
                    "required": ["scope", "lineIndex", "fieldPath"],
                    "additionalProperties": False,
                },
            ]
        },
        "currentValue": {},
        "suggestedValue": {},
        "optional": {"type": "boolean"},
        "overridable": {"type": "boolean"},
        "capturedField": {"type": "string"},
        "reason": {"type": "string"},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    },
    "required": [
        "id",
        "ruleId",
        "target",
        "currentValue",
        "suggestedValue",
        "optional",
        "overridable",
    ],
    "additionalProperties": False,
}

update_bill_attachment_validation_schema = {
    "type": "object",
    "description": (
        "Save validation details and proposed field overwrites on one bill "
        "attachment. The proposals do not change the bill. For a line target, "
        "use the persistent 1-based lineIndex and give currentValue. A user "
        "must review and approve proposed changes separately. Each call replaces "
        "only the rules named in validationDetails.ruleStatuses. Include a "
        "passed status to clear an old rule result."
    ),
    "properties": {
        "billExternalId": {"type": "string", "minLength": 1},
        "attachmentId": {"type": "string", "minLength": 1},
        "tenantId": {"type": "string", "description": "Tenant context hint"},
        "validationDetails": {
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "enum": ["inProgress", "passed", "warning", "error"],
                },
                "ruleStatuses": {
                    "type": "object",
                    "minProperties": 1,
                    "propertyNames": {"minLength": 1},
                    "additionalProperties": {
                        "type": "string",
                        "enum": ["inProgress", "passed", "warning", "error"],
                    },
                },
                "errors": {"type": "array", "items": _validation_issue_schema},
                "warnings": {"type": "array", "items": _validation_issue_schema},
                "checks": {"type": "array", "items": _validation_check_schema},
                "validatedAt": {"type": "string", "format": "date-time"},
            },
            "required": ["status", "ruleStatuses"],
            "additionalProperties": False,
        },
        "suggestedFieldOverwrites": {
            "type": "array",
            "items": _field_overwrite_schema,
        },
    },
    "required": ["billExternalId", "attachmentId", "validationDetails"],
    "additionalProperties": False,
}


update_ap_attachment_validation_schema = {
    **update_bill_attachment_validation_schema,
    "description": (
        "Save validation issues on an AP attachment by its Mongo object ID. "
        "Supported object types are bill, po, pq, pr, rn, tr, billPayment, and "
        "apCreditNote. Expense reports use bill; travel reports use tr. "
        "Field suggestions require a separate verified user action before "
        "any AP object value changes."
    ),
    "properties": {
        **{
            key: value
            for key, value in update_bill_attachment_validation_schema[
                "properties"
            ].items()
            if key != "billExternalId"
        },
        "objectType": {
            "type": "string",
            "enum": [
                "bill",
                "po",
                "pq",
                "pr",
                "rn",
                "tr",
                "billPayment",
                "apCreditNote",
            ],
        },
        "objectId": {"type": "string", "pattern": "^[0-9a-fA-F]{24}$"},
    },
    "required": ["objectType", "objectId", "attachmentId", "validationDetails"],
}

add_expense_report_attachment_schema = build_ap_attachment_schema(
    id_field="externalId",
    id_description=(
        "External ID of the expense report (BillType.EXPENSE_REPORT) to attach to"
    ),
    entity_label="expense report",
    route_hint="PUT /v1/expense-report/:externalId/attachments",
)

add_bill_payment_attachment_schema = build_ap_attachment_schema(
    id_field="externalId",
    id_description=(
        "External ID of the AP / TnE payment to attach the file to "
        "(same payments collection)"
    ),
    entity_label="bill payment",
    route_hint="PUT /v1/bill-payment/:externalId/attachments",
)
