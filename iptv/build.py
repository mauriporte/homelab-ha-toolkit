# Build the IPTV selection from the iptv-org API data (see fetch_data.py). Usage: python build.py <workdir>
# Rules: Spanish/English only; no US local stations (only national ones); <=1080p; one stream per
# channel; no religious, teleshopping/sales/ads, tarot or local news; Spain and Argentina kept even without EPG,
# everything else only with EPG (iptv-org guides, or recovered by name from the epgshare01 country guides).
import collections, gzip, json, re, sys, unicodedata
import xml.etree.ElementTree as ET

S = sys.argv[1]
D, E = S + "/iptv_data", S + "/iptv_epg"
L = lambda f: json.load(open(f"{D}/{f}.json", encoding="utf-8"))
ch = {c["id"]: c for c in L("channels")}
feeds = {(f["channel"], f["id"]): f for f in L("feeds")}
guides = collections.defaultdict(list)
for g in L("guides"):
    guides[g["channel"]].append(g)

KEEP_NO_EPG = {"ES", "AR"}
BAD_CATS = {"religious", "shop", "xxx"}
BAD_WORDS = re.compile(r"tarot|vident|videnc|astrolog|horoscop|esoter|teletienda|tele ?venta|televenta|shopping|"
                       r"\bshop\b|\bqvc\b|\bhsn\b|jewel|joyer|\btienda\b|\bventas?\b|infomercial|anuncio|publicidad|"
                       r"\bads?\b|church|iglesia|gospel|evangel|cristian|christ|catolic|catholic|biblia|bible|"
                       r"\bfe\b|esperanza tv|enlace|3abn|daystar|\btbn\b|\bewtn\b|adventist|mision|ministr|pastor|"
                       r"diocesan|islam|quran|coran", re.I)

def norm(s):
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"\b(hd|sd|fhd|uhd|4k|tv|channel|canal|el|la|the|us|uk|es|ar)\b", " ", s)
    return re.sub(r"[^a-z0-9]+", "", s)

def local(f):
    return all(a.split("/")[0] in ("ct", "s") for a in f["broadcast_area"])

drop = collections.Counter()
cand = []
for s in L("streams"):
    c = ch.get(s["channel"]); f = feeds.get((s["channel"], s["feed"]))
    if not c or not f: drop["sin canal identificado"] += 1; continue
    if c.get("closed"): drop["canal cerrado"] += 1; continue
    if not set(f["languages"]) & {"spa", "eng"}: drop["otro idioma"] += 1; continue
    if c.get("is_nsfw") or set(c["categories"]) & BAD_CATS: drop["religioso / teletienda / adultos (categoría)"] += 1; continue
    if BAD_WORDS.search(c["name"] + " " + " ".join(c.get("alt_names") or [])): drop["religioso / ventas / tarot (nombre)"] += 1; continue
    if c["country"] == "US" and local(f): drop["local de EE. UU."] += 1; continue
    if "news" in c["categories"] and local(f): drop["noticias locales"] += 1; continue
    q = int(re.match(r"\d+", s["quality"]).group()) if s.get("quality") else None
    if q and q > 1080: drop["más de 1080p"] += 1; continue
    if "Geo-blocked" in s["labels"]: drop["con restricción geográfica"] += 1; continue
    if "Not 24/7" in s["labels"]: drop["no emite 24 h"] += 1; continue
    g = [x for x in guides.get(s["channel"], []) if not x.get("feed") or x["feed"] == s["feed"]]
    cand.append(dict(s=s, c=c, f=f, q=q, g=g))

best = {}
for x in cand:  # one stream per channel: main feed, then highest quality up to 1080p
    k = x["s"]["channel"]; r = (x["f"].get("is_main", False), x["q"] or 0)
    if k not in best or r > best[k][0]:
        best[k] = (r, x)
sel = [x for _, x in best.values()]

# guide recovery by name from the epgshare01 files (country file first)
FILE_CC = {"US2": "US", "UK1": "UK", "CA2": "CA", "ES1": "ES", "MX1": "MX", "AR1": "AR", "CL1": "CL", "CO1": "CO",
           "PE1": "PE", "EC1": "EC", "DO1": "DO", "CR1": "CR", "PA1": "PA", "SV1": "SV", "UY1": "UY", "SE1": "SE",
           "DE1": "DE", "NL1": "NL", "PLEX1": "*", "DISTROTV1": "*", "MUSICBOX1": "*"}
idx = collections.defaultdict(list)  # normalized name -> [(file, country, xml channel id)]
for fn, cc in FILE_CC.items():
    try:
        with gzip.open(f"{E}/es_{fn}.xml.gz") as fh:
            for ev, el in ET.iterparse(fh):
                if el.tag == "channel":
                    for dn in el.findall("display-name"):
                        if dn.text and norm(dn.text):
                            idx[norm(dn.text)].append((fn, cc, el.get("id")))
                    el.clear()
                elif el.tag == "programme":
                    el.clear()
    except (OSError, EOFError, ET.ParseError) as e:
        print("skip", fn, e)

recovered = 0
for x in sel:
    x["epg"] = ("iptv-org", x["g"][0]["site"]) if x["g"] else None
    if x["epg"]:
        continue
    names = [x["c"]["name"]] + (x["c"].get("alt_names") or [])
    hits = [h for n in names for h in idx.get(norm(n), [])]
    hits.sort(key=lambda h: (h[1] != x["c"]["country"], h[1] == "*"))
    if hits and (hits[0][1] in (x["c"]["country"], "*") or x["c"]["country"] in ("US", "UK", "CA")):
        x["epg"] = ("epgshare01", f"{hits[0][0]}:{hits[0][2]}"); recovered += 1

FAST = re.compile(r"jmp2\.uk|pluto|plex|roku|samsung|amagi|wurl|stitcher|tubi|xumo|frequency", re.I)
MAJOR_FAST = re.compile(r"^(ABC News Live|NBC News NOW|CBS News 24/7|CBS News$|FOX Weather|Fox News|LiveNOW|Bloomberg|Reuters|Scripps News|NewsNation|Court TV|CNN|AccuWeather|Weather Channel|NFL Channel|MLB|NBA|NHL|PGA|Today All Day|Dateline|PBS)", re.I)
LOCAL_NEWS = re.compile(r"^(CBS|NBC|ABC|FOX) News (?!Live$|NOW|24/7)|^ABC News Live \d|^NBC \w+ News|News 12|Spectrum News|^FOX \d", re.I)
def us_ok(x):
    n = x["c"]["name"]
    if LOCAL_NEWS.search(n): drop["noticias locales (EE. UU.)"] += 1; return False
    if FAST.search(x["s"]["url"]) and not MAJOR_FAST.search(n): drop["EE. UU.: canal temático de streaming gratuito"] += 1; return False
    return True
sel = [x for x in sel if x["c"]["country"] != "US" or us_ok(x)]
final = [x for x in sel if x["epg"] or x["c"]["country"] in KEEP_NO_EPG]
print("dropped:", dict(drop.most_common()))
print("channels after rules:", len(sel), "| guide from iptv-org:", sum(1 for x in sel if x["g"]),
      "| recovered from epgshare01:", recovered)
print("FINAL:", len(final), "| with guide:", sum(1 for x in final if x["epg"]), "| ES/AR without guide:",
      sum(1 for x in final if not x["epg"]))
cc = collections.Counter(x["c"]["country"] for x in final)
pri = ["ES", "AR", "UK", "US"]
print("priority countries:", {k: f'{cc[k]} ({sum(1 for x in final if x["c"]["country"]==k and x["epg"])} con guía)' for k in pri})
print("other countries:", [(k, v) for k, v in cc.most_common() if k not in pri][:20], "... total other:", sum(v for k, v in cc.items() if k not in pri))
print("by category:", collections.Counter((x["c"]["categories"] or ["sin categoría"])[0] for x in final).most_common())
src = collections.Counter(x["epg"][1].split(":")[0] if x["epg"] and x["epg"][0] == "epgshare01" else (x["epg"][1] if x["epg"] else "—") for x in final)
print("guide sources:", src.most_common(15))
print("mjh-dependent:", sum(1 for x in final if x["epg"] and x["epg"][1] == "i.mjh.nz"))
json.dump([dict(id=x["s"]["channel"], name=x["c"]["name"], country=x["c"]["country"], cats=x["c"]["categories"],
                quality=x["q"], url=x["s"]["url"], ua=x["s"].get("user_agent"), ref=x["s"].get("referrer"),
                epg=x["epg"]) for x in final], open(S + "/iptv_final.json", "w", encoding="utf-8"), ensure_ascii=False)
