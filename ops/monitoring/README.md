# MCP lifecycle monitoring

The server exports Prometheus lifecycle metrics at `/metrics` and emits the
same lifecycle transitions as structured Cloud Run logs. The installer creates
log-based counters and one alert policy for client open/close imbalance, cleanup
failures, active session growth, old/reconnected receive streams, GET-to-POST
ratio, and the pfMCP Cloud Run instance baseline.

Apply to stage first:

```bash
./ops/monitoring/install-lifecycle-alerts.sh \
  "$STAGE_GCP_PROJECT_ID" \
  "projects/$STAGE_GCP_PROJECT_ID/notificationChannels/CHANNEL_ID"
```

The policy intentionally alerts above three pfMCP instances for ten minutes.
Adjust that threshold only after recording the stage canary baseline. Apply the
same reviewed policy to production as a separate rollout step; this repository
does not install alerts during application deployment.
