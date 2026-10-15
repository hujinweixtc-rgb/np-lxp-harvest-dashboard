"""Pull igad/advertisement/advertisedPage (DMS 素材分析素材页) per combo, in
monthly buckets.

This is the authoritative per-material view the DMS web UI shows: per-material
in-window spend / impressions / clicks / linkClicks / orders, including
materials that are neither in the library nor in the ads table snapshot.

Monthly buckets let build_data.py calibrate each material's daily
impressions / clicks / orders so that ANY window aligned to a month boundary
(e.g. 10-01 ~ 10-13, the default month-to-date view) sums exactly to what the
DMS material page shows. The trend+detail pipeline alone only gives lifetime
totals distributed by spend weight, which under-counts orders whenever a
material's conversion rate changed over time.

Usage: python refresh_adv.py [COMBO ...]
"""
from __future__ import annotations

import calendar
import json
import os
import sys
import time
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dms_api import COMBOS, Dms  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(ROOT, "raw")
PAGE = 500
MONTHS_BACK = 2  # current month + 2 previous months


def adv_buckets(today):
    """桶 = 前两个整月 + 本月1号~昨天 + 今天。
    这样"本月至今不含今天"（DMS 最常用的对账区间，如 10-01~10-13）是一个完整桶，
    看板聚合可精确对上 DMS 素材页。"""
    ranges = []
    y, m = today.year, today.month
    for _ in range(MONTHS_BACK + 1):
        first = date(y, m, 1)
        last = date(y, m, calendar.monthrange(y, m)[1])
        ranges.append({"start": first.isoformat(), "end": min(last, today).isoformat()})
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    ranges = list(reversed(ranges))
    # 把当前月拆成 [1号~昨天] 和 [今天] 两个桶
    cur = ranges[-1]
    yesterday = today - timedelta(days=1)
    if yesterday >= date.fromisoformat(cur["start"]):
        ranges[-1] = {"start": cur["start"], "end": yesterday.isoformat()}
        ranges.append({"start": today.isoformat(), "end": today.isoformat()})
    return ranges


def pull_window(client, rng, log, tag):
    rows = []
    page = 1
    total = None
    while True:
        body = {
            "pageNo": page, "pageSize": PAGE, "orderBy": "id", "orderType": "desc",
            "statisticDate": {
                "conditionType": "BETWEEN", "relationType": "date",
                "relationValue": "19", "value": [rng["start"], rng["end"]],
            },
        }
        resp = client.post("igad/advertisement/advertisedPage", body)
        data = resp.get("data") or {}
        lst = data.get("list") or []
        rows.extend(lst)
        total = int(data.get("total") or 0)
        if page == 1:
            log(f"      {tag}: total={total}")
        if not lst or len(rows) >= total:
            break
        page += 1
        time.sleep(0.3)
    return rows


def pull_combo(key, brand, host, brand_id, country, tenant, token, buckets, log):
    client = Dms(host, brand_id, country, tenant, token)
    out = []
    for rng in buckets:
        tag = f"{rng['start']}~{rng['end']}"
        rows = pull_window(client, rng, log, tag)
        spend = sum(float(r.get("spend") or 0) for r in rows)
        orders = sum(float(r.get("orderCount") or 0) for r in rows)
        log(f"      {tag}: rows={len(rows)} spend={spend:.2f} orders={orders:.0f}")
        out.append({"window": rng, "rows": rows})
    payload = {"fetchedAt": time.strftime("%Y-%m-%d %H:%M:%S"), "buckets": out}
    path = os.path.join(RAW, key, "advertised.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False)
    log(f"  [{key}] saved {sum(len(b['rows']) for b in out)} rows across {len(out)} buckets")
    return {"combo": key, "buckets": [len(b["rows"]) for b in out]}


def backfill_trend(client, codes, trend_dir, detail_dir, rng, log):
    """给 advertised 有、但 trend 缺失或过期的素材补 trend+detail，确保进入看板。"""
    from datetime import date as _date
    need = []
    for code in sorted(codes):
        path = os.path.join(trend_dir, code.replace("/", "_") + ".json")
        if not os.path.exists(path):
            need.append(code)
            continue
        try:
            with open(path, encoding="utf-8") as fh:
                rows = json.load(fh) or []
            mx = max((str(x.get("dataDate") or "") for x in rows), default="")
        except Exception:  # noqa: BLE001
            mx = ""
        if mx < rng["end"]:
            need.append(code)
    targets = need
    if not targets:
        log("      backfill: nothing to do")
        return 0
    log(f"      backfill trend+detail for {len(targets)} materials (missing/stale) ...")
    done = failed = 0

    def work(code):
        stem = code.replace("/", "_")
        try:
            t = client.post("igad/advertisement/getAdvertisementTrendByDate",
                            {"materialCode": code, "statisticDate": rng}).get("data") or []
            os.makedirs(trend_dir, exist_ok=True)
            with open(os.path.join(trend_dir, stem + ".json"), "w", encoding="utf-8") as fh:
                json.dump(t, fh, ensure_ascii=False)
            d = client.post("igad/advertisement/getAdvertisementDetials",
                            {"materialCode": code, "statisticDate": rng}).get("data") or {}
            os.makedirs(detail_dir, exist_ok=True)
            with open(os.path.join(detail_dir, stem + ".json"), "w", encoding="utf-8") as fh:
                json.dump(d, fh, ensure_ascii=False)
        except Exception:  # noqa: BLE001
            return False
        return True

    from concurrent.futures import ThreadPoolExecutor, as_completed
    with ThreadPoolExecutor(max_workers=12) as pool:
        futures = {pool.submit(work, c): c for c in targets}
        for idx, fut in enumerate(as_completed(futures), 1):
            if fut.result():
                done += 1
            else:
                failed += 1
            if idx % 100 == 0 or idx == len(targets):
                log(f"      backfill {idx}/{len(targets)} (ok={done} failed={failed})")
    return done


def main():
    only = sys.argv[1:] or None
    today = date.today()
    buckets = adv_buckets(today)
    print("buckets:", buckets, flush=True)
    results = []
    for combo, brand, host, brand_id, country, tenant, token in COMBOS:
        if only and combo not in only:
            continue
        client = Dms(host, brand_id, country, tenant, token)
        log = lambda m: print(m, flush=True)  # noqa: E731
        out = []
        all_codes = set()
        for rng in buckets:
            tag = f"{rng['start']}~{rng['end']}"
            rows = pull_window(client, rng, lambda m: print(m, flush=True), tag)
            spend = sum(float(r.get("spend") or 0) for r in rows)
            orders = sum(float(r.get("orderCount") or 0) for r in rows)
            log(f"      {tag}: rows={len(rows)} spend={spend:.2f} orders={orders:.0f}")
            out.append({"window": rng, "rows": rows})
            for r in rows:
                c = (r.get("materialCode") or "").strip()
                if c and (float(r.get("spend") or 0) > 0 or float(r.get("orderCount") or 0) > 0):
                    all_codes.add(c)
        payload = {"fetchedAt": time.strftime("%Y-%m-%d %H:%M:%S"), "buckets": out}
        path = os.path.join(RAW, combo, "advertised.json")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False)
        log(f"  [{combo}] saved {sum(len(b['rows']) for b in out)} rows across {len(out)} buckets")
        backfill_trend(client, all_codes,
                       os.path.join(RAW, combo, "trend"), os.path.join(RAW, combo, "detail"),
                       {"start": "2025-06-01", "end": today.isoformat()},
                       lambda m: print(m, flush=True))
        results.append({"combo": combo, "buckets": [len(b["rows"]) for b in out]})
    print(json.dumps(results, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
