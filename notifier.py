"""Enterprise WeChat group-bot delivery for the local alert outbox."""

from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen


def load_local_env() -> None:
    """Load simple KEY=VALUE pairs for local uvicorn use without overriding OS env."""
    env_file = Path(__file__).with_name(".env")
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        if not line or line.lstrip().startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_local_env()


def webhook_url() -> str | None:
    url = os.environ.get("WECOM_BOT_WEBHOOK", "").strip()
    if not url:
        return None
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.netloc != "qyapi.weixin.qq.com" or not parsed.path.endswith("/cgi-bin/webhook/send"):
        raise ValueError("WECOM_BOT_WEBHOOK 必须是企业微信 qyapi.weixin.qq.com 的 HTTPS 机器人地址")
    return url


def send_markdown(content: str) -> None:
    """Send one bounded UTF-8 markdown message without logging the secret URL."""
    url = webhook_url()
    if not url:
        raise RuntimeError("未配置 WECOM_BOT_WEBHOOK")
    payload = json.dumps({"msgtype": "markdown", "markdown": {"content": content[:3500]}}, ensure_ascii=False).encode("utf-8")
    request = Request(url, data=payload, headers={"Content-Type": "application/json"}, method="POST")
    with urlopen(request, timeout=15) as response:
        result = json.loads(response.read().decode("utf-8"))
    if result.get("errcode") != 0:
        raise RuntimeError(f"企业微信返回错误 {result.get('errcode')}: {result.get('errmsg', 'unknown')}")
