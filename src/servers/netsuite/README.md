# NetSuite MCP Server

The NetSuite MCP Server provides seamless integration with NetSuite's REST API, allowing you to manage records, search for vendors, and execute SuiteQL queries through the Model Context Protocol.

## Features

- **Record Management**: Create and update records of any type in NetSuite
- **Vendor Search**: Search for vendors by email address or name
- **SuiteQL Execution**: Run custom SuiteQL queries for advanced data retrieval
- **Authentication**: Secure OAuth 1.0a authentication with NetSuite
- **Error Handling**: Comprehensive error handling with retry logic

## Prerequisites

- NetSuite account with REST API access enabled
- OAuth 1.0a consumer credentials (Consumer Key, Consumer Secret)
- OAuth 1.0a token credentials (Token ID, Token Secret)
- Account ID for your NetSuite instance

## Authentication Setup

### 1. NetSuite Integration Setup

1. Log into your NetSuite account
2. Navigate to **Setup > Integration > Manage Integrations**
3. Create a new integration or use an existing one
4. Enable **Token-Based Authentication**
5. Note down your **Consumer Key** and **Consumer Secret**

### 2. Token Generation

1. Navigate to **Setup > Users/Roles > Access Tokens**
2. Create a new access token
3. Select the integration created in step 1
4. Note down your **Token ID** and **Token Secret**

### 3. Environment Variables

Set the following environment variables:

```bash
export NETSUITE_ACCOUNT_ID="your_account_id"
export NETSUITE_CONSUMER_KEY="your_consumer_key"
export NETSUITE_CONSUMER_SECRET="your_consumer_secret"
export NETSUITE_TOKEN_ID="your_token_id"
export NETSUITE_TOKEN_SECRET="your_token_secret"
```

## Available Tools

### 1. Create Record

Creates a new record in NetSuite with the specified record type and data.

**Parameters:**
- `record_type` (string): The NetSuite record type (e.g., 'customer', 'vendor', 'item', 'salesorder')
- `data` (object): The record data as key-value pairs

**Example:**
```json
{
  "record_type": "customer",
  "data": {
    "entityid": "ACME Corp",
    "companyname": "ACME Corporation",
    "email": "contact@acme.com",
    "phone": "+1-555-0123"
  }
}
```

**Supported Record Types:**
- `customer` - Customer records
- `vendor` - Vendor records
- `item` - Item records
- `salesorder` - Sales order records
- `invoice` - Invoice records
- `purchaseorder` - Purchase order records
- And many more...

### 2. Update Record

Updates an existing record in NetSuite with the specified record type, ID, and data.

**Parameters:**
- `record_type` (string): The NetSuite record type
- `record_id` (string): The unique identifier of the record to update
- `data` (object): The updated record data as key-value pairs

**Example:**
```json
{
  "record_type": "customer",
  "record_id": "12345",
  "data": {
    "email": "newemail@acme.com",
    "phone": "+1-555-9999"
  }
}
```

### 3. Search Vendor by Email

Searches for a vendor in NetSuite by email address.

**Parameters:**
- `email` (string): The email address to search for

**Example:**
```json
{
  "email": "vendor@example.com"
}
```

### 4. Search Vendor by Name

Searches for a vendor in NetSuite by vendor name (supports partial matches).

**Parameters:**
- `vendor_name` (string): The vendor name to search for

**Example:**
```json
{
  "vendor_name": "ABC Supplies"
}
```

### 5. Execute SuiteQL Query

Executes a SuiteQL query string against the NetSuite database.

**Parameters:**
- `query` (string): The SuiteQL query string to execute

**Example:**
```json
{
  "query": "SELECT id, entityid, email FROM vendor WHERE isinactive = F ORDER BY entityid"
}
```

**SuiteQL Examples:**

**Basic Vendor Query:**
```sql
SELECT id, entityid, email, phone FROM vendor WHERE isinactive = F
```

**Customer with Orders:**
```sql
SELECT 
  c.id, 
  c.entityid, 
  c.companyname,
  COUNT(so.id) as order_count
FROM customer c
LEFT JOIN salesorder so ON c.id = so.entity
WHERE c.isinactive = F
GROUP BY c.id, c.entityid, c.companyname
```

**Item Inventory:**
```sql
SELECT 
  i.id, 
  i.itemid, 
  i.displayname,
  i.quantityavailable,
  i.quantityonhand
FROM item i
WHERE i.type = 'InvtPart' AND i.isinactive = F
```

## Usage Examples

### Creating a New Customer

```python
# Using the create_record tool
{
  "record_type": "customer",
  "data": {
    "entityid": "New Customer Inc",
    "companyname": "New Customer Incorporated",
    "email": "info@newcustomer.com",
    "phone": "+1-555-0000",
    "custentity_industry": "Technology"
  }
}
```

### Updating Vendor Information

```python
# Using the update_record tool
{
  "record_type": "vendor",
  "record_id": "67890",
  "data": {
    "email": "updated@vendor.com",
    "phone": "+1-555-1111",
    "custentity_vendor_category": "Preferred"
  }
}
```

### Finding Vendors by Email Domain

```python
# Using the execute_suiteql tool
{
  "query": "SELECT id, entityid, email FROM vendor WHERE email LIKE '%@gmail.com' AND isinactive = F"
}
```

## Error Handling

The server includes comprehensive error handling:

- **Authentication Errors**: Invalid credentials or expired tokens
- **API Errors**: NetSuite API errors with detailed messages
- **Validation Errors**: Missing or invalid parameters
- **Network Errors**: Connection issues with automatic retry logic

## Rate Limiting

NetSuite has rate limits on API calls. The server includes retry logic with exponential backoff for:
- HTTP 429 (Too Many Requests)
- HTTP 500 (Internal Server Error)
- HTTP 502, 503, 504 (Gateway/Service Unavailable)

## Security Considerations

- All credentials are stored securely and never logged
- OAuth 1.0a provides secure authentication
- HTTPS is enforced for all API communications
- User-specific credential isolation

## Troubleshooting

### Common Issues

1. **Authentication Failed**
   - Verify your consumer key and secret
   - Check that your access token is valid
   - Ensure your account ID is correct

2. **Record Type Not Found**
   - Verify the record type name (case-sensitive)
   - Check that your integration has access to the record type
   - Ensure the record type is active in your NetSuite instance

3. **SuiteQL Query Errors**
   - Validate your SuiteQL syntax
   - Check field names and table names
   - Ensure your integration has access to the queried data

### Debug Mode

Enable debug logging by setting the log level to DEBUG in your environment:

```bash
export LOG_LEVEL=DEBUG
```

## Support

For issues or questions:
- Check the NetSuite REST API documentation
- Verify your integration permissions
- Review the server logs for detailed error messages

## Contributing

Contributions are welcome! Please ensure:
- All new features include proper error handling
- New tools follow the existing pattern
- Tests are added for new functionality
- Documentation is updated accordingly
