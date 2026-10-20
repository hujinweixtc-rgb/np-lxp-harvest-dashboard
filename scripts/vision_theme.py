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
# glm-4.6v-flash 质量更好但白天常被挤爆(429)；glm-4v-flash 同为免费档、更稳
MODEL = os.environ.get("ZHIPU_VISION_MODEL", "glm-4v-flash")
# 补译图上文案用的纯文本免费模型
TEXT_MODEL = os.environ.get("ZHIPU_TEXT_MODEL", "glm-4-flash")
KEY_ENVS = ("ZHIPU_API_KEY", "ZHIPUAI_API_KEY", "GLM_API_KEY", "ZAI_API_KEY", "BIGMODEL_API_KEY")

# 防欠费：只允许免费档模型（-flash / -flashx / -free 结尾），付费模型直接拒绝运行
FREE_SUFFIXES = ("-flash", "-flashx", "-free")


def assert_free_model(name: str) -> None:
    if not name.lower().endswith(FREE_SUFFIXES):
        sys.exit(
            f"拒绝运行：模型 {name} 不是免费档（需以 {' / '.join(FREE_SUFFIXES)} 结尾），"
            "可能产生真实费用。请改用 glm-4.6v-flash。"
        )

MAX_SIDE = 1024
JPEG_QUALITY = 82

PROMPT = """你是印尼 / 马来西亚 Shopee 电商广告素材分析助手。这是一条 IG 广告素材的封面快照，请提取卖点和文案主题。

只输出一个 JSON 对象，不要 Markdown 代码块，不要任何解释文字。字段如下：
{
  "lang": "画面主要文字语言：id / ms / en / zh / none",
  "scene": "画面场景，中文，10 字以内",
  "onimage": "画面上出现的主要文案原文，最多 2 条用 | 分隔，照抄不改写，没有就空字符串",
  "onimageZh": "onimage 的简体中文翻译，逐条对应，保留数字与百分比；onimage 为空时留空字符串",
  "sell": [{"src": "源语言卖点词", "zh": "对应中文卖点"}],
  "copy": [{"src": "源语言文案关键词", "zh": "对应中文"}]
}

要求：
- sell 是**卖点标签**，给 3~5 个，必须是功效 / 成分 / 效果 / 数据（如：去黑头、控油祛痘、烟酰胺、弱酸性、六合一、24K金、-90%油光）。
- copy 是**文案主题关键词**，给 2~4 个，是这条广告在讲什么（如：限时折扣、买三更划算、告别油光、男士专属、夏日轻薄、真实测评）。
- 严禁输出：品牌名（NEXT PRIME、Lumi Xpert、Shopee 等）、产品品类名（洗面奶、洁面乳、香皂、精华、洗发水、护肤品、面膜）、包装规格（6pcs、130K、50ribu）、
  以及没有信息量的泛词（护肤、面部护理、产品展示、效果、男士）。这些看图就知道，不需要标签。
- src 用画面文字的原始语言（印尼语 / 马来语）；画面确实没有文字时，用该语言对卖点的自然表达。zh 必须是对应的准确中文。
- 同一个词不要重复出现；文案整句不要直接抄，提炼成 2~6 个字的关键词。
- 整个 JSON 控制在 200 字以内，每个中文词不超过 8 个字，避免超长被截断。
- 严格合法 JSON，字符串内不要出现换行符。"""

TRANSLATE_PROMPT = """你是印尼语 / 马来语 / 英语到简体中文的电商广告翻译。
输入是若干条编号的广告文案（可能用 | 分隔多条），请逐条翻译成自然、口语化的简体中文。
要求：
- **必须输出中文译文，禁止照抄原文**；品牌名/型号可保留原文。
- 保留数字、百分比、折扣信息（如 -90.60%、6pcs、买 3 送 1）。
- 印尼盾价格换算注意：ribu / ribuan = 千，30 ribuan ≈ 3 万印尼盾；juta = 百万。
- 不要加解释、不要扩写，只翻原文意思。
- 只输出 JSON 数组，形如 [{"i":1,"zh":"译文"},{"i":2,"zh":"译文"}]，不要 Markdown 代码块。"""


def _looks_translated(text: str) -> bool:
    return len(re.findall(r"[\u4e00-\u9fff]", text or "")) >= 2


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


def call_vision(key: str, b64: str, retries: int = 7) -> dict:
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
        "max_tokens": 800,
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
                doc = json.loads(resp.read().decode("utf-8", "replace"))
            served = str(doc.get("model") or "")
            # 防欠费：服务端若返回非免费档模型，立刻中止
            if served and not served.lower().endswith(FREE_SUFFIXES):
                raise RuntimeError(f"服务端返回模型 {served} 不是免费档，已中止以防计费")
            return doc
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:300]
            last = RuntimeError(f"HTTP {exc.code}: {detail}")
            # 免费档常见 429（并发/高峰限流）：拉长退避，别把整批跑废
            if exc.code == 429 and attempt < retries - 1:
                wait = min(8.0 * (2**attempt), 90.0)
                log(f"    限流 429，等待 {wait:.0f}s 后重试（第 {attempt + 1}/{retries - 1} 次）")
                time.sleep(wait)
                continue
            if exc.code in (500, 502, 503, 504) and attempt < retries - 1:
                time.sleep(min(3.0 * (attempt + 1), 20))
                continue
            raise last
        except Exception as exc:  # noqa: BLE001
            last = exc
            if attempt < retries - 1:
                time.sleep(1.5 * (attempt + 1))
                continue
    raise RuntimeError(f"模型调用失败: {last}")


def call_text(key: str, user_text: str, retries: int = 6) -> dict:
    """纯文本调用，用于给已分析的图上文案补中文翻译（同样限免费档）。"""
    payload = {
        "model": TEXT_MODEL,
        "messages": [
            {"role": "system", "content": TRANSLATE_PROMPT},
            {"role": "user", "content": user_text},
        ],
        "temperature": 0.1,
        "max_tokens": 1400,
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
            with urllib.request.urlopen(req, timeout=90) as resp:
                doc = json.loads(resp.read().decode("utf-8", "replace"))
            served = str(doc.get("model") or "")
            if served and not served.lower().endswith(FREE_SUFFIXES):
                raise RuntimeError(f"服务端返回模型 {served} 不是免费档，已中止以防计费")
            return doc
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:200]
            last = RuntimeError(f"HTTP {exc.code}: {detail}")
            if exc.code == 429 and attempt < retries - 1:
                wait = min(6.0 * (2**attempt), 60.0)
                log(f"    翻译限流 429，等待 {wait:.0f}s")
                time.sleep(wait)
                continue
            if exc.code in (500, 502, 503, 504) and attempt < retries - 1:
                time.sleep(2.0 * (attempt + 1))
                continue
            raise last
        except Exception as exc:  # noqa: BLE001
            last = exc
            if attempt < retries - 1:
                time.sleep(1.5 * (attempt + 1))
                continue
    raise RuntimeError(f"翻译调用失败: {last}")


def translate_onimage(key: str, sleep: float = 0.4, batch: int = 15) -> None:
    """给缓存里已有 onimage 但缺 onimageZh 的条目批量补中文翻译。"""
    cache = load_cache()
    items = cache["items"]
    todo = [
        (k, v) for k, v in items.items()
        if v.get("status") == "ok" and str(v.get("onimage") or "").strip()
        and not _looks_translated(v.get("onimageZh") or "")
    ]
    log(f"待补译 {len(todo)} 条（文本模型 {TEXT_MODEL}，免费档）")
    if not todo:
        return
    done = fail = 0
    t0 = time.time()
    for start in range(0, len(todo), batch):
        chunk = todo[start : start + batch]
        lines = "\n".join(f"{i}. {v['onimage']}" for i, (_, v) in enumerate(chunk, 1))
        try:
            doc = call_text(key, lines)
            content = doc["choices"][0]["message"]["content"]
            arr = _extract_json_array(content)
            mapping = {}
            for row in arr:
                try:
                    mapping[int(row.get("i"))] = str(row.get("zh") or "").strip()
                except (TypeError, ValueError):
                    continue
            for i, (_, v) in enumerate(chunk, 1):
                zh = mapping.get(i, "")
                if zh:
                    v["onimageZh"] = zh
                    done += 1
        except Exception as exc:  # noqa: BLE001
            fail += len(chunk)
            log(f"  批次 {start // batch + 1} 失败：{exc}")
        save_cache(cache)
        log(f"  进度 {min(start + batch, len(todo))}/{len(todo)}（成功 {done}，失败 {fail}）")
        time.sleep(sleep)
    log(f"补译完成：成功 {done} / 失败 {fail}，耗时 {(time.time() - t0) / 60:.1f} 分钟")


def _extract_json_array(text: str) -> list:
    cleaned = re.sub(r"^```(?:json)?\s*", "", (text or "").strip())
    cleaned = re.sub(r"\s*```$", "", cleaned)
    start, end = cleaned.find("["), cleaned.rfind("]")
    if start == -1 or end <= start:
        raise ValueError(f"返回里没有 JSON 数组: {cleaned[:160]}")
    return json.loads(cleaned[start : end + 1])


def _normalize_pairs(raw) -> list[dict]:
    out = []
    for item in raw or []:
        if isinstance(item, dict):
            src = str(item.get("src") or "").strip()
            zh = str(item.get("zh") or "").strip()
            for piece in _split_tag(zh):
                out.append({"src": src if piece == zh else "", "zh": piece})
        elif isinstance(item, str) and item.strip():
            for piece in _split_tag(item.strip()):
                out.append({"src": "", "zh": piece})
    return out


def _split_tag(text: str) -> list[str]:
    """模型偶尔把多个卖点塞进一个标签（"提亮肤色，深层清洁，控油祛痘"），拆成独立标签。"""
    text = (text or "").strip()
    if not text:
        return []
    parts = [p.strip(" .。") for p in re.split(r"[，,、/|｜]+", text)]
    parts = [p for p in parts if p]
    if len(parts) > 1 and all(len(p) <= 10 for p in parts):
        return parts
    return [text]


# 看图就有的信息不做标签：品牌名、产品品类名、包装规格、没有信息量的泛词
BRAND_NOISE = ("next prime", "lumi xpert", "skintific", "glad2glow", "shopee", "虾皮")
PRODUCT_NOISE = (
    "洗面奶", "洁面", "洗脸", "香皂", "肥皂", "洗发", "护发", "沐浴", "面霜", "面膜",
    "精华", "护肤", "面部护理", "防晒", "卸妆", "磨砂", "凝胶", "喷雾", "身体乳",
    "素颜霜", "产品展示", "产品", "男士护理", "男性护肤",
)
GENERIC_NOISE = ("效果", "男士", "女性", "护肤", "美容", "美妆")
SPEC_RE = re.compile(r"^[\d.,]+\s*(pcs|pc|k|ribu|rb|%|ml|g|件|个|瓶|支|片)?\s*(装|套装|入)?$", re.I)


def _is_noise_tag(tag: dict) -> bool:
    zh = str(tag.get("zh") or "").strip()
    src = str(tag.get("src") or "").strip().lower()
    if not zh:
        return True
    low = zh.lower()
    if any(word in low or word in src for word in BRAND_NOISE):
        return True
    if any(word in low for word in PRODUCT_NOISE):
        return True
    if zh in GENERIC_NOISE:
        return True
    if SPEC_RE.match(low.replace(" ", "")):
        return True
    return False


def _clean_tags(tags: list[dict]) -> list[dict]:
    """去重 + 剔除产品名 / 品牌名 / 规格类噪音标签。"""
    seen, out = set(), []
    for tag in tags:
        zh = str(tag.get("zh") or "").strip()
        if not zh or zh in seen or _is_noise_tag(tag):
            continue
        seen.add(zh)
        out.append(tag)
    return out


def _salvage_truncated(text: str) -> dict:
    """模型输出撞 max_tokens 被截断时，按字段抽取已生成的部分。"""
    doc: dict = {}
    for field in ("lang", "scene", "onimage", "onimageZh"):
        m = re.search(rf'"{field}"\s*:\s*"((?:[^"\\]|\\.)*)"', text)
        if m:
            doc[field] = m.group(1)
    for group in ("sell", "copy", "themes"):
        m = re.search(rf'"{group}"\s*:\s*\[(.*)', text, re.S)
        pairs = []
        for item in re.finditer(
            r'\{\s*"src"\s*:\s*"((?:[^"\\]|\\.)*)"\s*,\s*"zh"\s*:\s*"((?:[^"\\]|\\.)*)"',
            m.group(1) if m else "",
        ):
            pairs.append({"src": item.group(1), "zh": item.group(2)})
        if pairs:
            doc[group] = pairs
    return doc


def parse_json_reply(text: str) -> dict:
    cleaned = (text or "").strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1:
        raise ValueError(f"返回里没有 JSON: {cleaned[:160]}")
    if end <= start:
        # 输出被截断（撞 max_tokens）时做宽松抢救：逐字段正则抽取
        doc = _salvage_truncated(cleaned)
    else:
        try:
            doc = json.loads(cleaned[start : end + 1])
        except json.JSONDecodeError:
            doc = _salvage_truncated(cleaned)
    sell = _clean_tags(_normalize_pairs(doc.get("sell")))
    copy = _clean_tags(_normalize_pairs(doc.get("copy")))
    legacy = _clean_tags(_normalize_pairs(doc.get("themes")))
    if not sell and not copy:
        # 旧格式（只有 themes）兜底：全部当卖点
        sell = legacy
    doc["sell"] = sell[:6]
    doc["copy"] = copy[:4]
    # 兼容旧读取逻辑：themes = 卖点 + 文案
    doc["themes"] = (doc["sell"] + doc["copy"])[:8]
    for field in ("lang", "scene", "subject", "onimage", "onimageZh", "style", "hook"):
        doc[field] = str(doc.get(field) or "").strip()
    if not doc["themes"]:
        raise ValueError("模型没有返回 sell / copy")
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
    ap.add_argument("--translate-onimage", action="store_true", help="只给已有图上文案补中文翻译")
    args = ap.parse_args()

    key = api_key()
    if args.translate_onimage:
        if not key:
            log("缺少 API Key，无法补译")
            sys.exit(2)
        assert_free_model(TEXT_MODEL)
        log(f"文本模型 {TEXT_MODEL}：免费档，补译不产生费用")
        translate_onimage(key, sleep=args.sleep)
        return
    if not args.dry_run and not key:
        log("缺少 API Key。请先执行：export ZHIPU_API_KEY=你的key")
        log("（智谱开放平台 bigmodel.cn 注册 → 实名 → API Keys，GLM-4.6V-Flash 本身免费）")
        log("想先看界面效果可加 --dry-run")
        sys.exit(2)
    if not args.dry_run:
        assert_free_model(MODEL)
        log(f"模型 {MODEL}：免费档，按官方定价不产生费用（仅消耗免费额度）")

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
    tok_in = tok_out = 0
    consec_fail = 0
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
                tok_in += int(usage.get("prompt_tokens") or 0)
                tok_out += int(usage.get("completion_tokens") or 0)
                time.sleep(args.sleep)
            theme["analyzedAt"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            theme["model"] = MODEL if not args.dry_run else "dry-run"
            theme["materialName"] = row.get("materialName", "")
            theme["cover"] = cover_url(row)
            items[seed] = theme
            ok += 1
            consec_fail = 0
            log(f"{label} OK  {theme.get('scene', '')} / "
                f"{' '.join(t['zh'] for t in theme.get('themes', [])[:4])}")
        except Exception as exc:  # noqa: BLE001
            fail += 1
            consec_fail += 1
            items[seed] = {
                "status": "error",
                "error": str(exc)[:300],
                "analyzedAt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
            log(f"{label} FAIL {exc}")
            if consec_fail >= 5:
                log("    连续 5 条失败（免费档高峰限流），暂停 120s 后继续")
                time.sleep(120)
                consec_fail = 0

        if ok and ok % 20 == 0:
            save_cache(cache)

    save_cache(cache)
    elapsed = time.time() - t0
    log("")
    log(f"完成：成功 {ok} / 跳过 {skip} / 失败 {fail}，耗时 {elapsed / 60:.1f} 分钟")
    if tok_in or tok_out:
        log(f"本次 token：输入 {tok_in:,} / 输出 {tok_out:,}（免费档，不计费）")
    log(f"结果写入 {OUT.relative_to(ROOT)}（累计 {len(items)} 条）")


if __name__ == "__main__":
    main()
