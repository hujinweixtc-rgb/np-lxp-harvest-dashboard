#!/usr/bin/env python3
"""NP / LXP 素材看板 —— Cloud Run 单服务（静态页 + 实时刷新 API）。

架构
----
* 镜像内自带 `data/` 快照与 `raw.tar.gz`（DMS 原始缓存压缩包）。
* Cloud Run 文件系统除 `/tmp` 外只读，因此启动时把 raw 缓存解压到
  `DASH_RAW_DIR`（/tmp/raw），并把 `data/` 复制到 `DASH_DATA_DIR`（/tmp/data）
  作为可写输出目录。
* 刷新由后台线程执行 `scripts/` 下的 DMS 管线，前端轮询进度。

路由
----
  GET  /                     首页 index.html
  GET  /data/*               data 文件（优先 /tmp 下的最新结果，回退镜像内快照）
  GET  /media-proxy?url=...  代理 DMS/OSS 素材（绕 Referer 防盗链，白名单域名）
  GET  /api/status           当前数据版本 + 刷新任务状态
  POST /api/refresh[?quick=1] 触发刷新（立即返回 202）
  GET  /api/refresh/status   刷新进度（前端轮询）

环境变量
--------
  PORT              监听端口（Cloud Run 注入，默认 8080）
  DASH_RAW_DIR      DMS 缓存目录（默认 <root>/raw）
  DASH_DATA_DIR     看板数据输出目录（默认 <root>/data）
  DMS_TOKEN_NP      NP 的 DMS token（来自 Secret Manager）
  DMS_TOKEN_LXP     LXP 的 DMS token（来自 Secret Manager）
"""
from __future__ import annotations

import json
import mimetypes
import os
import posixpath
import shutil
import subprocess
import sys
import tarfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS_DIR = os.path.join(APP_DIR, "scripts")
SEED_DATA_DIR = os.path.join(APP_DIR, "data")
RAW_ARCHIVE = os.path.join(APP_DIR, "raw.tar.gz")

RAW_DIR = os.environ.get("DASH_RAW_DIR") or os.path.join(APP_DIR, "raw")
DATA_DIR = os.environ.get("DASH_DATA_DIR") or os.path.join(APP_DIR, "data")
PORT = int(os.environ.get("PORT") or 8080)
RAW_READY_MARK = os.path.join(RAW_DIR, ".ready")

# 刷新结果持久化到 GCS：Cloud Run 实例闲置回收后 /tmp 会清空，否则下次冷启动
# 只能退回镜像内的旧快照。留空 DASH_GCS_BUCKET 即关闭该能力。
GCS_BUCKET = (os.environ.get("DASH_GCS_BUCKET") or "").strip()
GCS_PREFIX = (os.environ.get("DASH_GCS_PREFIX") or "np-lxp-harvest/data").strip("/")
DATA_FILES = ("materials.json", "dms_materials.json", "board.json")

LOG_TAIL = 120

# /media-proxy 只允许代理这些素材域名（防盗链 + 防 SSRF）
MEDIA_PROXY_HOSTS = {
    "dms-upload-prod-sg.oss-ap-southeast-1.aliyuncs.com",
    "cdn-prod.feimeidms.com",
}

# 快速刷新：只补素材投放窗口 + 大盘，跳过整张广告表与全量趋势重拉。
STAGES_QUICK = (
    ("大盘聚合", "refresh_board.py"),
    ("素材投放窗口（含趋势明细回补）", "refresh_adv.py"),
    ("组装看板数据", "build_data.py"),
)
STAGES_FULL = (
    ("大盘聚合", "refresh_board.py"),
    ("广告表 + 新增素材", "refresh_ads.py"),
    ("素材投放窗口（含趋势明细回补）", "refresh_adv.py"),
    ("近期趋势明细", "refresh_recent.py"),
    ("组装看板数据", "build_data.py"),
)

_meta = {"boot": time.strftime("%Y-%m-%d %H:%M:%S"), "raw": "pending", "data": "pending"}
_job_lock = threading.Lock()
_job = {
    "running": False,
    "mode": "",
    "stage": "",
    "index": 0,
    "total": 0,
    "startedAt": "",
    "finishedAt": "",
    "ok": None,
    "error": "",
    "log": [],
}


def _log(msg):
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    with _job_lock:
        _job["log"].append(line)
        if len(_job["log"]) > LOG_TAIL:
            del _job["log"][:-LOG_TAIL]


# --------------------------------------------------------------------------- #
# 启动引导
# --------------------------------------------------------------------------- #
def _is_nonempty_dir(path):
    try:
        with os.scandir(path) as it:
            return any(True for _ in it)
    except OSError:
        return False


def extract_raw():
    """把镜像内的 raw.tar.gz 解压到可写目录（仅首次）。

    安全约定：RAW_DIR 已有内容时直接复用，绝不删除已有目录。
    原实现会无条件 rmtree(RAW_DIR)——本地开发一旦把 DASH_RAW_DIR 指向真实
    缓存目录，就会误删数百 MB 数据（2026-10-15 实际踩到）。
    """
    if _is_nonempty_dir(RAW_DIR):
        return "raw dir already present"
    if not os.path.exists(RAW_ARCHIVE):
        return "no archive (expects existing raw dir)"
    if os.path.exists(RAW_READY_MARK):
        return "already extracted"
    parent = os.path.dirname(RAW_DIR)
    os.makedirs(parent, exist_ok=True)
    tmp = RAW_DIR.rstrip("/\\") + ".partial"
    if _is_nonempty_dir(tmp):
        # 残留的临时目录（上次解压中断 / 本地沙箱拦截）——提示而不强删
        return f"partial dir blocks extraction, remove it first: {tmp}"
    os.makedirs(tmp, exist_ok=True)
    t0 = time.time()
    with tarfile.open(RAW_ARCHIVE, "r:gz") as tf:
        tf.extractall(tmp)
    inner = os.path.join(tmp, "raw")
    source = inner if os.path.isdir(inner) else tmp
    # 走到这里说明 RAW_DIR 为空或不存在：空目录只删目录本身，不动内容
    if os.path.isdir(RAW_DIR):
        try:
            os.rmdir(RAW_DIR)
        except OSError:
            pass
    shutil.move(source, RAW_DIR)
    if os.path.isdir(tmp):
        shutil.rmtree(tmp, ignore_errors=True)
    with open(RAW_READY_MARK, "w", encoding="utf-8") as fh:
        fh.write(time.strftime("%Y-%m-%d %H:%M:%S"))
    return f"extracted in {time.time() - t0:.1f}s"


def seed_data():
    """把镜像内的 data 快照复制到可写目录（缺失才复制，保留已刷新的结果）。"""
    if os.path.abspath(DATA_DIR) == os.path.abspath(SEED_DATA_DIR):
        return "in-place"
    os.makedirs(DATA_DIR, exist_ok=True)
    copied = 0
    for name in os.listdir(SEED_DATA_DIR):
        src = os.path.join(SEED_DATA_DIR, name)
        dst = os.path.join(DATA_DIR, name)
        if os.path.isfile(src) and not os.path.exists(dst):
            shutil.copy2(src, dst)
            copied += 1
    return f"seeded {copied} file(s)"


# --------------------------------------------------------------------------- #
# 刷新任务
# --------------------------------------------------------------------------- #
def _run_script(script, env):
    path = os.path.join(SCRIPTS_DIR, script)
    proc = subprocess.Popen(
        [sys.executable, path],
        cwd=SCRIPTS_DIR,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )
    tail = []
    for raw_line in proc.stdout:  # type: ignore[union-attr]
        line = raw_line.rstrip()
        if not line:
            continue
        tail.append(line)
        if len(tail) > 6:
            del tail[:-6]
        _log(f"    {line[:400]}")
    code = proc.wait()
    if code != 0:
        raise RuntimeError(f"{script} 退出码 {code}: " + " | ".join(tail[-3:]))


def _worker(stages):
    env = dict(os.environ)
    env["DASH_RAW_DIR"] = RAW_DIR
    env["DASH_DATA_DIR"] = DATA_DIR
    env["PYTHONUNBUFFERED"] = "1"
    total = len(stages)
    try:
        for idx, (label, script) in enumerate(stages, 1):
            with _job_lock:
                _job["index"] = idx
                _job["stage"] = label
            _log(f"[{idx}/{total}] {label}  ({script})")
            _run_script(script, env)
        with _job_lock:
            _job["ok"] = True
            _job["stage"] = "完成"
        _log("刷新完成")
        _meta["gcs"] = gcs_backup(_log)
        _log(f"持久化：{_meta['gcs']}")
    except Exception as exc:  # noqa: BLE001
        with _job_lock:
            _job["ok"] = False
            _job["error"] = str(exc)
            _job["stage"] = "失败"
        _log(f"刷新失败：{exc}")
    finally:
        with _job_lock:
            _job["running"] = False
            _job["finishedAt"] = time.strftime("%Y-%m-%d %H:%M:%S")


def start_refresh(quick):
    stages = STAGES_QUICK if quick else STAGES_FULL
    with _job_lock:
        if _job["running"]:
            return False, "已有刷新任务在进行中"
        _job.update({
            "running": True,
            "mode": "quick" if quick else "full",
            "stage": "启动中",
            "index": 0,
            "total": len(stages),
            "startedAt": time.strftime("%Y-%m-%d %H:%M:%S"),
            "finishedAt": "",
            "ok": None,
            "error": "",
            "log": [],
        })
    threading.Thread(target=_worker, args=(stages,), daemon=True).start()
    return True, "已启动"


def _generated_at(path):
    """读取一个看板 JSON 的 generatedAt（只读文件头部，避免整个 11MB 解析）。"""
    try:
        with open(path, encoding="utf-8") as fh:
            head = fh.read(4000)
        marker = '"generatedAt"'
        pos = head.find(marker)
        if pos < 0:
            return ""
        seg = head[pos + len(marker):]
        start = seg.find('"') + 1
        end = seg.find('"', start)
        return seg[start:end]
    except Exception:  # noqa: BLE001
        return ""


def data_version():
    return _generated_at(os.path.join(DATA_DIR, "materials.json"))


# --------------------------------------------------------------------------- #
# GCS 持久化（刷新结果跨实例生命周期保留）
# --------------------------------------------------------------------------- #
def _metadata_token():
    req = urllib.request.Request(
        "http://metadata.google.internal/computeMetadata/v1/instance/"
        "service-accounts/default/token",
        headers={"Metadata-Flavor": "Google"},
    )
    with urllib.request.urlopen(req, timeout=5) as resp:
        return json.loads(resp.read().decode("utf-8"))["access_token"]


def _gcs_open(url, token, method="GET", data=None, ctype=None):
    headers = {"Authorization": f"Bearer {token}"}
    if ctype:
        headers["Content-Type"] = ctype
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    return urllib.request.urlopen(req, timeout=180)


def _object_name(name):
    return f"{GCS_PREFIX}/{name}" if GCS_PREFIX else name


def gcs_restore(log):
    """冷启动时用 GCS 上的最新结果覆盖镜像快照（仅当它更新时）。"""
    if not GCS_BUCKET:
        return "disabled"
    try:
        token = _metadata_token()
    except Exception as exc:  # noqa: BLE001
        return f"no token ({exc})"
    restored = []
    for name in DATA_FILES:
        url = ("https://storage.googleapis.com/storage/v1/b/"
               f"{GCS_BUCKET}/o/{urllib.parse.quote(_object_name(name), safe='')}?alt=media")
        try:
            with _gcs_open(url, token) as resp:
                payload = resp.read()
            remote_at = str(json.loads(payload.decode("utf-8")).get("generatedAt") or "")
        except urllib.error.HTTPError as exc:
            if exc.code != 404:
                log(f"gcs restore {name}: HTTP {exc.code}")
            continue
        except Exception as exc:  # noqa: BLE001
            log(f"gcs restore {name}: {exc}")
            continue
        local_path = os.path.join(DATA_DIR, name)
        local_at = _generated_at(local_path)
        if remote_at and (not local_at or remote_at > local_at):
            with open(local_path, "wb") as fh:
                fh.write(payload)
            restored.append(name)
    return f"restored {restored}" if restored else "up-to-date"


def gcs_backup(log):
    """刷新成功后把结果推回 GCS，供后续冷启动复用。"""
    if not GCS_BUCKET:
        return "disabled"
    try:
        token = _metadata_token()
    except Exception as exc:  # noqa: BLE001
        return f"no token ({exc})"
    saved = []
    for name in DATA_FILES:
        path = os.path.join(DATA_DIR, name)
        if not os.path.isfile(path):
            continue
        url = ("https://storage.googleapis.com/upload/storage/v1/b/"
               f"{GCS_BUCKET}/o?uploadType=media&name={urllib.parse.quote(_object_name(name), safe='')}")
        try:
            with open(path, "rb") as fh:
                payload = fh.read()
            with _gcs_open(url, token, method="POST", data=payload,
                           ctype="application/json; charset=utf-8") as resp:
                resp.read()
            saved.append(name)
        except Exception as exc:  # noqa: BLE001
            log(f"gcs backup {name}: {exc}")
    return f"saved {saved}" if saved else "nothing saved"


# --------------------------------------------------------------------------- #
# HTTP
# --------------------------------------------------------------------------- #
class Handler(BaseHTTPRequestHandler):
    server_version = "np-lxp-dashboard"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):  # noqa: A003
        pass  # Cloud Run 已收集请求日志，避免噪声

    # -- helpers ----------------------------------------------------------- #
    def _send(self, status, body, ctype="application/json; charset=utf-8", cache="no-store"):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(status)
        self.send_header("content-type", ctype)
        self.send_header("content-length", str(len(body)))
        self.send_header("cache-control", cache)
        self.send_header("access-control-allow-origin", "*")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, payload, status=200):
        self._send(status, json.dumps(payload, ensure_ascii=False))

    def _serve_file(self, path, content_type=None):
        if not os.path.isfile(path):
            return False
        ctype = content_type or mimetypes.guess_type(path)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript", "application/json"):
            ctype += "; charset=utf-8"
        try:
            size = os.path.getsize(path)
            self.send_response(200)
            self.send_header("content-type", ctype)
            self.send_header("content-length", str(size))
            self.send_header("cache-control", "no-store" if path.endswith(".json") else "public, max-age=300")
            self.send_header("access-control-allow-origin", "*")
            self.end_headers()
            if self.command != "HEAD":
                with open(path, "rb") as fh:
                    shutil.copyfileobj(fh, self.wfile)
            return True
        except (BrokenPipeError, ConnectionResetError):
            return True

    def _resolve(self, base, rel):
        """把 URL 相对路径安全地映射到 base 下的真实文件路径。"""
        rel = posixpath.normpath(unquote(rel)).lstrip("/")
        if rel.startswith("..") or os.path.isabs(rel):
            return ""
        target = os.path.normpath(os.path.join(base, rel.replace("/", os.sep)))
        if os.path.commonpath([os.path.abspath(base), os.path.abspath(target)]) != os.path.abspath(base):
            return ""
        return target

    def _proxy_media(self, params):
        """代理 DMS / OSS 素材（图片快照、视频封面）。

        这些域名开了 Referer 防盗链：浏览器带着 run.app / github.io 的 Referer
        直接请求会 403，所以必须由服务端转发（服务端请求不带 Referer）。
        只允许白名单域名，避免被当成任意 URL 的开放代理（SSRF）。
        """
        raw = (params.get("url") or [""])[0].strip()
        if not raw:
            return self._send(400, "missing url", "text/plain; charset=utf-8")
        parts = urlparse(raw)
        host = (parts.hostname or "").lower()
        if parts.scheme not in ("http", "https") or host not in MEDIA_PROXY_HOSTS:
            return self._send(403, "host not allowed", "text/plain; charset=utf-8")
        req = urllib.request.Request(raw, method="GET")
        # 刻意不转发 Referer —— 这是绕开防盗链的关键
        req.add_header("User-Agent", "np-lxp-dashboard-media-proxy/1.0")
        client_range = self.headers.get("range")
        if client_range:
            req.add_header("Range", client_range)
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                upstream = resp.status
                self.send_response(206 if upstream == 206 else 200)
                for key in ("content-type", "content-length", "content-range",
                            "accept-ranges", "last-modified", "etag"):
                    value = resp.headers.get(key)
                    if value:
                        self.send_header(key, value)
                self.send_header("cache-control", "public, max-age=86400")
                self.send_header("access-control-allow-origin", "*")
                self.send_header("cross-origin-resource-policy", "cross-origin")
                self.end_headers()
                if self.command != "HEAD":
                    shutil.copyfileobj(resp, self.wfile)
        except urllib.error.HTTPError as exc:
            return self._send(exc.code, f"upstream {exc.code}", "text/plain; charset=utf-8")
        except (BrokenPipeError, ConnectionResetError):
            return
        except Exception as exc:  # noqa: BLE001
            return self._send(502, f"proxy error: {exc}", "text/plain; charset=utf-8")

    # -- routes ------------------------------------------------------------ #
    def do_GET(self):  # noqa: N802
        parsed = urlparse(self.path)
        route = parsed.path
        if route == "/media-proxy":
            return self._proxy_media(parse_qs(parsed.query))
        if route == "/api/status":
            with _job_lock:
                job = dict(_job)
                job.pop("log", None)
            return self._json({
                "ok": True,
                "dataVersion": data_version(),
                "boot": _meta,
                "refresh": job,
            })
        if route == "/api/refresh/status":
            with _job_lock:
                return self._json({"ok": True, "refresh": dict(_job)})
        if route in ("/healthz", "/api/health"):
            return self._json({"ok": True})

        if route.startswith("/data/"):
            rel = route[len("/data/"):]
            for base in (DATA_DIR, SEED_DATA_DIR):
                target = self._resolve(base, rel)
                if target and self._serve_file(target):
                    return
            return self._send(404, "not found", "text/plain; charset=utf-8")

        rel = route.lstrip("/") or "index.html"
        target = self._resolve(APP_DIR, rel)
        if target and self._serve_file(target):
            return
        return self._send(404, "not found", "text/plain; charset=utf-8")

    do_HEAD = do_GET

    def do_OPTIONS(self):  # noqa: N802
        self.send_response(204)
        self.send_header("access-control-allow-origin", "*")
        self.send_header("access-control-allow-methods", "GET, HEAD, POST, OPTIONS")
        self.send_header("access-control-allow-headers", "content-type")
        self.send_header("content-length", "0")
        self.end_headers()

    def do_POST(self):  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path != "/api/refresh":
            return self._send(404, "not found", "text/plain; charset=utf-8")
        params = parse_qs(parsed.query)
        quick = str(params.get("quick", ["0"])[0]).lower() in ("1", "true", "yes")
        ok, message = start_refresh(quick)
        return self._json({"ok": ok, "message": message,
                           "mode": "quick" if quick else "full"}, 202 if ok else 409)


def main():
    _meta["raw"] = extract_raw()
    _meta["data"] = seed_data()
    _meta["gcs"] = gcs_restore(print)
    print(f"[boot] raw={_meta['raw']} data={_meta['data']} gcs={_meta['gcs']}", flush=True)
    httpd = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"[boot] listening on 0.0.0.0:{PORT}", flush=True)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
