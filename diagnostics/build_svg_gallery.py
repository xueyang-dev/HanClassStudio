"""Developer-only benchmark gallery for teaching illustrations.

Renders the fixed benchmark concepts through the deterministic pipeline
(recipe -> renderer -> offline-safe + illustration-quality gates) and produces
diagnostics/svg_gallery/index.html. This page is for human visual review only;
it is NOT embedded in any production courseware and uses zero network resources.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "api" / "src"))

from hcs_api.svg_illustration import (  # noqa: E402
    CONCEPT_RECIPES, build_scene_spec_for_concept, render_scene_spec,
    check_svg_offline_safe, check_illustration_quality, placeholder_svg,
)

OUT_DIR = Path(__file__).resolve().parent / "svg_gallery"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# 5 mandatory vertical-slice concepts + 3 supporting benchmarks.
BENCHMARKS = [
    "睡觉", "吃饭", "喝水", "学习", "学生向老师问好",
    "看书", "写字", "餐厅点餐",
]


def components_used(spec: dict) -> list[str]:
    return [s.get("object_type") for s in spec.get("subjects", [])] + \
           [o.get("object_type") for o in spec.get("objects", [])]


def build_case(concept: str) -> dict:
    spec = build_scene_spec_for_concept(concept, "")
    svg = render_scene_spec(spec)
    off = check_svg_offline_safe(svg, concept)
    iq = check_illustration_quality(spec, svg)
    # "before": the old geometric placeholder (pre-architecture) for contrast.
    before = placeholder_svg(concept, 1)
    return {
        "concept": concept,
        "level": spec.get("illustration_level"),
        "scene_type": spec.get("scene_type"),
        "text_policy": spec.get("text_policy"),
        "components": components_used(spec),
        "svg": svg,
        "before_svg": before,
        "offline_state": off.state,
        "quality_state": iq["state"],
        "quality_blocking": iq.get("blocking", []),
        "quality_warnings": iq.get("warnings", []),
        "human_review": iq.get("human_visual_review_required", True),
        "scene_spec": spec,
        "fallback": True,  # no LLM configured -> deterministic recipe path
    }


def _card(c: dict) -> str:
    comps = ", ".join(x for x in c["components"] if x)
    specs = json.dumps(c["scene_spec"], ensure_ascii=False, indent=1).replace("<", "&lt;").replace(">", "&gt;")
    qstate = c["quality_state"]
    qcolor = {"pass": "#2E8B78", "warning": "#E0864B", "blocked": "#C0392B"}.get(qstate, "#888")
    flags = []
    if c["quality_blocking"]:
        flags.append(f"<li class='blk'>{c['quality_blocking'][0]}</li>")
    for w in c["quality_warnings"][:2]:
        flags.append(f"<li class='warn'>{w}</li>")
    flags_html = "<ul class='flags'>" + "".join(flags) + "</ul>" if flags else ""
    return f"""
    <article class="case">
      <h2>{c['concept']} <span class="lvl">{c['level']} · {c['scene_type']}</span></h2>
      <div class="previews">
        <figure><div class="box ar169">{c['svg']}</div><figcaption>16:9</figcaption></figure>
        <figure><div class="box ar43">{c['svg']}</div><figcaption>4:3</figcaption></figure>
        <figure><div class="box ar11">{c['svg']}</div><figcaption>1:1</figcaption></figure>
      </div>
      <div class="meta">
        <div><b>组件:</b> {comps}</div>
        <div><b>文字策略:</b> {c['text_policy']} &nbsp; <b>fallback:</b> {str(c['fallback']).lower()}</div>
        <div class="states">
          <span class="pill ok">offline: {c['offline_state']}</span>
          <span class="pill" style="background:{qcolor}">quality: {qstate}</span>
          <span class="pill rev">人工视觉复核: 需要</span>
        </div>
        {flags_html}
        <details><summary>IllustrationSceneSpec</summary><pre>{specs}</pre></details>
      </div>
      <div class="before">
        <b>改造前 (旧几何占位图):</b>
        <div class="box ar169 beforebox">{c['before_svg']}</div>
      </div>
    </article>"""


def main() -> None:
    cases = [build_case(c) for c in BENCHMARKS]
    cards = "\n".join(_card(c) for c in cases)
    summary = (
        f"{len(cases)} benchmarks · offline-safe: "
        f"{sum(1 for c in cases if c['offline_state']=='pass')}/{len(cases)} · "
        f"illustration-quality pass: "
        f"{sum(1 for c in cases if c['quality_state']=='pass')}/{len(cases)} "
        f"(其余为 warning，均需要人工视觉复核)"
    )
    html = f"""<!doctype html><html lang="zh"><head><meta charset="utf-8">
<title>HanClassStudio 教学插画 Benchmark Gallery</title>
<style>
 body{{font-family:-apple-system,'PingFang SC','Microsoft YaHei',sans-serif;background:#eef2f1;margin:0;padding:28px;color:#22332e}}
 header{{max-width:1200px;margin:0 auto 18px}}
 h1{{font-size:22px;margin:0}} .sub{{color:#6f8d88;font-size:13px;margin:4px 0 0}}
 .summary{{background:#fff;border-left:4px solid #2E8B78;padding:10px 14px;border-radius:8px;font-size:13px;margin-top:12px}}
 .grid{{max-width:1200px;margin:0 auto;display:grid;grid-template-columns:1fr;gap:22px}}
 .case{{background:#fff;border-radius:14px;padding:18px 20px;box-shadow:0 4px 18px rgba(0,0,0,.06)}}
 h2{{font-size:18px;margin:0 0 12px}} .lvl{{font-size:12px;color:#6f8d88;font-weight:400}}
 .previews{{display:flex;gap:14px;flex-wrap:wrap}}
 figure{{margin:0;flex:1;min-width:220px}}
 .box{{width:100%;border:1px solid #e3efe9;border-radius:10px;background:#fff;overflow:hidden}}
 .box svg{{display:block;width:100%;height:auto}}
 .ar169{{aspect-ratio:16/9}} .ar43{{aspect-ratio:4/3}} .ar11{{aspect-ratio:1/1}}
 figcaption{{font-size:11px;color:#8aa;margin-top:4px;text-align:center}}
 .meta{{margin-top:12px;font-size:13px;line-height:1.7}}
 .states{{margin:6px 0}}
 .pill{{display:inline-block;color:#fff;font-size:11px;padding:2px 9px;border-radius:999px;margin-right:6px;background:#888}}
 .pill.ok{{background:#2E8B78}} .pill.rev{{background:#6f8d88}}
 .flags{{margin:6px 0;padding-left:18px;font-size:12px}} .flags .blk{{color:#C0392B}} .flags .warn{{color:#E0864B}}
 details{{margin-top:8px}} summary{{cursor:pointer;font-size:12px;color:#2E8B78}}
 pre{{background:#f4f7f6;padding:10px;border-radius:8px;font-size:11px;overflow:auto;max-height:240px}}
 .before{{margin-top:12px;font-size:12px;color:#6f8d88}}
 .beforebox{{margin-top:6px;opacity:.85}}
</style></head><body>
<header><h1>教学插画 Benchmark Gallery</h1>
<div class="sub">开发用 · 不进入生产课件 · 零网络依赖 · 确定性 recipe → 组件库渲染 → 离线安全门 + 教学适用门</div>
<div class="summary">{summary}</div></header>
<div class="grid">{cards}</div>
</body></html>"""
    (OUT_DIR / "index.html").write_text(html, encoding="utf-8")
    # Also drop raw per-benchmark SVGs for inspection.
    raw = OUT_DIR / "svgs"
    raw.mkdir(exist_ok=True)
    for c in cases:
        (raw / f"{c['concept']}.svg").write_text(c["svg"], encoding="utf-8")
        (raw / f"{c['concept']}.scene.json").write_text(json.dumps(c["scene_spec"], ensure_ascii=False), encoding="utf-8")
    print(f"WROTE {OUT_DIR}/index.html  ({len(cases)} benchmarks)")


if __name__ == "__main__":
    main()
