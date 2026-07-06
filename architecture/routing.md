# Routing Rules

Route selection decides which workflow owns a request. A wrong route creates bad courseware even if every later step works.

## Main Route Matrix

| Request shape | Trigger | Route | Output contract |
|---|---|---|---|
| Source material can be redesigned | PPTX, PDF, Markdown, text, or URL used as content | `main-generation` | New interactive courseware, page count and structure may change |
| Existing PPT/PDF should keep page order | User wants faithful conversion or lightweight interaction | `faithful-enhance` | Preserve original order and most source wording |
| Topic only | User provides only topic, audience, or teaching goal | `topic-research` then `main-generation` | Research notes become source input |
| Existing courseware HTML needs packaging | User has HTML and wants ZIP/offline check | `native-enhance` | Keep layout, add manifests, quality, package |
| Existing courseware template plus new material | User wants to fill a reusable courseware shell | `template-fill` | Keep template runtime/layout, replace lesson content |
| Create reusable template | User wants to reuse style, pedagogy, runtime, or whole lesson shape | `create-template` | Template package under `templates/` |
| Revise generated lesson plan | User edits objectives, slides, language, or activities before media/render | `refine-blueprint` | Updated blueprints and spec lock |
| Visual/runtime review | User asks to inspect UI or interaction behavior | `visual-review` | Findings and upstream fixes before export |
| Add or regenerate media | User asks for images/audio/video only | `media-refresh` | Updated media assets and manifest |

## Route Details

### main-generation

Use when the source is material, not a finished structure.

Allowed:

- merge, split, drop, or reorder source pages
- create new classroom flow
- choose new interactions
- generate new media

Forbidden:

- silently claiming source page order is preserved

### faithful-enhance

Use when source order and wording are part of the contract.

Locked:

- source page order
- main source text
- source images where feasible

Allowed:

- add scaffolding
- add audio buttons
- add simple checks
- wrap as interactive HTML

Stop condition:

- If the user asks to split, merge, or reorder pages, switch to `main-generation`.

### topic-research

Use when no source facts exist.

Outputs before main generation:

- `sources/source.md`
- `analysis/source_profile.json`
- citation/source list if web research is used

Stop condition:

- If reliable facts cannot be gathered, ask user for source material.

### template-fill

Use when a reusable courseware template already exists.

Template can lock:

- runtime layout
- component sequence
- visual theme
- pedagogical structure

Content can change:

- lesson title
- vocabulary
- grammar
- slide text
- media prompts

### create-template

Use to create reusable templates from:

- existing generated courseware
- teacher-designed HTML
- PPT/PDF design references
- brand identity
- pedagogy requirements

Outputs:

```text
templates/<kind>/<template_id>/
  template_spec.md
  template_lock.json
  assets/
  runtime/
```

### native-enhance

Use when rendered courseware is already good enough.

Allowed:

- add missing manifests
- add offline packaging
- add quality report
- add audio metadata
- patch minor runtime settings

Forbidden:

- redesigning lesson flow
- regenerating blueprint

## Ambiguity Rule

For requests like "optimize this courseware" or "make this PPT into a better lesson", ask one discriminator:

> Should HanClassStudio preserve the original page order and wording, or treat the material as source content and redesign the lesson flow?

Preserve means `faithful-enhance`. Redesign means `main-generation`.

## Template Name Boundary

| User input | Behavior |
|---|---|
| Explicit template path | Load that template |
| Bare template name | Search only if template discovery UI/API exists |
| Style description | Treat as strategist input, not template lock |
| PPTX called a template | Route to `template-fill` or `create-template`, not direct runtime template use |

