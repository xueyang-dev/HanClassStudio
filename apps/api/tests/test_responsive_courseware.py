from __future__ import annotations

from hcs_api.renderer import _css


def test_courseware_css_allows_grid_children_to_shrink() -> None:
    css = _css()
    assert ".stage { min-width: 0;" in css
    assert ".slide-frame { position: relative; min-width: 0; max-width: 100%; min-height: 0; aspect-ratio: 16 / 9;" in css


def test_mobile_courseware_reflows_instead_of_preserving_fixed_slide_canvas() -> None:
    css = _css()
    assert ".slide-frame { width: 100%; min-height: auto; max-height: none; aspect-ratio: auto; }" in css
    assert ".slide { position: relative; min-height: 0; padding: 24px; }" in css
