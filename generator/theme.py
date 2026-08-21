"""Palettes and type scale for the profile dashboard.

Two palettes are generated as separate files and selected in the README with
<picture media="(prefers-color-scheme: dark)">, which is the mechanism GitHub
documents for theme-aware images. A prefers-color-scheme media query inside an
<img>-rendered SVG would only follow the OS setting, not the GitHub theme.
"""

DARK = dict(
    name="dark",
    bg="#0B0E14",
    panel="#10141B",
    panel_top="#141922",
    border="#1F2733",
    hairline="#1A212B",
    grid="#161C25",
    text="#C8D0DB",
    text_bright="#E8EDF4",
    secondary="#77828F",
    dim="#4A5462",
    accent="#E9A23B",
    accent_soft="#8A6529",
    data="#6EA8D8",
    data_soft="#2B4055",
    ok="#4EA96B",
    warn="#E9A23B",
    idle="#5A6472",
    shadow="#05070B",
)

LIGHT = dict(
    name="light",
    bg="#FFFFFF",
    panel="#F7F9FB",
    panel_top="#EFF3F7",
    border="#D5DCE4",
    hairline="#E3E9EF",
    grid="#EBF0F5",
    text="#1F262E",
    text_bright="#0D1219",
    secondary="#5A6673",
    dim="#8B96A3",
    accent="#B5760F",
    accent_soft="#D9A441",
    data="#3D6E9E",
    data_soft="#C5D8E8",
    ok="#2E7D4F",
    warn="#B5760F",
    idle="#94A0AD",
    shadow="#C9D2DC",
)

THEMES = (DARK, LIGHT)

# Type scale (px). Monospace throughout, so widths are predictable:
# JetBrains Mono advance width is 0.6 em.
ADVANCE = 0.600

def text_width(s, size):
    """Exact rendered width, which only holds because the font is embedded."""
    return len(s) * size * ADVANCE
