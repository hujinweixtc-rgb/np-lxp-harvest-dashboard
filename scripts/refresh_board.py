"""刷新 DMS 大盘聚合数据（igad/stat/board/* + igad/ads/breakdown/*）。

fetch_dms.py 只在首次全量抓取时写 board_*.json（之后因为 _meta.json 已存在而
直接短路返回），所以"大盘"视图的数据会一直停在全量快照那一天。本脚本把同一批
接口单独抽出来做增量刷新。

Usage:
    python refresh_board.py            # 全部 combo
    python refresh_board.py NP-ID      # 单个 combo
"""
from __future__ import annotations

import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dms_api import COMBOS, Dms  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.environ.get("DASH_RAW_DIR") or os.path.join(ROOT, "raw")
RANGE_START = "2025-06-01"

BOARD_APIS = (
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
)


def dump(path, payload):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False)


def refresh_combo(combo, brand, host, brand_id, country, tenant, token, rng, log):
    out_dir = os.path.join(RAW, combo)
    client = Dms(host, brand_id, country, tenant, token)
    ok = failed = 0

    def pull(tag_api):
        tag, api_path = tag_api
        try:
            resp = client.post(api_path, {"statisticDate": rng})
            dump(os.path.join(out_dir, f"{tag}.json"), resp.get("data"))
            return True
        except Exception as exc:  # noqa: BLE001
            log(f"  [{combo}] !! {tag} failed: {exc}")
            return False

    # 单个 combo 的 10 个接口并行拉（同一 token，5 并发足够安全）
    with ThreadPoolExecutor(max_workers=5) as pool:
        for good in pool.map(pull, BOARD_APIS):
            if good:
                ok += 1
            else:
                failed += 1
    log(f"  [{combo}] board done: ok={ok} failed={failed}")
    return {"combo": combo, "ok": ok, "failed": failed}


def main():
    today = time.strftime("%Y-%m-%d")
    rng = {"start": RANGE_START, "end": today}
    only = sys.argv[1:] or None
    combos = [c for c in COMBOS if not only or c[0] in only]
    # 4 个 combo 并行拉取（各自独立 token/接口），整体耗时 = 最慢的那个
    with ThreadPoolExecutor(max_workers=min(4, max(1, len(combos)))) as pool:
        results = list(pool.map(
            lambda c: refresh_combo(*c, rng, lambda m: print(m, flush=True)), combos
        ))
    print(json.dumps(results, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
