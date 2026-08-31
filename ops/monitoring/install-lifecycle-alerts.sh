#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 2 ]]; then
  echo "usage: $0 GCP_PROJECT_ID NOTIFICATION_CHANNEL_RESOURCE" >&2
  exit 2
fi

target_project="$1"
notification_channel="$2"
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
rendered_policy="$(mktemp)"
trap 'rm -f "$rendered_policy"' EXIT

create_counter() {
  local metric_name="$1"
  local metric_filter="$2"
  if ! gcloud logging metrics describe "$metric_name" --project "$target_project" >/dev/null 2>&1; then
    gcloud logging metrics create "$metric_name" \
      --project "$target_project" \
      --description "MCP lifecycle incident guardrail" \
      --log-filter "$metric_filter"
  fi
}

create_counter mcp_clients_opened 'resource.type="cloud_run_revision" resource.labels.service_name="workflow-api" jsonPayload.component="mcp_lifecycle" jsonPayload.event="client_opened"'
create_counter mcp_clients_closed 'resource.type="cloud_run_revision" resource.labels.service_name="workflow-api" jsonPayload.component="mcp_lifecycle" jsonPayload.event="client_closed"'
create_counter mcp_cleanup_failures 'resource.type="cloud_run_revision" resource.labels.service_name="workflow-api" jsonPayload.component="mcp_lifecycle" jsonPayload.event="cleanup_failed"'
create_counter pfmcp_sessions_opened 'resource.type="cloud_run_revision" resource.labels.service_name="pf-mcp" jsonPayload.component="pfmcp_lifecycle" jsonPayload.event="session_opened"'
create_counter pfmcp_sessions_closed 'resource.type="cloud_run_revision" resource.labels.service_name="pf-mcp" jsonPayload.component="pfmcp_lifecycle" jsonPayload.event="session_closed"'
create_counter pfmcp_stream_reconnects 'resource.type="cloud_run_revision" resource.labels.service_name="pf-mcp" jsonPayload.component="pfmcp_lifecycle" jsonPayload.event="receive_stream_opened" jsonPayload.reconnect=true'
create_counter pfmcp_old_streams 'resource.type="cloud_run_revision" resource.labels.service_name="pf-mcp" jsonPayload.component="pfmcp_lifecycle" jsonPayload.event="receive_stream_closed" jsonPayload.stream_age_seconds>=240'
create_counter pfmcp_http_get 'resource.type="cloud_run_revision" resource.labels.service_name="pf-mcp" httpRequest.requestMethod="GET"'
create_counter pfmcp_http_post 'resource.type="cloud_run_revision" resource.labels.service_name="pf-mcp" httpRequest.requestMethod="POST"'

sed \
  -e "s|__PROJECT_ID__|${target_project}|g" \
  -e "s|__NOTIFICATION_CHANNEL__|${notification_channel}|g" \
  "$script_dir/lifecycle-alert-policy.yaml" > "$rendered_policy"

gcloud alpha monitoring policies create \
  --project "$target_project" \
  --policy-from-file "$rendered_policy"
