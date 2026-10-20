#!/usr/bin/env python
"""把 data/image_themes.json 导出成给其他 AI / BI 直接用的底稿数据集。

产出（默认 data/theme_dataset/）：
  themes.jsonl        一行一个素材，含素材元信息 + DMS 标签 + 投放指标 + 卖点/文案标签
  themes.csv          同上，UTF-8 BOM，Excel 可直接打开
  sell_keywords.csv   卖点关键词汇总（素材数 / 花费 / GMV / 订单 / ROI）
  copy_keywords.csv   文案关键词汇总
  README.md           字段说明（数据字典）

用法：
  python scripts/export_themes.py                # 全量导出
  python scripts/export_themes.py --out-dir DIR  # 指定输出目录
"""
from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
THEMES = ROOT / "data" / "image_themes.json"
DMS = ROOT / "data" / "dms_materials.json"
OUT_DEFAULT = ROOT / "data" / "theme_dataset"

FIELDS = [
    "materialCode", "brand", "country", "product", "materialName", "adName",
    "dmsTag1", "dmsTag2", "dmsTag3", "isVideo",
    "spend", "orders", "gmv", "roi",
    "lang", "scene", "onimage", "onimageZh",
    "sellZh", "sellSrc", "copyZh", "copySrc",
    "model", "analyzedAt",
]


def load_json(path: Path, required: bool = True) -> dict:
    if not path.exists():
        if required:
            raise SystemExit(f"缺少文件: {path}")
        print(f"跳过：缺少 {path}")
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def join_tags(tags) -> tuple[str, str]:
    zh = [str(t.get("zh") or "").strip() for t in (tags or []) if str(t.get("zh") or "").strip()]
    src = [str(t.get("src") or "").strip() for t in (tags or []) if str(t.get("src") or "").strip()]
    return " | ".join(zh), " | ".join(src)


def build_rows(themes: dict, dms_rows: list[dict]) -> list[dict]:
    by_code = {}
    for row in dms_rows:
        code = str(row.get("materialCode") or row.get("key") or "").strip()
        if code and code not in by_code:
            by_code[code] = row

    out = []
    for code, item in themes.items():
        if not isinstance(item, dict) or item.get("status") != "ok":
            continue
        row = by_code.get(str(code), {})
        sell_zh, sell_src = join_tags(item.get("sell"))
        copy_zh, copy_src = join_tags(item.get("copy"))
        if not sell_zh and not copy_zh:
            continue
        out.append({
            "materialCode": code,
            "brand": row.get("brand", ""),
            "country": row.get("country", ""),
            "product": row.get("product", ""),
            "materialName": row.get("materialName", ""),
            "adName": row.get("adName", ""),
            "dmsTag1": row.get("tag1", ""),
            "dmsTag2": row.get("tag2", ""),
            "dmsTag3": row.get("tag3", ""),
            "isVideo": "Y" if row.get("isVideo") else "N",
            "spend": round(float(row.get("spend") or 0), 2),
            "orders": int(float(row.get("orders") or 0)),
            "gmv": round(float(row.get("gmv") or 0), 2),
            "roi": round(float(row.get("roi") or 0), 2),
            "lang": item.get("lang", ""),
            "scene": item.get("scene", ""),
            "onimage": item.get("onimage", ""),
            "onimageZh": item.get("onimageZh", ""),
            "sellZh": sell_zh,
            "sellSrc": sell_src,
            "copyZh": copy_zh,
            "copySrc": copy_src,
            "model": item.get("model", ""),
            "analyzedAt": item.get("analyzedAt", ""),
        })
    out.sort(key=lambda r: -r["spend"])
    return out


def keyword_stats(rows: list[dict], field: str) -> list[dict]:
    stats: dict[str, dict] = defaultdict(lambda: {"materials": 0, "spend": 0.0, "orders": 0, "gmv": 0.0})
    for row in rows:
        seen = set()
        for kw in [k.strip() for k in str(row.get(field) or "").split("|")]:
            if not kw or kw in seen:
                continue
            seen.add(kw)
            bucket = stats[kw]
            bucket["materials"] += 1
            bucket["spend"] += float(row.get("spend") or 0)
            bucket["orders"] += int(row.get("orders") or 0)
            bucket["gmv"] += float(row.get("gmv") or 0)
    out = []
    for kw, s in stats.items():
        out.append({
            "keyword": kw,
            "materials": s["materials"],
            "spend": round(s["spend"], 2),
            "orders": s["orders"],
            "gmv": round(s["gmv"], 2),
            "roi": round(s["gmv"] / s["spend"], 2) if s["spend"] else 0,
        })
    out.sort(key=lambda r: (-r["spend"], -r["materials"]))
    return out


def write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


README = """# 素材卖点 / 文案关键词 数据集（AI 分析底稿）

由 `scripts/export_themes.py` 从 `data/image_themes.json` 导出，源数据为视觉模型
（智谱 `glm-4v-flash`，免费档）对 Shopee 广告素材封面快照的读取结果。

## 文件

| 文件 | 说明 |
|---|---|
| `themes.jsonl` | 一行一个素材，机器读取用（JSON Lines，UTF-8） |
| `themes.csv` | 同上，UTF-8 BOM，Excel 可直接打开 |
| `sell_keywords.csv` | 卖点关键词汇总（按花费降序） |
| `copy_keywords.csv` | 文案主题关键词汇总（按花费降序） |

## themes 字段

| 字段 | 含义 |
|---|---|
| `materialCode` | DMS 素材编号（唯一键，可与 `dms_materials.json` / `materials.json` 关联） |
| `brand` / `country` / `product` | 品牌（NP / LXP）、市场（ID / MY）、产品 |
| `materialName` / `adName` | 素材名称、广告名称（原始） |
| `dmsTag1..dmsTag3` | DMS 官方一/二/三级标签 |
| `isVideo` | 是否视频素材（Y/N），主题词来自视频封面帧 |
| `spend` / `orders` / `gmv` / `roi` | 该素材全周期投放指标（USD） |
| `lang` | 画面文字语言：id 印尼语 / ms 马来语 / en 英语 / none |
| `scene` | 画面场景（中文，≤10 字） |
| `onimage` | 画面上出现的文案原文（源语言，最多 2 条，`|` 分隔） |
| `onimageZh` | 上述文案的简体中文翻译 |
| `sellZh` / `sellSrc` | 卖点标签，中文 / 源语言，多条用 ` | ` 分隔 |
| `copyZh` / `copySrc` | 文案主题关键词，中文 / 源语言，同上 |
| `model` / `analyzedAt` | 生成该行的模型与分析时间 |

## keyword 汇总字段

`keyword`、`materials`（涉及素材数）、`spend`（花费合计）、`orders`、`gmv`、
`roi`（GMV / 花费）。同一素材内重复关键词只计一次。

## 注意

- 主题词由视觉模型读图生成，**仅供创意分析参考**，不是 DMS 官方口径。
- 未分析的素材不在本数据集中；覆盖率见 `data/image_themes.json` 的条目数。
- 指标是素材全周期值；按日期窗口的口径请用 `data/materials.json` 的逐日 `days`。
"""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", default=str(OUT_DEFAULT))
    args = ap.parse_args()

    themes_doc = load_json(THEMES, required=False)
    if not themes_doc:
        return
    themes = themes_doc.get("items") or {}
    dms_doc = load_json(DMS)
    dms_rows = dms_doc.get("rows") or dms_doc.get("materials") or []

    rows = build_rows(themes, dms_rows)
    if not rows:
        print("跳过：还没有可导出的主题词数据")
        return

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)

    (out / "themes.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8"
    )
    write_csv(out / "themes.csv", rows, FIELDS)

    sell = keyword_stats(rows, "sellZh")
    copy = keyword_stats(rows, "copyZh")
    kw_fields = ["keyword", "materials", "spend", "orders", "gmv", "roi"]
    write_csv(out / "sell_keywords.csv", sell, kw_fields)
    write_csv(out / "copy_keywords.csv", copy, kw_fields)
    (out / "README.md").write_text(README, encoding="utf-8")

    analysed = len(rows)
    total = len(dms_rows)
    print(f"导出完成：{analysed} 条已分析素材（覆盖 {analysed / total * 100:.1f}%），"
          f"卖点词 {len(sell)} 个 / 文案词 {len(copy)} 个")
    print(f"输出目录：{out}")


if __name__ == "__main__":
    main()
