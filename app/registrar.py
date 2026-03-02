"""
ChatGPT 单次注册流程模块。

包含 `ChatGPTRegister` 类，负责处理与 OpenAI API 的所有交互，
包括访问主页、获取 CSRF、注册、处理 OTP、创建账户以及执行 OAuth 流程。
"""
import uuid
import random
import json

from curl_cffi import requests as curl_requests

# 延迟导入或从 core 导入，以避免循环依赖
from core.utils import random_chrome_version as _random_chrome_version_impl
from core.logger import logger

# 全局锁应从主模块或 app context 传入，此处暂时留空
# from main import _print_lock


class ChatGPTRegister:
    BASE = "https://chatgpt.com"
    AUTH = "https://auth.openai.com"

    def __init__(self, proxy: str = None, tag: str = ""):
        self.tag = tag  # 线程标识，用于日志
        self.device_id = str(uuid.uuid4())
        self.auth_session_logging_id = str(uuid.uuid4())
        self.impersonate, self.chrome_major, self.chrome_full, self.ua, self.sec_ch_ua = _random_chrome_version_impl()

        self.session = curl_requests.Session(impersonate=self.impersonate)

        self.proxy = proxy
        if self.proxy:
            self.session.proxies = {"http": self.proxy, "https": self.proxy}

        self.session.headers.update({
            "User-Agent": self.ua,
            "Accept-Language": random.choice([
                "en-US,en;q=0.9", "en-US,en;q=0.9,zh-CN;q=0.8",
                "en,en-US;q=0.9", "en-US,en;q=0.8",
            ]),
            "sec-ch-ua": self.sec_ch_ua, "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"', "sec-ch-ua-arch": '"x86"',
            "sec-ch-ua-bitness": '"64"',
            "sec-ch-ua-full-version": f'"{self.chrome_full}"',
            "sec-ch-ua-platform-version": f'"{random.randint(10, 15)}.0.0"',
        })

        self.session.cookies.set("oai-did", self.device_id, domain="chatgpt.com")
        self._callback_url = None

    def _log(self, step, method, url, status, body=None):
        logger.log_http(step, method, url, status, body, tag=self.tag)

    def _print(self, msg):
        logger.debug(msg, tag=self.tag)

    # 临时邮箱（仅使用 freemail）
    def create_temp_email(self):
        """创建临时邮箱，委托给模块级 create_temp_email（仅使用 freemail）。"""
        # 依赖顶层函数，需要从原模块导入
        from main import create_temp_email
        return create_temp_email()

    def wait_for_verification_email(self, mail_token: str, timeout: int = 120):
        """等待并提取 OpenAI 验证码，委托给模块级 wait_for_verification_email。"""
        logger.info(f"等待验证码邮件 (最多 {timeout}s)...", tag=self.tag)
        # 依赖顶层函数
        from main import wait_for_verification_email
        code = wait_for_verification_email(mail_token, timeout)
        if code:
            logger.info(f"验证码: {code}", tag=self.tag)
            return code
        logger.info(f"超时 ({timeout}s)", tag=self.tag)
        return None

    # ==================== 注册流程 ====================

    def visit_homepage(self):
        url = f"{self.BASE}/"
        r = self.session.get(url, headers={
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Upgrade-Insecure-Requests": "1",
        }, allow_redirects=True)
        self._log("0. Visit homepage", "GET", url, r.status_code,
                   {"cookies_count": len(self.session.cookies)})

    def get_csrf(self) -> str:
        url = f"{self.BASE}/api/auth/csrf"
        r = self.session.get(url, headers={"Accept": "application/json", "Referer": f"{self.BASE}/"})
        data = r.json()
        token = data.get("csrfToken", "")
        self._log("1. Get CSRF", "GET", url, r.status_code, data)
        if not token:
            raise Exception("Failed to get CSRF token")
        return token

    def signin(self, email: str, csrf: str) -> str:
        url = f"{self.BASE}/api/auth/signin/openai"
        params = {
            "prompt": "login", "ext-oai-did": self.device_id,
            "auth_session_logging_id": self.auth_session_logging_id,
            "screen_hint": "login_or_signup", "login_hint": email,
        }
        form_data = {"callbackUrl": f"{self.BASE}/", "csrfToken": csrf, "json": "true"}
        r = self.session.post(url, params=params, data=form_data, headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json", "Referer": f"{self.BASE}/", "Origin": self.BASE,
        })
        data = r.json()
        authorize_url = data.get("url", "")
        self._log("2. Signin", "POST", url, r.status_code, data)
        if not authorize_url:
            raise Exception("Failed to get authorize URL")
        return authorize_url

    def authorize(self, url: str) -> str:
        r = self.session.get(url, headers={
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Referer": f"{self.BASE}/", "Upgrade-Insecure-Requests": "1",
        }, allow_redirects=True)
        final_url = str(r.url)
        self._log("3. Authorize", "GET", url, r.status_code, {"final_url": final_url})
        return final_url

    def register(self, email: str, password: str):
        from main import _make_trace_headers
        url = f"{self.AUTH}/api/accounts/user/register"
        headers = {"Content-Type": "application/json", "Accept": "application/json",
                    "Referer": f"{self.AUTH}/create-account/password", "Origin": self.AUTH}
        headers.update(_make_trace_headers())
        r = self.session.post(url, json={"username": email, "password": password}, headers=headers)
        try: data = r.json()
        except Exception: data = {"text": r.text[:500]}
        self._log("4. Register", "POST", url, r.status_code, data)
        return r.status_code, data

    def send_otp(self):
        url = f"{self.AUTH}/api/accounts/email-otp/send"
        r = self.session.get(url, headers={
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Referer": f"{self.AUTH}/create-account/password", "Upgrade-Insecure-Requests": "1",
        }, allow_redirects=True)
        try: data = r.json()
        except Exception: data = {"final_url": str(r.url), "status": r.status_code}
        self._log("5. Send OTP", "GET", url, r.status_code, data)
        return r.status_code, data

    def validate_otp(self, code: str):
        from main import _make_trace_headers
        url = f"{self.AUTH}/api/accounts/email-otp/validate"
        headers = {"Content-Type": "application/json", "Accept": "application/json",
                    "Referer": f"{self.AUTH}/email-verification", "Origin": self.AUTH}
        headers.update(_make_trace_headers())
        r = self.session.post(url, json={"code": code}, headers=headers)
        try: data = r.json()
        except Exception: data = {"text": r.text[:500]}
        self._log("6. Validate OTP", "POST", url, r.status_code, data)
        return r.status_code, data

    def create_account(self, name: str, birthdate: str):
        from main import _make_trace_headers
        url = f"{self.AUTH}/api/accounts/create_account"
        headers = {"Content-Type": "application/json", "Accept": "application/json",
                    "Referer": f"{self.AUTH}/about-you", "Origin": self.AUTH}
        headers.update(_make_trace_headers())
        r = self.session.post(url, json={"name": name, "birthdate": birthdate}, headers=headers)
        try: data = r.json()
        except Exception: data = {"text": r.text[:500]}
        self._log("7. Create Account", "POST", url, r.status_code, data)
        if isinstance(data, dict):
            cb = data.get("continue_url") or data.get("url") or data.get("redirect_url")
            if cb:
                self._callback_url = cb
        return r.status_code, data

    def callback(self, url: str = None):
        if not url:
            url = self._callback_url
        if not url:
            self._print("[!] No callback URL, skipping.")
            return None, None
        r = self.session.get(url, headers={
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Upgrade-Insecure-Requests": "1",
        }, allow_redirects=True)
        self._log("8. Callback", "GET", url, r.status_code, {"final_url": str(r.url)})
        return r.status_code, {"final_url": str(r.url)}

    # ==================== 自动注册主流程 ====================

    def run_register(self, email, password, name, birthdate, mail_token):
        from urllib.parse import urlparse
        from main import _random_delay
        """使用 freemail 的注册流程"""
        self.visit_homepage()
        _random_delay(0.3, 0.8)
        csrf = self.get_csrf()
        _random_delay(0.2, 0.5)
        auth_url = self.signin(email, csrf)
        _random_delay(0.3, 0.8)

        final_url = self.authorize(auth_url)
        final_path = urlparse(final_url).path
        _random_delay(0.3, 0.8)

        logger.info(f"Authorize → {final_path}", tag=self.tag)

        need_otp = False

        if "create-account/password" in final_path:
            logger.info("全新注册流程", tag=self.tag)
            _random_delay(0.5, 1.0)
            status, data = self.register(email, password)
            if status != 200:
                raise Exception(f"Register 失败 ({status}): {data}")
            # register 之后可能还需要 send_otp（全新注册流程中 OTP 不一定在 authorize 时发送）
            _random_delay(0.3, 0.8)
            self.send_otp()
            need_otp = True
        elif "email-verification" in final_path or "email-otp" in final_path:
            logger.info("跳到 OTP 验证阶段 (authorize 已触发 OTP，不再重复发送)", tag=self.tag)
            # 不调用 send_otp()，因为 authorize 重定向到 email-verification 时服务器已发送 OTP
            need_otp = True
        elif "about-you" in final_path:
            logger.info("跳到填写信息阶段", tag=self.tag)
            _random_delay(0.5, 1.0)
            self.create_account(name, birthdate)
            _random_delay(0.3, 0.5)
            self.callback()
            return True
        elif "callback" in final_path or "chatgpt.com" in final_url:
            logger.info("账号已完成注册", tag=self.tag)
            return True
        else:
            logger.info(f"未知跳转: {final_url}", tag=self.tag)
            self.register(email, password)
            self.send_otp()
            need_otp = True

        if need_otp:
            # 使用 freemail 等待验证码
            otp_code = self.wait_for_verification_email(mail_token)
            if not otp_code:
                raise Exception("未能获取验证码")

            _random_delay(0.3, 0.8)
            status, data = self.validate_otp(otp_code)
            if status != 200:
                logger.info("验证码失败，重试...", tag=self.tag)
                self.send_otp()
                _random_delay(1.0, 2.0)
                otp_code = self.wait_for_verification_email(mail_token, timeout=60)
                if not otp_code:
                    raise Exception("重试后仍未获取验证码")
                _random_delay(0.3, 0.8)
                status, data = self.validate_otp(otp_code)
                if status != 200:
                    raise Exception(f"验证码失败 ({status}): {data}")

        _random_delay(0.5, 1.5)
        status, data = self.create_account(name, birthdate)
        if status != 200:
            raise Exception(f"Create account 失败 ({status}): {data}")
        _random_delay(0.2, 0.5)
        self.callback()
        return True

    def _decode_oauth_session_cookie(self):
        import base64
        jar = getattr(self.session.cookies, "jar", None)
        if jar is not None:
            cookie_items = list(jar)
        else:
            cookie_items = []

        for c in cookie_items:
            name = getattr(c, "name", "") or ""
            if "oai-client-auth-session" not in name:
                continue

            raw_val = (getattr(c, "value", "") or "").strip()
            if not raw_val:
                continue

            candidates = [raw_val]
            try:
                from urllib.parse import unquote

                decoded = unquote(raw_val)
                if decoded != raw_val:
                    candidates.append(decoded)
            except Exception:
                pass

            for val in candidates:
                try:
                    if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
                        val = val[1:-1]

                    part = val.split(".")[0] if "." in val else val
                    pad = 4 - len(part) % 4
                    if pad != 4:
                        part += "=" * pad
                    raw = base64.urlsafe_b64decode(part)
                    data = json.loads(raw.decode("utf-8"))
                    if isinstance(data, dict):
                        return data
                except Exception:
                    continue
        return None

    def _oauth_allow_redirect_extract_code(self, url: str, referer: str = None):
        from main import _extract_code_from_url
        import re
        headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Upgrade-Insecure-Requests": "1",
            "User-Agent": self.ua,
        }
        if referer:
            headers["Referer"] = referer

        try:
            resp = self.session.get(
                url,
                headers=headers,
                allow_redirects=True,
                timeout=30,
                impersonate=self.impersonate,
            )
            final_url = str(resp.url)
            code = _extract_code_from_url(final_url)
            if code:
                logger.debug("allow_redirect 命中最终 URL code", tag="OAuth")
                return code

            for r in getattr(resp, "history", []) or []:
                loc = r.headers.get("Location", "")
                code = _extract_code_from_url(loc)
                if code:
                    logger.debug("allow_redirect 命中 history Location code", tag="OAuth")
                    return code
                code = _extract_code_from_url(str(r.url))
                if code:
                    logger.debug("allow_redirect 命中 history URL code", tag="OAuth")
                    return code
        except Exception as e:
            maybe_localhost = re.search(r'(https?://localhost[^\s\'\"]+)', str(e))
            if maybe_localhost:
                code = _extract_code_from_url(maybe_localhost.group(1))
                if code:
                    logger.debug("allow_redirect 从 localhost 异常提取 code", tag="OAuth")
                    return code
            logger.debug(f"allow_redirect 异常: {e}", tag="OAuth")

        return None

    def _oauth_follow_for_code(self, start_url: str, referer: str = None, max_hops: int = 16):
        from main import _extract_code_from_url, OAUTH_ISSUER
        import re
        headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Upgrade-Insecure-Requests": "1",
            "User-Agent": self.ua,
        }
        if referer:
            headers["Referer"] = referer

        current_url = start_url
        last_url = start_url

        for hop in range(max_hops):
            try:
                resp = self.session.get(
                    current_url,
                    headers=headers,
                    allow_redirects=False,
                    timeout=30,
                    impersonate=self.impersonate,
                )
            except Exception as e:
                maybe_localhost = re.search(r'(https?://localhost[^\s\'\"]+)', str(e))
                if maybe_localhost:
                    code = _extract_code_from_url(maybe_localhost.group(1))
                    if code:
                        logger.debug(f"follow[{hop + 1}] 命中 localhost 回调", tag="OAuth")
                        return code, maybe_localhost.group(1)
                logger.debug(f"follow[{hop + 1}] 请求异常: {e}", tag="OAuth")
                return None, last_url

            last_url = str(resp.url)
            logger.debug(f"follow[{hop + 1}] {resp.status_code} {last_url[:140]}", tag="OAuth")
            code = _extract_code_from_url(last_url)
            if code:
                return code, last_url

            if resp.status_code in (301, 302, 303, 307, 308):
                loc = resp.headers.get("Location", "")
                if not loc:
                    return None, last_url
                if loc.startswith("/"):
                    loc = f"{OAUTH_ISSUER}{loc}"
                code = _extract_code_from_url(loc)
                if code:
                    return code, loc
                current_url = loc
                headers["Referer"] = last_url
                continue

            return None, last_url

        return None, last_url

    def _oauth_submit_workspace_and_org(self, consent_url: str):
        from main import _extract_code_from_url, OAUTH_ISSUER, _make_trace_headers
        session_data = self._decode_oauth_session_cookie()
        if not session_data:
            jar = getattr(self.session.cookies, "jar", None)
            if jar is not None:
                cookie_names = [getattr(c, "name", "") for c in list(jar)]
            else:
                cookie_names = list(self.session.cookies.keys())
            logger.debug(f"无法解码 oai-client-auth-session, cookies={cookie_names[:12]}", tag="OAuth")
            return None

        workspaces = session_data.get("workspaces", [])
        if not workspaces:
            logger.debug("session 中没有 workspace 信息", tag="OAuth")
            return None

        workspace_id = (workspaces[0] or {}).get("id")
        if not workspace_id:
            logger.debug("workspace_id 为空", tag="OAuth")
            return None

        h = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Origin": OAUTH_ISSUER,
            "Referer": consent_url,
            "User-Agent": self.ua,
            "oai-device-id": self.device_id,
        }
        h.update(_make_trace_headers())

        resp = self.session.post(
            f"{OAUTH_ISSUER}/api/accounts/workspace/select",
            json={"workspace_id": workspace_id},
            headers=h,
            allow_redirects=False,
            timeout=30,
            impersonate=self.impersonate,
        )
        logger.debug(f"workspace/select -> {resp.status_code}", tag="OAuth")

        if resp.status_code in (301, 302, 303, 307, 308):
            loc = resp.headers.get("Location", "")
            if loc.startswith("/"):
                loc = f"{OAUTH_ISSUER}{loc}"
            code = _extract_code_from_url(loc)
            if code:
                return code
            code, _ = self._oauth_follow_for_code(loc, referer=consent_url)
            if not code:
                code = self._oauth_allow_redirect_extract_code(loc, referer=consent_url)
            return code

        if resp.status_code != 200:
            logger.debug(f"workspace/select 失败: {resp.status_code}", tag="OAuth")
            return None

        try:
            ws_data = resp.json()
        except Exception:
            logger.debug("workspace/select 响应不是 JSON", tag="OAuth")
            return None

        ws_next = ws_data.get("continue_url", "")
        orgs = ws_data.get("data", {}).get("orgs", [])
        ws_page = (ws_data.get("page") or {}).get("type", "")
        logger.debug(f"workspace/select page={ws_page or '-'} next={(ws_next or '-')[:140]}", tag="OAuth")

        org_id = None
        project_id = None
        if orgs:
            org_id = (orgs[0] or {}).get("id")
            projects = (orgs[0] or {}).get("projects", [])
            if projects:
                project_id = (projects[0] or {}).get("id")

        if org_id:
            org_body = {"org_id": org_id}
            if project_id:
                org_body["project_id"] = project_id

            h_org = dict(h)
            if ws_next:
                h_org["Referer"] = ws_next if ws_next.startswith("http") else f"{OAUTH_ISSUER}{ws_next}"

            resp_org = self.session.post(
                f"{OAUTH_ISSUER}/api/accounts/organization/select",
                json=org_body,
                headers=h_org,
                allow_redirects=False,
                timeout=30,
                impersonate=self.impersonate,
            )
            logger.debug(f"organization/select -> {resp_org.status_code}", tag="OAuth")
            if resp_org.status_code in (301, 302, 303, 307, 308):
                loc = resp_org.headers.get("Location", "")
                if loc.startswith("/"):
                    loc = f"{OAUTH_ISSUER}{loc}"
                code = _extract_code_from_url(loc)
                if code:
                    return code
                code, _ = self._oauth_follow_for_code(loc, referer=h_org.get("Referer"))
                if not code:
                    code = self._oauth_allow_redirect_extract_code(loc, referer=h_org.get("Referer"))
                return code

            if resp_org.status_code == 200:
                try:
                    org_data = resp_org.json()
                except Exception:
                    logger.debug("organization/select 响应不是 JSON", tag="OAuth")
                    return None

                org_next = org_data.get("continue_url", "")
                org_page = (org_data.get("page") or {}).get("type", "")
                logger.debug(f"organization/select page={org_page or '-'} next={(org_next or '-')[:140]}", tag="OAuth")
                if org_next:
                    if org_next.startswith("/"):
                        org_next = f"{OAUTH_ISSUER}{org_next}"
                    code, _ = self._oauth_follow_for_code(org_next, referer=h_org.get("Referer"))
                    if not code:
                        code = self._oauth_allow_redirect_extract_code(org_next, referer=h_org.get("Referer"))
                    return code

        if ws_next:
            if ws_next.startswith("/"):
                ws_next = f"{OAUTH_ISSUER}{ws_next}"
            code, _ = self._oauth_follow_for_code(ws_next, referer=consent_url)
            if not code:
                code = self._oauth_allow_redirect_extract_code(ws_next, referer=consent_url)
            return code

        return None

    def perform_codex_oauth_login_http(self, email: str, password: str, mail_token: str = None):
        from main import (_generate_pkce, OAUTH_CLIENT_ID, OAUTH_REDIRECT_URI, OAUTH_ISSUER,
                                      _make_trace_headers, build_sentinel_token, _wait_for_verification_email_impl,
                                      FREEMAIL_WORKER_DOMAIN, FREEMAIL_TOKEN, _extract_code_from_url)
        import secrets
        import time
        from urllib.parse import urlencode
        logger.info("开始执行 Codex OAuth 纯协议流程...", tag=self.tag)

        # 兼容两种 domain 形式，确保 auth 域也带 oai-did
        self.session.cookies.set("oai-did", self.device_id, domain=".auth.openai.com")
        self.session.cookies.set("oai-did", self.device_id, domain="auth.openai.com")

        code_verifier, code_challenge = _generate_pkce()
        state = secrets.token_urlsafe(24)

        authorize_params = {
            "response_type": "code",
            "client_id": OAUTH_CLIENT_ID,
            "redirect_uri": OAUTH_REDIRECT_URI,
            "scope": "openid profile email offline_access",
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "state": state,
        }
        authorize_url = f"{OAUTH_ISSUER}/oauth/authorize?{urlencode(authorize_params)}"

        def _oauth_json_headers(referer: str):
            h = {
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Origin": OAUTH_ISSUER,
                "Referer": referer,
                "User-Agent": self.ua,
                "oai-device-id": self.device_id,
            }
            h.update(_make_trace_headers())
            return h

        def _bootstrap_oauth_session():
            logger.debug("1/7 GET /oauth/authorize", tag="OAuth")
            try:
                r = self.session.get(
                    authorize_url,
                    headers={
                        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                        "Referer": f"{self.BASE}/",
                        "Upgrade-Insecure-Requests": "1",
                        "User-Agent": self.ua,
                    },
                    allow_redirects=True,
                    timeout=30,
                    impersonate=self.impersonate,
                )
            except Exception as e:
                logger.debug(f"/oauth/authorize 异常: {e}", tag="OAuth")
                return False, ""

            final_url = str(r.url)
            redirects = len(getattr(r, "history", []) or [])
            logger.debug(f"/oauth/authorize -> {r.status_code}, final={(final_url or '-')[:140]}, redirects={redirects}", tag="OAuth")

            has_login = any(getattr(c, "name", "") == "login_session" for c in self.session.cookies)
            logger.debug(f"login_session: {'已获取' if has_login else '未获取'}", tag="OAuth")

            if not has_login:
                logger.debug("未拿到 login_session，尝试访问 oauth2 auth 入口", tag="OAuth")
                oauth2_url = f"{OAUTH_ISSUER}/api/oauth/oauth2/auth"
                try:
                    r2 = self.session.get(
                        oauth2_url,
                        headers={
                            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                            "Referer": authorize_url,
                            "Upgrade-Insecure-Requests": "1",
                            "User-Agent": self.ua,
                        },
                        params=authorize_params,
                        allow_redirects=True,
                        timeout=30,
                        impersonate=self.impersonate,
                    )
                    final_url = str(r2.url)
                    redirects2 = len(getattr(r2, "history", []) or [])
                    logger.debug(f"/api/oauth/oauth2/auth -> {r2.status_code}, final={(final_url or '-')[:140]}, redirects={redirects2}", tag="OAuth")
                except Exception as e:
                    logger.debug(f"/api/oauth/oauth2/auth 异常: {e}", tag="OAuth")

                has_login = any(getattr(c, "name", "") == "login_session" for c in self.session.cookies)
                logger.debug(f"login_session(重试): {'已获取' if has_login else '未获取'}", tag="OAuth")

            return has_login, final_url

        def _post_authorize_continue(referer_url: str):
            sentinel_authorize = build_sentinel_token(
                self.session,
                self.device_id,
                flow="authorize_continue",
                user_agent=self.ua,
                sec_ch_ua=self.sec_ch_ua,
                impersonate=self.impersonate,
            )
            if not sentinel_authorize:
                logger.debug("authorize_continue 的 sentinel token 获取失败", tag="OAuth")
                return None

            headers_continue = _oauth_json_headers(referer_url)
            headers_continue["openai-sentinel-token"] = sentinel_authorize

            try:
                return self.session.post(
                    f"{OAUTH_ISSUER}/api/accounts/authorize/continue",
                    json={"username": {"kind": "email", "value": email}},
                    headers=headers_continue,
                    timeout=30,
                    allow_redirects=False,
                    impersonate=self.impersonate,
                )
            except Exception as e:
                logger.debug(f"authorize/continue 异常: {e}", tag="OAuth")
                return None

        has_login_session, authorize_final_url = _bootstrap_oauth_session()
        if not authorize_final_url:
            return None

        continue_referer = authorize_final_url if authorize_final_url.startswith(OAUTH_ISSUER) else f"{OAUTH_ISSUER}/log-in"

        logger.debug("2/7 POST /api/accounts/authorize/continue", tag="OAuth")
        resp_continue = _post_authorize_continue(continue_referer)
        if resp_continue is None:
            return None

        logger.debug(f"/authorize/continue -> {resp_continue.status_code}", tag="OAuth")
        if resp_continue.status_code == 400 and "invalid_auth_step" in (resp_continue.text or ""):
            logger.debug("invalid_auth_step，重新 bootstrap 后重试一次", tag="OAuth")
            has_login_session, authorize_final_url = _bootstrap_oauth_session()
            if not authorize_final_url:
                return None
            continue_referer = authorize_final_url if authorize_final_url.startswith(OAUTH_ISSUER) else f"{OAUTH_ISSUER}/log-in"
            resp_continue = _post_authorize_continue(continue_referer)
            if resp_continue is None:
                return None
            logger.debug(f"/authorize/continue(重试) -> {resp_continue.status_code}", tag="OAuth")

        if resp_continue.status_code != 200:
            logger.debug(f"邮箱提交失败: {resp_continue.text[:180]}", tag="OAuth")
            return None

        try:
            continue_data = resp_continue.json()
        except Exception:
            logger.debug("authorize/continue 响应解析失败", tag="OAuth")
            return None

        continue_url = continue_data.get("continue_url", "")
        page_type = (continue_data.get("page") or {}).get("type", "")
        logger.debug(f"continue page={page_type or '-'} next={(continue_url or '-')[:140]}", tag="OAuth")

        logger.debug("3/7 POST /api/accounts/password/verify", tag="OAuth")
        sentinel_pwd = build_sentinel_token(
            self.session,
            self.device_id,
            flow="password_verify",
            user_agent=self.ua,
            sec_ch_ua=self.sec_ch_ua,
            impersonate=self.impersonate,
        )
        if not sentinel_pwd:
            logger.debug("password_verify 的 sentinel token 获取失败", tag="OAuth")
            return None

        headers_verify = _oauth_json_headers(f"{OAUTH_ISSUER}/log-in/password")
        headers_verify["openai-sentinel-token"] = sentinel_pwd

        try:
            resp_verify = self.session.post(
                f"{OAUTH_ISSUER}/api/accounts/password/verify",
                json={"password": password},
                headers=headers_verify,
                timeout=30,
                allow_redirects=False,
                impersonate=self.impersonate,
            )
        except Exception as e:
            logger.debug(f"password/verify 异常: {e}", tag="OAuth")
            return None

        logger.debug(f"/password/verify -> {resp_verify.status_code}", tag="OAuth")
        if resp_verify.status_code != 200:
            logger.debug(f"密码校验失败: {resp_verify.text[:180]}", tag="OAuth")
            return None

        try:
            verify_data = resp_verify.json()
        except Exception:
            logger.debug("password/verify 响应解析失败", tag="OAuth")
            return None

        continue_url = verify_data.get("continue_url", "") or continue_url
        page_type = (verify_data.get("page") or {}).get("type", "") or page_type
        logger.debug(f"verify page={page_type or '-'} next={(continue_url or '-')[:140]}", tag="OAuth")

        need_oauth_otp = (
            page_type == "email_otp_verification"
            or "email-verification" in (continue_url or "")
            or "email-otp" in (continue_url or "")
        )

        if need_oauth_otp:
            logger.debug("4/7 检测到邮箱 OTP 验证", tag="OAuth")
            if not mail_token:
                logger.debug("OAuth 阶段需要邮箱 OTP，但未提供 mail_token", tag="OAuth")
                return None

            headers_otp = _oauth_json_headers(f"{OAUTH_ISSUER}/email-verification")
            tried_codes = set()
            otp_success = False
            otp_deadline = time.time() + 120

            # 使用 freemail worker 轮询验证码（不再逐条读取 DuckMail 邮件）
            while time.time() < otp_deadline and not otp_success:
                remaining = max(1, int(otp_deadline - time.time()))
                # 等待最多 10 秒或剩余时间来获取单条验证码
                try:
                    code = _wait_for_verification_email_impl(
                        None, mail_token, timeout=min(10, remaining), user_agent=None,
                        proxy=self.proxy, freemail_worker_domain=FREEMAIL_WORKER_DOMAIN, freemail_token=FREEMAIL_TOKEN
                    )
                except Exception as e:
                    logger.debug(f"等待验证码时出错: {e}", tag="OAuth")
                    code = None

                if not code:
                    elapsed = int(120 - max(0, otp_deadline - time.time()))
                    logger.debug(f"OTP 等待中... ({elapsed}s/120s)", tag="OAuth")
                    time.sleep(2)
                    continue

                if code in tried_codes:
                    continue

                tried_codes.add(code)
                logger.debug(f"尝试 OTP: {code}", tag="OAuth")
                try:
                    resp_otp = self.session.post(
                        f"{OAUTH_ISSUER}/api/accounts/email-otp/validate",
                        json={"code": code},
                        headers=headers_otp,
                        timeout=30,
                        allow_redirects=False,
                        impersonate=self.impersonate,
                    )
                except Exception as e:
                    logger.debug(f"email-otp/validate 异常: {e}", tag="OAuth")
                    continue

                logger.debug(f"/email-otp/validate -> {resp_otp.status_code}", tag="OAuth")
                if resp_otp.status_code != 200:
                    logger.debug(f"OTP 无效，继续尝试下一条: {resp_otp.text[:160]}", tag="OAuth")
                    continue

                try:
                    otp_data = resp_otp.json()
                except Exception:
                    logger.debug("email-otp/validate 响应解析失败", tag="OAuth")
                    continue

                continue_url = otp_data.get("continue_url", "") or continue_url
                page_type = (otp_data.get("page") or {}).get("type", "") or page_type
                logger.debug(f"OTP 验证通过 page={page_type or '-'} next={(continue_url or '-')[:140]}", tag="OAuth")
                otp_success = True
                break

            if not otp_success:
                logger.debug(f"OAuth 阶段 OTP 验证失败，已尝试 {len(tried_codes)} 个验证码", tag="OAuth")
                return None

        code = None
        consent_url = continue_url
        if consent_url and consent_url.startswith("/"):
            consent_url = f"{OAUTH_ISSUER}{consent_url}"

        if not consent_url and "consent" in page_type:
            consent_url = f"{OAUTH_ISSUER}/sign-in-with-chatgpt/codex/consent"

        if consent_url:
            code = _extract_code_from_url(consent_url)

        if not code and consent_url:
            logger.debug("5/7 跟随 continue_url 提取 code", tag="OAuth")
            code, _ = self._oauth_follow_for_code(consent_url, referer=f"{OAUTH_ISSUER}/log-in/password")

        consent_hint = (
            ("consent" in (consent_url or ""))
            or ("sign-in-with-chatgpt" in (consent_url or ""))
            or ("workspace" in (consent_url or ""))
            or ("organization" in (consent_url or ""))
            or ("consent" in page_type)
            or ("organization" in page_type)
        )

        if not code and consent_hint:
            if not consent_url:
                consent_url = f"{OAUTH_ISSUER}/sign-in-with-chatgpt/codex/consent"
            logger.debug("6/7 执行 workspace/org 选择", tag="OAuth")
            code = self._oauth_submit_workspace_and_org(consent_url)

        if not code:
            fallback_consent = f"{OAUTH_ISSUER}/sign-in-with-chatgpt/codex/consent"
            logger.debug("6/7 回退 consent 路径重试", tag="OAuth")
            code = self._oauth_submit_workspace_and_org(fallback_consent)
            if not code:
                code, _ = self._oauth_follow_for_code(fallback_consent, referer=f"{OAUTH_ISSUER}/log-in/password")

        if not code:
            logger.debug("未获取到 authorization code", tag="OAuth")
            return None

        logger.debug("7/7 POST /oauth/token", tag="OAuth")
        token_resp = self.session.post(
            f"{OAUTH_ISSUER}/oauth/token",
            headers={"Content-Type": "application/x-www-form-urlencoded", "User-Agent": self.ua},
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": OAUTH_REDIRECT_URI,
                "client_id": OAUTH_CLIENT_ID,
                "code_verifier": code_verifier,
            },
            timeout=60,
            impersonate=self.impersonate,
        )
        logger.debug(f"/oauth/token -> {token_resp.status_code}", tag="OAuth")

        if token_resp.status_code != 200:
            logger.debug(f"token 交换失败: {token_resp.status_code} {token_resp.text[:200]}", tag="OAuth")
            return None

        try:
            data = token_resp.json()
        except Exception:
            logger.debug("token 响应解析失败", tag="OAuth")
            return None

        if not data.get("access_token"):
            logger.debug("token 响应缺少 access_token", tag="OAuth")
            return None

        logger.info("Codex Token 获取成功", tag=self.tag)
        return data
