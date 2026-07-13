# Contract Fixes Release Note

## Scope

This release hardens the `fad3ec8` WebUI/backend contract baseline. It does not change the courseware component registry or generated lesson format.

## User-visible changes

- Provider settings responses are now write-only for credentials: API keys are never returned or served from the runtime static directory. Clients receive `api_key_present` instead.
- Provider readiness is explicit. The deterministic offline LLM is the supported no-credential path; unavailable, unimplemented, and execution-failed providers surface structured blockers instead of placeholder success.
- Export state is authoritative and four-layered. Missing gate reports are `not_run`; ordinary export requires all gates plus Blueprint and Render artifacts. Forced export cannot bypass missing or malformed technical prerequisites.
- OCR/profile/Blueprint/media/render changes persist downstream `stale` state. Stale previews and ZIP/PPTX downloads are not exposed as current results.
- Projects created before revision metadata existed remain readable, but their artifact lineage is marked unknown and requires regeneration/confirmation before use.
- Project mutations can carry `expected_revision`; conflicts return a structured 409. The WebUI debounced settings save uses request sequencing and cancellation so late responses cannot overwrite newer settings.

## Compatibility

Existing projects are read with safe defaults without an automatic rewrite. Existing API callers that omit `expected_revision` remain accepted, but new clients should send the revision returned by `ProjectState`.

## Verification

- Backend: 429 passed, 1 skipped, 6 warnings.
- Frontend state contract test: passed.
- Frontend TypeScript check and production build: passed.
- Browser contract E2E: one Chromium test covering upload, refresh/URL restoration, `not_run` gate state, and disabled export controls.
- CI now installs Chromium and runs the same browser contract test after the existing API and frontend checks.
