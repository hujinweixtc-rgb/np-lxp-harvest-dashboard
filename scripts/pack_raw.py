"""把 DMS 原始缓存打包成 raw.tar.gz，供 Cloud Run 镜像内置。

只打包管线实际读取的文件（见 build_data.py / refresh_adv.py / refresh_ads.py）：
  <combo>/materials.json      素材库
  <combo>/ads.json            广告表
  <combo>/advertised.json     素材分析投放窗口（月度桶）
  <combo>/label_dict.json     DMS 官方一二三级标签字典
  <combo>/trend/*.json        素材每日趋势
  <combo>/detail/*.json       素材区间明细
  <combo>/board_*.json        大盘聚合

排除按窗口保存的历史快照（advertised_2026-*.json）与 _meta.json，控制体积。

Usage:
    python pack_raw.py            # 输出 <root>/raw.tar.gz
    python pack_raw.py out.tar.gz
"""
from __future__ import annotations

import os
import sys
import tarfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.environ.get("DASH_RAW_DIR") or os.path.join(ROOT, "raw")
DEFAULT_OUT = os.path.join(ROOT, "raw.tar.gz")

KEEP_TOP_NAMES = {"materials.json", "ads.json", "advertised.json", "label_dict.json"}
KEEP_TOP_PREFIXES = ("board_",)
SKIP_TOP_PREFIXES = ("advertised_",)  # 按窗口的历史快照，已被 advertised.json 取代
KEEP_DIRS = {"trend", "detail"}


def collect():
    files = []
    for combo in sorted(os.listdir(RAW)):
        combo_dir = os.path.join(RAW, combo)
        if not os.path.isdir(combo_dir):
            continue
        for name in sorted(os.listdir(combo_dir)):
            path = os.path.join(combo_dir, name)
            if os.path.isdir(path):
                if name not in KEEP_DIRS:
                    continue
                for fn in sorted(os.listdir(path)):
                    if fn.endswith(".json"):
                        files.append((os.path.join(combo, name, fn), os.path.join(path, fn)))
                continue
            if not name.endswith(".json"):
                continue
            if name.startswith(SKIP_TOP_PREFIXES):
                continue
            if name in KEEP_TOP_NAMES or name.startswith(KEEP_TOP_PREFIXES):
                files.append((os.path.join(combo, name), path))
    return files


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_OUT
    files = collect()
    total = sum(os.path.getsize(p) for _, p in files)
    print(f"packing {len(files)} files ({total / 1048576:.1f} MB raw) -> {out}", flush=True)

    t0 = time.time()
    with tarfile.open(out, "w:gz", compresslevel=6) as tf:
        for arcname, path in files:
            tf.add(path, arcname=os.path.join("raw", arcname))
    size = os.path.getsize(out)
    print(f"done in {time.time() - t0:.1f}s, archive={size / 1048576:.1f} MB "
          f"(ratio {total / max(size, 1):.1f}x)", flush=True)


if __name__ == "__main__":
    main()
