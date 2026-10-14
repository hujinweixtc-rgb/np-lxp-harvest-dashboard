# -*- coding: utf-8 -*-
"""对账脚本：把看板素材口径的区间合计与 DMS 大盘（board.json）区间合计并列输出。

用途：回答「看板 X~Y 的数据和 DMS 对不上」这类问题，明确差异口径。
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

START = sys.argv[1] if len(sys.argv) > 1 else "2026-10-01"
END = sys.argv[2] if len(sys.argv) > 2 else "2026-10-13"


def daterange_ok(d):
    return START <= d <= END


def load(name):
    with open(DATA / name, encoding="utf-8") as f:
        return json.load(f)


def main():
    mats = load("materials.json")
    board = load("board.json")

    # 素材口径：按 combo 聚合 days
    agg = {}
    for rows in (mats.get("posts") or []):
        combo = "%s-%s" % (rows.get("brand"), rows.get("country"))
        a = agg.setdefault(combo, {"materialCodes": set(), "spend": 0.0, "gmv": 0.0,
                                   "impressions": 0, "clicks": 0, "orders": 0})
        a["materialCodes"].add(rows.get("materialCode"))
        for d, v in (rows.get("days") or {}).items():
            if not daterange_ok(d):
                continue
            a["spend"] += v.get("spend", 0) or 0
            a["gmv"] += v.get("purchaseValue", 0) or 0
            a["impressions"] += v.get("impressions", 0) or 0
            a["allClick"] = a.get("allClick", 0)
            a["clicks"] += v.get("allClick", 0) or 0
            a["orders"] += v.get("conversions", 0) or 0

    # 大盘口径：board.daily
    brd = {}
    for c in (board.get("combos") or []):
        b = {"spend": 0.0, "gmv": 0.0, "impressions": 0, "clicks": 0, "orders": 0}
        for row in (c.get("daily") or []):
            if not daterange_ok(row.get("date", "")):
                continue
            b["spend"] += row.get("spend", 0) or 0
            b["gmv"] += row.get("gmv", 0) or 0
            b["impressions"] += row.get("impressions", 0) or 0
            b["clicks"] += row.get("clicks", 0) or 0
            b["orders"] += row.get("orderCount", 0) or 0
        brd[c.get("key")] = b

    print("=" * 96)
    print("区间对账  %s ~ %s   (素材口径 = SC*/JJ* 排除「帖子」；大盘 = DMS igad 全量)" % (START, END))
    print("=" * 96)
    hdr = "%-8s %12s %12s %14s %14s %12s %10s" % (
        "combo", "素材spend", "大盘spend", "素材/大盘覆盖", "素材GMV", "大盘GMV", "素材数")
    print(hdr)
    print("-" * 96)
    for combo in sorted(set(list(agg.keys()) + list(brd.keys()))):
        a = agg.get(combo, {"spend": 0, "gmv": 0, "materialCodes": set()})
        b = brd.get(combo, {"spend": 0, "gmv": 0})
        cov = (a["spend"] / b["spend"] * 100) if b["spend"] else 0
        print("%-8s %12.2f %12.2f %13.1f%% %14.2f %14.2f %10d" % (
            combo, a["spend"], b["spend"], cov, a["gmv"], b["gmv"], len(a["materialCodes"])))

    print()
    print("提示：素材口径 < 大盘口径 是正常的（大盘含未投素材库的广告、非 SC/JJ 素材、非收割素材）。")


if __name__ == "__main__":
    main()
