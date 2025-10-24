# Firestore MCP Server

This MCP server provides integration with Google Cloud Firestore, allowing you to query collections, retrieve documents, and manage Firestore databases through the Model Context Protocol.

## Features

- **Query Collections**: Query Firestore collections with complex filters, ordering, and limits
- **Get Documents**: Retrieve individual documents by their path
- **List Collections**: Discover available collections in your Firestore database
- **Emulator Support**: Work with Firestore emulator for development and testing

## Authentication

This server requires Google Cloud credentials to access Firestore. You can authenticate using:

1. **Service Account Key**: Download a JSON key file from Google Cloud Console
2. **Application Default Credentials**: Use `gcloud auth application-default login`
3. **Environment Variables**: Set `GOOGLE_APPLICATION_CREDENTIALS` to point to your service account key

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

When specifying `compare_value`, use the appropriate type property:

- `string_value`: For string comparisons
- `boolean_value`: For boolean comparisons
- `integer_value`: For integer comparisons
- `double_value`: For floating-point comparisons
- `string_array_value`: For array of strings

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

# The server will be available through the guMCP framework
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
