# HubSpot Server

pfMCP server implementation for interacting with HubSpot CRM.

### Prerequisites

- Python 3.11+
- A HubSpot Developer Account ([HubSpot Developer Portal](https://developers.hubspot.com/))
- A HubSpot App with OAuth 2.0 configured

### Required Scopes

The following OAuth scopes are required for the server to function:

- `crm.objects.contacts.read` - Read access to contacts
- `crm.objects.contacts.write` - Write access to contacts
- `crm.objects.companies.read` - Read access to companies
- `crm.objects.companies.write` - Write access to companies
- `crm.objects.deals.read` - Read access to deals
- `crm.objects.deals.write` - Write access to deals
- `tickets` - Access to tickets
- `crm.objects.line_items.read` - Read access to line items
- `crm.objects.line_items.write` - Write access to line items
- `crm.objects.quotes.read` - Read access to quotes
- `crm.objects.quotes.write` - Write access to quotes
- `crm.lists.read` - Read access to contact lists
- `e-commerce` - Access to e-commerce functionality

### Local Authentication

Local authentication uses a OAuth Configuration JSON file:

```json
local_auth/oauth_configs/hubspot/oauth.json
```

Create the following file with the relevant attributes for your app:

```json
{
  "client_id": "xxxxxxxxxxxxxxxxxxxxx",
  "client_secret": "xxxxxxxxxxxxxxxxxxxxx",
  "redirect_uri": "xxxxxxxxxxxxxxxxxxxxx"
}
```

To authenticate and save credentials:

```bash
python src/servers/hubspot/main.py auth
```

### Tools

#### Contacts

##### list_contacts
List HubSpot contacts with optional filtering.

Parameters:
- `query` (string) — Search query for contacts
- `limit` (integer) — Maximum number of contacts to return
- `properties` (array of strings) — Specific contact properties to return

##### create_contact
Create a new HubSpot contact.

Parameters:
- `email` (string, required) — Email address
- `firstname` (string) — First name
- `lastname` (string) — Last name
- `phone` (string) — Phone number
- `company` (string) — Company name
- `website` (string) — Website URL
- `jobtitle` (string) — Job title
- `address`, `city`, `state`, `zip`, `country` (string) — Address fields

##### update_contact
Update an existing HubSpot contact.

Parameters:
- `contact_id` (string, required) — HubSpot contact ID
- Same property fields as `create_contact`

##### search_contacts
Search HubSpot contacts with advanced filtering.

Parameters:
- `filter_property` (string, required) — Property name to filter on
- `filter_operator` (string, required) — Filter operator (e.g. `EQ`, `CONTAINS_TOKEN`)
- `filter_value` (string, required) — Value to filter by
- `limit` (integer) — Maximum results
- `properties` (array of strings) — Properties to return

##### merge_contacts
Merge two HubSpot contacts into one.

Parameters:
- `primary_contact_id` (string, required) — Contact ID that will remain
- `secondary_contact_id` (string, required) — Contact ID that will be merged in

##### gdpr_delete_contact
Permanently delete a contact and all associated content (GDPR).

Parameters:
- `contact_id` (string) — Contact ID to delete
- `email` (string) — Email of contact to delete (alternative to contact_id)

#### Companies

##### list_companies
List HubSpot companies with optional filtering.

Parameters:
- `query` (string) — Search query for companies
- `limit` (integer) — Maximum number of companies to return
- `properties` (array of strings) — Specific company properties to return

##### create_company
Create a new HubSpot company.

Parameters:
- `name` (string, required) — Company name
- `domain`, `description`, `industry`, `city`, `state`, `country`, `phone` (string) — Company fields

##### update_company
Update an existing HubSpot company.

Parameters:
- `company_id` (string, required) — HubSpot company ID
- Same property fields as `create_company`

#### Deals

##### list_deals
List HubSpot deals with optional filtering.

Parameters:
- `query` (string) — Search query for deals
- `limit` (integer) — Maximum number of deals to return
- `properties` (array of strings) — Specific deal properties to return

##### create_deal
Create a new HubSpot deal.

Parameters:
- `dealname` (string, required) — Deal name
- `amount` (string) — Deal amount
- `dealstage` (string) — Deal stage
- `pipeline` (string) — Pipeline ID
- `closedate` (string) — Close date
- `contact_ids`, `company_ids` (array of strings) — Associated records

##### update_deal
Update an existing HubSpot deal.

Parameters:
- `deal_id` (string, required) — HubSpot deal ID
- `dealname`, `amount`, `dealstage`, `pipeline`, `closedate` (string) — Deal fields

#### Tickets

##### list_tickets
List HubSpot tickets.

Parameters:
- `limit` (integer) — Maximum number of tickets to return (max 50)
- `after` (string) — Paging cursor
- `properties` (array of strings) — Properties to return
- `associations` (array of strings) — Associations to include
- `archived` (boolean) — Include archived tickets

##### get_ticket
Get a single HubSpot ticket by ID.

Parameters:
- `ticket_id` (string, required) — Ticket ID
- `properties` (array of strings) — Properties to return
- `associations` (array of strings) — Associations to include

##### create_ticket
Create a new HubSpot ticket.

Parameters:
- `subject` (string, required) — Ticket subject
- `content` (string) — Ticket description
- `hs_pipeline` (string) — Pipeline ID
- `hs_pipeline_stage` (string) — Pipeline stage ID
- `hs_ticket_priority` (string) — Priority
- `hs_ticket_category` (string) — Category

##### update_ticket
Update an existing HubSpot ticket.

Parameters:
- `ticket_id` (string, required) — Ticket ID
- Same property fields as `create_ticket`

##### delete_ticket
Delete a HubSpot ticket.

Parameters:
- `ticket_id` (string, required) — Ticket ID

##### merge_tickets
Merge two HubSpot tickets into one.

Parameters:
- `primary_ticket_id` (string, required) — Ticket ID that will remain
- `secondary_ticket_id` (string, required) — Ticket ID that will be merged in

#### Pipelines

##### list_pipelines
List HubSpot pipelines for a given object type.

Parameters:
- `object_type` (string, required) — Object type: `deals` or `tickets`

Returns all pipelines with their stages for the specified object type.

#### Owners

##### list_owners
List HubSpot owners (users who can be assigned to records).

Parameters:
- `limit` (integer) — Maximum number of owners to return (default 100)
- `archived` (boolean) — Include archived owners (default false)

Returns owner details including `firstName`, `lastName`, and `email`.

#### Products

##### list_products
List HubSpot products.

Parameters:
- `limit` (integer) — Maximum number of products to return
- `after` (string) — Paging cursor
- `properties` (array of strings) — Properties to return

##### get_product
Get a single HubSpot product by ID.

Parameters:
- `product_id` (string, required) — Product ID
- `properties` (array of strings) — Properties to return

##### create_product
Create a new HubSpot product.

Parameters:
- `name` (string, required) — Product name
- `description` (string) — Description
- `price` (string) — Price
- `hs_sku` (string) — SKU
- `hs_cost_of_goods_sold` (string) — Cost of goods sold
- `hs_recurring_billing_period` (string) — Recurring billing period

##### update_product
Update an existing HubSpot product.

Parameters:
- `product_id` (string, required) — Product ID
- Same property fields as `create_product`

##### delete_product
Delete a HubSpot product.

Parameters:
- `product_id` (string, required) — Product ID

#### Engagements

##### list_engagements
List HubSpot engagements.

Parameters:
- `limit` (integer) — Maximum number of engagements to return (max 250)
- `offset` (string) — Paging offset

##### get_engagement
Get a single HubSpot engagement by ID.

Parameters:
- `engagement_id` (string, required) — Engagement ID

##### get_recent_engagements
Get recently created or updated engagements.

Parameters:
- `count` (integer) — Maximum number of engagements to return (max 100)
- `offset` (string) — Paging offset
- `since` (integer) — Unix timestamp in milliseconds to filter by

##### create_engagement
Create a new HubSpot engagement (email, call, meeting, task, or note).

Parameters:
- `type` (string, required) — Engagement type: `EMAIL`, `CALL`, `MEETING`, `TASK`, `NOTE`
- `metadata` (object) — Engagement metadata (varies by type)
- `metadata_body` (string) — Engagement metadata body
- `owner_id` (string) — Owner ID
- `timestamp` (integer) — Time of engagement in milliseconds
- `contact_ids`, `company_ids`, `deal_ids`, `ticket_ids` (array of strings) — Associated records

##### update_engagement
Update an existing HubSpot engagement.

Parameters:
- `engagement_id` (string, required) — Engagement ID
- `owner_id` (string) — Owner ID
- `timestamp` (integer) — Time of engagement
- `metadata` (object) — Engagement metadata
- `metadata_body` (string) — Metadata body text

##### delete_engagement
Delete a HubSpot engagement.

Parameters:
- `engagement_id` (string, required) — Engagement ID

##### get_engagements (for contact)
Get engagements associated with a specific contact.

Parameters:
- `contact_id` (string, required) — Contact ID

##### get_call_dispositions
Get all possible dispositions for sales calls.

No parameters required.

#### Email

##### send_email
Send an email through HubSpot.

Parameters:
- `to` (string, required) — Recipient email
- `subject` (string, required) — Email subject
- `body` (string, required) — Email body (HTML supported)
- `from_email` (string) — Sender email
- `from_name` (string) — Sender name
- `cc` (array of strings) — CC recipients
- `bcc` (array of strings) — BCC recipients
