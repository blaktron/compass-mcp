# Compass tool catalog — all 43 tools

Exact parameters and behaviors of the Compass MCP server (v0.1.x). Optional parameters
are omitted from calls, not passed as null.

## Contents

- [Conventions every tool shares](#conventions)
- [Legal entities](#legal-entities) · [Offices](#offices) · [Users](#users) ·
  [Locations](#locations) · [Trades](#trades)
- [Workflows](#workflows-qualification-requests) · [Prequalification](#prequalification) ·
  [Q Scores](#q-scores)
- [Tags](#tags) · [1Form](#1form) · [Contracts](#contracts) · [Reviews](#reviews) ·
  [Projects](#projects) · [Approvals](#approvals)
- [Auth](#auth)

## Conventions

- **Paginated reads** return `{count, returned, truncated, next_page, data: [...]}`.
  `count` is the server-side total; `truncated=true` means more matches exist —
  `next_page` says where to resume (pass a larger `max_pages` or higher `limit`).
  Defaults: `limit=50` (max 250), `max_pages=5`.
- **Timestamps**: inputs named `*_after` / `*_before` / `expires` / `deadline` /
  `changed_*` accept ISO-8601 strings or epoch seconds. Outputs render known timestamp
  fields as ISO-8601 UTC (`2026-08-23T14:00:00Z`).
- **Errors** return `{"error": {"type"|..., "status", "method", "path", "body"}}` —
  `body` is the raw API response (Compass documents no error schema). Auth problems
  return `type: NotAuthenticatedError`; disabled writes return `type:
  WritesDisabledError`.
- **Confirmation-gated writes** return
  `{"confirmation_required": true, "action", "preview", "instructions"}` until re-called
  with `confirm=true`.
- Enum-ish string parameters are open — known values are listed here, but pass through
  anything the user legitimately needs (Compass adds values non-breakingly).

---

## Legal entities

### compass_list_legal_entities — the universal entry point
`(name, type, status, nationality, gst_number, id, active, updated_after, updated_before, sort_by, sort_dir, limit, max_pages)`

- `type`: gc | sub | supplier | sub_supplier | insurance. `status`: active | inactive |
  unclaimed (prefer over legacy `active`). `sort_by`: created | updated | display_name.
- `gst_number` = tax ID (FEIN etc.) — the reliable key for ERP reconciliation.
- Whether `name` matches exactly or partially is undocumented; if a name search comes up
  empty, retry with a shorter fragment before concluding absence.

### compass_get_legal_entity
`(id, resolve_trades=false, resolve_work_locations=false)`

- Returns the company profile. `resolve_trades=true` adds `trades_resolved` (UUID → name,
  code, level for the whole trades/NAICS hierarchy); `resolve_work_locations=true` adds
  `work_locations_resolved` (+ `work_locations_unresolved`).
- `revenue` and `incorporated` are bare integers — no currency/unit; don't add symbols.
- `dba_names.primary/secondary` hold trade names the company also operates under.

### compass_list_legal_entity_notes
`(sub_legal_entity_id, limit, max_pages)` — public comments GCs left on a sub's record.
In results: `parent_id` = GC author, `child_id` = subject sub.

## Offices

### compass_list_offices
`(name, primary, purposes, user_id, location_id, updated_after, updated_before, sort_dir, limit, max_pages)`

- Embeds the full `main_contact` user object. `primary=true` → the company's head
  office (exactly one per company). `purposes`: list from {billing, purchasing}.

### compass_get_offices_for_entity
`(legal_entity_id)` — all offices for one company. Returns `main_contact_id` only
(resolve via users tools). Unpaginated: a `warning` appears if the API reported more
offices than it returned (the rest are unreachable).

### compass_list_inactive_offices
`(updated_after, updated_before, limit, max_pages)` — deleted/deactivated offices, for
detecting removals during a sync. These default `current=false`; don't filter them out.

## Users

### compass_get_user / compass_get_users
`(id)` / `(ids)` — resolve user UUIDs to name, title, email, phone, legal entity,
offices. `compass_get_users` takes ≤50 ids, runs concurrently, and caches. **There is no
user search** — UUIDs come from other objects (`created_by`, `requested_by`,
`reviewers`, `main_contact_id`, `primary_user`).

### compass_poll_office_main_contacts
`(changed_after, changed_before, sort_dir, limit, max_pages)` — users whose office
main-contact **assignment** changed in the window (filters `main_contact_updated`, not
the user record). Detects contact reassignment, not general user edits.

## Locations

### compass_get_work_locations
`(ids)` — resolves work-area UUIDs (from `legal_entity.work_locations`) to
country/province/county + boundary code. Boundary regions only — Compass exposes **no
street addresses or coordinates** for locations; office addresses live on office
objects. Returns `unresolved` for ids the API silently dropped.

## Trades

### compass_list_trades
`(taxonomy, name, division_1..division_5, limit, max_pages)`

- `taxonomy`: csi_code (default) | naics_code. Hierarchy is the division prefix: all of
  NAICS sector 54 → `taxonomy="naics_code", division_1="54"`. There's no parent pointer
  and (deliberately) no level filter.

### compass_get_trade / compass_get_trades_bulk
`(id)` / `(ids)` — bulk resolver is cached and adds `code` = concatenated division
segments (e.g. `54111`). Use it for every trade UUID you encounter: legal-entity trade
hierarchies, score `trade_id`, approval `trade_id`, review `internal_info.trade_code`.

## Workflows (qualification requests)

### compass_list_workflows
`(cs_status, status, sub_legal_entity_id, prequal_id, project_ids, analytics_run, submission_expires_after, submission_expires_before, on_hold_until_before, updated_after, updated_before, sort_dir, limit, max_pages)`

- `cs_status`: in_progress | on_hold | escalated | completed. `escalated` = COMPASS
  gave up chasing the sub; the GC must act.
- `status` is the legacy field — filter available, but read the derived `summary` each
  row carries instead.
- No server-side `review_status` filter (compass | in_review | changes_required |
  completed | cancelled) — fetch broader, filter locally.
- `project_ids` list is sent comma-joined. `submission_expires_*` are **inclusive**
  bounds on the Compass Complete submission expiry.
- Null `sub_legal_entity_id` → still awaiting registration; use `invited_sub_name`.
  `prequal_id` set → the resulting qualification record.

### compass_list_workflow_notes
`(workflow_id, type, include_non_shareable=false, include_history=false, sort_dir, limit, max_pages)`

- `type` (un-namespaced in queries; responses show `workflow.*`): internal | comment |
  escalation | on_hold | request (deprecated).
- The API filters by shareable-flag subset: default = shareable notes only;
  `include_non_shareable=true` = non-shareable only (both requires two calls).

### Writes
- `compass_create_workflow(sub_legal_entity_id, project_id, deadline, reason, internal_note)` —
  invite an existing sub. `reason`: new | increase | renewal | auto_renewal |
  referral_link | gc_invited | analytics | compass_suggested | sub_requested. No
  idempotency: check for an existing workflow first.
- `compass_invite_subcontractor(email, legal_entity_name, first_name, last_name, phone, phone_ext, project_id, deadline, confirm)` —
  **confirm-gated; emails a real person**; creates an unclaimed account. Company name ≤50
  chars, no `{}`.
- `compass_delete_workflow(id, confirm)` — confirm-gated; removes from Qualification
  Management; treat as irreversible.
- `compass_create_workflow_note(workflow_id, content, type="comment"|"internal", shareable)` —
  only those two types are creatable.
- `compass_update_workflow_note(workflow_id, note_id, content, shareable)` — overwrites
  content; type immutable; API returns no body (re-read to verify).

## Prequalification

### compass_list_prequalifications
`(sub_legal_entity_id, gc_legal_entity_id, qualified, prequal_review, created_by, include_history=false, expires_after, expires_before, created_after, created_before, updated_after, updated_before, sort_by, sort_dir, limit, max_pages)`

- Every record carries server-computed **`derived_status`**: EXPIRED |
  DENIED | QUALIFIED_WITH_EXCEPTIONS | QUALIFIED | UNKNOWN. Report that.
- Renewal sweep: `expires_after=<now>, expires_before=<cutoff>, sort_by="expires"`.
  Already lapsed: `expires_before=<now>`.
- `prequal_review`: approved | pending | refused (two-step limit-change approval;
  `refused` means the old limits still stand).
- If `currency_tracked` is false, limits are unitless numbers — no $ signs.

### compass_list_prequalification_notes
`(prequalification_id, type, include_history, limit, max_pages)` — `type`: comment (the
GC's Qualification Summary — where a created record's `comment` lands) | feedback (GC's
reaction to Compass's recommended limits). Notes cannot be created via the API.

### compass_create_prequalification — confirm-gated
`(sub_legal_entity_id, qualified, expires, single_contract_limit, aggregate_contract_limit, currency, exceptions, comment, prequal_review, remove_from_hotlist, confirm)`

- `qualified` and `expires` are required by the tool (not the API) so the resulting
  status is never ambiguous; the preview shows `resulting_status` — read it back to the
  user. Non-empty `exceptions` ⇒ "Qualified with exceptions".
- `remove_from_hotlist=true` is a second write: it completes/removes the sub's open
  qualification requests.
- `comment` is stored as a note, not on the returned object.

## Q Scores

### compass_list_scores
`(legal_entity_id, nationality, include_history=false, resolve_trade_names=true, updated_after, updated_before, sort_dir, limit, max_pages)`

- Returns `score_groups`: one entry per (trade, nationality) with `current`, `history`
  (empty unless `include_history`), `history_count`, and resolved `trade` names.
- A score's `submission_id` cannot be fetched by id; poll `compass_poll_one_form` by
  `legal_entity_id` and match on `id`.

## Tags

GC-private labels on companies. Everywhere this service says "entity", pass the
**company's `legal_entity_id`** (confirmed semantics).

- `compass_list_tags(sort_by, sort_dir)` — all tags; `sort_by`: created | updated |
  label. No pagination exists; a `warning` flags unreachable remainder. Deleted tags
  can't be listed.
- `compass_get_tag(id)` / `compass_get_tags_bulk(ids)`
- `compass_get_tag_assignments(entity_ids)` — "which tags are on these companies?"
  Returns renamed fields: `assignment_record_id`, `tag_id`,
  `subcontractor_legal_entity_id`, `owning_gc_legal_entity_id`. Reverse lookup ("which
  companies have tag T") needs a candidate list — no direct endpoint.
- `compass_create_tag(label)` — label 1–127 chars, unique per GC (duplicate → raw API
  error).
- `compass_update_tag(id, label)` — rename ripples to every assignment.
- `compass_delete_tag(id, confirm)` — **confirm-gated; cascades to all assignments**;
  preview includes the label.
- `compass_assign_tag(tag_id, sub_legal_entity_id)` / `compass_unassign_tag(tag_id, sub_legal_entity_id)`

## 1Form

### compass_poll_one_form
`(legal_entity_id, sections, summary_only=false, updated_after, updated_before, sort_by, sort_dir, limit=5, max_pages=1)`

- No `sections` → envelope + `sections_with_data` inventory per submission (cheap
  discovery). Then re-call with `sections=[...]`.
- Sections: company_info, offices, certifications, workforce, legal, projects,
  financials, expertise, safety_personnel, emr, osha_incidents, incidents, convictions,
  hs_programs.
- Keep `limit` small — payloads are huge. Completed submissions only; no fetch-by-id.
- Reading rules: `*_currency_guessed`-only ⇒ inferred currency; `currency_tracked=false`
  ⇒ unitless; OSHA `cannot_provide_data` lists which zeros aren't real; `emr` (v3.3+) is
  only the highest-EMR state; `csi_code_list` supersedes `csi_code` (both are strings,
  not trade UUIDs); `has_*` gates are strings; percentages are mixed string/int.

## Contracts

- `compass_validate_contracts_csv(file_path)` — local pre-flight; mirrors the 7 API
  error types + flags rows where completeness would be *inferred* (omitted
  `contract_completed` + zero remaining). Run before every import; fix everything.
- `compass_import_contracts_csv(file_path, confirm)` — **confirm-gated**; validates
  first and aborts on errors; multipart field name handled internally. Cannot be read
  back or undone via the API; after any 400, transactionality is unknown — say "verify
  in the Compass UI", never "nothing was imported".
- CSV shape: required columns project_internal_id, project_name, contract_code,
  contract_name, contract_tax_identifier (FEIN, matches the company's `gst_number`).
  Emit dates as `yyyy-mm-dd` or epoch; always include `contract_completed` explicitly.
  Projects are upserted as a side effect, keyed on the GC's own `project_internal_id`.

## Reviews

### compass_poll_reviews
`(sub_legal_entity_id, legal_entity_id, updated_after, updated_before, sort_dir, limit=25, max_pages)`

- GC→sub performance reviews: 5 rated sections (14 questions, ratings are **strings**);
  server adds `sections_answered` counts and top-level `flags`
  (`would_recommend_sub`, `has_sub_liened_project` — option_yes/option_no; these two
  carry more weight than any rating).
- Empty section `{}` = unanswered, not absent. `internal_info` contract values are
  free-text strings — no arithmetic. No project filter (filter locally on
  `internal_info.project_id`); no review ids exist.
- `legal_entity_id`: admin callers only (GC callers are auto-scoped and it's ignored).

## Projects

- `compass_poll_projects(archived, legal_entity_id, updated_after, updated_before, sort_dir, limit, max_pages)` —
  `archived` is the only server-side filter. `type` values are title-case with spaces
  ("Commercial High-rise") — match verbatim. Don't derive one state field from another
  (status/active/archived/published are independent).
- `compass_resolve_projects(ids, internal_ids, force_refresh=false)` — resolves project
  UUIDs and GC internal codes from a short-TTL index; `unresolved` lists misses. Use for
  every bare `project_id` you encounter.

## Approvals

### compass_poll_approval_requests
`(id, flow_type, statuses, outcomes, approval_flow_id, sub_legal_entity_id, project_id, legal_entity_id, resolve_reviewer_names=true, updated_after, updated_before, sort_by, sort_dir, limit, max_pages)`

- `statuses` list from: awaiting_qualification | in_progress | compass |
  changes_required | complete | cancelled. `outcomes` (null until concluded): approved |
  qualified | qualified_with_exceptions | denied | push_back | submitted.
- Each `current_stage` carries a `progress` string — quote its logic, don't recount
  reviewers. Null stage → `current_stage_note` explains (awaiting qualification,
  terminal, etc.).
- `resolve_reviewer_names=true` attaches `people` (uuid → name/title/email) for all
  reviewers/requesters. `id` lookups: empty data = unknown OR inaccessible (note
  included).
- Default order is oldest-updated first (the sync recipe relies on it).

### compass_poll_approval_flows
`(flow_type, ...)` — **`flow_type` ("project" | "company") is required**; a full picture
needs both calls. Returns ordered stages (annotated with `progress`), groups, and
sub-flow tracks (finance | health_and_safety | overall). `sort_by` adds `name` here.

## Auth

- `compass_auth_status()` — mode, environment, signed-in user/legal entity
  (authorization-code mode), token expiry, `writes_enabled`, any in-progress login.
  Never token material. Call it first when requests fail with auth errors or when the
  user asks "which account is this?".
- `compass_login(open_browser=true)` — starts the interactive OAuth login (only
  meaningful in authorization-code mode); returns `login_url` for the user to open on
  the server's machine, plus instructions. Poll `compass_auth_status` for the result.
