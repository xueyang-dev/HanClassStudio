# Templates And Specs

## Template Kinds

HanClassStudio should use four independent template kinds.

| Kind | Directory | Owns | Does not own |
|---|---|---|---|
| `brand` | `templates/brands/<id>/` | colors, fonts, logo, visual tone | pedagogy, slide flow |
| `pedagogy` | `templates/pedagogy/<id>/` | method constraints, sequencing policy, scaffolding style | lesson-specific goals, evidence, or activities |
| `runtime` | `templates/runtimes/<id>/` | HTML runtime, component renderer, layout shell | lesson content |
| `courseware` | `templates/courseware/<id>/` | full lesson shell: brand + pedagogy + runtime | source material facts |

This splits "how it looks", "how it teaches", and "how it runs".

## Template Package Shape

```text
templates/<kind>/<template_id>/
  template_spec.md
  template_lock.json
  assets/
    images/
    audio/
    fonts/
  runtime/
    styles.css
    runtime.js
    components.json
```

Only `runtime` and `courseware` templates need runtime files.

## lesson_spec.md

Human-readable teaching design.

Recommended sections:

```markdown
# Lesson Spec

## Source Summary

## Audience

## Teaching Goal

## Generation Route

## Lesson Flow

## Language Scaffolding

## Interaction Design

## Media Strategy

## Visual And Runtime Direction

## Quality Policy
```

`lesson_spec.md` explains why choices were made. It is not the machine authority for lesson-specific goals, evidence, or activities; those belong in the State-Evidence learning artifacts.

## spec_lock.json

Machine-readable execution contract.

Example shape:

```json
{
  "schema": "hanclassstudio.spec_lock.v1",
  "route": "main-generation",
  "lesson": {
    "title": "第14课 我在学习中文呢",
    "learner_level": "Beginner",
    "target_students": "International Chinese learners",
    "duration_minutes": 45,
    "scaffolding_language": "English"
  },
  "templates": {
    "brand": null,
    "pedagogy": "task_based_beginner",
    "runtime": "fresh_classroom",
    "courseware": null
  },
  "pedagogy": {
    "method": "guided_redesign",
    "objectives_count": 3,
    "max_new_words": 8,
    "grammar_focus_count": 1
  },
  "runtime": {
    "language_modes": ["zh", "scaffold", "bilingual"],
    "offline_required": true,
    "keyboard_required": true
  },
  "components": {
    "allowed": [
      "AudioButton",
      "VocabularyFlipCard",
      "SentenceDragBuilder",
      "ListenAndChoose",
      "MatchGame"
    ]
  },
  "media": {
    "image_policy": "placeholder-or-provider",
    "audio_policy": "placeholder-or-provider",
    "video_policy": "optional"
  },
  "quality": {
    "block_on_missing_interaction_answers": true,
    "block_on_missing_files": true,
    "warn_on_placeholder_media": true
  }
}
```

Executor, media generation, and quality checks read this file for locked execution policy. `spec_lock.json` may constrain pedagogy but must not replace the lesson-specific learning state, evidence, and activity plans.

## Blueprint Artifacts

### lesson_blueprint.json

Currently owns the legacy production renderer structure:

- title
- objectives
- vocabulary
- grammar
- slides
- content blocks
- interaction components
- media requirements

It is a compatibility and authoring contract for the current production route. It must not become the authority for learner state, learning goals, evidence, or learning activities. The canonical v2 presentation structure lives in `presentation/presentation_blueprint.json` and remains shadow/internal during migration.

### interaction_plan.json

Optional extracted interaction contract:

```json
{
  "schema": "hanclassstudio.interaction_plan.v1",
  "interactions": [
    {
      "slide_id": 5,
      "component_id": "sentence_drag",
      "component_type": "SentenceDragBuilder",
      "requires_answer": true,
      "requires_audio": false
    }
  ]
}
```

This can be derived from `lesson_blueprint.json` at first. It becomes useful when interactions become richer.

### media_plan.json

Media generation manifest:

```json
{
  "schema": "hanclassstudio.media_plan.v1",
  "images": [
    {
      "id": "slide_1_scene",
      "slide_id": 1,
      "prompt": "Clean classroom illustration...",
      "aspect_ratio": "16:9",
      "required": true
    }
  ],
  "audio": [
    {
      "id": "word_1",
      "text": "学习",
      "voice": "default",
      "required": true
    }
  ],
  "video": []
}
```

## Component Registry

The component registry prevents frontend, renderer, and quality checks from drifting.

Target file:

```text
courseware/components/registry.json
```

Example:

```json
{
  "VocabularyFlipCard": {
    "renderer": "builtin",
    "requires": ["items"],
    "optional": ["audio_key", "audio_text"],
    "quality": ["items_not_empty"],
    "accessible": true
  },
  "SentenceDragBuilder": {
    "renderer": "builtin",
    "requires": ["words", "answer"],
    "quality": ["answer_not_empty"],
    "accessible": true
  },
  "ListenAndChoose": {
    "renderer": "builtin",
    "requires": ["choices", "answer", "audio_key"],
    "quality": ["answer_in_choices", "audio_exists"],
    "accessible": true
  },
  "MatchGame": {
    "renderer": "builtin",
    "requires": ["pairs"],
    "quality": ["pairs_not_empty"],
    "accessible": true
  }
}
```

The frontend should only offer components that exist in this registry, unless explicitly marked experimental.

## Template Fusion

When multiple templates are selected:

| Selected templates | Fusion behavior |
|---|---|
| brand only | Lock visual identity, let pedagogy/runtime be chosen |
| pedagogy only | Lock lesson method, let visual/runtime be chosen |
| runtime only | Lock HTML runtime, let lesson design be chosen |
| courseware only | Use full shell as default |
| brand + pedagogy | Brand owns visual identity, pedagogy owns teaching flow |
| brand + runtime | Brand owns visuals, runtime owns rendering mechanics |
| pedagogy + runtime | Pedagogy owns flow, runtime owns UI components |
| courseware + override | Explicit brand/pedagogy/runtime overrides replace that segment |

Fusion is segment-level, not field-level. If two templates own the same segment, ask the user to choose.
