# Setup — connecting the Compass MCP server and this skill

Read this when `compass_*` tools are missing from the session, when auth errors persist,
or when the user asks how to install/configure any of this.

## Contents

- [Getting the server](#getting-the-server)
- [Configuration](#configuration)
- [Wiring into agent platforms](#wiring-into-agent-platforms)
- [Authentication modes and the interactive login](#authentication)
- [Troubleshooting](#troubleshooting)
- [Installing this skill](#installing-this-skill)

## Getting the server

The server lives in the same repository as this skill, at `../server/` (package
`compass-mcp-server`, Python ≥3.11):

```bash
cd <repo>/compass-mcp/server
python3 -m venv .venv
.venv/bin/pip install -e .
```

Entry point: `.venv/bin/compass-mcp` (subcommands: `serve` [default] | `login` |
`status` | `logout`).

Credentials come from Compass registration — the user contacts
product@bespokemetrics.com for a `client_id`/`client_secret` and sandbox access.
Published shared sandbox Client Credentials exist in Compass's public developer docs.

## Configuration

All via environment variables on the server process:

| Variable | Default | Notes |
| --- | --- | --- |
| `COMPASS_ENV` | `sandbox-app` | or `compass2` (production) |
| `COMPASS_CLIENT_ID` / `COMPASS_CLIENT_SECRET` | — | required; never in tool schemas/output |
| `COMPASS_GRANT_TYPE` | `client_credentials` | or `authorization_code` (per-user) |
| `COMPASS_ALLOW_WRITES` | `false` | master switch for all 12 write tools |
| `COMPASS_REDIRECT_URI` | `http://localhost:8765/oauth2/callback` | must match Compass registration (auth-code mode) |
| `COMPASS_TOKEN_DIR` | `~/.compass-mcp` | stored logins, mode 600 |
| `COMPASS_WEB_URL` | derived | override the consent host if Compass specifies one |

Default to sandbox for anything experimental; suggest `compass2` only when the user
explicitly wants production, and keep `COMPASS_ALLOW_WRITES` off until they need a write.

## Wiring into agent platforms

The server speaks MCP over **stdio**; any MCP-capable platform can run it.

Claude Code:

```bash
claude mcp add compass \
  -e COMPASS_CLIENT_ID=... -e COMPASS_CLIENT_SECRET=... \
  -e COMPASS_ENV=sandbox-app \
  -- /path/to/compass-mcp/server/.venv/bin/compass-mcp
```

Claude Desktop / generic MCP client config:

```json
{
  "mcpServers": {
    "compass": {
      "command": "/path/to/compass-mcp/server/.venv/bin/compass-mcp",
      "env": {
        "COMPASS_ENV": "sandbox-app",
        "COMPASS_CLIENT_ID": "...",
        "COMPASS_CLIENT_SECRET": "...",
        "COMPASS_ALLOW_WRITES": "false"
      }
    }
  }
}
```

Restart the client session after adding; verify with `compass_auth_status`.

## Authentication

Two modes — pick based on whether the integration should act as a service or as a person:

**client_credentials (default).** Server-to-server; the token's identity is the
registered application. No interaction ever needed; tokens auto-refresh (~15 min
lifetime, refreshed at T-60s).

**authorization_code.** Acts as a signed-in Compass user; the token carries that user's
legal entity, which drives auto-scoping on projects/reviews/approvals. Requires the
interactive login once (~180-day refresh tokens, rotated automatically):

- From the terminal: `COMPASS_GRANT_TYPE=authorization_code compass-mcp login`
- From an agent session: call `compass_login` → give the user the returned `login_url`
  to open **in a browser on the machine running the server** → they sign in on
  Compass's own consent page (the local page never sees credentials) → poll
  `compass_auth_status` until `logged_in: true`.

Never ask the user to paste passwords, tokens, or authorization codes into the chat —
the flow exists precisely so credentials stay between the user and Compass.

## Troubleshooting

| Symptom | Meaning / fix |
| --- | --- |
| `WritesDisabledError` | Server started without `COMPASS_ALLOW_WRITES=true`. Relay; user must restart the server with it set. |
| `NotAuthenticatedError: No stored Compass login` | Auth-code mode without a completed login — run the login flow above. |
| `NotAuthenticatedError: ... refresh token has expired` | ~180 days elapsed — log in again. |
| `Token request failed: HTTP 400/401` | Wrong client_id/secret or wrong `COMPASS_ENV` for those credentials. |
| `Could not listen on 127.0.0.1:<port>` during login | Port taken or a login already running; `compass_login` returns the existing flow's URL. |
| Every call errors with `status: 0, transport error` | Server can't reach `*.bespokemetrics.io` — network/VPN issue. |
| Consent page 404s in sandbox | Sandbox consent host is assumed `https://sandbox.compass-app.com`; if Compass says otherwise, set `COMPASS_WEB_URL`. |
| Tools missing entirely | MCP server not attached to the session — wire it up (above) and restart the session. |

`compass-mcp status` (CLI) or `compass_auth_status` (tool) is always the first
diagnostic: it shows mode, environment, identity, and whether writes are enabled,
without exposing tokens.

## Installing this skill

This folder follows the portable Agent Skills layout (`SKILL.md` + `references/`):

- **Claude Code**: copy the folder to `.claude/skills/compass/` in a project (or
  `~/.claude/skills/compass/` globally).
- **Claude.ai / Claude Desktop**: package and upload — from the repo:
  `zip -r compass.skill skill/` (or use a skill packager) and add it via Settings →
  Skills / Capabilities.
- **Agent SDK / other platforms**: point the skills loader at this directory; only
  `SKILL.md` frontmatter (name + description) needs to be indexed — the references load
  on demand.

If the platform requires the folder name to match the skill name, name the copied
folder `compass/`.
