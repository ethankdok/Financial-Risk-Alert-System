# Flask + SQLite 後台啟動方式

1. 進入專案資料夾：
   ```bash
   cd financial_risk_showcase_v3
   ```
2. 建立虛擬環境（建議）：
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```
3. 安裝套件：
   ```bash
   pip install -r requirements.txt
   ```
4. 啟動：
   ```bash
   python app.py
   ```
5. 瀏覽器開啟：
   `http://127.0.0.1:5000/admin-login.html`

## 初始管理員帳號
- admin001 / demo1234 → Ethan｜系統管理員（首次登入後建議立即修改密碼）
- admin002 / demo5678 → John｜內容審核員（首次登入後建議立即修改密碼）

## 資料庫
首次啟動會自動建立 `financial_risk.db`（SQLite），包含：
- admins：管理員
- keywords：正式關鍵字
- risk_features：風險特徵
- audit_logs：操作紀錄

密碼使用 Werkzeug password hash 儲存，不再放明碼在瀏覽器 JavaScript。

## 新增：管理員管理
登入「系統管理員」後，可從側邊欄進入 `管理員管理`：
- 新增管理員帳號
- 修改顯示名稱與角色
- 啟用／停用帳號
- 重設密碼
- 所有操作自動寫入 audit_logs

### 權限設計
- 系統管理員：可管理管理員、關鍵字、風險特徵與操作紀錄。
- 內容審核員：可登入並使用一般內容管理功能，但不可新增、停用、調整角色或重設其他管理員密碼。

### 為什麼用「停用」而不是直接刪除？
`audit_logs.admin_id` 會記錄是哪位管理員做過某次修改。若直接把管理員資料永久刪除，歷史紀錄就可能失去可追溯的身分。因此管理介面預設採用 `is_active = 0` 的軟停用方式。

### 這個功能背後的資料流
1. HTML / JavaScript 將新增管理員資料送到 `POST /api/admins`。
2. Flask 先透過 Session 確認目前登入者，再檢查角色是否為「系統管理員」。
3. 密碼透過 Werkzeug `generate_password_hash()` 轉為雜湊值。
4. Flask 使用 SQL `INSERT` 將管理員寫入 SQLite `admins` 資料表。
5. `audit()` 再新增一筆 `audit_logs`，記錄操作者與操作內容。
6. API 以 JSON 回傳新增結果，JavaScript 更新畫面。

### Authentication vs Authorization
- Authentication（身分驗證）：確認「你是誰」。本專案由帳號密碼 + Flask Session 完成。
- Authorization（權限授權）：確認「你可以做什麼」。本專案由 `role` 欄位與 `system_admin_required` decorator 控制。
