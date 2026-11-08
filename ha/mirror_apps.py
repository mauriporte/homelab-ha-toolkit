# Copy the app buttons that sync_apps.py keeps on a servers dashboard (one view per server) into another dashboard's
# per-server sections (e.g. a home page with an "Apps" block per server). A target section is matched to the source view
# whose path is the section heading in lower case ("MauThinkCentre" -> view path "mauthinkcentre"). Buttons are matched
# by their switch: kept ones stay as they are, new ones are copied from the source with the target's own show/hide
# input_boolean, buttons gone from the source are dropped, order follows the source. Rows keep the target's width
# (buttons + blank fillers of its first row). Nothing else changes.
# Usage: python mirror_apps.py --from dashboard-red --to dashboard-inicio [--apply]   (without --apply: show changes)
import copy, json, sys


def key(card):
    els = card.get("elements") if card.get("type") == "picture-elements" else None
    return els[0].get("entity") if els else None


def has_menu(pair):
    return any(e.get("type") == "custom:casaos-app-menu" for e in pair[0].get("elements", []))


def app_stack(o):
    """First vertical-stack made of horizontal-stack rows that hold switch buttons."""
    if isinstance(o, dict):
        if o.get("type") == "vertical-stack" and o.get("cards") and all(c.get("type") == "horizontal-stack" for c in o["cards"]) \
                and any((key(t) or "").startswith("switch.") for r in o["cards"] for t in r["cards"]):
            return o
        o = list(o.values())
    if isinstance(o, list):
        for x in o:
            r = app_stack(x)
            if r:
                return r


def group(stack):
    pairs, blank = {}, None
    for row in stack["cards"]:
        for card in row["cards"]:
            k = key(card)
            if k:
                pairs.setdefault(k, []).append(card)
            else:
                blank = card
    return pairs, blank


def mirror(source, target, log=print):
    """Update target (a dashboard config) in place from source; return True when something changed."""
    changed = False
    for view in target["views"]:
        for sec in view.get("sections", []):
            head = next((c.get("heading") for c in sec.get("cards", []) if c.get("type") == "heading"), "") or ""
            stack = app_stack(sec)
            sview = next((v for v in source["views"] if v.get("path") == head.lower()), None)
            if not stack or not sview or not app_stack(sview):
                continue
            have, blank = group(stack)
            src, src_blank = group(app_stack(sview))
            blank = blank or src_blank
            first = stack["cards"][0]["cards"]
            width = len({key(c) for c in first if key(c)}) + sum(1 for c in first if not key(c))
            flag = next((v["entity"] for v in next(iter(have.values()))[0].get("visibility", [])
                         if v["entity"].startswith("input_boolean.")), None) if have else None
            new = []
            for k, pair in src.items():
                if k in have and (has_menu(have[k]) or not has_menu(pair)):
                    new.append(have[k])
                    continue
                pair = copy.deepcopy(pair)
                for card in pair:
                    for v in card.get("visibility", []):
                        if flag and v["entity"].startswith("input_boolean."):
                            v["entity"] = flag
                new.append(pair)
                log(f"{head}: {'~' if k in have else '+'} {k}")
            for k in have:
                if k not in src:
                    log(f"{head}: - {k}")
            rows = []
            for i in range(0, len(new), width):
                chunk = new[i:i + width]
                cards = [c for p in chunk for c in p] + ([copy.deepcopy(blank) for _ in range(width - len(chunk))] if blank else [])
                rows.append({"type": "horizontal-stack", "cards": cards})
            if rows != stack["cards"]:
                stack["cards"] = rows
                changed = True
    return changed


def _selftest():
    def btn(sw, flag, menu=False):
        els = [{"type": "state-icon", "entity": sw}] + ([{"type": "custom:casaos-app-menu"}] if menu else [])
        return [{"type": "picture-elements", "elements": els, "visibility": [{"entity": flag}]}] * 2
    blank = {"type": "markdown", "content": " "}
    src = {"views": [{"path": "srv", "sections": [{"cards": [{"type": "vertical-stack", "cards": [
        {"type": "horizontal-stack", "cards": btn("switch.a", "input_boolean.red", True) + btn("switch.c", "input_boolean.red")}]}]}]}]}
    dst = {"views": [{"sections": [{"cards": [{"type": "heading", "heading": "Srv"}, {"type": "vertical-stack", "cards": [
        {"type": "horizontal-stack", "cards": btn("switch.a", "input_boolean.home") + btn("switch.b", "input_boolean.home") + [blank]}]}]}]}]}
    assert mirror(src, dst, log=lambda *_: None)
    row = dst["views"][0]["sections"][0]["cards"][1]["cards"][0]["cards"]
    assert [key(c) for c in row] == ["switch.a", "switch.a", "switch.c", "switch.c", None]  # b gone, c added, width 3 kept
    assert has_menu([row[0]]) and row[2]["visibility"][0]["entity"] == "input_boolean.home"
    assert not mirror(src, dst, log=lambda *_: None)  # second run: nothing to do


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        _selftest()
        sys.exit(print("ok"))
    from ha_ws import call
    src_path, dst_path = sys.argv[sys.argv.index("--from") + 1], sys.argv[sys.argv.index("--to") + 1]
    source = call(type="lovelace/config", url_path=src_path)["result"]
    target = call(type="lovelace/config", url_path=dst_path)["result"]
    if not mirror(source, target):
        print(dst_path, ": up to date")
    elif "--apply" in sys.argv:
        print("saved:", call(type="lovelace/config/save", url_path=dst_path, config=target)["success"])
    else:
        print("dry run: add --apply to save")
