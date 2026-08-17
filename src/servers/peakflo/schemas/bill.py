from peakflo.schemas.purchase_order import ap_attachment_file_types

add_bill_attachment_schema = {
    "type": "object",
    "description": (
        "Add an attachment to an existing bill. Supply the file "
        "via exactly one of: a signed 'file_url' (the server downloads it, "
        "base64-encodes the content and computes fileSize), or directly via "
        "'base64' (in which case 'fileSize' must also be provided). "
        "Providing both is rejected. Files over 10MB are rejected."
    ),
    "properties": {
        "billExternalId": {
            "type": "string",
            "description": "External ID of the bill to attach the file to (used in URL path)",
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
            "description": "Byte size of the attachment. Computed automatically when file_url is provided; required when supplying base64 directly.",
        },
        "file_url": {
            "type": "string",
            "description": "Signed URL to download the file. The server fetches the file, base64-encodes its content, and computes fileSize before forwarding to the Peakflo API.",
        },
        "base64": {
            "type": "string",
            "description": "Base64-encoded file content (a data URI or raw base64). Provide this, or file_url, to supply the file. When provided directly, fileSize is required.",
        },
        "fileType": {
            "type": "string",
            "enum": ap_attachment_file_types,
            "description": "Type of file being attached: transaction, statement, cabinet, invoice, other, paymentProof, incomingFile, customFieldFile, fakturPajak, payerReceipt, whtFile, eStampFile, shippingList, or dscSigned",
        },
    },
    "required": ["billExternalId", "id", "name", "contentType", "fileType"],
    "oneOf": [
        {"required": ["file_url"], "not": {"required": ["base64"]}},
        {"required": ["base64", "fileSize"], "not": {"required": ["file_url"]}},
    ],
    "additionalProperties": False,
}
