from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime
from functools import wraps
from pathlib import Path

from flask import Flask, jsonify, request, session, send_from_directory
from financial_routes import create_financial_blueprint
from werkzeug.security import check_password_hash, generate_password_hash

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "financial_risk.db"

app = Flask(__name__, static_folder=None)
app.secret_key = os.environ.get("SECRET_KEY", "dev-change-this-secret-key")
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
)
app.register_blueprint(create_financial_blueprint())


def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def db_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def row_to_dict(row):
    return dict(row) if row is not None else None


def audit(action, target, summary, before=None, after=None, admin_id=None):
    admin_id = admin_id or session.get("admin_id")
    with db_conn() as conn:
        conn.execute(
            """INSERT INTO audit_logs
               (admin_id, action, target, summary, before_json, after_json, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                admin_id,
                action,
                target,
                summary,
                json.dumps(before, ensure_ascii=False) if before is not None else None,
                json.dumps(after, ensure_ascii=False) if after is not None else None,
                now_str(),
            ),
        )


def login_required(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        if not session.get("admin_id"):
            return jsonify({"error": "unauthorized"}), 401
        return fn(*args, **kwargs)
    return wrapped


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


def init_db():
    with db_conn() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS admins (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              username TEXT UNIQUE NOT NULL,
              password_hash TEXT NOT NULL,
              display_name TEXT NOT NULL,
              role TEXT NOT NULL,
              is_active INTEGER NOT NULL DEFAULT 1,
              created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS keywords (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              phrase TEXT UNIQUE NOT NULL,
              category TEXT NOT NULL,
              risk TEXT NOT NULL,
              source TEXT NOT NULL,
              reason TEXT,
              status TEXT NOT NULL DEFAULT 'active',
              approved_by INTEGER,
              approved_at TEXT NOT NULL,
              updated_by INTEGER,
              updated_at TEXT NOT NULL,
              FOREIGN KEY(approved_by) REFERENCES admins(id),
              FOREIGN KEY(updated_by) REFERENCES admins(id)
            );

            CREATE TABLE IF NOT EXISTS risk_features (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              name TEXT UNIQUE NOT NULL,
              dimension TEXT NOT NULL,
              weight INTEGER NOT NULL,
              keywords_json TEXT NOT NULL DEFAULT '[]',
              definition TEXT NOT NULL,
              explain TEXT,
              status TEXT NOT NULL DEFAULT 'active',
              updated_by INTEGER,
              updated_at TEXT NOT NULL,
              FOREIGN KEY(updated_by) REFERENCES admins(id)
            );

            CREATE TABLE IF NOT EXISTS audit_logs (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              admin_id INTEGER,
              action TEXT NOT NULL,
              target TEXT NOT NULL,
              summary TEXT NOT NULL,
              before_json TEXT,
              after_json TEXT,
              created_at TEXT NOT NULL,
              FOREIGN KEY(admin_id) REFERENCES admins(id)
            );

        CREATE TABLE IF NOT EXISTS analysis_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            query_text TEXT NOT NULL,
            risk_score INTEGER NOT NULL,
            raw_score INTEGER NOT NULL DEFAULT 0,
            risk_level TEXT NOT NULL,
            matched_keywords_json TEXT NOT NULL DEFAULT '[]',
            matched_features_json TEXT NOT NULL DEFAULT '[]',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
            """
        )

        if conn.execute("SELECT COUNT(*) FROM admins").fetchone()[0] == 0:
            conn.executemany(
                "INSERT INTO admins(username,password_hash,display_name,role,created_at) VALUES(?,?,?,?,?)",
                [
                    ("admin001", generate_password_hash("demo1234"), "Ethan", "系統管理員", now_str()),
                    ("admin002", generate_password_hash("demo5678"), "Rainy", "內容審核員", now_str()),
                ],
            )

        admin_id = conn.execute("SELECT id FROM admins WHERE username='admin001'").fetchone()[0]

        if conn.execute("SELECT COUNT(*) FROM keywords").fetchone()[0] == 0:
            seeds = [
                ("保證獲利", "保證報酬", "高", "人工匯入", "對投資結果做確定性承諾。"),
                ("內線消息", "未公開消息", "高", "X", "宣稱取得未公開資訊，需提高警覺。"),
                ("加入 VIP", "行動誘導", "中", "X", "引導使用者加入特定會員或群組。"),
                ("最後機會", "心理壓力", "中", "Yahoo 財經", "以時間急迫降低使用者查證時間。"),
            ]
            for phrase, cat, risk, source, reason in seeds:
                t = now_str()
                conn.execute(
                    """INSERT INTO keywords
                    (phrase,category,risk,source,reason,status,approved_by,approved_at,updated_by,updated_at)
                    VALUES(?,?,?,?,?,'active',?,?,?,?)""",
                    (phrase, cat, risk, source, reason, admin_id, t, admin_id, t),
                )

        if conn.execute("SELECT COUNT(*) FROM risk_features").fetchone()[0] == 0:
            features = [
                ("保證報酬", "金融高風險主張", 3, ["保證獲利","穩賺不賠","一定漲停","保證翻倍"], "對未來投資報酬做確定性或無風險承諾。", "本文對投資結果做確定性承諾，可能使使用者低估投資風險。"),
                ("未公開消息", "可信感強化", 3, ["內線消息","公司高層透露","主力準備拉抬"], "宣稱掌握尚未公開或無法查證的公司資訊。", "本文以未公開消息建立可信感，但缺乏正式來源支持。"),
                ("時間急迫", "心理壓力", 1, ["立即","今晚截止","最後機會","現在處理"], "透過時間限制促使使用者快速做決定。", "本文使用時間限制製造急迫感，可能降低使用者查證時間。"),
                ("稀缺壓力", "心理壓力", 1, ["名額有限","僅剩三席","前50名","額滿即止"], "利用數量或名額限制增加錯失焦慮。", "本文利用名額或數量限制製造稀缺感。"),
                ("加入／聯絡誘導", "行動誘導", 1, ["加入VIP","私訊老師","聯絡助理","點擊連結"], "要求使用者加入群組、聯絡特定對象或點擊外部連結。", "本文包含直接行動要求，應確認對方身分與連結來源。"),
                ("權威訴求", "可信感強化", 1, ["老師推薦","專家預測","法人透露","官方合作"], "利用權威身分或專業形象提高說服力。", "本文使用權威身分強化可信感，但權威宣稱仍需獨立查證。"),
                ("來源不可驗證", "來源可信度", 2, ["獨家消息","內部消息","匿名人士指出"], "重要主張未提供可追溯、可驗證的正式來源。", "本文的重要主張目前缺乏可驗證來源，建議對照正式公告。"),
            ]
            for name, dimension, weight, keywords, definition, explain in features:
                conn.execute(
                    """INSERT INTO risk_features
                    (name,dimension,weight,keywords_json,definition,explain,status,updated_by,updated_at)
                    VALUES(?,?,?,?,?,?,'active',?,?)""",
                    (name, dimension, weight, json.dumps(keywords, ensure_ascii=False), definition, explain, admin_id, now_str()),
                )


def current_admin():
    admin_id = session.get("admin_id")
    if not admin_id:
        return None
    with db_conn() as conn:
        row = conn.execute(
            "SELECT id,username,display_name,role FROM admins WHERE id=? AND is_active=1",
            (admin_id,),
        ).fetchone()
    return row_to_dict(row)


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
    with db_conn() as conn:
        row = conn.execute("SELECT * FROM admins WHERE username=? AND is_active=1", (username,)).fetchone()
    if not row or not check_password_hash(row["password_hash"], password):
        return jsonify({"error": "帳號或密碼錯誤"}), 401
    session.clear()
    session["admin_id"] = row["id"]
    admin = {"id": row["id"], "username": row["username"], "name": row["display_name"], "role": row["role"]}
    audit("登入", "管理後台", "管理員登入系統", after={"username": username, "role": row["role"]}, admin_id=row["id"])
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
    with db_conn() as conn:
        rows = conn.execute(
            """SELECT k.*, a.display_name AS updated_by_name
               FROM keywords k LEFT JOIN admins a ON a.id=k.updated_by
               ORDER BY k.id DESC"""
        ).fetchall()
    return jsonify([row_to_dict(r) for r in rows])


@app.post("/api/keywords")
@login_required
def create_keyword():
    data = request.get_json(silent=True) or {}
    phrase = str(data.get("phrase", "")).strip()
    if not phrase:
        return jsonify({"error": "請輸入關鍵字"}), 400
    admin_id = session["admin_id"]
    t = now_str()
    payload = {
        "phrase": phrase,
        "category": data.get("category", "其他"),
        "risk": data.get("risk", "中"),
        "source": data.get("source", "管理者新增"),
        "reason": data.get("reason", ""),
        "status": data.get("status", "active"),
    }
    try:
        with db_conn() as conn:
            cur = conn.execute(
                """INSERT INTO keywords
                (phrase,category,risk,source,reason,status,approved_by,approved_at,updated_by,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (phrase,payload["category"],payload["risk"],payload["source"],payload["reason"],payload["status"],admin_id,t,admin_id,t),
            )
            kid = cur.lastrowid
    except sqlite3.IntegrityError:
        return jsonify({"error": "此關鍵字已存在"}), 409
    payload.update({"id": kid, "approved_at": t, "updated_at": t})
    audit("新增", "關鍵字", f"新增「{phrase}」", after=payload)
    return jsonify(payload), 201


@app.put("/api/keywords/<int:kid>")
@login_required
def update_keyword(kid):
    data = request.get_json(silent=True) or {}
    with db_conn() as conn:
        old = conn.execute("SELECT * FROM keywords WHERE id=?", (kid,)).fetchone()
        if not old:
            return jsonify({"error": "not found"}), 404
        before = row_to_dict(old)
        fields = {
            "phrase": data.get("phrase", old["phrase"]),
            "category": data.get("category", old["category"]),
            "risk": data.get("risk", old["risk"]),
            "source": data.get("source", old["source"]),
            "reason": data.get("reason", old["reason"]),
            "status": data.get("status", old["status"]),
            "updated_by": session["admin_id"],
            "updated_at": now_str(),
        }
        conn.execute(
            """UPDATE keywords SET phrase=?,category=?,risk=?,source=?,reason=?,status=?,updated_by=?,updated_at=? WHERE id=?""",
            (fields["phrase"],fields["category"],fields["risk"],fields["source"],fields["reason"],fields["status"],fields["updated_by"],fields["updated_at"],kid),
        )
    audit("修改", "關鍵字", f"修改「{fields['phrase']}」", before=before, after=fields)
    return jsonify({"id": kid, **fields})


@app.delete("/api/keywords/<int:kid>")
@login_required
def delete_keyword(kid):
    with db_conn() as conn:
        old = conn.execute("SELECT * FROM keywords WHERE id=?", (kid,)).fetchone()
        if not old:
            return jsonify({"error": "not found"}), 404
        before = row_to_dict(old)
        conn.execute("DELETE FROM keywords WHERE id=?", (kid,))
    audit("刪除", "關鍵字", f"刪除「{before['phrase']}」", before=before)
    return jsonify({"ok": True})


@app.get("/api/risk-features")
@login_required
def list_risk_features():
    with db_conn() as conn:
        rows = conn.execute("SELECT * FROM risk_features ORDER BY id DESC").fetchall()
    result = []
    for r in rows:
        d = row_to_dict(r)
        d["keywords"] = json.loads(d.pop("keywords_json") or "[]")
        result.append(d)
    return jsonify(result)


@app.post("/api/risk-features")
@login_required
def create_risk_feature():
    data = request.get_json(silent=True) or {}
    name = str(data.get("name", "")).strip()
    definition = str(data.get("definition", "")).strip()
    if not name or not definition:
        return jsonify({"error": "請輸入特徵名稱與判斷定義"}), 400
    t = now_str()
    payload = {
        "name": name,
        "dimension": data.get("dimension", "行動誘導"),
        "weight": int(data.get("weight", 1)),
        "keywords": data.get("keywords", []),
        "definition": definition,
        "explain": data.get("explain", ""),
        "status": data.get("status", "active"),
    }
    try:
        with db_conn() as conn:
            cur = conn.execute(
                """INSERT INTO risk_features(name,dimension,weight,keywords_json,definition,explain,status,updated_by,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?)""",
                (name,payload["dimension"],payload["weight"],json.dumps(payload["keywords"],ensure_ascii=False),definition,payload["explain"],payload["status"],session["admin_id"],t),
            )
            fid = cur.lastrowid
    except sqlite3.IntegrityError:
        return jsonify({"error": "此風險特徵已存在"}), 409
    payload.update({"id": fid, "updated_at": t})
    audit("新增", "風險特徵", f"新增「{name}」", after=payload)
    return jsonify(payload), 201


@app.put("/api/risk-features/<int:fid>")
@login_required
def update_risk_feature(fid):
    data = request.get_json(silent=True) or {}
    with db_conn() as conn:
        old = conn.execute("SELECT * FROM risk_features WHERE id=?", (fid,)).fetchone()
        if not old:
            return jsonify({"error": "not found"}), 404
        before = row_to_dict(old)
        old_keywords = json.loads(old["keywords_json"] or "[]")
        payload = {
            "name": data.get("name", old["name"]),
            "dimension": data.get("dimension", old["dimension"]),
            "weight": int(data.get("weight", old["weight"])),
            "keywords": data.get("keywords", old_keywords),
            "definition": data.get("definition", old["definition"]),
            "explain": data.get("explain", old["explain"]),
            "status": data.get("status", old["status"]),
            "updated_at": now_str(),
        }
        conn.execute(
            """UPDATE risk_features SET name=?,dimension=?,weight=?,keywords_json=?,definition=?,explain=?,status=?,updated_by=?,updated_at=? WHERE id=?""",
            (payload["name"],payload["dimension"],payload["weight"],json.dumps(payload["keywords"],ensure_ascii=False),payload["definition"],payload["explain"],payload["status"],session["admin_id"],payload["updated_at"],fid),
        )
    audit("修改", "風險特徵", f"修改「{payload['name']}」", before=before, after=payload)
    return jsonify({"id": fid, **payload})


@app.delete("/api/risk-features/<int:fid>")
@login_required
def delete_risk_feature(fid):
    with db_conn() as conn:
        old = conn.execute("SELECT * FROM risk_features WHERE id=?", (fid,)).fetchone()
        if not old:
            return jsonify({"error": "not found"}), 404
        before = row_to_dict(old)
        conn.execute("DELETE FROM risk_features WHERE id=?", (fid,))
    audit("刪除", "風險特徵", f"刪除「{before['name']}」", before=before)
    return jsonify({"ok": True})


@app.get("/api/admins")
@system_admin_required
def list_admins():
    with db_conn() as conn:
        rows = conn.execute(
            """SELECT id, username, display_name, role, is_active, created_at
               FROM admins ORDER BY is_active DESC, id ASC"""
        ).fetchall()
    return jsonify([row_to_dict(r) for r in rows])


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

    payload = {
        "username": username,
        "display_name": display_name,
        "role": role,
        "is_active": 1,
        "created_at": now_str(),
    }
    try:
        with db_conn() as conn:
            cur = conn.execute(
                """INSERT INTO admins(username,password_hash,display_name,role,is_active,created_at)
                   VALUES(?,?,?,?,1,?)""",
                (username, generate_password_hash(password), display_name, role, payload["created_at"]),
            )
            payload["id"] = cur.lastrowid
    except sqlite3.IntegrityError:
        return jsonify({"error": "此管理員帳號已存在"}), 409

    audit("新增", "管理員", f"新增管理員「{display_name}」", after=payload)
    return jsonify(payload), 201


@app.put("/api/admins/<int:admin_id>")
@system_admin_required
def update_admin(admin_id):
    data = request.get_json(silent=True) or {}
    with db_conn() as conn:
        old = conn.execute(
            "SELECT id,username,display_name,role,is_active,created_at FROM admins WHERE id=?",
            (admin_id,),
        ).fetchone()
        if not old:
            return jsonify({"error": "找不到管理員"}), 404
        before = row_to_dict(old)

        display_name = str(data.get("display_name", old["display_name"])).strip()
        role = str(data.get("role", old["role"])).strip()
        is_active = int(data.get("is_active", old["is_active"]))
        if role not in {"系統管理員", "內容審核員"}:
            return jsonify({"error": "無效的管理員角色"}), 400
        if is_active not in {0, 1}:
            return jsonify({"error": "無效的帳號狀態"}), 400

        # A logged-in administrator cannot disable their own account.
        if admin_id == session.get("admin_id") and is_active == 0:
            return jsonify({"error": "不能停用目前正在登入的自己"}), 400

        # Keep at least one active system administrator at all times.
        if old["role"] == "系統管理員" and (role != "系統管理員" or is_active == 0):
            active_system_admins = conn.execute(
                "SELECT COUNT(*) FROM admins WHERE role='系統管理員' AND is_active=1"
            ).fetchone()[0]
            if active_system_admins <= 1:
                return jsonify({"error": "系統至少必須保留一位啟用中的系統管理員"}), 400

        conn.execute(
            "UPDATE admins SET display_name=?, role=?, is_active=? WHERE id=?",
            (display_name, role, is_active, admin_id),
        )
        after = {**before, "display_name": display_name, "role": role, "is_active": is_active}

    audit("修改", "管理員", f"修改管理員「{display_name}」", before=before, after=after)
    return jsonify(after)


@app.post("/api/admins/<int:admin_id>/reset-password")
@system_admin_required
def reset_admin_password(admin_id):
    data = request.get_json(silent=True) or {}
    new_password = str(data.get("password", ""))
    if len(new_password) < 8:
        return jsonify({"error": "新密碼至少需要 8 個字元"}), 400

    with db_conn() as conn:
        old = conn.execute(
            "SELECT id,username,display_name,role,is_active,created_at FROM admins WHERE id=?",
            (admin_id,),
        ).fetchone()
        if not old:
            return jsonify({"error": "找不到管理員"}), 404
        conn.execute(
            "UPDATE admins SET password_hash=? WHERE id=?",
            (generate_password_hash(new_password), admin_id),
        )
        target = row_to_dict(old)

    # Do not put passwords or password hashes into audit logs.
    audit("重設密碼", "管理員", f"重設管理員「{target['display_name']}」的密碼", after={"admin_id": admin_id})
    return jsonify({"ok": True})


@app.get("/api/audit-logs")
@login_required
def list_audit_logs():
    with db_conn() as conn:
        rows = conn.execute(
            """SELECT l.*, a.username AS admin_id_text, a.display_name AS admin_name, a.role
               FROM audit_logs l LEFT JOIN admins a ON a.id=l.admin_id
               ORDER BY l.id DESC LIMIT 500"""
        ).fetchall()
    out = []
    for r in rows:
        d = row_to_dict(r)
        d["adminId"] = d.pop("admin_id_text") or "system"
        d["adminName"] = d.pop("admin_name") or "系統"
        d["time"] = d.pop("created_at")
        d["before"] = json.loads(d.pop("before_json")) if d.get("before_json") else None
        d["after"] = json.loads(d.pop("after_json")) if d.get("after_json") else None
        out.append(d)
    return jsonify(out)


@app.delete("/api/audit-logs")
@login_required
def clear_audit_logs():
    with db_conn() as conn:
        conn.execute("DELETE FROM audit_logs")
    audit("刪除", "操作紀錄", "清除操作紀錄")
    return jsonify({"ok": True})



@app.post("/api/analyze")
def analyze_text():
    data = request.get_json(silent=True) or {}
    text = str(data.get("text", "")).strip()

    if not text:
        return jsonify({"error": "請提供要分析的文字"}), 400

    matched_keywords = []
    matched_features = []
    total_score = 0

    with db_conn() as conn:
        keyword_rows = conn.execute(
            """
            SELECT id, phrase, category, risk, source, reason
            FROM keywords
            WHERE status = 'active'
            """
        ).fetchall()

        for row in keyword_rows:
            phrase = row["phrase"]

            if phrase and phrase in text:
                matched_keywords.append({
                    "id": row["id"],
                    "phrase": phrase,
                    "category": row["category"],
                    "risk": row["risk"],
                    "source": row["source"],
                    "reason": row["reason"]
                })

        feature_rows = conn.execute(
            """
            SELECT id, name, dimension, weight,
                   keywords_json, definition, explain
            FROM risk_features
            WHERE status = 'active'
            """
        ).fetchall()

        for row in feature_rows:
            try:
                feature_keywords = json.loads(row["keywords_json"] or "[]")
            except Exception:
                feature_keywords = []

            hits = [
                keyword
                for keyword in feature_keywords
                if keyword and keyword in text
            ]

            if hits:
                weight = int(row["weight"] or 0)
                total_score += weight

                matched_features.append({
                    "id": row["id"],
                    "name": row["name"],
                    "dimension": row["dimension"],
                    "weight": weight,
                    "matched_keywords": hits,
                    "definition": row["definition"],
                    "explain": row["explain"]
                })

    # 將內部原始權重轉換為 0-100 的風險指數
    # 原始權重 0-9 對應至 0-100，超過 9 分則以 100 分為上限
    raw_score = total_score
    risk_score = min(100, round((raw_score / 9) * 100))

    if risk_score >= 60:
        risk_level = "高風險"
    elif risk_score >= 30:
        risk_level = "中風險"
    else:
        risk_level = "低風險"

    # 儲存本次分析紀錄
    with db_conn() as conn:
        cursor = conn.execute(
            """
            INSERT INTO analysis_records (
                query_text,
                risk_score,
                raw_score,
                risk_level,
                matched_keywords_json,
                matched_features_json
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                text,
                risk_score,
                raw_score,
                risk_level,
                json.dumps(matched_keywords, ensure_ascii=False),
                json.dumps(matched_features, ensure_ascii=False)
            )
        )
        record_id = cursor.lastrowid

    return jsonify({
        "record_id": record_id,
        "text": text,
        "risk_level": risk_level,
        "score": risk_score,
        "raw_score": raw_score,
        "matched_keywords": matched_keywords,
        "matched_features": matched_features,
        "summary": {
            "keyword_count": len(matched_keywords),
            "feature_count": len(matched_features)
        }
    })


if __name__ == "__main__":
    init_db()
    app.run(host="127.0.0.1", port=5001, debug=True)
