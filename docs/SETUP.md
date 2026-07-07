# ConvergenceKanban — Setup Guide

This guide takes you from zero to a fully working ConvergenceKanban deployment,
including the optional Feishu / Lark integration.

> **Reminder:** the kanban runs fine *without* Feishu. If you're just
> trying it out, skip everything after Section 2.

---

## 1. Prerequisites

- **Docker + docker-compose** (recommended) — or Python 3.10+ and `pip`
- **A Feishu / Lark account** if you want the Bitable sync, chat bot, or
  wiki QA-ticket features (you can add this later — it's all opt-in)

## 2. Install the kanban

### Option A — one-line installer (Docker)

```bash
curl -fsSL https://raw.githubusercontent.com/phoenixjyb/convergence-kanban/main/install.sh | bash
```

This clones the repo, builds the Docker image, generates `.env` from
`.env.example`, and starts the kanban on `http://localhost:8666`.

### Option B — from source

```bash
git clone https://github.com/phoenixjyb/convergence-kanban.git
cd convergence-kanban
cp .env.example .env
python3 -m venv venv && . venv/bin/activate
pip install -r requirements.txt
python3 app.py
```

### Verify

```bash
curl http://localhost:8666/api/agent-guide?format=index
# → {"available_formats": {...}, ...}
```

Open `http://localhost:8666/` in a browser. Click the `login` button in
the top-right to create your first user.

You're done — you have a working kanban. Stop here if you don't need
Feishu integration.

---

## 3. (Optional) Enable Feishu / Lark integration

The Feishu side has three independent feature areas, all driven by the
same Feishu custom app:

| Feature | Why you'd want it |
|---------|-------------------|
| **Bitable two-way sync** | Lets your team see + edit the kanban from Feishu Bitable instead of the web UI |
| **Chat bot** | `@bot my tasks`, `@bot bugs`, etc. in your team's Feishu group |
| **Wiki QA tickets** | Agents auto-create test/data-collection requests as wiki pages under your QA team's existing wiki |

You can enable any subset.

### 3.1 Create a Feishu custom app

1. Go to https://open.feishu.cn/app (or your Lark tenant's equivalent)
2. Click **Create Custom App**, give it any name (e.g. "MyTeam Kanban Bot")
3. After creation, on the app's home page note down:
   - **App ID** (looks like `cli_xxxxxxxxxxxxxxxx`)
   - **App Secret** (long random string)
4. Paste them into `.env`:
   ```bash
   FEISHU_APP_ID=cli_xxxxxxxxxxxxxxxx
   FEISHU_APP_SECRET=...
   ```

### 3.2 Enable required scopes

In the app's **Permissions** panel, search for and enable the scopes you
need. Pay attention to the **identity column** — most scopes have
separate `tenant_access_token` (application identity) and `user_access_token`
(user identity) entries. ConvergenceKanban uses `tenant_access_token`, so make
sure each scope is enabled for **应用身份 / Application identity**.

**For Bitable sync (`feishu_sync.py`):**
- `bitable:app` — read + write multidimensional tables

**For the chat bot (`feishu_bot.py`):**
- `im:message` — receive and send chat messages
- `im:message.group_at_msg` — receive @-mentions
- `im:resource` and `im:resource:upload` — upload files (for sending
  attachments / docs from bot)
- `contact:user.id:readonly` — resolve `open_id` to user names

**For wiki QA tickets (`feishu_docs.py`):**
- `wiki:wiki` — read + write knowledge base
- `docx:document` — read + write new-format documents
- `docx:document:create` — create new documents
- `sheets:spreadsheet` — read + write embedded spreadsheets
- `drive:drive` — copy files in cloud drive (required for the wiki-node
  copy operation that instantiates a ticket from a template)

**For webhook notifications (`feishu_notify.py`):**
- No scopes needed — webhooks use a separate group-bot URL (see 3.6)

After enabling scopes, **create a new version** of the app via
**Version Management & Publishing → Create Version**, fill in a brief
description, and submit. If your tenant requires admin approval, an
admin needs to approve before the scope is actually active.

### 3.3 Set up the chat bot (optional)

In the app config:
1. **Features → Bot** — enable bot capability, give it a display name and
   avatar
2. **Event Subscriptions** — choose **Long Polling** mode (the bot connects
   to Feishu via WebSocket; no public-internet inbound traffic required)
3. **Subscribe to events** — enable `im.message.receive_v1`
4. Add the bot to your team's Feishu chat group (in the group, click
   "Manage Members" → add the app by name)

If you set encryption / verification, also fill into `.env`:
```bash
FEISHU_ENCRYPT_KEY=...
FEISHU_VERIFICATION_TOKEN=...
```

### 3.4 Set up the Bitable + sync (optional)

The sync's exact behavior depends on which Bitable schema you use.
ConvergenceKanban includes `feishu_migrate.py` which creates a default schema
matching the kanban's data model. Run it once after configuring `.env`:

```bash
python3 feishu_migrate.py
```

This creates the Bitable app with the right tables (projects, tasks, bugs,
etc.). Subsequent sync cycles keep the two sides in sync.

Optional: bug auto-routing. If your Bitable has a "feature" / 功能 field
that should auto-map to a kanban project, create
`config/feature_to_project.json`:

```json
{
  "Navigation": "<project-id-1>",
  "Localization": "<project-id-2>"
}
```

Use `config/feature_to_project.example.json` as a starting template.

### 3.5 Set up wiki QA tickets (optional)

This feature lets agents call `POST /api/qa-tickets` to create a wiki
page under your existing QA team's wiki, populated from an embedded
sheet template.

You need three values from Feishu:

| Env var | What |
|---------|------|
| `KANBAN_QA_WIKI_SPACE_ID` | The wiki space (numeric) where tickets live |
| `KANBAN_QA_WIKI_PARENT_NODE` | The wiki page (node_token) that new tickets are created under |
| `KANBAN_QA_WIKI_TEMPLATE_NODE` | The node_token of the empty template doc that gets copied for each ticket |
| `KANBAN_QA_WIKI_SUBDOMAIN` | Your tenant's Feishu subdomain (e.g. `yourorg.feishu.cn`) |

**How to find them:**

1. Open the wiki sub-page where you want tickets to go in your browser.
   URL looks like:
   `https://yourorg.feishu.cn/wiki/Xxxxxxxxxxxxxxxxxx`
   - `yourorg.feishu.cn` → `KANBAN_QA_WIKI_SUBDOMAIN`
   - `Xxxxxxxxxxxxxxxxxx` → `KANBAN_QA_WIKI_PARENT_NODE`

2. Get the **space ID** via the API (after Feishu auth is configured):
   ```bash
   curl -X GET "https://open.feishu.cn/open-apis/wiki/v2/spaces/get_node?token=Xxxxxxxxxxxxxxxxxx" \
     -H "Authorization: Bearer YOUR_TENANT_TOKEN"
   ```
   The response includes `space_id` and `obj_token`.

3. Create your template doc by hand:
   - In the same wiki space, create a new doc (use the type your team
     uses — usually `docx`)
   - Embed an empty spreadsheet with the schema you want (rows are
     populated by the API)
   - Note the doc's `node_token` from its URL → `KANBAN_QA_WIKI_TEMPLATE_NODE`

4. **Share the wiki space with the bot.** Even with all scopes enabled,
   the bot's `tenant_access_token` needs to be added as a member of the
   wiki space (or each individual doc must be shared with it):
   - Open the wiki space settings → **Members**
   - Add your custom app as a member with **Read & Edit** permission

5. Fill into `.env`:
   ```bash
   KANBAN_QA_WIKI_SPACE_ID=7524221xxxxxxxxxxx
   KANBAN_QA_WIKI_PARENT_NODE=Xxxxxxxxxxxxxxxxxx
   KANBAN_QA_WIKI_TEMPLATE_NODE=Yyyyyyyyyyyyyyyyyy
   KANBAN_QA_WIKI_SUBDOMAIN=yourorg.feishu.cn
   ```

If any of these are blank, `POST /api/qa-tickets` returns HTTP 503 with
a hint instead of erroring.

### 3.6 Set up webhook notifications (optional)

In your team's Feishu group:
1. Group settings → **Bots** → **Add Bot** → **Custom Bot**
2. Note the **Webhook URL** it generates (`https://open.feishu.cn/open-apis/bot/v2/hook/...`)
3. Paste into `.env`:
   ```bash
   FEISHU_WEBHOOK_URL=https://open.feishu.cn/open-apis/bot/v2/hook/...
   ```

This is separate from the custom app — it just lets the kanban POST
cards to the group when bugs/blockers/tasks change.

### 3.7 Run the Feishu services

```bash
docker compose --profile feishu up -d
```

This starts:
- `convergencekanban` (the core kanban)
- `convergencekanban-sync` (Bitable bidirectional sync, 30s cycle)
- `convergencekanban-bot` (chat bot WebSocket connection)

Or from source:
```bash
python3 feishu_sync.py &
python3 feishu_bot.py &
```

Verify the sync is working:
```bash
docker compose logs -f sync
# → look for "Feishu Sync starting" and per-cycle "Sync: ..." lines
```

---

## 4. (Optional) Enable Slack notifications

Bug/blocker/task events post to a Slack channel of your choice. Pure
outbound — no Slack app install needed, no permission scopes, no OAuth.

1. Open https://api.slack.com/messaging/webhooks
2. Click **Create a Slack app** → **From scratch** → name it (e.g.
   `ConvergenceKanban`) → choose your workspace
3. Under **Incoming Webhooks**, toggle on, click **Add New Webhook**
4. Pick the channel → click **Allow** → copy the webhook URL
5. Paste into `.env`:
   ```bash
   SLACK_WEBHOOK_URL=https://hooks.slack.com/services/<TEAM_ID>/<CHANNEL_ID>/<WEBHOOK_TOKEN>
   ```
6. Restart the kanban (Docker: `docker compose restart kanban`)

Test:
```bash
curl -X POST http://localhost:8666/api/bugs \
  -H 'Content-Type: application/json' -H 'X-Kanban-User: <your-name>' \
  -d '{"title":"Slack notify smoke test","severity":"low"}'
# → Slack channel gets a card within ~5 seconds (5s debounce)
```

Slack and Feishu notifications fire independently — having one enabled
doesn't disable the other.

---

## 5. (Optional) Enable DingTalk / 钉钉 notifications

Same shape as Slack — a custom group robot webhook.

1. In the DingTalk group → top-right ⚙ → **群助手 / Group Assistant**
2. **添加机器人 / Add Robot** → **自定义 / Custom** → set name + icon
3. **安全设置 / Security**: pick at least one option:
   - **加签 / HMAC-SHA256 signature** (most secure — copy the secret)
   - IP whitelist
   - Keyword (e.g. require the word "kanban" in every message — note
     this requires editing `dingtalk_notify.py` to include the keyword)
4. **完成 / Done** → copy the Webhook URL
5. Paste into `.env`:
   ```bash
   DINGTALK_WEBHOOK_URL=https://oapi.dingtalk.com/robot/send?access_token=XXXX...
   DINGTALK_WEBHOOK_SECRET=SECxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
   ```
   (Leave `DINGTALK_WEBHOOK_SECRET` blank if you chose IP whitelist
   instead of signature.)
6. Restart the kanban.

DingTalk, Slack, and Feishu fire in parallel — enable any combination.

---

## 6. Register users

Out of the box the kanban has no users. Click the `login` button in the
web UI to create the first one (it'll be human role, no governance
restrictions).

For AI agents, create them as `role: bot`:

```bash
curl -X POST http://localhost:8666/api/users \
  -H 'Content-Type: application/json' \
  -H 'X-Kanban-User: <your-admin-name>' \
  -d '{"name":"alice-claude","display_name":"[Bot] alice-claude","role":"bot"}'
```

Use the `{firstname}-{tool}` naming pattern so activity logs are readable.

## 7. Point your AI agents at the kanban

In each project repo that uses an AI agent, add a one-liner to
`CLAUDE.md` / `AGENTS.md`:

```markdown
ConvergenceKanban API guide: http://YOUR_HOST:8666/api/agent-guide
```

That's all your agents need. They'll fetch the live guide on each
session and follow it.

[→ Full agent integration walkthrough](AGENT_INSTRUCTIONS.md)

---

## 8. Backups

The DB is at `data/kanban.db`. Back it up with:

```bash
python3 scripts/backup_db.py
# → writes data/backups/kanban-<timestamp>.db
```

Or, with Docker:

```bash
docker compose exec kanban python3 scripts/backup_db.py
```

The provided `scripts/run_recurring.py` shows the cron pattern if you
want automated daily backups.

## 9. Updating

```bash
git pull
docker compose build
docker compose up -d           # restarts with the new image
```

Migrations run automatically on startup (see `db.py`). The status-flow
changes are forward-compatible — existing data is preserved.

## 10. Troubleshooting

| Symptom | Likely cause |
|---------|--------------|
| `401 Unknown user 'X'` | The user `X` isn't in the kanban's users table; register them first |
| Feishu sync silently doing nothing | `FEISHU_APP_ID` or `FEISHU_APP_SECRET` not set; check `docker compose logs sync` |
| `99991672 Access denied — scope X required` | The scope wasn't enabled, or the app wasn't republished after enabling. Re-check Section 3.2 |
| `99991672` even though scope shows "已开通 / Granted" | Check the **identity column** in the permissions page — the scope is probably only granted for `user_access_token`, not `tenant_access_token`. Both must be enabled for bot operations. |
| `131005 node not found` when deleting a wiki node | The bot isn't a member of the wiki space. Add it as a member (Section 3.5 step 4). |
| `POST /api/qa-tickets` returns 503 | One of the `KANBAN_QA_WIKI_*` env vars is blank. See Section 3.5. |
| Bug created in kanban but doesn't appear in Bitable | Wait 30s for next sync cycle, or check `docker compose logs sync` for errors. |

If you hit something not covered here, open an issue.
