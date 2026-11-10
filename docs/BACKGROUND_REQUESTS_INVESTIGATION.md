# Background requests across multiple chats

Investigation date: 2026-11-10.

Status: findings and proposed design only. Implementation is deferred at the
user's request. This document does not authorize implementation or indicate
that background requests are already supported.

## Assessment and proposed direction

Multiple pending text requests across different chats appear viable with a
small worker pool and explicit ownership of each request's state. This is a
moderate controller, persistence and UI refactor. Worker scheduling itself is
the smaller part of the work.

Most of the isolation work would be necessary even for a single request that
continues after navigating away. The recommended architecture should therefore
support multiple jobs from the outset, rather than introduce another global
single-request design.

The initial suggestion was to allow only one pending request application-wide.
The subsequent discussion refined that direction: support multiple pending
requests across different chats, while retaining one pending request per chat
and the other restrictions below. Proving the architecture with one worker
before enabling concurrency remains a useful implementation sequence.

These are design recommendations, not implemented behaviour or fixed product
decisions. No provider API rewrite, conversion to asyncio, database migration,
or persistent job queue has been identified as necessary for the initial scope.

## Current behaviour

- Submissions already run in worker threads, but the controller has one
  `_active_request_token`, one selected conversation and one active repository.
- The UI has one `_request_cancel_event`. Starting a new request signals the
  previous event.
- Request validity depends on the originating history and repository still
  being the controller's selected objects. Navigating to another chat, creating
  a chat, or switching projects invalidates the request.
- Stream cancellation attempts to close the HTTP response. Whether the server
  stops generation depends on its handling of disconnection. The model server
  process itself is not terminated.
- The cancellation watcher begins after an HTTP response is obtained; cancelling
  while waiting for initial response headers may be delayed.
- Partial output is retained for explicit cancellation of the active request.
  Output invalidated by navigation is discarded rather than saved offscreen.
- Loading a chat constructs a fresh history list. Returning to the same filename
  does not restore the original in-memory history object or request.
- There is no job registry that can restore an offscreen request's preview,
  status or Cancel control.

## Source map

Relevant locations at the time of investigation:

| Area | Source and relevant entry points |
| --- | --- |
| Request identity and completion | [controller.py](../src/controller.py): `ChatContext`, `capture_chat_context`, `is_chat_context_current`, `_request_is_current`, `send_message`, nested `is_cancelled` and `finish_response` |
| Loading and saving | [controller.py](../src/controller.py): `load_chat`, `save_current_chat`, `add_user_message` |
| Thread launch and UI cancellation | [ChatGTK.py](../src/ChatGTK.py): `emit_thinking_started`, `call_ai_api`, `_on_thinking_cancelled`, submission handler |
| Rendering completed responses | [ChatGTK.py](../src/ChatGTK.py): `_on_message_received_event`; [chat_view.py](../src/ui/chat_view.py): streaming preview and thinking handlers |
| Sidebar selection | [history_sidebar.py](../src/ui/history_sidebar.py): `_on_chat_event`, `select_chat` |
| Persistence and shared index | [chat_history_repository.py](../src/repositories/chat_history_repository.py): `save`, `_update_history_index`; [history_index.py](../src/repositories/history_index.py); [file_utils.py](../src/repositories/file_utils.py) |
| Streaming transport | [streaming_service.py](../src/services/streaming_service.py); [response_stream.py](../src/services/response_stream.py): `managed_stream` |
| Tools, project paths and compaction | [controller.py](../src/controller.py): `_init_history_repo_for_project`, `handle_apply_text_edit`, `handle_image_tool`, `_check_and_perform_compaction`; [ChatGTK.py](../src/ChatGTK.py): `_build_tool_handlers`; [ai_providers.py](../src/ai_providers.py): history-directory getter and media storage |

## Findings and risks

### Request validity and UI visibility are coupled

The same ownership check currently prevents stale output, cancels streams and
guards tool execution. Relaxing it alone is unsafe because completion still
appends to `self.conversation_history` and calls `save_current_chat()`.

A controlled experiment used the existing mocked controller fixture, switched
to a new chat inside a delayed provider response, and compared two cases:

| Case | Old reply appended to the new chat | Save calls |
| --- | --- | --- |
| Existing ownership guard | No | 0 |
| Guard changed to check only the active token | Yes | 1 |

This was an in-memory experiment with a mocked provider and mocked saving. It
made no live API calls and did not change application files or real histories.
It demonstrates why a cancellation-only patch would be insufficient.

### Saving must target the originating conversation

Completion needs a stable chat identity, captured repository, metadata and
authoritative history. It must not obtain its destination from the selected UI.
The submitted user message also needs to be durably saved before queuing work.

Reopening a running chat must reconnect to its existing state. Loading a separate
disk snapshot and later saving it could overwrite a completed background reply.
Pending-chat mutation restrictions and a revision check at completion should
protect against stale writes.

Atomic JSON replacement already protects against partially written files. It
does not serialize read-modify-write operations or prevent stale snapshots
overwriting newer histories.

Different chat files also share `.history_index.json`. Concurrent completions
can load the same index and overwrite one another's updates. Serialization must
cover all operations that mutate that shared index, including relevant listing,
deletion and document paths, rather than only background completion.

### UI events have side effects beyond displaying text

- `CHAT_SAVED` currently selects the saved chat in the sidebar. Background saves
  should refresh status without changing the user's selection.
- Streaming, completion and error events need chat and request identities, so
  an old queued callback cannot replace another chat's preview or stop button.
- Returning to a pending chat should restore its current preview and controls.
- Automatic read-aloud and compaction need explicit policies for offscreen
  completion. The initial recommendation is to suppress background speech and
  defer compaction until the originating chat is active.

### Tools and media are the larger expansion in scope

Tool handlers can read current controller targets, attachments, chat IDs and
settings. Pending text-edit events are also controller-wide. Project switching
changes repositories and module-level history-directory getters used for media.
Allowing these actions to continue after navigation requires separate work to
bind targets, permissions, undo state and output paths to each job.

Shared provider wrappers contain mutable clients, endpoint configuration and
caches. Their concurrent use needs an audit. Owning a provider/session per job
is a straightforward initial option; this is not a finding that all underlying
SDK clients are unsafe to share.

## Proposed initial scope

- Multiple pending requests across different chats, with one pending request
  per chat.
- Begin with local text requests that have tools disabled. Requests using tools
  or media retain the existing foreground behaviour; do not silently remove
  configured tools to make a request eligible.
- Browsing other chats is allowed. Editing, deleting or moving a pending chat
  is blocked until its job reaches a terminal state.
- Project switching continues to cancel pending jobs initially. Still capture
  the originating repository explicitly rather than rely on current globals.
- Each job can be cancelled independently, including while queued and while
  its chat is offscreen.
- Closing the application cancels pending jobs. Restart recovery, crash
  recovery and a persistent work queue are outside the initial scope.

## Proposed worker architecture

### Request manager

A request manager owns jobs keyed by a stable conversation identity. Include
the history root/project location as well as the chat ID, since filenames alone
are not necessarily unique across projects.

Separate the immutable request specification from mutable execution state:

| Request specification | Execution state |
| --- | --- |
| Request ID and originating chat key | Queued, running, completed, cancelled or failed status |
| Captured repository and metadata | Per-job cancellation event |
| Prepared message snapshot and starting revision | Streamed answer and reasoning buffers |
| Captured model/provider configuration | Result, error and persistence outcome |
| Explicit tool policy | Authoritative originating conversation state |

Preparing messages must capture prompt, memory and settings context before the
job is dispatched. Workers should not prepare their prompt later by reading
whatever chat happens to be selected.

### Bounded queue and worker pool

A small thread pool is sufficient for the existing blocking HTTP clients.
Workers perform provider calls and report updates tagged with request and chat
IDs. They do not modify GTK widgets or use selected-chat state as a destination.

A reasonable starting configuration is two workers overall and one active
request per local endpoint. Additional requests remain queued. The scheduler
should dispatch jobs only when endpoint capacity is available, so jobs waiting
for one endpoint do not occupy every worker and block other endpoints.

Pending work and simultaneous server generation are different capabilities.
More local-server parallelism should be configurable later, after testing the
server and available resources. A worker pool does not itself make a local
model generate faster.

### Completion and persistence

The manager validates the originating conversation revision, commits the result
once through its captured repository, and publishes the outcome. Serialize
saves and shared-index updates without holding a global lock during network
generation. GTK updates remain scheduled on the main thread.

The visible UI subscribes to the selected chat's job. Hidden jobs retain their
buffers and update sidebar status without changing selection. Reopening a
running chat uses its authoritative in-memory state rather than an independent
history snapshot.

Cancellation, failure and normal completion must resolve to one terminal
outcome. Queued cancellation should avoid contacting the endpoint. Running
cancellation should close that job's stream without affecting other jobs.
Retain a completed result and report a persistence failure rather than silently
claiming success if saving fails.

## Suggested implementation sequence

1. Introduce request-owned state, explicit destination saving and a stable chat
   key. Keep one worker while proving navigation and return-to-chat behaviour.
2. Separate UI visibility from job validity. Add independent cancellation,
   preview restoration and sidebar status without automatic selection.
3. Add persistence/index serialization and pending-chat mutation guards.
4. Enable two workers and endpoint scheduling; prove overlapping requests and
   independent cancellation.
5. Review the bounded implementation before considering tools, media,
   cross-project continuation or restart recovery.

Retain the existing stale-callback and wrong-chat protections throughout this
work. Tests that currently expect navigation to discard output will need new
expectations for eligible background jobs, while continuing to verify isolation.

## Validation requirements

- A and B stream concurrently; B finishes first; both results and reasoning
  are saved exactly once to their own chats.
- Navigate A to B to A while A runs; restore A's preview and cancellation state.
- Complete a hidden chat without changing the visible chat, sidebar selection,
  preview, speech playback or cancellation control.
- Cancel A while B continues. Cancel a queued job before any HTTP request starts.
- Reject a second pending request in the same chat.
- Enforce global and endpoint limits without starving independent endpoints.
- Refuse pending-chat edits, deletion and moves. Detect an unexpected missing
  or modified destination instead of recreating or overwriting it silently.
- Handle initial-header waits, stream failures and cancellation/completion races.
- Exercise simultaneous saves and shared-index updates; preserve metadata and
  prevent stale history writes.
- Cancel outstanding work on shutdown and handle late GTK callbacks safely.
- Verify that foreground tool/media requests retain their existing safeguards.

During the investigation, the following existing checks passed: **36 tests**.
These are baseline checks, not evidence that the proposed feature exists:

```sh
python3 -m pytest tests/test_chat_request_context.py tests/test_atomic_saves.py tests/test_compaction.py -q
```

## Separate issue for slow local models

Custom streaming currently uses `timeout=(10, 120)`: a ten-second connect timeout
and a 120-second read timeout. Long periods without received data can therefore
time out even after background jobs are introduced. Timeout policy and explicit
cancellation during initial-header waits should be investigated independently.

## Recommendation

Proceed, when implementation is explicitly requested, with the constrained
multi-job design above. Request isolation, durable destination-specific saving
and event routing are the acceptance gates. Worker count can increase once
those gates pass. Full concurrent tool-using agents should remain a separate
design effort.
