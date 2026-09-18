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
        fresh = dict(cache)
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
        return (ident, stats, weeks, series, shares, last,
                cache.get("prs") or [], fresh)

    if offline:
        contrib = synthetic(52, 7)
        stats = {"contrib_total": sum(contrib), "repos": 24,
                 "primary_lang": "C++", "last_push": "2h ago"}
        for i, p in enumerate(conf["project"]):
            fresh["series"][p["key"]] = (
                synthetic(52, i + 3) if p["repo"] else [])
        shares = {c["label"]: 0.0 for c in conf["capability"]}
        return (ident, stats, contrib, fresh["series"], shares, None,
                [], fresh)

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
    # Only needed as a fallback for the hero trace now that the project tiles
    # no longer draw commit bars, so it is fetched only when the contribution
    # calendar was unavailable (an unauthenticated build, usually).
    series = dict(cache.get("series") or {})
    if not contrib:
        for p in conf["project"]:
            s = client.commit_activity(p["repo"]) if p["repo"] else None
            if s:
                series[p["key"]] = s
        weeks = [0] * 52
        for s in series.values():
            for i, v in enumerate(s[-52:]):
                weeks[i] += v
        contrib = weeks
        contrib_total = sum(weeks)
    fresh["series"] = series

    # --- upstream pull requests ------------------------------------------
    prs = client.authored_prs(login)
    if prs is None:
        prs = cache.get("prs") or []
        client.warnings.append("pull request search unavailable; using cache")
    fresh["prs"] = prs

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
    return ident, stats, contrib, series, shares, last, prs, fresh


def oss_ledger(conf, prs):
    """Fold the raw pull request list into what the page actually shows.

    Returns (summary, rows, recent). `rows` is one entry per upstream
    organisation, ordered by what merged rather than by what was opened:
    anyone can open a pull request, so the merged count is the part that
    carries information.
    """
    meta = {o["owner"].lower(): o for o in conf.get("org", [])}
    mine = conf["identity"]["handle"].lower()

    by_org, repos = {}, set()
    merged = opened = closed = 0
    for pr in prs:
        org = pr["org"].lower()
        # Own repositories are the projects section's job; this panel is about
        # work accepted into codebases someone else maintains.
        if org == mine:
            continue
        repos.add(pr["repo"])
        slot = by_org.setdefault(org, {"merged": 0, "open": 0, "closed": 0})
        slot[pr["state"]] += 1
        if pr["state"] == "merged":
            merged += 1
        elif pr["state"] == "open":
            opened += 1
        else:
            closed += 1

    rows = []
    for org, counts in by_org.items():
        m = meta.get(org, {})
        rows.append({
            "owner": org,
            "name": m.get("name", org),
            "badge": m.get("badge", ""),
            "what": m.get("what", ""),
            "merged": counts["merged"],
            "open": counts["open"],
            "closed": counts["closed"],
        })
    rows.sort(key=lambda r: (-r["merged"], -(r["open"] + r["closed"]),
                             r["name"]))

    summary = {
        "total": merged + opened + closed,
        "merged": merged,
        "open": opened,
        "closed": closed,
        "orgs": len(rows),
        "repos": len(repos),
    }

    upstream = [p for p in prs if p["org"].lower() != mine]
    recent = sorted((p for p in upstream if p["state"] == "merged"),
                    key=lambda p: p["merged"], reverse=True)
    review = sorted((p for p in upstream if p["state"] == "open"),
                    key=lambda p: p["created"], reverse=True)
    return summary, rows, {"merged": recent, "review": review}


# ---------------------------------------------------------------------------
# rendering
# ---------------------------------------------------------------------------

def write(name, content):
    os.makedirs(ASSETS, exist_ok=True)
    path = os.path.join(ASSETS, name)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(content)
    return path


def render_all(conf, ident, stats, contrib, shares, summary, org_rows):
    written = []
    for t in THEMES:
        suffix = t["name"]
        written.append(write("hero-%s.svg" % suffix,
                             panels.hero(t, ident, stats, contrib)))
        written.append(write("capability-%s.svg" % suffix,
                             panels.capability(t, conf["capability"], shares)))
        written.append(write("oss-%s.svg" % suffix,
                             panels.contributions(t, summary, org_rows)))
        for p in conf["project"]:
            written.append(write(
                "tile-%s-%s.svg" % (p["key"], suffix),
                panels.tile(t, p)))
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


def render_readme(conf, ident, last, ver, stamp, summary, recent):
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

    # "What am I on right now" is answered better by the newest upstream pull
    # request than by the newest push: a push to a fork is usually a branch
    # nobody has seen, while an open PR names the codebase, the problem, and
    # the state it is in.
    newest = max(recent["review"] + recent["merged"],
                 key=lambda pr: (pr["created"], pr["number"]), default=None)
    if newest:
        current = ("**Currently** — in [`%s`](https://github.com/%s): "
                   "[`#%s`](%s) %s, %s."
                   % (newest["repo"], newest["repo"], newest["number"],
                      newest["url"], newest["title"],
                      "merged " + newest["merged"] if newest["state"] == "merged"
                      else "opened " + newest["created"]))
    elif last and last.get("repo"):
        current = ("**Currently** — last push to [`%s`](https://github.com/%s)"
                   " _(%s)_" % (last["repo"], last["repo"],
                                datestamp(last["at"])))
    else:
        current = "_no recent public activity_"

    def pr_line(pr, stamp_key, label):
        return ("- [`%s#%s`](%s) — %s _(%s %s)_"
                % (pr["repo"], pr["number"], pr["url"], pr["title"],
                   label, pr[stamp_key]))

    show = int(conf.get("contributions", {}).get("show", 5))
    merged_list = "\n".join(pr_line(pr, "merged", "merged")
                            for pr in recent["merged"][:show])
    review_list = "\n".join(pr_line(pr, "created", "opened")
                            for pr in recent["review"][:show])
    if not merged_list:
        merged_list = "_nothing merged upstream yet_"
    if not review_list:
        review_list = "_nothing awaiting review_"

    more_merged = max(0, len(recent["merged"]) - show)
    more_review = max(0, len(recent["review"]) - show)
    if more_merged:
        merged_list += "\n- …and %d more merged upstream" % more_merged
    if more_review:
        review_list += "\n- …and %d more open" % more_review

    headline = ("**%d pull requests** across **%d organisations** — "
                "**%d merged upstream**, %d in review."
                % (summary["total"], summary["orgs"], summary["merged"],
                   summary["open"]))

    out = tpl
    for key, val in {
        "HERO": picture("hero", "%s — %s" % (ident["name"], ident["role"]),
                        880, ver),
        "TILES": "\n".join(rows),
        "CAPABILITY": picture("capability", "Capability matrix", 880, ver),
        "LEDGER": ledger,
        "SECONDARY": secondary,
        "CURRENT": current,
        "OSS": picture("oss", "Open source contributions: %d pull requests "
                              "across %d organisations, %d merged"
                              % (summary["total"], summary["orgs"],
                                 summary["merged"]), 880, ver),
        "OSS_HEADLINE": headline,
        "OSS_MERGED": merged_list,
        "OSS_REVIEW": review_list,
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
        parts.append('<img src="assets/oss-%s.svg" width="880">' % theme)
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
    ident, stats, contrib, series, shares, last, prs, fresh = gather(
        conf, client, args.offline, args.cached)
    summary, org_rows, recent = oss_ledger(conf, prs)

    written = render_all(conf, ident, stats, contrib, shares, summary,
                         org_rows)

    # The cache-busting token is a digest of what was actually rendered, not a
    # timestamp. An unchanged profile therefore produces a byte-identical
    # README, the scheduled run finds an empty diff, and no commit is made.
    ver = digest(written)
    stamp = touch_version(ver)
    render_readme(conf, ident, last, ver, stamp, summary, recent)

    if not args.offline and not args.cached:
        with open(CACHE, "w", encoding="utf-8") as f:
            json.dump(fresh, f, indent=1, sort_keys=True)
    if args.local or args.offline or args.cached:
        render_preview(conf)

    for w in client.warnings:
        print("warn:", w, file=sys.stderr)
    print("built %d assets, version %s; %d PRs, %d merged upstream"
          % (len(written), ver, summary["total"], summary["merged"]))


if __name__ == "__main__":
    main()
