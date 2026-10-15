"""Build dashboard JSON payloads from raw DMS responses.

Outputs:
  data/materials.json      -> main dashboard payload (template-compatible posts[])
  data/dms_materials.json  -> DMS material library payload (media previews)
"""
from __future__ import annotations

import json
import os
import re
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(ROOT, "raw")
DATA = os.path.join(ROOT, "data")

COMBO_KEYS = ["NP-ID", "NP-MY", "LXP-ID", "LXP-MY"]
MATERIAL_TYPE = {1: "图文", 2: "视频", 3: "视频"}
SOURCE_TYPE = {
    1: "剪辑系统",
    2: "设计素材",
    3: "KOL内容",
    4: "KOL内容",
    5: "UGC",
}

import time  # noqa: E402


def load(path, default=None):
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def label_names(labels):
    if not labels:
        return []
    return [str(item.get("name") or "").strip() for item in labels if item.get("name")]


def pick_tag(names, fallback="未标注"):
    clean = [n for n in names if n]
    return clean[0] if clean else fallback


# ---- 收割三大类（与 FR 模板一致：awa / consi / conv）-----------------------
# DMS 一级标签是完整内容分类学（功效 / 对比 / 场景 / KOL种草 / AWA / ...），
# 这里按关键词归一到三大类；未命中的素材不进收割分布（tag1 = 未标注）。
HARVEST_TAG_RULES = (
    ("awa", ("awa",)),
    ("consi", ("consi", "种草")),
    ("conv", ("conv", "转化")),
)


def canonical_harvest_tag(names):
    for key, needles in HARVEST_TAG_RULES:
        for name in names:
            low = str(name or "").lower()
            if any(needle in low for needle in needles):
                return key
    return ""


def media_urls(row):
    """Return (previewUrl, downloadUrl, posterUrl, isVideo)."""
    files = row.get("ossFiles") or []
    if not files:
        return "", "", "", False
    first = files[0]
    origin = str(first.get("originName") or "").lower()
    is_video = origin.endswith((".mp4", ".mov", ".m4v")) or (first.get("mimeType") or "").startswith("video")
    full = first.get("fullUrlWithHttps") or ""
    if not full:
        raw = first.get("fullUrl") or ""
        full = ("https:" + raw) if raw.startswith("//") else raw
    poster = ""
    if is_video and full and "aliyuncs.com" in full:
        poster = f"{full}{'&' if '?' in full else '?'}x-oss-process=video/snapshot,t_1000,f_jpg,w_800,m_fast"
    elif not is_video:
        poster = full
    return poster, full, poster, is_video


ACCOUNT_COUNTRY_RE = re.compile(r"[-_](ID|MY|TH|TW|VN|PH|SG|US)[-_]", re.I)
CODE_PREFIX_RE = re.compile(r"^([A-Za-z]{2})-")
PRODUCT_SUFFIX_RE = re.compile(r"-[A-Za-z]{2}$")
CJK_RE = re.compile(r"[\u4e00-\u9fff]")

# ---- 看板收录口径 ----------------------------------------------------------
# 1) 只统计正式素材编号：SC* / JJ*（KOL 帖子类 ID-* / MY-* 编码不计入）
# 2) 广告名含「帖子」的投放行不计入
MATERIAL_CODE_PREFIXES = ("SC", "JJ")
EXCLUDED_AD_NAME_KEYWORDS = ("帖子",)


def keep_material_code(code):
    return str(code or "").strip().startswith(MATERIAL_CODE_PREFIXES)


def excluded_by_ad_name(*names):
    text = "".join(str(n or "") for n in names)
    return any(k in text for k in EXCLUDED_AD_NAME_KEYWORDS)


def product_from_ad(ad):
    """广告行 / 广告名兜底解析产品名（DMS 广告命名约定：产品_类型_品牌_...）。"""
    if not ad:
        return ""
    for key in ("productItemNames", "materialProductItemNames"):
        value = ad.get(key)
        if isinstance(value, str) and value.strip():
            return PRODUCT_SUFFIX_RE.sub("", value.strip())
        if isinstance(value, list) and value:
            return PRODUCT_SUFFIX_RE.sub("", str(value[0]).strip())
    head = str(ad.get("adName") or "").split("_")[0].strip()
    if head and CJK_RE.search(head):
        return head
    return ""


def ad_matches_country(ad, country):
    hit = ACCOUNT_COUNTRY_RE.search(ad.get("adAccountName") or "")
    return bool(hit) and hit.group(1).upper() == country.upper()


def apportion_int(total, weights):
    """把整数总量按权重摊到若干天；用最大余数法保证取整后总和精确等于 round(total)。"""
    n = len(weights)
    if n == 0:
        return []
    target = int(round(float(total)))
    raw = [float(total) * w for w in weights]
    out = [int(v) for v in raw]
    diff = target - sum(out)
    if diff > 0:
        order = sorted(range(n), key=lambda i: -(raw[i] - out[i]))
        for i in order[:diff]:
            out[i] += 1
    elif diff < 0:
        order = sorted(range(n), key=lambda i: (raw[i] - out[i]))
        for i in order[:(-diff)]:
            if out[i] > 0:
                out[i] -= 1
    return out


def collect(combo):
    brand, country = combo.split("-")
    base = os.path.join(RAW, combo)
    materials = load(os.path.join(base, "materials.json"), []) or []
    ads = load(os.path.join(base, "ads.json"), []) or []

    # igad/ads/page/all is a cross-country pool -> keep only rows whose ad account
    # belongs to this market, falling back to everything when nothing matches.
    ads_by_code = defaultdict(list)
    for ad in ads:
        code = (ad.get("materialCode") or "").strip()
        if code:
            ads_by_code[code].append(ad)
    for code, items in list(ads_by_code.items()):
        scoped = [a for a in items if ad_matches_country(a, country)]
        ads_by_code[code] = scoped or items

    material_by_code = {}
    for m in materials:
        code = (m.get("materialCode") or "").strip()
        if code and code not in material_by_code:
            material_by_code[code] = m

    # DMS 素材分析素材页（igad/advertisement/advertisedPage）——素材窗口指标的权威来源。
    # 按月分桶抓取：每个素材在当月窗口内的精确 spend / impressions / clicks /
    # linkClicks / orders，用于校准 trend+detail 管线"按花费摊比例"造成的窗口误差
    # （订单不随花费等比）。凡与月界对齐的查询区间（如 10-01~10-13）可精确对上 DMS。
    adv_buckets = []  # [(start, end, {code: row}), ...] 按时间升序
    adv_payload = load(os.path.join(base, "advertised.json"), None) or {}
    if isinstance(adv_payload, dict) and adv_payload.get("buckets"):
        for b in adv_payload["buckets"]:
            ws = str((b.get("window") or {}).get("start") or "")
            we = str((b.get("window") or {}).get("end") or "")
            by_code = {}
            for r in b.get("rows") or []:
                c = (r.get("materialCode") or "").strip()
                if c:
                    by_code[c] = r
            if ws and we:
                adv_buckets.append((ws, we, by_code))
        adv_buckets.sort(key=lambda x: x[0])

    trend_dir = os.path.join(base, "trend")
    detail_dir = os.path.join(base, "detail")
    posts = []
    dms_rows = []

    def build_days(code):
        """趋势接口只给 spend/gmv；曝光 / 点击 / 订单来自 getAdvertisementDetials 的区间总量，
        按当日花费占比摊到每一天。素材在 advertisedPage 月度桶内的天数用桶精确总量校准，
        完全落在桶外的天数用（终身总量 - 各桶总量）摊比例。"""
        raw_days = load(os.path.join(trend_dir, code.replace("/", "_") + ".json"), []) or []
        detail = load(os.path.join(detail_dir, code.replace("/", "_") + ".json"), None) or {}
        rows = detail.get("stats") or []
        totals = {}
        for key in ("impressions", "clicks", "orderCount", "cartGmv", "reach",
                    "videoPlayActions", "videoP100WatchedActions"):
            totals[key] = sum(float(r.get(key) or 0) for r in rows)

        days = {}
        for item in raw_days:
            day = item.get("dataDate")
            if not day:
                continue
            spend = float(item.get("spend") or 0)
            gmv = float(item.get("gmv") or 0)
            if spend <= 0 and gmv <= 0:
                continue
            days[day] = {"spend": round(spend, 4), "purchaseValue": round(gmv, 4)}
        if not days:
            return days, totals

        total_spend = sum(v["spend"] for v in days.values())
        if total_spend > 0:
            weights = {d: v["spend"] / total_spend for d, v in days.items()}
        else:
            first = sorted(days)[0]
            weights = {d: (1.0 if d == first else 0.0) for d in days}
        for day, values in days.items():
            w = weights[day]
            values["impressions"] = int(round(totals.get("impressions", 0) * w))
            values["allClick"] = int(round(totals.get("clicks", 0) * w))
            values["linkClick"] = int(round(totals.get("clicks", 0) * w))
            values["conversions"] = int(round(totals.get("orderCount", 0) * w))
            if totals.get("cartGmv"):
                values["addToCart"] = round(totals["cartGmv"] * w, 4)

        # --- advertisedPage 月度桶校准：桶内各天的指标总和 = DMS 素材页精确值 ---
        calibrated = set()
        bucket_totals = {"impressions": 0.0, "allClick": 0.0, "conversions": 0.0}
        adv_linkclick = 0.0
        for ws, we, by_code in adv_buckets:
            adv_row = by_code.get(code)
            if not adv_row:
                continue
            in_days = [d for d in days if ws <= d <= we and d not in calibrated]
            if not in_days:
                continue
            win_spend = sum(days[d]["spend"] for d in in_days)
            weights = ([days[d]["spend"] / win_spend for d in in_days] if win_spend > 0
                       else [1.0 / len(in_days)] * len(in_days))
            for local_key, adv_key in (("impressions", "impressions"),
                                       ("allClick", "clicks"),
                                       ("conversions", "orderCount")):
                adv_total = float(adv_row.get(adv_key) or 0)
                alloc = apportion_int(adv_total, weights)
                for d, value in zip(in_days, alloc):
                    days[d][local_key] = value
                bucket_totals[local_key] += int(round(adv_total))
            adv_link = float(adv_row.get("linkClicks") or 0)
            alloc_link = apportion_int(adv_link, weights)
            for d, value in zip(in_days, alloc_link):
                days[d]["linkClick"] = value
            adv_linkclick += int(round(adv_link))
            calibrated.update(in_days)

        # 桶外天数：用（终身总量 - 各桶总量）重新摊比例，避免双重计数
        if calibrated:
            out_days = [d for d in days if d not in calibrated]
            out_spend = sum(days[d]["spend"] for d in out_days)
            if out_days:
                out_weights = ([days[d]["spend"] / out_spend for d in out_days] if out_spend > 0
                               else [1.0 / len(out_days)] * len(out_days))
            else:
                out_weights = []
            for local_key, life_key in (("impressions", "impressions"),
                                        ("allClick", "clicks"),
                                        ("conversions", "orderCount")):
                residual = max(float(totals.get(life_key, 0) or 0) - bucket_totals[local_key], 0.0)
                alloc = apportion_int(residual, out_weights) if out_days else []
                for d, value in zip(out_days, alloc):
                    days[d][local_key] = value
            if out_days:
                life_clicks = float(totals.get("clicks", 0) or 0)
                ratio = (adv_linkclick / bucket_totals["allClick"]) if bucket_totals["allClick"] else 0.0
                residual_link = max(life_clicks - bucket_totals["allClick"], 0.0) * ratio
                for d, value in zip(out_days, apportion_int(residual_link, out_weights)):
                    days[d]["linkClick"] = value
        return days, totals

    adv_codes = set()
    for _, _, rc in adv_buckets:
        adv_codes.update(rc.keys())

    # 素材级口径：趋势接口里有花费的全部素材（含未入库的 KOL / 剪辑系统素材）。
    # 市场归属 = materialCode 前缀（ID-*/MY-*）；无前缀编码必须能在本国素材库或
    # 本国 advertisedPage（按国家隔离）中找到。
    code_spend = {}
    for fn in os.listdir(trend_dir):
        code = fn[:-5].replace("_", "/")
        try:
            rows = load(os.path.join(trend_dir, fn)) or []
        except Exception:  # noqa: BLE001
            continue
        s = sum(float(x.get("spend") or 0) for x in rows)
        g = sum(float(x.get("gmv") or 0) for x in rows)
        if s > 0 or g > 0:
            code_spend[code] = (s, g)

    def owns_market(code):
        """SC / JJ 素材按素材库或 advertisedPage 归属；带国家前缀的编码按前缀归属。"""
        if code in material_by_code or code in adv_codes:
            return True
        m = CODE_PREFIX_RE.match(code)
        if m:
            return m.group(1).lower() == country.lower()
        return False

    all_codes = {c for c in code_spend if keep_material_code(c) and owns_market(c)}
    for code in material_by_code:
        if not keep_material_code(code) or code in code_spend:
            continue
        detail = load(os.path.join(detail_dir, code.replace("/", "_") + ".json"), None) or {}
        if float(detail.get("spend") or 0) > 0 or float(detail.get("roi") or 0) > 0:
            all_codes.add(code)

    for code in sorted(all_codes):
        meta = material_by_code.get(code) or {}
        ad_list = ads_by_code.get(code) or []
        detail = load(os.path.join(detail_dir, code.replace("/", "_") + ".json"), None) or {}
        if not meta:
            det_rows0 = detail.get("stats") or []
            d0 = det_rows0[0] if det_rows0 else {}
            meta = {
                "materialName": detail.get("materialName") or code,
                "productItemNames": detail.get("productItemNames") or "",
                "adProductNames": "",
                "materialType": None,
                "dataFromType": d0.get("dataFromType"),
                "ossFiles": d0.get("ossFiles") or [],
                "networkDiskLink": d0.get("networkDiskLink") or "",
                "createdAt": str(d0.get("startCostDate") or "")[:10],
            }
        days, metric_totals = build_days(code)
        adv_row = next((rc.get(code) for _, _, rc in adv_buckets if code in rc), {}) or {}
        spend = round(sum(v["spend"] for v in days.values()), 4)
        gmv = round(sum(v["purchaseValue"] for v in days.values()), 4)
        if spend <= 0 and gmv <= 0:
            ad_spend = sum(float(a.get("totalSpend") or 0) for a in ad_list)
            ad_gmv = sum(float(a.get("totalGmv") or 0) for a in ad_list)
            if ad_spend <= 0 and ad_gmv <= 0:
                continue
            spend, gmv = round(ad_spend, 4), round(ad_gmv, 4)

        mtype = meta.get("materialType")
        preview, download, poster, is_video = media_urls(meta)
        # 类型 3 实际也是视频文件；以 OSS 文件为准，避免误判
        type_label = "视频" if is_video else MATERIAL_TYPE.get(mtype) or "图文"

        tag1_names = label_names(meta.get("firstLevelLabels"))
        tag2_names = label_names(meta.get("secondLevelLabels"))
        tag3_names = label_names(meta.get("thirdLevelLabels"))
        all_tags = tag1_names + tag2_names + tag3_names

        product_raw = (meta.get("productItemNames") or "").strip()
        product = (meta.get("adProductNames") or product_raw or "未标注").strip()
        # KOL / 剪辑系统素材的产品名常带国家后缀（如 黑色美白洁面皂-ID）-> 归一组去掉
        product = PRODUCT_SUFFIX_RE.sub("", product) or "未标注"
        if product == "未标注":
            for ad in ad_list:
                hit = product_from_ad(ad)
                if hit:
                    product = hit
                    break
        created_at = str(meta.get("createdAt") or meta.get("uploadTime") or "")[:10]
        primary_ad = ad_list[0] if ad_list else {}
        dates = sorted(days.keys())

        det_rows = detail.get("stats") or []
        det_first = det_rows[0] if det_rows else {}

        # 口径 2：广告名含「帖子」的投放行不计入
        ad_name = (meta.get("adName") or det_first.get("adName")
                   or primary_ad.get("adName") or "")
        if excluded_by_ad_name(ad_name):
            continue

        # 汇总口径与 days 一致（advertisedPage 校准后的窗口精确值 + 窗口外摊比例）
        impressions = int(sum(float(v.get("impressions") or 0) for v in days.values()))
        clicks = int(sum(float(v.get("allClick") or 0) for v in days.values()))
        link_clicks = int(sum(float(v.get("linkClick") or 0) for v in days.values()))
        conversions = int(sum(float(v.get("conversions") or 0) for v in days.values()))
        video_plays = int(sum(float(r.get("videoPlayActions") or 0) for r in det_rows))

        dft = adv_row.get("dataFromType") if adv_row else None
        dft = meta.get("dataFromType") if dft in (None, "") else dft
        try:
            dft_int = int(dft) if dft not in (None, "") else None
        except (TypeError, ValueError):
            dft_int = None

        post = {
            "key": f"{brand}|{country}|{code}",
            "materialCode": code,
            "materialName": meta.get("materialName") or "",
            "adName": meta.get("adName") or det_first.get("adName") or primary_ad.get("adName") or "",
            "brand": brand,
            "country": country,
            "product": product or "未标注",
            "productRaw": product_raw or product,
            "materialType": type_label,
            "graphicType": SOURCE_TYPE.get(dft_int, SOURCE_TYPE.get(meta.get("dataFromType"), "未标注")),
            "dataFromType": str(dft_int) if dft_int is not None else "",
            "tag1": canonical_harvest_tag(tag1_names) or "未标注",
            "tag2": pick_tag(tag2_names),
            "tag3": pick_tag(tag3_names),
            "tagsAll": " / ".join(all_tags),
            "tag1List": tag1_names,
            "tag2List": tag2_names,
            "tag3List": tag3_names,
            "materialCreatedAt": created_at,
            "firstDate": dates[0] if dates else "",
            "lastDate": dates[-1] if dates else "",
            "designerName": meta.get("designerName") or "",
            "planPicName": meta.get("planPicName") or "",
            "advertiser": det_first.get("advertiserName") or primary_ad.get("advertiserName") or "",
            "accountName": det_first.get("accountName") or primary_ad.get("adAccountName") or "",
            "campaignName": det_first.get("campaignName") or primary_ad.get("campaignName") or "",
            "adSetName": det_first.get("adSetName") or primary_ad.get("adSetName") or "",
            "adStatus": det_first.get("adStatus") or primary_ad.get("status") or "",
            "deliveryPlatform": det_first.get("deliveryPlatform") or "",
            "startCostDate": str(det_first.get("startCostDate") or primary_ad.get("startCostDate") or "")[:10],
            "sourceAdCount": max(len(ad_list), len(det_rows)),
            "mediaUrl": download,
            "previewUrl": preview,
            "posterUrl": poster,
            "isVideo": is_video,
            "networkDiskLink": meta.get("networkDiskLink") or "",
            "spend": spend,
            "purchaseValue": gmv,
            "impressions": impressions,
            "allClick": clicks,
            "linkClick": link_clicks,
            "conversions": conversions,
            "addToCart": 0,
            "videoPlays": video_plays,
            "days": days,
        }
        posts.append(post)

        if spend > 0 or gmv > 0:
            dms_rows.append({
                "key": code,
                "materialCode": code,
                "materialId": code,
                "materialName": meta.get("materialName") or "",
                "adName": post["adName"],
                "brand": brand,
                "country": country,
                "product": post["product"],
                "materialType": type_label,
                "graphicType": post["graphicType"],
                "dataFromType": post.get("dataFromType", ""),
                "tag1": post["tag1"],
                "tag2": post["tag2"],
                "tag3": post["tag3"],
                "spend": spend,
                "orders": conversions,
                "gmv": gmv,
                "impressions": impressions,
                "clicks": clicks,
                "roi": round(gmv / spend, 4) if spend else 0,
                "createdAt": created_at,
                "uploadTime": str(meta.get("uploadTime") or "")[:10],
                "designerName": post["designerName"],
                "planPicName": post["planPicName"],
                "advertiser": post["advertiser"],
                "campaignName": post["campaignName"],
                "adSetName": post["adSetName"],
                "adStatus": post["adStatus"],
                "matchedDms": True,
                "downloadReady": bool(download),
                "hasMedia": bool(download),
                "isVideo": is_video,
                "mediaUrl": download,
                "previewUrl": preview,
                "posterUrl": poster,
                "downloadUrl": download,
                "networkDiskLink": post["networkDiskLink"],
                "videoScale": meta.get("videoScale") or "",
                "paidMonth": (dates[0][:7] if dates else ""),
            })

    return posts, dms_rows


COUNTRY_LABEL = {"id": "印尼", "my": "马来"}
BRAND_LABEL = {"NP": "NP", "LXP": "LXP"}
DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# DMS board payloads use different key names across endpoints -> normalize.
FIELD_ALIASES = {
    "date": ("dataDate", "date", "statDate", "statisticDate", "dataDateStr", "category"),
    "spend": ("spend", "totalSpend", "cost", "costAmount"),
    "gmv": ("gmv", "totalGmv", "orderGmv", "purchaseValue", "payGmv"),
    "roi": ("roi", "totalRoi"),
    "impressions": ("impressions", "showCount", "exposureCount", "impressionCount"),
    "clicks": ("clicks", "clickCount", "allClick", "allClickCount"),
    "linkClicks": ("linkClicks", "linkClickCount", "linkClick"),
    "orderCount": ("orderCount", "orderNum", "orders", "conversionCount", "payOrderCount"),
    "cartGmv": ("cartGmv", "addCartGmv", "cartAmount"),
    "reach": ("reach", "reachCount", "reachNum"),
    "newMaterialCount": ("newMaterialCount", "materialCount", "newMaterialNum"),
}


def pick_field(item, name, default=0):
    for alias in FIELD_ALIASES.get(name, (name,)):
        if isinstance(item, dict) and item.get(alias) is not None:
            return item.get(alias)
    return default


def as_list(payload):
    if payload is None:
        return []
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("list", "records", "rows", "data", "items", "content"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
    return []


def build_board():
    combos = []
    days_all = []
    for combo in COMBO_KEYS:
        brand, country = combo.split("-")
        base = os.path.join(RAW, combo)
        daily_raw = as_list(load(os.path.join(base, "board_daily.json"), None))
        daily = []
        for item in daily_raw:
            day = str(pick_field(item, "date", "") or "")[:10]
            if not DAY_RE.match(day):
                continue
            daily.append({
                "date": day,
                "spend": round(float(pick_field(item, "spend") or 0), 4),
                "gmv": round(float(pick_field(item, "gmv") or 0), 4),
                "roi": round(float(pick_field(item, "roi") or 0), 4),
                "impressions": int(float(pick_field(item, "impressions") or 0)),
                "clicks": int(float(pick_field(item, "clicks") or 0)),
                "linkClicks": int(float(pick_field(item, "linkClicks") or 0)),
                "orderCount": int(float(pick_field(item, "orderCount") or 0)),
                "cartGmv": round(float(pick_field(item, "cartGmv") or 0), 4),
                "reach": int(float(pick_field(item, "reach") or 0)),
            })
        daily.sort(key=lambda x: x["date"])

        summary = {"spend": 0.0, "gmv": 0.0, "impressions": 0, "clicks": 0,
                   "linkClicks": 0, "orderCount": 0, "cartGmv": 0.0, "reach": 0}
        for item in daily:
            summary["spend"] += item["spend"]
            summary["gmv"] += item["gmv"]
            summary["impressions"] += item["impressions"]
            summary["clicks"] += item["clicks"]
            summary["linkClicks"] += item["linkClicks"]
            summary["orderCount"] += item["orderCount"]
            summary["cartGmv"] += item["cartGmv"]
            summary["reach"] += item["reach"]
        summary["spend"] = round(summary["spend"], 4)
        summary["gmv"] = round(summary["gmv"], 4)
        summary["roi"] = round(summary["gmv"] / summary["spend"], 4) if summary["spend"] else 0
        summary["ctr"] = round(summary["linkClicks"] / summary["impressions"], 6) if summary["impressions"] else 0
        summary["cpm"] = round(summary["spend"] / summary["impressions"] * 1000, 4) if summary["impressions"] else 0
        summary["cpa"] = round(summary["spend"] / summary["orderCount"], 4) if summary["orderCount"] else 0
        summary["aov"] = round(summary["gmv"] / summary["orderCount"], 4) if summary["orderCount"] else 0

        # product-level board (可选，用于后续扩展)
        products = []
        for item in as_list(load(os.path.join(base, "board_product.json"), None)):
            name = item.get("productItemName") or item.get("productName") or item.get("name")
            if not name:
                continue
            spend = float(pick_field(item, "spend") or 0)
            gmv = float(pick_field(item, "gmv") or 0)
            products.append({
                "name": str(name),
                "spend": round(spend, 4),
                "gmv": round(gmv, 4),
                "roi": round(gmv / spend, 4) if spend else 0,
                "orderCount": int(float(pick_field(item, "orderCount") or 0)),
                "impressions": int(float(pick_field(item, "impressions") or 0)),
                "newMaterialCount": int(float(pick_field(item, "newMaterialCount") or 0)),
            })
        products.sort(key=lambda x: x["spend"], reverse=True)

        days_all.extend(item["date"] for item in daily)
        combos.append({
            "key": combo,
            "brand": BRAND_LABEL.get(brand, brand),
            "country": country.upper(),
            "countryLabel": COUNTRY_LABEL.get(country, country.upper()),
            "summary": summary,
            "daily": daily,
            "products": products,
        })

    days_all = sorted(set(days_all))
    payload = {
        "generatedAt": time.strftime("%Y-%m-%d %H:%M:%S"),
        "source": "NP / LXP DMS igad 大盘（selectAdDateBoardData）",
        "range": {"start": days_all[0] if days_all else "", "end": days_all[-1] if days_all else ""},
        "combos": combos,
    }
    with open(os.path.join(DATA, "board.json"), "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False)
    for combo in combos:
        print(f"board {combo['key']}: days={len(combo['daily'])} spend={combo['summary']['spend']} gmv={combo['summary']['gmv']}", flush=True)
    return payload


def main():
    posts, dms_rows = [], []
    for combo in COMBO_KEYS:
        try:
            p, d = collect(combo)
            print(f"{combo}: posts={len(p)} dms={len(d)}", flush=True)
            posts.extend(p)
            dms_rows.extend(d)
        except Exception as exc:  # noqa: BLE001
            print(f"{combo}: FAILED {exc}", flush=True)

    days_all = sorted({day for post in posts for day in post["days"]})
    include_from = days_all[0] if days_all else ""
    include_to = days_all[-1] if days_all else ""
    # 默认展示最近 30 天（模板同样默认单月区间）
    default_from = include_from
    if include_to:
        end = time.strptime(include_to, "%Y-%m-%d")
        start_ts = time.mktime(end) - 29 * 86400
        default_from = time.strftime("%Y-%m-%d", time.localtime(start_ts))
        if default_from < include_from:
            default_from = include_from

    raw_rows = 0
    for combo in COMBO_KEYS:
        raw_rows += len(load(os.path.join(RAW, combo, "materials.json"), []) or [])

    type_counts = defaultdict(int)
    for post in posts:
        type_counts[post["materialType"]] += 1

    payload = {
        "generatedAt": time.strftime("%Y-%m-%d %H:%M:%S"),
        "source": "NP / LXP DMS（IG 素材库 + 广告投放 + 素材每日趋势）",
        "currency": "USD",
        "rawRows": raw_rows,
        "includedRows": len(posts),
        "materialTypeCounts": dict(type_counts),
        "filters": {
            "performanceFrom": default_from,
            "performanceTo": include_to,
            "dataFrom": include_from,
            "dataTo": include_to,
            "materialTypes": ["图文", "视频"],
            "codePrefixes": list(MATERIAL_CODE_PREFIXES),
            "excludedAdNameKeywords": list(EXCLUDED_AD_NAME_KEYWORDS),
        },
        "scope": "素材编号 " + " / ".join(f"{p}*" for p in MATERIAL_CODE_PREFIXES)
                 + " · 排除广告名含「" + "」「".join(EXCLUDED_AD_NAME_KEYWORDS) + "」",
        "brands": ["NP", "LXP"],
        "countries": ["ID", "MY"],
        "posts": posts,
    }
    os.makedirs(DATA, exist_ok=True)
    try:
        build_board()
    except Exception as exc:  # noqa: BLE001
        print(f"board: FAILED {exc}", flush=True)
    with open(os.path.join(DATA, "materials.json"), "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False)

    dms_payload = {
        "generatedAt": time.strftime("%Y-%m-%d %H:%M:%S"),
        "source": "NP / LXP DMS IG 已投放素材（有花费）",
        "paidFrom": include_from,
        "paidTo": include_to,
        "dmsUrl": "https://web.npdms.com/dms/id/ad/#/place/material",
        "count": len(dms_rows),
        "rows": dms_rows,
    }
    with open(os.path.join(DATA, "dms_materials.json"), "w", encoding="utf-8") as fh:
        json.dump(dms_payload, fh, ensure_ascii=False)

    print(f"\nposts={len(posts)} dms_rows={len(dms_rows)} days={include_from}~{include_to}")


if __name__ == "__main__":
    main()
