import os
import sys
from typing import Optional, Iterable, Dict, Any, List
import json
import asyncio
from typing import Callable, TypeVar

# Add both project root and src directory to Python path
# Get the project root directory and add to path
project_root = os.path.abspath(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
)
sys.path.insert(0, project_root)
sys.path.insert(0, os.path.join(project_root, "src"))

import logging
from pathlib import Path
import aiohttp
from google.cloud import firestore
from google.oauth2 import service_account

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

from src.utils.google.util import (
    authenticate_and_save_credentials,
    get_credentials,
)

SERVICE_NAME = Path(__file__).parent.name
SCOPES = [
    "https://www.googleapis.com/auth/cloud-platform",
    "https://www.googleapis.com/auth/datastore",
]

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(SERVICE_NAME)

T = TypeVar("T")


async def with_exponential_backoff(
    func: Callable[[], T],
    max_retries: int = 3,
    initial_delay: float = 1.0,
    max_delay: float = 10.0,
    backoff_factor: float = 2.0,
) -> T:
    """
    Execute a function with exponential backoff retry logic

    Args:
        func: Async function to execute
        max_retries: Maximum number of retries
        initial_delay: Initial delay in seconds
        max_delay: Maximum delay between retries
        backoff_factor: Multiplier for the delay after each retry
    """
    delay = initial_delay
    last_exception = None

    for attempt in range(max_retries + 1):
        try:
            return await func()
        except Exception as e:
            last_exception = e
            if attempt == max_retries:
                raise last_exception

            logger.warning(
                f"Request failed (attempt {attempt + 1}/{max_retries + 1}): {str(e)}"
            )
            await asyncio.sleep(delay)
            delay = min(delay * backoff_factor, max_delay)


def convert_input_to_value(value):
    """Convert input value to Firestore value format"""
    if isinstance(value, str):
        return {"stringValue": value}
    elif isinstance(value, bool):
        return {"booleanValue": value}
    elif isinstance(value, int):
        return {"integerValue": str(value)}
    elif isinstance(value, float):
        return {"doubleValue": value}
    elif isinstance(value, list):
        return {"arrayValue": {"values": [convert_input_to_value(item) for item in value]}}
    else:
        return {"stringValue": str(value)}


def firestore_document_to_json(doc):
    """Convert Firestore document to JSON format"""
    if hasattr(doc, 'to_dict'):
        return doc.to_dict()
    return doc


def convert_firestore_to_serializable(obj):
    """Convert Firestore objects to JSON serializable format"""
    try:
        if hasattr(obj, 'to_dict'):
            return obj.to_dict()
        elif hasattr(obj, 'path'):
            # DocumentReference or CollectionReference
            return str(obj.path)
        elif hasattr(obj, 'to_rfc3339'):
            # Firestore Timestamp objects (DatetimeWithNanoseconds)
            return obj.to_rfc3339()
        elif hasattr(obj, 'timestamp') and callable(getattr(obj, 'timestamp')):
            # Other Firestore datetime objects - check if timestamp is callable
            try:
                return obj.timestamp().isoformat()
            except (AttributeError, TypeError):
                # If timestamp() fails, try other methods
                if hasattr(obj, 'isoformat'):
                    return obj.isoformat()
                return str(obj)
        elif isinstance(obj, dict):
            return {key: convert_firestore_to_serializable(value) for key, value in obj.items()}
        elif isinstance(obj, list):
            return [convert_firestore_to_serializable(item) for item in obj]
        else:
            return obj
    except Exception as e:
        # Log the error and return string representation as fallback
        logger.warning(f"Failed to convert object {type(obj)} to serializable format: {e}")
        return str(obj)


def process_document_data(data, client):
    """Process document data to handle complex field types"""
    if isinstance(data, dict):
        processed = {}
        for key, value in data.items():
            if isinstance(value, dict) and '_type' in value and '_value' in value:
                # Handle complex field types
                field_type = value['_type']
                field_value = value['_value']
                
                if field_type == 'timestamp':
                    # Convert ISO string to datetime object
                    try:
                        from datetime import datetime
                        if 'T' in field_value and ('Z' in field_value or '+' in field_value or '-' in field_value[-6:]):
                            processed[key] = datetime.fromisoformat(field_value.replace('Z', '+00:00'))
                        else:
                            processed[key] = datetime.fromisoformat(field_value)
                        logger.info(f"Converted timestamp field '{key}' with value '{field_value}'")
                    except (ValueError, TypeError) as e:
                        logger.warning(f"Failed to convert timestamp field '{key}': {e}. Using as string.")
                        processed[key] = field_value
                elif field_type == 'reference':
                    # Create DocumentReference
                    try:
                        processed[key] = client.document(field_value)
                        logger.info(f"Converted reference field '{key}' with path '{field_value}'")
                    except Exception as e:
                        logger.warning(f"Failed to create reference field '{key}': {e}. Using as string.")
                        processed[key] = field_value
                else:
                    # Unknown type, use as-is
                    processed[key] = field_value
            else:
                # Recursively process nested objects
                processed[key] = process_document_data(value, client)
        return processed
    elif isinstance(data, list):
        return [process_document_data(item, client) for item in data]
    else:
        return data


async def create_firestore_client(user_id, api_key=None, project_id=None, use_emulator=False):
    """Create a Firestore client"""
    try:
        # Get Google OAuth2 credentials
        credentials = await get_credentials(user_id, SERVICE_NAME, api_key)
        
        # Try to get project_id from auth client metadata
        final_project_id = project_id
        metadata = {}

        if not final_project_id:
            try:
                from src.auth.factory import create_auth_client
                auth_client = create_auth_client(api_key=api_key)
                credentials_data = auth_client.get_user_credentials(SERVICE_NAME, user_id)
                
                if credentials_data and isinstance(credentials_data, dict):
                    # Extract project ID from metadata (now included in credentials)
                    if "metadata" in credentials_data:
                        metadata = credentials_data.get("metadata", {})
                        final_project_id = metadata.get("projectId") or metadata.get("project_id")
                        logger.info(f"Extracted project_id from metadata: {final_project_id}")
                        logger.info(f"Available metadata: {metadata}")
            except Exception as e:
                logger.warning(f"Failed to extract project_id from metadata: {e}")
        
        # Fallback to Application Default Credentials project
        if not final_project_id:
            try:
                from google.auth import default
                _, default_project = default()
                final_project_id = default_project
                logger.info(f"Using project_id from Application Default Credentials: {final_project_id}")
            except Exception:
                logger.warning("No project_id found in metadata or Application Default Credentials")
        
        if use_emulator:
            os.environ['FIRESTORE_EMULATOR_HOST'] = 'localhost:8080'
        
        # Create Firestore client with OAuth2 credentials
        client = firestore.Client(project=final_project_id, credentials=credentials)
        
        # Store metadata in client for potential future use (non-breaking)
        if metadata:
            client._metadata = metadata
        
        return client
    except Exception as e:
        logger.error(f"Failed to create Firestore client: {str(e)}")
        raise


def create_server(user_id, api_key=None):
    """Create a new server instance with optional user context"""
    server = Server("firestore-server")

    server.user_id = user_id
    server.api_key = api_key

    @server.list_resources()
    async def handle_list_resources(
        cursor: Optional[str] = None,
    ) -> list[Resource]:
        """List Firestore collections"""
        logger.info(
            f"Listing resources for user: {server.user_id} with cursor: {cursor}"
        )

        try:
            client = await create_firestore_client(server.user_id, server.api_key)
            collections = client.collections()
            
            # List collections
            resources = []
            
            for collection in collections:
                logger.info(f"Found collection: {collection.id}")
                resource = Resource(
                    uri=f"firestore://{collection.id}",
                    name=f"Collection: {collection.id}",
                    description=f"Firestore collection: {collection.id}",
                )
                resources.append(resource)
            
            logger.info(f"Total collections found: {len(resources)}")
            return resources
        except Exception as e:
            logger.error(f"Failed to list resources: {str(e)}")
            return []

    @server.read_resource()
    async def handle_read_resource(uri: AnyUrl) -> Iterable[ReadResourceContents]:
        """Read Firestore collection by URI"""
        logger.info(f"Reading resource: {uri} for user: {server.user_id}")

        uri_str = str(uri)
        if not uri_str.startswith("firestore://"):
            raise ValueError(f"Invalid Firestore URI format: {uri}")

        try:
            client = await create_firestore_client(server.user_id, server.api_key)
            
            # Extract collection path from URI
            collection_path = uri_str.replace("firestore://", "")
            
            # Query the collection
            docs = client.collection(collection_path).limit(10).stream()
            
            # Convert documents to JSON
            documents = []
            for doc in docs:
                doc_data = doc.to_dict()
                doc_data['_id'] = doc.id
                # Convert any DocumentReference objects to strings
                doc_data = convert_firestore_to_serializable(doc_data)
                documents.append(doc_data)
            
            formatted_data = json.dumps(documents, indent=2)
            
            return [
                ReadResourceContents(
                    content=formatted_data, mime_type="application/json"
                )
            ]
        except Exception as e:
            logger.error(f"Failed to read resource: {str(e)}")
            return [
                ReadResourceContents(
                    content=f"Error reading resource: {str(e)}", mime_type="text/plain"
                )
            ]

    @server.list_tools()
    async def handle_list_tools() -> list[Tool]:
        """List available tools"""
        logger.info(f"Listing tools for user: {server.user_id}")
        return [
            Tool(
                name="query_collection",
                description="Query a Firestore collection with advanced filtering, ordering, and pagination. Use this to search for documents that match specific criteria, sort results, and limit the number of returned documents. Perfect for finding specific data within a collection.\n\nUsage Examples:\n- Find all users with status 'active': collection_path='users', filters=[{field:'status', op:'EQUAL', compare_value:{string_value:'active'}}]\n- Get recent orders: collection_path='orders', order={orderBy:'created_at', orderByDirection:'DESCENDING'}, limit=20\n- Search by email: collection_path='users', filters=[{field:'email', op:'EQUAL', compare_value:{string_value:'user@example.com'}}]\n- Filter by timestamp (using date_value): collection_path='orders', filters=[{field:'created_at', op:'GREATER_THAN', compare_value:{date_value:'2023-10-23T00:00:00Z'}}]\n- Get orders from last week: collection_path='orders', filters=[{field:'created_at', op:'GREATER_THAN_OR_EQUAL', compare_value:{date_value:'2023-10-16T00:00:00Z'}}]",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "database": {
                            "type": "string",
                            "description": "Database id to use. Defaults to `(default)` if unspecified.",
                        },
                        "collection_path": {
                            "type": "string",
                            "description": "The collection path to query. Examples: 'users', 'companies', 'orders', 'users/123/orders' (for subcollections)",
                        },
                        "filters": {
                            "type": "array",
                            "description": "Array of filter conditions to apply to the query. Each filter specifies a field, operator, and value to match against. For timestamp fields, use ISO 8601 format (e.g., '2023-10-23T19:30:16.740Z') or RFC3339 format.",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "compare_value": {
                                        "type": "object",
                                        "description": "One and only one value may be specified per filters object.",
                                        "properties": {
                                            "string_value": {
                                                "type": "string",
                                                "description": "The string value to compare against. For timestamp fields, use ISO 8601 format (e.g., '2023-10-23T19:30:16.740Z').",
                                            },
                                            "boolean_value": {
                                                "type": "string",
                                                "description": "The boolean value to compare against.",
                                            },
                                            "string_array_value": {
                                                "type": "array",
                                                "items": {"type": "string"},
                                                "description": "The string value to compare against.",
                                            },
                                            "integer_value": {
                                                "type": "number",
                                                "description": "The integer value to compare against.",
                                            },
                                            "double_value": {
                                                "type": "number",
                                                "description": "The double value to compare against.",
                                            },
                                            "date_value": {
                                                "type": "string",
                                                "description": "The date/timestamp value to compare against. Use ISO 8601 format (e.g., '2023-10-23T19:30:16.740Z'). This will be automatically converted to a datetime object.",
                                            },
                                        },
                                    },
                                    "field": {
                                        "type": "string",
                                        "description": "The document field to filter against (e.g., 'name', 'email', 'created_at', 'updated_at'). For timestamp fields, use ISO 8601 format in compare_value.",
                                    },
                                    "op": {
                                        "type": "string",
                                        "enum": [
                                            "OPERATOR_UNSPECIFIED",
                                            "LESS_THAN",
                                            "LESS_THAN_OR_EQUAL",
                                            "GREATER_THAN",
                                            "GREATER_THAN_OR_EQUAL",
                                            "EQUAL",
                                            "NOT_EQUAL",
                                            "ARRAY_CONTAINS",
                                            "ARRAY_CONTAINS_ANY",
                                            "IN",
                                            "NOT_IN",
                                        ],
                                        "description": "The comparison operator to use (EQUAL, NOT_EQUAL, GREATER_THAN, LESS_THAN, etc.). For timestamp fields, use GREATER_THAN, LESS_THAN, GREATER_THAN_OR_EQUAL, LESS_THAN_OR_EQUAL for date ranges.",
                                    },
                                },
                                "required": ["compare_value", "field", "op"],
                            },
                        },
                    },
                    "order": {
                        "type": "object",
                        "description": "Optional sorting configuration. Specifies which field to sort by and the direction (ascending/descending).",
                        "properties": {
                            "orderBy": {
                                "type": "string",
                                "description": "The field name to sort by (e.g., 'created_at', 'name', 'price')",
                            },
                            "orderByDirection": {
                                "type": "string",
                                "enum": ["ASCENDING", "DESCENDING"],
                                "description": "Sort direction: ASCENDING (A-Z, 1-9) or DESCENDING (Z-A, 9-1)",
                            },
                        },
                        "required": ["orderBy", "orderByDirection"],
                    },
                    "limit": {
                        "type": "number",
                        "description": "Maximum number of documents to return (default: 10, max recommended: 100 for performance)",
                    },
                    "use_emulator": {
                        "type": "boolean",
                        "default": False,
                        "description": "Target the Firestore emulator if true.",
                    },
                    "required": ["collection_path"],
                },
                # outputSchema={
                #     "type": "array",
                #     "items": {"type": "object"},
                #     "description": "Array of Firestore documents matching the query",
                # },
            ),
            Tool(
                name="get_document",
                description="Retrieve a specific Firestore document by its full path. Use this when you know the exact document ID and want to fetch a single document's data. Perfect for getting detailed information about a specific record.\n\nUsage Examples:\n- Get user profile: document_path='users/123'\n- Get company details: document_path='companies/abc-456'\n- Get order information: document_path='orders/order-789'",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "document_path": {
                            "type": "string",
                            "description": "Full path to the document. Examples: 'users/123', 'companies/abc-456', 'orders/order-789'",
                        },
                        "database": {
                            "type": "string",
                            "description": "Database id to use. Defaults to `(default)` if unspecified.",
                        },
                        "use_emulator": {
                            "type": "boolean",
                            "default": False,
                            "description": "Target the Firestore emulator if true.",
                        },
                    },
                    "required": ["document_path"],
                },
                # outputSchema={
                #     "type": "object",
                #     "description": "Firestore document data",
                # },
            ),
            Tool(
                name="list_collections",
                description="List all top-level collections in the Firestore database. Use this to discover what collections are available before querying or to get an overview of your database structure. Returns collection names only.\n\nUsage Examples:\n- Discover available collections: No parameters needed\n- Get database overview: Use before querying to see what data is available\n- Check if a collection exists: Look for specific collection names in the results",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "database": {
                            "type": "string",
                            "description": "Database id to use. Defaults to `(default)` if unspecified.",
                        },
                        "use_emulator": {
                            "type": "boolean",
                            "default": False,
                            "description": "Target the Firestore emulator if true.",
                        },
                    },
                },
                # outputSchema={
                #     "type": "array",
                #     "items": {"type": "string"},
                #     "description": "Array of collection names",
                # },
            ),
            Tool(
                name="create_document",
                description="Create a new document in a Firestore collection. Use this to add new records to your database. The document_data must contain actual field values - it cannot be empty. Supports complex field types like timestamps and document references using special syntax.\n\nIMPORTANT: document_data must contain real data with field names and values. Do not send empty objects.\n\nUsage Examples:\n- Create a user: collection_path='users', document_data={name:'John Doe', email:'john@example.com', created_at:{_type:'timestamp', _value:'2023-10-23T19:30:16Z'}}\n- Create with reference: collection_path='orders', document_data={user_id:{_type:'reference', _value:'users/123'}, amount:99.99, status:'pending'}\n- Simple document: collection_path='products', document_data={name:'Widget', price:29.99, active:true, category:'electronics'}\n- With nested data: collection_path='profiles', document_data={user:{name:'Jane', age:30}, settings:{theme:'dark', notifications:true}}",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "collection_path": {
                            "type": "string",
                            "description": "The collection path where the document will be created. Examples: 'users', 'orders', 'products'",
                        },
                        "document_data": {
                            "type": "object",
                            "additionalProperties": True,
                            "description": "REQUIRED: The document data to create. Must contain actual field names and values (cannot be empty). For complex types, use {_type: 'timestamp', _value: 'ISO_string'} for timestamps and {_type: 'reference', _value: 'path/to/doc'} for references. Example: {name:'John', age:30, created_at:{_type:'timestamp', _value:'2023-10-23T19:30:16Z'}}",
                        },
                        "document_id": {
                            "type": "string",
                            "description": "Optional custom document ID. If not provided, Firestore will auto-generate one.",
                        },
                        "database": {
                            "type": "string",
                            "description": "Database id to use. Defaults to `(default)` if unspecified.",
                        },
                        "use_emulator": {
                            "type": "boolean",
                            "default": False,
                            "description": "Target the Firestore emulator if true.",
                        },
                    },
                    "required": ["collection_path", "document_data"],
                },
            ),
            Tool(
                name="update_document",
                description="Update an existing document in Firestore. Use this to modify existing records. The document_data must contain actual field values to update - it cannot be empty. Supports complex field types like timestamps and document references using special syntax.\n\nIMPORTANT: document_data must contain real field names and values to update. Do not send empty objects.\n\nUsage Examples:\n- Update user email: document_path='users/123', document_data={email:'newemail@example.com', updated_at:{_type:'timestamp', _value:'2023-10-23T19:30:16Z'}}\n- Update with reference: document_path='orders/456', document_data={status:'shipped', shipped_at:{_type:'timestamp', _value:'2023-10-23T19:30:16Z'}, tracking_number:'TRK123'}\n- Simple update: document_path='products/789', document_data={price:39.99, in_stock:false, last_updated:{_type:'timestamp', _value:'2023-10-23T19:30:16Z'}}\n- Update multiple fields: document_path='users/456', document_data={name:'Jane Smith', age:31, active:true, profile:{bio:'Updated bio', location:'New York'}}",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "document_path": {
                            "type": "string",
                            "description": "Full path to the document to update. Examples: 'users/123', 'orders/456', 'products/789'",
                        },
                        "document_data": {
                            "type": "object",
                            "additionalProperties": True,
                            "description": "REQUIRED: The document data to update. Must contain actual field names and values (cannot be empty). For complex types, use {_type: 'timestamp', _value: 'ISO_string'} for timestamps and {_type: 'reference', _value: 'path/to/doc'} for references. Example: {email:'new@example.com', age:31, updated_at:{_type:'timestamp', _value:'2023-10-23T19:30:16Z'}}",
                        },
                        "database": {
                            "type": "string",
                            "description": "Database id to use. Defaults to `(default)` if unspecified.",
                        },
                        "use_emulator": {
                            "type": "boolean",
                            "default": False,
                            "description": "Target the Firestore emulator if true.",
                        },
                    },
                    "required": ["document_path", "document_data"],
                },
            ),
        ]

    @server.call_tool()
    async def handle_call_tool(
        name: str, arguments: Dict[str, Any] | None
    ) -> List[TextContent | ImageContent | EmbeddedResource]:
        logger.info(
            f"User {server.user_id} calling tool: {name} with arguments: {arguments}"
        )

        arguments = arguments or {}

        try:
            client = await create_firestore_client(
                server.user_id, 
                server.api_key,
                use_emulator=arguments.get("use_emulator", False)
            )

            if name == "query_collection":
                collection_path = arguments.get("collection_path")
                filters = arguments.get("filters", [])
                order = arguments.get("order")
                limit = arguments.get("limit", 10)
                database = arguments.get("database", "(default)")

                if not collection_path:
                    raise ValueError("Must supply at least one collection path.")

                # Build the query
                query = client.collection(collection_path)

                # Apply filters
                for filter_item in filters:
                    field = filter_item.get("field")
                    op = filter_item.get("op")
                    compare_value = filter_item.get("compare_value", {})

                    # Find the non-null value
                    value = None
                    for key, val in compare_value.items():
                        if val is not None:
                            value = val
                            break

                    if value is not None:
                        # Convert string timestamps to Firestore Timestamp objects
                        processed_value = value
                        
                        # Check if this is a date_value (explicit timestamp field)
                        is_date_value = 'date_value' in compare_value and compare_value['date_value'] is not None
                        
                        if isinstance(value, str) and (is_date_value or any(timestamp_indicator in field.lower() for timestamp_indicator in ['_at', 'time', 'date', 'created', 'updated', 'modified'])):
                            try:
                                from datetime import datetime
                                
                                # Try to parse ISO 8601 format
                                if 'T' in value and ('Z' in value or '+' in value or '-' in value[-6:]):
                                    dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
                                    processed_value = dt
                                    logger.info(f"Converted {'date_value' if is_date_value else 'timestamp string'} '{value}' to datetime object for field '{field}'")
                                else:
                                    # Try to parse as regular datetime
                                    dt = datetime.fromisoformat(value)
                                    processed_value = dt
                                    logger.info(f"Converted {'date_value' if is_date_value else 'datetime string'} '{value}' to datetime object for field '{field}'")
                            except (ValueError, TypeError) as e:
                                logger.warning(f"Failed to convert {'date_value' if is_date_value else 'timestamp string'} '{value}' for field '{field}': {e}. Using as string.")
                                processed_value = value
                        
                        # Map Firestore operators
                        if op == "EQUAL":
                            query = query.where(field, "==", processed_value)
                        elif op == "NOT_EQUAL":
                            query = query.where(field, "!=", processed_value)
                        elif op == "LESS_THAN":
                            query = query.where(field, "<", processed_value)
                        elif op == "LESS_THAN_OR_EQUAL":
                            query = query.where(field, "<=", processed_value)
                        elif op == "GREATER_THAN":
                            query = query.where(field, ">", processed_value)
                        elif op == "GREATER_THAN_OR_EQUAL":
                            query = query.where(field, ">=", processed_value)
                        elif op == "ARRAY_CONTAINS":
                            query = query.where(field, "array_contains", processed_value)
                        elif op == "ARRAY_CONTAINS_ANY":
                            query = query.where(field, "array_contains_any", processed_value)
                        elif op == "IN":
                            query = query.where(field, "in", processed_value)
                        elif op == "NOT_IN":
                            query = query.where(field, "not_in", processed_value)

                # Apply ordering
                if order:
                    order_by = order.get("orderBy")
                    direction = order.get("orderByDirection", "ASCENDING")
                    if direction == "DESCENDING":
                        query = query.order_by(order_by, direction=firestore.Query.DESCENDING)
                    else:
                        query = query.order_by(order_by)

                # Apply limit
                query = query.limit(limit)

                # Execute query
                docs = query.stream()
                
                # Convert to JSON
                documents = []
                for doc in docs:
                    doc_data = doc.to_dict()
                    doc_data['_id'] = doc.id
                    # Convert any DocumentReference objects to strings
                    doc_data = convert_firestore_to_serializable(doc_data)
                    documents.append(doc_data)

                return [
                    TextContent(
                        type="text",
                        text=json.dumps(documents, indent=2),
                    )
                ]

            elif name == "get_document":
                document_path = arguments.get("document_path")
                database = arguments.get("database", "(default)")

                if not document_path:
                    raise ValueError("Must supply document path.")

                # Remove leading slash if present
                if document_path.startswith('/'):
                    document_path = document_path[1:]

                # Get the document
                doc_ref = client.document(document_path)
                doc = doc_ref.get()

                if doc.exists:
                    doc_data = doc.to_dict()
                    doc_data['_id'] = doc.id
                    # Convert any DocumentReference objects to strings
                    doc_data = convert_firestore_to_serializable(doc_data)
                    return [
                        TextContent(
                            type="text",
                            text=json.dumps(doc_data, indent=2),
                        )
                    ]
                else:
                    return [
                        TextContent(
                            type="text",
                            text=json.dumps({"error": "Document not found"}, indent=2),
                        )
                    ]

            elif name == "list_collections":
                database = arguments.get("database", "(default)")
                
                # List collections
                collections = client.collections()
                collection_names = [col.id for col in collections]

                return [
                    TextContent(
                        type="text",
                        text=json.dumps(collection_names, indent=2),
                    )
                ]

            elif name == "create_document":
                collection_path = arguments.get("collection_path")
                document_data = arguments.get("document_data", {})
                document_id = arguments.get("document_id")

                if not collection_path:
                    raise ValueError("Must supply collection path.")
                
                if not document_data or len(document_data) == 0:
                    raise ValueError("document_data cannot be empty. You must provide actual field names and values to create a document.")

                # Process document data to handle complex field types
                processed_data = process_document_data(document_data, client)

                # Create the document
                if document_id:
                    doc_ref = client.collection(collection_path).document(document_id)
                    doc_ref.set(processed_data)
                    result = {"id": document_id, "path": doc_ref.path, "created": True}
                else:
                    doc_ref = client.collection(collection_path).add(processed_data)
                    result = {"id": doc_ref[1].id, "path": doc_ref[1].path, "created": True}

                return [
                    TextContent(
                        type="text",
                        text=json.dumps(result, indent=2),
                    )
                ]

            elif name == "update_document":
                document_path = arguments.get("document_path")
                document_data = arguments.get("document_data", {})

                if not document_path:
                    raise ValueError("Must supply document path.")
                
                if not document_data or len(document_data) == 0:
                    raise ValueError("document_data cannot be empty. You must provide actual field names and values to update a document.")

                # Remove leading slash if present
                if document_path.startswith('/'):
                    document_path = document_path[1:]

                # Process document data to handle complex field types
                processed_data = process_document_data(document_data, client)

                # Update the document
                doc_ref = client.document(document_path)
                doc_ref.update(processed_data)

                result = {"id": doc_ref.id, "path": doc_ref.path, "updated": True}

                return [
                    TextContent(
                        type="text",
                        text=json.dumps(result, indent=2),
                    )
                ]

            else:
                raise ValueError(f"Unknown tool: {name}")

        except Exception as e:
            logger.error(f"Error executing tool {name}: {str(e)}")
            return [
                TextContent(
                    type="text",
                    text=json.dumps({"error": str(e)}, indent=2),
                )
            ]

    return server


server = create_server


def get_initialization_options(server_instance: Server) -> InitializationOptions:
    """Get the initialization options for the server"""
    return InitializationOptions(
        server_name="firestore-server",
        server_version="1.0.0",
        capabilities=server_instance.get_capabilities(
            notification_options=NotificationOptions(),
            experimental_capabilities={},
        ),
    )


# Main handler allows users to auth
if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1].lower() == "auth":
        user_id = "local"
        # Run OAuth flow for Firestore
        authenticate_and_save_credentials(user_id, SERVICE_NAME, SCOPES)
    else:
        print("Usage:")
        print("  python main.py auth - Run OAuth flow for a user")
        print("Note: To run the server normally, use the guMCP server framework.")
