import sys
import importlib.util
from pathlib import Path

from flask import render_template, send_from_directory
from starlette.middleware.wsgi import WSGIMiddleware

ROOT = Path(__file__).resolve().parent
BACKEND = ROOT / "fintrust_backend"

sys.path.insert(0, str(BACKEND))
sys.path.insert(1, str(ROOT))

# 載入原有 FastAPI
from app.main import app

# 載入原有 Flask
spec = importlib.util.spec_from_file_location(
    "fintrust_legacy_flask",
    ROOT / "app.py"
)

module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)

flask_app = module.app

# 正確設定 Flask 模板目錄
flask_app.template_folder = str(ROOT / "templates")

# 補上 CSS、JavaScript、圖片的靜態路由
if "static" not in flask_app.view_functions:
    flask_app.add_url_rule(
        "/static/<path:filename>",
        endpoint="static",
        view_func=lambda filename: send_from_directory(
            ROOT / "static",
            filename
        )
    )

# 使用 Jinja 正確渲染分析頁面
flask_app.add_url_rule(
    "/analysis",
    endpoint="legacy_analysis_page",
    view_func=lambda: render_template("analysis.html"),
    methods=["GET"]
)

# 保留 FastAPI 現有路由的優先順序
# 其餘路由交給 Flask
app.mount("/", WSGIMiddleware(flask_app))
