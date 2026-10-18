# Time how long each channel takes to start through Threadfin (the path Jellyfin/Kodi use).
# "Start" = first 64 KB of video data received. User rule (17/10): > 5 s = removed.
# A channel over the limit is retried once and only marked slow if both tries exceed it.
# One channel at a time with a 2 s pause: several at once made Threadfin reject streams and even crash. Resumable: results appended to a .jsonl.
import concurrent.futures as cf, json, os, re, sys, time, requests

TF = os.environ.get("THREADFIN", "localhost:34400")  # host:port of Threadfin

LIMIT, TIMEOUT, NEED = 5.0, 9.0, 64 * 1024
OUT = "iptv_starttime.jsonl"
m3u = requests.get(f"http://{TF}/m3u/threadfin.m3u", timeout=60).text
chans = re.findall(r'#EXTINF:[^\n]*?tvg-id="([^"]*)"[^\n]*,(.*)\n(http\S+)', m3u)
# Threadfin may write its Docker-internal IP in the playlist (unless httpThreadfinDomain is set); use THREADFIN
chans = [(t, n, re.sub(r"^http://[^/]+", f"http://{TF}", u)) for t, n, u in chans]
done = {}
if os.path.exists(OUT):
    for line in open(OUT, encoding="utf-8"):
        r = json.loads(line); done[r["url"]] = r


def start_time(url):
    t0 = time.monotonic(); got = 0
    try:
        with requests.get(url, stream=True, timeout=TIMEOUT) as r:
            for chunk in r.iter_content(8192):
                got += len(chunk)
                if got >= NEED:
                    return round(time.monotonic() - t0, 2)
                if time.monotonic() - t0 > TIMEOUT:
                    break
    except requests.RequestException:
        pass
    return None  # no video within TIMEOUT


def test(c):
    time.sleep(2)
    tid, name, url = c
    t1 = start_time(url)
    t2 = start_time(url) if (t1 is None or t1 > LIMIT) else None
    best = min([t for t in (t1, t2) if t is not None], default=None)
    return {"name": name.strip(), "tvg_id": tid, "url": url, "t1": t1, "t2": t2,
            "slow": best is None or best > LIMIT}


todo = [c for c in chans if c[2] not in done]
print(f"channels {len(chans)} | already tested {len(done)} | to test {len(todo)}", flush=True)
with cf.ThreadPoolExecutor(1) as ex, open(OUT, "a", encoding="utf-8") as f:
    for i, r in enumerate(ex.map(test, todo), 1):
        f.write(json.dumps(r, ensure_ascii=False) + "\n"); f.flush()
        if i % 50 == 0:
            print(i, "tested", flush=True)
res = [json.loads(l) for l in open(OUT, encoding="utf-8")]
slow = [r for r in res if r["slow"]]
print(f"done: {len(res)} tested, {len(slow)} slow/dead (> {LIMIT} s twice), {len(res) - len(slow)} kept")
