"""
接口鉴权模块。

通过请求头 token 校验调用方身份，校验失败的请求会脱敏记录到日志文件。

@author: ziyu
@date: 2026-07-16
"""
import datetime
from functools import wraps
from typing import Callable, TypeVar

from flask import jsonify, request

from app.core.config import settings


F = TypeVar("F", bound=Callable)


def _mask_token(token: str) -> str:
    """对 token 做脱敏处理，仅保留首尾 3 位，避免日志泄露完整凭证。"""
    if not token:
        return ""
    if len(token) <= 6:
        return "***"
    return f"{token[:3]}***{token[-3:]}"


def write_token_error_log() -> None:
    """记录 token 验证失败的请求日志（时间/IP/接口/脱敏 token）。"""
    try:
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        client_ip = request.remote_addr
        req_path = request.path
        req_method = request.method
        token = (request.headers.get("token") or "").strip().lower()

        log_content = (
            f"[{now}] TOKEN验证失败 | "
            f"IP: {client_ip} | "
            f"接口: {req_method} {req_path} | "
            f"提交的token: {_mask_token(token)}\n"
        )

        with open(settings.ERR_LOG, "a", encoding="utf-8") as file:
            file.write(log_content)
    except Exception as exc:
        print(f"日志写入失败: {str(exc)}")


def require_token(func: F) -> F:
    """接口鉴权装饰器：校验请求头 token 是否等于配置的 API_TOKEN，不通过则记日志并返回 400。"""
    @wraps(func)
    def wrapper(*args, **kwargs):
        token = (request.headers.get("token") or "").strip().lower()
        expected_token = settings.api_token.strip().lower()
        if not expected_token or token != expected_token:
            write_token_error_log()
            return jsonify({"success": False, "error": "token 错误。"}), 400
        return func(*args, **kwargs)

    return wrapper  # type: ignore[return-value]
