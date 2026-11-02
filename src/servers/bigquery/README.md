# Google BigQuery

The BigQuery server uses a Nango OAuth connection with provider config key
`google`. The workflow-builder connector ID remains `google-bigquery` and
routes to this server at `/bigquery`. Configure the Nango `google` integration
with Google OAuth. The workflow-builder connect session requests
`https://www.googleapis.com/auth/bigquery` via a scope override. The user
also needs BigQuery IAM permissions on the project and datasets: dataset/table
metadata permissions for discovery, and `bigquery.jobs.create` plus table data
access for queries. The Google Cloud project ID is supplied to each tool.

Each connection must have `allowedProjects`, a nonempty array of exact Google
Cloud project IDs, in its Nango connection metadata. workflow-builder collects
the IDs when the connection is created or edited and writes them to Nango.
Without this metadata, every BigQuery tool fails with an MCP error. All tool
`project_id` arguments are checked against the array. `run_query` first submits
a dry-run job and checks the returned referenced tables, routines, and any
destination against the same array before executing the query. A failed or
incomplete dry run is rejected. `INFORMATION_SCHEMA`, wildcard table queries,
and scripts are rejected because their dry-run references may be incomplete.
`get_query_results` verifies the returned job belongs to an allowed project.

| Tool | Purpose |
| --- | --- |
| `list_datasets` | List accessible datasets in a project |
| `list_tables` | List tables in a dataset |
| `get_table` | Retrieve table metadata and schema |
| `run_query` | Execute GoogleSQL; returns schema, rows, job status and pagination token |
| `get_query_results` | Poll an incomplete job or fetch another page of results |

`run_query` can execute statements that modify data, subject to the connected
identity's IAM permissions. It defaults to `maximum_bytes_billed=1000000000`
(1 GB), which callers can override. Result pages default to 100 rows and are
limited to 1000 rows. For a job that is still running, use the returned
`jobReference.jobId` and `jobReference.location` with `get_query_results`.
Pass `pageToken` back as `page_token` to fetch later pages. Nested and repeated
values retain BigQuery's REST JSON representation.

The Nango `google` integration and OAuth client must be provisioned in each
environment before users can connect BigQuery in workflow-builder.
The OAuth scope and ability to execute non-SELECT statements are unchanged;
the connected identity's IAM remains an additional permission boundary.
