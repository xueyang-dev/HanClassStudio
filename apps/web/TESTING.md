# HanClassStudio Web Regression Checklist

Use this checklist for manual smoke testing before handing a frontend build to teachers or before wiring real model providers.

## Setup

- Start backend: `npm run dev:api`
- Start frontend: `npm run dev:web`
- Open `http://127.0.0.1:5173/`

## Core Workflow

- Upload a `.pptx` or `.pdf` file.
- Confirm the parsed source preview appears.
- Save the lesson profile.
- Confirm the top status changes to `Profile confirmed`.
- Select generation mode and scaffolding language.
- Generate blueprint.
- Edit at least one slide title.
- Expand and collapse slide editor cards.
- Edit content block text and scaffolding explanation.
- Edit media prompt, audio text, and video scene prompt.
- Add and remove at least one component type.
- Save blueprint.
- Generate media.
- Render HTML.
- Confirm preview iframe loads.
- Confirm quality report is grouped into Errors, Warnings, and Passed checks.
- Confirm export ZIP button is disabled before render and enabled after render.
- Download the ZIP export.

## Full Pipeline

- Upload a fresh `.pptx` or `.pdf`.
- Save the lesson profile.
- Click `一键生成课件`.
- Confirm pipeline status shows:
  - Preparing profile
  - Generating blueprint
  - Generating media
  - Rendering HTML
  - Export ready
- Confirm preview and export links refresh after the pipeline completes.
- Confirm readable UI error appears if the backend is stopped during the run.

## Provider And Settings UI

- Confirm the sidebar shows `模型服务状态`.
- Confirm LLM, Image, TTS, Video, and OCR provider rows are visible.
- Open `Model Settings`.
- Confirm all fields are disabled placeholders.
- Confirm the modal explains that current configuration is handled by backend environment variables or backend console.

## Build Check

```bash
npm --prefix apps/web run build
```
