"""
ChatGPT 批量自动注册工具 (并发版) - freemail 临时邮箱版
依赖: pip install curl_cffi
功能: 使用 freemail 工作器创建临时邮箱，并发自动注册 ChatGPT 账号，自动获取 OTP 验证码
"""

import os
import re
import uuid
import json
import random
import string
import time
import sys
import threading
import traceback
import secrets
import hashlib
import base64
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse, parse_qs, urlencode

from curl_cffi import requests as curl_requests
from core.config import _load_config, as_bool
from app.registrar import ChatGPTRegister # 直接导入新的实现
from core.logger import logger

# Load configuration via core.config
BASE_PATH = os.path.dirname(os.path.abspath(__file__))
_CONFIG = _load_config(BASE_PATH)
DEFAULT_TOTAL_ACCOUNTS = _CONFIG["total_accounts"]
DEFAULT_PROXY = _CONFIG["proxy"]
DEFAULT_OUTPUT_FILE = _CONFIG["output_file"]
ENABLE_OAUTH = as_bool(_CONFIG.get("enable_oauth", True))
LOG_LEVEL = _CONFIG.get("log_level", "info")
logger.set_level(LOG_LEVEL)
OAUTH_REQUIRED = as_bool(_CONFIG.get("oauth_required", True))
OAUTH_ISSUER = _CONFIG["oauth_issuer"].rstrip("/")
OAUTH_CLIENT_ID = _CONFIG["oauth_client_id"]
OAUTH_REDIRECT_URI = _CONFIG["oauth_redirect_uri"]
AK_FILE = _CONFIG["ak_file"]
RK_FILE = _CONFIG["rk_file"]
TOKEN_JSON_DIR = _CONFIG["token_json_dir"]
UPLOAD_API_URL = _CONFIG["upload_api_url"]
UPLOAD_API_TOKEN = _CONFIG["upload_api_token"]

# freemail config (services/freemail.py)
FREEMAIL_WORKER_DOMAIN = (_CONFIG.get("freemail_worker_domain") or "").strip().rstrip("/")
FREEMAIL_TOKEN = (_CONFIG.get("freemail_token") or "").strip()

# 全局线程锁
_print_lock = threading.Lock()
_file_lock = threading.Lock()


# Chrome 指纹配置: impersonate 与 sec-ch-ua 必须匹配真实浏览器
from core.utils import (
    random_chrome_version as _random_chrome_version_impl,
    random_delay as _random_delay_impl,
    make_trace_headers as _make_trace_headers_impl,
    generate_pkce as _generate_pkce_impl,
    SentinelTokenGenerator,
    fetch_sentinel_challenge as fetch_sentinel_challenge_impl,
    build_sentinel_token as build_sentinel_token_impl,
    extract_code_from_url as _extract_code_from_url_impl,
    decode_jwt_payload as _decode_jwt_payload_impl,
    generate_password as _generate_password_impl,
    random_name as _random_name,
    random_birthdate as _random_birthdate,
)

from core.emailing import (
    create_temp_email as _create_temp_email_impl,
    wait_for_verification_email as _wait_for_verification_email_impl,
)

# backward-compatible wrapper names (old code expects these names)
def _random_delay(low=0.3, high=1.0):
    return _random_delay_impl(low, high)

def _random_chrome_version():
    return _random_chrome_version_impl()

def _make_trace_headers():
    return _make_trace_headers_impl()

def _generate_pkce():
    return _generate_pkce_impl()

def _extract_code_from_url(url: str):
    return _extract_code_from_url_impl(url)

def _decode_jwt_payload(token: str):
    return _decode_jwt_payload_impl(token)

def _generate_password(length=14):
    return _generate_password_impl(length)

def _save_codex_tokens(email, tokens, token_json_dir, ak_file, rk_file):
    """保存 Codex OAuth tokens 到指定路径的 JSON 文件。"""
    if not os.path.exists(token_json_dir):
        os.makedirs(token_json_dir)

    email_prefix = email.split("@")[0]
    ts = int(time.time())
    fname = f"{email_prefix}_{ts}.json"
    fpath = os.path.join(token_json_dir, fname)

    with open(fpath, "w", encoding="utf-8") as f:
        json.dump(tokens, f, indent=2)

    ak = tokens.get("access_token")
    rk = tokens.get("refresh_token")

    if ak and ak_file:
        with _file_lock:
            with open(ak_file, "a", encoding="utf-8") as f:
                f.write(f"{ak}\n")

    if rk and rk_file:
        with _file_lock:
            with open(rk_file, "a", encoding="utf-8") as f:
                f.write(f"{rk}\n")


# expose sentinel helpers under original names for backward compatibility
fetch_sentinel_challenge = fetch_sentinel_challenge_impl

def build_sentinel_token(session, device_id, flow, **kwargs):
    """向后兼容的 shim：委托给 core.utils.build_sentinel_token"""
    return build_sentinel_token_impl(session, device_id, flow, **kwargs)


# ================= 临时邮箱（freemail-only） =================

def create_temp_email():
    """创建临时邮箱，委托给 core.emailing.create_temp_email（仅使用 freemail）。

    返回 (email, mail_token)。
    """
    user_agent = None
    try:
        user_agent = _random_chrome_version()[3]
    except Exception:
        user_agent = None
    # DUCKMAIL 参数已移除 — 传入 None 以兼容 core.emailing 的签名
    email, mail_token = _create_temp_email_impl(
        None, None, DEFAULT_PROXY, FREEMAIL_WORKER_DOMAIN, FREEMAIL_TOKEN, user_agent=user_agent
    )
    return email, mail_token


def _extract_verification_code(email_content: str):
    """从邮件内容提取 6 位验证码"""
    if not email_content:
        return None

    patterns = [
        r"Verification code:?\s*(\d{6})",
        r"code is\s*(\d{6})",
        r"代码为[:：]?\s*(\d{6})",
        r"验证码[:：]?\s*(\d{6})",
        r">\s*(\d{6})\s*<",
        r"(?<![#&])\b(\d{6})\b",
    ]

    for pattern in patterns:
        matches = re.findall(pattern, email_content, re.IGNORECASE)
        for code in matches:
            if code == "177010":  # 已知误判
                continue
            return code
    return None


def wait_for_verification_email(mail_token: str, timeout: int = 120):
    """等待并提取 OpenAI 验证码，委托给 core.emailing.wait_for_verification_email。"""
    user_agent = None
    try:
        user_agent = _random_chrome_version()[3]
    except Exception:
        user_agent = None
    return _wait_for_verification_email_impl(
        None,
        mail_token,
        timeout,
        user_agent=user_agent,
        proxy=DEFAULT_PROXY,
        freemail_worker_domain=FREEMAIL_WORKER_DOMAIN,
        freemail_token=FREEMAIL_TOKEN,
    )


def _random_name():
    first = random.choice([
        "James", "Emma", "Liam", "Olivia", "Noah", "Ava", "Ethan", "Sophia",
        "Lucas", "Mia", "Mason", "Isabella", "Logan", "Charlotte", "Alexander",
        "Amelia", "Benjamin", "Harper", "William", "Evelyn", "Henry", "Abigail",
        "Sebastian", "Emily", "Jack", "Elizabeth",
    ])
    last = random.choice([
        "Smith", "Johnson", "Brown", "Davis", "Wilson", "Moore", "Taylor",
        "Clark", "Hall", "Young", "Anderson", "Thomas", "Jackson", "White",
        "Harris", "Martin", "Thompson", "Garcia", "Robinson", "Lewis",
        "Walker", "Allen", "King", "Wright", "Scott", "Green",
    ])
    return f"{first} {last}"


def _random_birthdate():
    y = random.randint(1985, 2002)
    m = random.randint(1, 12)
    d = random.randint(1, 28)
    return f"{y}-{m:02d}-{d:02d}"


# ==================== 并发批量注册 ====================

def run_batch(total_accounts: int = 3, output_file="registered_accounts.txt",
              max_workers: int = 3, proxy=None):
    """向后兼容的 shim：委托给 app.runner.run_batch"""
    from app.runner import run_batch as _run_batch
    return _run_batch(total_accounts=total_accounts, output_file=output_file,
                      max_workers=max_workers, proxy=proxy)


def main():
    """向后兼容的 shim：委托给 app.cli.main"""
    from app.cli import main as _main
    return _main()


if __name__ == "__main__":
    main()
