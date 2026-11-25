"""Incrementally refresh the material-library whitelist for scoped combos (SKT-MY).

Why this exists
---------------
fetch_dms.py only pulls the material library once: when raw/<combo>/_meta.json
exists it returns the cached library forever. refresh_ads.py and refresh_adv.py
both use that library as a materialCode whitelist for SKT (its full library has
~55k materials, so the dashboard intentionally keeps only recently created ones).
As a result, materials created after the initial snapshot are silently dropped
from the dashboard — SKT-MY was stuck at 2026-11-19 while other brands kept up.

What it does
------------
For every scoped combo it pulls only the recent tail of the library (ordered by
id desc, oldest-created stop condition) and merges it back into
raw/<combo>/materials.json, keyed by materialCode. The 2026-09-01 convergence
guard is applied to every incoming row, so the library never balloons.

Usage:
    python refresh_materials.py            # all scoped combos
    python refresh_materials.py SKT-MY      # one combo
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dms_api import (COMBOS, Dms, MATERIAL_CREATED_FROM, is_scoped_combo,  # noqa: E402
                     keep_scoped_material, material_created_at)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.environ.get("DASH_RAW_DIR") or os.path.join(ROOT, "raw")
PAGE_SIZE = 500
MAX_PAGES = 30  # 30 * 500 = 15000 rows, well past the ~2-3k recent tail


def refresh_materials(key, log):
    out_dir = os.path.join(RAW, key)
    path = os.path.join(out_dir, "materials.json")
    combo = next((c for c in COMBOS if c[0] == key), None)
    if not combo:
        log(f"  [{key}] combo not found, skip")
        return None
    _, brand, host, brand_id, country, tenant, token = combo
    client = Dms(host, brand_id, country, tenant, token)

    old = []
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as fh:
                old = json.load(fh) or []
        except Exception as exc:  # noqa: BLE001
            log(f"  [{key}] 读取现有素材库失败：{exc}")
            old = []
    by_code = {}
    for row in old:
        code = str(row.get("materialCode") or "").strip()
        if code:
            by_code[code] = row
    log(f"  [{key}] 现有素材库 {len(old)} 条 / {len(by_code)} code")

    fresh = []
    for page in range(1, MAX_PAGES + 1):
        try:
            resp = client.post("igad/advertisement/allPage",
                               {"orderBy": "id", "orderType": "desc",
                                "pageSize": PAGE_SIZE, "pageNo": page})
        except Exception as exc:  # noqa: BLE001
            log(f"  [{key}] 第 {page} 页拉取失败：{exc}")
            break
        rows = list((resp.get("data") or {}).get("list") or [])
        if not rows:
            break
        page_max = max((material_created_at(row) for row in rows), default="")
        fresh.extend(rows)
        log(f"  [{key}] page {page}: rows={len(rows)} maxCreated={page_max}")
        # id desc: once a whole page predates the cutoff, later pages are older still.
        if page_max and page_max < MATERIAL_CREATED_FROM:
            break

    if not fresh:
        log(f"  [{key}] 未拉到素材，保留现有缓存不动")
        return {"combo": key, "old": len(old), "new": len(old), "added": 0}

    added = 0
    for row in fresh:
        if not keep_scoped_material(key, row):
            continue
        code = str(row.get("materialCode") or "").strip()
        if not code:
            continue
        if code not in by_code:
            added += 1
        by_code[code] = row  # newer payload replaces stale copy

    merged = list(by_code.values())
    if merged:
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(merged, fh, ensure_ascii=False)
        os.replace(tmp, path)
    log(f"  [{key}] 素材库增量刷新：+{added} 条 -> {len(merged)} 条")
    return {"combo": key, "old": len(old), "new": len(merged), "added": added}


def main():
    only = sys.argv[1:] or None
    results = []
    for combo in COMBOS:
        key = combo[0]
        if not is_scoped_combo(key):
            continue
        if only and key not in only:
            continue
        result = refresh_materials(key, lambda msg: print(msg, flush=True))
        if result:
            results.append(result)
    print(json.dumps(results, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
