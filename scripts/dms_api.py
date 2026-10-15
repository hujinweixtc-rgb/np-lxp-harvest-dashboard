"""DMS API client for NP / LXP (feimei DMS igad module).

凭据来源（按优先级）：
  1. 环境变量  DMS_TOKEN_NP / DMS_TOKEN_LXP
  2. 本地文件  config/dms_tokens.json  -> {"NP": "...", "LXP": "..."}
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

BRANDS = ("NP", "LXP")


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
]

brand_label = {"NP": "NP（NextPrime）", "LXP": "LXP"}


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
