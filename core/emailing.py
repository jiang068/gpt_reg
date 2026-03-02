import os
import re
import time
import uuid
from typing import Optional, Tuple

import requests


class EmailService:
    """Minimal, robust freemail client."""

    def __init__(self, proxies=None):
        worker_domain = (os.getenv("WORKER_DOMAIN") or "").strip().rstrip("/")
        token = (os.getenv("FREEMAIL_TOKEN") or "").strip()
        if not worker_domain or not token:
            raise ValueError("Missing freemail config: WORKER_DOMAIN and FREEMAIL_TOKEN must be set.")

        self.base_url = f"https://{worker_domain}"
        self.headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
        self.proxies = proxies or {}

    def create_email(self) -> Tuple[str, str]:
        try:
            resp = requests.get(f"{self.base_url}/api/generate", headers=self.headers, proxies=self.proxies, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                email = data.get("email") or data.get("address")
                if email:
                    return email, email
        except Exception:
            pass

        username = uuid.uuid4().hex[:8]
        try:
            resp = requests.post(f"{self.base_url}/mailbox", json={"name": username}, headers=self.headers, proxies=self.proxies, timeout=10)
            if resp.status_code in (200, 201):
                data = resp.json()
                email = data.get("email") or data.get("address") or data.get("name")
                mailbox = data.get("mailbox") or data.get("id") or (email or username)
                if email:
                    return email, mailbox
        except Exception:
            pass
        return "", ""

    def fetch_verification_code(self, mailbox: str, max_attempts: int = 1, debug: bool = False) -> Optional[str]:
        if debug:
            print(f"[EmailService] Polling for code, mailbox={mailbox}, attempts={max_attempts}")
        for attempt in range(max_attempts):
            if attempt > 0:
                time.sleep(1)
            try:
                # 只保留 /api/emails 这一种方式
                resp = requests.get(f"{self.base_url}/api/emails", params={"mailbox": mailbox}, headers=self.headers, proxies=self.proxies, timeout=10)
                if resp.status_code == 200:
                    items = resp.json()
                    if items:
                        first = items[0]
                        code = first.get("verification_code") or first.get("code") or first.get("verify_code")
                        if code:
                            return str(code).replace('-', '')
                        subject = first.get("subject", "")
                        m = re.search(r'\b([A-Z0-9]{2,4}-[A-Z0-9]{2,4})\b', subject)
                        if m:
                            return m.group(1).replace('-', '')
            except Exception:
                pass
        return None

    def delete_mailbox(self, email: str) -> None:
        try:
            mailbox = email.split("@")[0] if "@" in email else email
            requests.delete(f"{self.base_url}/mailbox/{mailbox}", headers=self.headers, proxies=self.proxies, timeout=6)
        except Exception:
            pass


def create_temp_email(duckmail_api_base, duckmail_bearer, default_proxy, freemail_worker_domain, freemail_token, user_agent=None):
    os.environ["WORKER_DOMAIN"] = freemail_worker_domain
    os.environ["FREEMAIL_TOKEN"] = freemail_token
    proxies = {"http": default_proxy, "https": default_proxy} if default_proxy else None
    service = EmailService(proxies=proxies)
    return service.create_email()


def wait_for_verification_email(duckmail_api_base, mail_token, timeout=120, user_agent=None, proxy=None, freemail_worker_domain=None, freemail_token=None):
    os.environ["WORKER_DOMAIN"] = freemail_worker_domain
    os.environ["FREEMAIL_TOKEN"] = freemail_token
    proxies = {"http": proxy, "https": proxy} if proxy else None
    service = EmailService(proxies=proxies)
    
    start_time = time.time()
    while time.time() - start_time < timeout:
        code = service.fetch_verification_code(mail_token, max_attempts=1)
        if code:
            return code
        time.sleep(2)
    return None


def delete_temp_email(mail_token: str, freemail_worker_domain: str, freemail_token: str, proxy: str = None):
    if not mail_token or not freemail_worker_domain or not freemail_token:
        return
    os.environ["WORKER_DOMAIN"] = freemail_worker_domain
    os.environ["FREEMAIL_TOKEN"] = freemail_token
    proxies = {"http": proxy, "https": proxy} if proxy else None
    service = EmailService(proxies=proxies)
    service.delete_mailbox(mail_token)
