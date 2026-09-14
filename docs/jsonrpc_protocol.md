# Johnston Daemon JSON-RPC 2.0 Protocol Specification

Version: **1.0** · Status: **Draft (2026-09-14)**

Single source of truth for the wire protocol between Johnston frontends (Textual
TUI, CLI, Node/Ink) and the daemon (`johnston serve`). A Node/Ink client and the
Python daemon can be implemented independently from this document alone, without
reading Johnston source. The daemon hosts the core facade (`JohnstonClient`,
`src/johnston/core/client.py`) as a JSON-RPC 2.0 service; method names, params,
result shapes and event payloads map 1:1 onto the typed DTOs in
`src/johnston/core/dto/`.

---

## 1. Transport

- **Transport & framing**: the client spawns the daemon (`johnston serve`) and
  owns its stdin/stdout. One JSON object per line (JSON Lines, no embedded
  newlines; `\n`/`\r`/`\t` inside strings are escaped). UTF-8. stderr is daemon
  logs only — never protocol messages. Every message is flushed after writing.
- **Envelope**: every message has `jsonrpc:"2.0"`. Requests carry an `id`
  (number or string, never `null`); **notifications carry no `id`**; responses
  echo the request `id`. `params` is an object; may be omitted when empty.
- Success: `{"jsonrpc":"2.0","id":1,"result":{...}}`; failure:
  `{"jsonrpc":"2.0","id":1,"error":{"code":-32601,"message":"...","data":{...}}}`
  — `result`/`error` mutually exclusive, exactly one present.
- **Timeout**: client-enforced, default 120 s (600 s for `prompt.*`/`compact`).
  On timeout treat the daemon as wedged: close stdin, kill the process. Never
  re-send a request whose response may still arrive (double side effects).
- **Disconnect**: on stdin EOF the daemon aborts in-flight turns, persists
  sessions, exits 0. Client treats process exit without a response for id N as
  an error for request N.

---

## 2. Methods

Conventions: lists are wrapped (`{"result":{"sessions":[...]}}`, never a bare
array); timestamps are Unix epoch seconds (float); a `session_id` param scopes
the operation (omit = connection's active session, §6); unknown params members
are ignored (§7). JSON field names are exactly the DTO dataclass field names.
Each method below: *params → result* — *backing facade call*.

| Group | Methods |
| --- | --- |
| `session.*` | `list`, `create`, `resume`, `delete`, `export` |
| `prompt.*` | `stream`, `prompt` |
| — | `compact` |
| `rewind.*` | `points` |
| `provider.*` | `list` |
| `model.*` | `info`, `estimate_cost` |
| `rules.*` | `list` |
| `skills.*` | `list`, `toggle` |
| `workspace.*` | `roots`, `add`, `remove` |
| `worktree.*` | `list`, `create` |
| `config.*` | `get`, `set` |
| `task.*` | `list`, `kill` |
| `sandbox` | `toggle`, `state` |
| `daemon.*` | `info`, `shutdown` (notification) |
| `interaction.*` | `resolve` (§4.3) |

### 2.1 `session.list`

`{}` → `{"result":{"sessions":[{"id":"s-7f3a","title":"Fix the parser","created_at":1726000000.0,"updated_at":1726000123.0,"message_count":12,"token_count":48213}]}}`
— `get_sessions()` → `list[SessionSummaryDTO]` (`id`, `title`, `created_at`,
`updated_at`, `message_count`, `token_count`).

### 2.2 `session.create`

`{"title":"Optional","role":"worker"}` (both optional; daemon generates id/title
when omitted; new session becomes active) →
`{"result":{"session":{"id":"s-9b21","title":"Optional","created_at":1726000200.0,"updated_at":1726000200.0,"messages":[]}}}`
— `SessionStore.create_main()` + `get_session()` → `SessionDTO` (`id`, `title`,
`created_at`, `updated_at`, `messages`).

### 2.3 `session.resume`

`{"session_id":"s-7f3a"}` → `{"result":{"session":{SessionDTO per §2.2}}}`;
each message (`MessageDTO`) has `role`, `content`, `timestamp`, `tool_calls`,
`attachments`. Session becomes active. Unknown id → error `kind:"not_found"`
(§5). — `get_session(session_id)`.

### 2.4 `session.delete`

`{"session_id":"s-7f3a"}` → `{"result":{"deleted":true}}`
— `SessionStore.delete(session_id)` (main sessions only; subagents cascade).

### 2.5 `session.export`

`{"session_id":"s-7f3a","format":"json"}` (`format`: `"json"` default |
`"jsonl"`) → `{"result":{"session_id":"s-7f3a","format":"json","data":{...}}}`
— planned facade export. Clients must tolerate `method_not_found` until it
lands (§7).

### 2.6 `prompt.stream`

Starts a streaming turn: the daemon emits `event` notifications (§4) in yield
order, then exactly one terminal `turn_completed` event (or a `fatal` `error`
event), then responds.

`{"prompt":"<text>","attachments":[],"session_id":"s-9b21"}` (only `prompt`
required) → `{"result":{"session_id":"s-9b21","text":"","duration_s":8.23,
"usage":{"tokens_input":1200,"tokens_output":340,"total_tokens":1540,"cost_usd":0.0012},"tool_calls":[]}}`

— `stream(prompt, attachments)`; every `StreamEventDTO` yielded is forwarded
untouched as an `event` notification. Result mirrors `TurnCompletedDTO`
(`duration_s`, `usage`, `text`, `tool_calls`).

### 2.7 `prompt.prompt` (non-streaming)

Params as §2.6 → same result shape with accumulated `text`/`tool_calls`
— `prompt(prompt, attachments)` → one `TurnCompletedDTO`.

### 2.8 `compact`

`{"session_id":"s-9b21"}` (optional) →
`{"result":{"success":true,"tokens_before":24000,"tokens_after":3200,"summary":"Compacted transcript","error":null}}`
— `compact()` → `CompactionResultDTO` (`success`, `tokens_before`,
`tokens_after`, `summary`, `error`). A failed compaction returns
`success:false` + `error` set — not an RPC error.

### 2.9 `rewind.points`

`{"session_id":"s-9b21"}` (optional) →
`{"result":{"points":[{"index":0,"text":"Fix the parser","insertions":12,"deletions":3,"changed_files":["src/parser.py"],"is_checkpoint_available":true,"git_stats":"+12 / -3"}]}}`
— `get_rewind_points()` → `list[RewindPointDTO]` (`index`, `text`,
`insertions`, `deletions`, `changed_files` tuple→array,
`is_checkpoint_available`, `git_stats`).

### 2.10 `provider.list`

`{}` → `{"result":{"providers":[{"name":"Anthropic","is_configured":true,"key":"anthropic","is_active":true,"is_disabled":false,"models":[{"name":"claude-sonnet-4-5","display_name":"Claude Sonnet 4.5","provider":"anthropic","context_window":200000,"supports_vision":true,"supports_thinking":true}]}]}}`
— `get_providers()` → `list[ProviderDTO]` (`name`, `is_configured`, `models`,
`key`, `is_active`, `is_disabled`); models = `ModelInfoDTO` (`name`,
`display_name`, `provider`, `context_window`, `supports_vision`,
`supports_thinking`).

### 2.11 `model.info`

`{"provider_key":"anthropic","model_name":"claude-sonnet-4-5"}` →
`{"result":{ModelInfoDTO per §2.10}}` — `get_model_info(provider_key, model_name)`.

### 2.12 `model.estimate_cost`

`{"provider_key":"anthropic","model_name":"claude-sonnet-4-5","total_tokens":1540}`
→ `{"result":{"cost_usd":0.0012}}` — `estimate_cost(provider_key, model_name, total_tokens)`.

### 2.13 `rules.list`

`{}` → `{"result":{"rules":[{"title":"Repository Guidelines","path":"/abs/AGENTS.md","content_preview":"Johnston: Python terminal AI assistant…","scope":"project"}]}}`
— `get_rules()` → `list[RuleDTO]` (`title`, `path`, `content_preview`, `scope`).

### 2.14 `skills.list`

`{}` → `{"result":{"skills":[{"name":"review","description":"Autonomous defect-first review-fix loop.","path":"…/review/SKILL.md","enabled":true,"is_project":false,"scope":"global"}]}}`
— `get_skills()` → `list[SkillDTO]` (`name`, `description`, `path`, `enabled`,
`is_project`, `scope`).

### 2.15 `skills.toggle`

`{"name":"review"}` → `{"result":{"enabled":true}}` — the **new** state (`!old`;
backing `toggle_skill(name)` returns the new hidden state, inverted to
`enabled`). Unknown skill → `not_found`.

### 2.16 `workspace.roots`

`{}` → `{"result":{"roots":[{"path":"/abs/project","scope":"session"}]}}`
— `get_workspace_roots()` → `list[WorkspaceRootDTO]` (`path`, `scope`).

### 2.17 `workspace.add`

`{"path":"/abs/project","scope":"session"}` → `{"result":{"added":true}}`
— `add_workspace_root(path, scope)`.

### 2.18 `workspace.remove`

`{"path":"/abs/project"}` → `{"result":{"removed":true}}` (boolean)
— `remove_workspace_root(path)`.

### 2.19 `worktree.list`

`{"project_dir":"/abs/project"}` (optional; defaults to daemon project dir) →
`{"result":{"worktrees":[{"name":"main","is_current":true,"is_worktree":false,"is_root":true,"path":"/abs/project"}]}}`
— `list_worktrees(project_dir)` → `list[WorktreeDTO]` (`name`, `is_current`,
`is_worktree`, `is_root`, `path`).

### 2.20 `worktree.create`

`{"project_dir":"/abs/project","branch_name":"fix/parser","base_branch":"main"}`
→ `{"result":{"path":"/abs/project-wt","branch":"fix/parser"}}`; either member
may be `null` on failure — `create_worktree(project_dir, branch_name, base_branch)`
→ `tuple[str|None, str|None]`.

### 2.21 `config.get`

`{"key":"sandbox_enabled"}` → `{"result":{"key":"sandbox_enabled","value":false}}`.
Supported keys are daemon-defined (sandbox state, thinking effort,
provider/model, workspace roots, …); unknown key → `not_found`.

### 2.22 `config.set`

`{"key":"sandbox_enabled","value":true}` → `{"result":{"updated":true}}`
— settings/provider accessors behind the facade (`set_thinking_effort`,
`toggle_sandbox`, …). Effects visible in later `config.get`, `sandbox.state`,
`provider.list` responses.

### 2.23 `task.list`

`{"kind":"shell","session_id":"s-9b21"}` (both optional) →
`{"result":{"tasks":[{"task_id":"t-1","command":"pytest -n auto","status":"RUNNING","returncode":null,"log_path":"/tmp/johnston/t-1.log","is_running":true,"created_at":1726000300.0,"progress_badge":"running..."}]}}`
— `get_tasks(kind, session_id)` → `list[TaskDTO]` (`task_id`, `command`,
`status` — `"RUNNING"`/`"FINISHED"`, `returncode`, `log_path`, `is_running`,
`created_at`, `progress_badge`).

### 2.24 `task.kill`

`{"task_id":"t-1"}` → `{"result":{"killed":true}}` (boolean; `false` if already
finished/unknown) — `kill_task(task_id)`.

### 2.25 `sandbox.toggle`

`{}` → `{"result":{"sandbox_enabled":true}}` — the **new** state
— `toggle_sandbox()`.

### 2.26 `sandbox.state`

`{}` → `{"result":{"sandbox_enabled":false}}` — daemon's current sandbox flag.

### 2.27 `daemon.info`

`{}` → `{"result":{"protocol_version":"1.0","implementation":"johnston-daemon","pid":81234,"cwd":"/Users/me/project"}}`.

### 2.28 `daemon.shutdown` (client notification)

No `id`, no response. Daemon persists sessions and exits:

`{"jsonrpc":"2.0","method":"daemon.shutdown"}`

---

## 3. Sessions

A connection auto-creates an active main session on the first `prompt.*`/
`compact`/`rewind.points` call without `session_id` (mirrors
`JohnstonClient.__init__`). `session.create`/`session.resume` replace it.

---

## 4. Events (server → client notifications)

Streaming turns and interleaved interactions arrive as notifications:

`{"jsonrpc":"2.0","method":"event","params":{"type":"<event_type>","data":{...}}}`

`data` members are exactly the dataclass fields of the corresponding
`StreamEventDTO` subclass — same names, JSON types; never added/renamed/dropped.

### 4.1 Type table

| `type` | `data` members (DTO) | Notes |
| --- | --- | --- |
| `content_delta` | `text: str`, `is_reset: bool`, `final: bool` (`ContentDeltaDTO`) | `is_reset:true` clears rendered buffer; `final:true` = last text event |
| `thinking_delta` | `thought: str`, `duration: float`, `phase: str` (`ThinkingDeltaDTO`) | `phase` ∈ `start`\|`delta`\|`end` |
| `tool_call` | `tool_name: str`, `args: object`, `call_id: str`, `target: str`, `status: str`, `index: int\|null` (`ToolCallDTO`) | status starts `running` (or `generating`/`generating_update`); `index` may be null |
| `tool_result` | `tool_name: str`, `content: str`, `is_error: bool`, `status: str`, `returncode: int\|null`, `call_id: str` (`ToolResultDTO`) | correlate with `tool_call.call_id` |
| `compaction` | `summary: str` (`CompactionEventDTO`) | compaction divider in stream |
| `turn_completed` | `duration_s: float`, `usage: object`, `text: str`, `tool_calls: array` (`TurnCompletedDTO`) | **terminal** event of every `prompt.stream`; `usage` keys: `tokens_input`, `tokens_output`, `total_tokens`, `cost_usd` |
| `error` | `message: str`, `fatal: bool` (`ErrorEventDTO`) | `fatal:true` aborts the turn; no `turn_completed` follows |
| `queued_user_message` | `prompt: str`, `attachments: array`, `show_in_ui: bool`, `display_text: str` (`QueuedUserMessageDTO`) | prompt queued while a turn was active |
| `retry` | `attempt: int`, `max_retries: int`, `delay: float`, `error: str` (`RetryEventDTO`) | transient failure; daemon retrying |
| `permission_request` | `tool_name: str`, `args: object`, `risk_level: str`, `reason: str` (`PermissionRequestDTO`) | mid-turn permission prompt (§4.3) |
| `ask_user` | `questions: array` (daemon-defined) | `HostProtocol.ask_user` analog (§4.3) |

The first nine originate from `JohnstonClient.stream()` yields (parsed by
`parse_event_dto`); `permission_request`/`ask_user` are daemon-managed.

### 4.2 Example streamed turn

Request:

```json
{"jsonrpc": "2.0", "id": 7, "method": "prompt.stream", "params": {"prompt": "What files changed?", "session_id": "s-9b21"}}
```

Notifications, strictly in this order:

```json
{"jsonrpc": "2.0", "method": "event", "params": {"type": "content_delta", "data": {"text": "Three files changed:", "is_reset": false, "final": false}}}
{"jsonrpc": "2.0", "method": "event", "params": {"type": "tool_call", "data": {"tool_name": "bash", "args": {"command": "git status"}, "call_id": "call_1", "target": "", "status": "running", "index": 0}}}
{"jsonrpc": "2.0", "method": "event", "params": {"type": "tool_result", "data": {"tool_name": "bash", "content": "M src/parser.py", "is_error": false, "status": "done", "returncode": 0, "call_id": "call_1"}}}
{"jsonrpc": "2.0", "method": "event", "params": {"type": "content_delta", "data": {"text": "  - src/parser.py", "is_reset": false, "final": true}}}
{"jsonrpc": "2.0", "method": "event", "params": {"type": "turn_completed", "data": {"duration_s": 8.23, "usage": {"tokens_input": 1200, "tokens_output": 340, "total_tokens": 1540, "cost_usd": 0.0012}, "text": "Three files changed:\n  - src/parser.py", "tool_calls": []}}}
```

Then the response to id 7:

```json
{"jsonrpc": "2.0", "id": 7, "result": {"session_id": "s-9b21", "text": "Three files changed:\n  - src/parser.py", "duration_s": 8.23, "usage": {"tokens_input": 1200, "tokens_output": 340, "total_tokens": 1540, "cost_usd": 0.0012}, "tool_calls": []}}
```

### 4.3 Permission flow (round-trip)

Tool permission checks (`HostProtocol.confirm_permission`) and user questions
(`HostProtocol.ask_user`) block the turn. Because JSON-RPC cannot interleave a
response inside an in-flight request, the daemon suspends the turn, emits an
`event` notification (`permission_request` or `ask_user`), waits for a client→
server `interaction.resolve` request with the decision, then resumes the turn;
the original request completes normally.

Exact ordering, permission:

```json
{"jsonrpc": "2.0", "method": "event", "params": {"type": "permission_request", "data": {"tool_name": "bash", "args": {"command": "rm -rf /tmp/x"}, "risk_level": "high", "reason": "destructive command"}}}
```

Client decision:

```json
{"jsonrpc": "2.0", "id": 8, "method": "interaction.resolve", "params": {"id": "perm-bash-call_1", "allowed": true}}
```

Daemon responds `{"result":{"resolved":true}}` and resumes the turn.

ask_user analog:

```json
{"jsonrpc": "2.0", "method": "event", "params": {"type": "ask_user", "data": {"questions": [{"text": "Pick a branch", "options": ["main", "fix/parser"]}]}}}
{"jsonrpc": "2.0", "id": 9, "method": "interaction.resolve", "params": {"id": "ask-1", "answer": "fix/parser"}}
```

`interaction.resolve` params: `{"id": string, "allowed"?: bool, "answer"?: string|array}`
— exactly one of `allowed`/`answer`; a missing `answer` resolves as `null`/`""`.
`permission_request` data MAY carry an extra `id` member (any 1.x revision);
echo it back, else `""` (§7). Frontend mapping: Allow → `allowed: true`; Deny →
`allowed: false` (the tool then fails with `denied` kind on the turn's terminal
`error` event). No second `permission_request`/`ask_user` is emitted before the
previous `interaction.resolve` arrives; clients queue further ones per session.

---

## 5. Errors

### 5.1 Protocol error codes

| `code` | `message` | Meaning |
| --- | --- | --- |
| `-32700` | `Parse error` | line is not valid JSON |
| `-32600` | `Invalid Request` | valid JSON, not a request/notification object |
| `-32601` | `Method not found` | unknown method (§7) |
| `-32602` | `Invalid params` | `params` not an object; required member missing/wrong type |
| `-32603` | `Internal error` | daemon-side exception |
| `-32001` | `Turn in progress` | session already has an active turn (§6) |
| `-32002` | `Request timeout` | daemon aborted the request (internal deadline) |

Application failures carry `error.data` with a `kind` string mapping 1:1 onto the
canonical `ERROR_KIND_*` constants in `src/johnston/core/tools/base.py` (lines
429–466). Clients MUST branch on `data.kind`; `message` is human-readable only.
The daemon must never invent kinds beyond this table.

| `kind` | Typical cause on this API |
| --- | --- |
| `not_found` | unknown session / skill / config key / worktree path |
| `permission` | operation denied by permission policy |
| `denied` | user denied a tool permission (terminal `fatal` `error` event) |
| `timeout` | tool/turn exceeded its deadline |
| `cancelled` | turn killed by user/daemon |
| `notrunning` | `task.kill` on an already-exited task |
| `notkillable` | task cannot be killed |
| `conflict` | branch/worktree conflict, file exists |
| `sandbox` | command blocked by sandbox (remedy: `sandbox.toggle`) |
| `unavailable` | provider/daemon resource temporarily unavailable |
| `limit` | concurrent-turn/subagent cap hit |
| `params` | facade parameter validation failure |
| `unknown_tool` | tool in `permission_request` not in registry |
| `network` / `http_status` | provider connectivity/fetch failures |
| `setup` / `context` / `manager` | daemon service initialization problems |
| `unknown` | legacy generic fallback — treat as internal error |

Synthetic wire-level kinds (stable protocol values, not `ERROR_KIND_*`):
`method_not_found`, `invalid_params`, `internal_error` (`-3260x`/`-32700` layer),
`turn_in_progress`, `request_timeout` (`-32001`/`-32002`).

Delivery rule: failures inside `prompt.stream` surface as `error`/`retry`
**events** (`ErrorEventDTO.message` may carry `ERR: <kind> ...` text per the tool
`<tool_io_reference>` convention; the turn still ends with `turn_completed`, or
with a `fatal` `error` event). Failures of plain methods (`session.resume`,
`task.kill`, …) surface as RPC `error.data.kind`.

---

## 6. Concurrency and session scoping

- **`session_id` semantics**: selects the target session; omitted → the
  connection's active session. Scoped methods: `session.resume`/`delete`/`export`,
  `prompt.*`, `compact`, `rewind.points`, `task.list`.
- **One active turn per session**: a `prompt.stream` for a session already
  running a turn → `-32001` (`turn_in_progress`). `prompt.prompt`, `compact`,
  `rewind.*` also fail `-32001` while that session's turn is active. Turns on
  **different** sessions may run in parallel. `queued_user_message` (§4.1) lets
  type-ahead frontends show that the user's prompt is queued: `{"jsonrpc":"2.0","id":6,"error":{"code":-32001,"message":"Turn in progress","data":{"kind":"turn_in_progress","session_id":"s-9b21"}}}`
- **Notification ordering**: within one session's turn, `event` notifications are
  strictly ordered — exactly the `JohnstonClient.stream()` yield order;
  `turn_completed` (or `fatal` `error`) is always emitted **before** the RPC
  response for `prompt.stream`. Events for different sessions are unrelated;
  events never interleave within one session's stream.
- **Disconnect mid-turn**: the daemon finishes the turn, persists the session
  (visible on later `session.resume`), then exits on stdin EOF. The client treats
  an abrupt exit as an incomplete turn and reconciles on restart.

---

## 7. Versioning and forward compatibility

- **Unknown methods → `method_not_found`**: dispatch is by exact name; unknown
  methods return `-32601` with `data.kind:"method_not_found"` and `data.method`
  echoing the name. Clients must fall back gracefully (disable the UI action),
  never emulate the method locally. Methods documented here whose backing facade
  isn't wired in a given daemon build (`session.export`) may return this error.
- **Unknown fields ignored**: unknown `params` members (daemon side), unknown
  `data`/`result` members (client side) and unknown `event` `type` values
  (clients skip them without aborting the turn) are ignored. Adding optional
  members is allowed within a major version; removing/renaming is breaking.
- **Version handshake**: `daemon.info` → `result.protocol_version` (`"1.0"`) plus
  `implementation`/`pid`/`cwd`. Clients check the major component at startup and
  warn/refuse on mismatch.
- **Never-downgrade rule**: the daemon reports the newest *fully* implemented
  revision. Unknown `data.kind` values in errors → clients treat as `unknown`
  (`internal_error` fallback).

---

## 8. Reference: daemon ↔ facade map

| RPC method | Backing call | Return |
| --- | --- | --- |
| `session.list` | `get_sessions()` | `list[SessionSummaryDTO]` |
| `session.create` | store `create_main` + `get_session()` | `SessionDTO` |
| `session.resume` | `get_session(session_id)` | `SessionDTO` |
| `session.delete` | store `delete(session_id)` | `bool` |
| `session.export` | (planned facade export) | object |
| `prompt.stream` | `stream(prompt, attachments)` | async `StreamEventDTO` iterator |
| `prompt.prompt` | `prompt(prompt, attachments)` | `TurnCompletedDTO` |
| `compact` | `compact()` | `CompactionResultDTO` |
| `rewind.points` | `get_rewind_points()` | `list[RewindPointDTO]` |
| `provider.list` | `get_providers()` | `list[ProviderDTO]` |
| `model.info` | `get_model_info(provider_key, model_name)` | `ModelInfoDTO` |
| `model.estimate_cost` | `estimate_cost(provider_key, model_name, total_tokens)` | `float` |
| `rules.list` | `get_rules()` | `list[RuleDTO]` |
| `skills.list` | `get_skills()` | `list[SkillDTO]` |
| `skills.toggle` | `toggle_skill(name)` | `bool` |
| `workspace.roots` | `get_workspace_roots()` | `list[WorkspaceRootDTO]` |
| `workspace.add` | `add_workspace_root(path, scope)` | `None` |
| `workspace.remove` | `remove_workspace_root(path)` | `bool` |
| `worktree.list` | `list_worktrees(project_dir)` | `list[WorktreeDTO]` |
| `worktree.create` | `create_worktree(project_dir, branch_name, base_branch)` | `tuple[str\|None, str\|None]` |
| `config.get` / `config.set` | settings / provider accessors | scalar / `bool` |
| `task.list` | `get_tasks(kind, session_id)` | `list[TaskDTO]` |
| `task.kill` | `kill_task(task_id)` | `bool` |
| `sandbox.toggle` | `toggle_sandbox()` | `bool` |
| `sandbox.state` | client `sandbox` flag | `bool` |
| `interaction.resolve` | completes `confirm_permission` / `ask_user` | `bool`/`str` |

**Not exposed** (no backing facade method): provider/model switching params on
`prompt.*` (future revision), `rewind_to` checkpoint restore, subagent session
management, git merge/conflict helpers. Every future method requires a backing
`JohnstonClient`/store call — no facade, no RPC method.