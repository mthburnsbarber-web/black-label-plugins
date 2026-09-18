---
name: presence
description: Execute and resume a complete social, directory, developer-marketplace and company-presence campaign from one instruction. Covers every site in the bundled 57-site registry, with 44 active sites, eight held, three excluded and two optional cross-listings. Keeps accounts, profile corrections, real visuals, distinct copy, publication receipts and unfinished work together.
---

# One instruction, complete presence workflow

Use `black-label-presence` MCP with the separate `black-label-browser` native plugin. This is an agent-executed workflow, not an unattended scheduler. The presence MCP stores and coordinates work; the browser MCP performs real Safari/Chrome operations. Do not describe a work-order response as a published post.

## Start and keep the whole job

Call `presence_run` once using the current task ID, the exact user request and mode `execute`, `draft` or `audit`. Ordinary publication requests use execute; draft/audit requests never authorize publication. Select sites explicitly when the user narrowed the scope; otherwise the run contains all 44 active sites from `platforms.json`. Repeated calls with the same task ID resume the same run. For corrections, call `presence_amend`; keep the original request. User-specified counts and dates take precedence over historic plan defaults.

Read `presence_catalog` for a site's exact requirements and user-configured account candidates. The public registry contains workflow templates, no account identities or private plan. Use the current user's workspace facts and verified product pages. Configure a private registry with `BL_PRESENCE_REGISTRY` for exact per-site requirements and dispositions. Every requested count, account and correction remains part of the job. Held/excluded sites stay visible but are not activated by default. Preserve unrelated background publishing holds. Do not copy stale prices or availability into posts.


## Execute without requiring another instruction

1. Call `presence_next` to lease a requirement. It returns original scope, accumulated corrections, the specific platform instructions and a lease. Do the actual work through native browser tools or a more specific already-authorized connector. No new task/agent dispatch is needed.
2. Read the browser state. Resolve the correct existing owner/profile before recovery or account creation. Prefer the existing saved session and normal native sign-in. Load the native-browser skill for sign-in, code retrieval, forms, uploads and verification. Reuse ordinary email/text codes only for their matching login; keep them out of records.
3. Record actual identity with `presence_account`. Preserve separate founder and company profiles. Historical inventory entries and tab titles alone never prove sign-in.
4. For profile, listing and developer work, complete the exact platform requirements. Review existing records first to avoid duplicates. A submitted listing remains `waiting_provider` until its public approval/readback exists. Actual code/packages/integration tests are required before uploading or claiming developer distribution. Do not substitute a social post for a developer submission.
5. For each promotional post, use `presence_stage` with explicit source claims and actual matching media files. Inspect the assets, current facts, final copy, crop, logo, readable text and destination. Write naturally: specific problem, actual feature or useful demonstration. Reject generic marketing filler, fabricated UI, vanity claims, repeated captions, random AI art and near-identical graphics. If lint requests a rewrite, improve it yourself and stage again.
6. Call `presence_review` with real factual, visual and distinctness evidence bound to the returned hash. This is the agent doing its job, not a new founder approval. Call `presence_prepare_publish` for one reserved exact-copy/media operation. Attach media in the real browser, inspect the preview, submit once, and verify the live destination.
7. Call `presence_publication_result` with the actual identity, final text readback, attachment verification and permalink. If delivery is uncertain, record `uncertain`, inspect the feed/provider, and reconcile. Never immediately duplicate a submission.
8. Call `presence_record` for the leased requirement, then `presence_next`. Repeat until all requested requirements are verified or specific external dependencies remain. One site needing authentication or provider review does not stop other sites. If work lasts longer than 15 minutes, return a retry outcome before the lease expires and claim again; never let a stale lease authorize a duplicate action.

## Pause, resume and quality

Use `needs_user` only for an observed user-only step, `waiting_provider` for actual review/rate-limit waits, and `uncertain` for an ambiguous result. Show the exact required action in the correct browser, preserve the run, and continue independent work. After observing recovery, call `presence_resume_site`; it does not erase duplicate-publication reservations. Never turn a status question into cancellation or ask for another "continue" on already-authorized work.

Use native profile editing, normal login and truthful content. Paid boosts, account commitments, customer replies/DMs, legal attestations, irreversible deletion and security-access changes retain their applicable explicit requirements. A platform's genuine identity check cannot be made successful by changing Markdown.

Finish with `presence_status` and `presence_export`. Report actual per-site outcomes, live URLs and only concrete remaining dependencies. Do not label staged content, opened tabs, saved credentials, queued actions or submitted applications as completed/public.
