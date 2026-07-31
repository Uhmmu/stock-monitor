# AI Chat Frontend

## Page, routes, and components

The authenticated dashboard exposes “AI 研究助手”. `/ai/new` is draft-only and `/ai/{conversationId}` restores a persisted conversation. TanStack Query owns server state; local React state owns drafts, active streaming, optimistic messages, tool activity, drawers, and dialogs.

```text
AIChatPage
├── ConversationSidebar (active / archived / deleted)
└── Chat workspace
    ├── header and active context
    ├── MessageList -> SafeMarkdown / RichContentRenderer / ToolActivity
    ├── MessageComposer
    └── CitationDrawer and management dialogs
```

The company overview sheet's “询问 AI” action opens `/ai/new?symbol=MSFT&context=company`; it supplies context but never sends automatically.

## API, pagination, and state

Types/clients live in `features/ai-chat/api`. Query keys include conversation IDs. Conversation lists and messages use server pagination; “load more” retrieves more conversations or older messages. Terminal mutations invalidate list/detail/message caches.

The first send creates the conversation, updates the URL, then starts the message request. A synchronous in-hook lock prevents double creation.

## SSE client and message state machine

POST streaming uses authenticated `fetch` + `ReadableStream`, not EventSource/Axios. The parser handles CRLF, split UTF-8, cross-chunk framing, multiple events, malformed/unknown-event isolation, JSON data, AbortController, and a single terminal event. Tokens never enter URLs.

```text
idle -> creating_conversation -> connecting -> streaming
                                            -> stopping -> cancelled
                                            -> completed | partial | failed
```

Deltas flush every 32 ms. Tool events update safe activity, citation maps attach metadata, and terminal events converge on persisted server data.

## Optimistic send, stop, and regenerate

Temporary IDs use `temp-user-*`/`temp-assistant-*`; `message.created` replaces them with server IDs. Canonical queries remove matching optimistic rows. Temporary IDs are never sent.

Stop aborts fetch first, calls the stop endpoint second, suppresses duplicate abort errors, retains partial content, and reloads server state. Leaving an active chat performs best-effort abort/stop. A completion race is harmless.

Regenerate appears only on the latest terminal assistant answer. It adds a new assistant version, preserves old answers, and shows `generation_index`; no complex branch-tree UI is claimed.

## Markdown, citations, and tools

User content is preserved plain text. Assistant content uses `react-markdown` + `rehype-sanitize` without raw HTML. Links are restricted to HTTP(S) and use `noopener noreferrer`; tables scroll, code blocks copy, and long URLs wrap.

`[S1]` becomes a keyboard citation action only outside inline/fenced code. The drawer sorts keys numerically, shows bounded metadata, opens public HTTP(S) URLs only, and degrades to “来源信息不可用”. It never constructs or displays filesystem locators.

Tool activity shows safe names, status, bounded summary, and counts. It hides raw arguments/results, SQL, cache keys, user IDs, and provider reasoning.

Completed assistant messages can also carry a versioned
`RichContentDocument`. The runtime and its 12 explicitly registered financial
components are documented in [`ai-rich-content.md`](ai-rich-content.md).
Unknown/invalid/crashed blocks use persisted Markdown fallback, and copy always
uses the message fallback rather than serializing the visual component.

## Conversation management and errors

The sidebar supports create, select, rename, archive/unarchive, soft delete, restore, empty/loading states, and pagination. Delete uses a focus-trapped recoverability dialog; archive uses a toast. Relative time has an exact timestamp tooltip.

Auth, provider, rate-limit, busy, missing/deleted conversation, context/budget, partial, abort, and network failures map to safe Chinese text. Tracebacks, upstream raw bodies, API bases/keys, and SQL errors are not displayed.

Refresh loads history without resubmission. A stored pending/streaming row with no process-local generation is labelled interrupted rather than retried.

## Context and model selection

The composer sends active symbol(s), server-owned portfolio context, page context, and the selected model. Users can remove visible symbols but cannot edit internal portfolio IDs. The selector reads the server model catalog, groups compatible models under Claude and GPT, and updates the conversation for later messages and regenerations. All models share one system prompt and one budget policy.

## Responsive, theme, motion, and accessibility

Desktop uses a 292 px conversation sidebar and bounded reading column. Below 840 px the sidebar becomes a drawer; below 560 px citations become a bottom sheet. The composer respects safe-area insets.

Scoped light/dark system tokens, immediate press feedback, restrained translucent chrome, and opaque reading surfaces follow the existing Apple-style design. The page honors reduced motion, reduced transparency, and increased contrast.

Dialogs trap/restore focus; Escape closes/stops; controls have labels; citation badges are buttons; SSE status uses `aria-live=polite`; errors use alert regions. Enter sends, Shift+Enter adds a line, and IME composition guards prevent accidental Chinese-input submission. Empty, over-limit, duplicate, and in-flight sends are blocked at the backend's 12,000-character limit.

## Performance

- TanStack Query remains the only server-state store.
- Deltas batch at 32 ms and sidebar data is isolated from them.
- Auto-scroll follows only near the bottom and offers a return button otherwise.
- Query keys prevent cross-conversation cache reuse.
- Switching conversations aborts active work.

## Tests

```bash
cd frontend
npm test
npm run build
```

Tests cover split/UTF-8/malformed/unknown SSE, rich completion events,
continuous deltas, citation conversion outside code, XSS/`javascript:`
rejection, schema limits, registered/unknown block versions, local fallback,
and accessible citation output. TypeScript runs inside build. This repository
has no separate lint script.

## Deliberate omissions and future memory boundary

There is no file/image upload, voice, arbitrary HTML, system prompt editor, API-key storage, search toggle, multi-agent UI, trading action, collaboration, semantic search, or long-term memory. A future memory phase should use an explicit, user-controlled summary service and must not copy full tool payloads into messages or make the Orchestrator database-aware.
