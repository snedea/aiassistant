# Plan: AI Assistant with Memory

Date: 2026-03-10
Version: v1
Status: planning

## Context

Build a personal AI assistant that has persistent memory, integrates with Apple Calendar, Apple Notes, and email, and proactively notifies you about upcoming events, relevant notes, and important emails. Notifications go out via Slack (and optionally iMessage). It scans your data sources continuously and uses an LLM to surface what matters.

## Current State

Empty project directory. Starting from scratch.

## High-Level Architecture

```
┌─────────────────────────────────────────────────────┐
│                   AI Assistant Core                  │
│              (FastAPI + LLM via Ollama)              │
│                                                      │
│  ┌──────────┐  ┌──────────┐  ┌───────────────────┐  │
│  │  Memory   │  │ Scanner  │  │  Notification     │  │
│  │  Store    │  │ Service  │  │  Service           │  │
│  │ (SQLite + │  │ (Cron    │  │  (Slack, iMessage) │  │
│  │  Vector)  │  │  loops)  │  │                    │  │
│  └──────────┘  └──────────┘  └───────────────────┘  │
│        │              │                │             │
│        ▼              ▼                ▼             │
│  ┌──────────────────────────────────────────────┐   │
│  │              Data Source Adapters             │   │
│  │  ┌────────┐  ┌────────┐  ┌────────────────┐  │   │
│  │  │Calendar│  │ Notes  │  │    Email        │  │   │
│  │  │(CalDAV/│  │(Apple- │  │ (IMAP or       │  │   │
│  │  │ ICS)   │  │ Script)│  │  Apple Mail DB) │  │   │
│  │  └────────┘  └────────┘  └────────────────┘  │   │
│  └──────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────┘
```

## Data Source Integration Strategies

### Apple Calendar
- **Primary**: CalDAV protocol against iCloud (works with any CalDAV client library)
- **Fallback**: `icalBuddy` CLI tool (reads Calendar.app data directly on macOS)
- **Fallback 2**: AppleScript/osascript to query Calendar.app events
- Library: `caldav` (Python CalDAV client)

### Apple Notes
- Apple Notes has no public API. Options:
  - **Primary**: AppleScript via `osascript` -- can read note titles, bodies, folders
  - **Fallback**: Direct SQLite read from `~/Library/Group Containers/group.com.apple.notes/NoteStore.sqlite` (fragile but fast)
- Notes are synced to this SQLite DB; we parse the protobuf/gzip body

### Email
- **Primary**: IMAP (works with iCloud Mail, Gmail, any provider)
- **Fallback**: Apple Mail's local SQLite DB at `~/Library/Mail/`
- Library: `imapclient` + `email` stdlib for parsing
- For iCloud Mail IMAP: requires app-specific password

## Memory Architecture

Two-tier memory system:

1. **Structured Memory (SQLite via SQLModel)**
   - Conversation history with the user
   - Extracted facts (contacts, preferences, deadlines, commitments)
   - Source references (which email/note/event a fact came from)
   - Scan state (last-synced timestamps per source)

2. **Semantic Memory (Vector store)**
   - Embeddings of notes, emails, calendar descriptions
   - Used for RAG when answering questions or finding relevant context
   - Store: ChromaDB (file-based, no extra server) or Qdrant
   - Embeddings: `nomic-embed-text` via Ollama

## Notification Channels

### Slack (Primary)
- Slack Incoming Webhook or Slack Bot Token
- Rich message formatting (blocks, buttons)
- Can create a dedicated `#assistant` channel

### iMessage (Optional)
- macOS only: `osascript` to send via Messages.app
- Or use Shortcuts automation
- Less reliable for programmatic use, but native

## Implementation Steps

### Phase 1 -- Foundation
- [x] 1.1 Project scaffold: FastAPI app, pyproject.toml, Docker Compose, .env.example
- [x] 1.2 SQLite database schema: conversations, facts, source_items, scan_state
- [x] 1.3 Vector store setup (ChromaDB) with Ollama nomic-embed-text
- [x] 1.4 Basic LLM chat endpoint (POST /chat) with conversation memory
- [x] 1.5 Memory extraction pipeline: after each interaction, LLM extracts facts and stores them

### Phase 2 -- Data Source Adapters
- [x] 2.1 Calendar adapter: connect via CalDAV, fetch upcoming events, store in DB
- [x] 2.2 Notes adapter: AppleScript bridge to read Apple Notes, parse content
- [x] 2.3 Email adapter: IMAP connection, fetch recent emails, parse headers + body
- [x] 2.4 Embed all ingested content into vector store for semantic search
- [x] 2.5 Incremental sync: track last-synced state, only process new/changed items

### Phase 3 -- Scanner Service
- [x] 3.1 Background scheduler (APScheduler or simple asyncio loop)
- [x] 3.2 Calendar scan: every 5 min, check for events starting within configurable window
- [x] 3.3 Email scan: every 10 min, check for new unread emails, summarize important ones
- [x] 3.4 Notes scan: every 30 min, re-index changed notes
- [x] 3.5 LLM-powered triage: classify items as urgent/important/fyi/ignore

### Phase 4 -- Notifications
- [x] 4.1 Slack integration: webhook-based notifications with rich formatting
- [x] 4.2 Notification rules engine: what triggers a ping (upcoming event, urgent email, etc.)
- [x] 4.3 Quiet hours / do-not-disturb support
- [x] 4.4 iMessage integration via osascript (optional)
- [x] 4.5 Daily digest: morning summary of today's calendar, pending emails, relevant notes

### Phase 5 -- Conversational Interface
- [x] 5.1 RAG-powered Q&A: "What did John email me about last week?"
- [x] 5.2 Action commands: "Remind me about X tomorrow" (creates calendar event or fact)
- [x] 5.3 Cross-source correlation: "What's relevant to my 3pm meeting?" (pulls notes + emails)
- [x] 5.4 Slack bot interface: interact with assistant via Slack DMs (not just receive pings)

### Phase 6 -- Polish
- [x] 6.1 Web UI dashboard (React + Vite) showing memory, sources, upcoming items
- [x] 6.2 Admin controls: re-index, clear memory, manage connections
- [x] 6.3 Source health monitoring: alert if a data source stops syncing
- [x] 6.4 Rate limiting and token budget management for LLM calls

## Tech Stack

| Component       | Technology                          |
|-----------------|-------------------------------------|
| Backend         | Python 3.12+, FastAPI, SQLModel     |
| LLM             | Ollama (llama3.2 for chat)          |
| Embeddings      | Ollama (nomic-embed-text)           |
| Vector Store    | ChromaDB (file-based)               |
| Database        | SQLite                              |
| Scheduler       | APScheduler or asyncio tasks        |
| Calendar        | caldav (Python CalDAV client)       |
| Email           | imapclient                          |
| Notes           | osascript (AppleScript bridge)      |
| Notifications   | slack_sdk, osascript for iMessage   |
| Frontend        | React 19, Vite, Tailwind CSS        |
| Containerization| Docker Compose                      |

## Architecture Decisions

1. **ChromaDB over Qdrant**: Simpler for single-user -- no separate server process, just a file directory. Can swap to Qdrant later if needed.
2. **CalDAV over AppleScript for Calendar**: More reliable, works headless in Docker, supports any CalDAV server (iCloud, Google, Fastmail).
3. **AppleScript for Notes**: Only viable option. The Notes SQLite DB format is undocumented protobuf and breaks across macOS versions. AppleScript is stable.
4. **IMAP for Email**: Universal, works with any provider. App-specific password for iCloud.
5. **Ollama for LLM**: Already running in homelab. No API costs. Local and private -- important since we're processing personal email and notes.
6. **Slack as primary notification**: Rich formatting, reliable delivery, works on all devices. iMessage as optional second channel.

## Environment Variables (.env)

```bash
# LLM
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_CHAT_MODEL=llama3.2
OLLAMA_EMBED_MODEL=nomic-embed-text

# Calendar (CalDAV)
CALDAV_URL=https://caldav.icloud.com
CALDAV_USERNAME=
CALDAV_PASSWORD=        # App-specific password

# Email (IMAP)
IMAP_HOST=imap.mail.me.com
IMAP_PORT=993
IMAP_USERNAME=
IMAP_PASSWORD=           # App-specific password

# Notifications
SLACK_WEBHOOK_URL=
SLACK_BOT_TOKEN=         # Optional, for Slack bot mode

# Scanner
CALENDAR_SCAN_INTERVAL_MIN=5
EMAIL_SCAN_INTERVAL_MIN=10
NOTES_SCAN_INTERVAL_MIN=30
EVENT_ALERT_WINDOW_MIN=15

# General
DATABASE_URL=sqlite:///data/assistant.db
CHROMA_PERSIST_DIR=./data/chroma
```

## Project Structure

```
aiassistant/
├── IMPL_PLAN.md
├── docker-compose.yaml
├── Dockerfile
├── pyproject.toml
├── example.env
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI app + lifespan
│   │   ├── config.py            # Settings from env
│   │   ├── database.py          # SQLite + SQLModel setup
│   │   ├── models/
│   │   │   ├── conversation.py  # Chat history
│   │   │   ├── fact.py          # Extracted memory facts
│   │   │   ├── source_item.py   # Ingested emails/notes/events
│   │   │   └── scan_state.py    # Sync tracking
│   │   ├── routers/
│   │   │   ├── chat.py          # POST /chat
│   │   │   ├── memory.py        # GET/DELETE /memory
│   │   │   └── sources.py       # GET /sources, POST /sources/sync
│   │   ├── services/
│   │   │   ├── llm.py           # Ollama client wrapper
│   │   │   ├── memory.py        # Fact extraction + retrieval
│   │   │   ├── vectorstore.py   # ChromaDB operations
│   │   │   └── scanner.py       # Background scan orchestrator
│   │   ├── adapters/
│   │   │   ├── calendar.py      # CalDAV adapter
│   │   │   ├── notes.py         # AppleScript adapter
│   │   │   └── email.py         # IMAP adapter
│   │   └── notifications/
│   │       ├── slack.py         # Slack webhook/bot
│   │       └── imessage.py      # osascript iMessage
│   └── tests/
├── frontend/                    # Phase 6
│   ├── src/
│   └── ...
└── data/                        # SQLite + ChromaDB (gitignored)
```

## Risks & Open Questions

- **Apple Notes AppleScript**: Requires macOS with a logged-in GUI session. Won't work headless in Docker on a Linux server -- must run on the Mac itself or use a hybrid setup.
- **iCloud CalDAV auth**: Apple's CalDAV requires app-specific passwords and may need 2FA handling. Need to test connectivity early.
- **iCloud IMAP**: Same auth concerns. App-specific password required.
- **Docker vs native**: The AppleScript adapters (Notes, iMessage) can't run in Docker. Options:
  1. Run the whole backend natively on macOS (not containerized)
  2. Run backend in Docker but have a small native "bridge" service on macOS for AppleScript calls
  3. Skip Notes/iMessage in Docker and only use them when running natively
- **LLM token costs**: Scanning lots of emails burns Ollama compute. Need smart filtering (skip newsletters, only process unread, etc.)
- **Privacy**: All data stays local (Ollama + SQLite + ChromaDB). No cloud LLM calls. This is a hard requirement.

## Discovery Round 1

- [x] D1.1: Add API authentication -- all endpoints (admin, chat, memory, sources) are unauthenticated; anyone who can reach port 8000 can read personal email/calendar data or delete all memory via POST /admin/memory/clear
- [x] D1.2: Fix production deployment -- docker-compose.yaml has no frontend service and no reverse proxy; the frontend fetchApi() assumes /api prefix which only works via Vite dev proxy (vite.config.ts:13), so the dashboard cannot be used outside `npm run dev`
- [x] D1.3: Fix ephemeral LLM budget settings -- PUT /admin/llm/budget calls update_budget_settings() in llm_rate_limiter.py:146 which mutates the @lru_cache'd Settings object in-memory; changes silently revert on process restart with no indication to the user
- [x] D1.4: Reuse httpx.AsyncClient instead of creating one per LLM call -- llm.py:32 and vectorstore.py:57 each create and destroy a connection pool on every request, adding unnecessary latency and resource churn for the most frequent operations
- [x] D1.5: Fix get_upcoming_events full table scan -- calendar.py:208 loads ALL calendar events into Python then filters in a loop; should use a SQL date-range filter on a dtstart column (or at minimum filter raw_metadata in SQL) to avoid O(n) memory and CPU on every 5-minute alert check
- [x] D1.6: Sanitize AppleScript note ID interpolation in notes.py:69 -- _fetch_note_body() uses f-string interpolation of note_id directly into osascript; if a note ID ever contains a double-quote, this becomes an injection vector; should use the same _escape_applescript_string() pattern used in imessage.py
- [x] D1.7: CORS allow_origins is hardcoded to localhost:5173 only (main.py:43) -- will block frontend requests in any non-localhost deployment; should be configurable via env var

## Discovery Round 2

- [x] D2.1: Slack bot bypasses API key authentication -- slack_bot.py:30 handles DMs from any Slack workspace member with no user-level auth check; when api_key is configured, HTTP endpoints require Bearer auth but anyone who can DM the bot gets full RAG access to personal email/calendar/notes data
- [x] D2.2: Hardcoded timezone "America/Chicago" in action_commands.py:92,236 and cross_source.py:82,139,173 -- the system has a configurable timezone in the quiet hours config (daily_digest.py:24-32 reads it correctly), but reminder creation and meeting query correlation ignore it and always use America/Chicago
- [x] D2.3: Slack webhook creates a new httpx.AsyncClient per notification -- slack.py:121 uses `async with httpx.AsyncClient()` for every webhook POST; same pattern D1.4 fixed for Ollama calls; flush of held notifications after quiet hours sends multiple webhook calls in sequence, each creating and tearing down a connection pool
- [x] D2.4: daily_digest _get_todays_events() loads ALL calendar events into memory -- daily_digest.py:37-38 does `select(SourceItem).where(source_type == "calendar")` then filters in Python; D1.5 added dtstart_utc column specifically for SQL-level date filtering but this code path was not updated
- [x] D2.5: Backend service has no healthcheck in docker-compose.yaml -- frontend depends_on assistant but without condition: service_healthy; frontend container may start and serve requests before the backend is ready, causing failed API calls on initial page load

## Discovery Round 3

- [x] D3.1: Calendar alert dedup state lost on process restart -- calendar_alerter.py:22 stores _alerted_event_keys in a module-level set; on container redeploy or process restart, all keys are lost and every upcoming event within the alert window re-fires its Slack/iMessage notification; should persist alerted keys to the database
- [x] D3.2: cross_source.py find_matching_events() loads ALL calendar events into Python -- cross_source.py:63 does `select(SourceItem).where(source_type == "calendar")` with no date filter then scores in a loop; same bug class as D1.5/D2.4 but this code path was never updated to use the dtstart_utc column; gather_related_items() at line 252 also loads all notes+emails for keyword matching
- [x] D3.3: Backend Dockerfile runs as root -- Dockerfile has no USER directive; uvicorn process runs as root inside the container; should create a non-root user and switch to it before CMD
- [x] D3.4: AuthGate starts with authenticated=true -- AuthGate.tsx:5 initializes `authenticated: true`; when API_KEY is configured but localStorage has no key, all dashboard components mount and fire API calls that fail with 401 before the auth-required event switches to the login form; causes a flash of error states on first visit
- [x] D3.5: usePolling hook continues firing after 401 auth failure -- usePolling.ts:31 setInterval keeps calling the fetcher after authentication fails; the auth-required event shows the login form but polling intervals are never cleared, spamming the console and network with repeated 401 requests until the page is refreshed
- [x] D3.6: example.env missing health monitoring config vars -- config.py:48-50 defines health_check_interval_min, health_stale_multiplier, health_alert_cooldown_min with defaults but example.env does not document them; users copying example.env for first-time setup won't know these are configurable

## Discovery Round 4

- [x] D4.1: AuthGate treats non-401 errors as successful auth -- AuthGate.tsx:29-30 and :49-50 set `authenticated = true` when `getMemoryFacts()` throws any non-401 error (network timeout, 500, CORS failure); if backend is down and a stale key exists in localStorage, user sees the dashboard with all cards erroring; worse, `handleSubmit` at line 49-50 lets any entered key through when backend is unreachable
- [x] D4.2: Slack header blocks can exceed 150-char API limit -- slack.py:40 builds `:calendar: Upcoming: {title}` with no truncation on event title; Slack Block Kit header `text.text` max is 150 chars; same issue at slack.py:73 (triage) and :98 (email, partially mitigated by subject truncation at :93 but prefix can push past 150); long titles cause the webhook POST to fail silently
- [x] D4.3: PUT /notifications/quiet-hours accepts invalid timezone strings -- notifications.py:124 calls update_quiet_hours_config(); quiet_hours.py:70-71 stores the timezone to DB without validating it's a valid IANA zone; `get_local_timezone()` catches KeyError and silently falls back to America/Chicago while the config shows the invalid value; should validate with ZoneInfo() before saving
- [x] D4.4: No logout button in frontend dashboard -- DashboardLayout.tsx has no logout control; the only way to de-authenticate is to manually clear localStorage via browser devtools; should add a logout button to the header that calls clearApiKey() and dispatches auth-required
- [x] D4.5: count_held_notifications() fetches all rows to count -- quiet_hours.py:154-156 does `len(list(session.exec(stmt).all()))` instead of SQL `select(func.count()).select_from(HeldNotification)`; called on every GET /notifications/quiet-hours request; O(n) memory for a count query
- [x] D4.6: gather_related_items() keyword search loads all notes+emails from 90 days -- cross_source.py:287-291 does `select(SourceItem).where(source_type.in_(["notes", "email"]), updated_at >= cutoff)` then iterates all rows in Python for keyword matching; D3.2 fixed find_matching_events() but this second O(n) code path in the same function was not addressed; should push keyword LIKE filters into SQL
- [x] D4.7: No React error boundary -- if any dashboard card component throws during render, the entire app crashes to a white screen; should wrap each card (or the grid) in an ErrorBoundary so a single card failure degrades gracefully instead of taking down the whole UI

## Discovery Round 5

- [x] D5.1: flush_held_notifications() deletes held notification even when send fails -- quiet_hours_flusher.py:43 calls delete_held_notification() unconditionally after the try-except block; if Slack webhook is down (success=False) or an exception occurs during flush, the held notification is permanently deleted without being delivered; notifications queued during quiet hours are silently lost if the delivery channel is temporarily unavailable
- [x] D5.2: Notes stale-delete commits DB rows before vector store deletion -- notes.py:167-169 deletes SourceItem rows from SQLite and commits; lines 170-174 then attempt ChromaDB vector deletion, catching Exception on failure; if vector store delete fails, orphaned embeddings remain in ChromaDB with no corresponding DB record, polluting RAG search results with references to non-existent source items
- [x] D5.3: search_notes() loads all notes into Python then filters in a loop -- notes.py:213 does session.exec(stmt).all() with no SQL content filter, then iterates all rows checking `query_lower in item.title.lower()`; same O(n) full-scan bug class as D1.5/D2.4/D4.6 but this code path was never updated; should use SQL func.lower(SourceItem.title).contains() or LIKE filters
- [x] D5.4: get_notes() applies SQL LIMIT before Python folder filter -- notes.py:195 applies .limit(limit) in SQL, then lines 197-207 filter by folder in Python using json.loads(raw_metadata); requesting 50 notes from folder "Work" fetches 50 most-recent notes of any folder, then keeps only the "Work" ones, potentially returning far fewer than 50 even when more exist; should push folder filter into SQL or apply LIMIT after filtering
- [x] D5.5: fetchApi discards backend error response body -- api.ts:54 throws `new Error(${response.status} ${response.statusText})` without reading response JSON; FastAPI returns validation details in `{"detail": "..."}` (e.g. "Invalid timezone: 'Foo'"), but users only see "400 Bad Request"; should parse response body and include detail in the thrown error
- [x] D5.6: No fetch timeout in fetchApi -- api.ts:45 calls fetch() with no AbortController or timeout; LLM-powered endpoints (/chat, /admin/reindex, /admin/sync) can take 30+ seconds for inference; if the backend hangs, the frontend waits indefinitely with no way to cancel; should add an AbortController with a configurable timeout (e.g. 60s default, longer for LLM endpoints)

## Discovery Round 6

- [x] D6.1: search_emails() loads all emails into Python then filters in a loop -- email.py:227-235 does `session.exec(stmt).all()` with no SQL content filter, then iterates all rows checking `query_lower in item.title.lower() or query_lower in item.content.lower()`; same O(n) full-scan bug class as D5.3 (search_notes) which was fixed to use SQL LIKE filters, but search_emails() was never updated
- [x] D6.2: get_history() returns oldest N messages instead of most recent N -- conversation.py:21-23 uses `order_by(created_at.asc()).limit(50)`; for conversations longer than 50 messages (25+ user exchanges via Slack bot), the LLM receives the first 50 messages chronologically and loses the most recent context; should order by desc, limit, then reverse to get the latest N messages in chronological order
- [x] D6.3: update_budget_settings accepts negative values that disable all LLM calls -- llm_rate_limiter.py:164-181 has no input validation; setting rate_limit_rpm=-1 causes `len(timestamps) >= -1` at line 119 to always be true, blocking ALL requests; setting daily_budget=-1 causes `usage + estimated > -1` at line 134 to always be true; the user gets cryptic BudgetExceededError/RateLimitExceededError with no indication the cause is invalid settings; should validate non-negative values before saving
- [x] D6.4: Embedding failure during scanner sync leaves items permanently unindexed -- scanner.py:35-37 calls sync_fn (which commits items to DB and advances scan cursor), then calls embed_source_items; if Ollama is temporarily down, embedding fails but the scan cursor has already advanced; on the next cycle, those items are skipped (already in DB with matching hash/cursor) and never re-embedded; items exist in SQLite but not ChromaDB, invisible to semantic search until manual POST /admin/reindex

## Discovery Round 7

- [x] D7.1: sources.py sync endpoints block the FastAPI event loop -- sync_calendar (sources.py:30), sync_notes_endpoint (:77), and sync_email (:137) call blocking I/O functions (CalDAV HTTP, osascript subprocess, IMAP connection) directly in async route handlers without asyncio.to_thread(); admin.py:131 correctly wraps the same calls with asyncio.to_thread() and scanner.py:36 does the same; when a user triggers manual sync from the dashboard, the entire event loop freezes for the duration (up to 30s for Notes osascript), blocking all other API requests
- [x] D7.2: sources.py sync endpoints don't mark items as embedded after embedding -- sources.py:31, :78, :138 call embed_source_items() but don't set embedded=True on SourceItem rows afterward; admin.py:135-140 and scanner.py:46-51 both correctly mark items; items synced via /sources/sync/* get embedded into ChromaDB successfully but remain marked embedded=False in SQLite, causing the scanner to re-embed them on its next cycle and wasting LLM token budget on duplicate embedding calls
- [x] D7.3: clear_conversations() loads all rows into memory to count -- admin.py (services) line 63 does `count = len(list(session.exec(select(Conversation)).all()))` to get a row count before deletion; same O(n) bug class as D4.5 (count_held_notifications) which was fixed to use select(func.count()); for heavy Slack bot usage the conversations table can have thousands of rows loaded into Python memory just for a count
- [x] D7.4: clear_stale_alert_keys() loads all alerted events into Python to filter by date -- calendar_alerter.py:78 does session.exec(select(AlertedEvent)).all() then iterates every record comparing datetime.fromisoformat(record.dtstart) in Python; runs on every alert loop cycle (default every 5 min); should push the 24-hour cutoff into SQL since dtstart values are ISO-formatted strings that SQLite can compare lexicographically

## Discovery Round 8

- [x] D8.1: _create_caldav_event() blocks the FastAPI event loop -- action_commands.py:224 calls _create_caldav_event() synchronously from async detect_and_execute_action(); the function makes three blocking CalDAV HTTP calls (client.principal(), principal.calendars(), calendar.save_event()) without asyncio.to_thread(); same bug class as D7.1 which fixed sources.py sync endpoints but this code path was not updated; when a user creates a reminder via chat or Slack bot, the entire event loop freezes for the duration of the CalDAV round-trips
- [x] D8.2: get_facts() loads ALL active facts with no SQL LIMIT -- memory.py:122 returns list(session.exec(statement).all()) with no .limit() clause; rag.py:33 and :38 call get_facts()[:max_facts] slicing in Python after all rows are loaded; same O(n) full-scan bug class as D1.5/D2.4/D5.3/D6.1; runs on every chat message, loading potentially thousands of facts into memory to keep only 5
- [x] D8.3: clear_source_items() commits DB deletion before vector store deletion -- admin.py:93 commits the SQLite SourceItem deletion, then :94-96 attempts ChromaDB vector deletion; if Chroma deletion fails (connection error, corrupt collection), DB rows are already gone but orphaned embeddings remain in ChromaDB, polluting RAG search results; same bug pattern as D5.2 (notes stale-delete) which was fixed to delete vectors first, but this code path was not updated
- [x] D8.4: reindex_vectorstore() is not atomic -- admin.py:27-29 deletes ALL existing vectors from ChromaDB, then :35-38 re-embeds in batches of 50; if embedding fails partway (Ollama crash, budget exceeded, network timeout), the function raises and previously-deleted vectors are permanently lost; semantic search returns only partial results until the next successful full reindex; should either embed into a new collection and swap, or skip the upfront delete and use upsert
- [x] D8.5: AdminCard budget editor sends NaN as null for invalid input -- AdminCard.tsx:140-142 calls parseInt(budgetDraft.daily_budget, 10) on free-text input; non-numeric strings like "abc" produce NaN; JSON.stringify converts NaN to null; backend accepts null as "no change"; user sees "Settings saved" success message but the value was silently ignored; should validate with isNaN() and show an error before submitting
