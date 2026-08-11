"""
PDF 转图片 PDF 工具模块。

用 PyMuPDF 把 PDF 每页渲染为 JPEG 图片，再合并成一个新的图片型 PDF，
用于把文本型 PDF 转成扫描型走 OCR 流程（含压缩）。

@author: ziyu
@date: 2026-07-17
"""
import fitz  # PyMuPDF
import os
import img2pdf
from PIL import Image

def pdf_to_image_pdf_compressed(input_pdf, output_pdf, dpi=300, quality=100):
    """把 PDF 每页渲染为 JPEG 后合并为图片型 PDF，dpi 控制分辨率、quality 控制 JPEG 压缩质量。"""
    doc = fitz.open(input_pdf)
    img_paths = []

    for page_num in range(len(doc)):
        page = doc[page_num]
        mat = fitz.Matrix(dpi / 72, dpi / 72)
        pix = page.get_pixmap(matrix=mat)

        # 转PIL Image
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        img_path = f"temp_page_{page_num + 1}.jpg"
        img.save(img_path, "JPEG", quality=quality)
        img_paths.append(img_path)

    # 合并为PDF
    with open(output_pdf, "wb") as f:
        f.write(img2pdf.convert(img_paths))

    # 删除临时图片
    for path in img_paths:
        os.remove(path)

    print(f"压缩转换完成！已保存为：{output_pdf}")

# # 使用
# if __name__ == "__main__":
#     pdf_to_image_pdf_compressed(
#         "废水、废气、噪声.pdf",
#         dpi=150,    # 分辨率
#         quality=70  # JPEG压缩质量
#     )