# Provider Registry and Installation Lifecycle

HanClassStudio exposes provider installation as a backend-owned contract. The
current registry is a first-party, mock-only fixture for validating the UI and
state transitions; it does not clone GitHub/Hugging Face repositories or run
provider-supplied shell commands.

## Registry contract

The catalog carries a monotonic `catalog_version`, timezone-aware
`generated_at`, fixed `source_revision`, and whole-catalog `content_digest`.
Each entry has a stable `provider_id`, capability, publisher, distinct code and
model-license metadata, trust level, fixed version/ref, artifact SHA-256, manifest version/digest, structured
configuration schema, and environment requirements. Floating refs (`main`,
`latest`, and similar values), untrusted hosts, repository/source mismatches,
missing checksums, unknown manifest schemas, and invalid manifest digests are
rejected before the entry can be served. Manifest steps are a closed enum; the
registry never accepts an arbitrary command or shell fragment.

The current explicit trust store contains only `xueyang-dev/HanClassStudio` on
GitHub. A self-declared `verified_maintainer` value cannot expand that trust
boundary; adding another repository requires an intentional registry change and
review.

The bundled first-party sandbox fixtures display version `0.1.0` but pin their
source and LICENSE evidence to commit
`69b5f7dfe1231c4dd2e504a47c5d85992efb558a`; the version label is not treated as
a Git ref. The checked-in catalog, manifest refs, artifact checksums, manifest
digests, and catalog digest are generated from that same fixed source ref.

Registry discovery is deliberately user-triggered. Normal application startup,
`GET /api/providers/registry`, capability polling, and project loading read only
the bundled index or the last validated local cache; none of them contact an
external catalog. Clicking **Check catalog updates** calls
`POST /api/providers/registry/refresh`, which downloads the first-party
`providers/registry.v1.json` index from a backend-controlled, 40-character
commit-pinned URL
over HTTPS. It rejects redirects, requires the initial DNS resolution to remain
on public addresses, applies connection, read, and total timeouts, and enforces
the one-megabyte limit while bytes are read rather than trusting
`Content-Length`. Only a complete catalog with valid schema, bounds, unique IDs,
source/ref consistency, license policy, manifests, and whole-catalog digest can
replace the cache. If the request or validation fails, the last valid catalog
remains active. The feed is a curated HanClassStudio trust boundary, not a
GitHub/Hugging Face popularity search, and it cannot authorize a repository
outside the explicit trust store. A process-local single-flight lock rejects
overlapping refreshes; an older catalog version, or different content reusing
the active version, is rejected.

### Cache commit-point contract

The cache is written with a single explicit commit point so that the API
result, the active on-disk cache, and the persistence contract never
contradict each other:

1. **Pre-commit.** A same-directory temporary file is created, written,
   flushed, and `fsync`ed. If temp creation, the write, the flush, or the
   file `fsync` fails, the target file is never touched, the temporary file
   is cleaned up, and the refresh returns a structured
   `provider_registry_cache_write_failed` error. The previous cache remains
   the active cache.
2. **Commit.** `os.replace()` is the single explicit commit point. Once it
   returns, the new cache is the active cache on disk. If `os.replace()`
   itself fails, the previous cache is still untouched and the same
   structured write failure is returned.
3. **Post-commit durability.** On platforms that support it, the parent
   directory is `fsync`ed and the directory descriptor is closed after the
   commit to improve crash-durability. Because the commit has already
   happened, a directory `fsync` or close failure is never reported as a
   write failure: doing so would tell callers the old cache is still in use
   while subsequent reads already observe the new one.
   A platform or filesystem that explicitly does not support directory
   `fsync` (for example `EINVAL`, `ENOSYS`, `ENOTSUP`, or `EPERM`) is
   treated as a best-effort durability warning and the refresh succeeds.
   Any other `OSError` from the directory sync or close is also treated as a
   durability warning rather than a write failure, because the new cache is
   already active; the warning is recorded with its stable `errno` for
   observability and never silently ignored. The raw exception message is
   never persisted, so a filesystem error containing sensitive material
   cannot leak through the warning log.

This means a refresh either returns a structured failure with the previous
cache still active (pre-commit or commit failure), or returns success with
the new cache active (post-commit, regardless of directory sync or close
outcome).
The API never returns "refresh failed" while the new cache is already the
active cache on disk.

### DNS resolution boundary

The refresh transport checks the initial DNS resolution of the official host
and rejects non-public addresses, but it does **not** pin the HTTPS connection
to the verified IP. `HTTPSConnection(hostname)` re-resolves the hostname when
establishing the connection, so a DNS answer that changes between the
check and the connection (a TOCTOU gap) is not fully mitigated. TLS SNI and
hostname verification are still performed by the default SSL context. Pinning
the connection to the already-verified resolved IP, while preserving TLS SNI
and hostname verification, is recorded as a follow-up P2 hardening item and is
not claimed by this PR.

The `GET /api/providers/registry` response separates registry availability from
installation facts:

- `available_version` is the version currently offered by the registry.
- `installed_version` and `active_version` are versions actually installed and
  activated locally.
- `install_actions` is generated by the backend; the WebUI does not infer an
  action from a file or a displayed status.
- Environment blockers, configuration status, rollback availability, and
  structured failures are persisted and returned as facts.

The same facts are projected into `GET /api/settings/providers/capabilities`.
Registry-backed descriptors keep `install_state`, `configuration_status`,
`install_actions`, blockers, and failure details aligned with the registry; a
production provider is `available` only when a real executor and the backend
capability contract say so. A mock lifecycle may reach its internal
`install_state=available`, but its capability descriptor remains
`implemented=false`, `configurable=false`, and `available=false`.
The WebUI uses this contract for both model settings and first-use onboarding.
Capability descriptors distinguish official homepages, API application pages,
API documentation, repositories, model cards, code licenses, model-weight
licenses, service terms, and privacy policies. Cloud providers link to their
official API pages; local providers and Registry entries link to validated
official project sources. The client never builds these URLs from provider
names and refuses non-HTTPS or credential-bearing links.

When the selected local capability has no available provider, onboarding shows
only the matching registry entries. Preparing and confirming an installation
or completing configuration refreshes both endpoints in place, so the user
returns to the same capability selector without a browser refresh. Installed
but unconfigured entries remain out of usable provider options. The current
mock fixtures never enter those options because no production executor exists.

## Lifecycle

```text
discovered → ready → installing → installed → configuring → available
                         └──────────────→ failed
```

Illegal transitions are rejected. `POST .../install/prepare` only creates a
short-lived plan and confirmation token. A newer prepare supersedes the prior
plan. `POST .../install/confirm` requires the persisted plan to be current and
single-use, and validates the token, provider, fixed version, source ref,
checksum, manifest digest, exact structured steps, plan digest, and expiry. A
consumed or superseded plan cannot be replayed. The executor accepts only the
closed set of structured step kinds in the manifest.

Secret-required providers stop in `configuring` until the schema-driven form is
submitted. The API stores only non-secret configuration and presence flags; API
keys never appear in registry responses, installation records, logs, or audit
events.

Installation records and plans use temporary files plus atomic replacement;
read/transform/write operations are serialized by a process-local lock so
concurrent providers do not lose each other's plans. Corrupt JSON is reported as
a structured persistence error instead of being treated as an empty registry or
silently reset. Logs and audit events are append-only JSONL files with sanitized
messages and stable event IDs. A failed upgrade retains the previous active
version and only exposes rollback when the backend reports that action;
rollback from either `failed` or an upgraded `available` state records the
original version, target version, reason, and result.

An `installing` record older than 15 minutes (or with an invalid start marker)
is recovered as a retryable `failed` state on the next read. Unexpected
executor exceptions are converted to a controlled failure code and are never
stored verbatim. An available record with missing activation/configuration facts
is failed closed as `provider_state_inconsistent` rather than being exposed as
usable.

The persistence lock is intentionally process-local. The current development
API runs as one worker; a multi-worker or multi-process deployment must add an
external lock or transactional store before claiming cross-process installation
mutual exclusion. This PR does not pretend to provide that distributed lock.

Secret-like fields are removed from public settings and browser persistence; the
API exposes only presence flags. Logs, audit messages, and structured error
messages redact API keys, bearer/authorization values, token/password/secret
fields, and URL query credentials, including JSON-shaped messages.

`license_status` is an action gate, not merely display text. Unknown, custom,
review-required, or gated licenses expose no install action. An approved entry
must include a recognized code license and a validated license URL; entries
with model files must separately identify an approved model-weight license.
The license display does not grant installation authority or replace the user's
obligation to comply with applicable terms.

Provider names, code, models, and trademarks remain the property of their
respective owners. HanClassStudio presents verified source links and controlled
installation plans; it does not grant rights to third-party software. Users and
deployers must comply with each provider's license and service terms. This is
shown in the Registry UI instead of making an unverifiable blanket
non-infringement claim.

## Current scope

`hcs_mock_ocr` and `hcs_mock_llm` are deterministic first-party fixtures used by
API and Playwright tests. The explicit refresh mechanism can update this curated
catalog, but the current entries remain mock-only. Real provider downloads, dependency
installation, GPU validation, and model acquisition require a future executor
implementation and a separate security review. Until then the UI labels these
entries as sandbox lifecycle exercises, the plan and logs state that no
checkout, download, dependency installation, model acquisition, or production
activation occurs, and the capability contract never reports them as
executable. Environment checks can report platform, architecture,
Python, disk, memory, and GPU blockers, but no real executor consumes those
requirements yet.

The catalog digest and pinned first-party transport protect against malformed,
stale, and equivocated catalog responses. This version does not implement a
detached signature or transparency log and therefore does not claim to defend
against a complete compromise of the official source and repository account.

Current security boundaries:

- No detached signature or transparency log; compromise of the allowlisted
  official repository/account is not fully mitigated.
- Refresh and install locks are process-local and assume one API worker.
- The refresh transport checks the initial DNS resolution of the official host
  and rejects non-public addresses, but does not pin the HTTPS connection to
  the verified IP. `HTTPSConnection(hostname)` re-resolves the hostname, so a
  DNS answer that changes between the check and the connection (a TOCTOU gap)
  is not fully mitigated. TLS SNI and hostname verification are still enforced
  by the default SSL context. Pinning the connection to the already-verified
  resolved IP, while preserving TLS SNI and hostname verification, is a
  follow-up P2 hardening item.
- There is no real third-party executor, repository discovery, arbitrary shell
  execution, or automatic external tool installation in this version.
