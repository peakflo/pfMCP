# Gumloop Unified Model Context Protocol (guMCP)

guMCP is an open-source collection of Model Context Protocol (MCP) servers that can be run both remotely and locally. The project aims to create the largest collection of MCP servers with a unified backend, fostering a community around AI integrations and the future of AGI.
 
## Overview

While many MCP server providers are closed source, and open-source alternatives typically only support local hosting through stdio, guMCP provides:

- A comprehensive collection of MCP servers that work both locally and remotely
- Support for both stdio and SSE (Server-Sent Events) transports
- A unified backend architecture for consistent implementation
- Full open-source access to encourage community contributions

## Getting Started

> **🎬 RECOMMENDED: Watch our quick setup video before getting started!**
>
> This under 5-minute walkthrough will save you time and help you understand the key concepts.
>
> [![Watch the guMCP Getting Started Video](https://www.gumloop.com/_next/image?url=%2Fimages%2Fmcp%2FGuideVideo.png&w=1920&q=75)](https://vimeo.com/1070438737/8dea56e6a1)

### Prerequisites

- Python 3.11
- Git
- For Windows users: A bash-compatible shell is recommended (Git Bash, WSL, etc.)

### Installation

1. **Clone the repository**:

   ```bash
   git clone https://github.com/gumloop/guMCP.git
   cd guMCP
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

The following table provides an overview of the current servers implemented in guMCP, their authentication requirements, and relative ease of use with different authentication methods:

| Server                  | Auth Type | Remote Auth<br>(e.g., Cursor)                                            | Local Auth<br>(e.g., Claude Desktop)                 | Documentation                                                   |
| ----------------------- | --------- | ------------------------------------------------------------------------ | ---------------------------------------------------- | --------------------------------------------------------------- |
| **Google Services**     |           |                                                                          |                                                      |                                                                 |
| Google Sheets           | OAuth 2.0 | [✅ Seamless with Gumloop auth](https://www.gumloop.com/mcp/gsheets)     | ⚠️ Requires GCP project & OAuth setup                | [GSheets Docs](/src/servers/gsheets/README.md)                  |
| Gmail                   | OAuth 2.0 | [✅ Seamless with Gumloop auth](https://www.gumloop.com/mcp/gmail)       | ⚠️ Requires GCP project & OAuth setup                | [Gmail Docs](/src/servers/gmail/README.md)                      |
| Google Docs             | OAuth 2.0 | [✅ Seamless with Gumloop auth](https://www.gumloop.com/mcp/gdocs)       | ⚠️ Requires GCP project & OAuth setup                | [GDocs Docs](/src/servers/gdocs/README.md)                      |
| Google Drive            | OAuth 2.0 | [✅ Seamless with Gumloop auth](https://www.gumloop.com/mcp/gdrive)      | ⚠️ Requires GCP project & OAuth setup                | [GDrive Docs](/src/servers/gdrive/README.md)                    |
| Google Calendar         | OAuth 2.0 | [✅ Seamless with Gumloop auth](https://www.gumloop.com/mcp/gcalendar)   | ⚠️ Requires GCP project & OAuth setup                | [GCalendar Docs](/src/servers/gcalendar/README.md)              |
| Google Maps             | API Key   | ⚠️ Coming soon                                                           | ⚠️ Requires GCP project & API Key                    | [GMaps Docs](/src/servers/gmaps/README.md)                      |
| Google Meet             | OAuth 2.0 | [✅ Seamless with Gumloop auth](https://www.gumloop.com/mcp/gmeet)       | ⚠️ Requires GCP project & OAuth setup                | [GMeet Docs](/src/servers/gmeet/README.md)                      |
| YouTube                 | OAuth 2.0 | [✅ Seamless with Gumloop auth](https://www.gumloop.com/mcp/youtube)     | ⚠️ Requires GCP project & OAuth setup                | [YouTube Docs](/src/servers/youtube/README.md)                  |
| **Communication Tools** |           |                                                                          |                                                      |                                                                 |
| Slack                   | OAuth 2.0 | [✅ Seamless with Gumloop auth](https://www.gumloop.com/mcp/slack)       | ⚠️ Requires OAuth setup with HTTPS redirect          | [Slack Docs](/src/servers/slack/README.md)                      |
| Microsoft Teams         | OAuth 2.0 | ⚠️ Coming soon                                                           | ⚠️ Requires Azure app registration                   | [Teams Docs](/src/servers/teams/README.md)                      |
| Outlook                 | OAuth 2.0 | [✅ Seamless with Gumloop auth](https://www.gumloop.com/mcp/outlook)     | ⚠️ Requires Azure app registration                   | [Outlook Docs](/src/servers/outlook/README.md)                  |
| Discourse               | API Key   | [✅ Seamless with Gumloop auth](https://www.gumloop.com/mcp/discourse)   | ✅ Easy - Simple API key setup                       | [Discourse Docs](/src/servers/discourse/README.md)              |
| X (Twitter)             | OAuth 2.0 | ⚠️ Coming soon                                                           | ⚠️ Requires X Developer Account                      | [X Docs](/src/servers/x/README.md)                              |
| Bluesky                 | API Key   | ⚠️ Coming soon                                                           | ✅ Easy - Simple API key setup                       | [Bluesky Docs](/src/servers/bluesky/README.md)                  |
| Reddit                  | OAuth 2.0 | [✅ Seamless with Gumloop auth](https://www.gumloop.com/mcp/reddit)      | ⚠️ Requires Reddit Developer App                     | [Reddit Docs](/src/servers/reddit/README.md)                    |
| Intercom                | OAuth 2.0 | ⚠️ Coming soon                                                           | ⚠️ Requires Intercom OAuth App                       | [Intercom Docs](/src/servers/intercom/README.md)                |
| Zoom                    | OAuth 2.0 | ⚠️ Coming soon                                                           | ⚠️ Requires Zoom Developer App                       | [Zoom Docs](/src/servers/zoom/README.md)                        |
| Twilio                  | API Key   | ⚠️ Coming soon                                                           | ✅ Easy - Simple API key setup                       | [Twilio Docs](/src/servers/twilio/README.md)                    |
| **Productivity Tools**  |           |                                                                          |                                                      |                                                                 |
| Airtable                | OAuth 2.0 | [✅ Seamless with Gumloop auth](https://www.gumloop.com/mcp/airtable)    | ⚠️ Requires Airtable OAuth application               | [Airtable Docs](/src/servers/airtable/README.md)                |
| Excel                   | OAuth 2.0 | [✅ Seamless with Gumloop auth](https://www.gumloop.com/mcp/excel)       | ⚠️ Requires Microsoft OAuth application              | [Excel Docs](/src/servers/excel/README.md)                      |
| Word                    | OAuth 2.0 | [✅ Seamless with Gumloop auth](https://www.gumloop.com/mcp/word)        | ⚠️ Requires Microsoft OAuth application              | [Word Docs](/src/servers/word/README.md)                        |
| Linear                  | OAuth 2.0 | [✅ Seamless with Gumloop auth](https://www.gumloop.com/mcp/linear)      | ⚠️ Requires Linear OAuth application                 | [Linear Docs](/src/servers/linear/README.md)                    |
| Monday.com              | OAuth 2.0 | [✅ Seamless with Gumloop auth](https://www.gumloop.com/mcp/monday)      | ⚠️ Requires Monday.com OAuth application             | [Monday.com Docs](/src/servers/monday/README.md)                |
| Attio                   | OAuth 2.0 | [✅ Seamless with Gumloop auth](https://www.gumloop.com/mcp/attio)       | ⚠️ Requires Attio OAuth application                  | [Attio Docs](/src/servers/attio/README.md)                      |
| Notion                  | OAuth 2.0 | [✅ Seamless with Gumloop auth](https://www.gumloop.com/mcp/notion)      | ⚠️ Requires Notion OAuth application                 | [Notion Docs](/src/servers/notion/README.md)                    |
| Loops                   | OAuth 2.0 | ⚠️ Coming soon                                                           | ✅ Easy - Simple API key setup                       | [Loops Docs](/src/servers/loops/README.md)                      |
| Webflow                 | OAuth 2.0 | ⚠️ Coming soon                                                           | ⚠️ Requires Webflow OAuth application                | [Webflow Docs](/src/servers/webflow/README.md)                  |
| ClickUp                 | OAuth 2.0 | [✅ Seamless with Gumloop auth](https://www.gumloop.com/mcp/clickup)     | ⚠️ Requires ClickUp OAuth application                | [ClickUp Docs](/src/servers/clickup/README.md)                  |
| Dropbox                 | OAuth 2.0 | [✅ Seamless with Gumloop auth](https://www.gumloop.com/mcp/dropbox)     | ⚠️ Requires Dropbox OAuth application                | [Dropbox Docs](/src/servers/dropbox/README.md)                  |
| OneDrive                | OAuth 2.0 | ⚠️ Coming soon                                                           | ⚠️ Requires Microsoft OAuth application              | [OneDrive Docs](/src/servers/onedrive/README.md)                |
| SharePoint              | OAuth 2.0 | ⚠️ Coming soon                                                           | ⚠️ Requires Microsoft OAuth application              | [SharePoint Docs](/src/servers/sharepoint/README.md)            |
| Jira                    | OAuth 2.0 | [✅ Seamless with Gumloop auth](https://www.gumloop.com/mcp/jira)        | ⚠️ Requires Atlassian OAuth 2.0 (3LO) setup          | [Jira Docs](/src/servers/jira/README.md)                        |
| Calendly                | OAuth 2.0 | [✅ Seamless with Gumloop auth](https://www.gumloop.com/mcp/calendly)    | ⚠️ Requires Calendly OAuth application               | [Calendly Docs](/src/servers/calendly/README.md)                |
| Cal.com                 | API Key   | [✅ Seamless with Gumloop auth](https://www.gumloop.com/mcp/calcom)      | ⚠️ Requires Cal.com API key setup                    | [Cal.com Docs](/src/servers/calcom/README.md)                   |
| Canva                   | OAuth 2.0 | [✅ Seamless with Gumloop auth](https://www.gumloop.com/mcp/canva)       | ⚠️ Requires Canva OAuth integration                  | [Canva Docs](/src/servers/canva/README.md)                      |
| **Business Tools**      |           |                                                                          |                                                      |                                                                 |
| Apollo                  | API Key   | [✅ Seamless with Gumloop auth](https://www.gumloop.com/mcp/apollo)      | ✅ Easy - Simple API key setup                       | [Apollo Docs](/src/servers/apollo/README.md)                    |
| HubSpot                 | OAuth 2.0 | [✅ Seamless with Gumloop auth](https://www.gumloop.com/mcp/hubspot)     | ⚠️ Requires HubSpot OAuth application                | [HubSpot Docs](/src/servers/hubspot/README.md)                  |
| Hunter.io               | API Key   | [✅ Seamless with Gumloop auth](https://www.gumloop.com/mcp/hunter)      | ✅ Easy - Simple API key setup                       | [Hunter.io Docs](/src/servers/hunter_io/README.md)              |
| Lemlist                 | API Key   | ⚠️ Coming soon                                                           | ✅ Easy - Simple API key setup                       | [Lemlist Docs](/src/servers/lemlist/README.md)                  |
| SendGrid                | API Key   | [✅ Seamless with Gumloop auth](https://www.gumloop.com/mcp/sendgrid)    | ✅ Easy - Simple API key setup                       | [SendGrid Docs](/src/servers/sendgrid/README.md)                |
| QuickBooks              | OAuth 2.0 | ⚠️ Coming soon                                                           | ⚠️ Requires Intuit OAuth application                 | [QuickBooks Docs](/src/servers/quickbooks/README.md)            |
| Typeform                | API Key   | [✅ Seamless with Gumloop auth](https://www.gumloop.com/mcp/typeform)    | ✅ Easy - Simple API key setup                       | [Typeform Docs](/src/servers/typeform/README.md)                |
| Stripe                  | OAuth 2.0 | [✅ Seamless with Gumloop auth](https://www.gumloop.com/mcp/stripe)      | ⚠️ Requires Stripe OAuth setup                       | [Stripe Docs](/src/servers/stripe/README.md)                    |
| MailerLite              | API Key   | ⚠️ Coming soon                                                           | ✅ Easy - Simple API key setup                       | [MailerLite Docs](/src/servers/mailerlite/README.md)            |
| Mailchimp               | OAuth 2.0 | ⚠️ Coming soon                                                           | ⚠️ Requires Mailchimp OAuth application              | [Mailchimp Docs](/src/servers/mailchimp/README.md)              |
| Klaviyo                 | OAuth 2.0 | ⚠️ Coming soon                                                           | ⚠️ Requires Klaviyo OAuth application                | [Klaviyo Docs](/src/servers/klaviyo/README.md)                  |
| PayPal                  | OAuth 2.0 | ⚠️ Coming soon                                                           | ⚠️ Requires PayPal OAuth setup                       | [PayPal Docs](/src/servers/paypal/README.md)                    |
| Instacart               | API Key   | [✅ Seamless with Gumloop auth](https://www.gumloop.com/mcp/instacart)   | ✅ Easy - Simple API key setup                       | [Instacart Docs](/src/servers/instacart/README.md)              |
| PagerDuty               | OAuth 2.0 | ⚠️ Coming soon                                                           | ⚠️ Requires PagerDuty OAuth application              | [PagerDuty Docs](/src/servers/pagerduty/README.md)              |
| Shopify                 | OAuth 2.0 | ⚠️ Coming soon                                                           | ⚠️ Requires Shopify OAuth Application                | [Shopify Docs](/src/servers/shopify/README.md)                  |
| DocuSign                | OAuth 2.0 | ⚠️ Coming soon                                                           | ⚠️ Requires OAuth setup                              | [DocuSign Docs](/src/servers/docusign/README.md)                |
| Patreon                 | OAuth 2.0 | ⚠️ Coming soon                                                           | ⚠️ Requires Patreon OAuth application                | [Patreon Docs](/src/servers/patreon/README.md)                  |
| PostHog                 | API Key   | [✅ Seamless with Gumloop auth](https://www.gumloop.com/mcp/posthog)     | ✅ Easy - Simple API key setup                       | [PostHog Docs](/src/servers/posthog/README.md)                  |
| Salesforce              | OAuth 2.0 | [✅ Seamless with Gumloop auth](https://www.gumloop.com/mcp/salesforce)  | ⚠️ Requires Salesforce Connected App setup           | [Salesforce Docs](/src/servers/salesforce/README.md)            |
| **Search Tools**        |           |                                                                          |                                                      |                                                                 |
| Perplexity              | API Key   | [✅ Seamless with Gumloop auth](https://www.gumloop.com/mcp/perplexity)  | ✅ Easy - Simple API key setup                       | [Perplexity Docs](/src/servers/perplexity/README.md)            |
| Ahrefs                  | API Key   | [✅ Seamless with Gumloop auth](https://www.gumloop.com/mcp/ahrefs)      | ✅ Easy - Simple API key setup                       | [Ahrefs Docs](/src/servers/ahrefs/README.md)                    |
| Firecrawl               | API Key   | [✅ Seamless with Gumloop auth](https://www.gumloop.com/mcp/firecrawl)   | ✅ Easy - Simple API key setup                       | [Firecrawl Docs](/src/servers/firecrawl/README.md)              |
| SerpAPI                 | API Key   | [✅ Seamless with Gumloop auth](https://www.gumloop.com/mcp/serpapi)     | ✅ Easy - Simple API key setup                       | [SerpAPI Docs](/src/servers/serpapi/README.md)                  |
| Hacker News             | None      | ✅ No auth required                                                      | ✅ No auth required                                  | [Hacker News Docs](/src/servers/hackernews/README.md)           |
| Reducto                 | API Key   | [✅ Seamless with Gumloop auth](https://www.gumloop.com/mcp/reducto)     | ✅ Easy - Simple API key setup                       | [Reducto Docs](/src/servers/reducto/README.md)                  |
| Apify                   | API Key   | [✅ Seamless with Gumloop auth](https://www.gumloop.com/mcp/apify)       | ✅ Easy - Simple API key setup                       | [Apify Docs](/src/servers/apify/README.md)                      |
| **Development Tools**   |           |                                                                          |                                                      |                                                                 |
| Figma                   | OAuth 2.0 | [✅ Seamless with Gumloop auth](https://www.gumloop.com/mcp/figma)       | ⚠️ Requires Figma OAuth application                  | [Figma Docs](/src/servers/figma/README.md)                      |
| GitHub                  | OAuth 2.0 | ⚠️ Coming soon                                                           | ⚠️ Requires GitHub OAuth application                 | [GitHub Docs](/src/servers/github/README.md)                    |
| Browserbase             | API Key   | [✅ Seamless with Gumloop auth](https://www.gumloop.com/mcp/browserbase) | ✅ Easy - Simple API key setup                       | [Browserbase Docs](/src/servers/browserbase/README.md)          |
| Snowflake               | OAuth 2.0 | [✅ Seamless with Gumloop auth](https://www.gumloop.com/mcp/snowflake)   | ⚠️ Requires Snowflake Security Integration for OAuth | [Snowflake Docs](/src/servers/snowflake/README.md)              |
| Simple Tools Server     | None      | ✅ No auth required                                                      | ✅ No auth required                                  | [Simple Tools Docs](/src/servers/simple-tools-server/README.md) |

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

That's why [Gumloop is SOC 2 Type II, GDPR, and HIPAA compliant](https://trust.gumloop.com/), and why for this OSS repo, we're actively rewarding those who responsibly disclose serious vulnerabilities and exploits to security@gumloop.com.

## Community

- GitHub Issues: Bug reports and feature requests
- GitHub Discussions: General questions and discussions
- [Forum](https://forum.gumloop.com/): Community discussions and support

## Acknowledgments

This project builds on the Model Context Protocol (MCP) specification and is inspired by the work of various MCP implementations in the community, especially those at Anthropic.

Thank you to all the contributors that have provided feedback, advice, and early servers for the repository.
