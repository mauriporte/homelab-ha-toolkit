# Write the final M3U (working streams only, priority order, grouped) + the EPG grabber channel list + a summary.
import collections, json, re, sys, html
S = sys.argv[1]
F = json.load(open(S + "/iptv_final.json", encoding="utf-8"))
P = {i: st for i, st, t in json.load(open(S + "/iptv_probe.json"))}
logos = dict(re.findall(r'tvg-id="([^"@]+)(?:@[^"]*)?" tvg-logo="([^"]*)"', open(S + "/iptv_data/index.m3u", encoding="utf-8").read()))
guides = collections.defaultdict(list)
for g in json.load(open(S + "/iptv_data/guides.json", encoding="utf-8")):
    guides[g["channel"]].append(g)
CAT = {"general": "General", "movies": "Cine", "series": "Series", "sports": "Deportes", "news": "Noticias",
       "entertainment": "Entretenimiento", "music": "Música", "documentary": "Documentales", "kids": "Infantil",
       "animation": "Infantil", "family": "Infantil", "comedy": "Entretenimiento", "lifestyle": "Estilo de vida",
       "cooking": "Estilo de vida", "travel": "Estilo de vida", "outdoor": "Estilo de vida", "classic": "Cine",
       "education": "Documentales", "science": "Documentales", "culture": "Documentales", "business": "Noticias",
       "weather": "Noticias", "legislative": "Noticias", "auto": "Estilo de vida", "relax": "Estilo de vida"}
ORDER = {"ES": (0, "España"), "AR": (1, "Argentina"), "UK": (2, "Reino Unido"), "US": (3, "EE. UU.")}
ok = [x for x in F if P[x["id"]] == "ok"]
def group(x):
    if x["country"] in ORDER: return ORDER[x["country"]]
    return (4, "Otros · " + CAT.get((x["cats"] or ["general"])[0], "General"))
ok.sort(key=lambda x: (group(x)[0], group(x)[1], x["name"].lower()))
lines = ["#EXTM3U"]
for x in ok:
    attrs = f'tvg-id="{x["id"]}" tvg-name="{html.escape(x["name"])}" tvg-logo="{logos.get(x["id"], "")}" group-title="{group(x)[1]}"'
    lines.append(f"#EXTINF:-1 {attrs},{x['name']}")
    if x.get("ua"): lines.append(f"#EXTVLCOPT:http-user-agent={x['ua']}")
    if x.get("ref"): lines.append(f"#EXTVLCOPT:http-referrer={x['ref']}")
    lines.append(x["url"])
open(S + "/iptv_out/playlist.m3u", "w", encoding="utf-8").write("\n".join(lines) + "\n")
# channel list for the iptv-org EPG grabber (all known guide sources per channel, so it can fall back)
ch = ['<?xml version="1.0" encoding="UTF-8"?>', "<channels>"]
for x in ok:
    for g in guides.get(x["id"], []):
        ch.append(f'  <channel site="{g["site"]}" lang="{g["lang"]}" xmltv_id="{x["id"]}" site_id="{html.escape(g["site_id"])}">{html.escape(x["name"])}</channel>')
ch.append("</channels>")
open(S + "/iptv_out/channels.xml", "w", encoding="utf-8").write("\n".join(ch) + "\n")
json.dump({x["id"]: x["epg"][1] for x in ok if x["epg"] and x["epg"][0] == "epgshare01"},
          open(S + "/iptv_out/epgshare_map.json", "w"), ensure_ascii=False, indent=1)
gc = collections.Counter(group(x)[1] for x in ok)
withg = sum(1 for x in ok if x["epg"])
mjh_only = sum(1 for x in ok if x["epg"] and x["epg"][0] == "iptv-org" and {g["site"] for g in guides[x["id"]]} == {"i.mjh.nz"})
print("M3U channels:", len(ok), "| with guide:", withg, "| without (ES/AR):", len(ok) - withg)
print("guide only via i.mjh.nz (blocked on this line):", mjh_only)
print("groups:", gc.most_common())
print("grabber entries:", len(ch) - 3, "| epgshare-only channels:", sum(1 for x in ok if x["epg"] and x["epg"][0] == "epgshare01"))
