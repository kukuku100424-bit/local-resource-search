from flask import Flask, render_template_string, request, jsonify
import pandas as pd
import os
import re

app = Flask(__name__)

FILE_PATH = "service_resources.xlsx"
df = pd.read_excel(FILE_PATH)

# ================= 공통 CSS =================
BASE_STYLE = """
* { box-sizing: border-box; }
body { font-family: 'Pretendard', sans-serif; margin:0; padding:20px; background:#f7f9fc; }
h1,h2 { text-align:center; color:#2c3e50; }
label { font-weight:bold; margin-top:10px; display:block; }
input, select, textarea {
  width:100%; padding:12px; font-size:16px;
  border-radius:8px; border:1px solid #ccc; margin-top:5px;
}
button {
  width:100%; padding:14px; font-size:18px;
  background:#0078d7; color:white; border:none;
  border-radius:8px; cursor:pointer; margin-top:15px;
}
button:hover { background:#005fa3; }
.container { max-width:600px; margin:auto; }
.result {
  margin-top:30px; background:white; padding:20px;
  border-radius:8px; box-shadow:0 2px 6px rgba(0,0,0,0.1);
}
.home-btn {
  display:inline-block; background:#2c3e50; color:white;
  text-decoration:none; padding:10px 16px; border-radius:6px;
  margin-bottom:20px;
}
.home-btn:hover { background:#1a252f; }
.bottom-image { width:100%; margin-top:40px; }
"""

# ================= HOME =================
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
<img src="/static/bottom.png" class="bottom-image">
</div>
</body>
</html>
"""

# ================= COMBO =================
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
<label>연령 (이상)</label>
<input type="text" name="age" placeholder="예: 70" value="{{ age or '' }}">

<label>가구유형</label>
<select name="family_type">
<option value="">무관</option>
{% for f in family_types %}
<option value="{{ f }}" {% if f==family_type %}selected{% endif %}>{{ f }}</option>
{% endfor %}
</select>

<label>장애여부</label>
<select name="disability">
<option value="">무관</option>
{% for d in disabilities %}
<option value="{{ d }}" {% if d==disability %}selected{% endif %}>{{ d }}</option>
{% endfor %}
</select>

<label>방문형서비스</label>
<select name="service_type">
<option value="">무관</option>
{% for s in services %}
<option value="{{ s }}" {% if s==service_type %}selected{% endif %}>{{ s }}</option>
{% endfor %}
</select>

<label>지역</label>
<input type="text" name="region" placeholder="예: 나주시" value="{{ region or '' }}">

<label>기타 키워드</label>
<input type="text" name="keyword" placeholder="예: 정서지원, 에너지" value="{{ keyword or '' }}">

<button type="submit">검색하기 🔍</button>
</form>

{% if results is not none %}
<div class="result">
{% if results|length > 0 %}
<p>총 {{ results|length }}개의 자원을 찾았습니다.</p>
{% for r in results %}
<div style="cursor:pointer;color:#0078d7;"
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

<!-- 공통 팝업 -->
<div id="modal" style="display:none;position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,.5)">
<div style="background:white;margin:5% auto;padding:20px;width:90%;max-width:500px;border-radius:10px">
<h3 id="m_title"></h3>
<p><b>기관명:</b> <span id="m_org"></span></p>
<p><b>기관 연락처:</b> <span id="m_tel"></span></p>
<p><b>기관주소:</b> <span id="m_addr"></span></p>
<iframe id="m_map" width="100%" height="250" style="border:0"></iframe>
<button onclick="closeModal()">닫기</button>
</div>
</div>

<script>
function openDetail(idx){
fetch("/detail/"+idx)
.then(r=>r.json())
.then(d=>{
m_title.innerText=d["프로그램명칭"];
m_org.innerText=d["기관명"];
m_tel.innerText=d["기관 연락처"];
m_addr.innerText=d["기관주소"];
m_map.src="https://www.google.com/maps?q="+encodeURIComponent(d["기관주소"])+"&output=embed";
modal.style.display="block";
});
}
function closeModal(){ modal.style.display="none"; }
</script>
</body>
</html>
"""

# ================= DESC (수정됨) =================
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
<textarea name="query" placeholder="예: 목포에 사는 독거노인이 이용 가능한 서비스">{{ query }}</textarea>
<button type="submit">검색하기</button>
</form>

{% if message %}
<div class="result">{{ message }}</div>

{% elif results is not none %}
<div class="result">
{% if cond_display %}
<p><b>이 조건으로 검색했습니다</b></p>
<ul>
{% for c in cond_display %}
<li>✔ {{ c }}</li>
{% endfor %}
</ul>
<hr>
{% endif %}

{% if results|length > 0 %}
<p>총 {{ results|length }}개의 자원을 찾았습니다.</p>
{% for r in results %}
<div style="cursor:pointer;color:#0078d7;"
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

<!-- 동일 팝업 -->
<div id="modal" style="display:none;position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,.5)">
<div style="background:white;margin:5% auto;padding:20px;width:90%;max-width:500px;border-radius:10px">
<h3 id="m_title"></h3>
<p><b>기관명:</b> <span id="m_org"></span></p>
<p><b>기관 연락처:</b> <span id="m_tel"></span></p>
<p><b>기관주소:</b> <span id="m_addr"></span></p>
<iframe id="m_map" width="100%" height="250" style="border:0"></iframe>
<button onclick="closeModal()">닫기</button>
</div>
</div>

<script>
function openDetail(idx){
fetch("/detail/"+idx)
.then(r=>r.json())
.then(d=>{
m_title.innerText=d["프로그램명칭"];
m_org.innerText=d["기관명"];
m_tel.innerText=d["기관 연락처"];
m_addr.innerText=d["기관주소"];
m_map.src="https://www.google.com/maps?q="+encodeURIComponent(d["기관주소"])+"&output=embed";
modal.style.display="block";
});
}
function closeModal(){ modal.style.display="none"; }
</script>
</body>
</html>
"""

# ================= ROUTES =================
@app.route("/")
def home():
    return render_template_string(HOME_HTML, style=BASE_STYLE)

@app.route("/combo", methods=["GET","POST"])
def combo():
    family_types = sorted(df["가구유형"].dropna().unique().tolist())
    disabilities = sorted(df["장애여부"].dropna().unique().tolist())
    services = sorted(df["방문형서비스"].dropna().unique().tolist())

    results=None
    age=family_type=disability=service_type=region=keyword=""

    if request.method=="POST":
        age=request.form.get("age","").strip()
        family_type=request.form.get("family_type","")
        disability=request.form.get("disability","")
        service_type=request.form.get("service_type","")
        region=request.form.get("region","").strip()
        keyword=request.form.get("keyword","").strip()

        filtered=df.copy()

        if age.isdigit() and "연령" in df.columns:
            filtered=filtered[pd.to_numeric(filtered["연령"],errors="coerce")>=int(age)]
        if family_type:
            filtered=filtered[filtered["가구유형"].astype(str).str.contains(family_type,na=False)]
        if disability:
            filtered=filtered[filtered["장애여부"].astype(str).str.contains(disability,na=False)]
        if service_type:
            filtered=filtered[filtered["방문형서비스"].astype(str).str.contains(service_type,na=False)]
        if region:
            filtered=filtered[filtered["지역"].astype(str).str.contains(region,na=False)]
        if keyword:
            filtered=filtered[filtered.apply(
                lambda x: keyword.lower() in str(x.to_dict()).lower(), axis=1)]

        results=filtered.reset_index()[["index","프로그램명칭"]].dropna().to_dict("records")

    return render_template_string(
        COMBO_HTML, style=BASE_STYLE,
        family_types=family_types, disabilities=disabilities,
        services=services, results=results,
        age=age,family_type=family_type,
        disability=disability,service_type=service_type,
        region=region,keyword=keyword
    )

@app.route("/detail/<int:idx>")
def detail(idx):
    r=df.iloc[idx]
    return jsonify({
        "프로그램명칭":str(r.get("프로그램명칭","")),
        "기관명":str(r.get("서비스 제공기관명","")),
        "기관 연락처":str(r.get("기관연락처","")),
        "기관주소":str(r.get("기관주소",""))
    })

@app.route("/desc", methods=["GET","POST"])
def desc():
    query=""
    results=None
    message=None
    cond_display=[]

    if request.method=="POST":
        query=request.form["query"]
        cond={}

        # ✅ 지역: 엑셀 기준 (시/군 단위 추출)
        if "지역" in df.columns:
            for region in df["지역"].dropna().astype(str).unique():
                # 예: "전라남도 나주시 남평읍" → "나주"
                m = re.search(r"([가-힣]+)(시|군)", region)
                if not m:
                    continue

                city = m.group(1)  # "나주", "목포", "화순"

                if city in query:
                    cond["지역"] = city
                    cond_display.append(f"지역: {city}")
                    break


        if any(w in query for w in ["혼자","독거","1인"]):
            cond["가구유형"]="독거"
            cond_display.append("가구유형: 독거")

        if not cond:
            message="검색어에서 조건을 찾지 못했습니다."
            results=[]
            cond_display=[]
        else:
            f=df.copy()
            for k,v in cond.items():
                if k in df.columns:
                    f=f[f[k].astype(str).str.contains(v,na=False)]
            results=f.reset_index()[["index","프로그램명칭"]].dropna().to_dict("records")

    return render_template_string(
        DESC_HTML,
        style=BASE_STYLE,
        query=query,
        results=results,
        message=message,
        cond_display=cond_display
    )

if __name__=="__main__":
    app.run(debug=True)
