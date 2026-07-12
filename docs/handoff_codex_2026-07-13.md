# Handoff — HanClassStudio full project state (2026-07-13)

**Project:** HanClassStudio (FastAPI backend `apps/api` + React/Vite/TS frontend `apps/web`)
**Author:** WorkBuddy
**For:** Codex — take over from here.
**Status:** ✅ Main app is wired end-to-end and merged to `main`. One feature area
(`source_understanding` OCR layer) is MVP-grade and needs further work (see §4).

---

## 0. TL;DR for Codex

- Everything is on `main` (also reachable via `pilot/greetings-raster-lesson`, same commit).
- Backend provider config now **drives real generation + OCR** (was localStorage-only).
- Frontend got an **Apple HIG visual refresh** + the modal sheets were just made **opaque**.
- Full backend test suite is green: **403 passed, 1 skipped**.
- The backend import-depends on `apps/api/src/hcs_api/source_understanding/` — do not delete it.

---

## 1. Git / branch state (read this before you touch anything)

```
Current branch: main
main is AHEAD of origin/main by 12 commits (not pushed yet).
pilot/greetings-raster-lesson == main (same commit, fast-forward merged).

Recent commits:
  f064df0 fix(web): make modal sheets opaque instead of translucent glass
  c30ac38 feat: provider backend integration, Apple UI refresh, and source-understanding OCR layer
  ... (10 earlier pilot commits)
```

**Action for Codex:** if you need the code on the remote, push `main` (shared-repo
caution) or push to a dedicated branch. Nothing is uncommitted; working tree is clean.

---

## 2. Provider configuration — now backend-driven (completed)

Before this work, provider settings lived only in `localStorage` and did not affect
generation or OCR. Now:

**Backend (`apps/api/src/hcs_api/`)**
- `models.py`: `ProviderSettings` gained `ocr`, `video` (`OCRProviderSettings` /
  `VideoProviderSettings`) and a `capabilities: dict` field — the **frontend config is the
  single source of truth**; flat `llm/image/audio` fields are kept for the media pipeline.
- `main.py`:
  - `_apply_capabilities(settings)` derives flat `image`/`audio`/`ocr`/`video` from
    `settings.capabilities` on every `PUT /api/settings/providers`.
  - `_resolve_ocr_engine(force_engine, settings)` falls back to the configured provider
    (`paddle_ocr` / `tesseract`) when no explicit engine is given; surfaced via
    `GET /api/ocr/status` → `configured_engine`.
  - `upload_project` and `rerun_ocr` consume the resolved engine.

**Frontend (`apps/web/src/`)**
- `api.ts`: `configToBackend` / `backendToConfig` round-trip translation; `fetchProviderSettings`
  / `putProviderSettings`.
- `App.tsx`: on mount, load backend config (or push local config up); `providerConfig` changes
  auto-sync to backend (400 ms debounce). `ModelSettingsModal` shows "设置已保存到服务器" when synced.
- `i18n.tsx`: 6 locales updated (`settings.savedToServer` etc.).

**Test contract:** `tests/test_api_routes.py::test_provider_settings_round_trip` asserts the
flat `llm/image/audio` round-trips and that `ocr/video/capabilities` are present (not exact
object equality — the model grew fields).

---

## 3. Frontend visual state (Apple HIG + opaque modals)

`apps/web/src/styles.css` is the only UI file changed (App.tsx logic untouched):
- SF / system font stack; cool Apple neutral grays; brand teal `#0a8276`; Apple semantic colors.
- Vibrancy glass sidebar/topbar/panels (backdrop-filter blur+saturate, hairline border).
- Pill buttons (`--radius-pill: 980px`), authentic segmented control, materialized modal entrance.
- **System dark mode** (`prefers-color-scheme: dark`): black canvas, `#1c1c1e` surfaces, teal `#30d1c0`.
- **Modal fix (latest):** `.settings-modal`/`.onboarding-modal` are now **solid surfaces**
  (`--modal-bg`, `backdrop-filter: none`); scrim deepened to 0.52 (light) / 0.78 (dark).
  This was the user's explicit complaint — keep modals solid, do NOT reintroduce glass on the sheet.
- `prefers-reduced-transparency` falls glass back to solid surfaces.

Sidebar provider-status block was simplified to a single "模型服务状态" entry (the 4 capability
mini-cards + OCR mini-row + setup button were removed from `ProviderStatusPanel` in App.tsx).

---

## 4. `source_understanding` OCR layer (MVP — continue here)

See the dedicated `docs/handoff_source_understanding_2026-07-12.md` for full detail. Summary:

- 7-stage pipeline at `apps/api/src/hcs_api/source_understanding/` turns PDF/PPTX/images into a
  normalized `SourceAnalysisResult` (per-block bbox, reading order, confidence, source_method,
  needs_review, evidence crops).
- **Working:** PaddleOCR PP-OCRv6 reads scanned Chinese far better than Tesseract (verified on
  Lesson 1 of *Short-Term Spoken Chinese* 4th ed.: conf 0.973 vs 0.614).
- **Not done:** full PP-StructureV3 layout/tables/formulas (model download times out on this
  network); PaddleOCR-VL stubbed, not wired to a real model; OCR output is **not yet consumed**
  by downstream blueprint / interaction / media plans or the quality gate.
- `main.py` / `parser.py` import this module — keep it.

**Suggested Codex next steps (pick one):**
1. Wire `SourceAnalysisResult` into the downstream teaching-plan / quality-gate consumption path.
2. Re-attempt PP-StructureV3 install in an environment with model-download access.
3. Add a human-reviewed ground-truth set to turn the Paddle/Tesseract comparison into a real CER
   benchmark (currently a directional smoke test only — confidence numbers are not accuracy).

---

## 5. How to run / verify

```bash
# Backend (venv already created at apps/api/.venv)
cd apps/api
PYTHONPATH=src .venv/bin/python -m uvicorn hcs_api.main:app --reload --port 8000

# Backend smoke
curl -s http://127.0.0.1:8000/api/health
curl -s http://127.0.0.1:8000/api/ocr/status      # note configured_engine

# Full backend tests
cd /Users/xueyang/Dev/HanClassStudio
PYTHONPATH=apps/api/src apps/api/.venv/bin/python -m pytest apps/api/tests/ -q   # 403 passed, 1 skipped

# Frontend (managed node 22.22.2)
cd apps/web
/Users/xueyang/.workbuddy/binaries/node/versions/22.22.2/bin/npm run dev       # or `npm run build` + `npm run preview`
```

---

## 6. Cautions / open items

- **Local preview server dies between sessions** (background process reclaimed). For a stable URL,
  deploy the `apps/web/dist` build to CloudStudio.
- `main` is 12 commits ahead of `origin/main` and **not pushed** — confirm push target before
  publishing (shared repo).
- Do not re-introduce translucent glass on modal sheets (user explicitly disliked it).
- The 1 skipped test is pre-existing, not a regression.
