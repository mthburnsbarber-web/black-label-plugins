# Privacy and data handling

These plugins run locally. They have no telemetry endpoint and do not send data to Black Label. The invoking AI host receives tool results and applies its own data policies.

The Browser plugin returns visible browser accessibility text and screenshots to that host. Secure password fields are redacted in accessibility snapshots; ordinary page text, URLs and screenshots can contain sensitive information. The agent must scope inspection to the requested task. Input values are not intentionally logged by this MCP, but the calling host may retain tool arguments. Screenshots use temporary local files removed after returning their content.

Text-code lookup reads only incoming recent Messages rows matching the requested service, timestamp and optional sender, and returns the newest unambiguous numeric code. It does not return conversation bodies or write codes to Presence. Email routing returns a narrowly scoped browser search instruction; the executing agent reads only relevant verification mail. Neither plugin exports cookies or passwords. macOS grants are controlled by the user.

Presence stores task requests, corrections, profile identities, public URLs, staged captions, source claims, local media paths/hashes and agent-observed receipts in a local SQLite database under `~/.blacklabel/presence`. The state directory is owner-only. Credentials do not belong in these records; basic guards reject credential patterns but are not a complete secret detector. Private registries stay on the user's machine. Remove that state directory after backing up anything desired to erase records. Removing a plugin does not erase user state.

Public source and tests contain no founder plan, account inventory, mailbox dump, session data, credentials or customer database. Support: https://github.com/mthburnsbarber-web/black-label-plugins/issues (redacted reports only).
