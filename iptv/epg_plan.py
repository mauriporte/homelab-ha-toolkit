# From the final channel list, build the guide plan:
#  - channels.xml for the iptv-org grabber: ONE source per channel (avoids duplicated programmes),
#    never i.mjh.nz when another source exists (i.mjh.nz is blocked on the ISP)
#  - sources.json for epg-extra: i.mjh.nz feeds fetched from GitHub + epgshare01 country files,
#    each mapping the source's channel id -> the playlist tvg-id
# (one source channel can feed several playlist channels, e.g. HD/SD variants)
# Usage: iptv_epgplan.py <scratch> <ids.json>   (ids.json = list of tvg-ids that made the final list)
import collections, html, json, sys

S, IDS = sys.argv[1], sys.argv[2]
ids = json.load(open(IDS, encoding="utf-8"))
F = {x["id"]: x for x in json.load(open(S + "/iptv_final.json", encoding="utf-8"))}
guides = collections.defaultdict(list)
for g in json.load(open(S + "/iptv_data/guides.json", encoding="utf-8")):
    guides[g["channel"]].append(g)
GH = "https://github.com/matthuisman/i.mjh.nz/raw/refs/heads/master/{}.xml.gz"
ES = "https://epgshare01.online/epgshare01/epg_ripper_{}.xml.gz"

grab, extra, none = [], collections.defaultdict(lambda: collections.defaultdict(list)), []
for i in ids:
    x = F[i]
    gs = guides.get(i, [])
    pick = next((g for g in gs if g["site"] != "i.mjh.nz"), None)
    if pick:
        grab.append((pick, x)); continue
    mjh = next((g for g in gs if g["site"] == "i.mjh.nz"), None)
    if mjh:
        path, cid = mjh["site_id"].split("#", 1)
        extra[GH.format(path)][cid].append(i); continue
    if x.get("epg") and x["epg"][0] == "epgshare01":
        fn, cid = x["epg"][1].split(":", 1)
        extra[ES.format(fn)][cid].append(i); continue
    none.append(i)

lines = ['<?xml version="1.0" encoding="UTF-8"?>', "<channels>"]
for g, x in grab:
    lines.append(f'  <channel site="{g["site"]}" lang="{g["lang"]}" xmltv_id="{x["id"]}" site_id="{html.escape(g["site_id"], quote=True)}">{html.escape(x["name"])}</channel>')
lines.append("</channels>")
open(S + "/iptv_deploy/channels.xml", "w", encoding="utf-8").write("\n".join(lines) + "\n")
json.dump(extra, open(S + "/iptv_deploy/epg-extra/sources.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(f"grabber: {len(grab)} channels from {len({g['site'] for g, _ in grab})} sites | "
      f"extra: {sum(len(t) for v in extra.values() for t in v.values())} channels from {len(extra)} files | no guide: {len(none)}")
assert len(grab) + sum(len(t) for v in extra.values() for t in v.values()) + len(none) == len(ids)
