"""刷新素材卖点 / 文案关键词（供 server/app.py 刷新链调用）。

增量逻辑在 vision_theme.py 里：cache 中已 status=ok 的素材自动跳过，
所以每次刷新只分析新增素材（以及上次失败的，会自动重试一次）。

没有 ZHIPU_API_KEY 时静默跳过（不阻断整个刷新链），模型为免费档。
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vision_theme  # noqa: E402


def main() -> None:
    if not vision_theme.api_key():
        print("未配置 ZHIPU_API_KEY，跳过素材关键词分析（不影响其余数据）", flush=True)
        return
    vision_theme.assert_free_model(vision_theme.MODEL)
    print(f"关键词分析：模型 {vision_theme.MODEL}（免费档，仅新增素材）", flush=True)
    sys.argv = ["vision_theme.py", "--all", "--workers", "4"]
    vision_theme.main()


if __name__ == "__main__":
    main()
