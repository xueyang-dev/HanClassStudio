# Contributing

HanClassStudio is a local-first, demo-ready alpha for international Chinese interactive courseware generation. It uses an artifact-first pipeline, Agent Handoff, a quality gate, and offline exports.

## Local Development

Install dependencies:

```bash
npm install
npm run install:web
uv sync --project apps/api
```

Run the backend:

```bash
npm run dev:api
```

Run the frontend:

```bash
npm run dev:web
```

Open `http://localhost:5173`.

## Tests

Run the full check:

```bash
npm test
```

This runs backend pytest and the frontend TypeScript/Vite build.

## Agent Workflow Notes

- Read `AGENTS.md` and `skills/hanclassstudio/SKILL.md` before editing project artifacts.
- Agents may edit specs and blueprints, but must not directly edit `courseware/lesson.html`, `exports/`, or `uploads/`.
- Use only components from `courseware/components/registry.json`.
- Do not bypass quality gate.
- PPTX and HTML outputs are derived export artifacts.

## Pull Request Requirements

Please include:

- What changed and why.
- Test results, especially `npm test`.
- Whether the change affects artifact schema, quality gate, runtime export, or Agent Handoff.
- Screenshots or short notes for frontend-visible changes.

