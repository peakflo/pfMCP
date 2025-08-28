# TLDV MCP Server

This MCP server provides integration with the TLDV (Too Long; Didn't View) meeting platform API. TLDV is a platform that helps users get insights from their meetings through AI-powered transcription, highlights, and analysis.

## Features

- **Meeting Management**: Retrieve meeting details and list meetings with filtering
- **Transcript Access**: Get full meeting transcripts with speaker identification
- **Highlights**: Access AI-generated meeting highlights and key points
- **Health Monitoring**: Check API health status

## Authentication

The TLDV server uses API key authentication. You'll need to obtain an API key from your TLDV account.

### Setting up Authentication

1. Get your TLDV API key from your account settings
2. Run the authentication command:
   ```bash
   python main.py auth <user_id>
   ```
3. Enter your API key when prompted

## Available Tools

### get_meeting
Retrieve a specific meeting by its ID.

**Parameters:**
- `meeting_id` (string, required): The unique identifier of the meeting

**Example:**
```json
{
  "meeting_id": "meeting-123"
}
```

### get_meetings
Retrieve a list of meetings with optional filtering and pagination.

**Parameters:**
- `query` (string, optional): Search query to filter meetings
- `page` (integer, optional): Page number for pagination (minimum: 1)
- `limit` (integer, optional): Number of results per page (1-100, default: 50)
- `from` (string, optional): Start date for filtering (ISO 8601 format)
- `to` (string, optional): End date for filtering (ISO 8601 format)
- `onlyParticipated` (boolean, optional): Only return meetings where the user participated
- `meetingType` (string, optional): Filter by meeting type ("internal" or "external")

**Example:**
```json
{
  "query": "team sync",
  "page": 1,
  "limit": 10,
  "from": "2024-01-01T00:00:00Z",
  "to": "2024-12-31T23:59:59Z",
  "onlyParticipated": true,
  "meetingType": "internal"
}
```

### get_transcript
Retrieve the full transcript for a specific meeting.

**Parameters:**
- `meeting_id` (string, required): The unique identifier of the meeting

**Example:**
```json
{
  "meeting_id": "meeting-123"
}
```

### get_highlights
Retrieve AI-generated highlights for a specific meeting.

**Parameters:**
- `meeting_id` (string, required): The unique identifier of the meeting

**Example:**
```json
{
  "meeting_id": "meeting-123"
}
```

### health_check
Check the health status of the TLDV API.

**Parameters:** None

## Data Models

### Meeting
```json
{
  "id": "string",
  "name": "string",
  "happenedAt": "string (ISO 8601)",
  "url": "string (URL)",
  "organizer": {
    "name": "string",
    "email": "string"
  },
  "invitees": [
    {
      "name": "string",
      "email": "string"
    }
  ],
  "template": {
    "id": "string",
    "label": "string"
  }
}
```

### Transcript Response
```json
{
  "id": "string",
  "meetingId": "string",
  "data": [
    {
      "speaker": "string",
      "text": "string",
      "startTime": "number (seconds)",
      "endTime": "number (seconds)"
    }
  ]
}
```

### Highlights Response
```json
{
  "meetingId": "string",
  "data": [
    {
      "text": "string",
      "startTime": "number (seconds)",
      "source": "manual" | "auto",
      "topic": {
        "title": "string",
        "summary": "string"
      }
    }
  ]
}
```

### Meetings Response
```json
{
  "page": "number",
  "pages": "number",
  "total": "number",
  "pageSize": "number",
  "results": [
    {
      // Meeting object
    }
  ]
}
```

## Error Handling

The server includes comprehensive error handling with:
- Retry logic for network failures
- Proper error messages for missing credentials
- Validation of required parameters
- Graceful handling of API errors

## Rate Limiting

The server implements exponential backoff retry logic to handle rate limiting and temporary failures:
- Maximum 3 retries
- Initial delay of 1 second
- Maximum delay of 2 seconds
- Exponential backoff between retries

## Development

To run the server locally:

1. Install dependencies
2. Set up authentication
3. Run the server:
   ```bash
   python main.py
   ```

## API Reference

For more information about the TLDV API, visit the [TLDV API documentation](https://docs.tldv.io/).

