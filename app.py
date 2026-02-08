from flask import Flask, render_template_string, request, jsonify
import pandas as pd
import os
import re

app = Flask(__name__)

FILE_PATH = "service_resources.xlsx"
df = pd.read_excel(FILE_PATH)

# 공통 CSS (모바일 반응형 + 홈버튼)
BASE_STYLE = """
    * { box-sizing: border-box; }
    body { font-family: 'Pretendard', sans-serif; margin: 0; padding: 20px; background: #f7f9fc; }
    h1, h2 { color: #2c3e50; text-align: center; }
    label { display: block; margin-top: 10px; font-weight: bold; }
    input, select, textarea { 
        width: 100%; 
        padding: 12px; 
        font-size: 16px; 
        border-radius: 8px; 
        border: 1px solid #ccc; 
        margin-top: 5px; 
    }
    button { 
        padding: 14px 22px; 
        font-size: 18px; 
        background: #0078d7; 
        color: white; 
        border: none; 
        border-radius: 8px; 
        cursor: pointer; 
        margin-top: 15px; 
        width: 100%;
    }
    button:hover { background: #005fa3; }
    .result { margin-top: 30px; background: #fff; padding: 20px; border-radius: 8px; box-shadow: 0 2px 6px rgba(0,0,0,0.1); }
    .container { max-width: 600px; margin: auto; }
    .home-btn {
        display: inline-block; 
        background: #2c3e50; 
        color: white; 
        text-decoration: none; 
        padding: 10px 16px; 
        border-radius: 6px; 
        font-size: 15px; 
        margin-bottom: 20px;
    }
    .home-btn:hover { background: #1a252f; }

    /* ✅ 메인 하단 이미지 (추가된 부분 ONLY) */
    .bottom-image {
        width: 100%;
        height: auto;
        display: block;
        margin-top: 40px;
    }

    @media (max-width: 600px) {
        h1, h2 { font-size: 22px; }
        button { font-size: 16px; padding: 12px; }
    }
"""

# 🏠 첫 화면
HOME_HTML = """
<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>지자체 서비스자원 검색 시스템</title>
    <style>{{ style }}</style>
</head>
<body>
<div class="container">
    <h1>🏛 지자체 서비스자원 검색 시스템</h1>
    <p style="text-align:center;">검색 방식을 선택하세요</p>
    <a href="/combo"><button>① 대상자 특성 검색</button></a>
    <a href="/desc"><button>② 서술형 검색</button></a>

    <!-- ✅ 이미지 추가 (이 줄 하나만 추가됨) -->
    <img src="/static/bottom.png" class="bottom-image">
</div>
</body>
</html>
"""

# ✅ 대상자 특성 검색 페이지
COMBO_HTML = """
<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>대상자 특성 검색</title>
    <style>{{ style }}</style>
</head>
<body>
<div class="container">
    <a href="/" class="home-btn">← 홈으로</a>
    <h2>대상자 특성 검색</h2>
    <form method="post">
        <label>연령 (이상):</label>
        <input type="number" name="age" placeholder="예: 70" value="{{ age or '' }}">

        <label>가구유형:</label>
        <select name="family_type">
            <option value="">무관</option>
            {% for f in family_types %}
                <option value="{{ f }}" {% if f == family_type %}selected{% endif %}>{{ f }}</option>
            {% endfor %}
        </select>

        <label>장애여부:</label>
        <select name="disability">
            <option value="">무관</option>
            {% for d in disabilities %}
                <option value="{{ d }}" {% if d == disability %}selected{% endif %}>{{ d }}</option>
            {% endfor %}
        </select>

        <label>방문형서비스:</label>
        <select name="service_type">
            <option value="">무관</option>
            {% for s in services %}
                <option value="{{ s }}" {% if s == service_type %}selected{% endif %}>{{ s }}</option>
            {% endfor %}
        </select>

        <label>지역:</label>
        <input type="text" name="region" placeholder="예: 종로구" value="{{ region or '' }}">

        <label>기타 키워드:</label>
        <input type="text" name="keyword" placeholder="예: 정서지원, 에너지" value="{{ keyword or '' }}">

        <button type="submit">검색하기 🔍</button>
    </form>

    {% if results is not none %}
        <div class="result">
            {% if results|length > 0 %}
                <p>총 {{ results|length }}개의 자원을 찾았습니다.</p>
                {% for r in results %}
                    <div style="cursor:pointer; color:#0078d7;"
                         onclick="openDetail({{ r['index'] }})">
                        🔹 {{ loop.index }}. {{ r['프로그램명칭'] }}
                    </div>
                {% endfor %}
            {% else %}
                <p>조건에 맞는 자원이 없습니다.</p>
            {% endif %}
        </div>
    {% endif %}
</div>

<!-- 상세 팝업 -->
<div id="modal" style="display:none; position:fixed; top:0; left:0;
width:100%; height:100%; background:rgba(0,0,0,0.5);">
  <div style="background:#fff; margin:5% auto; padding:20px;
       width:90%; max-width:500px; border-radius:10px;">
    <h3 id="m_title"></h3>
    <p><b>기관명:</b> <span id="m_org"></span></p>
    <p><b>기관 연락처:</b> <span id="m_tel"></span></p>
    <p><b>기관주소:</b> <span id="m_addr"></span></p>
    <iframe id="m_map" width="100%" height="250" style="border:0; margin-top:10px;" loading="lazy"></iframe>
    <button onclick="closeModal()">닫기</button>
  </div>
</div>

<script>
function openDetail(idx){
  fetch("/detail/" + idx)
    .then(res => res.json())
    .then(data => {
      document.getElementById("m_title").innerText = data["프로그램명칭"];
      document.getElementById("m_org").innerText = data["기관명"];
      document.getElementById("m_tel").innerText = data["기관 연락처"];
      document.getElementById("m_addr").innerText = data["기관주소"];
      const addr = encodeURIComponent(data["기관주소"]);
      document.getElementById("m_map").src = "https://www.google.com/maps?q=" + addr + "&output=embed";
      document.getElementById("modal").style.display = "block";
    });
}
function closeModal(){
  document.getElementById("modal").style.display = "none";
}
</script>
</body>
</html>
"""

# ✅ 서술형 검색 페이지
DESC_HTML = """
<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>서술형 검색</title>
    <style>{{ style }}</style>
</head>
<body>
<div class="container">
    <a href="/" class="home-btn">← 홈으로</a>
    <h2>서술형 검색</h2>
    <form method="post">
        <textarea name="query" placeholder="예: 담양에 65세 이상이 이용 가능한 요양 서비스를 찾아줘">{{ query }}</textarea><br>
        <button type="submit">검색하기</button>
    </form>

    {% if results is not none %}
        <div class="result">
            {% if results|length > 0 %}
                <p>총 {{ results|length }}개의 자원을 찾았습니다.</p>
                {% for r in results %}
                    <div>🔹 {{ loop.index }}. {{ r }}</div>
                {% endfor %}
            {% else %}
                <p>조건에 맞는 자원이 없습니다.</p>
            {% endif %}
        </div>
    {% endif %}
</div>
</body>
</html>
"""

@app.route("/")
def home():
    return render_template_string(HOME_HTML, style=BASE_STYLE)

@app.route("/combo", methods=["GET", "POST"])
def combo():
    family_types = sorted(df["가구유형"].dropna().unique().tolist()) if "가구유형" in df else []
    disabilities = sorted(df["장애여부"].dropna().unique().tolist()) if "장애여부" in df else []
    services = sorted(df["방문형서비스"].dropna().unique().tolist()) if "방문형서비스" in df else []

    results = None
    age = family_type = disability = service_type = region = keyword = ""

    if request.method == "POST":
        age = request.form.get("age", "")
        family_type = request.form.get("family_type", "")
        disability = request.form.get("disability", "")
        service_type = request.form.get("service_type", "")
        region = request.form.get("region", "").strip()
        keyword = request.form.get("keyword", "").strip()
        filtered = df.copy()

        if family_type:
            filtered = filtered[filtered["가구유형"].astype(str).str.contains(family_type, case=False, na=False)]
        if disability:
            filtered = filtered[filtered["장애여부"].astype(str).str.contains(disability, case=False, na=False)]
        if service_type:
            filtered = filtered[filtered["방문형서비스"].astype(str).str.contains(service_type, case=False, na=False)]
        if region:
            filtered = filtered[filtered["지역"].astype(str).str.contains(region, case=False, na=False)]
        if keyword:
            filtered = filtered[filtered.apply(lambda x: keyword.lower() in str(x.to_dict()).lower(), axis=1)]
        if age.isdigit() and "연령" in df.columns:
            filtered = filtered[pd.to_numeric(filtered["연령"], errors="coerce") >= int(age)]

        if not any([age, family_type, disability, service_type, region, keyword]):
            results = df.reset_index()[["index", "프로그램명칭"]].dropna().to_dict("records")
        else:
            results = filtered.reset_index()[["index", "프로그램명칭"]].dropna().to_dict("records")

    return render_template_string(COMBO_HTML,
                                  style=BASE_STYLE,
                                  family_types=family_types,
                                  disabilities=disabilities,
                                  services=services,
                                  results=results,
                                  age=age,
                                  family_type=family_type,
                                  disability=disability,
                                  service_type=service_type,
                                  region=region,
                                  keyword=keyword)

@app.route("/detail/<int:idx>")
def detail(idx):
    row = df.iloc[idx]
    return jsonify({
        "프로그램명칭": str(row.get("프로그램명칭", "")),
        "기관명": str(row.get("서비스 제공기관명", "")),
        "기관 연락처": str(row.get("기관연락처", "")),
        "기관주소": str(row.get("기관주소", ""))
    })

@app.route("/desc", methods=["GET", "POST"])
def desc():
    query = ""
    results = None
    if request.method == "POST":
        query = request.form["query"]
        cond = {}
        regions = ["목포", "담양", "광주", "서울", "부산", "전주"]
        categories = ["요양", "복지", "돌봄", "장애", "아동", "노인"]

        for r in regions:
            if r in query:
                cond["지역"] = r
        for c in categories:
            if c in query:
                cond["대분류"] = c
        age_match = re.search(r'(\d{2})세', query)
        if age_match:
            cond["연령"] = int(age_match.group(1))
        filtered = df.copy()
        for k, v in cond.items():
            if k in df.columns:
                filtered = filtered[filtered[k].astype(str).str.contains(str(v), na=False)]
        results = filtered["프로그램명칭"].dropna().tolist()
    return render_template_string(DESC_HTML, style=BASE_STYLE, query=query, results=results)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
