# Compass recipes — multi-step playbooks

Each recipe encodes the correct call order and the mistakes it prevents. `LE` below means
a resolved `legal_entity_id`.

## Contents

1. [Resolve a company](#1-resolve-a-company) — the universal first step
2. [Company 360°](#2-company-360)
3. [Expiring / lapsed qualifications](#3-expiring--lapsed-qualifications)
4. [Escalation triage](#4-escalation-triage-what-needs-my-attention)
5. [Approval status report](#5-approval-status-report-where-is-x-stuck)
6. [Invite a subcontractor](#6-invite-a-subcontractor-safely)
7. [Assign a qualification](#7-assign-a-qualification-contract-limits)
8. [Contracts CSV import](#8-contracts-csv-import)
9. [Tag operations](#9-tag-operations)
10. [Incremental sync](#10-incremental-sync-high-water-mark)
11. [Find subs by trade or area](#11-find-subs-by-trade-or-work-area)

---

## 1. Resolve a company

```
compass_list_legal_entities(name="<fragment>")          # try shorter fragments if empty
→ 0 matches: retry by gst_number (tax ID) if the user has one; then report not found
→ 1 match : verify type/status look right, proceed with its id
→ many    : show name + type + status + nationality per candidate; ask the user
```
Wrong-company errors are unrecoverable downstream — every later number silently attaches
to the UUID chosen here. When the user gave a tax ID or the task is reconciliation,
prefer `gst_number` over `name`.

## 2. Company 360°

For "tell me about X" / "brief me before the meeting":

```
1. Resolve → LE
2. compass_get_legal_entity(LE, resolve_trades=true, resolve_work_locations=true)
3. compass_list_prequalifications(sub_legal_entity_id=LE)      # derived_status + limits
4. compass_list_scores(legal_entity_id=LE)                     # score_groups
5. compass_poll_reviews(sub_legal_entity_id=LE)                # flags first
6. compass_get_tag_assignments([LE]) → compass_get_tags_bulk   # labels
7. compass_get_offices_for_entity(LE) → compass_get_users      # primary office contact
8. Optional depth: compass_poll_one_form(LE) inventory → chosen sections
```
Report order: identity (name, type, status, trades) → qualification standing
(derived_status, limits + currency caveat, expiry) → Q Scores (score_groups), review
flags, lien history → relationship artifacts (tags, open workflows) → contacts.
Steps 3–7 are independent — run them in parallel where the platform allows.

## 3. Expiring / lapsed qualifications

"Whose qualification expires this quarter?" / renewal chase:

```
compass_list_prequalifications(expires_after=<now>, expires_before=<cutoff>,
                               sort_by="expires", sort_dir="asc", max_pages=10)
```
Already lapsed instead: `expires_before=<now>` (their derived_status will be EXPIRED).
Resolve each `sub_legal_entity_id` to a name before presenting. If `truncated`, say so
and continue paging — a renewal list with silent gaps causes missed renewals. Follow-up
"start renewals" → recipe 6/7 territory (writes).

## 4. Escalation triage ("what needs my attention?")

```
1. compass_list_workflows(cs_status="escalated", sort_dir="desc")
2. For each: compass_list_workflow_notes(workflow_id, type="escalation")  # the why
3. Identity: sub_legal_entity_id → resolve; if null, use invited_sub_name
4. Also check compass_list_workflows(cs_status="on_hold") and, for "awaiting my review",
   fetch recent workflows and filter review_status=="in_review" locally (no server filter)
```
Present per item: who, how long (created/updated), COMPASS's escalation note verbatim,
and whether `review_status_override` explains inaction. Escalated means COMPASS stopped
chasing — the GC owns the next move.

## 5. Approval status report ("where is X stuck / who hasn't signed?")

```
1. compass_poll_approval_requests(sub_legal_entity_id=LE, statuses=["in_progress","changes_required"])
2. Read each current_stage.progress — it already states the rule
   (one_review vs all_reviews vs groups vs sub-flow tracks vs custom_form)
3. Names come back in `people` (resolve_reviewer_names defaults on)
4. Structure questions ("what are the stages?"):
   compass_poll_approval_flows(flow_type="project") AND flow_type="company" — both calls
```
Phrase pending correctly: "needs any 1 of 5 reviewers" ≠ "5 approvals outstanding".
`custom_form` → "waiting on the subcontractor's form", not "no reviewers assigned".
Never sum sub-flow track counts with the parent's union list.

## 6. Invite a subcontractor (safely)

```
1. Resolve the company name.
   Found?  → check compass_list_workflows(sub_legal_entity_id=LE) for an open request
             (no idempotency — a duplicate invite re-notifies them)
           → compass_create_workflow(LE, project_id?, reason?, internal_note?)
   Not in Compass? → compass_invite_subcontractor(email, legal_entity_name, ..., confirm=false)
2. The tool returns a preview. Show the user the exact email address and company name,
   remind them a real person gets emailed, get an explicit yes.
3. Re-call with confirm=true and identical arguments. Report the workflow id; the new
   account starts unclaimed with sub_legal_entity_id null until they register.
```

## 7. Assign a qualification (contract limits)

The highest-stakes write on the platform.

```
1. Confirm the sub (resolve; show name + id back)
2. Gather explicitly: qualified (true/false), expires, single & aggregate limits,
   currency, exceptions text (non-empty ⇒ "Qualified with exceptions"), optional
   comment / prequal_review ("approved" for direct assignment) / remove_from_hotlist
3. compass_create_prequalification(..., confirm=false) → preview includes
   resulting_status — read every value AND the resulting status back to the user
4. On explicit yes → confirm=true. Then re-fetch compass_list_prequalifications(LE)
   and show the stored record. Note: the comment lives in notes, not on the record;
   remove_from_hotlist also closed their open qualification requests.
```
Corrections don't edit — they layer a new record; the old becomes history. Get it right
before confirming.

## 8. Contracts CSV import

```
1. compass_validate_contracts_csv(path) — fix every error; take warnings seriously:
   completed_will_be_inferred means Compass will silently mark work complete
2. Optional integrity check: FEINs should match companies —
   compass_list_legal_entities(gst_number=<fein>) for unmatched-row spot checks
   (unmatched behavior is undocumented)
3. compass_import_contracts_csv(path, confirm=false) → preview (rows, size, warnings)
   → user approves → confirm=true
4. Report: imported, N rows; cannot be verified via API — check the Compass UI.
   On a 400: quote the errors array verbatim; do NOT claim nothing was imported.
```
Never fabricate rows or "fix" financial values yourself; every change to the file goes
back to the user.

## 9. Tag operations

```
What tags does X have?   compass_get_tag_assignments([LE]) → compass_get_tags_bulk(tag_ids)
Which companies have T?  No direct endpoint: get candidates via compass_list_legal_entities
                         (state the scope), batch ids through compass_get_tag_assignments,
                         filter on tag_id — and say the sweep's coverage out loud.
Label a company          compass_list_tags → reuse or compass_create_tag(label) →
                         compass_assign_tag(tag_id, LE)
Remove a label           compass_unassign_tag(tag_id, LE)
Delete a tag             confirm-gated; cascades to every assignment; preview shows the
                         label — repeat it to the user before confirming.
```

## 10. Incremental sync (high-water mark)

For mirroring Compass into an external system. Per poll-style tool:

```
1. Sort ascending by update time (approvals default to it; others: sort_dir="asc")
2. Request updated_after=<last high-water mark> (strict bound — no overlap, no gap)
3. Page until truncated=false; new mark = max updated seen
4. Offices need BOTH compass_list_offices and compass_list_inactive_offices (deletions
   only appear in the second). Main-contact reassignment needs
   compass_poll_office_main_contacts (its clock is main_contact_updated, not updated).
```
Exception: the workflow submission-expiry bounds are inclusive — dedupe boundary rows.

## 11. Find subs by trade or work area

```
By trade: compass_list_trades(name="Electrical") → note the trade UUID(s)
          → compass_list_legal_entities(type="sub", status="active", max_pages=10+)
          → compass_get_legal_entity(id, resolve_trades=true) has the hierarchy, but
            there is NO server-side trade filter on companies — you are scanning.
            State the coverage ("checked the first N active subs") in the answer.
By area:  same scan; compare compass_get_work_locations of candidates to the target
          province/county.
```
For large tenants this is expensive — confirm scope with the user ("all 2,000 subs, or
your tagged shortlist?") before a full sweep; tagged shortlists (recipe 9) or an
external index built via recipe 10 are the scalable paths.
