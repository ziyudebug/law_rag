"""
应用入口模块。

负责创建 Flask 应用实例，并将 DashScope API Key 从 pydantic settings 同步到进程
环境变量（dashscope SDK 直接读环境变量，不经过 settings）。

@author: ziyu
@date: 2026-07-29
"""
import os

from app import create_app
from app.core.config import settings

# .env 只进了 pydantic settings，dashscope SDK 读的是进程环境变量，这里同步过去
if settings.dashscope_api_key and not os.environ.get("DASHSCOPE_API_KEY"):
    os.environ["DASHSCOPE_API_KEY"] = settings.dashscope_api_key

app = create_app()


if __name__ == "__main__":
    app.run(
        host=settings.api_host,
        port=settings.api_port,
        debug=settings.flask_debug,
    )
