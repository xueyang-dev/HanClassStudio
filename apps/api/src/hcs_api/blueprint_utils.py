from __future__ import annotations

from collections import defaultdict

from .models import LessonBlueprint


def duplicate_component_id_messages(blueprint: LessonBlueprint) -> list[str]:
    occurrences: dict[str, list[int]] = defaultdict(list)
    for slide in blueprint.slides:
        for component in slide.components:
            occurrences[component.id].append(slide.id)
    return [
        f"Duplicate component id {component_id} on slide_id(s): {', '.join(str(s) for s in slide_ids)}"
        for component_id, slide_ids in sorted(occurrences.items())
        if len(slide_ids) > 1
    ]


def normalize_component_ids(blueprint: LessonBlueprint) -> LessonBlueprint:
    seen: set[str] = set()
    totals: dict[str, int] = defaultdict(int)
    for slide in blueprint.slides:
        for component in slide.components:
            totals[component.id] += 1

    per_slide_counts: dict[tuple[int, str], int] = defaultdict(int)
    for slide in blueprint.slides:
        for component in slide.components:
            original = component.id
            if totals[original] > 1 or original in seen:
                while True:
                    per_slide_counts[(slide.id, original)] += 1
                    candidate = f"{original}_s{slide.id}_{per_slide_counts[(slide.id, original)]}"
                    if candidate not in seen:
                        component.id = candidate
                        break
            seen.add(component.id)
    return blueprint
