# Firestore MCP Server

This MCP server provides comprehensive integration with Google Cloud Firestore, allowing you to query collections, retrieve documents, create new records, update existing data, and manage Firestore databases through the Model Context Protocol.

## Features

- **Query Collections**: Query Firestore collections with complex filters, ordering, and limits
- **Get Documents**: Retrieve individual documents by their path
- **Create Documents**: Add new documents to collections with support for complex field types
- **Update Documents**: Modify existing documents with partial updates
- **List Collections**: Discover available collections in your Firestore database
- **Complex Field Types**: Support for timestamps and document references
- **Emulator Support**: Work with Firestore emulator for development and testing

## Authentication

This server supports multiple authentication methods for Google Cloud Firestore:

1. **Nango OAuth2**: Seamless authentication through Nango services
2. **Service Account Key**: Download a JSON key file from Google Cloud Console
3. **Application Default Credentials**: Use `gcloud auth application-default login`
4. **Environment Variables**: Set `GOOGLE_APPLICATION_CREDENTIALS` to point to your service account key

The server automatically extracts project ID from authentication metadata when using Nango OAuth2.

## Tools

### query_collection

Query a Firestore collection with filters, ordering, and limits.

**Parameters:**
- `collection_path` (required): Path to the collection (e.g., "users", "projects/123/tasks")
- `filters` (optional): Array of filter objects with:
  - `field`: Field name to filter on
  - `op`: Operator (EQUAL, NOT_EQUAL, LESS_THAN, etc.)
  - `compare_value`: Value to compare against (with type-specific properties)
- `order` (optional): Ordering specification with `orderBy` field and `orderByDirection`
- `limit` (optional): Maximum number of documents to return (default: 10)
- `database` (optional): Database ID (defaults to "(default)")
- `use_emulator` (optional): Use Firestore emulator (default: false)

**Example:**
```json
{
  "collection_path": "users",
  "filters": [
    {
      "field": "age",
      "op": "GREATER_THAN",
      "compare_value": {"integer_value": 18}
    }
  ],
  "order": {
    "orderBy": "name",
    "orderByDirection": "ASCENDING"
  },
  "limit": 50
}
```

### get_document

Retrieve a single document by its path.

**Parameters:**
- `document_path` (required): Full path to the document (e.g., "users/user123")
- `database` (optional): Database ID (defaults to "(default)")
- `use_emulator` (optional): Use Firestore emulator (default: false)

**Example:**
```json
{
  "document_path": "users/user123"
}
```

### create_document

Create a new document in a Firestore collection with support for complex field types.

**Parameters:**
- `collection_path` (required): Path to the collection (e.g., "users", "orders")
- `document_data` (required): Document data with field names and values (cannot be empty)
- `document_id` (optional): Custom document ID (auto-generated if not provided)
- `database` (optional): Database ID (defaults to "(default)")
- `use_emulator` (optional): Use Firestore emulator (default: false)

**Example:**
```json
{
  "collection_path": "users",
  "document_data": {
    "name": "John Doe",
    "email": "john@example.com",
    "age": 30,
    "created_at": {
      "_type": "timestamp",
      "_value": "2023-10-23T19:30:16Z"
    },
    "profile": {
      "bio": "Software developer",
      "location": "San Francisco"
    }
  }
}
```

### update_document

Update an existing document in Firestore with partial updates.

**Parameters:**
- `document_path` (required): Full path to the document (e.g., "users/user123")
- `document_data` (required): Document data to update (cannot be empty)
- `database` (optional): Database ID (defaults to "(default)")
- `use_emulator` (optional): Use Firestore emulator (default: false)

**Example:**
```json
{
  "document_path": "users/user123",
  "document_data": {
    "email": "newemail@example.com",
    "age": 31,
    "updated_at": {
      "_type": "timestamp",
      "_value": "2023-10-23T19:30:16Z"
    },
    "profile": {
      "bio": "Updated bio",
      "location": "New York"
    }
  }
}
```

### list_collections

List all collections in the database.

**Parameters:**
- `database` (optional): Database ID (defaults to "(default)")
- `use_emulator` (optional): Use Firestore emulator (default: false)

## Filter Operators

The following operators are supported for filtering:

- `EQUAL`: Field equals value
- `NOT_EQUAL`: Field does not equal value
- `LESS_THAN`: Field is less than value
- `LESS_THAN_OR_EQUAL`: Field is less than or equal to value
- `GREATER_THAN`: Field is greater than value
- `GREATER_THAN_OR_EQUAL`: Field is greater than or equal to value
- `ARRAY_CONTAINS`: Array field contains value
- `ARRAY_CONTAINS_ANY`: Array field contains any of the values
- `IN`: Field value is in the provided array
- `NOT_IN`: Field value is not in the provided array

## Value Types

### Query Filter Values

When specifying `compare_value` in filters, use the appropriate type property:

- `string_value`: For string comparisons
- `boolean_value`: For boolean comparisons
- `integer_value`: For integer comparisons
- `double_value`: For floating-point comparisons
- `string_array_value`: For array of strings
- `date_value`: For timestamp comparisons (ISO 8601 format)

### Complex Field Types in Documents

When creating or updating documents, use special syntax for complex field types:

#### Timestamps
```json
{
  "created_at": {
    "_type": "timestamp",
    "_value": "2023-10-23T19:30:16Z"
  }
}
```

#### Document References
```json
{
  "user_id": {
    "_type": "reference",
    "_value": "users/123"
  }
}
```

#### Nested Objects
```json
{
  "profile": {
    "name": "John Doe",
    "settings": {
      "theme": "dark",
      "notifications": true
    }
  }
}
```

## Emulator Support

To use the Firestore emulator, set `use_emulator: true` in your tool calls. Make sure the Firestore emulator is running on `localhost:8080`.

## Error Handling

The server includes comprehensive error handling and will return detailed error messages for:

- Authentication failures
- Invalid collection/document paths
- Query syntax errors
- Network connectivity issues
- Permission errors

## Development

To run the server locally for development:

```bash
# Install dependencies
pip install google-cloud-firestore

# Run authentication
python main.py auth

# The server will be available through the pfMCP framework
```

## Security Notes

- Always use least-privilege service accounts
- Never commit service account keys to version control
- Use environment variables for sensitive configuration
- Consider using Workload Identity for production deployments

## Examples

### Query users by age and status
```json
{
  "collection_path": "users",
  "filters": [
    {
      "field": "age",
      "op": "GREATER_THAN_OR_EQUAL",
      "compare_value": {"integer_value": 21}
    },
    {
      "field": "status",
      "op": "EQUAL",
      "compare_value": {"string_value": "active"}
    }
  ],
  "order": {
    "orderBy": "created_at",
    "orderByDirection": "DESCENDING"
  },
  "limit": 100
}
```

### Query with timestamp filtering
```json
{
  "collection_path": "orders",
  "filters": [
    {
      "field": "created_at",
      "op": "GREATER_THAN",
      "compare_value": {"date_value": "2023-10-23T00:00:00Z"}
    }
  ],
  "order": {
    "orderBy": "created_at",
    "orderByDirection": "DESCENDING"
  }
}
```

### Create a new user with complex fields
```json
{
  "collection_path": "users",
  "document_data": {
    "name": "Jane Smith",
    "email": "jane@example.com",
    "age": 28,
    "created_at": {
      "_type": "timestamp",
      "_value": "2023-10-23T19:30:16Z"
    },
    "profile": {
      "bio": "Software engineer",
      "location": "Seattle",
      "skills": ["Python", "JavaScript", "Go"]
    },
    "settings": {
      "theme": "dark",
      "notifications": true
    }
  }
}
```

### Update user information
```json
{
  "document_path": "users/user123",
  "document_data": {
    "email": "newemail@example.com",
    "age": 29,
    "updated_at": {
      "_type": "timestamp",
      "_value": "2023-10-23T20:15:30Z"
    },
    "profile": {
      "bio": "Senior software engineer",
      "location": "San Francisco"
    }
  }
}
```

### Get a specific document
```json
{
  "document_path": "projects/project123/tasks/task456"
}
```

### List all collections
```json
{}
```

## Best Practices

### Document Data Requirements
- **Never send empty document_data**: Always include actual field names and values
- **Use meaningful field names**: Choose descriptive names like `created_at`, `user_id`, `status`
- **Include timestamps**: Add `created_at` and `updated_at` fields for tracking
- **Validate data**: Ensure required fields are present before creating/updating

### Complex Field Types
- **Use timestamp syntax**: `{_type: "timestamp", _value: "ISO_string"}` for dates
- **Use reference syntax**: `{_type: "reference", _value: "path/to/doc"}` for references
- **Nest objects naturally**: Use regular JSON objects for nested data structures

### Query Optimization
- **Use appropriate limits**: Set reasonable limits (10-100) for performance
- **Index your fields**: Ensure queried fields have Firestore indexes
- **Filter early**: Apply filters before ordering for better performance
