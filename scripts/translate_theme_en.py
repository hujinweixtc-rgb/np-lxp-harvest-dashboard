#!/usr/bin/env python
"""给 image_themes.json 里的中文标签生成英文字段 en（带缓存、可断点续传）。

免费模型 glm-4-flash 批量把 sell/copy/themes 的 zh 以及 scene 翻成英文，
结果写入 data/theme_en_cache.json；--apply 时把缓存回写进 image_themes.json
（tag 加 en 字段、item 加 sceneEn），不改动原有 zh/src。

用法:
  export ZHIPU_API_KEY=xxx
  python scripts/translate_theme_en.py --limit 40          # 试跑
  python scripts/translate_theme_en.py --all               # 全量生成缓存
  python scripts/translate_theme_en.py --apply             # 回写 image_themes.json
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
import threading

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(os.environ.get("DASH_DATA_DIR") or (ROOT / "data"))
THEMES = DATA / "image_themes.json"
CACHE = DATA / "theme_en_cache.json"

API_BASE = os.environ.get("ZHIPU_BASE_URL", "https://open.bigmodel.cn/api/paas/v4").rstrip("/")
MODEL = os.environ.get("ZHIPU_TEXT_MODEL", "glm-4-flash")
KEY_ENVS = ("ZHIPU_API_KEY", "ZHIPUAI_API_KEY", "GLM_API_KEY", "ZAI_API_KEY", "BIGMODEL_API_KEY")
FREE_SUFFIXES = ("-flash", "-flashx", "-free")

SYSTEM = """你是电商广告素材标签翻译助手。把每条简体中文短语翻译成简洁、自然的英文（护肤/美妆/日化电商语境）。
要求：
- 保留数字、百分号、型号、品牌名与成分名（如 SPF50 PA++++、Niacinamide、B5）
- 译文控制在 12 个英文单词以内，不要解释、不要加引号
- 严格按输入编号逐条输出，格式为「1. English phrase」，一行一条，不遗漏不多出"""


def log(msg: str) -> None:
    print(msg, flush=True)


def api_key() -> str:
    for name in KEY_ENVS:
        val = os.environ.get(name, "").strip()
        if val:
            return val
    return ""


def has_cn(s: str) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff]", s or ""))


def call_translate(key: str, lines: list[str], retries: int = 6) -> list[str]:
    body = json.dumps({
        "model": MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": "\n".join(f"{i + 1}. {s}" for i, s in enumerate(lines))},
        ],
        "temperature": 0.1,
        "max_tokens": 1800,
        "thinking": {"type": "disabled"},
    }, ensure_ascii=False).encode("utf-8")
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
                raise RuntimeError(f"返回模型 {served} 非免费档，已中止以防计费")
            text = str(((doc.get("choices") or [{}])[0].get("message") or {}).get("content") or "")
            out: dict[int, str] = {}
            for m in re.finditer(r"(?m)^\s*(\d+)\s*[.、)]\s*(.+?)\s*$", text):
                idx = int(m.group(1)) - 1
                val = m.group(2).strip().strip('"“”')
                if 0 <= idx < len(lines) and val and idx not in out:
                    out[idx] = val
            return [out.get(i, "") for i in range(len(lines))]
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:200]
            last = RuntimeError(f"HTTP {exc.code}: {detail}")
            if exc.code == 429 and attempt < retries - 1:
                wait = min(5.0 * (2 ** attempt), 60.0)
                log(f"    限流 429，等待 {wait:.0f}s")
                time.sleep(wait)
                continue
            if exc.code in (500, 502, 503, 504) and attempt < retries - 1:
                time.sleep(2.0 * (attempt + 1))
                continue
            break
        except Exception as exc:  # noqa: BLE001
            last = exc
            if attempt < retries - 1:
                time.sleep(2.0 * (attempt + 1))
                continue
            break
    raise RuntimeError(f"翻译调用失败: {last}")


def collect_phrases(items: dict) -> list[str]:
    """收集所有需要翻译的中文短语（去重、稳定排序）。"""
    phrases: set[str] = set()
    for item in items.values():
        if not isinstance(item, dict):
            continue
        for kind in ("sell", "copy", "themes"):
            for tag in (item.get(kind) or []):
                if not isinstance(tag, dict):
                    continue
                zh = str(tag.get("zh") or "").strip()
                if zh and has_cn(zh):
                    phrases.add(zh)
        for field in ("scene", "subject", "style", "hook"):
            val = str(item.get(field) or "").strip()
            if val and has_cn(val):
                phrases.add(val)
    return sorted(phrases)


def load_cache() -> dict:
    if CACHE.exists():
        try:
            return json.loads(CACHE.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            pass
    return {}


def save_cache(cache: dict) -> None:
    tmp = CACHE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(cache, ensure_ascii=False, indent=0), encoding="utf-8")
    tmp.replace(CACHE)


def generate(key: str, limit: int = 0, batch: int = 50, sleep: float = 0.0, workers: int = 8) -> None:
    doc = json.loads(THEMES.read_text(encoding="utf-8"))
    items = doc.get("items") or {}
    phrases = collect_phrases(items)
    cache = load_cache()
    todo = [p for p in phrases if p not in cache]
    if limit:
        todo = todo[:limit]
    chunks = [todo[i:i + batch] for i in range(0, len(todo), batch)]
    log(f"待翻译短语 {len(todo)} / 总 {len(phrases)}（缓存已有 {len(cache)}），{len(chunks)} 批 × {workers} 并发")
    done = 0
    lock_error: list[str] = []
    cache_lock = threading.Lock()

    def persist(new_pairs: dict) -> None:
        with cache_lock:
            cache.update(new_pairs)
            save_cache(cache)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(call_translate, key, chunk): idx for idx, chunk in enumerate(chunks)}
        for future in as_completed(futures):
            idx = futures[future]
            chunk = chunks[idx]
            try:
                results = future.result()
            except Exception as exc:  # noqa: BLE001
                lock_error.append(f"批 {idx + 1}: {exc}")
                continue
            batch_pairs = {}
            for phrase, en in zip(chunk, results):
                if en:
                    batch_pairs[phrase] = en
                    done += 1
                else:
                    log(f"  未解析: {phrase[:50]}")
            persist(batch_pairs)
            if (idx + 1) % 10 == 0 or idx + 1 == len(chunks):
                log(f"批 {idx + 1}/{len(chunks)} 完成，累计新译 {done}，缓存 {len(cache)}")
            if sleep:
                time.sleep(sleep)
    if lock_error:
        log(f"失败批次 {len(lock_error)}：")
        for msg in lock_error[:10]:
            log(f"  {msg}")
    log(f"生成结束，缓存 {len(cache)} 条 -> {CACHE}")


def apply_cache() -> None:
    doc = json.loads(THEMES.read_text(encoding="utf-8"))
    items = doc.get("items") or {}
    cache = load_cache()
    added = 0
    for item in items.values():
        if not isinstance(item, dict):
            continue
        for kind in ("sell", "copy", "themes"):
            for tag in (item.get(kind) or []):
                if not isinstance(tag, dict):
                    continue
                zh = str(tag.get("zh") or "").strip()
                en = cache.get(zh)
                if en and not tag.get("en"):
                    tag["en"] = en
                    added += 1
        for field in ("scene", "subject", "style", "hook"):
            val = str(item.get(field) or "").strip()
            en = cache.get(val)
            key = field + "En"
            if en and not item.get(key):
                item[key] = en
                added += 1
    doc["generatedAt"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    doc["enVersion"] = 1
    THEMES.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    log(f"回写完成：新增英文字段 {added} 处 -> {THEMES}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true", help="全量生成英文缓存")
    ap.add_argument("--limit", type=int, default=0, help="只处理前 N 条待译短语（试跑）")
    ap.add_argument("--batch", type=int, default=50)
    ap.add_argument("--sleep", type=float, default=0.0)
    ap.add_argument("--workers", type=int, default=8, help="并发数")
    ap.add_argument("--apply", action="store_true", help="把缓存回写进 image_themes.json")
    args = ap.parse_args()
    if args.apply:
        apply_cache()
        return
    key = api_key()
    if not key:
        sys.exit("缺少 API Key：export ZHIPU_API_KEY=xxx")
    if not args.all and not args.limit:
        sys.exit("请指定 --all 或 --limit N")
    generate(key, limit=args.limit, batch=args.batch, sleep=args.sleep, workers=args.workers)


if __name__ == "__main__":
    main()
