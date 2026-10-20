"""推送渠道。全部通过环境变量配置（在 GitHub 仓库 Settings → Secrets 里设置），配几个就推几个。

  SERVERCHAN_KEY                       Server酱（推送到个人微信）  https://sct.ftqq.com
  WECOM_WEBHOOK                        企业微信群机器人 webhook 地址
  TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID Telegram 机器人
  SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS, ALERT_EMAIL_TO   邮件
"""
from __future__ import annotations

import os
import smtplib
from email.mime.text import MIMEText
from email.header import Header

import requests


def _env(name: str) -> str:
    return os.environ.get(name, "").strip().strip("\"'").strip()


def channels() -> list[str]:
    out = []
    if _env("SERVERCHAN_KEY"):
        out.append("serverchan")
    if _env("WECOM_WEBHOOK"):
        out.append("wecom")
    if _env("TELEGRAM_BOT_TOKEN") and _env("TELEGRAM_CHAT_ID"):
        out.append("telegram")
    if _env("SMTP_HOST") and _env("ALERT_EMAIL_TO"):
        out.append("email")
    return out


def send(title: str, body_md: str) -> dict[str, str]:
    """发送到所有已配置的渠道，返回每个渠道的结果。单个渠道失败不影响其他渠道。"""
    print(f"\n===== {title} =====\n{body_md}\n")
    results = {}
    for ch in channels():
        try:
            {"serverchan": _serverchan, "wecom": _wecom, "telegram": _telegram, "email": _email}[ch](title, body_md)
            results[ch] = "ok"
        except Exception as e:  # noqa: BLE001 - 推送失败只记录
            results[ch] = f"失败: {_safe_error(e)}"
            print(f"[推送失败] {ch}: {_safe_error(e)}")
    return results


def _safe_error(e: Exception) -> str:
    """错误信息里常带完整 URL（Server酱 / Telegram 的密钥就在 URL 里），只保留不含密钥的部分。"""
    if isinstance(e, requests.HTTPError) and e.response is not None:
        return f"HTTP {e.response.status_code} {e.response.text[:150]}"
    if isinstance(e, requests.RequestException):
        return f"网络错误 {type(e).__name__}"
    return str(e)[:200]


def _serverchan(title: str, body: str) -> None:
    key = _env("SERVERCHAN_KEY")
    host = "sctapi.ftqq.com"
    if key.startswith("sctp"):  # Server酱³ 的 key 用另一个域名
        import re
        m = re.match(r"sctp(\d+)t", key)
        host = f"{m.group(1)}.push.ft07.com" if m else host
    r = requests.post(f"https://{host}/send/{key}.send" if host != "sctapi.ftqq.com" else f"https://{host}/{key}.send",
                      data={"title": title[:32], "desp": body}, timeout=15)
    r.raise_for_status()
    data = r.json()
    if data.get("code", 0) != 0:
        raise RuntimeError(f"Server酱返回错误: {data.get('message') or data}")


def _wecom(title: str, body: str) -> None:
    r = requests.post(_env("WECOM_WEBHOOK"),
                      json={"msgtype": "markdown", "markdown": {"content": f"**{title}**\n{body}"}}, timeout=15)
    r.raise_for_status()
    if r.json().get("errcode", 0) != 0:
        raise RuntimeError(r.text)


def _telegram(title: str, body: str) -> None:
    token = _env("TELEGRAM_BOT_TOKEN")
    text = f"{title}\n\n{body}".replace("**", "")
    r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                      json={"chat_id": _env("TELEGRAM_CHAT_ID"), "text": text, "disable_web_page_preview": True},
                      timeout=15)
    r.raise_for_status()


def _email(title: str, body: str) -> None:
    msg = MIMEText(body.replace("**", ""), "plain", "utf-8")
    msg["Subject"] = Header(title, "utf-8")
    msg["From"] = _env("SMTP_USER")
    msg["To"] = _env("ALERT_EMAIL_TO")
    port = int(_env("SMTP_PORT") or 465)
    cls = smtplib.SMTP_SSL if port == 465 else smtplib.SMTP
    with cls(_env("SMTP_HOST"), port, timeout=20) as s:
        if port != 465:
            s.starttls()
        if _env("SMTP_USER"):
            s.login(_env("SMTP_USER"), _env("SMTP_PASS"))
        s.sendmail(_env("SMTP_USER"), [x.strip() for x in _env("ALERT_EMAIL_TO").split(",")], msg.as_string())
