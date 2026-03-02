"""并发/批量任务模块（低耦合）：
实现 _register_one 与 run_batch，但对 `chatgpt_register` 做延迟导入以避免循环依赖。
"""
import importlib
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
import os
import datetime
from core.logger import logger


def _register_one(idx, total, proxy, output_file, token_json_dir, ak_file, rk_file):
    """单个注册任务（在线程中运行）。对主模块做延迟导入以避免循环导入问题。
    返回 (ok, email, error_message)
    """
    try:
        mod = importlib.import_module("main")
        ChatGPTRegister = getattr(mod, "ChatGPTRegister")
        _generate_password = getattr(mod, "_generate_password")
        _random_name = getattr(mod, "_random_name")
        _random_birthdate = getattr(mod, "_random_birthdate")
        _print_lock = getattr(mod, "_print_lock")
        _file_lock = getattr(mod, "_file_lock")

        reg = ChatGPTRegister(proxy=proxy, tag=f"{idx}")

        # 创建临时邮箱（freemail）
        logger.info("创建临时邮箱...", tag=reg.tag)
        email, mail_token = reg.create_temp_email()
        tag = email.split("@")[0]
        reg.tag = tag

        chatgpt_password = _generate_password()
        name = _random_name()
        birthdate = _random_birthdate()

        logger.debug(f"\n{'='*60}")
        logger.info(f"  [{idx}/{total}] 注册: {email}")
        logger.debug(f"  ChatGPT密码: {chatgpt_password}")
        logger.debug(f"  姓名: {name} | 生日: {birthdate}")
        logger.debug(f"{'='*60}")

        reg.run_register(email, chatgpt_password, name, birthdate, mail_token)

        oauth_ok = True
        mod = importlib.import_module("main")
        ENABLE_OAUTH = getattr(mod, "ENABLE_OAUTH", True)
        if ENABLE_OAUTH:
            logger.info("开始获取 Codex Token...", tag=reg.tag)
            tokens = reg.perform_codex_oauth_login_http(email, chatgpt_password, mail_token=mail_token)
            oauth_ok = bool(tokens and tokens.get("access_token"))
            if oauth_ok:
                save_fn = getattr(mod, "_save_codex_tokens", None)
                if save_fn:
                    save_fn(email, tokens, token_json_dir, ak_file, rk_file)

        with _file_lock:
            with open(output_file, "a", encoding="utf-8") as out:
                out.write(f"{email}----{chatgpt_password}----oauth={'ok' if oauth_ok else 'fail'}\n")

        logger.info(f"注册成功!", tag=tag)

        # 删除临时邮箱
        try:
            from core.emailing import delete_temp_email
            FREEMAIL_WORKER_DOMAIN = getattr(mod, "FREEMAIL_WORKER_DOMAIN", "")
            FREEMAIL_TOKEN = getattr(mod, "FREEMAIL_TOKEN", "")
            delete_temp_email(mail_token, FREEMAIL_WORKER_DOMAIN, FREEMAIL_TOKEN, proxy=proxy)
            logger.info(f"临时邮箱 {email} 已删除", tag=tag)
        except Exception:
            pass # 删除失败不影响结果

        return True, email, None

    except Exception as e:
        try:
            mod = importlib.import_module("main")
            _print_lock = getattr(mod, "_print_lock")
        except Exception:
            _print_lock = None
        error_msg = str(e)
        logger.info(f"注册失败: {error_msg}", tag=str(idx))
        if _print_lock:
            with _print_lock:
                traceback.print_exc()
        else:
            traceback.print_exc()
        return False, None, error_msg


def run_batch(total_accounts: int = 3,
              max_workers: int = 3, proxy: str = None):
    """并发批量注册 - freemail 临时邮箱版（从 app 运行）
    使用延迟导入读取配置以保持与现有模块兼容。
    """
    # 创建新的输出目录
    timestamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    output_dir_name = f"{timestamp}-{total_accounts}"
    output_dir = os.path.join("output", output_dir_name)
    os.makedirs(output_dir, exist_ok=True)

    # 更新文件路径
    accounts_file = os.path.join(output_dir, "registered_accounts.txt")
    token_json_dir = os.path.join(output_dir, "codex_tokens")
    ak_file = os.path.join(output_dir, "ak.txt")
    rk_file = os.path.join(output_dir, "rk.txt")

    mod = importlib.import_module("main")
    FREEMAIL_WORKER_DOMAIN = getattr(mod, "FREEMAIL_WORKER_DOMAIN", "")
    ENABLE_OAUTH = getattr(mod, "ENABLE_OAUTH", True)
    OAUTH_ISSUER = getattr(mod, "OAUTH_ISSUER", "")
    OAUTH_CLIENT_ID = getattr(mod, "OAUTH_CLIENT_ID", "")
    
    actual_workers = min(max_workers, total_accounts)
    logger.info(f"\n{'#'*60}")
    logger.info(f"  ChatGPT 批量自动注册 (freemail 临时邮箱版)")
    logger.info(f"  注册数量: {total_accounts} | 并发数: {actual_workers}")
    logger.info(f"  freemail worker: {FREEMAIL_WORKER_DOMAIN}")
    logger.info(f"  OAuth: {'开启' if ENABLE_OAUTH else '关闭'}")
    if ENABLE_OAUTH:
        logger.info(f"  OAuth Issuer: {OAUTH_ISSUER}")
        logger.info(f"  OAuth Client: {OAUTH_CLIENT_ID}")
    logger.info(f"  输出目录: {output_dir}")
    logger.info(f"{'#'*60}\n")

    success_count = 0
    fail_count = 0
    start_time = time.time()

    with ThreadPoolExecutor(max_workers=actual_workers) as executor:
        futures = {}
        for idx in range(1, total_accounts + 1):
            future = executor.submit(_register_one, idx, total_accounts, proxy, accounts_file, token_json_dir, ak_file, rk_file)
            futures[future] = idx

        for future in as_completed(futures):
            idx = futures[future]
            try:
                ok, email, err = future.result()
                if ok:
                    success_count += 1
                else:
                    fail_count += 1
                    logger.info(f"  [账号 {idx}] 失败: {err}")
            except Exception as e:
                fail_count += 1
                logger.info(f"[FAIL] 账号 {idx} 线程异常: {e}")

    elapsed = time.time() - start_time
    avg = elapsed / total_accounts if total_accounts else 0
    logger.info(f"\n{'#'*60}")
    logger.info(f"  注册完成! 耗时 {elapsed:.1f} 秒")
    logger.info(f"  总数: {total_accounts} | 成功: {success_count} | 失败: {fail_count}")
    logger.info(f"  平均速度: {avg:.1f} 秒/个")
    if success_count > 0:
        logger.info(f"  结果文件: {accounts_file}")
    logger.info(f"{'#'*60}")
