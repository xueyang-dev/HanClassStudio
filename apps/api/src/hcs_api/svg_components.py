"""Reusable, uniform teaching-illustration components + deterministic renderer.

Design rules (mirror the spec):
- Every component is a pure function (cx, cy, u, token, **variant) -> SVG string,
  authored in absolute 1200x675 coordinates around an anchor (cx, cy).
- Components read colours / stroke / proportions ONLY from the style token.
- Components NEVER embed teaching text (word / pinyin / translation / debug).
  The only permitted in-illustration text is a short semantic symbol such as a
  single greeting inside a speech bubble (handled by the SpeechBubble component).
- The renderer assembles a final SVG from an IllustrationSceneSpec; it does not
  free-hand arbitrary paths. This is what guarantees style consistency and lets
  the deterministic fallback produce real teaching pictures.

Components are registered in COMPONENTS keyed by their type name so the LLM
(or the fallback recipe table) can reference them by string and the quality
gate can reject unknown component ids.
"""

from __future__ import annotations

from typing import Any, Callable

from .style_tokens import SKIN_TONES, HAIR_TONES, get_style_token, style_token_for_presentation_theme

CANVAS_W = 1200
CANVAS_H = 675

# Component types that paint a full-canvas background and must be drawn first.
BACKGROUND_TYPES = {
    "BedroomBackground", "ClassroomBackground", "RestaurantBackground",
    "OutdoorBackground",
}

# Decorative / atmospheric components that should be dropped on tighter
# aspects (1:1, thumbnail) so the subject stays the clear visual centre.
DECOR_TYPES = {"Moon", "Stars", "SleepMarks", "Sun", "SimpleWindow"}


def _rr(x: float, y: float, w: float, h: float, r: float, fill: str,
        stroke: str = "", sw: float = 0.0, opacity: float = 1.0,
        id: str | None = None) -> str:
    """Rounded rect helper."""
    s = f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" rx="{r:.1f}" fill="{fill}"'
    if id:
        s += f' id="{id}"'
    if stroke:
        s += f' stroke="{stroke}" stroke-width="{sw:.1f}" stroke-linejoin="round"'
    if opacity != 1.0:
        s += f' opacity="{opacity:.2f}"'
    return s + "/>"


def _circ(cx: float, cy: float, r: float, fill: str, stroke: str = "",
          sw: float = 0.0, opacity: float = 1.0,
          id: str | None = None) -> str:
    s = f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{r:.1f}" fill="{fill}"'
    if id:
        s += f' id="{id}"'
    if stroke:
        s += f' stroke="{stroke}" stroke-width="{sw:.1f}"'
    if opacity != 1.0:
        s += f' opacity="{opacity:.2f}"'
    return s + "/>"


def _line(x1: float, y1: float, x2: float, y2: float, color: str, w: float,
          opacity: float = 1.0) -> str:
    return (f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
            f'stroke="{color}" stroke-width="{w:.1f}" stroke-linecap="round"'
            + (f' opacity="{opacity:.2f}"' if opacity != 1.0 else "") + '/>')


def _z_mark(x: float, y: float, s: float, color: str, w: float,
            opacity: float = 1.0, el_id: str | None = None) -> str:
    """A single 'Z' drawn as a polyline (no <text>), anchored at top-left."""
    s2 = f' id="{el_id}"' if el_id else ""
    return (f'<polyline{s2} points="{x:.1f},{y:.1f} {x+s:.1f},{y:.1f} {x:.1f},{y+s:.1f} {x+s:.1f},{y+s:.1f}" '
            f'fill="none" stroke="{color}" stroke-width="{w:.1f}" '
            f'stroke-linejoin="round" stroke-linecap="round"'
            + (f' opacity="{opacity:.2f}"' if opacity != 1.0 else "") + '/>')


# --------------------------------------------------------------------------
# People
# --------------------------------------------------------------------------

def person_standing(cx: float, cy: float, u: float, t, skin: str = SKIN_TONES[0],
                    hair: str = HAIR_TONES[0], garment: str = "", arm: str = "down",
                    garment2: str = "") -> str:
    garment = garment or t.fabric_blue
    o, sw = t.outline, t.outline_width
    top = cy - u / 2
    head_r = u * 0.13
    head_cy = top + head_r
    torso_w = u * 0.34
    torso_top = head_cy + head_r * 0.7
    torso_bottom = cy + u * 0.16
    torso_h = torso_bottom - torso_top
    leg_w = u * 0.13
    leg_bottom = cy + u / 2
    parts = [
        _circ(cx, head_cy, head_r, skin, o, sw),
        _rr(cx - head_r * 0.9, head_cy - head_r * 0.95, head_r * 1.8, head_r * 1.1, head_r * 0.6, hair),
        _rr(cx - torso_w / 2, torso_top, torso_w, torso_h, t.corner_radius, garment, o, sw),
        _rr(cx - torso_w / 2 - leg_w * 0.2, torso_bottom, leg_w, leg_bottom - torso_bottom, t.corner_radius * 0.6, garment2 or t.ink, o, sw),
        _rr(cx + torso_w / 2 - leg_w * 0.8, torso_bottom, leg_w, leg_bottom - torso_bottom, t.corner_radius * 0.6, garment2 or t.ink, o, sw),
    ]
    # arms
    if arm == "wave":
        parts.append(_rr(cx + torso_w / 2 - u * 0.02, torso_top + u * 0.02, leg_w * 0.8, u * 0.30, t.corner_radius * 0.6, garment, o, sw))
        parts.append(_rr(cx + torso_w / 2 + u * 0.10, torso_top - u * 0.06, leg_w * 0.8, u * 0.22, t.corner_radius * 0.6, skin, o, sw))
        parts.append(_circ(cx + torso_w / 2 + u * 0.16, torso_top - u * 0.10, head_r * 0.5, skin, o, sw))
    else:
        parts.append(_rr(cx - torso_w / 2 - leg_w * 0.1, torso_top + u * 0.02, leg_w * 0.8, u * 0.30, t.corner_radius * 0.6, garment, o, sw))
        parts.append(_rr(cx + torso_w / 2 - leg_w * 0.7, torso_top + u * 0.02, leg_w * 0.8, u * 0.30, t.corner_radius * 0.6, garment, o, sw))
    return "".join(parts)


def person_sitting(cx: float, cy: float, u: float, t, skin: str = SKIN_TONES[0],
                   hair: str = HAIR_TONES[0], garment: str = "", arm: str = "down",
                   garment2: str = "") -> str:
    garment = garment or t.fabric_blue
    o, sw = t.outline, t.outline_width
    top = cy - u / 2
    head_r = u * 0.14
    head_cy = top + head_r
    torso_w = u * 0.34
    torso_top = head_cy + head_r * 0.7
    seat_y = cy + u * 0.18
    torso_h = seat_y - torso_top
    parts = [
        _circ(cx, head_cy, head_r, skin, o, sw),
        _rr(cx - head_r * 0.9, head_cy - head_r * 0.95, head_r * 1.8, head_r * 1.1, head_r * 0.6, hair),
        _rr(cx - torso_w / 2, torso_top, torso_w, torso_h, t.corner_radius, garment, o, sw),
        # thighs (horizontal lap)
        _rr(cx - torso_w / 2, seat_y, torso_w, u * 0.16, t.corner_radius * 0.6, garment, o, sw),
        # lower legs down
        _rr(cx - torso_w / 2 + u * 0.02, seat_y + u * 0.14, u * 0.13, u * 0.22, t.corner_radius * 0.6, garment2 or t.ink, o, sw),
        _rr(cx + torso_w / 2 - u * 0.15, seat_y + u * 0.14, u * 0.13, u * 0.22, t.corner_radius * 0.6, garment2 or t.ink, o, sw),
    ]
    if arm == "forward":
        parts.append(_rr(cx + torso_w / 2 - u * 0.04, torso_top + u * 0.04, u * 0.30, u * 0.10, t.corner_radius * 0.6, garment, o, sw))
        parts.append(_circ(cx + torso_w / 2 + u * 0.26, torso_top + u * 0.08, head_r * 0.5, skin, o, sw))
    else:
        parts.append(_rr(cx - torso_w / 2 - u * 0.04, torso_top + u * 0.02, u * 0.10, u * 0.26, t.corner_radius * 0.6, garment, o, sw))
        parts.append(_rr(cx + torso_w / 2 - u * 0.06, torso_top + u * 0.02, u * 0.10, u * 0.26, t.corner_radius * 0.6, garment, o, sw))
    return "".join(parts)


def person_lying(cx: float, cy: float, u: float, t, skin: str = SKIN_TONES[0],
                 hair: str = HAIR_TONES[0], garment: str = "", blanket: str = "", **kw) -> str:
    garment = garment or t.fabric_teal
    blanket = blanket or t.fabric_teal
    o, sw = t.outline, t.outline_width
    left = cx - u / 2
    head_r = u * 0.16
    head_cx = left + head_r * 1.4
    body_h = u * 0.30
    body_top = cy - body_h / 2
    parts = [
        _circ(head_cx, cy, head_r, skin, o, sw),
        _rr(head_cx - head_r * 0.8, cy - head_r * 1.0, head_r * 1.6, head_r * 0.9, head_r * 0.5, hair),
        _rr(head_cx + head_r * 0.6, body_top, u * 0.78, body_h, body_h / 2, garment, o, sw),
    ]
    # blanket covering the body
    parts.append(_rr(head_cx + head_r * 1.4, body_top - u * 0.02, u * 0.66, body_h + u * 0.04, body_h / 2, blanket, o, sw * 0.8, 0.95))
    return "".join(parts)


# Friendly exported aliases used by recipes / LLM scene specs.
def PersonStanding(cx, cy, u, t, **kw): return person_standing(cx, cy, u, t, **kw)
def PersonSitting(cx, cy, u, t, **kw): return person_sitting(cx, cy, u, t, **kw)
def PersonLying(cx, cy, u, t, **kw): return person_lying(cx, cy, u, t, **kw)
def PersonReading(cx, cy, u, t, **kw):
    return person_sitting(cx, cy, u, t, **kw)
def PersonWriting(cx, cy, u, t, **kw):
    return person_sitting(cx, cy, u, t, **kw)
def StudentSitting(cx, cy, u, t, **kw):
    return person_sitting(cx, cy, u, t, garment=t.fabric_blue, **kw)
def TeacherStanding(cx, cy, u, t, **kw):
    return person_standing(cx, cy, u, t, garment=t.accent, garment2=t.fabric_blue, **kw)


# --------------------------------------------------------------------------
# Composite: a person sleeping IN a bed.
#
# This exists because the per-component floating-anchor layout CANNOT express
# "head resting on pillow, body on mattress, blanket draped over torso" — each
# primitive (Bed/Pillow/Blanket/PersonLying) is placed at an independent zone
# with no shared geometry, so contact relationships always drift apart.
# The composite OWNS the contact relationships as internal constants, so they
# are guaranteed regardless of caller. It is also aspect-aware: 16:9 / 1:1 /
# thumbnail get genuinely different compositions, not the same crop.
# --------------------------------------------------------------------------

def sleeping_in_bed(cx: float, cy: float, u: float, t, aspect: str = "16:9",
                    skin: str = SKIN_TONES[0], hair: str = HAIR_TONES[0], **kw) -> str:
    o, sw, r = t.outline, t.outline_width, t.corner_radius
    # Aspect-specific framing: genuinely different compositions, NOT a uniform
    # crop. 16:9 shows the full bedroom environment (largest blank tolerated);
    # 1:1 enlarges the subject and trims the background; thumbnail keeps only the
    # strongest semantic elements (bed + person + blanket + a small Z), no
    # window/moon/stars. The 'f' multiplier grows the whole composite so the
    # subject dominates the frame (less dead whitespace).
    if aspect == "thumb":
        f, dy, z_count = 1.36, -u * 0.10, 1
    elif aspect == "1:1":
        f, dy, z_count = 1.33, -u * 0.04, 2
    else:  # "16:9"
        f, dy, z_count = 1.27, 0.0, 3
    u = u * f
    cy = cy + dy

    garment = t.fabric_teal
    blanket_c = t.fabric_blue
    parts: list[str] = []

    # --- Bed (wood frame + legs + headboard), head to the LEFT.
    # Shortened 10–15% so the sleeper reads as the dominant mass rather than a
    # small figure on a long platform. ---
    bed_w = u * 2.70
    bed_x = cx - bed_w / 2
    mat_top = cy - u * 0.02              # top surface of the mattress
    frame_h = u * 0.40
    frame_y = mat_top
    parts.append(_rr(bed_x, frame_y, bed_w, frame_h, r * 0.5, t.wood, o, sw, id="sib-bed"))
    # legs
    leg_w = u * 0.10
    leg_h = u * 0.10
    leg_y = frame_y + frame_h
    parts.append(_rr(bed_x + u * 0.08, leg_y, leg_w, leg_h, r * 0.3, t.wood, o, sw))
    parts.append(_rr(bed_x + bed_w - u * 0.18, leg_y, leg_w, leg_h, r * 0.3, t.wood, o, sw))
    # headboard (left / head end)
    hb_w = u * 0.11
    hb_x = bed_x - u * 0.02
    hb_top = mat_top - u * 0.28
    hb_h = u * 0.34
    parts.append(_rr(hb_x, hb_top, hb_w, hb_h, r * 0.5, t.wood, o, sw))
    # mattress (cream) on top of frame
    mat_x = bed_x + u * 0.05
    mat_w = bed_w - u * 0.10
    mat_y = mat_top - u * 0.10
    mat_h = u * 0.12
    parts.append(_rr(mat_x, mat_y, mat_w, mat_h, r * 0.5, t.bg_light_warm, o, sw))

    # --- Pillow: wide, soft, slightly compressed; head rests on it ---
    pil_w = bed_w * 0.30
    pil_x = bed_x + u * 0.015
    pil_y = mat_top - u * 0.23
    pil_h = u * 0.20
    parts.append(_rr(pil_x, pil_y, pil_w, pil_h, r * 0.95, t.white, o, sw, id="sib-pillow"))
    # compression dent under where the head presses (subtle shadow line)
    parts.append(_line(pil_x + pil_w * 0.30, pil_y + pil_h * 0.55,
                       pil_x + pil_w * 0.85, pil_y + pil_h * 0.55, o, sw * 0.5, 0.30))

    # --- Person ---
    head_r = u * 0.143                       # ~8% smaller than the prior version
    head_cx = bed_x + bed_w * 0.155
    # head sits so its lower portion sinks into the pillow top (real contact)
    head_cy = pil_y + pil_h * 0.30

    # Head group: hair + head + face, tilted slightly so the sleeper looks
    # relaxed rather than bolt-upright. Rotation preserves the head/pillow bbox
    # (a circle's bbox is rotation-invariant) so the contact checks still hold.
    head_parts: list[str] = []
    head_parts.append(_circ(head_cx - head_r * 0.20, head_cy - head_r * 0.62,
                            head_r * 1.02, hair, o, sw * 0.8))
    head_parts.append(_circ(head_cx, head_cy, head_r, skin, o, sw, id="sib-head"))
    # closed eye (gentle downward curve, facing the foot / right)
    eye_x = head_cx + head_r * 0.30
    head_parts.append(f'<path d="M{eye_x:.1f} {head_cy - head_r*0.02:.1f} '
                      f'Q {eye_x + head_r*0.22:.1f} {head_cy + head_r*0.17:.1f} '
                      f'{eye_x + head_r*0.45:.1f} {head_cy - head_r*0.02:.1f}" '
                      f'fill="none" stroke="{o}" stroke-width="{sw*0.85:.1f}" stroke-linecap="round"/>')
    # relaxed, content mouth (small soft curve below the eye)
    mth_x = head_cx + head_r * 0.34
    head_parts.append(f'<path d="M{mth_x:.1f} {head_cy + head_r*0.34:.1f} '
                      f'Q {mth_x + head_r*0.18:.1f} {head_cy + head_r*0.46:.1f} '
                      f'{mth_x + head_r*0.36:.1f} {head_cy + head_r*0.34:.1f}" '
                      f'fill="none" stroke="{o}" stroke-width="{sw*0.7:.1f}" stroke-linecap="round"/>')
    parts.append(f'<g transform="rotate(-12 {head_cx:.1f} {head_cy:.1f})">{"".join(head_parts)}</g>')

    # Shoulder anchor where the neck meets the torso.
    shoulder_x = head_cx + head_r * 1.05
    foot_x = bed_x + bed_w * 0.93            # less empty bed past the feet

    # Neck + shoulder wedge: a soft skin bridge plus a small garment triangle
    # that fuses the neck base into the shoulder, so the head is clearly JOINED
    # to the body (not pasted onto the blanket).
    neck_x = head_cx + head_r * 0.42
    neck_y = head_cy + head_r * 0.32
    parts.append(_rr(neck_x, neck_y, u * 0.11, u * 0.12, u * 0.05, skin, o, sw * 0.8))
    parts.append(f'<path d="M{neck_x:.1f} {neck_y + u*0.05:.1f} '
                  f'Q {shoulder_x + u*0.02:.1f} {neck_y - u*0.03:.1f} '
                  f'{shoulder_x + u*0.12:.1f} {neck_y + u*0.12:.1f} '
                  f'L {neck_x:.1f} {neck_y + u*0.12:.1f} Z" '
                  f'fill="{garment}" stroke="{o}" stroke-width="{sw*0.7:.1f}" stroke-linejoin="round"/>')

    # Body silhouette (path): shoulder hump (high) -> waist dip -> hip swell ->
    # knee -> foot (lower & narrower). Gentle curves = a body, not a capsule.
    body_top = mat_top - u * 0.18
    body_bot = mat_top + u * 0.20
    body_h = body_bot - body_top
    hip_x = shoulder_x + (foot_x - shoulder_x) * 0.55
    knee_x = shoulder_x + (foot_x - shoulder_x) * 0.80
    d_body = (f'M{shoulder_x:.1f} {body_top:.1f} '
              f'Q {shoulder_x + u*0.05:.1f} {body_top - u*0.045:.1f} {shoulder_x + u*0.20:.1f} {body_top:.1f} '
              f'L {hip_x - u*0.12:.1f} {body_top + u*0.01:.1f} '
              f'Q {hip_x + u*0.05:.1f} {body_top - u*0.03:.1f} {hip_x + u*0.18:.1f} {body_top + u*0.005:.1f} '
              f'L {knee_x:.1f} {body_top + u*0.02:.1f} '
              f'Q {foot_x - u*0.06:.1f} {body_top + u*0.03:.1f} {foot_x:.1f} {body_bot - u*0.05:.1f} '
              f'L {foot_x:.1f} {body_bot:.1f} '
              f'Q {foot_x - u*0.12:.1f} {body_bot + u*0.025:.1f} {foot_x - u*0.30:.1f} {body_bot:.1f} '
              f'L {shoulder_x + u*0.05:.1f} {body_bot:.1f} '
              f'Q {shoulder_x:.1f} {body_bot - u*0.02:.1f} {shoulder_x:.1f} {body_top + body_h*0.40:.1f} Z')
    parts.append(f'<path id="sib-body" d="{d_body}" fill="{garment}" stroke="{o}" stroke-width="{sw:.1f}" stroke-linejoin="round"/>')

    # --- Blanket: draped from the shoulder. The TOP edge follows the body
    # (shoulder high, a slight waist dip, hip bump, then falls to the lower
    # foot), and the foot end tapers to a narrow point with the hem draping
    # lower — breaking the "long blue bar" read via real fabric volume. ---
    bl_x = shoulder_x + u * 0.02
    bl_w = (foot_x - bl_x)
    waist_x = shoulder_x + (foot_x - shoulder_x) * 0.40
    hip_bl = shoulder_x + (foot_x - shoulder_x) * 0.58
    knee_bl = shoulder_x + (foot_x - shoulder_x) * 0.80
    bl_top_sh = body_top + body_h * 0.02      # shoulder (high)
    bl_top_wa = body_top + body_h * 0.14      # waist (dips)
    bl_top_hip = body_top + body_h * 0.00     # hip (bump, highest)
    bl_top_ft = body_top + body_h * 0.22      # foot (lower)
    bl_bot_sh = body_bot + u * 0.00
    bl_bot_ft = body_bot + u * 0.12           # foot hem drapes lower
    d_blanket = (f'M{bl_x:.1f} {bl_top_sh:.1f} '
                 f'Q {bl_x + u*0.10:.1f} {bl_top_sh - u*0.03:.1f} {waist_x:.1f} {bl_top_wa:.1f} '
                 f'Q {hip_bl:.1f} {bl_top_hip - u*0.02:.1f} {knee_bl:.1f} {bl_top_ft:.1f} '
                 # right (foot) edge tapers to a narrower point
                 f'L {foot_x - u*0.03:.1f} {bl_top_ft + u*0.01:.1f} '
                 f'Q {foot_x + u*0.015:.1f} {bl_top_ft + u*0.06:.1f} {foot_x - u*0.03:.1f} {bl_bot_ft - u*0.03:.1f} '
                 # bottom edge: natural drape (wavy) back toward the shoulder
                 f'Q {knee_bl:.1f} {bl_bot_ft + u*0.02:.1f} {waist_x:.1f} {bl_bot_sh + u*0.03:.1f} '
                 f'Q {bl_x + u*0.10:.1f} {bl_bot_sh - u*0.02:.1f} {bl_x:.1f} {bl_bot_sh:.1f} Z')
    parts.append(f'<path id="sib-blanket" d="{d_blanket}" fill="{blanket_c}" fill-opacity="0.97" '
                 f'stroke="{o}" stroke-width="{sw:.1f}" stroke-linejoin="round"/>')
    # restrained fold lines following the body contour (1–2 only)
    parts.append(_line(bl_x + u * 0.10, bl_top_sh + body_h * 0.40,
                       waist_x, bl_top_wa + body_h * 0.50, o, sw * 0.6, 0.42))
    parts.append(_line(hip_bl, bl_top_hip + body_h * 0.22,
                       knee_bl, bl_top_ft + body_h * 0.34, o, sw * 0.5, 0.32))

    # --- Z marks ABOVE the head: SHRUNK further, hugged close to the head,
    # progressively smaller along the diagonal, and a light auxiliary colour so
    # they are a quiet signal, never a second visual centre. ---
    if z_count:
        zs = u * 0.15 * 0.50                  # ~50% smaller than the pre-polish Z
        zx = head_cx - zs * 0.20              # hugged close to the head
        zy = head_cy - head_r * 1.65          # sits just above the head
        for i in range(z_count):
            off = i * u * 0.15
            size = zs * (1 - i * 0.20)        # progressively smaller up the diagonal
            parts.append(_z_mark(zx + off, zy - off, size, t.aux_symbol, 3.0,
                                 0.55 - i * 0.16,
                                 el_id="sib-z" if i == 0 else None))

    return "".join(parts)


# --------------------------------------------------------------------------
# Furniture & objects
# --------------------------------------------------------------------------

def bed(cx, cy, u, t, **kw):
    o, sw, r = t.outline, t.outline_width, t.corner_radius
    w = u * 1.5
    h = u * 0.42
    x = cx - w / 2
    y = cy - h / 2
    return (_rr(x, y + h * 0.35, w, h * 0.65, r * 0.6, t.wood, o, sw)
            + _rr(x, y, w, h * 0.55, r, t.white, o, sw))

def pillow(cx, cy, u, t, **kw):
    return _rr(cx - u * 0.28, cy - u * 0.16, u * 0.56, u * 0.32, t.corner_radius, t.white, t.outline, t.outline_width)

def blanket(cx, cy, u, t, **kw):
    return _rr(cx - u * 0.5, cy - u * 0.18, u, u * 0.36, t.corner_radius, t.fabric_teal, t.outline, t.outline_width * 0.8, 0.95)

def table(cx, cy, u, t, **kw):
    o, sw, r = t.outline, t.outline_width, t.corner_radius
    w = u * 1.1
    h = u * 0.12
    return (_rr(cx - w / 2, cy - h / 2, w, h, r * 0.5, t.wood, o, sw)
            + _rr(cx - w / 2 + u * 0.05, cy + h / 2, u * 0.08, u * 0.30, r * 0.4, t.wood, o, sw)
            + _rr(cx + w / 2 - u * 0.13, cy + h / 2, u * 0.08, u * 0.30, r * 0.4, t.wood, o, sw))

def chair(cx, cy, u, t, **kw):
    o, sw, r = t.outline, t.outline_width, t.corner_radius
    return (_rr(cx - u * 0.22, cy - u * 0.30, u * 0.44, u * 0.10, r * 0.5, t.wood, o, sw)
            + _rr(cx - u * 0.22, cy - u * 0.30, u * 0.08, u * 0.50, r * 0.4, t.wood, o, sw)
            + _rr(cx + u * 0.14, cy - u * 0.30, u * 0.08, u * 0.50, r * 0.4, t.wood, o, sw))

def book(cx, cy, u, t, **kw):
    open_b = kw.get("open", True)
    o, sw, r = t.outline, t.outline_width, t.corner_radius
    if open_b:
        w = u * 0.6
        return (_rr(cx - w, cy - u * 0.18, w, u * 0.36, r * 0.4, t.white, o, sw)
                + _rr(cx, cy - u * 0.18, w, u * 0.36, r * 0.4, t.white, o, sw)
                + _rr(cx - u * 0.02, cy - u * 0.18, u * 0.04, u * 0.36, 0, t.ink, o, sw * 0.6))
    return _rr(cx - u * 0.3, cy - u * 0.2, u * 0.6, u * 0.4, r * 0.4, t.accent2, o, sw)

def notebook(cx, cy, u, t, **kw):
    return _rr(cx - u * 0.3, cy - u * 0.22, u * 0.6, u * 0.44, t.corner_radius * 0.4, t.white, t.outline, t.outline_width) + \
        _rr(cx - u * 0.3, cy - u * 0.22, u * 0.10, u * 0.44, t.corner_radius * 0.4, t.accent, t.outline, t.outline_width * 0.6)

def cup(cx, cy, u, t, **kw):
    o, sw, r = t.outline, t.outline_width, t.corner_radius
    return (_rr(cx - u * 0.16, cy - u * 0.18, u * 0.32, u * 0.36, r * 0.6, t.white, o, sw)
            + _rr(cx + u * 0.12, cy - u * 0.06, u * 0.06, u * 0.22, r * 0.3, t.white, o, sw)
            + _rr(cx - u * 0.10, cy - u * 0.10, u * 0.20, u * 0.10, r * 0.3, t.fabric_blue, o, sw * 0.6, 0.8))

def bowl(cx, cy, u, t, **kw):
    o, sw, r = t.outline, t.outline_width, t.corner_radius
    return (_rr(cx - u * 0.30, cy - u * 0.06, u * 0.60, u * 0.26, r * 0.8, t.white, o, sw)
            + _rr(cx - u * 0.20, cy - u * 0.14, u * 0.40, u * 0.14, r * 0.4, t.accent2, o, sw * 0.6, 0.85))

def chopsticks(cx, cy, u, t, **kw):
    o, sw = t.outline, t.outline_width
    return (_rr(cx - u * 0.02, cy - u * 0.30, u * 0.04, u * 0.60, 0, t.wood, o, sw * 0.6)
            + _rr(cx + u * 0.08, cy - u * 0.30, u * 0.04, u * 0.60, 0, t.wood, o, sw * 0.6))

def school_desk(cx, cy, u, t, **kw):
    o, sw, r = t.outline, t.outline_width, t.corner_radius
    w = u * 1.2
    return (_rr(cx - w / 2, cy - u * 0.10, w, u * 0.12, r * 0.5, t.wood, o, sw)
            + _rr(cx - w / 2 + u * 0.05, cy + u * 0.02, u * 0.08, u * 0.34, r * 0.4, t.wood, o, sw)
            + _rr(cx + w / 2 - u * 0.13, cy + u * 0.02, u * 0.08, u * 0.34, r * 0.4, t.wood, o, sw))


# --------------------------------------------------------------------------
# Environments (full-canvas backgrounds)
# --------------------------------------------------------------------------

def bedroom_background(cx, cy, u, t, aspect: str = "16:9", **kw):
    """Night bedroom. A window with night sky + a crescent moon INSIDE it
    forms a WEAK spatial background; the subject must dominate. The window is
    deliberately low-contrast, small, and pushed toward the canvas edge so it
    clearly reads as background, not a second subject. For the thumbnail there
    is NO window at all (only the strongest semantic elements survive), which
    is what makes the three aspects genuinely different recipes."""
    wall = _rr(0, 0, CANVAS_W, CANVAS_H, 0, t.bg_light_warm)
    if aspect == "thumb":
        return wall  # flat, weak background only
    # 1:1 keeps a smaller window near the edge; 16:9 the full (still weak) env.
    # Both are kept small and pushed hard against the edge so they read as
    # background, never as a second subject.
    win_u = 92.0 if aspect == "1:1" else 108.0
    win_cx = CANVAS_W - 92 if aspect == "1:1" else CANVAS_W - 96
    win_cy = 150.0
    return wall + night_window(win_cx, win_cy, win_u, t)


def night_window(cx, cy, u, t, **kw):
    """A window whose glass shows night sky with a crescent moon (tagged so the
    quality gate can verify the moon sits inside the window's visible area)."""
    o = t.outline
    w = u
    x = cx - w / 2
    y = cy - w / 2
    # frame — lighter, lower-contrast so it stays clearly background
    frame = _rr(x, y, w, w, t.corner_radius * 0.7, t.white, o, t.outline_width * 0.35, 0.55, id="sib-window")
    # glass (night sky) — very low opacity over the warm wall => weak contrast
    glass = _rr(x + u * 0.10, y + u * 0.10, w - u * 0.20, w - u * 0.20, t.corner_radius * 0.4,
                t.night_top, o, t.outline_width * 0.3, 0.14)
    # crescent moon INSIDE the glass (tagged)
    mx, my = x + u * 0.40, y + u * 0.34
    moon = (_circ(mx, my, u * 0.15, t.moon, o, t.outline_width * 0.4, id="sib-moon")
            + _circ(mx - u * 0.06, my - u * 0.03, u * 0.13, t.night_top, opacity=0.14))
    # a couple of faint stars inside the glass
    star = (_circ(x + u * 0.74, y + u * 0.26, 1.6, t.star, opacity=0.40)
            + _circ(x + u * 0.62, y + u * 0.66, 1.3, t.star, opacity=0.36))
    # muntins (cross bars) — thin, faint
    bars = (_rr(cx - u * 0.015, y + u * 0.10, u * 0.03, w - u * 0.20, 0, t.white, o, t.outline_width * 0.45, 0.7)
            + _rr(x + u * 0.10, cy - u * 0.015, w - u * 0.20, u * 0.03, 0, t.white, o, t.outline_width * 0.45, 0.7))
    return frame + glass + moon + star + bars

def classroom_background(cx, cy, u, t, **kw):
    return _rr(0, 0, CANVAS_W, CANVAS_H, 0, t.bg_light)

def restaurant_background(cx, cy, u, t, **kw):
    return _rr(0, 0, CANVAS_W, CANVAS_H, 0, t.bg_light)

def outdoor_background(cx, cy, u, t, **kw):
    return _rr(0, 0, CANVAS_W, CANVAS_H, 0, t.bg_light) + sun(170, 150, 90, t)

def simple_window(cx, cy, u, t, **kw):
    o, sw, r = t.outline, t.outline_width, t.corner_radius
    return (_rr(cx - u / 2, cy - u / 2, u, u, r, t.white, o, sw)
            + _rr(cx - u / 2 + u * 0.12, cy - u / 2 + u * 0.12, u * 0.76, u * 0.76, r * 0.5, t.fabric_blue, o, sw * 0.6, 0.5)
            + _rr(cx - u * 0.02, cy - u / 2, u * 0.04, u, 0, t.white, o, sw)
            + _rr(cx - u / 2, cy - u * 0.02, u, u * 0.04, 0, t.white, o, sw))

def moon(cx, cy, u, t, **kw):
    return _circ(cx, cy, u * 0.5, t.moon) + _circ(cx - u * 0.12, cy - u * 0.12, u * 0.42, t.night_top, opacity=0.5)

def sun(cx, cy, u, t, **kw):
    return _circ(cx, cy, u * 0.45, t.moon)

def stars(cx, cy, u, t, **kw):
    pts = [(180, 120), (320, 80), (520, 60), (700, 110), (250, 200), (1040, 160), (980, 320)]
    return "".join(_circ(x, y, 3.5, t.star) for x, y in pts)


# --------------------------------------------------------------------------
# Semantic symbols (allowed in-illustration marks; never teaching text)
# --------------------------------------------------------------------------

def sleep_marks(cx, cy, u, t, **kw):
    """Three small 'Z' zigzags drawn as polylines (no <text>)."""
    c = t.ink
    sw = 4
    z = lambda x, y, s: (f'<polyline points="{x},{y} {x+s},{y} {x},{y+s} {x+s},{y+s}" '
                         f'fill="none" stroke="{c}" stroke-width="{sw}" stroke-linejoin="round" stroke-linecap="round" opacity="0.85"/>')
    return z(cx, cy, u * 0.18) + z(cx + u * 0.22, cy - u * 0.18, u * 0.24) + z(cx + u * 0.5, cy - u * 0.42, u * 0.30)

def sound_waves(cx, cy, u, t, **kw):
    c = t.accent
    return (_rr(cx, cy - u * 0.2, u * 0.04, u * 0.4, 0, c, opacity=0.8)
            + _rr(cx + u * 0.1, cy - u * 0.3, u * 0.04, u * 0.6, 0, c, opacity=0.6)
            + _rr(cx + u * 0.2, cy - u * 0.4, u * 0.04, u * 0.8, 0, c, opacity=0.4))

def speech_bubble(cx, cy, u, t, **kw):
    text = kw.get("text", "")
    r = t.corner_radius
    w, h = u * 1.1, u * 0.6
    x = cx - w / 2
    y = cy - h / 2
    parts = [_rr(x, y, w, h, r, t.white, t.outline, t.outline_width),
             f'<path d="M{cx - u*0.12:.1f} {y+h:.1f} L{cx:.1f} {y+h+u*0.18:.1f} L{cx+u*0.12:.1f} {y+h:.1f} Z" fill="{t.white}" stroke="{t.outline}" stroke-width="{t.outline_width:.1f}"/>']
    if text:
        parts.append(f'<text x="{cx:.1f}" y="{cy+u*0.14:.1f}" text-anchor="middle" font-family="sans-serif" font-size="{u*0.34:.0f}" font-weight="700" fill="{t.ink}">{text}</text>')
    return "".join(parts)

def motion_lines(cx, cy, u, t, **kw):
    c = t.accent
    return (_rr(cx, cy - u * 0.18, u * 0.04, u * 0.36, 0, c, opacity=0.7)
            + _rr(cx + u * 0.12, cy - u * 0.10, u * 0.04, u * 0.20, 0, c, opacity=0.5))

def attention_mark(cx, cy, u, t, **kw):
    c = t.accent2
    return (_circ(cx, cy, u * 0.32, c)
            + f'<text x="{cx:.1f}" y="{cy+u*0.16:.1f}" text-anchor="middle" font-family="sans-serif" font-size="{u*0.42:.0f}" font-weight="700" fill="{t.white}">!</text>')


# --------------------------------------------------------------------------
# Registry
# --------------------------------------------------------------------------

COMPONENTS: dict[str, Callable[..., str]] = {
    "PersonStanding": PersonStanding,
    "PersonSitting": PersonSitting,
    "PersonLying": PersonLying,
    "SleepingInBed": sleeping_in_bed,
    "PersonReading": PersonReading,
    "PersonEating": PersonSitting,
    "PersonDrinking": PersonStanding,
    "PersonWriting": PersonWriting,
    "TeacherStanding": TeacherStanding,
    "StudentSitting": StudentSitting,
    "Bed": bed,
    "Pillow": pillow,
    "Blanket": blanket,
    "Table": table,
    "Chair": chair,
    "Book": book,
    "Notebook": notebook,
    "Cup": cup,
    "Bowl": bowl,
    "Chopsticks": chopsticks,
    "SchoolDesk": school_desk,
    "BedroomBackground": bedroom_background,
    "ClassroomBackground": classroom_background,
    "RestaurantBackground": restaurant_background,
    "OutdoorBackground": outdoor_background,
    "SimpleWindow": simple_window,
    "Moon": moon,
    "Sun": sun,
    "Stars": stars,
    "SleepMarks": sleep_marks,
    "SoundWaves": sound_waves,
    "SpeechBubble": speech_bubble,
    "MotionLines": motion_lines,
    "AttentionMark": attention_mark,
}

SETTING_BG = {
    "bedroom": "BedroomBackground",
    "classroom": "ClassroomBackground",
    "restaurant": "RestaurantBackground",
    "outdoor": "OutdoorBackground",
    "park": "OutdoorBackground",
}


def known_component(name: str) -> bool:
    return name in COMPONENTS


# --------------------------------------------------------------------------
# Deterministic renderer: SceneSpec (dict) -> SVG
# --------------------------------------------------------------------------

_ZONE_ANCHORS = {
    "center": (600, 360),
    "left": (380, 400),
    "right": (820, 400),
    "top_left": (360, 250),
    "top_right": (840, 250),
    "bottom_center": (600, 470),
    "lower_left": (360, 470),
    "lower_right": (840, 470),
}


def _zone_anchor(zone: str, level: str) -> tuple[float, float]:
    return _ZONE_ANCHORS.get(zone, _ZONE_ANCHORS["center"])


def _pose_for_action(action: str) -> str:
    a = (action or "").lower()
    if "wave" in a or "greet" in a:
        return "wave"
    if any(k in a for k in ("eat", "drink", "read", "write", "study", "point")):
        return "forward"
    return "down"


def _wrap_svg(inner: str, spec: dict, token) -> str:
    label = spec.get("accessibility_label") or spec.get("concept") or "illustration"
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {CANVAS_W} {CANVAS_H}" '
        f'role="img" aria-label="{label}">\n{inner}\n</svg>'
    )


def render_scene_spec(spec: dict, aspect: str = "16:9", presentation_theme=None) -> str:
    """Deterministically assemble an SVG from an IllustrationSceneSpec (dict).

    Pure function of the spec + style token: no LLM, no randomness, so the
    same spec always yields the same illustration (incl. the fallback path).

    `aspect` ("16:9" | "1:1" | "thumb") selects an independently-designed
    composition. Decorative objects (flagged decor:true or in DECOR_TYPES) are
    suppressed for non-16:9 aspects so small frames stay uncluttered and the
    subject dominates.
    """
    token = style_token_for_presentation_theme(presentation_theme) if presentation_theme is not None else get_style_token(spec.get("style_token"))
    level = spec.get("illustration_level", "scene")
    setting = spec.get("setting")

    if level == "icon":
        bg = _rr(0, 0, CANVAS_W, CANVAS_H, 0, "#FFFFFF")
    else:
        bg_type = SETTING_BG.get(setting)
        bg = COMPONENTS[bg_type](600, 337, 675, token, aspect=aspect) if bg_type else _rr(0, 0, CANVAS_W, CANVAS_H, 0, token.bg_light)

    parts = [bg]
    # Objects explicitly flagged decor, or in DECOR_TYPES, are dropped when the
    # aspect is not the full 16:9 scene (keeps 1:1 / thumbnail uncluttered).
    suppress = {"1:1": {"Stars"}, "thumb": {"Moon", "Stars", "SleepMarks"}}.get(aspect, set())
    items = list(spec.get("objects", [])) + list(spec.get("subjects", []))
    for item in items:
        ctype = item.get("object_type") or item.get("role")
        if ctype not in COMPONENTS:
            continue
        if (item.get("decor") or ctype in DECOR_TYPES) and ctype in suppress:
            continue
        cx, cy = _zone_anchor(item.get("position_zone", "center"), level)
        rs = float(item.get("relative_scale", 0.5))
        u = rs * (token.body_height_unit if level == "scene" else token.icon_unit)
        idx = abs(hash(str(item.get("id", ctype)))) % len(SKIN_TONES)
        variant = {"skin": SKIN_TONES[idx], "hair": HAIR_TONES[idx % len(HAIR_TONES)]}
        if item.get("action") or item.get("pose"):
            variant["arm"] = _pose_for_action(item.get("action") or item.get("pose"))
        if item.get("symbol_text"):
            variant["text"] = item["symbol_text"]
        # Only the composite consumes aspect; everything else ignores it via **kw.
        if ctype == "SleepingInBed":
            variant["aspect"] = aspect
        parts.append(COMPONENTS[ctype](cx, cy, u, token, **variant))
    return _wrap_svg("".join(parts), spec, token)
