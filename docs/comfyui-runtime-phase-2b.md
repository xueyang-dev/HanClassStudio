# Controlled ComfyUI Runtime — Phase 2B

Phase 2B defines a controlled local ComfyUI **Runtime** for HanClassStudio. It is
infrastructure for a future fixed image Model Package; it is not an image
generator by itself. The current manifest deliberately exposes no installable
platform because the reviewed uv/Python/wheel artifact set is incomplete.

```text
Provider Hub
→ reviewed adapter/toolchain gate
→ teacher starts an install task when enabled
→ pinned official source download
→ SHA-256 and archive safety gates
→ isolated fixed Python environment
→ durable publish journal
→ managed loopback process
→ ComfyUI API identity and core-node health check
→ stop / repair / uninstall
```

The invariant exposed in both API and UI is:

```text
runtime_ready ≠ generation_ready
```

`generation_ready` is always `false` in Phase 2B. The card says
“运行环境可用，但尚未安装图片模型。” and exposes no image-generation action.

## Official source and immutable identity

| Fact | Pinned value |
| --- | --- |
| Project | [Comfy-Org/ComfyUI](https://github.com/Comfy-Org/ComfyUI) |
| Publisher | Comfy Org / upstream ComfyUI contributors |
| Release | `v0.28.0` |
| Commit | `700821e1364eaab0e8f21c538a2131719fec57bf` |
| Source archive | `https://codeload.github.com/Comfy-Org/ComfyUI/tar.gz/700821e1364eaab0e8f21c538a2131719fec57bf` |
| Archive size | 11,611,291 bytes |
| Archive SHA-256 | `326eb47c6f8f2bdd61a87095238250953f0e5bae61fbae13b68a8eec00e45c7a` |
| Extracted source-tree SHA-256 | `9a0930b7b26cf02e9a6392d340309f35ce88f4506d365374c95cd1f98caaa5a6` |
| License | `GPL-3.0-only` |
| Upstream license SHA-256 | `3972dc9744f6499f0f9b2dbf76696f2ae7ad8af9b23dde66d6af86c9dfb36986` |

GitHub codeload archives are generated from a commit rather than signed release
assets. HanClassStudio therefore binds the URL, full commit, exact byte length,
archive SHA-256, archive root, extracted full-tree SHA-256, upstream license,
and critical source-file hashes. If GitHub ever regenerates different bytes for the same commit, the
installer fails closed until the manifest is deliberately reviewed and updated.

The Runtime manifest is
`providers/comfyui/runtime-manifest.v1.json`. It is a strict data-only Pydantic
contract. It cannot carry shell commands, environment variables, arbitrary Git
URLs, custom-node declarations, workflow JSON, or model downloads. Installation
steps are fixed in HanClassStudio source.

HanClassStudio is not an official ComfyUI product. It downloads the official
source directly and supplies a lifecycle/security wrapper. The upstream
`LICENSE` file remains unmodified in the installed source. GPL distribution and
source-offer obligations must remain part of release packaging review.

## Platform support

| Platform adapter | Manifest status | Install enabled | Evidence |
| --- | --- | --- | --- |
| macOS Apple Silicon | `experimental` | no | Lifecycle and security fixtures only; fixed toolchain artifacts are incomplete |
| Windows x86_64 NVIDIA/CPU | `contract_only` | no | Contract only; not represented as verified |
| Linux x86_64 NVIDIA/CPU | `contract_only` | no | Contract only; not represented as verified |
| Other OS/architecture | `unavailable` | no | No reviewed adapter |

The architecture keeps platform selection explicit. No adapter is currently
install-enabled. It does not
install GPU drivers, CUDA Toolkit, DirectML, Homebrew packages, or system
components. Unsupported platforms receive a stable error and no install action.

## Isolated Python and dependency policy

The macOS contract requires:

- an exact application-bundled uv artifact, including version, source URL,
  byte length, and SHA-256; `PATH` lookup is forbidden;
- an exact application-bundled CPython `3.11.13` tree, including platform,
  architecture, source URL, byte length, tree identity, and executable path;
- a complete wheelhouse plus an artifact lock containing one exact filename,
  byte length, and SHA-256 for every direct and transitive dependency;
- the generated lock
  `providers/comfyui/locks/comfyui-macos-arm64-py311.lock`;
- lock SHA-256
  `926e90e5a1cb0bd81c783061880fd74ff35ded94c3132bda9862fd9e3fb61df0`;
- offline, no-index installation with `--require-hashes`,
  `--only-binary=:all:`, `--no-build-isolation`, and `--no-deps`;
- a configuration-free uv environment and a small environment-variable
  allowlist;
- `UV_PYTHON_DOWNLOADS=never`; no sdist, editable, direct-URL fallback, build
  backend, or dependency re-resolution;
- exact post-install Python and package-version comparison with the lock;
- the installed Python executable SHA-256 recorded and rechecked before start.

The requirements lock is an inventory, not by itself an install authorization.
Until the separate complete wheel artifact lock and bundled toolchain exist,
`toolchain_status=unavailable`, macOS installation remains disabled, and no
online or source-build fallback is permitted.

The installer never uses or modifies the user's global Python, HanClassStudio's
API virtual environment, or system packages. Repair rebuilds this managed
environment. Uninstall removes only the managed Runtime Python/cache. The
separate `provider-models/comfyui` boundary is preserved for Phase 2C.

## Download and archive security

The downloader accepts only the manifest's exact `https://codeload.github.com`
commit path. It rejects credentials, ports, query/fragment data, redirects,
non-public DNS results, unexpected HTTP status, unexpected content length,
timeouts, oversized streams, final byte-count mismatches, and SHA-256 mismatch.
Downloads go to owner-private staging and can be cancelled.

The tar reader never calls `extractall()`. It performs a full directory scan
before creating archive contents and enforces:

- exactly the pinned archive root;
- no `..`, absolute, Windows-drive, UNC/backslash, empty, dot, control-character,
  or non-NFC path segments;
- bounded UTF-8 path length and depth;
- no duplicate, Unicode-NFKC/casefold-colliding paths;
- regular files and directories only—no symbolic links, hard links, devices,
  FIFO, sockets, or sparse/special entries;
- no nested archive suffixes;
- limits on compressed bytes, entries, individual files, expanded bytes, and
  compression ratio;
- directory-fd-relative traversal from an opened trusted staging root;
- every directory opened with `O_DIRECTORY | O_NOFOLLOW`, and every output
  created with dir-fd-relative `O_NOFOLLOW | O_CREAT | O_EXCL`;
- written byte counts equal to inspected sizes;
- a second complete `lstat` traversal after extraction;
- exact critical-file, upstream-license, requirements, and official baseline
  custom-node hashes;
- archive hash and size verification again after extraction.
- exact full extracted-tree fingerprint bound to the reviewed manifest.

No extraction write re-resolves an absolute string path. Platforms without the
required directory-fd semantics are disabled rather than using an unsafe
fallback. Post-extraction checks are defense in depth, not the control that
prevents parent-directory replacement.

## Install journal and crash recovery

Every install, repair, and uninstall has a persisted transaction containing the
task/transaction IDs, operation, Runtime/version/manifest identity, platform
adapter, relative staging/final/backup/archive paths, expected archive hash,
published paths, phase, timestamps, stable error, and recovery policy.

```text
prepared
→ downloading → downloaded
→ archive_validated → tree_extracted
→ environment_created → dependencies_installed
→ runtime_validated → publish_prepared
→ runtime_published → state_committed → completed
                     ↘ rolling_back → rolled_back / failed
```

Journal paths are relative to the dedicated managed Runtime root and are
validated before resolution. Runtime source plus the relocatable environment is
published as one version directory. Repair first retains the previous complete
version as a backup and deletes it only after the new version validates and the
state commit is durable.

Recovery is idempotent and distinguishes the publish crash windows:

- pre-publish staging is removed and a retained backup is restored;
- if the payload has left staging and a complete final tree exists, the tree is
  revalidated and state commit is completed;
- invalid published data restores the previous version or marks
  `repair_required`;
- an interrupted uninstall resumes deletion only when the installation record,
  manifest, tree, trusted parent, and directory identities still agree;
- repeated recovery makes no additional changes.

HTTP Range/resumable download is not implemented. An interrupted download is
discarded and a retry starts from byte zero.

## Managed process and network boundary

The Process Supervisor persists PID, OS process-start token, process-group and
session IDs, executable and supervisor hashes, working directory, installation
identity, Runtime version/root, actual port, one-time nonce, supervisor/runtime
argv digests, listener PID/start token, and start time.

Start is permitted only after full source, custom-node, Python-version, and
locked-dependency validation. HanClassStudio builds an argv array and uses
`shell=False`; neither a manifest nor teacher input can introduce arguments.
The managed interpreter uses `-s`, so the pinned source directory remains
importable while user site-packages stay disabled; the environment allowlist
does not inherit `PYTHONPATH`.
The fixed arguments include:

```text
--listen 127.0.0.1
--disable-auto-launch
--disable-all-custom-nodes
--disable-api-nodes
--disable-metadata
```

Input, output, temp, user, model, home, and base directories are explicit
managed paths; the real user home is not inherited. A random nonce is embedded
in the per-start user-directory argument and
therefore appears in the API-reported argv used for service identity. The
environment is allowlisted and `PYTHONNOUSERSITE=1` is forced.

Ports come only from `8188..8288`. The supervisor tests loopback binding before
launch, skips occupied ports, never takes over another listener, saves the
selected port, and waits for identity health before returning ready. The small
bind/start race is handled by process-exit and API identity checks; a foreign
service can never satisfy the complete identity contract.

ComfyUI runs as a child of a small code-owned supervisor that remains the
independent session/process-group leader. Stop/force-stop requires its PID,
start token, PGID/SID, cwd, installation and source identities, exact argv,
executable/supervisor hashes, port, and nonce to agree. POSIX signals target
only that revalidated group. PID reuse or an edited process record produces
`runtime_identity_mismatch`; HanClassStudio does not send a signal. It never
uses process-name matching, `killall`, or another user's ComfyUI process.

Dependency/Python subprocesses run in their own session and persist a separate
worker ownership record. Cancellation, timeout, and parent exceptions terminate
that exact group. On restart, recovery revalidates PID/start token, PGID/SID,
cwd, executable, argv, and managed-root identity before reclaiming it; a
mismatch is never signalled. If the Runtime supervisor exits while an owned
child remains, the next health/snapshot/start path revalidates and reclaims only
that recorded group. Adjacent processes are outside this contract.

Runtime stdout/stderr is captured by a bounded rotating log. Logs redact the
HanClassStudio Runtime root, home directory, and common credential forms. APIs
return only a capped summary and never expose a local absolute path. The
directory API returns an opaque desktop action contract rather than a path.

## Health and custom-node policy

An explicit health check is more than PID, port, or HTTP 200. It verifies:

1. installation record, manifest-bound full source tree, exact Python, and every locked package;
2. official baseline `custom_nodes` content and no additions;
3. supervisor PID/start token, PGID/SID, cwd, executable, argv, source, and
   installation identity;
4. the target listener is owned by the same process group/session and listens
   only on `127.0.0.1`, never `0.0.0.0`, `::`, or another interface;
5. listener PID/start token, cwd, managed-Python identity, and argv;
6. `/system_stats` JSON shape and `comfyui_version == 0.28.0`;
7. API-reported argv equals the nonce-bearing managed argv;
8. `/object_info` exposes reviewed core nodes `KSampler`,
   `CheckpointLoaderSimple`, and `SaveImage`;
9. actual service port is the persisted managed loopback port.

The upstream source at this commit contains two official baseline files in
`custom_nodes`; “empty directory” would be an incorrect policy. Their exact
hashes are in the manifest, and `--disable-all-custom-nodes` prevents execution.
Any added, removed, linked, or changed file produces `unsupported_modified`.
HanClassStudio does not execute or silently delete the change. Repair asks for
explicit confirmation, explains that controlled source/environment and external
custom-node changes are replaced, and preserves the separate future model
directory.

## Provider Hub and API contract

The card's backend-authoritative states include `not_installed`, `installing`,
`stopped`, `starting`, `runtime_ready`, `stopping`, `crashed`, `degraded`,
`repair_required`, `unsupported_modified`, `incompatible`, and `failed`.
`available_actions` is the only action authority.

Lifecycle endpoints cover Runtime detail, install/task/cancel, start, stop,
force stop, health, prepare-repair, prepare-uninstall, repair, uninstall,
redacted logs, and the opaque local directory action. Repair and uninstall
require a short-lived one-time backend token bound to operation, Runtime ID,
installation identity, full current tree identity, modified state, nonce, and
expiry. Identity changes after preparation invalidate the token. The operations
then revalidate the same identity inside the mutation lock. Install/repair/
uninstall/cancel use the common asynchronous
`{task, provider}` response. Start/stop/health return the updated Provider item.
OpenAPI response models match these payloads.

The teacher UI shows understandable phases and errors, the official source and
license, estimated source download, platform support, the no-model boundary,
repair/uninstall impact confirmations, narrow-screen layout, and collapsible
technical data. It never embeds the ComfyUI node editor.

## Repair and uninstall

When an adapter has a complete reviewed toolchain, repair stops only an owned Runtime, downloads and verifies the pinned source
again, rebuilds the isolated environment, revalidates it, atomically publishes
the replacement, runs through the same journal, and retains the previous valid
version until commit. It does not modify the separate future model directory.

Uninstall verifies/stops the owned process and removes only paths authorized by
the installation record. Runtime logs and data are retained because they are
outside that record. It deliberately
preserves project assets, uploads, exports, other ComfyUI installations, user
Python, and `provider-models/comfyui`. An interrupted uninstall is resumed
idempotently.

## Test layers

- Archive unit tests use project-controlled security regression fixtures and
  verify rejection plus containment, collision, link/special-file, nesting,
  depth/entry/file/expanded/compression, identity, and staging invariants.
- Installer tests cover publish journal phases, cancellation, concurrency,
  checksum/security-invariant failure, backup recovery, published-state reconciliation,
  interrupted uninstall, model/project preservation, and bounded/redacted logs.
- Process tests use a project-controlled ComfyUI HTTP fixture and cover
  supervisor/group ownership, orphan and worker recovery, adjacent-process
  preservation, listener ownership/address identity, nonce, core nodes, stop,
  crash, port conflicts, PID reuse protection, and log rotation.
- API/UI tests cover action gating and `runtime_ready`/`generation_ready`
  separation.
- Playwright covers the complete fixture lifecycle and archive security rejection at
  390 px, including the absence of a generation button.
- `test_comfyui_real_opt_in.py` remains skipped in normal CI. The current
  manifest disables installation, so it cannot pass until the fixed bundled
  uv/Python/wheel artifacts are supplied and reviewed.

## Real validation

A 2026-07-22 run exercised the earlier, less strict implementation. It is
historical evidence only and does not validate the current fixed-artifact,
supervisor/listener, ownership, or confirmation contracts. Current-code real
install/start/stop/repair/uninstall validation is blocked by the intentionally
unavailable toolchain and must be rerun before any adapter is enabled.

## Deliberately not implemented

- model/checkpoint, LoRA, VAE, ControlNet, or Civitai downloads;
- image generation or arbitrary workflow execution;
- custom nodes, ComfyUI Manager, or an advanced bypass;
- node-editor embedding;
- LAN/public binding or remote access;
- arbitrary Git/GitHub/Hugging Face sources or remote commands;
- GPU driver, CUDA Toolkit, DirectML, Homebrew, or system-Python installation;
- Windows/Linux executable adapters beyond contract-only declarations;
- HTTP Range download resume;
- Phase 2C Model Package, compatibility, activation, or generation readiness.

## Phase 2C seam

Phase 2C can add a separately pinned `ModelPackageSpec` with its own source,
license, byte/hash limits, safe-format validation, hardware compatibility, and
managed `provider-models/comfyui` ownership. It may reference this Runtime by
ID/version only after Runtime health passes. Model installation must not mutate
the Runtime source/environment, enable custom nodes, broaden network binding, or
grant workflow execution. None of that seam is activated in Phase 2B.
