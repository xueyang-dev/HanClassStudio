"""Generate an honest current-vs-new comparison gallery for the 睡觉 scene.

BEFORE = the currently-reviewed v2 composite (the version from the previous
         round, already on disk in diagnostics/sleep_comparison/after/).
AFTER  = this round's polished v3 composite (re-rendered from the edited code).
Zero network deps. Developer-only visual review artifact.
"""
import json, os, shutil, sys
sys.path.insert(0, "apps/api/src")
from hcs_api.svg_illustration import (
    build_scene_spec_for_concept, render_scene_spec,
    check_svg_offline_safe, check_illustration_quality, _sub,
)

OUT = "diagnostics/sleep_comparison"
ASPECTS = ["16:9", "1:1", "thumb"]


def gates(spec_dict, svg, aspect):
    off = check_svg_offline_safe(svg, "cmp")
    iq = check_illustration_quality(spec_dict, svg, aspect=aspect)
    return off.state, iq["state"], iq["blocking"]


def main():
    os.makedirs(f"{OUT}/before", exist_ok=True)
    os.makedirs(f"{OUT}/after", exist_ok=True)

    # Capture the currently-reviewed v2 (on disk) as this round's "before".
    # (The 'after' folder on disk was produced by the previous round.)
    if os.path.isfile(f"{OUT}/after/16x9.svg"):
        for asp in ASPECTS:
            fn = asp.replace(":", "x") + ".svg"
            shutil.copyfile(f"{OUT}/after/{fn}", f"{OUT}/before/{fn}")
        if os.path.isfile(f"{OUT}/after_reports.json"):
            shutil.copyfile(f"{OUT}/after_reports.json", f"{OUT}/before_reports.json")
        print("captured current v2 (on disk) as BEFORE")
    else:
        # First run / missing: fall back to the v1 composite so we still have a before.
        for asp in ASPECTS:
            fn = asp.replace(":", "x") + ".svg"
            if os.path.isfile(f"{OUT}/before_v1/{fn}"):
                shutil.copyfile(f"{OUT}/before_v1/{fn}", f"{OUT}/before/{fn}")
        if os.path.isfile(f"{OUT}/before_v1_reports.json"):
            shutil.copyfile(f"{OUT}/before_v1_reports.json", f"{OUT}/before_reports.json")
        print("captured v1 composite as BEFORE (no on-disk v2 found)")

    # AFTER = freshly rendered from the now-edited code (v3).
    after_spec = build_scene_spec_for_concept("睡觉", "汉语课")
    after_reports = {}
    for asp in ASPECTS:
        svg = render_scene_spec(after_spec, aspect=asp)
        with open(f"{OUT}/after/{asp.replace(':', 'x')}.svg", "w") as f:
            f.write(svg)
        off, iq, blk = gates(after_spec, svg, asp)
        after_reports[asp] = {"offline": off, "iq": iq, "blocking": blk}
        print(f"AFTER  {asp:4}: offline={off} iq={iq} blocking={len(blk)}")

    with open(f"{OUT}/after_reports.json", "w") as f:
        json.dump(after_reports, f, ensure_ascii=False, indent=1)
    print("SVGs written to", OUT)


if __name__ == "__main__":
    main()
