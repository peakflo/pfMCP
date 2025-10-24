# Peakflo Model Context Protocol (pfMCP)

pfMCP is an open-source collection of Model Context Protocol (MCP) servers that can be run both remotely and locally. The project aims to create the largest collection of MCP servers with a unified backend, fostering a community around AI integrations and the future of AGI.
 
## Overview

While many MCP server providers are closed source, and open-source alternatives typically only support local hosting through stdio, pfMCP provides:

- A comprehensive collection of MCP servers that work both locally and remotely
- Support for both stdio and Streamable stateless HTTP transports
- A unified backend architecture for consistent implementation
- Full open-source access to encourage community contributions

## Getting Started

### Prerequisites

- Python 3.11
- Git
- For Windows users: A bash-compatible shell is recommended (Git Bash, WSL, etc.)

### Installation

1. **Clone the repository**:

   ```bash
   git clone https://github.com/peakflo/pfMCP.git
   cd pfMCP
   ```

2. **Set up a virtual environment**:

   This isolates the project dependencies from your system Python installation.

   ```bash
   # Create the virtual environment
   python -m venv venv

   # Activate it (choose the appropriate command for your OS)
   # On Unix/macOS:
   source venv/bin/activate

   # On Windows (Command Prompt):
   venv\Scripts\activate

   # On Windows (PowerShell):
   .\venv\Scripts\Activate.ps1

   # On Windows (Git Bash):
   source venv/Scripts/activate
   ```

   You'll know your virtual environment is active when you see `(venv)` at the beginning of your command prompt.

3. **Install dependencies**:

   ```bash
   # Install core dependencies
   pip install -r requirements.txt

   # Install development dependencies (for contributing)
   pip install -r requirements-dev.txt
   ```

4. **Configure environment variables**:

   ```bash
   # Create a local environment file from the template
   cp .env.example .env

   # Open the .env file in your preferred text editor and update values as needed
   # If you're using VS Code:
   code .env
   ```

   The `.env` file contains configuration for:

   - API keys for service integrations
   - Authentication settings
   - Server configuration options
   - Development environment settings

Note: For local usage, by default, the `local_auth` folder should be located in the root of the repository

## Usage

### Running SSE Servers

An SSE server can be run locally. This will provide a single URL and host every server available.

To start the SSE development server, run:

```bash
./start_sse_dev_server.sh
```

For convenience, we also provide a lightweight MCP Client to connect to SSE servers. Usage:

```bash
python tests/clients/RemoteMCPTestClient.py --endpoint=http://localhost:8000/simple-tools-server/local
```

### Running Stdio Servers

```bash
python src/servers/local.py --server=simple-tools-server
```

For convenience, we also provide a lightweight MCP Client to start and connect to stdio servers. Usage:

```bash
 python tests/clients/LocalMCPTestClient.py --server=simple-tools-server
```

## Supported Servers and Authentication Methods

The following table provides an overview of the current servers implemented in pfMCP and their Remote Auth options:

| Server | Remote Auth | Documentation |
| ------ | ----------- | ------------- |
| **Google Services** |  |  |
| Google Sheets | ✅ Seamless with Nango auth, ✅ Seamless with Gumloop auth | [GSheets Docs](/src/servers/gsheets/README.md) |
| Gmail | ✅ Seamless with Nango auth, ✅ Seamless with Gumloop auth | [Gmail Docs](/src/servers/gmail/README.md) |
| Google Docs | ✅ Seamless with Nango auth, ✅ Seamless with Gumloop auth | [GDocs Docs](/src/servers/gdocs/README.md) |
| Google Drive | ✅ Seamless with Nango auth, ✅ Seamless with Gumloop auth | [GDrive Docs](/src/servers/gdrive/README.md) |
| Google Calendar | ✅ Seamless with Nango auth, ✅ Seamless with Gumloop auth | [GCalendar Docs](/src/servers/gcalendar/README.md) |
| Google Maps | ⚠️ Coming soon | [GMaps Docs](/src/servers/gmaps/README.md) |
| Google Meet | ✅ Seamless with Nango auth, ✅ Seamless with Gumloop auth | [GMeet Docs](/src/servers/gmeet/README.md) |
| Google Firestore | ✅ Seamless with Nango auth | [Firestore Docs](/src/servers/firestore/README.md) |
| YouTube | ✅ Seamless with Nango auth, ✅ Seamless with Gumloop auth | [YouTube Docs](/src/servers/youtube/README.md) |
| **Communication Tools** |  |  |
| Slack | ✅ Seamless with Nango auth, ✅ Seamless with Gumloop auth | [Slack Docs](/src/servers/slack/README.md) |
| Microsoft Teams | ⚠️ Coming soon | [Teams Docs](/src/servers/teams/README.md) |
| Outlook | ✅ Seamless with Nango auth, ✅ Seamless with Gumloop auth | [Outlook Docs](/src/servers/outlook/README.md) |
| Discourse | ✅ Seamless with Gumloop auth | [Discourse Docs](/src/servers/discourse/README.md) |
| X (Twitter) | ⚠️ Coming soon | [X Docs](/src/servers/x/README.md) |
| Bluesky | ⚠️ Coming soon | [Bluesky Docs](/src/servers/bluesky/README.md) |
| Reddit | ✅ Seamless with Nango auth, ✅ Seamless with Gumloop auth | [Reddit Docs](/src/servers/reddit/README.md) |
| Intercom | ⚠️ Coming soon | [Intercom Docs](/src/servers/intercom/README.md) |
| Zoom | ⚠️ Coming soon | [Zoom Docs](/src/servers/zoom/README.md) |
| TLDV | ✅ Seamless with Nango auth | [TLDV Docs](/src/servers/tldv/README.md) |
| Twilio | ⚠️ Coming soon | [Twilio Docs](/src/servers/twilio/README.md) |
| **Productivity Tools** |  |  |
| Airtable | ✅ Seamless with Nango auth, ✅ Seamless with Gumloop auth | [Airtable Docs](/src/servers/airtable/README.md) |
| Excel | ✅ Seamless with Nango auth, ✅ Seamless with Gumloop auth | [Excel Docs](/src/servers/excel/README.md) |
| Word | ✅ Seamless with Nango auth, ✅ Seamless with Gumloop auth | [Word Docs](/src/servers/word/README.md) |
| Linear | ✅ Seamless with Nango auth, ✅ Seamless with Gumloop auth | [Linear Docs](/src/servers/linear/README.md) |
| Monday.com | ✅ Seamless with Nango auth, ✅ Seamless with Gumloop auth | [Monday.com Docs](/src/servers/monday/README.md) |
| Attio | ✅ Seamless with Nango auth, ✅ Seamless with Gumloop auth | [Attio Docs](/src/servers/attio/README.md) |
| Notion | ✅ Seamless with Nango auth, ✅ Seamless with Gumloop auth | [Notion Docs](/src/servers/notion/README.md) |
| Loops | ⚠️ Coming soon | [Loops Docs](/src/servers/loops/README.md) |
| Webflow | ⚠️ Coming soon | [Webflow Docs](/src/servers/webflow/README.md) |
| ClickUp | ✅ Seamless with Nango auth, ✅ Seamless with Gumloop auth | [ClickUp Docs](/src/servers/clickup/README.md) |
| Dropbox | ✅ Seamless with Nango auth, ✅ Seamless with Gumloop auth | [Dropbox Docs](/src/servers/dropbox/README.md) |
| OneDrive | ⚠️ Coming soon | [OneDrive Docs](/src/servers/onedrive/README.md) |
| SharePoint | ⚠️ Coming soon | [SharePoint Docs](/src/servers/sharepoint/README.md) |
| Jira | ✅ Seamless with Nango auth, ✅ Seamless with Gumloop auth | [Jira Docs](/src/servers/jira/README.md) |
| Calendly | ✅ Seamless with Nango auth, ✅ Seamless with Gumloop auth | [Calendly Docs](/src/servers/calendly/README.md) |
| Cal.com | ✅ Seamless with Gumloop auth | [Cal.com Docs](/src/servers/cal/README.md) |
| Canva | ✅ Seamless with Nango auth, ✅ Seamless with Gumloop auth | [Canva Docs](/src/servers/canva/README.md) |
| **Business Tools** |  |  |
| Apollo | ✅ Seamless with Gumloop auth | [Apollo Docs](/src/servers/apollo/README.md) |
| HubSpot | ✅ Seamless with Nango auth, ✅ Seamless with Gumloop auth | [HubSpot Docs](/src/servers/hubspot/README.md) |
| Hunter.io | ✅ Seamless with Gumloop auth | [Hunter.io Docs](/src/servers/hunter_io/README.md) |
| Lemlist | ⚠️ Coming soon | [Lemlist Docs](/src/servers/lemlist/README.md) |
| SendGrid | ✅ Seamless with Gumloop auth | [SendGrid Docs](/src/servers/sendgrid/README.md) |
| QuickBooks | ⚠️ Coming soon | [QuickBooks Docs](/src/servers/quickbooks/README.md) |
| Typeform | ✅ Seamless with Gumloop auth | [Typeform Docs](/src/servers/typeform/README.md) |
| Stripe | ✅ Seamless with Nango auth, ✅ Seamless with Gumloop auth | [Stripe Docs](/src/servers/stripe/README.md) |
| MailerLite | ⚠️ Coming soon | [MailerLite Docs](/src/servers/mailerlite/README.md) |
| Mailchimp | ⚠️ Coming soon | [Mailchimp Docs](/src/servers/mailchimp/README.md) |
| Klaviyo | ⚠️ Coming soon | [Klaviyo Docs](/src/servers/klaviyo/README.md) |
| PayPal | ⚠️ Coming soon | [PayPal Docs](/src/servers/paypal/README.md) |
| Instacart | ✅ Seamless with Gumloop auth | [Instacart Docs](/src/servers/instacart/README.md) |
| PagerDuty | ⚠️ Coming soon | [PagerDuty Docs](/src/servers/pagerduty/README.md) |
| Shopify | ⚠️ Coming soon | [Shopify Docs](/src/servers/shopify/README.md) |
| DocuSign | ⚠️ Coming soon | [DocuSign Docs](/src/servers/docusign/README.md) |
| Patreon | ⚠️ Coming soon | [Patreon Docs](/src/servers/patreon/README.md) |
| PostHog | ✅ Seamless with Nango auth | [PostHog Docs](/src/servers/posthog/README.md) |
| Salesforce | ✅ Seamless with Nango auth, ✅ Seamless with Gumloop auth | [Salesforce Docs](/src/servers/salesforce/README.md) |
| NetSuite | ✅ Seamless with Nango auth | [NetSuite Docs](/src/servers/netsuite/README.md) |
| **Search Tools** |  |  |
| Perplexity | ✅ Seamless with Gumloop auth | [Perplexity Docs](/src/servers/perplexity/README.md) |
| Ahrefs | ✅ Seamless with Gumloop auth | [Ahrefs Docs](/src/servers/ahrefs/README.md) |
| Firecrawl | ✅ Seamless with Gumloop auth | [Firecrawl Docs](/src/servers/firecrawl/README.md) |
| SerpAPI | ✅ Seamless with Gumloop auth | [SerpAPI Docs](/src/servers/serpapi/README.md) |
| Hacker News | ✅ No auth required | [Hacker News Docs](/src/servers/hackernews/README.md) |
| Reducto | ✅ Seamless with Gumloop auth | [Reducto Docs](/src/servers/reducto/README.md) |
| Apify | ✅ Seamless with Gumloop auth | [Apify Docs](/src/servers/apify/README.md) |
| **Development Tools** |  |  |
| Figma | ✅ Seamless with Nango auth, ✅ Seamless with Gumloop auth | [Figma Docs](/src/servers/figma/README.md) |
| GitHub | ⚠️ Coming soon | [GitHub Docs](/src/servers/github/README.md) |
| Browserbase | ✅ Seamless with Gumloop auth | [Browserbase Docs](/src/servers/browserbase/README.md) |
| Snowflake | ✅ Seamless with Gumloop auth | [Snowflake Docs](/src/servers/snowflake/README.md) |
| Simple Tools Server | ✅ No auth required | [Simple Tools Docs](/src/servers/simple-tools-server/README.md) |

## Contributing

We welcome contributions! Please see our [CONTRIBUTING.md](CONTRIBUTING.MD) for guidelines.

Key areas for contribution:

- New server implementations
- Transport improvements
- Documentation
- Test coverage
- Bug fixes

## License

This project is licensed under the GNU General Public License v3.0 (GPL-3.0) - see the [LICENSE](LICENSE) file for details

## Security

Security is the single highest priority for us.

That's why Peakflo is SOC 2 Type II, and why for this OSS repo, we're actively rewarding those who responsibly disclose serious vulnerabilities and exploits to security@peakflo.com.

## Community

- GitHub Issues: Bug reports and feature requests
- GitHub Discussions: General questions and discussions
- [Forum](https://forum.gumloop.com/): Community discussions and support

## Acknowledgments

This project builds on the Model Context Protocol (MCP) specification and is inspired by the work of various MCP implementations in the community, especially those at Anthropic.

Thank you to all the contributors that have provided feedback, advice, and early servers for the repository.
