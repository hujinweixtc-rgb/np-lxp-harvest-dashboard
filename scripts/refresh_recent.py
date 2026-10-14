"""Refresh trend + detail payloads for recently-active materials only.

The full fetch (fetch_dms.py) snapshots data once; this script re-pulls the
per-material daily trend and detail (impressions / clicks / orders) for every
code that had spend after RECENT_FROM, so the dashboard reflects the latest
settled days (DMS settles a day's spend on the following day).
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

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(ROOT, "raw")
WORKERS = 12
RECENT_FROM = "2026-09-20"


def dump(path, payload):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False)


def load(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def active_codes(combo):
    tdir = os.path.join(RAW, combo, "trend")
    out = []
    for fn in os.listdir(tdir):
        code = fn[:-5].replace("_", "/")
        try:
            rows = load(os.path.join(tdir, fn))
        except Exception:  # noqa: BLE001
            continue
        if any(float(x.get("spend") or 0) > 0 and str(x.get("dataDate") or "") >= RECENT_FROM
               for x in rows):
            out.append(code)
    return sorted(out)


def refresh_combo(combo, brand, host, brand_id, country, tenant, token, rng, log):
    client = Dms(host, brand_id, country, tenant, token)
    codes = active_codes(combo)
    log(f"[{combo}] refreshing {len(codes)} active materials (range {rng['start']}~{rng['end']})")
    trend_dir = os.path.join(RAW, combo, "trend")
    detail_dir = os.path.join(RAW, combo, "detail")
    done = failed = 0

    def work(code):
        nonlocal done, failed
        stem = code.replace("/", "_")
        try:
            t = client.post("igad/advertisement/getAdvertisementTrendByDate",
                            {"materialCode": code, "statisticDate": rng}).get("data") or []
            dump(os.path.join(trend_dir, stem + ".json"), t)
            d = client.post("igad/advertisement/getAdvertisementDetials",
                            {"materialCode": code, "statisticDate": rng}).get("data") or {}
            dump(os.path.join(detail_dir, stem + ".json"), d)
        except Exception:  # noqa: BLE001
            failed += 1
            return
        done += 1

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = [pool.submit(work, c) for c in codes]
        for idx, fut in enumerate(as_completed(futures), 1):
            fut.result()
            if idx % 100 == 0:
                log(f"  [{combo}] {idx}/{len(codes)} (ok={done} failed={failed})")
    log(f"  [{combo}] done: ok={done} failed={failed}")
    return {"combo": combo, "refreshed": done, "failed": failed}


def main():
    today = date.today().isoformat()
    rng = {"start": "2025-06-01", "end": today}
    only = sys.argv[1:] or None
    results = []
    for combo, brand, host, brand_id, country, tenant, token in COMBOS:
        if only and combo not in only:
            continue
        results.append(refresh_combo(combo, brand, host, brand_id, country, tenant, token, rng,
                                     lambda m: print(m, flush=True)))
    print(json.dumps(results, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
