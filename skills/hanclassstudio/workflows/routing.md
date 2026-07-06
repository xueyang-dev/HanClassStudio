# Routing

Choose one route before editing specs or blueprints.

## Routes

| Route | Use when | Output focus |
|---|---|---|
| `main-generation` | Source material should be redesigned into a stronger lesson flow | new lesson structure |
| `faithful-enhance` | Preserve original page order and wording while adding light enhancement | source-faithful courseware |
| `topic-research` | User provides only a topic, not source material | research notes for later source intake |
| `template-fill` | Fill an existing courseware/template structure with new lesson content | template-bound artifacts |
| `media-refresh` | Keep lesson structure but regenerate or replace media | updated media plan and assets |
| `refine-blueprint` | Improve existing lesson structure or interactions after review | updated blueprints |
| `runtime-review` | Inspect rendered courseware, quality report, or export readiness | findings and upstream fixes |

## Ambiguous PPT Requests

For requests like "optimize this PPT" or "generate courseware", ask exactly one discriminator:

> Should the original page order and wording be preserved, or should the lesson flow be redesigned?

Preserve original page order and wording -> `faithful-enhance`.

Redesign the lesson flow -> `main-generation`.

