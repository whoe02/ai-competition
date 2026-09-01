# Kira — Butler Agent: Architecture Design

Date: 2026-08-27
Status: Draft for review
Supersedes: §8 of `2026-08-24-kira-architecture-design.md` (which reserved LangGraph
and a read-only tool registry; this document keeps the graph and replaces the
read-only rule with a structurally-enforced two-tier registry).

## 1. What this builds

The Butler is the conversational surface of Kira: a LangGraph agent, native to the
app, that reaches every module through a tool registry and personalises itself over
time through a durable, user-inspectable memory.

Three requirements drive every decision below.

1. **LangGraph architecture.** A real graph with a policy guard, a tool loop, a
   Postgres checkpointer, and `interrupt()`-based human-in-the-loop — not a
   prompt-and-parse wrapper.
2. **Controls every module, present and future.** Modules expose capability through
   a `ToolSpec` registry. Adding the day planner, receipt OCR, or CSV import later
   means adding one file and one `register()` call; the agent itself does not change.
3. **Long-term, personalising memory.** Typed facts in Postgres, extracted from
   conversation, retrieved into the prompt, and visible and correctable by the user.

## 2. Decisions made

| Decision | Choice | Why |
|---|---|---|
| Write scope | Two-tier registry: reads run freely, writes route through `interrupt()` | "Control all modules" without losing the approval gate that is the product's trust story |
| Money movement | No `ToolSpec` exists for it, at all | Structural incapacity, not instruction |
| LLM provider | Qwen via DashScope OpenAI-compatible endpoint | Product owner's choice; `ChatOpenAI` with a base URL gives LangGraph-native tool calling |
| Offline behaviour | `OfflineChatModel` behind the same interface | Competition venues have unreliable networks; the graph, tools and approval flow stay identical |
| Approval persistence | `interrupt()` + `AsyncPostgresSaver` **and** a `butler_approvals` projection row | Canonical resume semantics plus an audit trail readable in SQL |
| Memory storage | Typed rows in Postgres, no vectors | Tens of facts at demo scale; fully inspectable; no pgvector extension in the container |
| Memory UI | List with source, correct and delete, under More | Makes the feature visible and a wrong fact fixable |
| Streaming | SSE, tokens only on the tool-free composition call | DashScope compat mode forbids `tools` together with `stream=True` |

### 2.1 Two verified constraints

These were checked against vendor documentation rather than assumed, and both shape
the design.

**DashScope forbids `tools` with `stream=True`.** Alibaba Cloud's OpenAI-compatibility
documentation states the `tools` parameter cannot be used with streaming. The graph
therefore separates the two concerns: reasoning turns bind tools and do not stream
(they emit tool calls, not prose, so there is nothing worth streaming); the final
composition turn binds no tools and streams tokens. Progress remains visible
throughout because the SSE channel emits structured `thinking` and `tool` events from
the graph itself, not only model tokens.

**`langgraph-checkpoint-postgres` requires psycopg3.** It needs
`psycopg[binary,pool]` and a plain `postgresql://` DSN. The application is asyncpg
throughout and its DSN is `postgresql+asyncpg://`. The checkpointer therefore runs a
second driver and a second pool against the same database, and `config.py` grows a
derived `checkpointer_dsn` property that strips the SQLAlchemy dialect suffix. This is
an accepted cost, not an oversight.

## 3. Package layout

```
apps/api/kira/agent/
  graph.py          StateGraph construction and compilation
  state.py          ButlerState
  llm.py            chat model factory; DashScope and offline implementations
  policy.py         protected-resource rules
  prompt.py         system prompt assembly, including the memory block
  nodes/
    context.py      load_context   — deterministic, no LLM
    reason.py       agent          — model bound to registry tools
    guard.py        guard          — the write boundary
    execute.py      tools          — read-tool execution
    approve.py      approval       — interrupt() and the projection row
    compose.py      compose        — answer plus recorded evidence
    memory.py       extract_memory — durable-fact distillation
  tools/
    spec.py         ToolSpec, ToolContext, ToolResult, ToolRegistry
    dashboard.py    get_financial_snapshot, calculate_safe_to_spend
    ledger.py       list_activity, confirm_draft*, discard_draft*,
                    unconfirm_transaction*, add_transaction*
    goals.py        list_goals, project_goal, create_goal*, update_goal*
    commitments.py  list_commitments, create_commitment*, update_commitment*
    memory.py       remember*, forget*
  services/         (in kira/services/) goals.py, commitments.py — new write services
```

`*` marks a write tool. Every write tool is unreachable except through an approved
`butler_approvals` row.

### 3.1 Layering

`pyproject.toml` already forbids `kira.engine` from importing `kira.agent`. The layers
contract extends to place the agent between the API and the services:

```
api  →  agent  →  services  →  engine
                        ↓
                    adapters
```

`kira.agent` must not import `kira.api`. Enforced by import-linter in CI, like the
existing contracts.

## 4. The graph

```
START
  → load_context
  → agent  ⇄  guard  →  tools        (read tools; loop back to agent)
              guard  →  approval     (write tools; interrupt())
  → compose
  → extract_memory
  → END
```

**`load_context`** is deterministic and calls no model. It loads the financial
snapshot via the existing `load_snapshot`, the dashboard result via
`today_dashboard`, the recent thread history from `butler_messages`, and the
retrieved memories. Because it is pure orchestration over existing services, the
agent's view of money is exactly the app's view of money — there is no second,
divergent read path.

**`agent`** binds the registry's tool schemas to the chat model and produces either
tool calls or a final answer.

**`guard`** inspects every proposed call before anything executes:

- unknown tool name → refused, with a message back to the model;
- arguments failing the `args_model` validation → refused, with the validation error;
- a call that would touch a protected commitment or the buffer → refused outright,
  regardless of tier;
- `kind="read"` → routed to `tools`;
- `kind="write"` → routed to `approval`.

**`tools`** executes read handlers, collecting their evidence rows, and returns to
`agent`. A hard iteration cap (`butler_max_tool_iterations`, default 6) prevents
runaway loops.

**`approval`** writes the `butler_approvals` row and calls `interrupt()`. The HTTP
request ends; the graph state sits in the checkpointer. Nothing has been written to
financial state.

**`compose`** produces the final prose. It streams.

**`extract_memory`** distils durable facts from the exchange and writes them.

## 5. The write boundary

Three independent mechanisms, so that no single mistake opens the gate.

1. **Routing.** `guard` routes on `ToolSpec.kind`. A write handler is never invoked
   from the `tools` node — only from the approval-resume path.
2. **Registration.** Constructing a `ToolSpec` with `kind="write"` and no `summarise`
   callable raises at import time. A silent write cannot be registered.
3. **Absence.** `apply_plan_change` and anything else that moves money has no
   `ToolSpec` whatsoever. It remains a service function reachable only from
   `POST /v1/butler/approvals/{id}/respond` after an explicit user decision.

Approval-time re-validation matters as much as proposal-time validation: on `accept`
and on `edit`, the endpoint re-parses the arguments through `args_model` and
re-checks ownership and the protected-resource policy before the service runs. An
approval row is not a licence to execute whatever it happens to contain.

## 6. The tool contract

```python
@dataclass(frozen=True, slots=True)
class ToolSpec:
    name: str
    module: str                       # "ledger" | "goals" | "dashboard" | …
    kind: Literal["read", "write"]
    description: str
    args_model: type[BaseModel]
    handler: Callable[[ToolContext, BaseModel], Awaitable[ToolResult]]
    summarise: Callable[[BaseModel], str] | None = None   # required when write
```

`ToolContext` carries the `AsyncSession`, the `User`, `today`, and the already-loaded
`Snapshot`. Tools therefore never read a clock and never widen ownership — both are
supplied, not fetched.

`ToolResult` is `(value, evidence: tuple[EvidenceRow, ...])` where `EvidenceRow` is a
label and a formatted value.

**Extending to a future module** is a new file under `kira/agent/tools/` and a
`register()` call. The graph, the guard, the approval flow, and the API are untouched.
This is the whole of the "controls all modules, present and future" requirement.

## 7. Evidence is recorded, not claimed

Every read tool returns its evidence rows alongside its value. `compose` renders the
"What I used" panel from rows that executed tools actually returned. The model
receives those rows as context and writes prose around them; it never authors the
panel.

The consequence is that the evidence display cannot drift from reality and cannot be
fabricated. This is what makes the prototype's evidence panel an honest artefact
rather than decoration, and it is the concrete form of the architecture document's
requirement that every Butler answer persist the exact snapshot it consumed.

## 8. Memory

### 8.1 Model

```
butler_memories(
  id, user_id,
  kind,               -- preference | constraint | context | person | pattern
  subject,            -- short noun phrase, the dedupe key with kind
  fact,               -- one sentence, user-readable
  source_message_id,  -- provenance
  confidence,         -- 0..100
  status,             -- active | superseded | deleted
  superseded_by,
  created_at, last_used_at
)
```

| Kind | Holds | Example |
|---|---|---|
| `preference` | how the user wants to be treated | prefers blunt numbers over encouragement |
| `constraint` | a standing rule | never suggests cutting the wedding goal |
| `context` | durable life fact | works in KL, commutes by MRT |
| `person` | someone who recurs in their money | splits rent with a housemate |
| `pattern` | an observed regularity | groceries land on Sunday, about RM180 |

### 8.2 Write path

`extract_memory` runs after the answer and proposes candidate facts. A candidate
matching an existing `(kind, subject)` supersedes rather than overwrites: the old row
moves to `status='superseded'` with `superseded_by` set. Nothing is destroyed, so the
trail of what Kira believed and when stays intact — the same discipline as the ledger.

Memory writes are the one exception to the approval rule: `remember` and `forget` as
explicit user-directed tools do route through approval, but passive extraction does
not, because pausing to approve every remembered fact would make the feature
unusable. The compensating control is that extraction can only write to
`butler_memories` — it holds no other capability — and every fact is visible and
deletable in the UI.

### 8.3 Read path

`load_context` selects `status='active'` rows for the user, ordered by kind priority
then `last_used_at`, capped at 40, and renders them into the system prompt as a
compact block. Facts cited in an answer have `last_used_at` bumped, so the working
set converges on what actually matters to this user.

### 8.4 User control

`GET /v1/butler/memories` lists every active fact with its source message and
confidence. `PATCH` corrects the text; `DELETE` sets `status='deleted'`. Both write an
`audit_event`. The More screen surfaces this as a plain list.

## 9. Data model

| Table | Purpose |
|---|---|
| `butler_threads` | one conversation; one per user by default |
| `butler_messages` | role, content, evidence JSON, tool-call JSON, created_at |
| `butler_memories` | as §8.1 |
| `butler_approvals` | tool, validated args, summary, evidence, status, LangGraph thread id and checkpoint ref, decided_at, resulting audit event |
| `audit_events` | actor, action, detail JSON — every applied approval and every memory change |

All five are Alembic-managed. LangGraph's own checkpoint tables are created by an
idempotent `checkpointer.setup()` at application startup, alongside the existing
migration step; they are LangGraph's schema and deliberately stay outside Alembic.

`butler_approvals` is a strict projection of the interrupt: only the resume endpoint
transitions its status, so the row and the checkpoint cannot disagree about what was
decided.

## 10. LLM adapter

The current `LlmAdapter.complete(system, messages) -> str` and its `ScriptedLlm` fake
cannot express tool calling, and `ScriptedLlm` has no other consumer. Both are
replaced.

`kira/agent/llm.py` exposes `get_chat_model() -> BaseChatModel`, returning one of:

- `FallbackChatModel` — two `ChatOpenAI` clients against
  `settings.dashscope_base_url`, the first on `settings.butler_model` and the
  second on `settings.butler_fallback_model`. Every turn is asked of the main
  model; when that call raises — an id this key is not served, a rate limit, a
  timeout — the identical call is re-issued against the fallback and the reply
  carries `kira_model_fallback` in its metadata. `bind_tools` binds both children
  and rewraps, so the reasoning turn keeps its tools across a swap;
  `with_structured_output` hands off to LangChain's own fallback wrapper, whose
  children return the schema rather than a message; `_astream` swaps only before
  the first token, since a stream that dies mid-answer has already put words on
  the screen.
- `ChatOpenAI` alone — when `butler_fallback_model` is blank or repeats
  `butler_model`, there is no ladder to build.
- `OfflineChatModel` — a deterministic `BaseChatModel` subclass that emits scripted
  tool calls and answers covering the demo-script questions.

So the ladder is: main model, fallback model, scripted. Offline is selected by
`BUTLER_OFFLINE=1` and on a missing key; it is also where `agent` and `compose`
land when *both* online models fail, each node catching the raised error for
itself. The graph, the tools, the guard, the evidence and the approval flow are
identical at every rung; only language generation differs. A dead venue network
degrades the Butler's prose, not its behaviour.

New settings: `dashscope_api_key`, `dashscope_base_url`
(default `https://dashscope-intl.aliyuncs.com/compatible-mode/v1`), `butler_model`
(default `qwen3.7-flash`), `butler_fallback_model` (default `qwen3.6-plus`),
`butler_offline`, `butler_max_tool_iterations`, `butler_request_timeout_seconds`.
`docker-compose.yml` passes `DASHSCOPE_API_KEY` through as an optional variable,
and both model ids with those defaults.

## 11. API surface

```
GET    /v1/butler/threads/{id}            thread and messages
POST   /v1/butler/threads/{id}/messages   SSE stream
POST   /v1/butler/approvals/{id}/respond  accept | edit | reject
GET    /v1/butler/memories                list
PATCH  /v1/butler/memories/{id}           correct
DELETE /v1/butler/memories/{id}           forget
```

SSE event types: `thinking`, `tool` (module and human label), `evidence`, `token`,
`approval`, `done`, `error`.

The client uses `fetch` with a `ReadableStream` reader rather than `EventSource`,
because authentication is a bearer header on a POST and `EventSource` supports
neither.

## 12. Frontend

The Butler tab currently renders `Placeholder`. It becomes a real screen reusing the
prototype's markup at `kira-prototype.jsx:1774` — user and Kira bubbles, the thinking
indicator, the evidence panel, the scenario and approval card, the composer with its
scan and voice affordances. `App.tsx` already treats `butler` as the dark tab and
already routes to it, so the shell needs no change.

A memory list is added under More: each fact with its kind, its source, and correct
and delete actions.

## 13. Testing

- **Golden conversation tests** against `OfflineChatModel` — deterministic, no
  network, no key. Each case fixes a question and asserts the tools called, the
  evidence rows produced, and the approval raised.
- **Registry contract tests** — every `kind="write"` spec has a `summarise`; no
  registered handler transitively reaches money movement; every spec's `args_model`
  round-trips through JSON schema.
- **Write-boundary test** — run the graph with a scripted model that emits a write
  call; assert zero rows changed in financial tables and exactly one pending approval.
- **Approval re-validation test** — an `edit` carrying arguments that violate the
  protected-resource policy is rejected at the endpoint, not applied.
- **Memory tests** — extraction, `(kind, subject)` supersede, retrieval ordering and
  cap, `last_used_at` bump, delete.
- **SSE test** — event ordering and terminal `done`.
- **Import-linter** — the new `api → agent → services → engine` layering.

## 14. Build order

| Task | Deliverable |
|---|---|
| 1 | Five tables, Alembic migration, config settings, dependencies |
| 2 | `ToolSpec`, `ToolContext`, `ToolResult`, registry, contract tests |
| 3 | Graph with read tools only; `OfflineChatModel`; golden conversation tests |
| 4 | Memory subsystem: extraction, retrieval, supersede, CRUD API |
| 5 | Write tools, `interrupt()`, checkpointer, approvals endpoint, audit events |
| 6 | SSE endpoint, Butler screen, memory screen |

Tasks 1–3 are independently useful: at the end of task 3 the Butler answers
truthfully from real data with real evidence, and cannot write anything at all.

## 15. Known consequence of resequencing

This work pulls the architecture document's week 7 ahead of weeks 3–6. Goals and
scenario replanning, receipt and voice capture, and the day planner do not exist yet.

The registry means each of those plugs in later without touching the agent. But the
overspend-recovery flow in the demo script depends on the goal-scenario engine from
weeks 3–4, so that specific conversation remains a stub until that engine lands. The
Butler will be genuinely useful before then — affordability, why a number moved, goal
progress, ledger control — but the scenario-comparison approval card is the one demo
beat this work cannot complete on its own.

New write services for goals and commitments are built here, since the Butler needs
something to control. They are ordinary services in `kira/services/` and the eventual
Plan screen will consume the same functions.

## 16. Space left for voice and camera

Added after review, at the product owner's request. The requirement is that
speaking to Kira and showing her a receipt are first-class inputs, not
retrofits — so the seam is built now and the providers arrive later.

**Nothing here writes.** A machine read is a proposal. `POST /v1/capture/receipt`
and `POST /v1/capture/voice` take bytes, return fields with a confidence on each,
and touch no table. Turning one into a draft is a separate, explicit
`POST /v1/transactions`; turning a draft into ledger truth is still the user
confirming it. The rule that a read amount is never a fact is enforced in one
place, `create_transaction`, rather than at each caller.

**The providers are already abstracted.** `OcrAdapter.read_receipt` and
`VoiceAdapter.transcribe` exist in `kira/adapters/protocols.py` and are wired to
the deterministic fakes. `kira/services/capture.py` is the only consumer.
Swapping in a real vendor is a change to `registry.py` and nothing else — the
API, the agent, the tools and the UI do not know which one is behind it.

**The Butler sees a capture as an attachment on the turn.** `ButlerAskRequest`
carries it, `ToolContext.attachment` exposes it, and `inspect_attachment` — an
ordinary read tool in `kira/agent/tools/capture.py` — returns the read fields as
evidence rows, including the row that says it is not on the ledger. The turn is
persisted with its attachment, so the thread shows what was shown.

**The UI captures for real.** `ScanSheet` uses `capture="environment"`, which
opens the rear camera on a phone and degrades to the file picker on a desktop.
`VoiceSheet` uses `getUserMedia` and `MediaRecorder`, with a live waveform driven
by an `AnalyserNode` rather than an animation loop pretending to listen. Where
the browser refuses the microphone the sheet says so and offers the sample; a
dead affordance is worse than none, which is also why `GET /v1/capture` tells the
client what to offer.

**What is deliberately not built.** Streaming speech-to-text, on-device
transcription, receipt line-item extraction, and correcting a doubtful word by
tapping it. Each is a change behind the adapter or inside one sheet, and none of
them moves the boundary this document is about.
