# Deep probe: follow HLS master -> media playlist -> last segment and check it is real video (TS/fMP4).
# DASH (.mpd) manifests are checked with a segment from the SegmentTemplate when simple, else marked "dash".
# Usage: iptv_probe2.py <scratch> <direct|proxy> [proxy_url]   (read-only)
import json, os, re, ssl, sys, time, urllib.parse, urllib.request, concurrent.futures as cf
S, mode = sys.argv[1], sys.argv[2]; PX = sys.argv[3] if len(sys.argv) > 3 else None
F = json.load(open(S + "/iptv_final.json", encoding="utf-8"))
if os.environ.get("PROBE_IDS"):  # recheck a subset only
    _keep = set(json.load(open(os.environ["PROBE_IDS"]))); F = [x for x in F if x["id"] in _keep]
    mode = mode + os.environ.get("PROBE_TAG", "_recheck")
ctx = ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE
hs = [urllib.request.HTTPSHandler(context=ctx)]
if mode == "proxy": hs.append(urllib.request.ProxyHandler({"http": PX, "https": PX}))
op = urllib.request.build_opener(*hs)
def get(u, x, n=None):
    h = {"User-Agent": x.get("ua") or "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/149 Safari/537.36"}
    if x.get("ref"): h["Referer"] = x["ref"]
    r = op.open(urllib.request.Request(u, headers=h), timeout=12)
    b = r.read(n or 1_000_000)  # cap: some URLs are endless video streams, not playlists
    if b[:2] == bytes((0x1f, 0x8b)) and not n:  # gzip-compressed playlist (players decompress it)
        import gzip, zlib
        try: b = gzip.decompress(b)
        except Exception: b = zlib.decompressobj(31).decompress(b)
    return r.geturl(), b
def isvideo(b):
    return b[:1] == b"G" or b"ftyp" in b[:64] or b"moof" in b[:64] or b"styp" in b[:64] or b[:3] == b"ID3" or b[188:189] == b"G"
def probe(x):
    t = time.time()
    try:
        u, b = get(x["url"], x)
        txt = b.decode("utf-8", "ignore")
        for _ in range(3):
            if "#EXT-X-STREAM-INF" in txt:  # master: take the first variant
                v = [l for l in txt.splitlines() if l and not l.startswith("#")][0]
                u, b = get(urllib.parse.urljoin(u, v), x); txt = b.decode("utf-8", "ignore"); continue
            break
        if "#EXTINF" in txt:
            seg = [l for l in txt.splitlines() if l and not l.startswith("#")][-1]
            _, sb = get(urllib.parse.urljoin(u, seg), x, 4096)
            if isvideo(sb):
                return x["id"], "ok", round(time.time() - t, 2)
            k = re.search(r'#EXT-X-KEY:METHOD=AES-128,URI="([^"]+)"', txt)  # standard encrypted HLS: needs its key
            if k:
                _, kb = get(urllib.parse.urljoin(u, k.group(1)), x, 64)
                return x["id"], ("ok" if len(kb) == 16 else "clave de cifrado no válida"), round(time.time() - t, 2)
            return x["id"], "segmento no es vídeo", round(time.time() - t, 2)
        if "<MPD" in txt:
            return x["id"], "dash", round(time.time() - t, 2)
        if isvideo(b[:4096]):
            return x["id"], "ok", round(time.time() - t, 2)
        return x["id"], "respuesta rara", round(time.time() - t, 2)
    except Exception as e:
        return x["id"], f"{type(e).__name__}:{getattr(e, 'code', '') or str(e)[:50]}", round(time.time() - t, 2)
# progress is appended per channel, so an interruption loses nothing and a rerun resumes
prog = f"{S}/iptv_probe2_{mode}.jsonl"
done = {}
if os.path.exists(prog):
    for line in open(prog, encoding="utf-8"):
        i, st, t = json.loads(line); done[i] = (i, st, t)
todo = [x for x in F if x["id"] not in done]
with open(prog, "a", encoding="utf-8") as fh, cf.ThreadPoolExecutor(16) as ex:
    for r in ex.map(probe, todo):
        fh.write(json.dumps(r, ensure_ascii=False) + chr(10)); fh.flush(); done[r[0]] = r
res = [done[x["id"]] for x in F]
json.dump(res, open(f"{S}/iptv_probe2_{mode}.json", "w"), ensure_ascii=False)
import collections, statistics
by = {i: (s, t) for i, s, t in res}
okk = [x for x in F if by[x["id"]][0] == "ok"]
print(mode, "| ok:", len(okk), "/", len(F), "| results:", collections.Counter(s.split(":")[0] for _, s, _ in res).most_common(6))
for k in ("ES", "AR", "UK", "US"):
    a = [x for x in F if x["country"] == k]; print("  ", k, sum(1 for x in a if by[x["id"]][0] == "ok"), "/", len(a))
print("   median time to first segment:", statistics.median(by[x["id"]][1] for x in okk), "s")
