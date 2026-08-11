"""
PaddleOCRVL 本地调试脚本：对单个 PDF 执行 OCR 并把结果打印、保存为 JSON 与 Markdown。

仅用于本地开发验证，非服务入口。

@author: ziyu
@date: 2026-07-16
"""
from paddleocr import PaddleOCRVL

from app.core.config import settings

pipeline = PaddleOCRVL(
    vl_rec_backend=settings.paddle_vl_backend,
    vl_rec_server_url=settings.paddle_vl_server_url,
)
output = pipeline.predict('/private/var/folders/97/p2n6_28n0xlctn_vfb6lzx8r0000gn/T/tmp0czep9rj/upload.pdf')
for res in output:
    res.print()
    res.save_to_json(save_path="output2")
    res.save_to_markdown(save_path="output2")
