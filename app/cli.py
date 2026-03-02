"""应用 CLI（交互）入口，迁移自原始 `chatgpt_register.py` 的 main。
该模块做延迟导入以使用原来模块的默认常量（保持行为一致）。
"""
import importlib
from core.logger import logger


def main():
    mod = importlib.import_module("main")
    DEFAULT_TOTAL_ACCOUNTS = getattr(mod, "DEFAULT_TOTAL_ACCOUNTS")
    DEFAULT_PROXY = getattr(mod, "DEFAULT_PROXY")
    DEFAULT_OUTPUT_FILE = getattr(mod, "DEFAULT_OUTPUT_FILE")
    FREEMAIL_WORKER_DOMAIN = getattr(mod, "FREEMAIL_WORKER_DOMAIN")
    FREEMAIL_TOKEN = getattr(mod, "FREEMAIL_TOKEN")
    ENABLE_OAUTH = getattr(mod, "ENABLE_OAUTH")
    OAUTH_REQUIRED = getattr(mod, "OAUTH_REQUIRED")
    OAUTH_ISSUER = getattr(mod, "OAUTH_ISSUER")
    OAUTH_CLIENT_ID = getattr(mod, "OAUTH_CLIENT_ID")
    TOKEN_JSON_DIR = getattr(mod, "TOKEN_JSON_DIR")
    AK_FILE = getattr(mod, "AK_FILE", "")
    RK_FILE = getattr(mod, "RK_FILE", "")

    logger.info("=" * 60)
    logger.info("  ChatGPT 批量自动注册工具 (freemail 临时邮箱版)")
    logger.info("=" * 60)
    if not FREEMAIL_WORKER_DOMAIN or not FREEMAIL_TOKEN:
        logger.info("\n⚠️  警告: 未配置 freemail 工作器 (freemail_worker_domain 或 freemail_token)")
        logger.info("   请编辑 config.json 设置 freemail_worker_domain 与 freemail_token，或设置环境变量")
        logger.info("\n   按 Enter 继续尝试运行 (可能会失败)...")
        input()

    proxy = DEFAULT_PROXY
    if proxy:
        logger.info(f"[Info] 检测到默认代理: {proxy}")
        use_default = input("使用此代理? (Y/n): ").strip().lower()
        if use_default == "n":
            proxy = input("输入代理地址 (留空=不使用代理): ").strip() or None
    else:
        import os
        env_proxy = (
            os.environ.get("HTTPS_PROXY")
            or os.environ.get("https_proxy")
            or os.environ.get("ALL_PROXY")
            or os.environ.get("all_proxy")
        )
        if env_proxy:
            logger.info(f"[Info] 检测到环境变量代理: {env_proxy}")
            use_env = input("使用此代理? (Y/n): ").strip().lower()
            if use_env == "n":
                proxy = input("输入代理地址 (留空=不使用代理): ").strip() or None
            else:
                proxy = env_proxy
        else:
            proxy = input("输入代理地址 (如 http://127.0.0.1:7890，留空=不使用代理): ").strip() or None

    if proxy:
        logger.info(f"[Info] 使用代理: {proxy}")
    else:
        logger.info("[Info] 不使用代理")

    count_input = input(f"\n注册账号数量 (默认 {DEFAULT_TOTAL_ACCOUNTS}): ").strip()
    total_accounts = int(count_input) if count_input.isdigit() and int(count_input) > 0 else DEFAULT_TOTAL_ACCOUNTS

    workers_input = input("并发数 (默认 3): ").strip()
    max_workers = int(workers_input) if workers_input.isdigit() and int(workers_input) > 0 else 3

    from .runner import run_batch

    run_batch(total_accounts=total_accounts,
              max_workers=max_workers, proxy=proxy)


if __name__ == "__main__":
    main()
