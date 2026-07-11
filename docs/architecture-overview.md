# Architecture Overview

HanClassStudio uses an artifact-first, State-first and Evidence-first architecture. The web workbench is a teacher-facing controller; the backend owns project workspaces, canonical artifacts, validation, rendering, quality gates, and export.

The original v0.1 demo proved the local authoring/export loop. Phase 2B established a shadow canonical presentation compiler and Phase 2C established an internal rendered-output validation path. Production renderers and exports still use the legacy LessonBlueprint contract. Real teaching validation has not started.

Current phase status:

```text
Phase 2B: substantially complete
Phase 2C: internal technical validation complete
Real teaching validation: not started
Production v2 cutover: not started
```

The canonical roadmap is [roadmap.md](roadmap.md).

## Artifact-First Workspace

Each project lives under:

```text
runtime/projects/<project_id>/
```

The workspace is divided by ownership:

```text
uploads/
sources/
analysis/
learning/
presentation/
specs/
blueprints/
assets/
courseware/
quality/
exports/
agent/
backup/
```

The important rule: each stage writes named artifacts to a predictable path. Later stages read those artifacts instead of guessing state from UI fields.

## Target Pipeline

```text
Source
→ learner/source analysis
→ Learning State Plan
→ Evidence Plan
→ Activity Plan
→ Evidence Alignment Gate
→ Presentation Content Contract
→ Presentation Media Request Contract
→ Abstract Presentation Bindings
→ Canonical Presentation Blueprint
→ Legacy LessonBlueprint Adapter
→ Renderers
→ Quality Gates
→ Export
```

Goals define evidence before activities are selected. Evidence constrains activities; activities support presentation. Renderers compile approved presentation artifacts and do not make pedagogical decisions.

## State-Evidence Kernel

HanClassStudio now builds a teaching kernel before presentation artifacts:

```text
source_material.json
  -> analysis/source_lesson_profile.json
  -> analysis/learner_model.json
  -> analysis/language_items.json
  -> learning/learning_state_plan.json
  -> learning/evidence_plan.json
  -> learning/activity_plan.json
  -> quality/evidence_alignment_report.json
  -> presentation contracts
```

The kernel follows the [State-Evidence Kernel white paper](state-evidence-kernel-v0.2.2.md):

- `learning/learning_state_plan.json` defines learner states, learning goals, and transitions.
- `learning/evidence_plan.json` defines evidence contracts for those transitions.
- `learning/activity_plan.json` defines activities that collect evidence.
- `quality/evidence_alignment_report.json` checks Goal-Evidence-Activity alignment.

If evidence alignment is `blocked`, downstream presentation artifacts cannot appear successful and normal classroom render/export is blocked. This keeps pedagogical failure upstream of presentation generation.

## Presentation Contracts

The v2 canonical path separates four responsibilities:

- `presentation/presentation_content_plan.json` owns component-neutral learner-facing payloads and provenance.
- `presentation/presentation_media_request_plan.json` owns deterministic renderer-neutral media needs.
- `presentation/abstract_activity_bindings.json` maps approved activity/evidence pairs to presentation modes without slide or component IDs.
- `presentation/presentation_blueprint.json` owns ordered renderer-neutral presentation units.

`presentation/activity_bindings.json` is the v1 legacy production binding. It maps into existing slide/component targets and remains necessary for the current renderer contract, but it is not the future source of pedagogical truth. See [Presentation Contracts and Bindings](presentation-bindings-v0.2.2.md).

## Current Production, Shadow, And Internal Routes

```text
Production: Legacy LessonBlueprint → v1 bindings → existing renderers → public exports
Shadow v2: Kernel → content/media contracts → abstract bindings → canonical blueprint → shadow adapter → diagnostics
Internal experiment: eligible whole lesson → v2 readiness → lesson_v2_internal.html → rendered-output review
```

The internal route is disabled by default, does not overwrite production output, and currently supports only whole lessons whose learner-facing modes are all `listening_choice` or `matching_response`.

## Artifact Ownership Summary

| Category | Artifacts | Authority |
|---|---|---|
| Pedagogical authoritative | learning state, evidence, and activity plans | learner assumptions, goals, evidence, activities |
| Pedagogical gate | evidence alignment report | Goal-Evidence-Activity validity |
| Canonical presentation | content plan, media request plan, abstract bindings, canonical blueprint | renderer-neutral content and presentation structure |
| Legacy production compatibility | lesson blueprint, v1 bindings, interaction plan, media plan | current renderer input only |
| Diagnostic-only | readiness, parity, projection, reconciliation, assessment, cutover, and rendered-output reports | explain and validate a run |

## Lesson Spec And Spec Lock

`specs/lesson_spec.md` is the human-readable teaching design. It explains the lesson intent, audience, language scaffolding, route, media strategy, and quality policy.

`specs/spec_lock.json` is the execution contract. It locks the route, generation mode, runtime assumptions, allowed components, media policy, and export policy.

Downstream stages should read `spec_lock.json` instead of inferring policy directly from frontend fields.

## Component Registry

`courseware/components/registry.json` is the source of truth for interactive components.

The registry defines:

- component names
- renderer support
- required data fields
- optional fields
- quality checks
- experimental status

The frontend loads this registry through `/api/component-registry`, and the renderer plus quality gate validate against the same component names.

## Agent Handoff

Agent Handoff lets external coding Agents work on structured lesson artifacts without owning render/export.

HanClassStudio can generate:

```text
agent/AGENT_TASK.md
agent/AGENT_RULES.md
```

An external Agent may edit:

- `specs/lesson_spec.md`
- `specs/spec_lock.json`
- `blueprints/lesson_blueprint.json`
- `blueprints/interaction_plan.json`
- `blueprints/media_plan.json`

HanClassStudio then validates the output, renders `courseware/lesson.html`, runs quality, and exports.

The State-Evidence Kernel artifacts are currently generated by HanClassStudio. Agents should inspect them when diagnosing quality failures, but should treat the kernel alignment gate as authoritative unless explicitly working on the kernel generator itself.

## Teaching Candidate Extraction

Before blueprint generation, HanClassStudio runs a Teaching Candidate Extraction step that analyses the source material and produces `analysis/teaching_candidates.json` with the following fields:

| Field | Purpose |
|-------|---------|
| `route_hint` | Lesson type classification (`greeting_lesson`, `vocabulary_lesson`, `dialogue_lesson`, `character_lesson`, `grammar_pattern_lesson`, `mixed_lesson`) |
| `core_vocabulary` | High-confidence target words — based on frequency, position (dialogue/context), and pinyin proximity |
| `secondary_vocabulary` | Medium-confidence words — present in source but with weaker evidence |
| `noise_candidates` | Low-confidence or non-teaching strings (stroke names, framework noise, generic functional words) |
| `grammar_candidates` | Detected grammar patterns ordered by confidence — sourced from structural patterns in the text |
| `dialogue_candidates` | Extracted A/B dialogue lines from the source |
| `character_candidates` | Candidate characters for writing practice |
| `classroom_task_candidates` | Inferred classroom activity types |
| `source_warnings` | Diagnostic warnings about source quality |

The teaching candidates feed directly into the Lesson Strategist (blueprint generation). A greeting lesson produces a different slide structure than a character-writing lesson.

The extraction logic in `analysis.py`:
- Classifies characters into stroke noise vs. real vocabulary
- Prioritises words that appear near pinyin annotations, example sentences, or English glosses
- Detects dialogue structures from "A：" / "B：" patterns
- Infers grammar patterns from source text (在+呢, 了, 喜欢, etc.) without hard-coding defaults
- Scores route hints by checking title, content signals, and structural patterns

## Learner Comprehension Core

After teaching candidates are extracted, the Learner Comprehension Core (`learner_comprehension.py`) builds a structured understanding of what the learner knows and what they can handle:

### Learner Model

`analysis/learner_model.json` captures:
- `target_language` / `scaffold_language`
- `level`: zero_beginner, beginner, elementary, intermediate
- `known_words`: words the learner already knows (functional words like 我, 的, 是 are pre-populated)
- `new_word_limit_per_slide` (2 for zero_beginner) and `new_word_limit_per_lesson`
- `max_sentence_length`
- `require_scaffold_meaning` / `require_usage_scene`

### Language Items

`analysis/language_items.json` converts teaching candidates into structured `LanguageItem` objects:
- Each item has `target_form`, `pronunciation`, `scaffold_meaning`, `usage_context`, `example`
- Vocabulary items look up built-in gloss tables for supported scaffold languages (Arabic, English)
- Grammar patterns (e.g., 你 vs 您) become LanguageItems with usage context

### Input Sequence Plan

`analysis/input_sequence_plan.json` plans the introduction order of new items:
- Checks that prerequisites are met before introducing dependent items
- Flags items missing scaffold meaning or usage context
- Warns about example sentences containing unknown words

### Comprehensibility Gate

`quality/comprehensibility_report.json` runs during `render_and_check` and checks:
- New word count per slide doesn't exceed the limit
- All vocabulary items have scaffold meaning (blocked for zero_beginner)
- Example sentences don't use "我会说" template unless 我/会/说 are known
- No meta labels (生词卡, 词卡) are exposed to learners in classroom mode
- Usage context is present for each item

### Built-in Gloss Tables

For greeting lessons, a minimal built-in gloss table provides real translations for supported languages:

| Word | Arabic | English |
|------|--------|---------|
| 你好 | مرحبًا | hello |
| 您好 | مرحبًا / تحية رسمية | hello (polite) |
| 你 | أنتَ / أنتِ | you (informal) |
| 您 | حضرتك | you (polite) |
| 老师 | مُعَلِّم / مُعَلِّمَة | teacher |
| 再见 | إلى اللقاء | goodbye |

The table is extensible in `learner_comprehension.py` and does not require a real LLM provider.

## Syllabus-Aware Comprehensible Input Engine

After language items are built, the Syllabus Engine (`syllabus_engine.py`) adds a second layer of constraints based on the source material's actual scope and the learner's level:

### Pipeline Flow

```text
source_material
  -> SourceLessonProfile (extract dialogue/vocab/grammar/exercise/teacher/noise units)
  -> DifficultyProfile (infer HSK level from content signals)
  -> LearnerModel -> LanguageInventory (classify known/target/off-level/excluded)
  -> Learning State Plan -> Evidence Plan -> Activity Plan
  -> Evidence Alignment Report
  -> AllowedTextPlan (per-slide allowed/forbidden text, max new items)
  -> Blueprint generation (constrained by allowed text)
  -> OffLevelReport (post-generation check for violations)
  -> Exports
```

### Source Lesson Profile

`analysis/source_lesson_profile.json` extracts structured units:
- `dialogue_units`: lines matching A：/B： patterns
- `vocabulary_units`: Chinese words with adjacent pinyin
- `grammar_units`: pattern signals (语法, 在...呢, 了, etc.)
- `exercise_units`: activity descriptions (读一读, 写一写, 听一听)
- `teacher_instruction_units`: teacher-facing prompts
- `noise_units`: irrelevant text

### Difficulty Profile

`analysis/difficulty_profile.json` infers lesson level from source:
- Greeting signals + pinyin presence + unique character count → zero_beginner, beginner, etc.
- Maps to standard schemes (HSK1-6, CEFR A1-C2, JLPT N5-N1)
- Includes evidence list and confidence score

### Language Inventory

`analysis/language_inventory.json` classifies every lexical item:
- `known_items`: from learner model + standard profile
- `lesson_target_items`: from source, will enter learner-facing text
- `off_level_items`: complex items filtered out for zero_beginner/beginner
- `teacher_only_items`: instructions, meta labels
- `excluded_items`: noise, functional words

### Allowed Text Plan

`analysis/allowed_text_plan.json` defines per-slide constraints:
- `allowed_target_text`: words that may appear on this slide
- `forbidden_target_text`: never show these (meta labels, "我会说", "朋友之间")
- `max_new_items`: 1 for zero_beginner
- `teacher_only_text`: never reaches student view

### Off-Level Report

`quality/off_level_report.json` validates the final output:
- `unknown_target_items`: words in learner-facing text not in known or target list
- `teacher_text_leaks`: meta labels or teacher instructions visible to students
- `unsupported_new_items`: slides with too many new items
- State is `blocked` for zero_beginner with violations, otherwise `warning`

### i+1 Constraints

For zero_beginner:
- Maximum 1 new core target item per slide
- First exposure must include audio/image/scaffold meaning
- No "我会说", "朋友之间", "同学之间" in target text
- No output tasks before input is established
- Teacher instructions only in scaffold language, not target language

## Quality Gate

The quality gate writes:

```text
quality/quality_report.json
quality/quality_summary.md
```

The report state is:

```text
pass | warning | blocked
```

`blocked` prevents normal export. A forced export path exists for demo use, and forced exports are marked in `export_manifest.json`.

The quality system now includes:

- State-Evidence alignment checks for goal orphans, evidence orphans, activity suitability, semantic safety, presentation independence, and teacher observation readiness.
- Classroom/content checks for forbidden learner-facing labels, unsuitable zero-beginner activities, scaffold leakage, and placeholder provider data.
- Traditional v0.1 checks for title/objectives/slides, component support, interaction answers, missing assets, path safety, runtime output, and basic vocabulary language requirements.

## Offline HTML Export

The renderer writes:

```text
courseware/lesson.html
courseware/render_manifest.json
```

The exported ZIP includes `lesson.html`, media assets, canonical data artifacts, the quality report, and an export manifest.

The runtime is slide-based, local-only, and does not depend on external CDNs. Its CSS and JavaScript come from the fixed runtime renderer/template, not from generated Agent content.

## Editable PPTX Export

Editable PPTX is the second export target. It reads the same canonical artifacts:

```text
specs/spec_lock.json
blueprints/lesson_blueprint.json
blueprints/interaction_plan.json
blueprints/media_plan.json
assets/data/asset_manifest.json
quality/quality_report.json
```

The exporter writes:

```text
exports/HanClassStudio_Editable_<timestamp>.pptx
exports/pptx_export_manifest.json
quality/pptx_quality_report.json
```

The PPTX exporter is deterministic and uses `python-pptx` to generate native editable PowerPoint shapes, text boxes, and image placeholders. It does not convert HTML or SVG snapshots. Interactive components are downgraded into static classroom activity pages so teachers can edit and present them in PowerPoint.

The same quality policy applies: blocked quality prevents normal PPTX export unless `force=true` is explicit and recorded in the manifest.
