# Google BigQuery

The BigQuery server uses a Nango OAuth connection with integration ID
`google-bigquery`. Configure that Nango integration with the Google OAuth
template and the `https://www.googleapis.com/auth/bigquery` scope. The user
also needs BigQuery IAM permissions on the project and datasets: dataset/table
metadata permissions for discovery, and `bigquery.jobs.create` plus table data
access for queries. The Google Cloud project ID is supplied to each tool.

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

The Nango integration ID and OAuth scope must be provisioned separately in
each environment before users can connect BigQuery in workflow-builder.
