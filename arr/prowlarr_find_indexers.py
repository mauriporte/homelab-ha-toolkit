"""Find public Prowlarr indexers you haven't added yet that answer from this network.

Run it on the Prowlarr host (it reads Prowlarr's config folder read-only):
    python3 prowlarr_find_indexers.py /path/to/prowlarr/config [--lang en,es] [--flaresolverr http://localhost:8191]

For each public definition in <config>/Definitions that isn't in prowlarr.db yet, it opens the site's
links in order and prints: OK (opens directly), CF (Cloudflare/DDoS-Guard page: needs FlareSolverr),
or the error. With --flaresolverr, CF sites are retried through FlareSolverr (FS-OK = add with your
FlareSolverr tag). A site that opens is not proof that searches work: add it and run Prowlarr's Test.
Definitions that Prowlarr's catalogue has dropped stay on disk; adding one shows a "no definition" error.
"""
import argparse, concurrent.futures as cf, json, os, re, sqlite3, urllib.request

UA = "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0"
CHALLENGE = re.compile(r"Just a moment|cf-chl|challenge-platform|DDoS-Guard")


def field(text, key):
    m = re.search(rf"^{key}:\s*(.+)$", text, re.M)
    return m[1].strip().strip("\"'") if m else ""


def links(text):
    head = text.split("legacylinks")[0].split("caps:")[0]
    return re.findall(r"^\s*-\s*(https?://\S+)", head, re.M)


def added(config):
    db = sqlite3.connect(f"file:{config}/prowlarr.db?mode=ro", uri=True)
    have = set()
    for s, in db.execute("select Settings from Indexers"):
        s = json.loads(s)
        have.add(s.get("definitionFile"))
        m = re.search(r"/indexers/([^/]+)/results", s.get("baseUrl") or "")  # Jackett-backed Torznab
        if m:
            have.add(m[1])
    return have


def fetch(url):
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=15) as r:
            body = r.read(200000).decode(errors="replace")
            return "CF" if CHALLENGE.search(body) else "OK"
    except urllib.error.HTTPError as e:
        body = e.read(200000).decode(errors="replace")
        return "CF" if CHALLENGE.search(body) else f"HTTP {e.code}"
    except Exception as e:
        return type(e).__name__ + ": " + str(getattr(e, "reason", e))[:60]


def via_flaresolverr(fs, url):
    req = urllib.request.Request(fs.rstrip("/") + "/v1", json.dumps({"cmd": "request.get", "url": url, "maxTimeout": 60000}).encode(),
                                 {"Content-Type": "application/json"})
    try:
        r = json.load(urllib.request.urlopen(req, timeout=75))
        s = r.get("solution") or {}
        ok = r.get("status") == "ok" and str(s.get("status", "")).startswith("2") and not CHALLENGE.search(s.get("response") or "")
        return "FS-OK" if ok else f"FS-FAIL {r.get('message', '')[:60]}"
    except Exception as e:
        return f"FS-FAIL {str(e)[:60]}"


def check(item, fs):
    result = "no links"
    for u in item["links"][:4]:
        result = fetch(u)
        if result == "CF" and fs:
            result = via_flaresolverr(fs, u)
        if result in ("OK", "FS-OK"):
            return {**item, "url": u, "result": result}
    return {**item, "url": item["links"][0] if item["links"] else "", "result": result}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("config")
    ap.add_argument("--lang", help="comma-separated language prefixes, e.g. en,es")
    ap.add_argument("--flaresolverr")
    a = ap.parse_args()
    have, langs = added(a.config), tuple(a.lang.split(",")) if a.lang else ()
    todo = []
    for f in sorted(os.listdir(f"{a.config}/Definitions")):
        t = open(f"{a.config}/Definitions/{f}", encoding="utf-8", errors="replace").read()
        if field(t, "type") != "public" or f[:-4] in have or (langs and not field(t, "language").startswith(langs)):
            continue
        cats = sorted(set(re.findall(r"cat:\s*(\w+)", t)))
        todo.append({"id": f[:-4], "name": field(t, "name"), "lang": field(t, "language"), "adult": cats == ["XXX"], "links": links(t)})
    with cf.ThreadPoolExecutor(3 if a.flaresolverr else 16) as ex:  # FlareSolverr runs one browser per request
        for r in ex.map(lambda i: check(i, a.flaresolverr), todo):
            print(f"{r['id']:<24} {r['lang']:<6} {'XXX ' if r['adult'] else '    '}{r['url']:<45} {r['result']}")


assert field("type: public\nname: 'X'\n", "name") == "X"
assert links("links:\n  - https://a.example/\nlegacylinks:\n  - https://old.example/\n") == ["https://a.example/"]

if __name__ == "__main__":
    main()
