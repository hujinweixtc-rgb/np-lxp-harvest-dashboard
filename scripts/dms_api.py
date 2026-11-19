"""DMS API client for NP / LXP / FR / SKT (feimei DMS igad module).

凭据来源（按优先级）：
  1. 环境变量  DMS_TOKEN_NP / DMS_TOKEN_LXP / DMS_TOKEN_FR / DMS_TOKEN_SKT
  2. 本地文件  config/dms_tokens.json  -> {"NP": "...", "LXP": "...", "FR": "...", "SKT": "..."}
     （config/ 已加入 .gitignore，切勿提交）

不要把 token 写进源码——本仓库是公开仓库，曾因此泄露过一次。
"""
import json
import os
import ssl
import time
import urllib.error
import urllib.request

CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.environ.get("DMS_TOKENS_FILE") or os.path.join(ROOT, "config", "dms_tokens.json")

BRANDS = ("NP", "LXP", "FR", "SKT")


def load_tokens():
    tokens = {}
    for brand in BRANDS:
        value = (os.environ.get(f"DMS_TOKEN_{brand}") or "").strip()
        if value:
            tokens[brand] = value
    if len(tokens) < len(BRANDS) and os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, encoding="utf-8") as fh:
                local = json.load(fh) or {}
            for brand in BRANDS:
                if brand not in tokens and str(local.get(brand) or "").strip():
                    tokens[brand] = str(local[brand]).strip()
        except Exception:  # noqa: BLE001
            pass
    return tokens


_TOKENS = load_tokens()


def token_for(brand):
    value = _TOKENS.get(brand) or ""
    if not value:
        raise RuntimeError(
            f"缺少 {brand} 的 DMS token：请设置环境变量 DMS_TOKEN_{brand}，"
            f"或在 {CONFIG_PATH} 写入 {{\"{brand}\": \"...\"}}"
        )
    return value


# key, brand, host, brandId, country, tenant, token
COMBOS = [
    ("NP-ID",   "NP",  "web.npdms.com",   6, "id", "206", token_for("NP")),
    ("NP-MY",   "NP",  "web.npdms.com",   6, "my", "206", token_for("NP")),
    ("LXP-ID",  "LXP", "web.lxpdms.com",  8, "id", "209", token_for("LXP")),
    ("LXP-MY",  "LXP", "web.lxpdms.com",  8, "my", "209", token_for("LXP")),
    ("FR-MY",   "FR",  "web.bersamadms.com", 4, "my", "202", token_for("FR")),
    ("SKT-MY",  "SKT", "web.cerahdms.com",   1, "my", "125", token_for("SKT")),
]

brand_label = {"NP": "NP（NextPrime）", "LXP": "LXP", "FR": "FR", "SKT": "SKT（SKINTIFIC）"}

# SKT 素材库基数极大（5.5 万素材 / 23 万广告 / 5.8 万有花费素材），全量进管线会把
# Cloud Run 的 /tmp 与免费关键词额度一起吃光。这里只把 SKT 收敛到近期创建的素材，
# 其余品牌保持全量历史。日期可用 DASH_MATERIAL_CREATED_FROM 调整。
MATERIAL_CREATED_FROM = os.environ.get("DASH_MATERIAL_CREATED_FROM", "2026-09-01").strip()
SCOPED_COMBOS = {"SKT-MY"}


def is_scoped_combo(key):
    return key in SCOPED_COMBOS and bool(MATERIAL_CREATED_FROM)


def material_created_at(row):
    return str((row or {}).get("createdAt") or (row or {}).get("uploadTime") or "")[:10]


def keep_scoped_material(key, row):
    """SKT 只保留近期创建的素材；无创建时间的行一律丢弃，避免误收历史长尾。"""
    if not is_scoped_combo(key):
        return True
    created = material_created_at(row)
    return bool(created) and created >= MATERIAL_CREATED_FROM


class Dms:
    def __init__(self, host, brand_id, country, tenant, token):
        self.host = host
        self.base = f"https://{host}/api/admin-api/"
        self.headers = {
            "accept": "application/json, text/plain, */*",
            "accept-language": "zh",
            "authorization": f"Bearer {token}",
            "content-type": "application/json",
            "corp": "fm",
            "fm-brandid": str(brand_id),
            "fm-country": country,
            "fm-domain-id": "0",
            "fm-domain-type": "brand",
            "fm-system": "ad",
            "origin": f"https://{host}",
            "platform": "ig",
            "referer": f"https://{host}/dms/{country}/ad/",
            "tenant-id": str(tenant),
            "user-agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                           "(KHTML, like Gecko) Chrome/154.0.0.0 Safari/537.36"),
        }

    def post(self, path, body, retries=4):
        data = json.dumps(body).encode()
        last = None
        for attempt in range(retries):
            try:
                req = urllib.request.Request(self.base + path, data=data, headers=self.headers)
                with urllib.request.urlopen(req, context=CTX, timeout=90) as r:
                    return json.loads(r.read().decode("utf-8"))
            except Exception as exc:  # noqa: BLE001
                last = exc
                time.sleep(1.5 * (attempt + 1))
        raise RuntimeError(f"POST {path} failed: {last}")


def client_for(key):
    """按 COMBOS 的 key（如 NP-ID）创建客户端。"""
    for combo_key, brand, host, brand_id, country, tenant, token in COMBOS:
        if combo_key == key:
            return Dms(host, brand_id, country, tenant, token)
    raise KeyError(key)
