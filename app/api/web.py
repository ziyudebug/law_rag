"""
Web 控制台路由模块。

提供首页、登录、检索测试、上传测试、文件夹测试、检索配置等页面入口，
页面访问均需登录（session 校验），未登录跳转登录页。

@author: ziyu
@date: 2026-07-27
"""
from flask import Blueprint, redirect, render_template, request, session, url_for

from app.core.config import settings

bp = Blueprint("web", __name__)


@bp.get("/")
def index():
    """首页 / 控制台，未登录则跳转登录页。"""
    if not session.get("logged_in"):
        return redirect(url_for("web.login_page"))
    return render_template("index.html", api_token=settings.api_token)


@bp.get("/retrieval-config")
def retrieval_config_page():
    """检索配置页，注入默认检索参数供前端表单回填。"""
    if not session.get("logged_in"):
        return redirect(url_for("web.login_page"))
    retrieval_defaults = {
        "retrieval_mode": settings.retrieval_default_mode,
        "hybrid_strategy": settings.retrieval_default_hybrid_strategy,
        "use_rerank": settings.retrieval_default_use_rerank,
        "semantic_weight": settings.retrieval_default_semantic_weight,
        "keyword_weight": settings.retrieval_default_keyword_weight,
        "top_k": settings.retrieval_default_top_k,
        "enable_source": settings.retrieval_default_enable_source,
        "score_threshold": settings.retrieval_default_score_threshold,
    }
    return render_template(
        "retrieval_config.html",
        default_rerank_model=settings.default_rerank_model,
        retrieval_defaults=retrieval_defaults,
    )


@bp.get("/retrieval-test")
def retrieval_test_page():
    """检索测试页。"""
    if not session.get("logged_in"):
        return redirect(url_for("web.login_page"))
    return render_template("retrieval_test.html", api_token=settings.api_token)


@bp.get("/upload-test")
def upload_test_page():
    """上传测试页。"""
    if not session.get("logged_in"):
        return redirect(url_for("web.login_page"))
    return render_template("upload_test.html", api_token=settings.api_token)


@bp.get("/folder-test")
def folder_test_page():
    """文件夹测试页。"""
    if not session.get("logged_in"):
        return redirect(url_for("web.login_page"))
    return render_template("folder_test.html", api_token=settings.api_token)


@bp.get("/login")
def login_page():
    """渲染登录页。"""
    return render_template("login.html")


@bp.post("/check-password")
def check_password():
    """校验登录密码，通过则写入 session 并跳转首页，否则回显错误。"""
    password = request.form.get("password", "")
    if password == settings.access_password:
        session["logged_in"] = True
        return redirect(url_for("web.index"))
    return render_template("login.html", error="密码错误，请重试！")
