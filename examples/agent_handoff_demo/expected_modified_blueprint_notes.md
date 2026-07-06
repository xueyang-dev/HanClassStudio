# Expected Modified Blueprint Notes

The edited blueprint should remain schema-valid and registry-compatible.

Expected characteristics:

- `lesson_title` remains a clear Chinese lesson title.
- `objectives` includes at least one communicative classroom goal.
- `slides` remain ordered and use stable numeric ids.
- Components use only names from `courseware/components/registry.json`.
- Component ids are unique.
- `SentenceDragBuilder` includes `words` and `answer`.
- `ListenAndChoose` includes `choices`, `answer`, and `audio_key`.
- `MatchGame` includes non-empty `pairs`.
- `CharacterFormation` includes `character`, `parts`, and `explanation`.
- Scaffold text supports the teacher-selected language but does not replace Chinese.

Expected after HanClassStudio validation:

- Agent validation returns readable `passed`, `warnings`, or `blocking` messages.
- Render creates `courseware/lesson.html`.
- Quality report is written to `quality/quality_report.json`.
- Export ZIP includes the canonical data files under `assets/data/`.
