#!/usr/bin/env python3
"""拉取 DMS 官方一二三级标签字典（含 category 与 parentId 层级）。

接口：POST admin-api/kol/material/label/listByLevelAndParentId
      body = {"level": 1|2|3, "categories": ["design_igad", "test_direction"]}

用途：素材自带的是「广告名里手写的那几级标签」，名称排版不统一、层级也可能缺。
拿到完整官方字典后，build_data.py 可以按 id 取标准名、按 parentId 回溯补全上级，
并区分两套体系（design_igad=内容 / test_direction=测试方向）。

字典变化很慢，默认 7 天内复用缓存（DASH_LABEL_DICT_TTL_HOURS 可调，0 表示每次都拉）。

用法：python scripts/refresh_labels.py [NP-ID NP-MY ...] [--force]
输出：raw/<combo>/label_dict.json
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dms_api import client_for  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.environ.get("DASH_RAW_DIR") or os.path.join(ROOT, "raw")

CATEGORIES = ["design_igad", "test_direction"]
LEVELS = (1, 2, 3)
ALL_COMBOS = ("NP-ID", "NP-MY", "LXP-ID", "LXP-MY")

try:
    TTL_HOURS = float(os.environ.get("DASH_LABEL_DICT_TTL_HOURS") or 168)
except ValueError:
    TTL_HOURS = 168


def cache_age_hours(path):
    """返回缓存文件的年龄（小时）；无法判定时返回 None（视为过期）。"""
    try:
        with open(path, encoding="utf-8") as fh:
            stamp = (json.load(fh) or {}).get("fetchedAt") or ""
        ts = time.mktime(time.strptime(stamp, "%Y-%m-%d %H:%M:%S"))
    except Exception:  # noqa: BLE001
        return None
    return (time.time() - ts) / 3600.0


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    force = "--force" in sys.argv
    keys = args or list(ALL_COMBOS)
    log = lambda m: print(m, flush=True)
    for key in keys:
        path = os.path.join(RAW, key, "label_dict.json")
        age = cache_age_hours(path)
        if not force and age is not None and age < TTL_HOURS:
            log(f"[{key}] 复用缓存（{age:.1f}h < {TTL_HOURS:.0f}h）")
            continue
        cli = client_for(key)
        rows = []
        ok = True
        for level in LEVELS:
            try:
                res = cli.post("kol/material/label/listByLevelAndParentId",
                               {"level": level, "categories": CATEGORIES})
            except Exception as exc:  # noqa: BLE001
                log(f"[{key}] level {level} 失败: {exc}")
                ok = False
                continue
            data = res.get("data") or []
            log(f"[{key}] level {level}: {len(data)} 个标签")
            rows.extend(data)
        if not ok and not rows:
            log(f"[{key}] 拉取失败，保留原字典")
            continue
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"fetchedAt": time.strftime("%Y-%m-%d %H:%M:%S"), "rows": rows},
                      fh, ensure_ascii=False)
        log(f"[{key}] 写入 {path}（共 {len(rows)} 个标签）")


if __name__ == "__main__":
    main()
