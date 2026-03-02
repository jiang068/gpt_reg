"""
OpenAI 协议注册机 (Protocol Keygen) v5 — 全流程纯 HTTP 实现
========================================================
协议注册机实现

核心架构（全流程纯 HTTP，零浏览器依赖）：

  【注册流程】全步骤纯 HTTP：
    步骤0：GET  /oauth/authorize         → 获取 login_session cookie（PKCE + screen_hint=signup）
    步骤0：POST /api/accounts/authorize/continue → 提交邮箱（需 sentinel token）
    步骤2：POST /api/accounts/user/register      → 注册用户（username+password，需 sentinel）
    步骤3：GET  /api/accounts/email-otp/send      → 触发验证码发送
    步骤4：POST /api/accounts/email-otp/validate  → 提交邮箱验证码
    步骤5：POST /api/accounts/create_account      → 提交姓名+生日完成注册

  【OAuth 登录流程】纯 HTTP（perform_codex_oauth_login_http）：
    步骤1：GET  /oauth/authorize                  → 获取 login_session
    步骤2：POST /api/accounts/authorize/continue   → 提交邮箱
    步骤3：POST /api/accounts/password/verify       → 提交密码
    步骤4：consent 多步流程 → 提取 code → POST /oauth/token 换取 tokens

  Sentinel Token PoW 生成（纯 Python，逆向 SDK JS 的 PoW 算法）：
    - FNV-1a 哈希 + xorshift 混合
    - 伪造浏览器环境数据数组
    - 暴力搜索直到哈希前缀 ≤ 难度阈值
    - t 字段传空字符串（服务端不校验），c 字段从 sentinel API 实时获取

关键协议字段（逆向还原）：
  - oai-client-auth-session: OAuth 流程中由服务端 Set-Cookie 设置的会话 cookie
  - openai-sentinel-token:   JSON 对象 {p, t, c, id, flow}
  - Cookie 链式传递:         每步 Set-Cookie 自动累积
  - oai-did:                 设备唯一标识（UUID v4）

环境依赖：
  pip install requests
"""

import json
import os
import re
import sys
import time
import uuid
import math
import random
import string
import secrets
import hashlib
import base64
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse, parse_qs, urlencode, quote

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# 迁移的工具函数和常量
from .utils import *


# =================== 配置加载 ===================

def load_config():
    """加载外部配置文件"""
    # 指向根目录的 config.json，而不是 codex 子目录中的
    script_dir = os.path.dirname(os.path.abspath(__file__))
    root_dir = os.path.dirname(script_dir)  # 向上一级到根目录
    config_path = os.path.join(root_dir, "config.json")
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"config.json 未找到: {config_path}")
    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)


_config = load_config()

# 基础配置
TOTAL_ACCOUNTS = _config.get("total_accounts", 30)
CONCURRENT_WORKERS = _config.get("concurrent_workers", 1)  # 并发数（默认串行）
HEADLESS = _config.get("headless", False)  # 是否无头模式运行浏览器
PROXY = _config.get("proxy", "")

# 邮箱配置（使用统一的 freemail 配置）
FREEMAIL_WORKER_DOMAIN = _config.get("freemail_worker_domain", "")
FREEMAIL_TOKEN = _config.get("freemail_token", "")

# OAuth 配置
OAUTH_ISSUER = _config.get("oauth_issuer", "https://auth.openai.com")
OAUTH_CLIENT_ID = _config.get("oauth_client_id", "app_EMoamEEZ73f0CkXaXp7hrann")
OAUTH_REDIRECT_URI = _config.get("oauth_redirect_uri", "http://localhost:1455/auth/callback")

# 上传配置
UPLOAD_API_URL = _config.get("upload_api_url", "")
UPLOAD_API_TOKEN = _config.get("upload_api_token", "")

# 输出文件
ACCOUNTS_FILE = _config.get("accounts_file", "accounts.txt")
CSV_FILE = _config.get("csv_file", "registered_accounts.csv")
AK_FILE = _config.get("ak_file", "ak.txt")
RK_FILE = _config.get("rk_file", "rk.txt")

# 并发文件写入锁（多线程共享文件时防止数据竞争）
_file_lock = threading.Lock()

# 使用根目录的 emailing 模块
from core.emailing import create_temp_email as create_temp_email_impl, wait_for_verification_email as wait_for_verification_email_impl
from .registrar import ProtocolRegistrar
from .oauth import *


# =================== 账号持久化 ===================

def save_account(email, password, accounts_file, csv_file):
    """保存账号信息（线程安全）"""
    try:
        with _file_lock:
            with open(accounts_file, "a", encoding="utf-8") as f:
                f.write(f"{email}:{password}\n")
            file_exists = os.path.exists(csv_file)
            with open(csv_file, "a", newline="", encoding="utf-8") as f:
                import csv
                w = csv.writer(f)
                if not file_exists:
                    w.writerow(["email", "password", "timestamp"])
                w.writerow([email, password, time.strftime("%Y-%m-%d %H:%M:%S")])
        print(f"  ✅ 账号已保存")
    except Exception as e:
        print(f"  ⚠️ 保存失败: {e}")


# =================== 批量执行入口 ===================

def register_one(worker_id=0, task_index=0, total=1):
    """
    注册单个账号的完整流程（线程安全）
    返回: (email, password, success, reg_time, total_time)
    """
    tag = f"[W{worker_id}]" if CONCURRENT_WORKERS > 1 else ""
    t_start = time.time()
    
    # 注意：codex 工具现在将使用 freemail
    print("📧 创建临时邮箱 (freemail)...")
    email, _, mail_token = create_temp_email_impl(
        None, None, PROXY, FREEMAIL_WORKER_DOMAIN, FREEMAIL_TOKEN, user_agent=USER_AGENT
    )
    if not email:
        return None, None, False, 0, 0

    password = generate_random_password()

    # 2. 协议注册
    registrar = ProtocolRegistrar()
    # ProtocolRegistrar 需要一个方法来获取验证码
    def _wait_for_code_wrapper():
        return wait_for_verification_email_impl(
            None, mail_token, 120, user_agent=USER_AGENT, proxy=PROXY, 
            freemail_worker_domain=FREEMAIL_WORKER_DOMAIN, freemail_token=FREEMAIL_TOKEN
        )
    
    success, email, password = registrar.register(email, password, _wait_for_code_wrapper)
    save_account(email, password, ACCOUNTS_FILE, CSV_FILE)

    t_reg = time.time() - t_start  # 注册耗时

    if not success:
        return email, password, success, t_reg, time.time() - t_start

    # 3. Codex OAuth 登录
    tokens = None
    try:
        tokens = perform_codex_oauth_login_http(
            email, password,
            registrar_session=registrar.session,
            mail_token=mail_token
        )

        if not tokens:
            print(f"{tag}  ❌ 纯 HTTP OAuth 失败")

        t_total = time.time() - t_start
        if tokens:
            # 直接在这里保存 tokens
            access_token = tokens.get("access_token", "")
            refresh_token = tokens.get("refresh_token", "")
            with _file_lock:
                if access_token:
                    with open(AK_FILE, "a", encoding="utf-8") as f:
                        f.write(f"{access_token}\n")
                if refresh_token:
                    with open(RK_FILE, "a", encoding="utf-8") as f:
                        f.write(f"{refresh_token}\n")
            print(f"{tag} ✅ {email} | 注册 {t_reg:.1f}s + OAuth {t_total - t_reg:.1f}s = 总 {t_total:.1f}s")
        else:
            print(f"{tag} ⚠️ OAuth 失败（注册已成功）")
    except Exception as e:
        t_total = time.time() - t_start
        print(f"{tag} ⚠️ OAuth 异常: {e}")
        import traceback
        traceback.print_exc()

    return email, password, True, t_reg, t_total


def run_batch():
    """批量注册入口（支持并发）"""
