"""
简单的日志分级模块。
"""
import threading

class Logger:
    def __init__(self, level='info'):
        self.level = level.lower()
        self._print_lock = threading.Lock()

    def set_level(self, level):
        self.level = level.lower()

    def debug(self, msg, tag=""):
        if self.level == 'debug':
            with self._print_lock:
                prefix = f"[{tag}] " if tag else ""
                print(f"{prefix}{msg}")

    def info(self, msg, tag=""):
        with self._print_lock:
            prefix = f"[{tag}] " if tag else ""
            print(f"{prefix}{msg}")

    def log_http(self, step, method, url, status, body=None, tag=""):
        if self.level == 'debug':
            with self._print_lock:
                prefix = f"[{tag}] " if tag else ""
                lines = [
                    f"\n{'='*60}",
                    f"{prefix}[Step] {step}",
                    f"{prefix}[{method}] {url}",
                    f"{prefix}[Status] {status}",
                ]
                if body:
                    try:
                        import json
                        lines.append(f"{prefix}[Response] {json.dumps(body, indent=2, ensure_ascii=False)[:1000]}")
                    except Exception:
                        lines.append(f"{prefix}[Response] {str(body)[:1000]}")
                lines.append(f"{'='*60}")
                print("\n".join(lines))

# 全局 logger 实例，将在 main.py 中初始化
logger = Logger()
