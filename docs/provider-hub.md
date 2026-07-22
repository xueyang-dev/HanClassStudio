# HanClass Provider Hub v1

The Provider Hub is the teacher-facing capability management surface for
HanClassStudio. It presents online services, local runtimes, model packages,
and teaching workflows as verified backend facts. It is not a package manager
for arbitrary repositories and it does not make a Provider usable merely
because a card can be displayed.

## Architecture and authority

```text
built-in catalog ─┐
validated registry ├─> Hub adapter ─> local snapshot API ─> teacher UI
local settings ────┤       │
hardware probes ───┘       ├─> explicit refresh tasks
                           ├─> explicit configuration / connection tests
                           └─> reviewed installation task runners
```

The v1 Provider Registry remains the authority for its existing entries,
refresh validation, cache, and sandbox lifecycle. `provider_hub.py` adapts
those entries and adds the new layered capability-package contract. Existing
settings and Registry routes remain compatible.

The backend is authoritative for `status`, `compatible`, `ready`, and
`available_actions`. The WebUI renders only returned actions. Opening the Hub
performs local `GET` requests only; it never refreshes a remote source, saves a
configuration, starts an installation, or tests a connection implicitly.

The teaching-video entry uses a process-local `VideoCapabilityProbeCache`
instead of launching the full FFmpeg/font probe on every catalog read. A normal
read reuses a result for 15 minutes; the first read probes once, and concurrent
readers share the same locked probe. The cache records result, probe/expiry
times, probe-contract version, environment fingerprint, and failure summary.
The fingerprint covers resolved FFmpeg/ffprobe file identity and configured
font path, stat, family, source, license status, and Fontconfig settings. An
expired entry or changed fingerprint triggers a new probe. The explicit
`check_health` action forces refresh. Executable/font stat or probe failures
degrade the item to unavailable/degraded with stable blockers and never fail
the complete Hub response.

The teacher surface is titled **教学能力中心**, with `Provider Hub` retained as
the secondary technical label. Recommended capability packages remain in the
primary catalog. Legacy Provider descriptors and implementation-level services
are localized where their meaning is known and placed in a collapsed advanced
services section; their original name, description, IDs, and source facts remain
available in technical details.

## Domain model

The layers are intentionally separate:

- **Provider** identifies the vendor or service integration, trust level,
  source links, license/terms, data boundary, and available actions.
- **Runtime** is the process or execution environment used by a local
  capability. A runtime is not itself a model.
- **Model Package** describes versioned model assets and whether the format is
  declared non-executable. It does not contain installation commands.
- **Workflow Pack** maps one or more teacher-facing capabilities to a reviewed
  workflow definition.
- **Capability Package** binds reviewed Runtime, Model Package, Workflow Pack,
  and health-check declarations into one installable unit.

The first featured entries are:

| ID | Type | Phase-1 behavior |
| --- | --- | --- |
| `hcs.teaching-video-basic` | local | Probes system FFmpeg/ffprobe, required encoders/decoders, subtitle filter, and a usable CJK font. It does not install FFmpeg. |
| `hcs.local-image-basic` | local | Installs a bundled, checksum-pinned JSON fixture through the real asynchronous task pipeline. It is a safe lifecycle proof, not a generative model. |
| `hcs.online-image-high-quality` | online | Configures and tests the user's OpenAI image API credentials. The default is `gpt-image-2`; generation/editing still uses the existing media pipeline adapter. |

## Manifest and catalog contract

`ProviderHubItem` uses Pydantic with unknown fields forbidden. External links
must be plain HTTPS origins/paths with no credentials, custom ports, query, or
fragment. Entries are validated independently by `isolate_provider_manifests`,
so one malformed entry produces an `invalid_manifest` record without hiding
valid peers.

A Provider item may describe stable IDs, display metadata, type, capabilities,
publisher/version, trust/source, license/terms, redistribution, official links,
install/configure/readiness/compatibility facts, exact backend actions, and
optional Runtime/Model Package/Workflow Pack/health-check declarations.

Remote manifests are metadata only. They cannot provide shell commands,
executable installers, arbitrary URLs, environment mutation, or a new trust
root. A future installable entry needs a reviewed, code-owned task runner.

## Discovery and refresh

`GET /api/providers/hub` returns the last trusted local snapshot plus best-effort
hardware facts. `POST /api/providers/hub/refresh` is the only Hub operation that
starts source refresh. It returns a task ID; the UI polls
`GET /api/providers/hub/refresh/{task_id}`.

The task reports added, updated, unchanged, failed-source counts, and one result
per source. Registry item changes use complete-manifest digests, not only version
labels. If a source fails, the task finishes `partial`, sanitizes the error, and
retains the previous valid snapshot. Overlapping refreshes are rejected. The
existing Registry transport continues to enforce commit-pinned HTTPS, public
address checks, time/size limits, schema validation, and atomic cache commit.

Adding GitHub, Hugging Face, or another discovery source requires a reviewed
adapter in `_REFRESH_SOURCE_ADAPTERS`. A source adapter can discover metadata;
it cannot authorize execution.

## Installation task state

Phase 1 implements one real, safe installer for the bundled local-image fixture:

```text
queued
  -> preflight -> resolving -> downloading -> verifying -> extracting
  -> installing_runtime -> installing_model -> installing_workflow
  -> starting -> health_check -> smoke_test -> completed
                                      ├-> failed
                                      └-> cancelled
```

Task state is persisted and includes overall/file progress, actual copied byte
counts, phase, teacher-facing message, stable error code, recoverable actions,
timestamps, and cancellation state. On the next catalog read, a queued or
running task without a live in-process worker is converted to a retryable failed
state. Phase 1 does not continue the original process, resume downloaded byte
ranges, or provide download checkpoint recovery. UI polling has a bounded wait;
backend runners also use bounded work.

The fixture runner enforces a bundled `.json` artifact with a 64 KiB limit, a
fixed SHA-256 and known identity, localhost runtime binding, a non-executable
model declaration, a known workflow, containment of the fixed JSON target path,
isolated staging, atomic replacement, deterministic health/smoke tests, and
failure cleanup.
A failure or cancellation never marks the package ready. Phase 1 intentionally
does not download or execute third-party code.

Asynchronous lifecycle mutations use one authoritative response shape:

```json
{
  "task": { "task_id": "...", "state": "running" },
  "provider": { "id": "...", "available_actions": ["cancel_install"] }
}
```

This shape applies to install, repair, future update/rollback/uninstall, and
cancel operations because each changes both task and Provider state. The backend
commits the task transition and computes the Provider snapshot together; the UI
applies both atomically. Synchronous configuration, enable/disable, deletion,
and health checks return their updated resource directly and do not invent a
task.

The fixture is a plain JSON file and Phase 1 does **not** implement ZIP or TAR
extraction. Before any real archive is accepted, the installer must reject `..`
traversal, absolute and Windows drive paths, symbolic- and hard-link escapes,
declared/actual size mismatches, decompression bombs, excessive extracted bytes,
and excessive file counts; it must also avoid check/use replacement races. The
current path check must not be described as archive extraction protection.

## Online configuration and secrets

Online configuration is explicit: opening reads public configuration; `PUT`
saves only after teacher submission; `POST .../test` performs a bounded,
authenticated model-endpoint request; disable/enable changes availability
without deleting credentials; `DELETE` removes the key and capability binding.
Authentication, rate-limit, network, and health failures have stable codes.

API keys are write-only in public responses and never enter browser persistence,
Hub snapshots, task messages, validation responses, or logs. Public 422 responses
use `SafeValidationErrorEnvelope`, return only stable error codes and schema
field paths, and never include rejected input. The same schema is installed as
the global OpenAPI 422 response, including routes whose successful response is
HTML, so generated clients see the actual JSON error contract. The Web client
parses both this envelope and legacy `detail` responses; it localizes
`request_validation_failed` by code instead of displaying the backend English
message. The current storage adapter uses the
existing local backend settings file with atomic replacement and owner-only
`0600` permissions on POSIX. It is **not encrypted and is not an OS keychain**;
the UI and API report `local_file_write_only`. A production desktop distribution
should replace this adapter with Keychain, Credential Manager, Secret Service,
or equivalent while preserving the public contract.

`0600` is a POSIX-only guarantee and the application does not claim equivalent
Windows ACL protection. The settings path stays under the backend runtime config
directory rather than project/export data, deletion rewrites the configuration
without the key, and temporary JSON uses the same owner-only POSIX mode. Secure
erasure and Windows credential protection remain release blockers for the
file-backed adapter.

The OpenAI endpoint is restricted to `https://api.openai.com` with no
credentials, alternate port, query, or fragment. External links use `noopener
noreferrer`, and the UI displays the destination hostname.

OpenAI Images inherits endpoint, model, and saved-key state only when the stored
image Provider is already `openai_images`. Placeholder or unrelated Provider
settings remain available to their legacy path but the Hub presents the real
defaults `https://api.openai.com/v1` and `gpt-image-2`. Empty submitted model
values normalize to `gpt-image-2`; `placeholder-svg` is rejected on save and is
also blocked before a connection check. Endpoint and custom-model controls are
advanced settings in the teacher UI.

## Hardware facts

The Hub performs best-effort detection of OS, architecture, memory, free disk,
NVIDIA GPU/CUDA, Apple MPS, and the DirectML platform signal. Results are
`compatible`, `compatible_but_slow`, `unsupported`, or `unknown`, with reasons.
Probe failures degrade to `unknown` and never hide the catalog. No runtime speed
estimate is shown because phase 1 has no representative benchmark.

## Add an online Provider

1. Add reviewed Provider metadata and links in the built-in catalog or validated
   Registry adapter.
2. Add a backend settings/secret adapter; never persist credentials in the
   browser or return them from an API.
3. Add allowlisted endpoint validation and a bounded connection checker.
4. Map errors to stable codes and persist only sanitized health facts.
5. Return exact backend actions for configure, test, delete, disable, and enable.
6. Test no implicit writes/network, redaction, auth/network failure, explicit
   delete, state transitions, and browser behavior.

## Add an offline Provider

1. Define separate Runtime, Model Package, Workflow Pack, license, source,
   compatibility, and health contracts.
2. Add a reviewed code-owned installer. A registry manifest cannot introduce
   commands.
3. Pin versions/checksums and enforce host, protocol, size, path, format, and
   license allowlists before materialization.
4. Stage in isolation, use an explicit atomic commit point, and define cleanup
   or rollback for every later failure.
5. Implement deterministic health and teaching-capability smoke tests. Only the
   backend may mark the package ready.
6. Test tampering, traversal, malicious metadata, timeout, cancellation,
   recovery, cleanup, and unsupported hardware before exposing install.

## Test strategy

- Backend: schema/layers, zero-network reads, hardware degradation, link and
  manifest rejection, real install progress, checksum cleanup, cancellation,
  refresh/partial retention, secret redaction/permissions, configuration/test/
  delete/disable, connection errors, real OpenAPI 422 output, and legacy online
  configuration isolation.
- Frontend state: exact action gating, teacher-facing filters, and direct safe/
  legacy error-envelope parsing tests.
- Playwright: no startup refresh, explicit refresh, failed install never ready,
  real fixture install, mobile overflow, Escape/focus restoration, and explicit
  configuration without secret rendering or placeholder-model inheritance.
- Repository gate: full `npm test` plus full Playwright E2E.

## Explicitly unsupported in phase 1

- arbitrary GitHub/Hugging Face/ComfyUI discovery or installation;
- remote shell, Python, npm, Docker, Homebrew, or system-package commands;
- installing FFmpeg, GPU drivers, CUDA, or DirectML;
- real local model downloads or model execution;
- ZIP/TAR extraction or archive traversal/link/bomb/inode defenses;
- detached registry signatures, transparency logs, or multi-process locks;
- encrypted/keychain secret storage or reliable performance estimates;
- uninstall/update/log-view actions for the new capability fixture;
- automatic refresh, implicit credential writes, or quality-gate bypasses.

## ComfyUI follow-up

ComfyUI remains a planned adapter, not a phase-1 claim. The next slice should
first define a version-pinned local Runtime contract and localhost-only API
health check, then model/workflow compatibility metadata. Installation should
use reviewed platform-specific runners, safe model formats, checksums, size and
disk budgets, source/license evidence, resumable/cancellable tasks, and cleanup/
rollback. Workflow JSON must be validated against a HanClassStudio allowlist
before activation; custom nodes and arbitrary Python are out of scope until a
separate sandbox and supply-chain review exist.
