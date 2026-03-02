"""
Codex 协议工具 - Sentinel Token 生成模块
"""
import json
import time
import uuid
import random
import base64
from datetime import datetime, timezone

from .utils import USER_AGENT, generate_device_id

class SentinelTokenGenerator:
    """
    Sentinel Token 纯 Python 生成器
    """
    MAX_ATTEMPTS = 500000
    ERROR_PREFIX = "wQ8Lk5FbGpA2NcR9dShT6gYjU7VxZ4D"

    def __init__(self, device_id=None):
        self.device_id = device_id or generate_device_id()
        self.requirements_seed = str(random.random())
        self.sid = str(uuid.uuid4())

    @staticmethod
    def _fnv1a_32(text):
        h = 2166136261
        for ch in text:
            h ^= ord(ch)
            h = ((h * 16777619) & 0xFFFFFFFF)
        h ^= (h >> 16)
        h = ((h * 2246822507) & 0xFFFFFFFF)
        h ^= (h >> 13)
        h = ((h * 3266489909) & 0xFFFFFFFF)
        h ^= (h >> 16)
        h = h & 0xFFFFFFFF
        return format(h, '08x')

    def _get_config(self):
        screen_info = "1920x1080"
        now = datetime.now(timezone.utc)
        date_str = now.strftime("%a %b %d %Y %H:%M:%S GMT+0000 (Coordinated Universal Time)")
        js_heap_limit = 4294705152
        nav_random1 = random.random()
        ua = USER_AGENT
        script_src = "https://sentinel.openai.com/sentinel/20260124ceb8/sdk.js"
        language = "en-US"
        languages = "en-US,en"
        nav_random2 = random.random()
        nav_props = ["vendorSub", "productSub", "vendor", "maxTouchPoints", "hardwareConcurrency", "cookieEnabled"]
        nav_prop = random.choice(nav_props)
        nav_val = f"{nav_prop}−undefined"
        doc_key = random.choice(["location", "implementation", "URL", "documentURI", "compatMode"])
        win_key = random.choice(["Object", "Function", "Array", "Number", "parseFloat", "undefined"])
        perf_now = random.uniform(1000, 50000)
        hardware_concurrency = random.choice([4, 8, 12, 16])
        time_origin = time.time() * 1000 - perf_now
        return [screen_info, date_str, js_heap_limit, nav_random1, ua, script_src, None, None, language, languages, nav_random2, nav_val, doc_key, win_key, perf_now, self.sid, "", hardware_concurrency, time_origin]

    @staticmethod
    def _base64_encode(data):
        json_str = json.dumps(data, separators=(',', ':'), ensure_ascii=False)
        return base64.b64encode(json_str.encode('utf-8')).decode('ascii')

    def _run_check(self, start_time, seed, difficulty, config, nonce):
        config[3] = nonce
        config[9] = round((time.time() - start_time) * 1000)
        data = self._base64_encode(config)
        hash_hex = self._fnv1a_32(seed + data)
        if hash_hex[:len(difficulty)] <= difficulty:
            return data + "~S"
        return None

    def generate_token(self, seed=None, difficulty=None):
        if seed is None:
            seed = self.requirements_seed
            difficulty = difficulty or "0"
        start_time = time.time()
        config = self._get_config()
        for i in range(self.MAX_ATTEMPTS):
            result = self._run_check(start_time, seed, difficulty, config, i)
            if result:
                elapsed = time.time() - start_time
                print(f"  ✅ PoW 完成: {i+1} 次迭代, 耗时 {elapsed:.2f}s")
                return "gAAAAAB" + result
        print(f"  ⚠️ PoW 超过最大尝试次数 ({self.MAX_ATTEMPTS})")
        return "gAAAAAB" + self.ERROR_PREFIX + self._base64_encode(str(None))

    def generate_requirements_token(self):
        config = self._get_config()
        config[3] = 1
        config[9] = round(random.uniform(5, 50))
        data = self._base64_encode(config)
        return "gAAAAAC" + data

def fetch_sentinel_challenge(session, device_id, flow="authorize_continue"):
    gen = SentinelTokenGenerator(device_id=device_id)
    p_token = gen.generate_requirements_token()
    req_body = {"p": p_token, "id": device_id, "flow": flow}
    headers = {
        "Content-Type": "text/plain;charset=UTF-8",
        "Referer": "https://sentinel.openai.com/backend-api/sentinel/frame.html",
        "User-Agent": USER_AGENT,
        "Origin": "https://sentinel.openai.com",
        "sec-ch-ua": '"Not:A-Brand";v="99", "Google Chrome";v="145", "Chromium";v="145"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
    }
    try:
        resp = session.post(
            "https://sentinel.openai.com/backend-api/sentinel/req",
            data=json.dumps(req_body),
            headers=headers,
            timeout=15,
            verify=False,
        )
        if resp.status_code != 200:
            print(f"  ❌ sentinel API 返回 {resp.status_code}: {resp.text[:200]}")
            return None
        return resp.json()
    except Exception as e:
        print(f"  ❌ sentinel API 调用异常: {e}")
        return None

def build_sentinel_token(session, device_id, flow, **kwargs):
    challenge_data = fetch_sentinel_challenge(session, device_id, flow)
    if not challenge_data:
        return None
    c_value = challenge_data.get("token", "")
    pow_data = challenge_data.get("proofofwork", {})
    gen = SentinelTokenGenerator(device_id=device_id)
    if pow_data.get("required") and pow_data.get("seed"):
        p_value = gen.generate_token(seed=pow_data["seed"], difficulty=pow_data.get("difficulty", "0"))
    else:
        p_value = gen.generate_requirements_token()
    return json.dumps({"p": p_value, "t": "", "c": c_value, "id": device_id, "flow": flow})
