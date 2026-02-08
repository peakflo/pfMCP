import os
import sys
from typing import Optional, Iterable
from base64 import urlsafe_b64encode, urlsafe_b64decode
import base64
import mimetypes

# Add both project root and src directory to Python path
# Get the project root directory and add to path
project_root = os.path.abspath(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
)
sys.path.insert(0, project_root)
sys.path.insert(0, os.path.join(project_root, "src"))

import logging
from pathlib import Path

from mcp.types import (
    AnyUrl,
    Resource,
    TextContent,
    Tool,
    ImageContent,
    EmbeddedResource,
)
from mcp.server.lowlevel.helper_types import ReadResourceContents
from mcp.server import NotificationOptions, Server
from mcp.server.models import InitializationOptions

from src.utils.google.util import authenticate_and_save_credentials, get_credentials
from src.utils.storage.factory import get_storage_service

from googleapiclient.discovery import build
import email.utils
import email.mime.text
import email.mime.multipart
import email.mime.base
import email.encoders

SERVICE_NAME = Path(__file__).parent.name
SCOPES = [
    "https://www.googleapis.com/auth/gmail.labels",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.modify",  # Required for update_email (modify labels)
]

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(SERVICE_NAME)


def parse_email_body(payload):
    """Extract email body from Gmail API payload"""
    body = {"text": "", "html": ""}

    if "parts" in payload:
        # Multipart message
        for part in payload["parts"]:
            mime_type = part.get("mimeType", "")

            if mime_type == "text/plain":
                if "data" in part.get("body", {}):
                    body["text"] = urlsafe_b64decode(part["body"]["data"]).decode(
                        "utf-8", errors="replace"
                    )
            elif mime_type == "text/html":
                if "data" in part.get("body", {}):
                    body["html"] = urlsafe_b64decode(part["body"]["data"]).decode(
                        "utf-8", errors="replace"
                    )
            elif mime_type.startswith("multipart/"):
                # Recursively parse nested multipart
                nested_body = parse_email_body(part)
                if nested_body["text"]:
                    body["text"] = nested_body["text"]
                if nested_body["html"]:
                    body["html"] = nested_body["html"]
    else:
        # Single part message
        if "body" in payload and "data" in payload["body"]:
            mime_type = payload.get("mimeType", "")
            data = urlsafe_b64decode(payload["body"]["data"]).decode(
                "utf-8", errors="replace"
            )
            if mime_type == "text/plain":
                body["text"] = data
            elif mime_type == "text/html":
                body["html"] = data

    return body


def get_attachments_info(payload):
    """Extract attachment information from Gmail API payload"""
    attachments = []

    if "parts" in payload:
        for part in payload["parts"]:
            if part.get("filename"):
                attachment_info = {
                    "filename": part["filename"],
                    "mimeType": part.get("mimeType", "application/octet-stream"),
                    "size": part["body"].get("size", 0),
                    "attachmentId": part["body"].get("attachmentId"),
                }
                attachments.append(attachment_info)
            # Check for nested parts
            elif "parts" in part:
                nested_attachments = get_attachments_info(part)
                attachments.extend(nested_attachments)

    return attachments


def download_attachment(gmail_service, user_id, message_id, attachment_id):
    """Download attachment data from Gmail"""
    try:
        attachment = (
            gmail_service.users()
            .messages()
            .attachments()
            .get(userId=user_id, messageId=message_id, id=attachment_id)
            .execute()
        )
        return urlsafe_b64decode(attachment["data"])
    except Exception as e:
        logger.error(f"Error downloading attachment: {str(e)}")
        return None


def create_message_with_attachments(
    to, subject, body, cc=None, bcc=None, attachments=None
):
    """Create a MIME message with optional attachments"""
    if attachments:
        message = email.mime.multipart.MIMEMultipart()
    else:
        message = email.mime.text.MIMEText(body)
        message["to"] = to
        message["subject"] = subject
        if cc:
            message["cc"] = cc
        if bcc:
            message["bcc"] = bcc
        return message

    # For multipart messages
    message["to"] = to
    message["subject"] = subject
    if cc:
        message["cc"] = cc
    if bcc:
        message["bcc"] = bcc

    # Attach the body
    message.attach(email.mime.text.MIMEText(body, "plain"))

    # Attach files
    if attachments:
        for attachment in attachments:
            filename = attachment.get("filename", "attachment")
            content = attachment.get("content")  # Base64 encoded content
            mime_type = attachment.get("mimeType", "application/octet-stream")

            if not content:
                continue

            # Decode base64 content
            try:
                file_data = base64.b64decode(content)
            except Exception as e:
                logger.error(f"Error decoding attachment {filename}: {str(e)}")
                continue

            # Determine main type and subtype
            main_type, sub_type = (
                mime_type.split("/", 1)
                if "/" in mime_type
                else ("application", "octet-stream")
            )

            if main_type == "text":
                part = email.mime.text.MIMEText(
                    file_data.decode("utf-8", errors="replace"), _subtype=sub_type
                )
            else:
                part = email.mime.base.MIMEBase(main_type, sub_type)
                part.set_payload(file_data)
                email.encoders.encode_base64(part)

            part.add_header("Content-Disposition", f"attachment; filename={filename}")
            message.attach(part)

    return message


async def create_gmail_service(user_id, api_key=None):
    """Create a new Gmail service instance for this request"""
    credentials = await get_credentials(user_id, SERVICE_NAME, api_key=api_key)
    return build("gmail", "v1", credentials=credentials)


def create_server(user_id, api_key=None):
    """Create a new server instance with optional user context"""
    server = Server("gmail-server")

    server.user_id = user_id
    server.api_key = api_key

    @server.list_resources()
    async def handle_list_resources(
        cursor: Optional[str] = None,
    ) -> list[Resource]:
        """List Gmail labels as resources"""
        logger.info(
            f"Listing label resources for user: {server.user_id} with cursor: {cursor}"
        )

        gmail_service = await create_gmail_service(
            server.user_id, api_key=server.api_key
        )

        try:
            # Get all labels
            results = gmail_service.users().labels().list(userId="me").execute()
            labels = results.get("labels", [])

            resources = []
            for label in labels:
                # Skip system labels that aren't useful to show
                if label.get("type") == "system" and label.get("id") in [
                    "CHAT",
                    "SENT",
                    "SPAM",
                    "TRASH",
                    "DRAFT",
                ]:
                    continue

                label_id = label.get("id")
                label_name = label.get("name", "Unknown Label")

                # Get message count for this label
                label_data = (
                    gmail_service.users()
                    .labels()
                    .get(userId="me", id=label_id)
                    .execute()
                )
                total_messages = label_data.get("messagesTotal", 0)
                unread_messages = label_data.get("messagesUnread", 0)

                description = (
                    f"{label_name} ({unread_messages} unread of {total_messages} total)"
                )

                resource = Resource(
                    uri=f"gmail://label/{label_id}",
                    mimeType="application/gmail.label",
                    name=label_name,
                    description=description,
                )
                resources.append(resource)

            return resources
        except Exception as e:
            logger.error(f"Error listing Gmail labels: {str(e)}")
            return []

    @server.read_resource()
    async def handle_read_resource(uri: AnyUrl) -> Iterable[ReadResourceContents]:
        """Read emails from a Gmail label"""
        logger.info(f"Reading label resource: {uri} for user: {server.user_id}")

        gmail_service = await create_gmail_service(
            server.user_id, api_key=server.api_key
        )

        uri_str = str(uri)
        if not uri_str.startswith("gmail://label/"):
            raise ValueError(f"Invalid Gmail label URI: {uri_str}")

        label_id = uri_str.replace("gmail://label/", "")

        # Get messages in this label
        results = (
            gmail_service.users()
            .messages()
            .list(userId="me", labelIds=[label_id], maxResults=10)
            .execute()
        )

        messages = results.get("messages", [])

        if not messages:
            return [
                ReadResourceContents(
                    content="No messages in this label", mime_type="text/plain"
                )
            ]

        # Format messages
        formatted_messages = []

        for message in messages:
            # Get message data
            msg_data = (
                gmail_service.users()
                .messages()
                .get(
                    userId="me",
                    id=message["id"],
                    format="metadata",
                    metadataHeaders=["Subject", "From", "Date"],
                )
                .execute()
            )

            # Extract headers
            headers = {}
            for header in msg_data.get("payload", {}).get("headers", []):
                headers[header["name"]] = header["value"]

            subject = headers.get("Subject", "No Subject")
            sender = headers.get("From", "Unknown")
            date = headers.get("Date", "Unknown date")

            # Format message summary
            message_summary = (
                f"ID: gmail://message/{message['id']}\n"
                f"Subject: {subject}\n"
                f"From: {sender}\n"
                f"Date: {date}\n"
                f"---\n"
            )
            formatted_messages.append(message_summary)

        content = "\n".join(formatted_messages)
        return [ReadResourceContents(content=content, mime_type="text/plain")]

    @server.list_tools()
    async def handle_list_tools() -> list[Tool]:
        """List available email tools"""
        logger.info(f"Listing email tools for user: {server.user_id}")
        return [
            Tool(
                name="read_emails",
                description="Search and read emails in Gmail with full text body and attachment information",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Search query (e.g., 'from:someone@example.com' or 'subject:important')",
                        },
                        "max_results": {
                            "type": "integer",
                            "description": "Maximum number of emails to return (default: 10)",
                        },
                        "include_body": {
                            "type": "boolean",
                            "description": "Include email body text in results (default: true)",
                        },
                        "include_attachments_info": {
                            "type": "boolean",
                            "description": "Include attachment information in results (default: true)",
                        },
                    },
                    "required": ["query"],
                },
            ),
            Tool(
                name="send_email",
                description="Send an email through Gmail with optional attachments",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "to": {
                            "type": "string",
                            "description": "Recipient email address",
                        },
                        "subject": {"type": "string", "description": "Email subject"},
                        "body": {
                            "type": "string",
                            "description": "Email body (plain text)",
                        },
                        "cc": {
                            "type": "string",
                            "description": "CC recipients (comma separated)",
                        },
                        "bcc": {
                            "type": "string",
                            "description": "BCC recipients (comma separated)",
                        },
                        "attachments": {
                            "type": "array",
                            "description": "Array of attachments to include",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "filename": {
                                        "type": "string",
                                        "description": "Name of the file",
                                    },
                                    "content": {
                                        "type": "string",
                                        "description": "Base64-encoded file content",
                                    },
                                    "mimeType": {
                                        "type": "string",
                                        "description": "MIME type of the file (e.g., 'application/pdf', 'image/png')",
                                    },
                                },
                                "required": ["filename", "content", "mimeType"],
                            },
                        },
                    },
                    "required": ["to", "subject", "body"],
                },
            ),
            Tool(
                name="forward_email",
                description="Forward an email to recipients, preserving original content and attachments",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "email_id": {
                            "type": "string",
                            "description": "ID of the email to forward",
                        },
                        "to": {
                            "type": "string",
                            "description": "Recipient email address(es) (comma separated)",
                        },
                        "cc": {
                            "type": "string",
                            "description": "CC recipients (comma separated)",
                        },
                        "bcc": {
                            "type": "string",
                            "description": "BCC recipients (comma separated)",
                        },
                        "additional_message": {
                            "type": "string",
                            "description": "Additional message to add before the forwarded content",
                        },
                        "include_attachments": {
                            "type": "boolean",
                            "description": "Whether to include original attachments (default: true)",
                        },
                    },
                    "required": ["email_id", "to"],
                },
            ),
            Tool(
                name="update_email",
                description="Update email labels (mark as read/unread, move to folders)",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "email_id": {
                            "type": "string",
                            "description": "Email ID to modify",
                        },
                        "add_labels": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Labels to add (e.g., 'INBOX', 'STARRED', 'IMPORTANT')",
                        },
                        "remove_labels": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Labels to remove (e.g., 'UNREAD')",
                        },
                    },
                    "required": ["email_id"],
                },
            ),
            Tool(
                name="get_attachment",
                description="Get a temporary download URL for an email attachment",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "email_id": {
                            "type": "string",
                            "description": "ID of the email containing the attachment",
                        },
                        "attachment_id": {
                            "type": "string",
                            "description": "ID of the attachment to download (from read_emails results)",
                        },
                    },
                    "required": ["email_id", "attachment_id"],
                },
            ),
        ]

    @server.call_tool()
    async def handle_call_tool(
        name: str, arguments: dict | None
    ) -> list[TextContent | ImageContent | EmbeddedResource]:
        """Handle email tool execution requests"""
        logger.info(
            f"User {server.user_id} calling tool: {name} with arguments: {arguments}"
        )

        gmail_service = await create_gmail_service(
            server.user_id, api_key=server.api_key
        )

        if name == "read_emails":
            if not arguments or "query" not in arguments:
                raise ValueError("Missing query parameter")

            query = arguments["query"]
            max_results = int(arguments.get("max_results", 10))
            include_body = arguments.get("include_body", True)
            include_attachments_info = arguments.get("include_attachments_info", True)

            results = (
                gmail_service.users()
                .messages()
                .list(userId="me", q=query, maxResults=max_results)
                .execute()
            )

            messages = results.get("messages", [])
            if not messages:
                return [
                    TextContent(
                        type="text", text="No emails found matching your query."
                    )
                ]

            email_summaries = []
            for message in messages:
                # Fetch full message to get body and attachments
                msg = (
                    gmail_service.users()
                    .messages()
                    .get(userId="me", id=message["id"], format="full")
                    .execute()
                )

                # Extract headers
                subject = "No Subject"
                sender = "Unknown"
                date = "Unknown"
                for header in msg.get("payload", {}).get("headers", []):
                    if header["name"] == "Subject":
                        subject = header["value"]
                    elif header["name"] == "From":
                        sender = header["value"]
                    elif header["name"] == "Date":
                        date = header["value"]

                # Get labels
                labels = msg.get("labelIds", [])
                is_unread = "UNREAD" in labels

                # Build email summary
                email_summary = (
                    f"ID: {message['id']}\n"
                    f"From: {sender}\n"
                    f"Subject: {subject}\n"
                    f"Date: {date}\n"
                    f"Status: {'Unread' if is_unread else 'Read'}\n"
                    f"Labels: {', '.join(labels)}\n"
                )

                # Parse email body if requested
                if include_body:
                    payload = msg.get("payload", {})
                    body = parse_email_body(payload)

                    if body["text"]:
                        email_summary += f"\nBody (Text):\n{body['text'][:1000]}"
                        if len(body["text"]) > 1000:
                            email_summary += f"\n... (truncated, total length: {len(body['text'])} chars)"
                    elif body["html"]:
                        email_summary += f"\nBody (HTML):\n{body['html'][:1000]}"
                        if len(body["html"]) > 1000:
                            email_summary += f"\n... (truncated, total length: {len(body['html'])} chars)"
                    else:
                        email_summary += "\nBody: (No text content found)"

                # Get attachment info if requested
                if include_attachments_info:
                    payload = msg.get("payload", {})
                    attachments = get_attachments_info(payload)
                    if attachments:
                        email_summary += f"\n\nAttachments ({len(attachments)}):"
                        for att in attachments:
                            size_kb = att["size"] / 1024 if att["size"] else 0
                            email_summary += (
                                f"\n  - {att['filename']} "
                                f"({att['mimeType']}, {size_kb:.1f} KB, "
                                f"attachmentId: {att['attachmentId']})"
                            )

                email_summaries.append(email_summary)

            result = f"Found {len(messages)} emails:\n\n" + "\n\n---\n\n".join(
                email_summaries
            )
            return [TextContent(type="text", text=result)]

        elif name == "send_email":
            if not arguments or not all(
                k in arguments for k in ["to", "subject", "body"]
            ):
                raise ValueError("Missing required parameters: to, subject, body")

            # Create email message with optional attachments
            message = create_message_with_attachments(
                to=arguments["to"],
                subject=arguments["subject"],
                body=arguments["body"],
                cc=arguments.get("cc"),
                bcc=arguments.get("bcc"),
                attachments=arguments.get("attachments"),
            )

            # Encode the message
            raw_message = urlsafe_b64encode(message.as_bytes()).decode()

            # Send the message
            try:
                sent_message = (
                    gmail_service.users()
                    .messages()
                    .send(userId="me", body={"raw": raw_message})
                    .execute()
                )

                attachment_info = ""
                if arguments.get("attachments"):
                    num_attachments = len(arguments["attachments"])
                    attachment_info = f" with {num_attachments} attachment(s)"

                return [
                    TextContent(
                        type="text",
                        text=f"Email sent successfully to {arguments['to']}{attachment_info}. Message ID: {sent_message['id']}",
                    )
                ]
            except Exception as e:
                return [
                    TextContent(type="text", text=f"Failed to send email: {str(e)}")
                ]

        elif name == "forward_email":
            if not arguments or not all(k in arguments for k in ["email_id", "to"]):
                raise ValueError("Missing required parameters: email_id, to")

            email_id = arguments["email_id"]
            include_attachments = arguments.get("include_attachments", True)

            # Fetch the original email
            try:
                original_msg = (
                    gmail_service.users()
                    .messages()
                    .get(userId="me", id=email_id, format="full")
                    .execute()
                )
            except Exception as e:
                return [
                    TextContent(
                        type="text", text=f"Failed to fetch original email: {str(e)}"
                    )
                ]

            # Extract original headers
            original_subject = "No Subject"
            original_from = "Unknown"
            original_date = "Unknown"
            for header in original_msg.get("payload", {}).get("headers", []):
                if header["name"] == "Subject":
                    original_subject = header["value"]
                elif header["name"] == "From":
                    original_from = header["value"]
                elif header["name"] == "Date":
                    original_date = header["value"]

            # Parse original body
            payload = original_msg.get("payload", {})
            body = parse_email_body(payload)
            original_body = body.get("text") or body.get("html") or "(No content)"

            # Build forwarded message body
            forward_body = ""
            if arguments.get("additional_message"):
                forward_body = f"{arguments['additional_message']}\n\n"

            forward_body += (
                f"---------- Forwarded message ---------\n"
                f"From: {original_from}\n"
                f"Date: {original_date}\n"
                f"Subject: {original_subject}\n\n"
                f"{original_body}"
            )

            # Prepare attachments if requested
            attachments_list = []
            if include_attachments:
                attachments_info = get_attachments_info(payload)
                for att_info in attachments_info:
                    if att_info.get("attachmentId"):
                        # Download the attachment
                        att_data = download_attachment(
                            gmail_service, "me", email_id, att_info["attachmentId"]
                        )
                        if att_data:
                            attachments_list.append(
                                {
                                    "filename": att_info["filename"],
                                    "content": base64.b64encode(att_data).decode(),
                                    "mimeType": att_info["mimeType"],
                                }
                            )

            # Create and send the forwarded message
            forward_subject = (
                f"Fwd: {original_subject}"
                if not original_subject.startswith("Fwd:")
                else original_subject
            )

            message = create_message_with_attachments(
                to=arguments["to"],
                subject=forward_subject,
                body=forward_body,
                cc=arguments.get("cc"),
                bcc=arguments.get("bcc"),
                attachments=attachments_list if attachments_list else None,
            )

            # Encode and send
            raw_message = urlsafe_b64encode(message.as_bytes()).decode()

            try:
                sent_message = (
                    gmail_service.users()
                    .messages()
                    .send(userId="me", body={"raw": raw_message})
                    .execute()
                )

                attachment_info = ""
                if attachments_list:
                    attachment_info = f" with {len(attachments_list)} attachment(s)"

                return [
                    TextContent(
                        type="text",
                        text=f"Email forwarded successfully to {arguments['to']}{attachment_info}. Message ID: {sent_message['id']}",
                    )
                ]
            except Exception as e:
                return [
                    TextContent(type="text", text=f"Failed to forward email: {str(e)}")
                ]

        elif name == "update_email":
            if not arguments or "email_id" not in arguments:
                raise ValueError("Missing email_id parameter")

            email_id = arguments["email_id"]
            add_labels = arguments.get("add_labels", [])
            remove_labels = arguments.get("remove_labels", [])

            if not add_labels and not remove_labels:
                return [
                    TextContent(
                        type="text",
                        text="No label changes specified. Please provide labels to add or remove.",
                    )
                ]

            # Modify labels
            try:
                result = (
                    gmail_service.users()
                    .messages()
                    .modify(
                        userId="me",
                        id=email_id,
                        body={
                            "addLabelIds": add_labels,
                            "removeLabelIds": remove_labels,
                        },
                    )
                    .execute()
                )

                # Get updated labels
                updated_labels = result.get("labelIds", [])

                return [
                    TextContent(
                        type="text",
                        text=f"Successfully updated email {email_id}.\n"
                        f"Added labels: {', '.join(add_labels) if add_labels else 'None'}\n"
                        f"Removed labels: {', '.join(remove_labels) if remove_labels else 'None'}\n"
                        f"Current labels: {', '.join(updated_labels)}",
                    )
                ]
            except Exception as e:
                return [
                    TextContent(type="text", text=f"Failed to update email: {str(e)}")
                ]

        elif name == "get_attachment":
            if not arguments or not all(
                k in arguments for k in ["email_id", "attachment_id"]
            ):
                raise ValueError("Missing required parameters: email_id, attachment_id")

            email_id = arguments["email_id"]
            attachment_id = arguments["attachment_id"]

            # Fetch message to get attachment metadata
            try:
                msg = (
                    gmail_service.users()
                    .messages()
                    .get(userId="me", id=email_id, format="full")
                    .execute()
                )
            except Exception as e:
                return [
                    TextContent(type="text", text=f"Failed to fetch email: {str(e)}")
                ]

            # Find the matching attachment metadata
            payload = msg.get("payload", {})
            attachments_info = get_attachments_info(payload)
            attachment_meta = None
            for att in attachments_info:
                if att.get("attachmentId") == attachment_id:
                    attachment_meta = att
                    break

            if not attachment_meta:
                return [
                    TextContent(
                        type="text",
                        text=f"Attachment with ID {attachment_id} not found in email {email_id}.",
                    )
                ]

            # Download the attachment binary data
            att_data = download_attachment(gmail_service, "me", email_id, attachment_id)
            if not att_data:
                return [
                    TextContent(
                        type="text",
                        text=f"Failed to download attachment {attachment_meta['filename']}.",
                    )
                ]

            # Upload to storage and get signed URL
            try:
                storage = get_storage_service()
                download_url = storage.upload_temporary(
                    data=att_data,
                    filename=attachment_meta["filename"],
                    mime_type=attachment_meta["mimeType"],
                )
            except Exception as e:
                return [
                    TextContent(
                        type="text",
                        text=f"Failed to upload attachment to storage: {str(e)}",
                    )
                ]

            size_kb = len(att_data) / 1024
            return [
                TextContent(
                    type="text",
                    text=(
                        f"Attachment: {attachment_meta['filename']}\n"
                        f"Type: {attachment_meta['mimeType']}\n"
                        f"Size: {size_kb:.1f} KB\n"
                        f"Download URL (expires in 1 hour): {download_url}"
                    ),
                )
            ]

        raise ValueError(f"Unknown tool: {name}")

    return server


server = create_server


def get_initialization_options(server_instance: Server) -> InitializationOptions:
    """Get the initialization options for the server"""
    return InitializationOptions(
        server_name="gmail-server",
        server_version="1.0.0",
        capabilities=server_instance.get_capabilities(
            notification_options=NotificationOptions(),
            experimental_capabilities={},
        ),
    )


# Main handler allows users to auth
if __name__ == "__main__":
    if sys.argv[1].lower() == "auth":
        user_id = "local"
        # Run authentication flow
        authenticate_and_save_credentials(user_id, SERVICE_NAME, SCOPES)
    else:
        print("Usage:")
        print("  python main.py auth - Run authentication flow for a user")
        print("Note: To run the server normally, use the guMCP server framework.")
