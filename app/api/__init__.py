"""
Flask 蓝图注册模块。

集中注册全部业务蓝图（web/pdf/upload/search/retrieval_config/folder）到应用实例。

@author: ziyu
@date: 2026-07-22
"""
from flask import Flask


def register_blueprints(app: Flask) -> None:
    """向 Flask 应用注册全部业务蓝图。"""
    from app.api.pdf import bp as pdf_bp
    from app.api.retrieval_config import bp as retrieval_config_bp
    from app.api.search import bp as search_bp
    from app.api.upload import bp as upload_bp
    from app.api.web import bp as web_bp
    from app.api.folder import bp as folder_bp

    app.register_blueprint(web_bp)
    app.register_blueprint(pdf_bp)
    app.register_blueprint(upload_bp)
    app.register_blueprint(search_bp)
    app.register_blueprint(retrieval_config_bp)
    app.register_blueprint(folder_bp)
