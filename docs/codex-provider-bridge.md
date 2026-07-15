# Codex ChatGPT / Image Provider Bridge

HanClassStudio cannot invoke the model embedded in a Codex Desktop conversation as a
normal HTTP model endpoint. The Codex bridge therefore uses an explicit asynchronous
handoff instead of pretending that Codex is an OpenAI-compatible API.

## Contract

Two Provider IDs are exposed by the backend capability catalog:

- `codex_chatgpt` for Blueprint generation;
- `codex_image` for raster image generation.

Both require the same user-generated bridge token. A Provider is `configured` after
its token has been saved, but it is `available` only while an authenticated Codex
agent is sending a fresh heartbeat. The heartbeat expires after 120 seconds. The
backend stores only a SHA-256 digest of the token in its session file; settings GET,
capability responses, jobs, and logs never return the token.

## Lifecycle

1. The teacher selects one or both Codex bridge Providers in **模型设置**, enters a
   locally generated bridge token, and saves.
2. The Codex agent authenticates with `Authorization: Bearer <token>` and sends:

   `POST /api/providers/codex-bridge/heartbeat`

   with `{"capabilities":["llm","image"]}` (or only the configured subset).
3. A normal HanClassStudio Blueprint or media action creates a project-scoped,
   schema-bound job and returns structured HTTP 409
   `codex_agent_action_required`. It does not report the stage as completed.
4. The agent reads pending work from:

   `GET /api/providers/codex-bridge/jobs?state=pending`
5. The agent submits a result to exactly one of:

   - `POST /api/providers/codex-bridge/jobs/{job_id}/complete-blueprint`
   - `POST /api/providers/codex-bridge/jobs/{job_id}/complete-image`
6. The teacher retries the original action. HanClassStudio validates and consumes the
   completed job through the ordinary pipeline.

## Validation and ownership

- Blueprint results must validate as `LessonBlueprint` before a job can complete.
- Image results must be PNG, JPEG, or WebP with a valid decodable header and a
  maximum payload size of 25 MB.
- Completed jobs are immutable; a second submission is rejected.
- Bridge results are first written below the project's `agent/codex_bridge/results/`
  directory. Images then enter the normal asset candidate and teacher-review flow;
  they are not silently accepted as current media.
- Media changes retain the existing downstream stale propagation. Export and quality
  gates are not bypassed.
- The bridge does not execute arbitrary shell commands, install Providers, search
  external repositories, or expose a general filesystem API.

## Operational limitation

The bridge is session-bound. Codex must be open and actively heartbeating while the
Provider is used. If it disconnects, the capability catalog truthfully reports the
Provider as unavailable and leaves queued jobs pending for later recovery.
