from flask import Flask, jsonify, render_template, request
from financial_routes import create_financial_blueprint

app = Flask(__name__)
app.register_blueprint(create_financial_blueprint())

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/analysis")
def analysis():
    return render_template("analysis.html")


@app.route("/analyzing")
def analyzing():
    return render_template("analyzing.html")


@app.route("/summary")
def summary():
    return render_template("summary.html")


@app.route("/result")
def result():
    return render_template("result.html")


@app.route("/official")
def official():
    return render_template("official.html")


@app.route("/records")
def records():
    return render_template("records.html")


@app.route("/member")
def member():
    return render_template("member.html")


@app.route("/login")
def login():
    return render_template("login.html")


@app.route("/register")
def register():
    return render_template("register.html")


@app.route("/api/analyze", methods=["POST"])
def api_analyze():
    data = request.get_json(silent=True) or {}
    question = str(data.get("question", "")).strip()

    if not question:
        return jsonify({
            "success": False,
            "error": "請輸入想查詢的金融資訊。"
        }), 400

    result = {
        "success": True,
        "question": question,
        "summary": (
            "目前未發現公開資訊觀測站中有資料支持「保證漲停」"
            "或「保證獲利」等說法。若相關內容同時要求加入私人群組，"
            "可能具有行銷或投資詐騙風險。"
        ),
        "risk_level": "高風險",
        "credibility_score": 23,
        "reasons": [
            "內容包含保證獲利或保證漲停等絕對性話術",
            "未提供可驗證的官方公告或可靠新聞來源",
            "可能引導使用者加入 LINE 群組或私人投資社團"
        ],
        "sources": [
            "公開資訊觀測站",
            "Yahoo 財經新聞",
            "X 貼文"
        ]
    }

    return jsonify(result)


if __name__ == "__main__":
    app.run(debug=True)
