#!/usr/bin/env python
"""用免费视觉模型（智谱 GLM-4.6V-Flash）提取素材快照的图片主题词。

免费模型仍需要一个智谱 API Key（注册 + 实名，模型本身不计费）。
  export ZHIPU_API_KEY=xxxxxxxx
  python scripts/vision_theme.py --limit 300      # 花费 Top300 试跑
  python scripts/vision_theme.py --all            # 全量
  python scripts/vision_theme.py --dry-run        # 不调模型，用素材名规则兜底

产物: data/image_themes.json
  {"version":1,"model":"glm-4.6v-flash","generatedAt":"...","items":{"<key>":{...}}}

增量：已成功的 key 默认跳过；--force 强制重跑。
"""
from __future__ import annotations

import argparse
import base64
import io
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
SRC = DATA / "dms_materials.json"
OUT = DATA / "image_themes.json"

API_BASE = os.environ.get("ZHIPU_BASE_URL", "https://open.bigmodel.cn/api/paas/v4").rstrip("/")
MODEL = os.environ.get("ZHIPU_VISION_MODEL", "glm-4.6v-flash")
KEY_ENVS = ("ZHIPU_API_KEY", "ZHIPUAI_API_KEY", "GLM_API_KEY", "ZAI_API_KEY", "BIGMODEL_API_KEY")

MAX_SIDE = 1024
JPEG_QUALITY = 82

PROMPT = """你是印尼 / 马来西亚 Shopee 电商广告素材分析助手。这是一条 IG 广告素材的封面快照，请提取画面主题。

只输出一个 JSON 对象，不要 Markdown 代码块，不要任何解释文字。字段如下：
{
  "lang": "画面主要文字语言：id / ms / en / zh / none",
  "scene": "画面场景，中文，10 字以内",
  "subject": "画面主体或人物动作，中文，12 字以内",
  "onimage": "画面上出现的主要文案原文，最多 2 条用 | 分隔，照抄不改写，没有就空字符串",
  "themes": [{"src": "源语言主题关键词", "zh": "对应中文"}],
  "style": "视觉风格，中文，8 字以内",
  "hook": "这条素材打的卖点或痛点，中文，20 字以内"
}

要求：
- themes 给 4~6 个，覆盖画面内容、产品功效、使用场景、目标人群、情绪氛围。
- src 用画面文字的原始语言（印尼语 / 马来语）；画面确实没有文字时，用该语言对画面的自然表达。zh 必须是对应的准确中文。
- 只描述画面看得见的内容，不要编造品牌名、价格或销量。
- 严格合法 JSON，字符串内不要出现换行符。"""


def log(msg: str) -> None:
    print(msg, flush=True)


def api_key() -> str:
    for name in KEY_ENVS:
        val = os.environ.get(name, "").strip()
        if val:
            return val
    return ""


def load_source() -> list[dict]:
    if not SRC.exists():
        sys.exit(f"缺少数据源: {SRC}（先跑一次数据刷新）")
    doc = json.loads(SRC.read_text(encoding="utf-8"))
    rows = doc.get("rows") or []
    if not rows:
        sys.exit("dms_materials.json 里没有 rows")
    return rows


def seed_of(row: dict) -> str:
    """稳定的素材标识：优先用数据里的 key，退化为素材编号。"""
    return str(row.get("key") or row.get("materialCode") or row.get("materialId") or "").strip()


def cover_url(row: dict) -> str:
    """视频取 OSS 快照（posterUrl），图片直接取原图。"""
    if row.get("isVideo"):
        for field in ("posterUrl", "previewUrl", "mediaUrl"):
            url = str(row.get(field) or "")
            if not url.startswith("http"):
                continue
            if re.search(r"x-oss-process=[^&]*video/snapshot", url, re.I):
                return url
            if re.search(r"\.(mp4|mov|m3u8)(\?|$)", url, re.I):
                joiner = "&" if "?" in url else "?"
                return f"{url}{joiner}x-oss-process=video/snapshot,t_1200,f_jpg,w_900,m_fast"
            return url
    for field in ("previewUrl", "mediaUrl", "downloadUrl"):
        url = str(row.get(field) or "")
        if url.startswith("http") and not re.search(r"\.(mp4|mov|m3u8)(\?|$)", url, re.I):
            return url
    return ""


def fetch_bytes(url: str, retries: int = 3) -> bytes:
    last: Exception | None = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
                    "Accept": "image/avif,image/webp,image/jpeg,image/*,*/*",
                },
            )
            with urllib.request.urlopen(req, timeout=45) as resp:
                return resp.read()
        except Exception as exc:  # noqa: BLE001
            last = exc
            if attempt < retries - 1:
                time.sleep(1.2 * (attempt + 1))
    raise RuntimeError(f"下载失败: {last}")


def shrink_jpeg(raw: bytes) -> bytes:
    from PIL import Image

    im = Image.open(io.BytesIO(raw))
    if im.mode != "RGB":
        im = im.convert("RGB")
    w, h = im.size
    scale = MAX_SIDE / max(w, h)
    if scale < 1:
        im = im.resize((max(1, round(w * scale)), max(1, round(h * scale))), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=JPEG_QUALITY, optimize=True)
    return buf.getvalue()


def call_vision(key: str, b64: str, retries: int = 4) -> dict:
    payload = {
        "model": MODEL,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": b64}},
                    {"type": "text", "text": PROMPT},
                ],
            }
        ],
        "temperature": 0.2,
        "max_tokens": 700,
        "thinking": {"type": "disabled"},
    }
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    last: Exception | None = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(
                f"{API_BASE}/chat/completions",
                data=body,
                headers={
                    "Authorization": f"Bearer {key}",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=150) as resp:
                return json.loads(resp.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:300]
            last = RuntimeError(f"HTTP {exc.code}: {detail}")
            if exc.code in (429, 500, 502, 503, 504) and attempt < retries - 1:
                time.sleep(2.0 * (2**attempt))
                continue
            raise last
        except Exception as exc:  # noqa: BLE001
            last = exc
            if attempt < retries - 1:
                time.sleep(1.5 * (attempt + 1))
                continue
    raise RuntimeError(f"模型调用失败: {last}")


def parse_json_reply(text: str) -> dict:
    cleaned = (text or "").strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end <= start:
        raise ValueError(f"返回里没有 JSON: {cleaned[:160]}")
    doc = json.loads(cleaned[start : end + 1])
    themes = []
    for item in doc.get("themes") or []:
        if isinstance(item, dict):
            src = str(item.get("src") or "").strip()
            zh = str(item.get("zh") or "").strip()
            if zh:
                themes.append({"src": src, "zh": zh})
        elif isinstance(item, str) and item.strip():
            themes.append({"src": "", "zh": item.strip()})
    doc["themes"] = themes[:8]
    for field in ("lang", "scene", "subject", "onimage", "style", "hook"):
        doc[field] = str(doc.get(field) or "").strip()
    if not doc["themes"]:
        raise ValueError("模型没有返回 themes")
    return doc


CLASS_HINTS = {
    "DAILY": ("日常使用", "pemakaian harian"),
    "PROMO": ("促销", "promo"),
    "SALE": ("折扣", "diskon"),
    "DISCOUNT": ("折扣", "diskon"),
    "TESTI": ("用户证言", "testimoni"),
    "REVIEW": ("测评", "review"),
    "UNBOX": ("开箱", "unboxing"),
    "BEFORE": ("使用前", "sebelum"),
    "AFTER": ("使用后", "sesudah"),
    "TUTORIAL": ("教程", "tutorial"),
    "HOWTO": ("教程", "cara pakai"),
    "NEW": ("上新", "baru"),
    "BUNDLE": ("套装", "bundel"),
    "GIFT": ("赠品", "hadiah"),
}


def dry_themes(row: dict) -> dict:
    """不调模型时的规则兜底：只用素材名分段 + 已有标签拼主题词。"""
    name = str(row.get("materialName") or "")
    tokens = [t for t in re.split(r"[-_.&\s]+", name.upper()) if t and not t.isdigit()]
    themes: list[dict] = []
    for token in tokens:
        for hint, (zh, src) in CLASS_HINTS.items():
            if hint in token:
                themes.append({"src": src, "zh": zh})
                break
    for field in ("tag1", "tag2", "tag3"):
        val = str(row.get(field) or "").strip()
        if val and val not in ("未标注", "-", "None"):
            themes.append({"src": "", "zh": val})
    product = str(row.get("product") or "").strip()
    if product and product not in ("-", "None"):
        themes.append({"src": "", "zh": product})
    dedup, seen = [], set()
    for item in themes:
        if item["zh"] in seen:
            continue
        seen.add(item["zh"])
        dedup.append(item)
    return {
        "lang": "",
        "scene": "",
        "subject": "",
        "onimage": "",
        "themes": dedup[:6],
        "style": "",
        "hook": "",
        "mode": "dry",
    }


def load_cache() -> dict:
    if OUT.exists():
        try:
            doc = json.loads(OUT.read_text(encoding="utf-8"))
            if isinstance(doc.get("items"), dict):
                return doc
        except Exception:  # noqa: BLE001
            pass
    return {"version": 1, "model": MODEL, "generatedAt": "", "items": {}}


def save_cache(doc: dict) -> None:
    doc["generatedAt"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    doc["model"] = MODEL
    tmp = OUT.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(OUT)


def pick_rows(rows: list[dict], args) -> list[dict]:
    picked = []
    for row in rows:
        if args.brand and str(row.get("brand") or "").upper() != args.brand.upper():
            continue
        if args.country and str(row.get("country") or "").upper() != args.country.upper():
            continue
        if not cover_url(row):
            continue
        if not seed_of(row):
            continue
        picked.append(row)
    picked.sort(key=lambda r: -(float(r.get("spend") or 0)))
    if args.all:
        return picked
    return picked[: args.limit]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=300, help="按花费降序取前 N 条（默认 300）")
    ap.add_argument("--all", action="store_true", help="跑全部素材")
    ap.add_argument("--brand", default="", help="只跑某品牌，如 NP / LXP")
    ap.add_argument("--country", default="", help="只跑某国家，如 ID / MY")
    ap.add_argument("--dry-run", action="store_true", help="不调模型，仅用规则兜底")
    ap.add_argument("--force", action="store_true", help="已有结果也重跑")
    ap.add_argument("--sleep", type=float, default=0.4, help="每次请求间隔秒数")
    args = ap.parse_args()

    key = api_key()
    if not args.dry_run and not key:
        log("缺少 API Key。请先执行：export ZHIPU_API_KEY=你的key")
        log("（智谱开放平台 bigmodel.cn 注册 → 实名 → API Keys，GLM-4.6V-Flash 本身免费）")
        log("想先看界面效果可加 --dry-run")
        sys.exit(2)

    rows = load_source()
    targets = pick_rows(rows, args)
    cache = load_cache()
    items = cache["items"]
    total_spend = sum(float(r.get("spend") or 0) for r in rows)
    picked_spend = sum(float(r.get("spend") or 0) for r in targets)
    log(f"素材总数 {len(rows)}，本次目标 {len(targets)} 条"
        f"（覆盖花费 {picked_spend:,.0f} / {total_spend:,.0f}，"
        f"{picked_spend / total_spend * 100 if total_spend else 0:.1f}%）")
    log(f"模式 {'dry-run 规则兜底' if args.dry_run else f'视觉模型 {MODEL}'}")

    ok = skip = fail = 0
    t0 = time.time()
    for idx, row in enumerate(targets, 1):
        seed = seed_of(row)
        cached = items.get(seed)
        if cached and cached.get("status") == "ok" and not args.force and not args.dry_run \
                and cached.get("model") != "dry-run":
            skip += 1
            continue
        if cached and cached.get("mode") == "dry" and args.dry_run and not args.force:
            skip += 1
            continue

        label = f"[{idx}/{len(targets)}] {seed}"
        try:
            if args.dry_run:
                theme = dry_themes(row)
                theme["status"] = "ok"
            else:
                raw = fetch_bytes(cover_url(row))
                jpeg = shrink_jpeg(raw)
                b64 = base64.b64encode(jpeg).decode("ascii")
                reply = call_vision(key, b64)
                choices = reply.get("choices") or []
                content = (choices[0].get("message") or {}).get("content") if choices else ""
                if isinstance(content, list):
                    content = "".join(str(p.get("text", "")) for p in content if isinstance(p, dict))
                theme = parse_json_reply(str(content or ""))
                theme["status"] = "ok"
                theme["imageBytes"] = len(raw)
                theme["sentBytes"] = len(jpeg)
                usage = reply.get("usage") or {}
                theme["usage"] = {
                    "prompt": usage.get("prompt_tokens"),
                    "completion": usage.get("completion_tokens"),
                }
                time.sleep(args.sleep)
            theme["analyzedAt"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            theme["model"] = MODEL if not args.dry_run else "dry-run"
            theme["materialName"] = row.get("materialName", "")
            theme["cover"] = cover_url(row)
            items[seed] = theme
            ok += 1
            log(f"{label} OK  {theme.get('scene', '')} / "
                f"{' '.join(t['zh'] for t in theme.get('themes', [])[:4])}")
        except Exception as exc:  # noqa: BLE001
            fail += 1
            items[seed] = {
                "status": "error",
                "error": str(exc)[:300],
                "analyzedAt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
            log(f"{label} FAIL {exc}")

        if ok and ok % 20 == 0:
            save_cache(cache)

    save_cache(cache)
    elapsed = time.time() - t0
    log("")
    log(f"完成：成功 {ok} / 跳过 {skip} / 失败 {fail}，耗时 {elapsed / 60:.1f} 分钟")
    log(f"结果写入 {OUT.relative_to(ROOT)}（累计 {len(items)} 条）")


if __name__ == "__main__":
    main()
