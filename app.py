from __future__ import annotations

import os
from datetime import datetime
from functools import wraps
from pathlib import Path
from typing import Any

from flask import Flask, jsonify, request, session, send_from_directory
from financial_routes import create_financial_blueprint
from flask_data_repository import DuplicateRecordError, build_flask_data_repository
from werkzeug.security import check_password_hash, generate_password_hash

from data_shift import data_shift_bp
from taiwan_shift import taiwan_shift_bp

BASE_DIR = Path(__file__).resolve().parent
APP_ENV = os.environ.get("APP_ENV", "development").strip().lower()
IS_PRODUCTION = APP_ENV == "production"
SECRET_KEY = os.environ.get("SECRET_KEY", "").strip()
if IS_PRODUCTION and not SECRET_KEY:
    raise RuntimeError("SECRET_KEY must be configured when APP_ENV=production")

app = Flask(__name__, static_folder=None)
app.secret_key = SECRET_KEY or "dev-change-this-secret-key"
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=IS_PRODUCTION,
)
app.register_blueprint(create_financial_blueprint())
app.register_blueprint(data_shift_bp)
app.register_blueprint(taiwan_shift_bp)

repository = build_flask_data_repository(BASE_DIR)
repository.initialize()


def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _public_admin(admin: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": admin["id"],
        "username": admin["username"],
        "display_name": admin["display_name"],
        "role": admin["role"],
        "is_active": int(admin.get("is_active", 1)),
        "created_at": admin.get("created_at"),
    }


def _demo_seed_enabled() -> bool:
    configured = os.getenv("ALLOW_DEMO_SEED_DATA")
    if configured is not None:
        return configured.strip().lower() in {"1", "true", "yes", "on"}
    return repository.backend_name == "sqlite"


def ensure_seed_data() -> None:
    """Keep local demo data without auto-creating production Firestore records.

    Firestore production deployments should receive data through an explicit
    migration/upsert step. Set ALLOW_DEMO_SEED_DATA=true only for local or
    disposable demo environments.
    """
    if not _demo_seed_enabled():
        return

    admins = repository.list_admins()
    if not admins:
        repository.create_admin({
            "username": "admin001",
            "password_hash": generate_password_hash("demo1234"),
            "display_name": "Ethan",
            "role": "系統管理員",
            "is_active": 1,
            "created_at": now_str(),
        })
        repository.create_admin({
            "username": "admin002",
            "password_hash": generate_password_hash("demo5678"),
            "display_name": "John",
            "role": "內容審核員",
            "is_active": 1,
            "created_at": now_str(),
        })

    primary_admin = repository.get_admin_by_username("admin001")
    if not primary_admin:
        return
    admin_id = int(primary_admin["id"])

    if not repository.list_keywords():
        seeds = [
            ("保證獲利", "保證報酬", "高", "人工匯入", "對投資結果做確定性承諾。"),
            ("內線消息", "未公開消息", "高", "X", "宣稱取得未公開資訊，需提高警覺。"),
            ("加入 VIP", "行動誘導", "中", "X", "引導使用者加入特定會員或群組。"),
            ("最後機會", "心理壓力", "中", "Yahoo 財經", "以時間急迫降低使用者查證時間。"),
        ]
        for phrase, category, risk, source, reason in seeds:
            timestamp = now_str()
            repository.create_keyword({
                "phrase": phrase,
                "category": category,
                "risk": risk,
                "source": source,
                "reason": reason,
                "status": "active",
                "approved_by": admin_id,
                "approved_at": timestamp,
                "updated_by": admin_id,
                "updated_at": timestamp,
            })

    if not repository.list_risk_features():
        features = [
            (
                "保證報酬／低風險高報酬",
                "金融高風險主張",
                3,
                ["保證獲利", "穩賺不賠", "一定漲停", "保證翻倍", "零風險高報酬", "保證報酬"],
                "對未來投資報酬做確定性承諾，或宣稱高報酬同時幾乎沒有風險。",
                "本文出現保證報酬或低風險高報酬主張，屬於重要投資風險警訊。",
            ),
            (
                "內線／未公開消息訴求",
                "可信感強化",
                3,
                ["內線消息", "公司高層透露", "主力準備拉抬", "未公開消息", "內部人士透露"],
                "宣稱掌握尚未公開、內線或一般投資人無法驗證的資訊。",
                "本文以內線或未公開消息建立可信感，但缺乏正式公開來源支持。",
            ),
            (
                "來源不可驗證",
                "來源可信度",
                2,
                ["獨家消息", "內部消息", "匿名人士指出", "消息人士透露", "不能公開來源"],
                "重要主張未提供可追溯、可驗證的正式來源。",
                "本文的重要主張目前缺乏可驗證來源，建議對照公開資訊觀測站或正式公告。",
            ),
            (
                "急迫性／時間壓力",
                "心理壓力",
                2,
                ["立即", "今晚截止", "最後機會", "現在處理", "馬上買", "立刻加入", "今天最後"],
                "透過時間限制或立即行動要求促使使用者快速做決定。",
                "本文使用時間壓力降低使用者查證與思考時間。",
            ),
            (
                "稀缺性訴求",
                "心理壓力",
                1,
                ["名額有限", "僅剩三席", "前50名", "額滿即止", "限量名額", "最後幾個名額"],
                "利用名額、數量或機會有限製造錯失焦慮。",
                "本文利用稀缺性增加行動壓力；此特徵單獨出現時不一定代表高風險。",
            ),
            (
                "群組／私訊／外部導流",
                "行動誘導",
                2,
                ["加入VIP", "加入 VIP", "私訊老師", "聯絡助理", "點擊連結", "加入LINE", "加入 LINE", "下載APP", "下載 App"],
                "要求使用者加入群組、私訊特定對象、下載 App 或前往外部連結。",
                "本文包含群組、私訊或外部導流行為，應確認對方身分、平台與連結來源。",
            ),
            (
                "未驗證權威訴求",
                "可信感強化",
                1,
                ["老師推薦", "專家預測", "法人透露", "官方合作", "金管會認證", "分析師保證"],
                "透過權威、專業或官方身分提高說服力，但相關身分或合作未經驗證。",
                "本文使用權威身分強化可信感，仍需透過正式來源獨立查證。",
            ),
            (
                "社會認同／從眾訴求",
                "社會影響",
                2,
                ["大家都買了", "大家都上車了", "群友都賺錢", "會員都獲利", "已經很多人獲利", "很多人都買", "大家都在買"],
                "利用他人已參與或已獲利的描述，製造從眾與社會認同壓力。",
                "本文透過『大家都在做』或『大家都賺錢』建立從眾感，可能降低個別投資人的查證意願。",
            ),
        ]
        for name, dimension, weight, keywords, definition, explain in features:
            repository.create_risk_feature({
                "name": name,
                "dimension": dimension,
                "weight": weight,
                "keywords": keywords,
                "definition": definition,
                "explain": explain,
                "status": "active",
                "updated_by": admin_id,
                "updated_at": now_str(),
            })


ensure_seed_data()


def audit(action: str, target: str, summary: str, before=None, after=None, admin_id=None) -> None:
    repository.append_audit({
        "admin_id": admin_id or session.get("admin_id"),
        "action": action,
        "target": target,
        "summary": summary,
        "before": before,
        "after": after,
        "created_at": now_str(),
    })


def login_required(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        if not session.get("admin_id"):
            return jsonify({"error": "unauthorized"}), 401
        return fn(*args, **kwargs)
    return wrapped


def current_admin() -> dict[str, Any] | None:
    admin_id = session.get("admin_id")
    if not admin_id:
        return None
    admin = repository.get_admin(int(admin_id), active_only=True)
    return _public_admin(admin) if admin else None


def system_admin_required(fn):
    """Only active administrators with the 系統管理員 role may continue."""
    @wraps(fn)
    def wrapped(*args, **kwargs):
        admin = current_admin()
        if not admin:
            return jsonify({"error": "unauthorized"}), 401
        if admin["role"] != "系統管理員":
            return jsonify({"error": "forbidden", "message": "只有系統管理員可以管理管理員帳號"}), 403
        return fn(*args, **kwargs)
    return wrapped


@app.get("/health")
def health():
    return jsonify({
        "status": "ok",
        "service": "financial-risk-web",
        "datastore_backend": repository.backend_name,
    })


@app.route("/")
def home():
    return send_from_directory(BASE_DIR, "index.html")


@app.route("/<path:filename>")
def static_files(filename):
    return send_from_directory(BASE_DIR, filename)


@app.post("/api/auth/login")
def api_login():
    data = request.get_json(silent=True) or {}
    username = str(data.get("username", "")).strip()
    password = str(data.get("password", ""))
    admin_row = repository.get_admin_by_username(username, active_only=True)
    if not admin_row or not check_password_hash(admin_row["password_hash"], password):
        return jsonify({"error": "帳號或密碼錯誤"}), 401

    session.clear()
    session["admin_id"] = int(admin_row["id"])
    admin = {
        "id": int(admin_row["id"]),
        "username": admin_row["username"],
        "name": admin_row["display_name"],
        "role": admin_row["role"],
    }
    audit("登入", "管理後台", "管理員登入系統", after={"username": username, "role": admin_row["role"]}, admin_id=int(admin_row["id"]))
    return jsonify(admin)


@app.post("/api/auth/logout")
@login_required
def api_logout():
    admin = current_admin()
    audit("登出", "管理後台", "管理員登出系統")
    session.clear()
    return jsonify({"ok": True, "admin": admin})


@app.get("/api/auth/me")
def api_me():
    admin = current_admin()
    if not admin:
        return jsonify({"error": "unauthorized"}), 401
    return jsonify({"id": admin["id"], "username": admin["username"], "name": admin["display_name"], "role": admin["role"]})


@app.get("/api/keywords")
@login_required
def list_keywords():
    return jsonify(repository.list_keywords())


@app.post("/api/keywords")
@login_required
def create_keyword():
    data = request.get_json(silent=True) or {}
    phrase = str(data.get("phrase", "")).strip()
    if not phrase:
        return jsonify({"error": "請輸入關鍵字"}), 400

    admin_id = int(session["admin_id"])
    timestamp = now_str()
    payload = {
        "phrase": phrase,
        "category": data.get("category", "其他"),
        "risk": data.get("risk", "中"),
        "source": data.get("source", "管理者新增"),
        "reason": data.get("reason", ""),
        "status": data.get("status", "active"),
        "approved_by": admin_id,
        "approved_at": timestamp,
        "updated_by": admin_id,
        "updated_at": timestamp,
    }
    try:
        created = repository.create_keyword(payload)
    except DuplicateRecordError:
        return jsonify({"error": "此關鍵字已存在"}), 409

    audit("新增", "關鍵字", f"新增「{phrase}」", after=created)
    return jsonify(created), 201


@app.put("/api/keywords/<int:kid>")
@login_required
def update_keyword(kid: int):
    data = request.get_json(silent=True) or {}
    old = repository.get_keyword(kid)
    if not old:
        return jsonify({"error": "not found"}), 404

    fields = {
        "phrase": data.get("phrase", old["phrase"]),
        "category": data.get("category", old["category"]),
        "risk": data.get("risk", old["risk"]),
        "source": data.get("source", old["source"]),
        "reason": data.get("reason", old.get("reason", "")),
        "status": data.get("status", old["status"]),
        "updated_by": int(session["admin_id"]),
        "updated_at": now_str(),
    }
    try:
        updated = repository.update_keyword(kid, fields)
    except DuplicateRecordError:
        return jsonify({"error": "此關鍵字已存在"}), 409
    if not updated:
        return jsonify({"error": "not found"}), 404

    audit("修改", "關鍵字", f"修改「{fields['phrase']}」", before=old, after=updated)
    return jsonify(updated)


@app.delete("/api/keywords/<int:kid>")
@login_required
def delete_keyword(kid: int):
    old = repository.delete_keyword(kid)
    if not old:
        return jsonify({"error": "not found"}), 404
    audit("刪除", "關鍵字", f"刪除「{old['phrase']}」", before=old)
    return jsonify({"ok": True})


@app.get("/api/risk-features")
@login_required
def list_risk_features():
    return jsonify(repository.list_risk_features())


@app.post("/api/risk-features")
@login_required
def create_risk_feature():
    data = request.get_json(silent=True) or {}
    name = str(data.get("name", "")).strip()
    definition = str(data.get("definition", "")).strip()
    if not name or not definition:
        return jsonify({"error": "請輸入特徵名稱與判斷定義"}), 400

    payload = {
        "name": name,
        "dimension": data.get("dimension", "行動誘導"),
        "weight": int(data.get("weight", 1)),
        "keywords": data.get("keywords", []),
        "definition": definition,
        "explain": data.get("explain", ""),
        "status": data.get("status", "active"),
        "updated_by": int(session["admin_id"]),
        "updated_at": now_str(),
    }
    try:
        created = repository.create_risk_feature(payload)
    except DuplicateRecordError:
        return jsonify({"error": "此風險特徵已存在"}), 409

    audit("新增", "風險特徵", f"新增「{name}」", after=created)
    return jsonify(created), 201


@app.put("/api/risk-features/<int:fid>")
@login_required
def update_risk_feature(fid: int):
    data = request.get_json(silent=True) or {}
    old = repository.get_risk_feature(fid)
    if not old:
        return jsonify({"error": "not found"}), 404

    fields = {
        "name": data.get("name", old["name"]),
        "dimension": data.get("dimension", old["dimension"]),
        "weight": int(data.get("weight", old["weight"])),
        "keywords": data.get("keywords", old.get("keywords", [])),
        "definition": data.get("definition", old["definition"]),
        "explain": data.get("explain", old.get("explain", "")),
        "status": data.get("status", old["status"]),
        "updated_by": int(session["admin_id"]),
        "updated_at": now_str(),
    }
    try:
        updated = repository.update_risk_feature(fid, fields)
    except DuplicateRecordError:
        return jsonify({"error": "此風險特徵已存在"}), 409
    if not updated:
        return jsonify({"error": "not found"}), 404

    audit("修改", "風險特徵", f"修改「{fields['name']}」", before=old, after=updated)
    return jsonify(updated)


@app.delete("/api/risk-features/<int:fid>")
@login_required
def delete_risk_feature(fid: int):
    old = repository.delete_risk_feature(fid)
    if not old:
        return jsonify({"error": "not found"}), 404
    audit("刪除", "風險特徵", f"刪除「{old['name']}」", before=old)
    return jsonify({"ok": True})


@app.get("/api/admins")
@system_admin_required
def list_admins():
    return jsonify([_public_admin(admin) for admin in repository.list_admins()])


@app.post("/api/admins")
@system_admin_required
def create_admin():
    data = request.get_json(silent=True) or {}
    username = str(data.get("username", "")).strip()
    display_name = str(data.get("display_name", "")).strip()
    password = str(data.get("password", ""))
    role = str(data.get("role", "內容審核員")).strip()

    if not username or not display_name or not password:
        return jsonify({"error": "請輸入帳號、顯示名稱與密碼"}), 400
    if len(username) < 4:
        return jsonify({"error": "管理員帳號至少需要 4 個字元"}), 400
    if len(password) < 8:
        return jsonify({"error": "密碼至少需要 8 個字元"}), 400
    if role not in {"系統管理員", "內容審核員"}:
        return jsonify({"error": "無效的管理員角色"}), 400

    internal_payload = {
        "username": username,
        "password_hash": generate_password_hash(password),
        "display_name": display_name,
        "role": role,
        "is_active": 1,
        "created_at": now_str(),
    }
    try:
        created = repository.create_admin(internal_payload)
    except DuplicateRecordError:
        return jsonify({"error": "此管理員帳號已存在"}), 409

    public = _public_admin(created)
    audit("新增", "管理員", f"新增管理員「{display_name}」", after=public)
    return jsonify(public), 201


@app.put("/api/admins/<int:admin_id>")
@system_admin_required
def update_admin(admin_id: int):
    data = request.get_json(silent=True) or {}
    old = repository.get_admin(admin_id)
    if not old:
        return jsonify({"error": "找不到管理員"}), 404

    display_name = str(data.get("display_name", old["display_name"])).strip()
    role = str(data.get("role", old["role"])).strip()
    is_active = int(data.get("is_active", old["is_active"]))
    if role not in {"系統管理員", "內容審核員"}:
        return jsonify({"error": "無效的管理員角色"}), 400
    if is_active not in {0, 1}:
        return jsonify({"error": "無效的帳號狀態"}), 400
    if admin_id == session.get("admin_id") and is_active == 0:
        return jsonify({"error": "不能停用目前正在登入的自己"}), 400
    if old["role"] == "系統管理員" and (role != "系統管理員" or is_active == 0):
        if repository.count_active_system_admins() <= 1:
            return jsonify({"error": "系統至少必須保留一位啟用中的系統管理員"}), 400

    before = _public_admin(old)
    updated = repository.update_admin(admin_id, {
        "display_name": display_name,
        "role": role,
        "is_active": is_active,
    })
    if not updated:
        return jsonify({"error": "找不到管理員"}), 404

    after = _public_admin(updated)
    audit("修改", "管理員", f"修改管理員「{display_name}」", before=before, after=after)
    return jsonify(after)


@app.post("/api/admins/<int:admin_id>/reset-password")
@system_admin_required
def reset_admin_password(admin_id: int):
    data = request.get_json(silent=True) or {}
    new_password = str(data.get("password", ""))
    if len(new_password) < 8:
        return jsonify({"error": "新密碼至少需要 8 個字元"}), 400

    target = repository.get_admin(admin_id)
    if not target:
        return jsonify({"error": "找不到管理員"}), 404
    repository.set_admin_password(admin_id, generate_password_hash(new_password))
    audit("重設密碼", "管理員", f"重設管理員「{target['display_name']}」的密碼", after={"admin_id": admin_id})
    return jsonify({"ok": True})


@app.get("/api/audit-logs")
@login_required
def list_audit_logs():
    output = []
    for row in repository.list_audit_logs(limit=500):
        item = dict(row)
        item["adminId"] = item.pop("admin_id_text", None) or "system"
        item["adminName"] = item.pop("admin_name", None) or "系統"
        item["time"] = item.pop("created_at")
        output.append(item)
    return jsonify(output)


@app.delete("/api/audit-logs")
@login_required
def clear_audit_logs():
    repository.clear_audit_logs()
    audit("刪除", "操作紀錄", "清除操作紀錄")
    return jsonify({"ok": True})


@app.post("/api/analyze")
def analyze_text():
    data = request.get_json(silent=True) or {}
    text_input = str(data.get("text", "")).strip()

    if not text_input:
        return jsonify({"error": "請提供要分析的文字"}), 400

    matched_keywords: list[dict[str, Any]] = []
    matched_features: list[dict[str, Any]] = []
    raw_score = 0

    for row in repository.list_keywords(active_only=True):
        phrase = row.get("phrase")
        if phrase and phrase in text_input:
            matched_keywords.append({
                "id": row["id"],
                "phrase": phrase,
                "category": row["category"],
                "risk": row["risk"],
                "source": row["source"],
                "reason": row.get("reason"),
            })

    feature_rows = repository.list_risk_features(active_only=True)
    max_score = sum(max(0, int(row.get("weight") or 0)) for row in feature_rows)

    for row in feature_rows:
        feature_keywords = list(row.get("keywords") or [])
        hits = [keyword for keyword in feature_keywords if keyword and keyword in text_input]
        if hits:
            weight = max(0, int(row.get("weight") or 0))
            raw_score += weight
            matched_features.append({
                "id": row["id"],
                "name": row["name"],
                "dimension": row["dimension"],
                "weight": weight,
                "matched_keywords": hits,
                "definition": row["definition"],
                "explain": row.get("explain"),
            })

    risk_score = min(100, round((raw_score / max_score) * 100)) if max_score > 0 else 0

    if risk_score >= 60:
        risk_level = "高風險"
    elif risk_score >= 30:
        risk_level = "中風險"
    else:
        risk_level = "低風險"

    record_id = repository.create_analysis_record({
        "query_text": text_input,
        "risk_score": risk_score,
        "raw_score": raw_score,
        "max_score": max_score,
        "risk_level": risk_level,
        "matched_keywords": matched_keywords,
        "matched_features": matched_features,
        "created_at": now_str(),
    })

    return jsonify({
        "record_id": record_id,
        "text": text_input,
        "score": risk_score,
        "raw_score": raw_score,
        "max_score": max_score,
        "risk_level": risk_level,
        "matched_keywords": matched_keywords,
        "matched_features": matched_features,
        "summary": {
            "keyword_count": len(matched_keywords),
            "feature_count": len(matched_features),
            "active_feature_count": len(feature_rows),
        },
        "normalization": {
            "formula": "100 * raw_score / max_score",
            "note": "max_score 由所有 active risk features 的權重動態加總，不寫死固定值。",
        },
        "threshold": {
            "low": "< 30",
            "medium": "30-59",
            "high": ">= 60",
            "status": "prototype",
        },
    })


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5001, debug=True)
