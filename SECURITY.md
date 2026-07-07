# Security Policy

## Reporting a vulnerability

Please **do not** open a public GitHub issue for security problems.

Email the details to **phoenixjyb@gmail.com** with `[security]` in the
subject line. If you'd like to encrypt the report, ask for a public key in
your first message and I'll send one back.

Include whatever you have:

1. What's affected (file / route / endpoint)
2. How to reproduce (curl command or steps)
3. What an attacker could do with it
4. Your suggested fix, if any

You'll get an acknowledgement within **7 days** (best effort — this is a
small project, not a paid product). If the issue is valid we'll work on a
fix in a private branch, cut a patch release, and credit you in
`CHANGELOG.md` unless you'd rather stay anonymous.

## Supported versions

Only the latest minor line gets security patches.

| Version | Supported |
|---------|-----------|
| 0.2.x   | yes       |
| < 0.2   | no — please upgrade |

## Scope

ConvergenceKanban is a **self-hosted tool**. The deployer is responsible
for:

- Keeping `.env` (Feishu / Slack / DingTalk credentials) out of version
  control and off shared filesystems
- Putting the service behind a reverse proxy with TLS if it's exposed
  beyond `localhost`
- Restricting who can reach `/api/...` — there is no built-in
  authentication beyond the `X-Kanban-User` header (which is an identity
  hint, not an auth token)
- Backing up `data/kanban.db` — it's the single source of truth

In-scope for reports:

- Anything that lets an unauthenticated request bypass the bot-governance
  rules (mark tasks `done`, delete projects, change roles)
- SQL injection, path traversal, SSRF in the Feishu/Slack/DingTalk fetchers
- Credential leakage in logs or error responses
- XSS in the web UI

Out of scope:

- "The kanban has no login screen" — by design; deployer's responsibility
- Issues that only apply when `.env` is committed to a public repo
- Denial-of-service via unlimited request volume on a public deployment
  without a rate-limiting proxy
