"""SVG primitives for the profile dashboard.

Every asset is a self-contained document: fonts are embedded as base64 woff2,
all styling is internal, and nothing is fetched at render time. That matters
because GitHub serves these through its camo image proxy, where an external
request would simply fail and the layout would reflow per viewer.
"""
import base64
import io
import math
import os

FONT_DIR = os.path.join(os.path.dirname(__file__), "fonts")
_font_cache = {}

MONO_STACK = ("'JBM','JetBrains Mono',ui-monospace,SFMono-Regular,"
              "Menlo,Consolas,monospace")


def esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def subset_font(style, chars):
    """Subset JetBrains Mono to exactly the glyphs an asset uses (~2-4 KB)."""
    key = (style, "".join(sorted(set(chars))))
    if key in _font_cache:
        return _font_cache[key]
    from fontTools import subset
    opts = subset.Options()
    opts.flavor = "woff2"
    opts.desubroutinize = True
    opts.layout_features = []
    opts.notdef_outline = True
    # Hinting instructions are roughly half the glyf table and do
    # nothing at these sizes on any renderer that will see this.
    opts.hinting = False
    opts.drop_tables += ["GSUB", "GPOS", "GDEF", "MATH", "BASE", "JSTF", "DSIG"]
    font = subset.load_font(os.path.join(FONT_DIR, "JBM-%s.ttf" % style), opts)
    sub = subset.Subsetter(options=opts)
    sub.populate(text="".join(sorted(set(chars))) or " ")
    sub.subset(font)
    buf = io.BytesIO()
    font.save(buf)
    font.close()
    out = base64.b64encode(buf.getvalue()).decode("ascii")
    _font_cache[key] = out
    return out


class Doc:
    """Collects body markup plus the exact glyph set each weight needs."""

    def __init__(self, w, h, theme, title, desc=""):
        self.w, self.h, self.t = w, h, theme
        self.title, self.desc = title, desc
        self.body = []
        self.defs = []
        self.css = []
        self.chars = {"Regular": set(), "Bold": set()}
        self._uid = 0

    def uid(self, p="i"):
        self._uid += 1
        return "%s%d" % (p, self._uid)

    def add(self, s):
        self.body.append(s)

    # ---- primitives ---------------------------------------------------

    def rect(self, x, y, w, h, fill, r=0, stroke=None, sw=1, opacity=None,
             extra=""):
        a = ('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" fill="%s"'
             % (x, y, w, h, fill))
        if r:
            a += ' rx="%s"' % r
        if stroke:
            a += ' stroke="%s" stroke-width="%s"' % (stroke, sw)
        if opacity is not None:
            a += ' opacity="%s"' % opacity
        self.add(a + " " + extra + "/>")

    def line(self, x1, y1, x2, y2, stroke, sw=1, opacity=None, dash=None):
        a = ('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="%s" '
             'stroke-width="%s"' % (x1, y1, x2, y2, stroke, sw))
        if opacity is not None:
            a += ' opacity="%s"' % opacity
        if dash:
            a += ' stroke-dasharray="%s"' % dash
        self.add(a + "/>")

    def text(self, x, y, s, size=12, fill=None, weight=400, anchor="start",
             tracking=0, opacity=None, extra=""):
        s = str(s)
        self.chars["Bold" if weight >= 600 else "Regular"].update(s)
        fill = fill or self.t["text"]
        a = ('<text x="%.1f" y="%.1f" font-size="%s" fill="%s" font-weight="%s"'
             % (x, y, size, fill, weight))
        if anchor != "start":
            a += ' text-anchor="%s"' % anchor
        if tracking:
            a += ' letter-spacing="%s"' % tracking
        if opacity is not None:
            a += ' opacity="%s"' % opacity
        self.add(a + " " + extra + ">" + esc(s) + "</text>")

    # ---- composites ---------------------------------------------------

    def panel(self, x, y, w, h, r=8, header=28):
        """A framed instrument panel with a faint header band."""
        t = self.t
        self.rect(x, y, w, h, t["panel"], r=r, stroke=t["border"], sw=1)
        cid = self.uid("clip")
        self.defs.append(
            '<clipPath id="%s"><rect x="%s" y="%s" width="%s" height="%s" '
            'rx="%s"/></clipPath>' % (cid, x, y, w, h, r))
        if header:
            self.add('<g clip-path="url(#%s)">' % cid)
            self.rect(x, y, w, header, t["panel_top"])
            self.line(x, y + header, x + w, y + header, t["hairline"], 1)
            self.add("</g>")
        return cid

    def led(self, cx, cy, color, live=True, r=3.2):
        """Status indicator. Only a live tile animates."""
        if live:
            self.css.append(
                "@keyframes halo{0%{r:3.2px;opacity:.5}"
                "70%{r:9px;opacity:0}100%{r:9px;opacity:0}}"
                ".halo{animation:halo 2.6s ease-out infinite}"
                "@keyframes bl{0%,100%{opacity:1}50%{opacity:.45}}"
                ".bl{animation:bl 2.6s ease-in-out infinite}")
            self.add('<circle class="halo" cx="%.1f" cy="%.1f" r="%s" '
                     'fill="%s"/>' % (cx, cy, r, color))
        cls = 'class="bl" ' if live else ""
        self.add('<circle %scx="%.1f" cy="%.1f" r="%s" fill="%s"/>'
                 % (cls, cx, cy, r, color))

    def sparkline(self, x, y, w, h, values, color, fill_color, delay=0.0,
                  baseline=True, smooth=True, marker=True, fill_op=0.8):
        """Area chart that draws itself in once, then holds."""
        if not values or len(values) < 2:
            return
        lo, hi = min(values), max(values)
        rng = (hi - lo) or 1
        n = len(values)
        pts = [(x + i * w / (n - 1), y + h - (v - lo) / float(rng) * h)
               for i, v in enumerate(values)]

        d = _catmull_rom(pts) if smooth else (
            "M" + " L".join("%.1f,%.1f" % p for p in pts))

        gid = self.uid("g")
        self.defs.append(
            '<linearGradient id="%s" x1="0" y1="0" x2="0" y2="1">'
            '<stop offset="0" stop-color="%s" stop-opacity="%s"/>'
            '<stop offset="1" stop-color="%s" stop-opacity="0"/>'
            "</linearGradient>" % (gid, fill_color, fill_op, fill_color))
        self.add('<path d="%s L%.1f,%.1f L%.1f,%.1f Z" fill="url(#%s)"/>'
                 % (d, pts[-1][0], y + h, pts[0][0], y + h, gid))

        length = int(sum(math.dist(pts[i], pts[i + 1])
                         for i in range(n - 1)) * 1.2) + 12
        cls = self.uid("sp")
        # The hidden state lives only inside the keyframes. If a renderer
        # ignores CSS animation entirely, the trace still draws complete
        # rather than vanishing, which a base stroke-dashoffset would cause.
        self.css.append(
            ".%s{animation:d%s 1.15s cubic-bezier(.4,0,.2,1) %ss both}"
            "@keyframes d%s{from{stroke-dasharray:%d;stroke-dashoffset:%d}"
            "to{stroke-dasharray:%d;stroke-dashoffset:0}}"
            % (cls, cls, delay, cls, length, length, length))
        self.add('<path class="%s" d="%s" fill="none" stroke="%s" '
                 'stroke-width="1.6" stroke-linecap="round" '
                 'stroke-linejoin="round"/>' % (cls, d, color))
        if baseline:
            self.line(x, y + h, x + w, y + h, color, 1, opacity=0.16)
        if marker:
            fade = self.uid("fd")
            self.css.append(
                ".%s{animation:f%s .4s ease-out %ss both}"
                "@keyframes f%s{from{opacity:0}to{opacity:1}}"
                % (fade, fade, round(delay + 1.1, 2), fade))
            self.add('<circle class="%s" cx="%.1f" cy="%.1f" r="2.1" '
                     'fill="%s"/>' % (fade, pts[-1][0], pts[-1][1], color))


    def bars(self, x, y, w, h, values, color, delay=0.0, min_h=1.5):
        """Discrete weekly counts.

        Commit activity is sparse and bursty. A smoothed area chart would draw
        a continuous signal through weeks that contain nothing, so the counts
        are drawn as what they are.
        """
        if not values:
            return
        n = len(values)
        hi = max(values) or 1
        slot = w / float(n)
        bw = max(1.6, slot * 0.62)
        cls = self.uid("bs")
        self.css.append(
            ".%s{animation:g%s .5s ease-out both}"
            "@keyframes g%s{from{opacity:0}to{opacity:1}}" % (cls, cls, cls))
        for i, v in enumerate(values):
            bh = max(min_h, h * v / float(hi)) if v else min_h * 0.8
            bx = x + i * slot + (slot - bw) / 2.0
            op = 1.0 if v else 0.16
            self.add('<rect class="%s" x="%.1f" y="%.1f" width="%.1f" '
                     'height="%.1f" rx="%.1f" fill="%s" opacity="%.2f" '
                     'style="animation-delay:%.2fs"/>'
                     % (cls, bx, y + h - bh, bw, bh, min(1.0, bw / 2.0),
                        color, op, delay + i * 0.012))

    def render(self):
        faces = []
        for style, chars in self.chars.items():
            if not chars:
                continue
            b64 = subset_font(style, chars)
            faces.append(
                "@font-face{font-family:'JBM';font-style:normal;"
                "font-weight:%d;src:url(data:font/woff2;base64,%s) "
                "format('woff2')}" % (700 if style == "Bold" else 400, b64))
        # Every hidden state is keyframe-only, so simply cancelling animation
        # leaves each element in its finished state.
        reduce_rule = ("@media(prefers-reduced-motion:reduce){"
                       "*{animation:none!important}}")
        css = ("".join(faces)
               + "text{font-family:%s;-webkit-font-smoothing:antialiased}"
                 % MONO_STACK
               + "".join(dict.fromkeys(self.css))
               + reduce_rule)
        defs = "".join(dict.fromkeys(self.defs))
        return ('<svg xmlns="http://www.w3.org/2000/svg" width="%d" '
                'height="%d" viewBox="0 0 %d %d" role="img" '
                'aria-labelledby="ttl dsc">'
                '<title id="ttl">%s</title><desc id="dsc">%s</desc>'
                '<defs>%s</defs><style>%s</style>%s</svg>'
                % (self.w, self.h, self.w, self.h, esc(self.title),
                   esc(self.desc), defs, css, "".join(self.body)))


def _catmull_rom(pts):
    """Catmull-Rom through the samples, emitted as cubic beziers.

    A plain polyline reads as a chart; a gently smoothed trace reads as a
    signal, which is the whole point of the panel.
    """
    if len(pts) < 3:
        return "M" + " L".join("%.1f,%.1f" % p for p in pts)
    p = [pts[0]] + list(pts) + [pts[-1]]
    d = ["M%.1f,%.1f" % pts[0]]
    for i in range(1, len(p) - 2):
        p0, p1, p2, p3 = p[i - 1], p[i], p[i + 1], p[i + 2]
        c1 = (p1[0] + (p2[0] - p0[0]) / 6.0, p1[1] + (p2[1] - p0[1]) / 6.0)
        c2 = (p2[0] - (p3[0] - p1[0]) / 6.0, p2[1] - (p3[1] - p1[1]) / 6.0)
        d.append("C%.1f,%.1f %.1f,%.1f %.1f,%.1f"
                 % (c1[0], c1[1], c2[0], c2[1], p2[0], p2[1]))
    return " ".join(d)
