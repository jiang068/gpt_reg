"""
CPA 面板上传工具

该脚本会扫描 `output/` 目录下的所有任务文件夹，
解析其中 `codex_tokens/` 子目录下的所有 .json 文件，
并将它们上传到在 `config.json` 中指定的 CPA 面板。
"""
import os
import json
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import time

from core.config import _load_config
from core.logger import logger

# 加载配置
BASE_PATH = os.path.dirname(os.path.abspath(__file__))
_CONFIG = _load_config(BASE_PATH)

UPLOAD_API_URL = _CONFIG.get("upload_api_url", "")
UPLOAD_API_TOKEN = _CONFIG.get("upload_api_token", "")
PROXY = _CONFIG.get("proxy", "")
LOG_LEVEL = _CONFIG.get("log_level", "info")
logger.set_level(LOG_LEVEL)

def create_session():
    """创建带重试策略的 HTTP 会话"""
    session = requests.Session()
    retry = Retry(total=3, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504])
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    if PROXY:
        session.proxies = {"http": PROXY, "https": PROXY}
    return session

def upload_token_json(session, filepath):
    """上传单个 Token JSON 文件到 CPA 管理平台"""
    filename = os.path.basename(filepath)
    try:
        with open(filepath, "rb") as f:
            files = {"file": (filename, f, "application/json")}
            headers = {"Authorization": f"Bearer {UPLOAD_API_TOKEN}"}

            resp = session.post(
                UPLOAD_API_URL,
                files=files,
                headers=headers,
                verify=False,
                timeout=30,
            )

            if resp.status_code == 200:
                logger.info(f"✅ Token 文件 {filename} 已上传成功")
                return True
            else:
                logger.info(f"❌ CPA 上传失败: {filename} - {resp.status_code} - {resp.text[:200]}")
                return False
    except Exception as e:
        logger.info(f"❌ CPA 上传异常: {filename} - {e}")
        return False

def main():
    logger.info("=" * 60)
    logger.info("  CPA 面板上传工具")
    logger.info("=" * 60)

    if not UPLOAD_API_URL or not UPLOAD_API_TOKEN:
        logger.info("⚠️  错误: 未在 config.json 中配置 `upload_api_url` 或 `upload_api_token`")
        return

    output_dir = "output"
    if not os.path.isdir(output_dir):
        logger.info(f"📂 目录 '{output_dir}' 不存在，无需上传。")
        return

    session = create_session()
    total_files = 0
    uploaded_count = 0
    start_time = time.time()

    logger.info(f"🔍 正在扫描目录: {output_dir}")

    for task_dir_name in os.listdir(output_dir):
        task_dir_path = os.path.join(output_dir, task_dir_name)
        if not os.path.isdir(task_dir_path):
            continue

        codex_tokens_dir = os.path.join(task_dir_path, "codex_tokens")
        if not os.path.isdir(codex_tokens_dir):
            continue

        logger.info(f"📂 正在处理任务目录: {task_dir_path}")
        for filename in os.listdir(codex_tokens_dir):
            if filename.endswith(".json"):
                total_files += 1
                filepath = os.path.join(codex_tokens_dir, filename)
                if upload_token_json(session, filepath):
                    uploaded_count += 1
                time.sleep(0.1) # 避免过快请求

    elapsed = time.time() - start_time
    logger.info("\n" + "=" * 60)
    logger.info("  上传完成!")
    logger.info(f"  总共扫描文件: {total_files}")
    logger.info(f"  成功上传: {uploaded_count}")
    logger.info(f"  失败: {total_files - uploaded_count}")
    logger.info(f"  耗时: {elapsed:.2f} 秒")
    logger.info("=" * 60)

if __name__ == "__main__":
    main()
