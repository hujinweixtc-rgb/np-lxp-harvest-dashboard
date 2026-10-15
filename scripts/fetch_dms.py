"""Pull raw NP / LXP DMS (igad) data for the harvest material dashboard.

Raw responses are cached under raw/<combo>/ so build_data.py can be re-run
without hitting the API again.
"""
from __future__ import annotations

import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dms_api import COMBOS, Dms  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.environ.get("DASH_RAW_DIR") or os.path.join(ROOT, "raw")
PAGE_MATERIALS = 500
PAGE_ADS = 2000
TREND_WORKERS = 12
RANGE = {"start": "2025-06-01", "end": "2026-10-12"}


def dump(path, payload):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False)


def load(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def fetch_paged(client, api_path, base_body, page_size, out_dir, tag, log, workers=8):
    out_path = os.path.join(out_dir, f"{tag}.json")
    if os.path.exists(out_path):
        cached = load(out_path)
        log(f"    {tag}: cached rows={len(cached)}")
        return cached
    first = client.post(api_path, {**base_body, "pageSize": page_size, "pageNo": 1})
    total = (first.get("data") or {}).get("total") or 0
    pages = max(1, -(-total // page_size))
    log(f"    {tag}: total={total} pages={pages}")
    results = {1: list((first.get("data") or {}).get("list") or [])}
    if pages > 1:
        def one(page):
            resp = client.post(api_path, {**base_body, "pageSize": page_size, "pageNo": page})
            return page, list((resp.get("data") or {}).get("list") or [])

        done = 1
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for page, rows in pool.map(one, range(2, pages + 1)):
                results[page] = rows
                done += 1
                if done % 5 == 0 or done == pages:
                    log(f"      {tag} page {done}/{pages}")
    rows = []
    for page in sorted(results):
        rows.extend(results[page])
    dump(out_path, rows)
    return rows


def fetch_combo(key, brand, host, brand_id, country, tenant, token, log):
    out_dir = os.path.join(RAW, key)
    meta_path = os.path.join(out_dir, "_meta.json")
    if os.path.exists(meta_path):
        log(f"  [{key}] cached")
        return load(meta_path)

    client = Dms(host, brand_id, country, tenant, token)
    log(f"  [{key}] fetching material library + ads ...")
    materials = fetch_paged(client, "igad/advertisement/allPage",
                            {"orderBy": "id", "orderType": "desc"},
                            PAGE_MATERIALS, out_dir, "materials", log)
    ads = fetch_paged(client, "igad/ads/page/all",
                      {"orderBy": "id", "orderType": "asc"},
                      PAGE_ADS, out_dir, "ads", log)

    log(f"  [{key}] fetching board aggregates ...")
    for tag, api_path in [
        ("board_product", "igad/stat/board/product"),
        ("board_material_type", "igad/stat/board/materialType"),
        ("board_plan_pic", "igad/stat/board/planPic"),
        ("board_daily", "igad/ads/product/board/selectAdDateBoardData"),
        ("board_product_daily", "igad/ads/breakdown/byProductAndDate"),
        ("board_age", "igad/ads/breakdown/byAgeAndDate"),
        ("board_gender", "igad/ads/breakdown/byGenderAndDate"),
        ("board_platform", "igad/ads/breakdown/byPlatformAndDate"),
        ("board_country", "igad/ads/breakdown/byCountry"),
        ("board_position", "igad/ads/breakdown/byPosition"),
    ]:
        try:
            resp = client.post(api_path, {"statisticDate": RANGE})
            dump(os.path.join(out_dir, f"{tag}.json"), resp.get("data"))
        except Exception as exc:  # noqa: BLE001
            log(f"    !! {tag} failed: {exc}")
            dump(os.path.join(out_dir, f"{tag}.json"), None)

    # per-material daily trend + detail.
    # NOTE: igad/ads/page/all is NOT country-scoped (brand-wide, mixes TH/US/MY/...
    # rows), while igad/advertisement/allPage IS country-scoped. Trend/detail APIs
    # are brand-global (same payload regardless of fm-country), so we attribute the
    # market in build_data.py via the materialCode prefix (ID-*/MY-*) plus library
    # membership. Country attribution is also done in build_data.py.
    lib_codes = {(m.get("materialCode") or "").strip() for m in materials} - {""}
    spend_by_code = {}
    last_cost = {}
    for a in ads:
        code = (a.get("materialCode") or "").strip()
        if not code:
            continue
        spend_by_code[code] = spend_by_code.get(code, 0) + (a.get("totalSpend") or 0)
        started = str(a.get("startCostDate") or "")
        if started > last_cost.get(code, ""):
            last_cost[code] = started
    # Only fetch codes that were active in 2026 (plus the whole library) so the
    # historical long tail does not explode the request count.
    targets = sorted(
        c for c, s in spend_by_code.items()
        if s > 0 and (c in lib_codes or last_cost.get(c, "") >= "2026-01-01")
    )
    log(f"  [{key}] per-material trend for {len(targets)} materials "
        f"(library={len(lib_codes)}, ads-pool={len(spend_by_code)}) ...")

    trend_dir = os.path.join(out_dir, "trend")
    detail_dir = os.path.join(out_dir, "detail")
    os.makedirs(trend_dir, exist_ok=True)
    os.makedirs(detail_dir, exist_ok=True)
    done = failed = 0
    done_d = failed_d = 0

    def work(code):
        nonlocal done, failed
        path = os.path.join(trend_dir, code.replace("/", "_") + ".json")
        if os.path.exists(path):
            return
        try:
            resp = client.post("igad/advertisement/getAdvertisementTrendByDate",
                               {"materialCode": code, "statisticDate": RANGE})
            dump(path, resp.get("data") or [])
        except Exception:  # noqa: BLE001
            failed += 1
            return
        done += 1

    def work_detail(code):
        nonlocal done_d, failed_d
        path = os.path.join(detail_dir, code.replace("/", "_") + ".json")
        if os.path.exists(path):
            return
        try:
            resp = client.post("igad/advertisement/getAdvertisementDetials",
                               {"materialCode": code, "statisticDate": RANGE})
            dump(path, resp.get("data") or {})
        except Exception:  # noqa: BLE001
            failed_d += 1
            return
        done_d += 1

    with ThreadPoolExecutor(max_workers=TREND_WORKERS) as pool:
        futures = [pool.submit(work, c) for c in targets]
        total = len(futures)
        for idx, fut in enumerate(as_completed(futures), 1):
            fut.result()
            if idx % 100 == 0:
                log(f"      trend {idx}/{total} (fetched={done} failed={failed})")

    # Detail payloads carry impressions / clicks / orders, but are much heavier
    # than trends, so only fetch them for the library plus materials that
    # actually spent money in the recent window.
    detail_targets = set(lib_codes)
    recent_from = "2026-04-01"
    for code in targets:
        path = os.path.join(trend_dir, code.replace("/", "_") + ".json")
        if not os.path.exists(path):
            continue
        try:
            days = load(path)
        except Exception:  # noqa: BLE001
            continue
        if any(float(x.get("spend") or 0) > 0 and str(x.get("dataDate") or "") >= recent_from
               for x in days):
            detail_targets.add(code)
    detail_targets = sorted(detail_targets)
    log(f"  [{key}] detail for {len(detail_targets)} materials ...")

    with ThreadPoolExecutor(max_workers=TREND_WORKERS) as pool:
        futures = [pool.submit(work_detail, c) for c in detail_targets]
        total_d = len(futures)
        for idx, fut in enumerate(as_completed(futures), 1):
            fut.result()
            if idx % 100 == 0:
                log(f"      detail {idx}/{total_d} (fetched={done_d} failed={failed_d})")

    meta = {
        "key": key, "brand": brand, "country": country, "host": host,
        "materials": len(materials), "ads": len(ads), "trendTargets": len(targets),
        "trendFailed": failed, "fetchedAt": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    dump(meta_path, meta)
    log(f"  [{key}] done: materials={len(materials)} ads={len(ads)} trend={len(targets)} failed={failed}")
    return meta


def main():
    only = sys.argv[1:] or None
    def log(msg):
        print(msg, flush=True)

    summaries = []
    for key, brand, host, brand_id, country, tenant, token in COMBOS:
        if only and key not in only:
            continue
        summaries.append(fetch_combo(key, brand, host, brand_id, country, tenant, token, log))
    log("\n=== summary ===")
    for s in summaries:
        log(json.dumps(s, ensure_ascii=False))


if __name__ == "__main__":
    main()
