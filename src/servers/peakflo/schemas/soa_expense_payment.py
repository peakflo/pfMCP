"""
Input schemas for TSK-17697 SOA OCR creation tools.

These tools let the SOA OCR workflow create real Peakflo TnE objects through
the billing-api gateway (the same endpoints the Peakflo UI uses):

  1. create_soa_expenses        -> POST /expense/myexpenses   (one call per line item)
  2. create_soa_expense_report  -> POST /expense/expenseReport (ER bill, items[].expense = join key)
  3. create_soa_payment         -> POST /ap/payment            (BillPayment linked to the ER bill)
"""

create_soa_expenses_input_schema = {
    "type": "object",
    "properties": {
        "expenses": {
            "type": "array",
            "description": (
                "One entry per OCR line item. Each entry is a General Expense "
                "(My Expenses) payload as accepted by POST /expense/myexpenses. "
                "Required per entry: expenseType ('ExpensesGeneral'), merchant, "
                "date (ISO), amount, totalAmount, totalAmountConv, currencyRate, "
                "defaultCurrency, sourceCurrency, status ('draft'), employeeId, "
                "employeeName, expensePolicy, category {categoryId, name}. "
                "Optional: note, customFields, attachments."
            ),
            "items": {"type": "object"},
            "minItems": 1,
        },
        "forceSave": {
            "type": "boolean",
            "description": (
                "Create even when a duplicate expense is detected (OCR draft "
                "path). Defaults to true for the SOA OCR flow."
            ),
        },
        "skipWorkflowValidation": {
            "type": "boolean",
            "description": (
                "Skip expense workflow validation gates for programmatic "
                "creation. Defaults to true for the SOA OCR flow."
            ),
        },
    },
    "required": ["expenses"],
}

create_soa_expense_report_input_schema = {
    "type": "object",
    "properties": {
        "vendorId": {
            "type": "string",
            "description": (
                "Employee id of the cardholder — the ER 'vendor' IS the "
                "employee (e.g. 00rPGcYMaLYN9MAgvxhy)."
            ),
        },
        "vendorName": {
            "type": "string",
            "description": "Cardholder display name.",
        },
        "currency": {
            "type": "string",
            "description": "ER currency (e.g. 'PHP').",
        },
        "date": {
            "type": "string",
            "description": "ER date (ISO) — usually the statement date.",
        },
        "subTotal": {
            "type": "number",
            "description": "Sum of item totals (excluding tax).",
        },
        "totalAmount": {
            "type": "number",
            "description": "ER total (converted amount).",
        },
        "notes": {
            "type": "string",
            "description": "Optional ER note (e.g. the SOA statement id).",
        },
        "items": {
            "type": "array",
            "description": (
                "One item per expense. Each item: {name, unit: 'expense', "
                "quantity: 1, unitPrice, expense: '<expense _id>', total, "
                "totalTax, balanceAmount, balanceQuantity: 1}. The `expense` "
                "field is THE join key linking the ER bill line to the "
                "created expense."
            ),
            "items": {"type": "object"},
            "minItems": 1,
        },
        "expenseReportType": {
            "type": "string",
            "description": "Defaults to 'NON_TRAVEL'.",
        },
        "attachments": {
            "type": "array",
            "description": "Optional attachments carried from the expenses.",
            "items": {"type": "object"},
        },
    },
    "required": ["vendorId", "vendorName", "currency", "date", "items"],
}

create_soa_payment_input_schema = {
    "type": "object",
    "properties": {
        "externalId": {
            "type": "string",
            "description": (
                "Unique id per issuer+subsidiary (400 on duplicate). The SOA "
                "flow sends the same uuid it uses as Fusion PeakfloRefId."
            ),
        },
        "paymentReference": {
            "type": "string",
            "description": (
                "Human reference — the SOA flow sends the statement id "
                "('SOA-<cardFirst4Last4>-<YYYYMMDD>')."
            ),
        },
        "externalVendorId": {
            "type": "string",
            "description": "Cardholder employee external id.",
        },
        "paymentDate": {
            "type": "string",
            "description": "Payment date (ISO).",
        },
        "scheduledDate": {
            "type": "string",
            "description": "Optional scheduled date (ISO).",
        },
        "amount": {
            "type": "number",
            "description": "Payment amount in payment currency.",
        },
        "baseCurrency": {
            "type": "string",
            "description": "Payment currency (e.g. 'PHP').",
        },
        "fxRate": {
            "type": "number",
            "description": "FX rate (1 when currencies match).",
        },
        "subsidiaryReference": {
            "type": "string",
            "description": "Business-unit / subsidiary reference for the payment.",
        },
        "bills": {
            "type": "array",
            "description": (
                "Bills this payment pays. Each entry: {bill: '<ER bill _id>', "
                "appliedAmount: <bill currency>, convertedAppliedAmount: "
                "<appliedAmount x fxRate>}. This creates the payment->ER link."
            ),
            "items": {"type": "object"},
            "minItems": 1,
        },
        "note": {
            "type": "string",
            "description": "Optional payment note.",
        },
        "status": {
            "type": "string",
            "description": "Optional initial status (defaults to draft).",
        },
    },
    "required": ["externalId", "paymentReference", "externalVendorId", "amount", "baseCurrency", "bills"],
}
