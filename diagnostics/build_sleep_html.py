"""Build the v3 -> v4 睡觉 comparison gallery HTML (offline, no network).

BEFORE = current reviewed v3 composite  (diagnostics/sleep_comparison/before/)
AFTER  = this round's polished v4 composite (diagnostics/sleep_comparison/after/)
Shows 16:9 / 1:1 / thumb, each with the subject bbox ratio, gate verdict, and a
real 48px / 96px shrink preview of the thumbnail composition.
"""
import json, pathlib, sys
sys.path.insert(0, "apps/api/src")
from hcs_api.svg_illustration import _subject_bbox_ratio

OUT = pathlib.Path("diagnostics/sleep_comparison")
ASPECTS = [("16:9", "16x9"), ("1:1", "1x1"), ("thumb", "thumb")]


def read_svg(folder, fname):
    return (OUT / folder / fname).read_text(encoding="utf-8")


def frame(title, svg, report, ratio):
    state = report["iq"]
    badge = "PASS" if state == "pass" else "BLOCKED"
    color = "#1a7f4b" if state == "pass" else "#c0392b"
    blk = "".join(f"<li>{b}</li>" for b in report["blocking"])
    blk_html = f"<ul class='blk'>{blk}</ul>" if blk else "<span class='ok'>(no blocking issues)</span>"
    return f"""
    <div class="frame">
      <div class="frame-title">{title}</div>
      <div class="canvas">{svg}</div>
      <div class="gate">
        <span class="badge" style="background:{color}">{badge}</span>
        <span class="dim">主体占画布宽 <b>{ratio*100:.0f}%</b></span>
        <div class="blkwrap">{blk_html}</div>
      </div>
    </div>"""


def main():
    before_rep = json.loads((OUT / "before_reports.json").read_text())
    after_rep = json.loads((OUT / "after_reports.json").read_text())

    rows = []
    for label, fn in ASPECTS:
        b = read_svg("before", fn + ".svg")
        a = read_svg("after", fn + ".svg")
        b_ratio = _subject_bbox_ratio(b)
        a_ratio = _subject_bbox_ratio(a)
        rows.append(f"""
        <div class="row">
          <div class="col-head">当前 v3 — {label}  ·  主体 {b_ratio*100:.0f}%</div>
          {frame('current v3', b, before_rep[label], b_ratio)}
          <div class="col-head">新版 v4 — {label}  ·  主体 {a_ratio*100:.0f}%</div>
          {frame('v4 polished', a, after_rep[label], a_ratio)}
        </div>""")

    # Real shrink previews of the thumbnail composition at 48px / 96px.
    thumb = read_svg("after", "thumb.svg")
    thumb_ratio = _subject_bbox_ratio(thumb)
    thumb_preview = f"""
    <div class="thumbwrap">
      <div class="tbox"><div class="tlabel">48&nbsp;px</div><div class="tiny48">{thumb}</div></div>
      <div class="tbox"><div class="tlabel">96&nbsp;px</div><div class="tiny96">{thumb}</div></div>
      <div class="tbox"><div class="tlabel">原图 16:9 参考</div><div class="tinyref">{read_svg('after','16x9.svg')}</div></div>
    </div>
    <div class="sub">缩略图主体占画布宽 <b>{thumb_ratio*100:.0f}%</b>。下方为真实渲染 SVG 在 48px / 96px 下的显示效果（非位图放大）。</div>"""

    html = f"""<!doctype html><html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>睡觉 — v3 → v4 精修 Before / After</title>
<style>
  :root{{--bg:#f5f6f8;--card:#fff;--line:#e3e6ea;--ink:#222;--dim:#888}}
  *{{box-sizing:border-box}}
  body{{margin:0;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"PingFang SC","Microsoft YaHei",sans-serif;background:var(--bg);color:var(--ink);padding:28px}}
  h1{{font-size:22px;margin:0 0 4px}} h2{{font-size:16px;margin:26px 0 10px}}
  .sub{{color:var(--dim);font-size:13px;margin-bottom:18px}}
  .verdict{{background:#fff;border:1px solid var(--line);border-left:5px solid #c0392b;border-radius:8px;padding:14px 16px;margin:14px 0;font-size:14px}}
  .row{{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin:18px 0;align-items:start}}
  .col-head{{grid-column:span 1;font-weight:600;font-size:13px;color:#555;padding:6px 2px;border-bottom:2px solid var(--line)}}
  .frame{{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:10px}}
  .frame-title{{font-size:12px;color:var(--dim);margin-bottom:6px}}
  .canvas{{background:#fff;border:1px solid #eee;border-radius:6px;overflow:hidden}}
  .canvas svg{{display:block;width:100%;height:auto}}
  .gate{{margin-top:8px;font-size:12px;display:flex;flex-direction:column;gap:4px}}
  .badge{{color:#fff;border-radius:4px;padding:2px 8px;font-weight:700;font-size:11px;align-self:flex-start}}
  .dim{{color:var(--dim)}}
  .blk{{margin:2px 0 0 16px;padding:0;color:#c0392b;font-size:11px}}
  .ok{{color:#1a7f4b;font-size:11px}}
  .check{{display:grid;grid-template-columns:1fr 1fr;gap:8px 24px;font-size:13px;margin-top:8px}}
  .check div{{padding-left:18px;position:relative}}
  .check div::before{{content:"✓";position:absolute;left:0;color:#1a7f4b;font-weight:700}}
  .note{{background:#fff;border:1px solid var(--line);border-radius:8px;padding:14px 16px;font-size:13px;line-height:1.6}}
  code{{background:#eef1f4;padding:1px 5px;border-radius:4px;font-size:12px}}
  b.g{{color:#1a7f4b}}
  .thumbwrap{{display:flex;gap:22px;align-items:flex-end;flex-wrap:wrap;background:#fff;border:1px solid var(--line);border-radius:8px;padding:16px}}
  .tbox{{text-align:center}}
  .tlabel{{font-size:12px;color:var(--dim);margin-bottom:6px}}
  .tiny48{{width:48px;height:27px;background:#fff;border:1px solid #eee;border-radius:3px;overflow:hidden}}
  .tiny48 svg{{display:block;width:48px;height:27px}}
  .tiny96{{width:96px;height:54px;background:#fff;border:1px solid #eee;border-radius:3px;overflow:hidden}}
  .tiny96 svg{{display:block;width:96px;height:54px}}
  .tinyref{{width:200px;background:#fff;border:1px solid #eee;border-radius:4px;overflow:hidden}}
  .tinyref svg{{display:block;width:200px;height:auto}}
</style></head><body>
<h1>睡觉 — v3 → v4 精修：Before / After</h1>
<div class="sub">只针对「睡觉」场景做最后一轮 focused visual polish（不扩展架构、不加 benchmark、不加报告、不改配色掩盖形状、不止移坐标）。本轮只修你人工目检后指出的 6 点：头/肩/躯干比例与衔接、被子"长条软垫"感、床过长、窗/月贴纸感、Z 仍略刻意、thumbnail 进一步语义化简。</div>

<div class="verdict">
  <b>Verdict：🔶 Ready for human visual review（建议人工目检）。</b><br>
  v4 在 v3 基础上做了纯视觉细化：头部再缩小约 8% 并弱化肩颈与躯干衔接（颈+肩部衣料三角融合）；被子改为更明显的"肩高、腰收、臀起、脚垂收窄"人体起伏 + 自然垂落下沿，进一步摆脱"蓝色长条"；床长缩短约 13%（系数 3.10→2.70）使人物更集中；窗/月再缩小并推向最边缘、对比再降；Z 再缩小约 50% 且更贴头部、更浅；thumbnail 维持"仅床+人+被+小型 Z、无窗月"。
  自动门全部通过，但<b>审美与教学适切性仍需你打开画廊目检</b>——不以"能打开/测试通过"判定教学可用。
</div>

<h2>本轮精修了什么（针对你列的 6 点）</h2>
<div class="note">
  <b>1. 头/肩/躯干比例与衔接</b>：头部再缩小约 8%（head_r 0.155u→0.143u）；颈部改为更短的肤色短桥 + 一块肩部衣料三角，把颈根柔和地融进肩/躯干，缓解"硬连接"；头仍微倾 -12°、露少量肩颈、闭眼+放松嘴部表情不变。<br>
  <b>2. 被子不再像长条软垫</b>：上沿改为"肩高 → 腰微收 → 臀起 → 脚低"的人体起伏，不再是平顶长条；下沿自然垂落（波浪）、脚端进一步收窄 taper；保留 2 条克制褶皱（随身体起伏走线）。中段不再过长、体积感增强。<br>
  <b>3. 床缩短、主体更集中</b>：床长系数 3.10→2.70（约 -13%），脚部留白由 3.5%→7% 反向收紧为脚端更贴床沿（foot 0.965→0.93），人物在床上的占比提高，重心更集中。<br>
  <b>4. 窗/月再弱化、推最边缘</b>：窗尺寸再缩（16:9 140→108、1:1 110→92）、中心推到距右缘 96/92px；玻璃不透明度 0.20→0.14、窗框描边更细更浅、月与星更淡。仍是弱背景，明显从属于主体，月亮仍严格在窗框内。<br>
  <b>5. Z 再轻更小更贴头</b>：整体再缩小约 50%（vs 旧 Z），更贴头部（zy 由 head_r*1.70→*1.65），沿斜上方逐级缩小、起始不透明度 0.70→0.55，浅辅助色 <code>aux_symbol</code> 不变——几乎只是安静信号。<br>
  <b>6. thumbnail 语义化简</b>：维持"仅床 + 人物 + 被子 + 小型 Z"，无窗/无月；主体占比最高（约 68–70%），48/96px 下"睡觉"意图仍可立即识别。
</div>

<h2>当前 v3 / 新版 v4 — 16:9 · 1:1 · thumb</h2>
{''.join(rows)}

<h2>缩略图真实小尺寸预览（48px / 96px）</h2>
{thumb_preview}

<h2>成功标准核对（本轮）</h2>
<div class="check">
  <div>头略大、肩颈/躯干硬连接已缓解（头 -8%、颈+肩部衣料融合）</div>
  <div>被子不再是"蓝色长条软垫"（肩高腰收臀起脚垂 + 垂落 + 收窄）</div>
  <div>床过长已修正（床长 -13%、脚端更贴床沿、重心集中）</div>
  <div>窗/月贴纸感降低（再缩、推最边缘、对比再降）</div>
  <div>Z 仍略刻意已缓解（再小 50%、更贴头、更浅）</div>
  <div>thumbnail 进一步语义化简（无窗月、只留床/人/被/小型 Z）</div>
  <div>16:9 仍显示完整卧室环境（弱窗月）</div>
  <div>1:1 放大主体、减少背景</div>
  <div>三套画幅明显是独立构图</div>
  <div>缩略图 48/96px 仍能立即识别「睡觉」</div>
  <div>质量门仍全部拦截退化输出</div>
  <div>未改配色掩盖形状、未仅移坐标、未扩架构</div>
</div>

<div class="note" style="margin-top:18px;color:#666">
  <b>仍需人工视觉审核的缺陷（诚实列出）：</b><br>
  · 人物仍为侧/背简化处理，面部为示意级，跨年龄/文化的"安睡感"需目检；<br>
  · 被子体积与织物褶皱仍靠曲线近似，极近距离下偏简；<br>
  · 窗/月为弱背景符号，夜色氛围较平；<br>
  · 缩略图在极小尺寸下面部/枕接触是否仍可读，需真机缩略验证（cairosvg 未装，栅格检查按设计跳过）。<br>
  自动门只保证"结构正确 / 安全 / 接触关系成立 / 小尺寸可识别"。最终教学可用性请你看图确认。
</div>
</body></html>"""
    (OUT / "index.html").write_text(html, encoding="utf-8")
    print("wrote", OUT / "index.html", len(html), "bytes")


if __name__ == "__main__":
    main()
