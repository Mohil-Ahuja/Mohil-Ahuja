"""GitHub REST + GraphQL client on the standard library only.

No third-party HTTP dependency, so the workflow needs no install step beyond
fontTools. Every call degrades to a documented fallback rather than raising,
because a rate limit or a 202 must not leave the profile rendering a flat line.
"""
import json
import os
import time
import urllib.error
import urllib.request

API = "https://api.github.com"
UA = "mohil-profile-generator"


class Client:
    def __init__(self, token=None):
        self.token = token or os.environ.get("GITHUB_TOKEN") or ""
        self.warnings = []

    def _req(self, url, data=None, headers=None):
        h = {"User-Agent": UA, "Accept": "application/vnd.github+json"}
        if self.token:
            h["Authorization"] = "Bearer " + self.token
        h.update(headers or {})
        body = json.dumps(data).encode() if data is not None else None
        req = urllib.request.Request(url, data=body, headers=h)
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read().decode() or "null")

    def get(self, path, retries=3):
        url = path if path.startswith("http") else API + path
        for attempt in range(retries):
            try:
                status, payload = self._req(url)
            except urllib.error.HTTPError as e:
                if e.code in (403, 429) and attempt < retries - 1:
                    time.sleep(2 + attempt * 3)
                    continue
                self.warnings.append("%s -> HTTP %s" % (path, e.code))
                return None
            except Exception as e:  # network, DNS, timeout
                self.warnings.append("%s -> %s" % (path, e.__class__.__name__))
                return None
            # 202 means GitHub is computing the statistic; it needs a moment.
            if status == 202 or payload is None:
                time.sleep(3 + attempt * 4)
                continue
            return payload
        self.warnings.append("%s -> still computing after %d tries"
                             % (path, retries))
        return None

    # ---- endpoints ----------------------------------------------------

    def user(self, login):
        return self.get("/users/%s" % login) or {}

    def repos(self, login):
        out, page = [], 1
        while page <= 4:
            batch = self.get("/users/%s/repos?per_page=100&type=owner"
                             "&sort=pushed&page=%d" % (login, page))
            if not batch:
                break
            out.extend(batch)
            if len(batch) < 100:
                break
            page += 1
        return out

    def commit_activity(self, full_name):
        """52 weeks of weekly commit counts, oldest first."""
        data = self.get("/repos/%s/stats/commit_activity" % full_name)
        if not isinstance(data, list) or not data:
            return None
        return [int(w.get("total", 0)) for w in data]

    def languages(self, full_name):
        return self.get("/repos/%s/languages" % full_name) or {}

    def last_push_event(self, login):
        """Most recent push to a repository other than the profile repo.

        The refresh workflow pushes to `login/login` itself, so without this
        exclusion the line would permanently report the generator committing
        its own output.
        """
        events = self.get("/users/%s/events/public?per_page=100" % login)
        if not isinstance(events, list):
            return None
        skip = ("%s/%s" % (login, login)).lower()
        for e in events:
            if (e.get("repo") or {}).get("name", "").lower() == skip:
                continue
            if e.get("type") == "PushEvent":
                commits = (e.get("payload") or {}).get("commits") or []
                msg = commits[-1]["message"].splitlines()[0] if commits else ""
                return {
                    "repo": (e.get("repo") or {}).get("name", ""),
                    "message": msg,
                    "at": e.get("created_at", ""),
                }
        return None

    def contributions(self, login):
        """53 weekly contribution totals via GraphQL.

        The default workflow token can read public contribution data. If it
        cannot, the caller falls back to summing per-repo commit activity.
        """
        if not self.token:
            return None
        q = ("query($l:String!){user(login:$l){contributionsCollection{"
             "contributionCalendar{totalContributions weeks{"
             "contributionDays{contributionCount}}}}}}")
        try:
            _, payload = self._req(
                "https://api.github.com/graphql",
                {"query": q, "variables": {"l": login}},
                {"Content-Type": "application/json"})
        except Exception as e:
            self.warnings.append("graphql -> %s" % e.__class__.__name__)
            return None
        try:
            cal = (payload["data"]["user"]["contributionsCollection"]
                   ["contributionCalendar"])
        except (TypeError, KeyError):
            self.warnings.append("graphql -> contributions unavailable")
            return None
        weeks = [sum(d["contributionCount"] for d in w["contributionDays"])
                 for w in cal["weeks"]]
        return {"weeks": weeks, "total": cal["totalContributions"]}


def datestamp(iso):
    """Absolute date from an ISO-8601 timestamp.

    Deliberately not a relative "3h ago": a relative string changes on every
    scheduled run, which would make an otherwise unchanged profile produce a
    fresh commit four times a day.
    """
    if not iso:
        return "unknown"
    try:
        time.strptime(iso, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return "unknown"
    return iso[:10]
