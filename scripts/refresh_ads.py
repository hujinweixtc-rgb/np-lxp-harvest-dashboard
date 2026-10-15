"""Re-pull the ads table (igad/ads/page/all) and backfill trend+detail for any
material codes that are new since the last snapshot.

Why: the dashboard originally snapshotted the ads table once; ads created after
that (e.g. new launches mid-month) never entered the pipeline, so their spend /
orders were missing from the dashboard and it could not reconcile with the DMS
material page.

Usage:
    python refresh_ads.py            # all combos
    python refresh_ads.py NP-ID      # single combo
"""
from __future__ import annotations

import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dms_api import COMBOS, Dms  # noqa: E402
from fetch_dms import fetch_paged, load, dump  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.environ.get("DASH_RAW_DIR") or os.path.join(ROOT, "raw")
PAGE_ADS = 2000
WORKERS = 12
RANGE = {"start": "2025-06-01", "end": date.today().isoformat()}


def refresh_combo(key, brand, host, brand_id, country, tenant, token, log):
    out_dir = os.path.join(RAW, key)
    client = Dms(host, brand_id, country, tenant, token)

    old_rows = load(os.path.join(out_dir, "ads.json"))
    old_codes = {(a.get("materialCode") or "").strip() for a in old_rows} - {""}
    log(f"  [{key}] old ads={len(old_rows)} old codes={len(old_codes)}")

    ads = fetch_paged(client, "igad/ads/page/all", {"orderBy": "id", "orderType": "asc"},
                      PAGE_ADS, out_dir, "ads_fresh", log)
    new_codes = {(a.get("materialCode") or "").strip() for a in ads} - old_codes - {""}
    log(f"  [{key}] fresh ads={len(ads)} new codes={len(new_codes)}")

    # keep only codes with spend>0 that have no trend file yet
    trend_dir = os.path.join(out_dir, "trend")
    detail_dir = os.path.join(out_dir, "detail")
    os.makedirs(trend_dir, exist_ok=True)
    os.makedirs(detail_dir, exist_ok=True)
    spend_by_new = {}
    for a in ads:
        code = (a.get("materialCode") or "").strip()
        if code in new_codes:
            spend_by_new[code] = spend_by_new.get(code, 0) + (a.get("totalSpend") or 0)
    targets = []
    for code in sorted(new_codes):
        if os.path.exists(os.path.join(trend_dir, code.replace("/", "_") + ".json")):
            continue
        if spend_by_new.get(code, 0) <= 0:
            continue
        targets.append(code)
    log(f"  [{key}] backfilling trend+detail for {len(targets)} new materials ...")

    done = failed = 0

    def work(code):
        nonlocal done, failed
        stem = code.replace("/", "_")
        try:
            t = client.post("igad/advertisement/getAdvertisementTrendByDate",
                            {"materialCode": code, "statisticDate": RANGE}).get("data") or []
            dump(os.path.join(trend_dir, stem + ".json"), t)
            d = client.post("igad/advertisement/getAdvertisementDetials",
                            {"materialCode": code, "statisticDate": RANGE}).get("data") or {}
            dump(os.path.join(detail_dir, stem + ".json"), d)
        except Exception:  # noqa: BLE001
            failed += 1
            return
        done += 1

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = [pool.submit(work, c) for c in targets]
        for idx, fut in enumerate(as_completed(futures), 1):
            fut.result()
            if idx % 50 == 0 or idx == len(targets):
                log(f"  [{key}] {idx}/{len(targets)} (ok={done} failed={failed})")

    # swap in the fresh ads table
    if ads:
        dump(os.path.join(out_dir, "ads.json"), ads)
        dump(os.path.join(out_dir, "ads_fresh.json"), [])  # clear temp
        try:
            os.remove(os.path.join(out_dir, "ads_fresh.json"))
        except OSError:
            pass

    log(f"  [{key}] done: backfilled={done} failed={failed}")
    return {"combo": key, "oldAds": len(old_rows), "newAds": len(ads),
            "newCodes": len(new_codes), "backfilled": done, "failed": failed}


def main():
    only = sys.argv[1:] or None
    results = []
    for combo, brand, host, brand_id, country, tenant, token in COMBOS:
        if only and combo not in only:
            continue
        results.append(refresh_combo(combo, brand, host, brand_id, country, tenant, token,
                                     lambda m: print(m, flush=True)))
    print(json.dumps(results, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
