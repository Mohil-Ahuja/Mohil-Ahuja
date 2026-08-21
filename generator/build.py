"""Fetch -> render -> write. Run with --local to build without a token.

Usage:
    python generator/build.py            # uses $GITHUB_TOKEN if present
    python generator/build.py --local    # unauthenticated, writes preview.html
    python generator/build.py --offline  # cached/synthetic data, no network
"""
import argparse
import datetime as dt
import hashlib
import json
import os
import sys
import tomllib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import panels  # noqa: E402
from github_api import Client, datestamp  # noqa: E402
from theme import THEMES  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS = os.path.join(ROOT, "assets")
CACHE = os.path.join(ROOT, "data", "cache.json")
VERSION = os.path.join(ROOT, "data", "version.json")


# ---------------------------------------------------------------------------
# data assembly
# ---------------------------------------------------------------------------

def load_conf():
    with open(os.path.join(ROOT, "data", "profile.toml"), "rb") as f:
        return tomllib.load(f)


def load_cache():
    try:
        with open(CACHE, "rb") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def synthetic(n, seed):
    """Deterministic stand-in so an offline build still renders a real shape."""
    out, v = [], 4 + seed % 5
    for i in range(n):
        seed = (seed * 1103515245 + 12345) & 0x7FFFFFFF
        v = max(0, v + (seed % 7) - 3)
        out.append(v)
    return out


def gather(conf, client, offline, cached=False):
    ident = conf["identity"]
    login = ident["handle"]
    cache = load_cache()
    fresh = {"series": {}}

    if cached:
        # Replay the last successful fetch. Useful when the unauthenticated
        # rate limit is exhausted but the committed output should still be
        # real rather than synthetic.
        series = cache.get("series") or {}
        langs = cache.get("languages") or {}
        grand = sum(langs.values()) or 1
        shares = {c["label"]: sum(langs.get(l, 0) for l in c["langs"]) / grand
                  for c in conf["capability"]}
        last = cache.get("last")
        stats = dict(cache.get("stats") or {})
        stats["last_push"] = datestamp(last["at"]) if last else "unknown"
        weeks = [0] * 52
        for sv in series.values():
            for i, v in enumerate(sv[-52:]):
                weeks[i] += v
        return ident, stats, weeks, series, shares, last, cache

    if offline:
        contrib = synthetic(52, 7)
        stats = {"contrib_total": sum(contrib), "repos": 24,
                 "primary_lang": "C++", "last_push": "2h ago"}
        for i, p in enumerate(conf["project"]):
            fresh["series"][p["key"]] = (
                synthetic(52, i + 3) if p["repo"] else [])
        shares = {c["label"]: 0.0 for c in conf["capability"]}
        return ident, stats, contrib, fresh["series"], shares, None, fresh

    user = client.user(login)
    repos = client.repos(login)

    # --- contribution signal ---------------------------------------------
    gql = client.contributions(login)
    if gql:
        contrib = gql["weeks"][-52:]
        contrib_total = gql["total"]
    else:
        contrib, contrib_total = [], 0

    # --- per-project telemetry -------------------------------------------
    series = {}
    for p in conf["project"]:
        s = client.commit_activity(p["repo"]) if p["repo"] else None
        if not s:
            s = (cache.get("series") or {}).get(p["key"]) or []
        series[p["key"]] = s
    fresh["series"] = series

    if not contrib:
        # Fallback: superimpose every repo's weekly commit counts.
        weeks = [0] * 52
        for s in series.values():
            for i, v in enumerate(s[-52:]):
                weeks[i] += v
        contrib = weeks
        contrib_total = sum(weeks)

    # --- language byte share ---------------------------------------------
    # Jupyter Notebook byte counts are dominated by base64 image output
    # embedded in the .ipynb, not by code. Left in, they were 95% of every
    # byte on this account and made the share numbers meaningless.
    EXCLUDE = {"Jupyter Notebook", "HTML", "CSS", "SCSS"}
    totals = {}
    for r in repos:
        if r.get("fork"):
            continue
        for lang, n in client.languages(r["full_name"]).items():
            if lang in EXCLUDE:
                continue
            totals[lang] = totals.get(lang, 0) + n
    grand = sum(totals.values()) or 1
    shares = {}
    for c in conf["capability"]:
        shares[c["label"]] = sum(totals.get(l, 0) for l in c["langs"]) / grand
    fresh["languages"] = totals

    primary = max(totals, key=totals.get) if totals else "C++"
    last = client.last_push_event(login)
    stats = {
        "contrib_total": contrib_total or sum(contrib),
        "repos": user.get("public_repos", len(repos)),
        "primary_lang": primary,
        "last_push": datestamp(last["at"]) if last else "unknown",
    }
    fresh["stats"] = stats
    fresh["last"] = last
    return ident, stats, contrib, series, shares, last, fresh


# ---------------------------------------------------------------------------
# rendering
# ---------------------------------------------------------------------------

def write(name, content):
    os.makedirs(ASSETS, exist_ok=True)
    path = os.path.join(ASSETS, name)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(content)
    return path


def render_all(conf, ident, stats, contrib, series, shares):
    written = []
    for t in THEMES:
        suffix = t["name"]
        written.append(write("hero-%s.svg" % suffix,
                             panels.hero(t, ident, stats, contrib)))
        written.append(write("capability-%s.svg" % suffix,
                             panels.capability(t, conf["capability"], shares)))
        for p in conf["project"]:
            written.append(write(
                "tile-%s-%s.svg" % (p["key"], suffix),
                panels.tile(t, p, series.get(p["key"]))))
    return written



def digest(paths):
    """Short content hash across every rendered asset."""
    h = hashlib.sha256()
    for path in sorted(paths):
        with open(path, "rb") as f:
            h.update(f.read())
    return h.hexdigest()[:10]


def touch_version(ver):
    """Record when the rendered output last actually changed."""
    try:
        with open(VERSION, encoding="utf-8") as f:
            state = json.load(f)
    except (OSError, ValueError):
        state = {}
    if state.get("ver") != ver:
        state = {"ver": ver,
                 "changed": dt.datetime.now(dt.UTC).strftime("%Y-%m-%d")}
        with open(VERSION, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=1)
    return state["changed"]


def picture(base, alt, width, ver):
    return ('<picture>'
            '<source media="(prefers-color-scheme: dark)" '
            'srcset="assets/%s-dark.svg?v=%s">'
            '<img alt="%s" src="assets/%s-light.svg?v=%s" width="%d">'
            '</picture>' % (base, ver, alt, base, ver, width))


def render_readme(conf, ident, last, ver, stamp):
    tpl_path = os.path.join(ROOT, "generator", "templates", "README.tmpl.md")
    with open(tpl_path, encoding="utf-8") as f:
        tpl = f.read()

    rows = []
    projects = conf["project"]
    for i in range(0, len(projects), 2):
        pair = projects[i:i + 2]
        cells = []
        for p in pair:
            alt = "%s — %s %s. %s" % (p["title"], p["value"], p["unit"],
                                      p["caption"])
            cells.append('<td width="50%%" valign="top">'
                         '<a href="%s">%s</a></td>'
                         % (p["href"], picture("tile-" + p["key"], alt, 428,
                                               ver)))
        if len(cells) == 1:
            cells.append('<td width="50%"></td>')
        rows.append("<tr>" + "".join(cells) + "</tr>")

    ledger = "\n".join(
        "| `%s` | %s | %s |" % (e["year"], e["what"], e.get("detail", ""))
        for e in sorted(conf["ledger"], key=lambda e: e["year"],
                        reverse=True))

    secondary = "\n".join(
        "- **[%s](%s)** — %s" % (s["title"], s["href"], s["blurb"])
        for s in conf["secondary"])

    if last and last.get("repo"):
        current = ("`%s` — %s _(%s)_"
                   % (last["repo"], last["message"] or "pushed",
                      datestamp(last["at"])))
    else:
        current = "_no recent public push_"

    out = tpl
    for key, val in {
        "HERO": picture("hero", "%s — %s" % (ident["name"], ident["role"]),
                        880, ver),
        "TILES": "\n".join(rows),
        "CAPABILITY": picture("capability", "Capability matrix", 880, ver),
        "LEDGER": ledger,
        "SECONDARY": secondary,
        "CURRENT": current,
        "EMAIL": ident["email"],
        "LINKEDIN": ident["linkedin"],
        "STAMP": stamp,
    }.items():
        out = out.replace("{{%s}}" % key, val)

    with open(os.path.join(ROOT, "README.md"), "w", encoding="utf-8",
              newline="\n") as f:
        f.write(out)


def render_preview(conf):
    """Local-only harness: every asset in mock GitHub light and dark shells."""
    def block(theme, bg, fg):
        parts = ['<div class="pane" style="background:%s;color:%s">' % (bg, fg)]
        parts.append('<img src="assets/hero-%s.svg" width="880">' % theme)
        parts.append('<div class="grid">')
        for p in conf["project"]:
            parts.append('<img src="assets/tile-%s-%s.svg" width="428">'
                         % (p["key"], theme))
        parts.append("</div>")
        parts.append('<img src="assets/capability-%s.svg" width="880">' % theme)
        parts.append("</div>")
        return "".join(parts)

    html = (
        "<!doctype html><meta charset=utf-8><title>profile preview</title>"
        "<style>body{margin:0;font-family:system-ui}"
        ".pane{padding:32px;display:flex;flex-direction:column;gap:16px;"
        "align-items:center}"
        ".grid{display:grid;grid-template-columns:428px 428px;gap:16px}"
        "img{display:block}</style>"
        + block("light", "#ffffff", "#1f2328")
        + block("dark", "#0d1117", "#e6edf3"))
    with open(os.path.join(ROOT, "preview.html"), "w", encoding="utf-8") as f:
        f.write(html)


# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--local", action="store_true",
                    help="write preview.html as well")
    ap.add_argument("--offline", action="store_true",
                    help="no network; synthetic telemetry")
    ap.add_argument("--cached", action="store_true",
                    help="no network; replay the last fetched data")
    args = ap.parse_args()

    conf = load_conf()
    client = Client()
    ident, stats, contrib, series, shares, last, fresh = gather(
        conf, client, args.offline, args.cached)

    written = render_all(conf, ident, stats, contrib, series, shares)

    # The cache-busting token is a digest of what was actually rendered, not a
    # timestamp. An unchanged profile therefore produces a byte-identical
    # README, the scheduled run finds an empty diff, and no commit is made.
    ver = digest(written)
    stamp = touch_version(ver)
    render_readme(conf, ident, last, ver, stamp)

    if not args.offline and not args.cached:
        with open(CACHE, "w", encoding="utf-8") as f:
            json.dump(fresh, f, indent=1, sort_keys=True)
    if args.local or args.offline or args.cached:
        render_preview(conf)

    for w in client.warnings:
        print("warn:", w, file=sys.stderr)
    print("built %d assets, version %s" % (len(conf["project"]) * 2 + 4, ver))


if __name__ == "__main__":
    main()
