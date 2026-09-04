# Compass MCP Server

An unofficial [MCP](https://modelcontextprotocol.io) server exposing the COMPASS (Bespoke Metrics)
subcontractor-prequalification API as 43 tools, with OAuth2 handled entirely at the server
layer — including an **interactive browser login** for the Authorization Code grant.

## Install

```bash
cd server
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
```

Requires Python ≥ 3.11. Dependencies: `mcp>=2.0`, `httpx`.

## Configure

Everything is environment-driven; **no secrets ever appear in tool schemas or output.**

| Variable | Default | Purpose |
| --- | --- | --- |
| `COMPASS_ENV` | `sandbox-app` | `sandbox-app` (sandbox) or `compass2` (production) |
| `COMPASS_CLIENT_ID` | — | From Compass registration (product@bespokemetrics.com) |
| `COMPASS_CLIENT_SECRET` | — | From Compass registration. Keep out of committed files. |
| `COMPASS_GRANT_TYPE` | `client_credentials` | `client_credentials` (service principal) or `authorization_code` (act as a signed-in Compass user) |
| `COMPASS_ALLOW_WRITES` | `false` | Master switch for all 12 mutating tools |
| `COMPASS_REDIRECT_URI` | `http://localhost:8765/oauth2/callback` | Loopback redirect registered with Compass (Authorization Code only) |
| `COMPASS_TOKEN_DIR` | `~/.compass-mcp` | Where Authorization Code tokens are stored (`chmod 600`) |
| `COMPASS_WEB_URL` | derived from env | Override the consent-page host if Compass confirms a different sandbox URL |
| `COMPASS_BASE_URL` | derived from env | Full API base override (testing) |
| `COMPASS_TIMEOUT` / `COMPASS_MAX_RETRIES` | `30` / `3` | HTTP timeout (s) and retry budget for 429/5xx |

## Run

```bash
COMPASS_CLIENT_ID=... COMPASS_CLIENT_SECRET=... .venv/bin/compass-mcp        # stdio server
```

Claude Code:

```bash
claude mcp add compass -e COMPASS_CLIENT_ID=... -e COMPASS_CLIENT_SECRET=... -- /path/to/server/.venv/bin/compass-mcp
```

Claude Desktop (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "compass": {
      "command": "/path/to/server/.venv/bin/compass-mcp",
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

## Authentication

### Client Credentials (default — recommended for server-to-server)

Nothing to do beyond setting the env vars. Tokens live ~15 minutes; the server refreshes
proactively 60 s before expiry and retries once on 401. There is deliberately **no token
tool** — auth is infrastructure, not a model capability.

### Authorization Code — the interactive login

Use this when the integration should act as a specific Compass **user** (the token response
then carries that user's `legal_entity`, which drives auto-scoping on the poll endpoints).

```bash
COMPASS_GRANT_TYPE=authorization_code .venv/bin/compass-mcp login
```

What happens:

1. A small page opens at `http://localhost:8765/` (loopback only). It never asks for
   credentials — it links to Compass's own consent page (`{web_url}/oauth-login`).
2. You sign in **on Compass's site** and click Allow.
3. Compass redirects back to the local callback; the server validates the CSRF `state`,
   exchanges the `authorization_code`, and stores tokens in
   `~/.compass-mcp/{env}.json` (mode 600). Refresh tokens last ~180 days and are rotated
   on every refresh.
4. Run the server with `COMPASS_GRANT_TYPE=authorization_code` and it uses the stored login.

The same flow is reachable from inside an MCP session via the `compass_login` tool (it
returns the login URL for the user to open; check `compass_auth_status` afterwards), and
`compass-mcp status` / `compass-mcp logout` manage the stored tokens from the CLI.

> The sandbox consent host is assumed to be `https://sandbox.compass-app.com` (the docs only
> show production); set `COMPASS_WEB_URL` if Compass confirms a different one.

## Tool surface (43)

### Reads (28 remote + 2 local)

| Tool | Notes |
| --- | --- |
| `compass_list_legal_entities` | The entry point: resolve company names → `legal_entity_id` |
| `compass_get_legal_entity` | Optional `resolve_trades` / `resolve_work_locations` enrichment |
| `compass_list_legal_entity_notes` | GC comments on a sub (`parent`=GC, `child`=sub) |
| `compass_list_offices` | Embeds the main-contact user object |
| `compass_get_offices_for_entity` | Warns when the (unpaginated) endpoint reports more than it returned |
| `compass_list_inactive_offices` | Deletion detection for syncs |
| `compass_get_user` / `compass_get_users` | No user search exists; bulk resolver fans out with concurrency 5 + cache |
| `compass_poll_office_main_contacts` | Filters on `main_contact_updated_*`, not user `updated` |
| `compass_get_work_locations` | Boundary work areas only; reports unresolved UUIDs |
| `compass_list_trades` / `compass_get_trade` / `compass_get_trades_bulk` | Bulk resolver returns concatenated `code`; broken spec `level` filter not exposed |
| `compass_list_workflows` | Adds a derived `summary`; inclusive `_gte/_lte` bounds named explicitly |
| `compass_list_workflow_notes` | Type filter un-namespaced; shareable-subset toggle |
| `compass_list_prequalifications` | **Adds `derived_status`** (EXPIRED > DENIED > QUALIFIED_WITH_EXCEPTIONS > QUALIFIED); defaults to current records |
| `compass_list_prequalification_notes` | `comment` = Qualification Summary; `feedback` = reaction to recommended limits |
| `compass_list_scores` | Returns `score_groups` keyed by (trade, nationality); optional trade-name resolution |
| `compass_list_tags` / `compass_get_tag` / `compass_get_tags_bulk` | |
| `compass_get_tag_assignments` | "Which tags are on company X?" — takes `legal_entity_id`s (confirmed semantics) |
| `compass_poll_one_form` | Mandatory section projection; envelope+inventory by default; suppresses deprecated placeholder fields |
| `compass_poll_reviews` | Adds per-section answer counts + recommend/lien flags; ratings passed through as strings |
| `compass_poll_projects` / `compass_resolve_projects` | Short-TTL index by `id` and `internal_id` (no fetch-by-ID exists) |
| `compass_poll_approval_requests` | Stage `progress` strings (one_review vs all_reviews), null-stage explanations, optional reviewer-name resolution |
| `compass_poll_approval_flows` | `flow_type` required (the API's only required query param) |
| `compass_validate_contracts_csv` | Local-only pre-flight mirroring the 7 documented error types |
| `compass_auth_status` | Mode, signed-in identity, expiries — never token material |

### Writes (12 — all require `COMPASS_ALLOW_WRITES=true`)

| Tool | Extra gate |
| --- | --- |
| `compass_create_workflow` | — |
| `compass_invite_subcontractor` | `confirm=true` — **emails a real third party** |
| `compass_delete_workflow` | `confirm=true` |
| `compass_create_workflow_note` / `compass_update_workflow_note` | — |
| `compass_create_prequalification` | `confirm=true` — sets contract limits; preview shows the resulting derived status; tool requires `qualified` + `expires` |
| `compass_create_tag` / `compass_update_tag` | — |
| `compass_delete_tag` | `confirm=true` — cascades to every assignment |
| `compass_assign_tag` / `compass_unassign_tag` | take the sub's `legal_entity_id` |
| `compass_import_contracts_csv` | `confirm=true` — validated locally first; multipart field is literally `data.csv` |

Confirmation-gated tools return a `confirmation_required` preview (no API call) until
re-invoked with `confirm=true`, so the human sees the exact values before anything happens.

### Auth action

`compass_login` — starts the interactive login (Authorization Code mode only) and returns
the local login URL.

## Behavior guarantees

- **Timestamps**: tool inputs accept ISO-8601 or epoch seconds; known epoch fields in
  responses are rendered as ISO-8601 UTC.
- **Pagination**: auto-paginates up to `max_pages` (default 5) and reports
  `count / returned / truncated / next_page` — truncation is never silent.
- **Errors**: Compass documents no error schema, so non-2xx responses come back as
  `{"error": {status, method, path, body}}` with the body verbatim. Retries with backoff on
  429/5xx; one automatic re-auth on 401.
- **Enums are open**: known values live in tool descriptions, not as hard schema constraints
  (Compass adds enum values non-breakingly).
- **No codegen from the spec**: request/response handling here is hand-written rather
  than generated from the published OpenAPI document.

## Tests

110 unit tests, no network:

```bash
PYTHONPATH=src:tests .venv/bin/python -m pytest tests/ -q
```

Coverage: config, time conversion, token lifecycle for both grants (incl. refresh rotation
and file permissions), the login page/callback (CSRF state, cancel, success, exchange
failure, loopback enforcement), HTTP retries/pagination/params, every shaping rule
(prequal truth table, score grouping, 1Form sectioning, approvals progress), the CSV
validator (all 7 error types + the completed-inference trap), read/write tool request
shapes, write gating + confirmation flows, and the registered tool surface (43 tools,
annotations, required params).

## Layout

```
server/
├── pyproject.toml
├── src/compass_mcp/
│   ├── config.py         env-driven configuration
│   ├── auth.py           TokenManager (both grants) + code exchange
│   ├── login_server.py   interactive OAuth login page (loopback HTTP)
│   ├── token_store.py    0600 token persistence
│   ├── client.py         retries, 401 re-auth, pagination
│   ├── caches.py         trades / users / project index
│   ├── shaping.py        derived statuses, grouping, sectioning, progress strings
│   ├── csv_validator.py  local contracts-CSV pre-flight
│   ├── runtime.py        app context
│   ├── server.py         tool registration + annotations (the whole surface in one file)
│   ├── cli.py            serve | login | status | logout
│   └── tools/            one module per Compass service, mirroring ../NN-*.md
└── tests/
```
