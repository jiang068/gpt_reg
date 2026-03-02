"""
Codex 协议工具 - 纯协议注册模块
"""
import time
from .utils import (
    create_session,
    generate_device_id,
    generate_random_name,
    generate_random_birthday,
    COMMON_HEADERS,
    NAVIGATE_HEADERS,
    OPENAI_AUTH_BASE,
    generate_datadog_trace,
)
from core.utils import generate_pkce
from .sentinel import SentinelTokenGenerator, build_sentinel_token
from core.emailing import wait_for_verification_email as wait_for_verification_code

class ProtocolRegistrar:
    """
    协议注册机核心类 v3 — 纯 HTTP 实现
    """
    def __init__(self):
        self.session = create_session()
        self.device_id = generate_device_id()
        self.sentinel_gen = SentinelTokenGenerator(device_id=self.device_id)
        self.code_verifier = None
        self.state = None

    def _build_headers(self, referer, with_sentinel=False):
        headers = dict(COMMON_HEADERS)
        headers["referer"] = referer
        headers["oai-device-id"] = self.device_id
        headers.update(generate_datadog_trace())
        if with_sentinel:
            token = self.sentinel_gen.generate_token()
            headers["openai-sentinel-token"] = token
        return headers

    def step0_init_oauth_session(self, email, client_id, redirect_uri):
        from urllib.parse import urlencode
        import secrets
        print("\n🔗 [步骤0] OAuth 会话初始化 + 邮箱提交")
        self.session.cookies.set("oai-did", self.device_id, domain=".auth.openai.com")
        self.session.cookies.set("oai-did", self.device_id, domain="auth.openai.com")
        code_verifier, code_challenge = generate_pkce()
        self.code_verifier = code_verifier
        self.state = secrets.token_urlsafe(32)
        authorize_params = {
            "response_type": "code", "client_id": client_id, "redirect_uri": redirect_uri,
            "scope": "openid profile email offline_access", "code_challenge": code_challenge,
            "code_challenge_method": "S256", "state": self.state, "screen_hint": "signup", "prompt": "login",
        }
        authorize_url = f"{OPENAI_AUTH_BASE}/oauth/authorize?{urlencode(authorize_params)}"
        try:
            resp = self.session.get(authorize_url, headers=NAVIGATE_HEADERS, allow_redirects=True, verify=False, timeout=30)
            print(f"  步骤0a: {resp.status_code}")
        except Exception as e:
            print(f"  ❌ OAuth 授权请求失败: {e}")
            return False
        if not any(c.name == "login_session" for c in self.session.cookies):
            print("  ⚠️ 未获得 login_session cookie")
            return False
        headers = dict(COMMON_HEADERS)
        headers["referer"] = f"{OPENAI_AUTH_BASE}/create-account"
        headers["oai-device-id"] = self.device_id
        headers.update(generate_datadog_trace())
        sentinel_token = build_sentinel_token(self.session, self.device_id, flow="authorize_continue")
        if not sentinel_token:
            print("  ❌ 无法获取 authorize_continue 的 sentinel token")
            return False
        headers["openai-sentinel-token"] = sentinel_token
        try:
            resp = self.session.post(
                f"{OPENAI_AUTH_BASE}/api/accounts/authorize/continue",
                json={"username": {"kind": "email", "value": email}, "screen_hint": "signup"},
                headers=headers, verify=False, timeout=30,
            )
        except Exception as e:
            print(f"  ❌ 邮箱提交失败: {e}")
            return False
        if resp.status_code != 200:
            print(f"  ❌ 邮箱提交失败: HTTP {resp.status_code}")
            return False
        return True

    def step2_register_user(self, email, password):
        print(f"\n🔑 [步骤2-HTTP] 注册用户: {email}")
        url = f"{OPENAI_AUTH_BASE}/api/accounts/user/register"
        headers = self._build_headers(referer=f"{OPENAI_AUTH_BASE}/create-account/password", with_sentinel=True)
        payload = {"username": email, "password": password}
        resp = self.session.post(url, json=payload, headers=headers, verify=False, timeout=30)
        if resp.status_code == 200:
            print("  ✅ 注册成功")
            return True
        else:
            print(f"  ❌ 失败: {resp.text[:300]}")
            if resp.status_code in (301, 302):
                redirect_url = resp.headers.get('Location', '')
                if 'email-otp' in redirect_url or 'email-verification' in redirect_url:
                    return True
            return False

    def step3_send_otp(self):
        print("\n📬 [步骤3-HTTP] 触发验证码发送")
        url_send = f"{OPENAI_AUTH_BASE}/api/accounts/email-otp/send"
        headers = dict(NAVIGATE_HEADERS)
        headers["referer"] = f"{OPENAI_AUTH_BASE}/create-account/password"
        self.session.get(url_send, headers=headers, verify=False, timeout=30, allow_redirects=True)
        url_verify = f"{OPENAI_AUTH_BASE}/email-verification"
        self.session.get(url_verify, headers=headers, verify=False, timeout=30, allow_redirects=True)
        print(f"  ✅ 验证码发送触发完成")
        return True

    def step4_validate_otp(self, code):
        print(f"\n🔢 [步骤4-HTTP] 验证邮箱 OTP: {code}")
        url = f"{OPENAI_AUTH_BASE}/api/accounts/email-otp/validate"
        headers = self._build_headers(referer=f"{OPENAI_AUTH_BASE}/email-verification")
        payload = {"code": code}
        resp = self.session.post(url, json=payload, headers=headers, verify=False, timeout=30)
        if resp.status_code == 200:
            print("  ✅ 邮箱验证成功")
            return True
        else:
            print(f"  ❌ 失败: {resp.text[:300]}")
            return False

    def step5_create_account(self, first_name, last_name, birthdate):
        print(f"\n📝 [步骤5-HTTP] 创建账号（{first_name} {last_name}, {birthdate}）")
        url = f"{OPENAI_AUTH_BASE}/api/accounts/create_account"
        headers = self._build_headers(referer=f"{OPENAI_AUTH_BASE}/about-you")
        payload = {"name": f"{first_name} {last_name}", "birthdate": birthdate}
        resp = self.session.post(url, json=payload, headers=headers, verify=False, timeout=30)
        if resp.status_code == 200:
            print("  ✅ 账号创建完成！")
            return True
        elif resp.status_code == 403 and "sentinel" in resp.text.lower():
            headers["openai-sentinel-token"] = self.sentinel_gen.generate_token()
            resp = self.session.post(url, json=payload, headers=headers, verify=False, timeout=30)
            if resp.status_code == 200:
                return True
        return False

    def register(self, email, password, wait_for_code_func):
        """
        执行完整的注册流程（全 6 步纯 HTTP）
        """
        first_name, last_name = generate_random_name()
        birthdate = generate_random_birthday()
        print(f"\n🚀 注册: {email}")
        try:
            if not self.step0_init_oauth_session(email, password, wait_for_code_func): return False, email, password
            time.sleep(1)
            if not self.step2_register_user(email, password): return False, email, password
            time.sleep(1)
            self.step3_send_otp()

            # 等待验证码
            code = wait_for_code_func()
            if not code:
                print("❌ 未收到验证码")
                return False, email, password
            if not self.step4_validate_otp(code): return False, email, password
            time.sleep(1)
            if not self.step5_create_account(first_name, last_name, birthdate): return False, email, password
            print("\n🎉 注册成功！")
            return True, email, password
        except Exception as e:
            print(f"\n❌ 注册异常: {e}")
            return False, email, password
