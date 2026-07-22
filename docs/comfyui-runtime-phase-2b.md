# Controlled ComfyUI Runtime — Phase 2B

Phase 2B adds a controlled local ComfyUI **Runtime** to HanClassStudio. It is
infrastructure for a future fixed image Model Package; it is not an image
generator by itself.

```text
Provider Hub
→ teacher starts an install task
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
| macOS Apple Silicon | `experimental` | yes | Fixture coverage plus the opt-in real validation recorded below |
| Windows x86_64 NVIDIA/CPU | `contract_only` | no | Contract only; not represented as verified |
| Linux x86_64 NVIDIA/CPU | `contract_only` | no | Contract only; not represented as verified |
| Other OS/architecture | `unavailable` | no | No reviewed adapter |

The architecture keeps platform selection explicit, but Phase 2B deliberately
enables only the platform exercised in the development environment. It does not
install GPU drivers, CUDA Toolkit, DirectML, Homebrew packages, or system
components. Unsupported platforms receive a stable error and no install action.

## Isolated Python and dependency policy

The reviewed macOS adapter uses:

- uv-managed CPython `3.11.13` under the HanClassStudio Runtime root;
- uv `0.11.0` or newer, with the actual manager version recorded in the
  installation provenance;
- a relocatable virtual environment published with the Runtime;
- the generated lock
  `providers/comfyui/locks/comfyui-macos-arm64-py311.lock`;
- lock SHA-256
  `926e90e5a1cb0bd81c783061880fd74ff35ded94c3132bda9862fd9e3fb61df0`;
- `--require-hashes` and the explicit `https://pypi.org/simple` index;
- a configuration-free uv environment and a small environment-variable
  allowlist;
- exact post-install Python and package-version comparison with the lock.
- the installed Python executable SHA-256 recorded and rechecked before start.

The lock was generated from the pinned upstream `requirements.txt` for CPython
3.11.13 on `aarch64-apple-darwin`. It is the dependency inventory and includes
artifact hashes. Runtime installation logs record the resolved package names and
versions without logging the user's environment or private absolute paths.

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
- exclusive `O_EXCL`/`O_NOFOLLOW` file creation in a `0700` staging directory;
- written byte counts equal to inspected sizes;
- a second complete `lstat` traversal after extraction;
- exact critical-file, upstream-license, requirements, and official baseline
  custom-node hashes;
- archive hash and size verification again after extraction.
- exact full extracted-tree fingerprint bound to the reviewed manifest.

The private staging directory and exclusive creation close the relevant
same-user check/use window; the post-walk and second archive hash detect
replacement before publication. Any failure removes staging and never marks the
Runtime installed.

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
- an interrupted uninstall resumes deletion of only managed Runtime data and
  clears its state/journal/logs;
- repeated recovery makes no additional changes.

HTTP Range/resumable download is not implemented. An interrupted download is
discarded and a retry starts from byte zero.

## Managed process and network boundary

The Process Supervisor persists `ComfyUIRuntimeProcess`, process state, and
ownership facts: PID, OS process-start token, exact executable SHA-256, Runtime
version/root, actual port, one-time nonce, fixed argv digest, and start time.

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

Stop/force-stop requires the PID to match its original start token, exact HCS
argv, executable hash, Runtime root, port, and nonce. POSIX signals target only
the owned process group. PID reuse or an edited process record produces
`runtime_identity_mismatch`; HanClassStudio does not send a signal. It never
uses process-name matching, `killall`, or another user's ComfyUI process.

Dependency/Python subprocesses also run in their own process group. Task
cancellation, timeout, and parent-process exceptions terminate that exact group
before journal recovery proceeds, so an interrupted installer cannot keep
writing into staging after the API worker exits.

The current shutdown policy permits an owned Runtime to survive an API process
restart. The next API process can recover it only after the persisted ownership
checks. Unexpected exit becomes `crashed`; stale/mismatched identity becomes
`repair_required` and is never silently killed.

Runtime stdout/stderr is captured by a bounded rotating log. Logs redact the
HanClassStudio Runtime root, home directory, and common credential forms. APIs
return only a capped summary and never expose a local absolute path. The
directory API returns an opaque desktop action contract rather than a path.

## Health and custom-node policy

An explicit health check is more than PID, port, or HTTP 200. It verifies:

1. installation record, manifest-bound full source tree, exact Python, and every locked package;
2. official baseline `custom_nodes` content and no additions;
3. live PID ownership and start token;
4. `/system_stats` JSON shape;
5. `comfyui_version == 0.28.0`;
6. API-reported argv equals the nonce-bearing managed argv;
7. `/object_info` exposes reviewed core nodes `KSampler`,
   `CheckpointLoaderSimple`, and `SaveImage`;
8. actual service port is the persisted managed loopback port.

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
force stop, health, repair, uninstall, redacted logs, and the opaque local
directory action. Install/repair/uninstall/cancel use the common asynchronous
`{task, provider}` response. Start/stop/health return the updated Provider item.
OpenAPI response models match these payloads.

The teacher UI shows understandable phases and errors, the official source and
license, estimated source download, platform support, the no-model boundary,
repair/uninstall impact confirmations, narrow-screen layout, and collapsible
technical data. It never embeds the ComfyUI node editor.

## Repair and uninstall

Repair stops only an owned Runtime, downloads and verifies the pinned source
again, rebuilds the isolated environment, revalidates it, atomically publishes
the replacement, runs through the same journal, and retains the previous valid
version until commit. It does not modify the separate future model directory.

Uninstall verifies/stops the owned process, removes the managed Runtime version,
managed Python, uv cache, Runtime logs, state, and journal. It deliberately
preserves project assets, uploads, exports, other ComfyUI installations, user
Python, and `provider-models/comfyui`. An interrupted uninstall is resumed
idempotently.

## Test layers

- Archive unit tests use tiny tar fixtures and cover normal extraction,
  traversal, absolute/drive/UNC paths, symbolic and hard links, FIFO/special
  entries, duplicate/case/Unicode collisions, non-NFC names, nested archives,
  depth/entry/file/expanded/compression limits, hash/size failure, and existing
  staging refusal.
- Installer tests cover publish journal phases, cancellation, concurrency,
  checksum/unsafe failure, backup recovery, published-state reconciliation,
  interrupted uninstall, model/project preservation, and bounded/redacted logs.
- Process tests use a clearly named fake ComfyUI HTTP server and cover start,
  loopback/API identity, nonce, core nodes, stop, crash, occupied/full port
  range, PID reuse protection, external modification, and log rotation.
- API/UI tests cover action gating and `runtime_ready`/`generation_ready`
  separation.
- Playwright covers the complete fixture lifecycle and unsafe-archive failure at
  390 px, including the absence of a generation button.
- `test_comfyui_real_opt_in.py` is skipped in normal CI. It requires
  `HCS_RUN_REAL_COMFYUI_RUNTIME=1`, macOS Apple Silicon, uv, network, and 8 GB
  free disk.

## Real validation

The code-frozen opt-in test completed on 2026-07-22. It downloaded the pinned
official archive, created the fixed environment, started real ComfyUI, verified
the live API and listener, stopped the owned process, and uninstalled the
managed Runtime. It did not download a model or generate an image.

| Evidence | Result |
| --- | --- |
| Command | `HCS_RUN_REAL_COMFYUI_RUNTIME=1 HCS_COMFYUI_REAL_REPORT=/tmp/hcs-comfyui-real-validation.json PYTHONPATH=apps/api/src apps/api/.venv/bin/python -m pytest apps/api/tests/test_comfyui_real_opt_in.py -vv -s` |
| Test result | `1 passed in 646.28s` |
| Platform | macOS arm64, Apple M4 (10-core CPU, integrated 8-core GPU) |
| Managed Python | CPython `3.11.13` |
| Environment manager | uv `0.11.26` |
| Install time | 578.707 seconds |
| Installed version-directory bytes | 1,260,509,761 |
| Startup time | 62.981 seconds |
| Listener | `127.0.0.1:8188` only |
| API health | healthy; identity, core API, official custom-node baseline, and ComfyUI `0.28.0` verified |
| Stop | `stopped` |
| Uninstall | `not_installed`; managed version directory absent |
| Skip/degradation | none |

The report contains hashes and generic hardware facts but no personal absolute
paths. The adapter remains `experimental`: one development-machine run is real
evidence, not a claim of broad macOS compatibility. A skipped opt-in run is
reported as a skip, never as a pass.

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
