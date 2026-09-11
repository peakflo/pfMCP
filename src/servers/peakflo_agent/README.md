# Peakflo Autonomous Agent MCP server

This server is a thin adapter over Peakflo's autonomous-agent runtime. Pass the short-lived signed agent-session token as the server API key. Tool discovery and every execution are authorized again by Peakflo against the live agent, role, tenant, document version, and approval assignment.

Tool arguments never contain tenant, role, permissions, document ID, or session ID.
