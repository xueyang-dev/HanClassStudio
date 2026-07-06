# Demo Recording Checklist

## Before Recording

- Run tests:

  ```bash
  npm test
  ```

- Start backend:

  ```bash
  npm run dev:api
  ```

- Start frontend:

  ```bash
  npm run dev:web
  ```

- Open the workbench at `http://localhost:5173`.
- Prepare a small PPTX/PDF sample.
- Close unrelated browser tabs.
- Reset zoom to 100%.
- Use a clean browser window and readable font size.
- Confirm the backend health route works at `http://localhost:8000/api/health`.
- Optional: clear old `runtime/projects` demo clutter if it distracts from the recording.

## Recording Flow

1. Introduce HanClassStudio as an agent-compatible interactive courseware pipeline.
2. Upload a PPTX/PDF.
3. Show course profile confirmation.
4. Select generation mode and scaffolding language.
5. Run `一键生成课件`.
6. Show route badge and pipeline phases.
7. Show quality panel, Spec Lock Summary, and Artifact Inspector.
8. Demonstrate the slide-based runtime:
   - previous/next
   - keyboard left/right
   - fullscreen
   - slide list
   - language mode toggle
   - interactive component
9. Generate Agent Handoff files.
10. Show Agent task/rules and Validate Agent Output.
11. Export ZIP.
12. Show exported `lesson.html` and `assets/data` artifacts.

## After Recording

- Check audio clarity.
- Check that text in the browser is readable.
- Confirm no secrets, local tokens, or private paths are shown.
- Trim dead time during upload/generation.
- Add short title cards only if needed.
- Keep the final video around 3 to 5 minutes.

## Common Failures And Recovery

- Backend unavailable: restart with `npm run dev:api`.
- Frontend unavailable: restart with `npm run dev:web`.
- Upload fails: use a small PPTX fixture and retry.
- Preview stale: click render again or refresh the iframe.
- Quality blocked: show it as a feature, then fix the blueprint or use a known-good sample.
- Export disabled: check quality state and use force export only if the demo explicitly explains it.
- Agent validation blocked: show readable blocking messages, then fix the named artifact.
- Browser UI too small: increase zoom to 110% before recording.

