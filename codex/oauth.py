"""
Codex 协议工具 - OAuth 登录模块
"""
import re
import json
import time
from urllib.parse import urlparse, parse_qs

from .utils import *
from core.utils import generate_pkce
from .sentinel import build_sentinel_token

def perform_codex_oauth_login_http(email, password, registrar_session=None, mail_token=None):
    """
    纯 HTTP 方式执行 Codex OAuth 登录获取 Token（零浏览器）。
    """
    print("\n🔐 执行 Codex OAuth 登录（纯 HTTP 模式）...")
    session = create_session()
    device_id = generate_device_id()
    session.cookies.set("oai-did", device_id, domain=".auth.openai.com")
    session.cookies.set("oai-did", device_id, domain="auth.openai.com")
    code_verifier, code_challenge = generate_pkce()
    # ===== 步骤1: 获取授权码（Authorization Code） =====
    print("  --- [步骤1] 获取授权码 ---")
    try:
        resp = session.get(
            f"{OAUTH_ISSUER}/oauth/authorize",
            params={
                "response_type": "code",
                "client_id": "codex-web",
                "redirect_uri": "https://chat.openai.com/auth/callback",
                "scope": "openid email profile",
                "code_challenge": code_challenge,
                "code_challenge_method": "S256",
            },
            headers=NAVIGATE_HEADERS,
            allow_redirects=False,
            timeout=30,
        )
    except Exception as e:
        print(f"  ❌ 获取授权码失败: {e}")
        return None

    if resp.status_code != 302:
        print(f"  ❌ 获取授权码失败: {resp.status_code} - {resp.text[:300]}")
        return None

    location = resp.headers.get("Location", "")
    code = None
    if "error" in location:
        print(f"  ❌ 获取授权码失败: {location}")
    else:
        code = parse_qs(urlparse(location).query).get("code", [None])[0]
        print(f"  ✅ 获取到授权码: {code}")

    # ===== 步骤2: 交换 Token =====
    if code:
        print("  --- [步骤2] 交换 Token ---")
        token_data = codex_exchange_code(code, code_verifier, "codex-web", "https://chat.openai.com/auth/callback")
        if token_data:
            return token_data

    # ===== 步骤3: 处理特殊情况（如邮箱验证）=====
    print("  --- [步骤3] 处理特殊情况 ---")
    try:
        resp = session.get(
            f"{OAUTH_ISSUER}/v1/user",
            headers=COMMON_HEADERS,
            timeout=30,
        )
        data = resp.json()
        continue_url = data.get("continue_url", "")
        page_type = data.get("page", {}).get("type", "")
        print(f"  continue_url: {continue_url}")
        print(f"  page.type: {page_type}")
    except Exception as e:
        print(f"  ❌ 获取用户信息失败: {e}")
        return None

    # ===== 步骤3.5: 邮箱验证（新注册账号首次登录时可能触发） =====
    if page_type == "email_otp_verification" or "email-verification" in continue_url:
        print("\n  --- [步骤3.5] 邮箱验证（新注册账号首次登录） ---")

        if not mail_token:
            print("  ❌ 无 mail_token，无法接收验证码")
            return None

        # 使用 core/emailing 等待验证码
        from core.emailing import wait_for_verification_email_impl
        from .codex import PROXY, FREEMAIL_WORKER_DOMAIN, FREEMAIL_TOKEN
        from .utils import USER_AGENT

        code = None
        tried_codes = set()
        start_time = time.time()

        h_val = dict(COMMON_HEADERS)
        h_val["referer"] = f"{OAUTH_ISSUER}/email-verification"
        h_val["oai-device-id"] = device_id
        h_val.update(generate_datadog_trace())

        while time.time() - start_time < 120:
            try_code = wait_for_verification_email_impl(
                None, mail_token, 10, user_agent=USER_AGENT, proxy=PROXY,
                freemail_worker_domain=FREEMAIL_WORKER_DOMAIN, freemail_token=FREEMAIL_TOKEN
            )

            if not try_code or try_code in tried_codes:
                time.sleep(2)
                continue

            tried_codes.add(try_code)
            print(f"  🔢 尝试验证码: {try_code}")
            resp = session.post(
                f"{OAUTH_ISSUER}/api/accounts/email-otp/validate",
                json={"code": try_code},
                headers=h_val, verify=False, timeout=30,
            )
            if resp.status_code == 200:
                code = try_code
                print(f"  ✅ 验证码 {code} 验证通过！")
                try:
                    data = resp.json()
                    continue_url = data.get("continue_url", "")
                    page_type = data.get("page", {}).get("type", "")
                    print(f"  continue_url: {continue_url}")
                    print(f"  page.type: {page_type}")
                except Exception:
                    pass
                break
            else:
                print(f"  ❌ 验证码 {try_code} 失败: {resp.status_code}")

        if not code:
            print("  ❌ 验证码等待超时")
            return None

        # 如果验证后进入 about-you（填写姓名生日），需要处理
        if "about-you" in continue_url:
            print("  --- [步骤3.6] 处理 about-you 页面 ---")
            try:
                resp = session.get(
                    continue_url,
                    headers=NAVIGATE_HEADERS,
                    timeout=30,
                )
                print(f"  ✅ 成功进入 about-you 页面")
            except Exception as e:
                print(f"  ❌ 进入 about-you 页面失败: {e}")
                return None

            # 这里可以选择自动填写信息并提交，或者提示用户手动填写
            # 为了安全起见，建议还是提示用户手动填写，并提供相应的说明

    return None

def codex_exchange_code(code, code_verifier, client_id, redirect_uri):
    """
    用 authorization code 换取 Codex tokens
    """
    print("  🔄 换取 Codex Token...")
    session = create_session()
    for attempt in range(2):
        try:
            resp = session.post(
                f"{OAUTH_ISSUER}/oauth/token",
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": redirect_uri,
                    "client_id": client_id,
                    "code_verifier": code_verifier,
                },
                verify=False,
                timeout=60,
            )
            break
        except Exception as e:
            if attempt == 0:
                time.sleep(2)
                continue
            print(f"  ❌ Token 交换失败: {e}")
            return None
    if resp.status_code == 200:
        data = resp.json()
        print("  ✅ Codex Token 获取成功！")
        return data
    else:
        print(f"  ❌ Token 交换失败: {resp.status_code} - {resp.text[:300]}")
        return None
