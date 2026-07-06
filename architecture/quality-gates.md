# Quality Gates

Quality gates decide whether a generated lesson can be previewed, exported, or handed to a teacher.

The goal is not perfection. The goal is to catch failures that make courseware unusable, misleading, inaccessible, or impossible to run offline.

## Quality States

| State | Meaning | Export |
|---|---|---|
| `pass` | No blocking issues | allowed |
| `warning` | Usable, but has quality concerns | allowed with report |
| `blocked` | Broken or unsafe for delivery | blocked unless forced |

## Gate Categories

### 1. Pedagogy Gate

Checks whether the lesson is instructionally coherent.

Blocking:

- no lesson title
- no objectives
- no slides
- learner level missing
- generated content clearly empty

Warnings:

- too many new words for level
- no grammar focus in a grammar lesson
- no practice after presentation
- scaffolding language missing for beginner/intermediate learners

### 2. Interaction Gate

Checks whether interactive components can run.

Blocking:

- component type unsupported by renderer
- required component data missing
- answer missing for graded interaction
- `ListenAndChoose` answer not in choices
- duplicated component IDs in one lesson

Warnings:

- interaction has no feedback text
- too many interactions on one slide
- component is marked experimental

### 3. Media Gate

Checks whether media references resolve.

Blocking:

- referenced image/audio/video file does not exist
- asset path escapes project root
- required audio key missing

Warnings:

- placeholder media used when real provider was requested
- image prompt empty
- generated media has no provider/model metadata
- audio text is too long for a button-level prompt

### 4. Runtime Gate

Checks whether courseware can run in the browser.

Blocking:

- `courseware/lesson.html` missing
- exported ZIP missing `lesson.html`
- required `assets/data/*.json` missing
- external network dependency in offline mode

Warnings:

- large ZIP size
- unused assets
- missing render manifest

### 5. Accessibility Gate

Checks basic classroom accessibility.

Blocking:

- buttons without accessible text
- interactive elements unreachable by keyboard
- iframe/preview render failure

Warnings:

- image without meaningful alt when it carries content
- color contrast below target
- animation without reduced-motion fallback
- audio-only activity without text fallback

### 6. Language Gate

Checks international Chinese teaching details.

Blocking:

- vocabulary item missing Chinese word
- pinyin field missing where vocabulary cards require it
- empty scaffold text when scaffold mode is locked as required

Warnings:

- pinyin tone format inconsistent
- English scaffold too long
- mixed simplified/traditional Chinese without explicit policy
- vocabulary examples do not include target words

## Report Shape

Target file:

```text
quality/quality_report.json
```

Example:

```json
{
  "schema": "hanclassstudio.quality_report.v1",
  "state": "warning",
  "blocking": [],
  "warnings": [
    "Slide 3 uses placeholder image: assets/images/slide_3_warmup.svg"
  ],
  "passed": [
    "lesson_has_title",
    "slides_have_titles",
    "all_referenced_files_exist"
  ],
  "suggestions": [
    "Regenerate image media before classroom delivery."
  ]
}
```

Human summary:

```text
quality/quality_summary.md
```

## Gate Timing

| Pipeline phase | Gate |
|---|---|
| after source intake | source sanity checks |
| after strategist | pedagogy and blueprint checks |
| after media generation | media checks |
| after render | runtime and accessibility checks |
| before export | full quality gate |

## Export Policy

Default policy:

- `pass`: export normally
- `warning`: export with report
- `blocked`: do not export

Development/demo policy may allow forced export:

```json
{
  "quality": {
    "allow_forced_export": true,
    "force_export_label": "demo"
  }
}
```

Forced export must write the blocked report into the ZIP.
