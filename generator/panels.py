"""The compositions: hero faceplate, project telemetry tiles, capability bars.

Layout is absolute and computed in advance rather than flowed. That is only
safe because the font is embedded and monospaced, so `theme.text_width` is
exact on every machine rather than an estimate.
"""
from svg import Doc
from theme import text_width

HERO_W, HERO_H = 880, 264
TILE_W, TILE_H = 428, 168
CAP_W, CAP_H = 880, 284

STATUS = {
    "live": ("LIVE", "accent"),
    "shipped": ("SHIPPED", "ok"),
    "done": ("COMPLETE", "data"),
}


def fit(s, size, maxw):
    """Truncate to what actually fits, since nothing here can reflow."""
    n = int(maxw / (size * 0.6))
    s = str(s)
    return s if len(s) <= n else s[: max(0, n - 1)].rstrip(" ·,;") + "…"


def _dash_in(doc, cls_prefix, length, dur, delay):
    cls = doc.uid(cls_prefix)
    doc.css.append(
        ".%s{animation:k%s %ss cubic-bezier(.35,0,.15,1) %ss both}"
        "@keyframes k%s{from{stroke-dasharray:%d;stroke-dashoffset:%d}"
        "to{stroke-dasharray:%d;stroke-dashoffset:0}}"
        % (cls, cls, dur, delay, cls, length, length, length))
    return cls


# ---------------------------------------------------------------------------
# Hero
# ---------------------------------------------------------------------------

def hero(theme, ident, stats, contributions):
    t = theme
    d = Doc(HERO_W, HERO_H, t,
            "%s — %s" % (ident["name"], ident["role"]),
            ident["thesis"])

    d.rect(0.5, 0.5, HERO_W - 1, HERO_H - 1, t["bg"], r=10,
           stroke=t["border"], sw=1)

    clip = d.uid("hclip")
    d.defs.append('<clipPath id="%s"><rect x="0.5" y="0.5" width="%d" '
                  'height="%d" rx="10"/></clipPath>'
                  % (clip, HERO_W - 1, HERO_H - 1))
    d.add('<g clip-path="url(#%s)">' % clip)

    # --- status strip -----------------------------------------------------
    d.rect(0, 0, HERO_W, 30, t["panel_top"])
    d.line(0, 30, HERO_W, 30, t["hairline"], 1)
    d.led(24, 15.5, t["ok"], live=True, r=3.0)
    d.text(38, 19, ident["handle"], size=10, fill=t["secondary"], tracking=1.1)
    right = "%s  ·  STATUS NOMINAL  ·  LAST PUSH %s" % (
        ident["location"].upper(), stats["last_push"])
    d.text(HERO_W - 22, 19, right, size=9, fill=t["dim"], anchor="end",
           tracking=1.2)

    # --- identity ---------------------------------------------------------
    d.text(28, 94, ident["name"], size=38, weight=700, fill=t["text_bright"],
           tracking=3.4)
    d.rect(30, 106, 96, 2.5, t["accent"], r=1.5)
    d.text(28, 132, ident["role"], size=12, fill=t["secondary"])

    for i, ln in enumerate(_wrap(ident["thesis"], 11, 566)[:2]):
        d.text(28, 158 + i * 17, ln, size=11, fill=t["dim"])

    # --- readouts ---------------------------------------------------------
    d.line(608, 50, 608, 174, t["hairline"], 1)
    rows = [
        ("CONTRIBUTIONS / 52W", stats["contrib_total"]),
        ("PUBLIC REPOSITORIES", stats["repos"]),
        ("PRIMARY LANGUAGE", stats["primary_lang"]),
    ]
    for i, (label, value) in enumerate(rows):
        y = 78 + i * 43
        d.text(HERO_W - 22, y - 19, label, size=8.5, fill=t["dim"],
               anchor="end", tracking=1.4)
        d.text(HERO_W - 22, y, str(value), size=18, weight=700,
               fill=t["text_bright"], anchor="end")

    # --- contribution trace ----------------------------------------------
    d.line(0, 186, HERO_W, 186, t["hairline"], 1)
    d.text(28, 206, "CONTRIBUTION SIGNAL  ·  52 WEEKS", size=8.5,
           fill=t["dim"], tracking=1.4)
    d.text(HERO_W - 22, 206, "peak %d / week" % max(contributions or [0]),
           size=8.5, fill=t["dim"], anchor="end", tracking=1.0)

    gx, gy, gw, gh = 28, 214, HERO_W - 56, 40
    for i in range(1, 13):
        x = gx + gw * i / 13.0
        d.line(x, gy, x, gy + gh, t["grid"], 1, opacity=0.9)
    d.sparkline(gx, gy, gw, gh, contributions or [0, 0],
                t["data"], t["data"], delay=0.15)

    d.add("</g>")
    return d.render()


def _wrap(s, size, maxw):
    limit = int(maxw / (size * 0.6))
    words, lines, cur = str(s).split(), [], ""
    for w in words:
        cand = (cur + " " + w).strip()
        if len(cand) > limit and cur:
            lines.append(cur)
            cur = w
        else:
            cur = cand
    if cur:
        lines.append(cur)
    return lines


# ---------------------------------------------------------------------------
# Project tile
# ---------------------------------------------------------------------------

def tile(theme, p, series):
    t = theme
    label, ckey = STATUS.get(p["status"], STATUS["done"])
    accent = t[ckey]

    d = Doc(TILE_W, TILE_H, t, "%s — %s" % (p["title"], label),
            "%s %s. %s. %s" % (p["value"], p["unit"], p["caption"],
                               p.get("note", "")))

    clip = d.panel(0.5, 0.5, TILE_W - 1, TILE_H - 1, r=8, header=30)
    d.add('<g clip-path="url(#%s)">' % clip)

    # status rail
    d.rect(0, 30, 2.5, TILE_H - 30, accent, opacity=0.85)

    d.text(16, 20, fit(p["title"], 11.5, 296), size=11.5, weight=700,
           fill=t["accent"])
    d.text(TILE_W - 16, 19.5, label, size=8.5, fill=t["secondary"],
           anchor="end", tracking=1.3)
    d.led(TILE_W - 22 - text_width(label, 8.5) - 8, 15.5, accent,
          live=(p["status"] == "live"), r=3.0)

    # headline metric
    d.text(16, 74, p["value"], size=29, weight=700, fill=t["text_bright"])
    if p["unit"]:
        d.text(16 + text_width(p["value"], 29) + 8, 74, p["unit"], size=11.5,
               fill=t["secondary"])

    d.text(16, 95, fit(p["caption"], 9.5, TILE_W - 32), size=9.5,
           fill=t["secondary"])
    d.text(16, 111, fit(p["stack"], 9, TILE_W - 32), size=9, fill=t["dim"])

    # full-bleed telemetry, kept quiet enough that the metric still leads
    if series and len(series) > 2 and max(series) > 0:
        d.text(16, 130, "WEEKLY ACTIVITY", size=7.5, fill=t["dim"], tracking=1.2)
        d.text(TILE_W - 16, 130, "%d COMMITS · PEAK %d" % (sum(series), max(series)), size=7.5,
               fill=t["dim"], anchor="end", tracking=1.2)
        # The zero weeks already read as a baseline, so no extra rule.
        d.bars(14, 136, TILE_W - 28, 30, series[-52:], accent, delay=0.25)
    else:
        d.text(16, 130, "WEEKLY ACTIVITY", size=7.5, fill=t["dim"],
               tracking=1.2)
        d.text(TILE_W - 16, 130, "SOURCE NOT PUBLIC", size=7.5, fill=t["dim"],
               anchor="end", tracking=1.2)
        d.line(14, 160, TILE_W - 14, 160, t["hairline"], 2, dash="2 5")

    d.add("</g>")
    return d.render()


# ---------------------------------------------------------------------------
# Capability matrix
# ---------------------------------------------------------------------------

def capability(theme, caps, shares):
    t = theme
    d = Doc(CAP_W, CAP_H, t, "Capability matrix",
            "Self-assessed depth against measured language byte share.")

    clip = d.panel(0.5, 0.5, CAP_W - 1, CAP_H - 1, r=10, header=34)
    d.add('<g clip-path="url(#%s)">' % clip)

    d.text(24, 22, "CAPABILITY", size=10.5, weight=700, fill=t["accent"],
           tracking=1.6)
    # Legend keyed to the two marks, laid out right-to-left. Tracking has to
    # be included in the width or the swatches drift off the labels.
    def tw(s_, size, track):
        return len(s_) * (size * 0.6 + track)

    cur = CAP_W - 24
    for lbl, col in (("SHARE OF PUBLIC CODE", t["data"]),
                     ("SELF-ASSESSED DEPTH", t["accent"])):
        d.text(cur, 22, lbl, size=8.5, fill=t["dim"], anchor="end",
               tracking=1.2)
        cur -= tw(lbl, 8.5, 1.2) + 8
        d.rect(cur - 11, 16, 11, 3.5, col, r=1.75)
        cur -= 11 + 18

    x0, bw = 396, 388
    # One gradient in user space across the whole bar column, so a shorter bar
    # genuinely reads as less far along rather than just shorter.
    bg = d.uid("bg")
    d.defs.append(
        '<linearGradient id="%s" gradientUnits="userSpaceOnUse" '
        'x1="%d" y1="0" x2="%d" y2="0">'
        '<stop offset="0" stop-color="%s"/>'
        '<stop offset="1" stop-color="%s"/></linearGradient>'
        % (bg, x0, x0 + bw, t["accent_soft"], t["accent"]))

    for i, c in enumerate(caps):
        y = 66 + i * 40
        d.text(24, y, c["label"], size=11, fill=t["text"])
        d.text(24, y + 13, fit(c["detail"], 8.5, 358), size=8.5, fill=t["dim"])

        # Depth: the claim.
        d.line(x0, y - 6, x0 + bw, y - 6, t["border"], 6, opacity=0.75)
        w = bw * c["weight"] / 100.0
        cls = _dash_in(d, "bar", int(w) + 2, 0.9, round(0.2 + i * 0.08, 2))
        d.add('<line class="%s" x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" '
              'stroke="url(#%s)" stroke-width="6" stroke-linecap="round"/>'
              % (cls, x0, y - 6, x0 + w, y - 6, bg))

        # Share of public bytes: a different quantity, so a different mark.
        share = shares.get(c["label"], 0.0)
        sw_ = bw * share
        d.line(x0, y + 3, x0 + bw, y + 3, t["border"], 2, opacity=0.5)
        if sw_ > 0.5:
            cls2 = _dash_in(d, "sbar", int(sw_) + 2, 0.9,
                            round(0.35 + i * 0.08, 2))
            d.add('<line class="%s" x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" '
                  'stroke="%s" stroke-width="2.5" stroke-linecap="round"/>'
                  % (cls2, x0, y + 3, x0 + sw_, y + 3, t["data"]))

        d.text(CAP_W - 24, y - 2, str(c["weight"]), size=11, weight=700,
               fill=t["text_bright"], anchor="end")
        d.text(CAP_W - 24, y + 10, "%.0f%%" % (share * 100), size=8,
               fill=t["data"], anchor="end")

    d.line(24, CAP_H - 32, CAP_W - 24, CAP_H - 32, t["hairline"], 1)
    d.text(24, CAP_H - 14,
           "Share counts public repositories only, and excludes notebooks, "
           "whose bytes are mostly embedded output. Two shipped products are "
           "closed-source.",
           size=8, fill=t["dim"])

    d.add("</g>")
    return d.render()
