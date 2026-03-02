from flask import Flask, render_template_string, request, jsonify, redirect, url_for, session
import pandas as pd
import os
import re
import json

from dotenv import load_dotenv
load_dotenv()

from openai import OpenAI

app = Flask(__name__)
app.secret_key = "super_secret_key"

FILE_PATH = "service_resources.xlsx"

# =========================
# 로그인 체크
# =========================
def login_required():
    if not session.get("logged_in"):
        return redirect(url_for("login"))
    return None

# =========================
# 로그인 페이지
# =========================
LOGIN_HTML = """
<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>사용자 로그인</title>
<style>
body{
  font-family:'Pretendard',sans-serif;
  background:#f7f9fc;
  display:flex;
  justify-content:center;
  align-items:center;
  height:100vh;
  margin:0;
}
.box{
  background:white;
  padding:40px;
  border-radius:14px;
  box-shadow:0 10px 30px rgba(0,0,0,.1);
  width:360px;
  text-align:center;
}
input, button{
  width:100%;
  height:48px;
  padding:0 12px;
  border-radius:8px;
  font-size:16px;
  box-sizing:border-box;
}
input{
  border:1px solid #ccc;
  margin-top:10px;
}
button{
  margin-top:15px;
  border:none;
  background:#0078d7;
  color:white;
  cursor:pointer;
}
button:hover{ opacity:0.95; }
.footer{
  margin-top:28px;
  font-size:12px;
  color:#555;
  line-height:1.5;
}
.ci{
  margin-top:28px;
}
.error{ color:red; margin-top:10px; }
</style>
</head>
<body>
<div class="box">
<h2>사용자 로그인</h2>
<form method="post">
<input type="password" name="password" placeholder="비밀번호 입력">
<button type="submit">로그인</button>
</form>

<div class="footer">
※ 본 서비스는 국민건강보험공단 광주전라제주지역본부 <br>
관할 지자체, 지사 직원만 이용가능합니다.
</div>

<div class="ci">
<img src="/static/ci.png" width="280">
</div>

{% if error %}
<div class="error">비밀번호가 올바르지 않습니다.</div>
{% endif %}
</div>
</body>
</html>
"""

@app.route("/", methods=["GET","POST"])
def login():
    if request.method == "POST":
        if request.form.get("password") == "admin":
            session["logged_in"] = True
            return redirect(url_for("home"))
        return render_template_string(LOGIN_HTML, error=True)
    return render_template_string(LOGIN_HTML, error=False)

# =========================
# 공통 CSS
# =========================
BASE_STYLE = """
*{box-sizing:border-box;}
body{font-family:'Pretendard',sans-serif;margin:0;padding:20px;background:#f7f9fc;}
.container{max-width:600px;margin:auto;}

h1,h2{ text-align:center; color:#2c3e50; }
h3{ margin:18px 0 10px; color:#111827; }

button{
  width:100%;
  height:52px;
  border:none;
  border-radius:8px;
  font-size:18px;
  cursor:pointer;
  margin-top:15px;
}

.menu-btn{
  background:#0078d7;
  color:white;
}
.menu-btn:hover{opacity:0.95;}

.pdf-btn{
  width:100%;
  height:52px;
  background:#ffffff;
  color:#2c3e50;
  border:1px solid #ccc;
  display:flex;
  align-items:center;
  justify-content:center;
  gap:12px;
  border-radius:8px;
  cursor:pointer;
}
.pdf-btn:hover{background:#f1f5f9;}
.pdf-btn img{width:36px; height:auto;}

input,select,textarea{
  width:100%;
  padding:12px;
  font-size:16px;
  border-radius:8px;
  border:1px solid #ccc;
  margin-top:5px;
}

.home-btn{
  display:inline-block;
  background:#2c3e50;
  color:white;
  padding:10px 16px;
  border-radius:6px;
  margin-bottom:20px;
  text-decoration:none;
}

.result{
  margin-top:30px;
  background:white;
  padding:20px;
  border-radius:8px;
  box-shadow:0 2px 6px rgba(0,0,0,0.1);
}

.item{cursor:pointer;color:#0078d7;margin-top:6px;margin-left:10px;}
.small{font-size:13px;color:#6b7280;margin-top:6px;}

.choice-btn{
  width:100%;
  margin-top:10px;
  height:48px;
  padding:0 12px;
  border-radius:10px;
  border:1px solid #cfd8e3;
  background:#ffffff;
  cursor:pointer;
  font-size:16px;
  color:#111827;
}
.choice-btn:hover{ background:#f1f5f9; }
"""

# =========================
# 엑셀 로드 + 컬럼 공백 제거
# =========================
df = pd.read_excel(FILE_PATH).fillna("")
df.columns = df.columns.astype(str).str.replace(" ", "").str.strip()
print("현재 컬럼명:", list(df.columns))

# =========================
# HOME
# =========================
HOME_HTML = """
<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>지자체 서비스자원 검색 시스템</title>
<style>{{style}}</style>
</head>
<body>
<div class="container">
<h1>🏛 지자체 서비스자원 검색 시스템</h1>

<a href="/combo" style="text-decoration:none;display:block;">
  <button class="menu-btn">① 통합돌봄 자원검색(선택형)</button>
</a>

<a href="/desc" style="text-decoration:none;display:block;">
  <button class="menu-btn">② 통합돌봄 자원검색(서술형)</button>
</a>

<a href="/care" style="text-decoration:none;display:block;">
  <button class="menu-btn">③ 통합돌봄 사전조사</button>
</a>

<a href="/guide" style="text-decoration:none;display:block;">
  <button class="pdf-btn">
    <img src="/static/pdf_icon.png" alt="PDF">
    사업안내 보기
  </button>
</a>

<img src="/static/bottom.png" style="width:100%;margin-top:-20px;">
</div>
</body>
</html>
"""

@app.route("/home")
def home():
    check = login_required()
    if check:
        return check
    return render_template_string(HOME_HTML, style=BASE_STYLE)

@app.route("/guide")
def guide():
    check = login_required()
    if check:
        return check
    return '<iframe src="/static/guide.pdf" width="100%" height="100%" style="border:none;height:100vh;"></iframe>'

# =========================
# 상세 API (팝업에서 사용)
# =========================
@app.route("/detail/<int:idx>")
def detail(idx):
    check = login_required()
    if check:
        return check

    if idx < 0 or idx >= len(df):
        return jsonify({
            "프로그램명칭": "데이터가 변경되었습니다",
            "서비스제공기관명": "다시 검색해주세요",
            "기관연락처": "",
            "기관주소": "",
            "기타": ""
        })

    r = df.iloc[idx]
    return jsonify({
        "프로그램명칭": str(r.get("프로그램명칭", "")),
        "서비스제공기관명": str(r.get("서비스제공기관명", "")),
        "기관연락처": str(r.get("기관연락처", "")),
        "기관주소": str(r.get("기관주소", "")),
        "기타": str(r.get("기타", "")),
    })

@app.route("/combo", methods=["GET","POST"])
def combo():
    check = login_required()
    if check:
        return check

    region = (request.values.get("region","") or "").strip()
    main_category = (request.values.get("main_category","") or "").strip()
    health_kw = (request.values.get("health_kw","") or "").strip()

    if region == "나주":
        region = "나주시"

    results = {}

    if request.method == "POST":
        filtered = df.copy()

        if region:
            filtered = filtered[
                filtered["시군구"].astype(str)
                .str.contains(region, na=False)
            ]

        if main_category:
            filtered = filtered[
                filtered["대분류"].astype(str) == main_category
            ]

        if health_kw:
            filtered = filtered[
                filtered["건강상태"].astype(str)
                .str.contains(health_kw, na=False)
            ]

        for _, row in filtered.reset_index().iterrows():
            sigungu = str(row.get("시군구","")) or "기타"
            results.setdefault(sigungu, []).append({
                "index": int(row["index"]),
                "label": f"{row.get('프로그램명칭','')} ({row.get('서비스제공기관명','')})"
            })

    return render_template_string(
        COMBO_HTML,
        style=BASE_STYLE,
        region=region,
        main_category=main_category,
        health_kw=health_kw,
        results=results
    )



# =========================
# ① 선택형 검색
# =========================
COMBO_HTML = """
<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>통합돌봄 자원검색(선택형)</title>
<style>{{style}}</style>
</head>
<body>
<div class="container">
<a href="/home" class="home-btn">← 홈으로</a>
<h2>통합돌봄 자원검색(선택형)</h2>

<form method="post">
<label>지역(시군구)</label>
<input name="region" value="{{region}}" placeholder="예) 나주시">
<div class="small">※ 예: '나주' 입력 시 자동으로 '나주시'로 검색됩니다.</div>

<label>대분류</label>
<select name="main_category">
  <option value="">무관</option>
  {% for c in ["보건의료","생활지원","요양","주거지원"] %}
  <option value="{{c}}" {% if c==main_category %}selected{% endif %}>{{c}}</option>
  {% endfor %}
</select>

<label>건강상태</label>
<input name="health_kw" value="{{health_kw}}" placeholder="예) 고혈압">

<button type="submit" class="menu-btn">검색하기</button>
</form>

{% if results %}
<div class="result">
{% for region,items in results.items() %}
<h3>📍 {{region}}</h3>
{% for r in items %}
<div class="item" onclick="openDetail({{r['index']}})">- {{r['label']}}</div>
{% endfor %}
{% endfor %}
</div>
{% endif %}
</div>

<!-- 팝업 -->
<div id="modal" style="display:none;position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,.5);">
  <div style="background:white;margin:5% auto;padding:20px;width:90%;max-width:520px;border-radius:10px;">
    <h3 id="m_title"></h3>
    <p><b>기관명:</b> <span id="m_org"></span></p>
    <p>
        <b>기관 연락처:</b> <span id="m_tel"></span>
        <a id="tel_link" style="display:none; font-size:20px; margin-left:8px; text-decoration:none;">📞</a>
    </p>
    <p><b>기관주소:</b> <span id="m_addr"></span></p>
    <p><b>기타:</b> <span id="m_other"></span></p>
    <iframe id="m_map" width="100%" height="250" style="border:0;margin-top:10px;"></iframe>
    <button onclick="closeModal()" class="menu-btn">닫기</button>
  </div>
</div>

<script>
function openDetail(idx){
  fetch("/detail/"+idx)
    .then(r=>r.json())
    .then(d=>{
      document.getElementById("m_title").innerText = d["프로그램명칭"] || "";
      document.getElementById("m_org").innerText   = d["서비스제공기관명"] || "";
      document.getElementById("m_tel").innerText   = d["기관연락처"] || "";
      document.getElementById("m_addr").innerText  = d["기관주소"] || "";
      document.getElementById("m_other").innerText = d["기타"] || "";

      const addr = d["기관주소"] || "";
      document.getElementById("m_map").src =
        "https://www.google.com/maps?q=" + encodeURIComponent(addr) + "&output=embed";

      document.getElementById("modal").style.display="block";
    });
}
function closeModal(){
  document.getElementById("modal").style.display="none";
}
</script>

</body>
</html>
"""

@app.route("/desc", methods=["GET","POST"])
def desc():
    check = login_required()
    if check:
        return check

    query = ""
    results = {}
    cond_display = None
    count = 0

    if request.method == "POST":
        query = (request.form.get("query") or "").strip()
        cond_display = []

        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            cond_display.append("OPENAI_API_KEY가 설정되어 있지 않습니다.")
            return render_template_string(
                DESC_HTML,
                style=BASE_STYLE,
                query=query,
                results={},
                cond_display=cond_display,
                count=0
            )

        client = OpenAI(api_key=api_key)

        prompt = f"""
너는 통합돌봄 자원검색 시스템의 자연어 조건 분석기다.
반드시 JSON만 출력한다.
설명, 문장, 코드블록, 주석 절대 출력하지 마라.
JSON 외 다른 텍스트를 출력하면 안 된다.

[목표]
사용자의 문장에서 조건을 최대한 정확하게 추출한다.

[출력 형식 - 반드시 이 형식만]
{{
  "시군구": string|null,
  "대분류": "보건의료"|"생활지원"|"요양"|"주거지원"|null,
  "건강상태": string|null
}}

[중요 규칙]

1. 문장에 지역명이 포함되어 있으면 반드시 "시군구"에 채워라.
2. null은 정말 아무 단서도 없을 때만 사용하라.
3. 최소 하나 이상의 값은 반드시 채워라.
4. "어르신", "노인", "고령자"는 조건에 영향 없음.
5. "거동"과 "불편"이 함께 있으면 반드시 "거동불편"으로 출력하라.
6. 건강 관련 단어가 있으면 반드시 건강상태에 반영하라.
7. 대분류 단어(요양, 의료, 주거, 생활 등)가 있으면 반드시 대분류에 매칭하라.

[시군구 변환 규칙]

※ 광주광역시
- 광주 → 광주광역시
- 동구 → 광주광역시 동구
- 서구 → 광주광역시 서구
- 남구 → 광주광역시 남구
- 북구 → 광주광역시 북구
- 광산구 → 광주광역시 광산구

※ 전라남도
- 목포 → 목포시
- 여수 → 여수시
- 순천 → 순천시
- 나주 → 나주시
- 광양 → 광양시
- 담양 → 담양군
- 곡성 → 곡성군
- 구례 → 구례군
- 고흥 → 고흥군
- 보성 → 보성군
- 화순 → 화순군
- 장흥 → 장흥군
- 강진 → 강진군
- 해남 → 해남군
- 영암 → 영암군
- 무안 → 무안군
- 함평 → 함평군
- 영광 → 영광군
- 장성 → 장성군
- 완도 → 완도군
- 진도 → 진도군
- 신안 → 신안군

※ 전라북도
- 전주 → 전주시
- 군산 → 군산시
- 익산 → 익산시
- 정읍 → 정읍시
- 남원 → 남원시
- 김제 → 김제시
- 완주 → 완주군
- 진안 → 진안군
- 무주 → 무주군
- 장수 → 장수군
- 임실 → 임실군
- 순창 → 순창군
- 고창 → 고창군
- 부안 → 부안군

[예시]

입력: 나주에 사는 거동불편 어르신
출력:
{{
  "시군구": "나주시",
  "대분류": null,
  "건강상태": "거동불편"
}}

입력: 영암 요양 서비스
출력:
{{
  "시군구": "영암군",
  "대분류": "요양",
  "건강상태": null
}}

입력 문장:
{query}
"""

        data = {"시군구": None, "대분류": None, "건강상태": None}

        try:
            res = client.chat.completions.create(
                model="gpt-4.1-mini",
                messages=[{"role":"user","content":prompt}],
                temperature=0
            )

            text = res.choices[0].message.content
            print("GPT 원문:", text)   # ✅ 이 줄 추가
            m = re.search(r"\{.*\}", text, re.S)

            if m:
                parsed = json.loads(m.group())
                data["시군구"] = parsed.get("시군구")
                data["대분류"] = parsed.get("대분류")
                data["건강상태"] = parsed.get("건강상태")

        except Exception as e:
            cond_display.append(f"GPT 오류: {e}")


        # 후처리
        if data.get("시군구"):
            data["시군구"] = normalize_sigungu(data["시군구"])
            cond_display.append(f"시군구: {data['시군구']}")

        if data.get("대분류"):
            cond_display.append(f"대분류: {data['대분류']}")

        if data.get("건강상태"):
            data["건강상태"] = normalize_health(data["건강상태"])
            cond_display.append(f"건강상태: {data['건강상태']}")

        # 🔎 필터링
        filtered = df.copy()

        if data.get("시군구"):
            filtered = filtered[
                filtered["시군구"].astype(str)
                .str.contains(str(data["시군구"]), na=False)
            ]

        if data.get("대분류"):
            filtered = filtered[
                filtered["대분류"].astype(str) == str(data["대분류"])
            ]

        if data.get("건강상태"):
            filtered = filtered[
                filtered["건강상태"].astype(str)
                .str.contains(str(data["건강상태"]), na=False)
            ]

        # 🔎 그룹핑
        grouped = {}

        for _, row in filtered.reset_index().iterrows():
            sigungu = str(row.get("시군구","")) or "기타"

            grouped.setdefault(sigungu, []).append({
                "index": int(row["index"]),
                "label": f"{row.get('프로그램명칭','')} ({row.get('서비스제공기관명','')})"
            })

        results = grouped
        count = sum(len(v) for v in grouped.values())

    return render_template_string(
        DESC_HTML,
        style=BASE_STYLE,
        query=query,
        results=results,
        cond_display=cond_display,
        count=count
    )
# =========================
# ② 서술형 검색 (GPT 기반) + 팝업/지도 포함
# =========================
DESC_HTML = """
<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>통합돌봄 자원검색(서술형)</title>
<style>{{style}}</style>
</head>
<body>
<div class="container">
<a href="/home" class="home-btn">← 홈으로</a>
<h2>통합돌봄 자원검색(서술형)</h2>

<form method="post">
<textarea name="query" placeholder="예: 담양에 거동불편한 어르신이 이용가능한 서비스">{{query}}</textarea>
<button type="submit" class="menu-btn">검색하기</button>
</form>

{% if cond_display is not none %}
<div class="result">

{% if cond_display %}
<p><b>이 조건으로 검색했습니다</b></p>
<ul>
{% for c in cond_display %}
<li>✔ {{c}}</li>
{% endfor %}
</ul>
<hr>
{% endif %}

<p><b>{{count}}건이 조회되었습니다.</b></p>

{% if count == 0 %}
<p style="color:#6b7280;">조건에 맞는 서비스가 없습니다.</p>
{% endif %}

{% for region,items in results.items() %}
<h3>📍 {{region}}</h3>
{% for r in items %}
<div class="item" onclick="openDetail({{r['index']}})">- {{r['label']}}</div>
{% endfor %}
{% endfor %}

</div>
{% endif %}

<!-- 팝업 -->
<div id="modal" style="display:none;position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,.5);">
  <div style="background:white;margin:5% auto;padding:20px;width:90%;max-width:520px;border-radius:10px;">
    <h3 id="m_title"></h3>
    <p><b>기관명:</b> <span id="m_org"></span></p>
    <p>
        <b>기관 연락처:</b> <span id="m_tel"></span>
        <a id="tel_link"
             style="display:none; font-size:20px; margin-left:8px; text-decoration:none;">
             📞
        </a>
</p>
    <p><b>기관주소:</b> <span id="m_addr"></span></p>
    <p><b>기타:</b> <span id="m_other"></span></p>
    <iframe id="m_map" width="100%" height="250" style="border:0;margin-top:10px;"></iframe>
    <button onclick="closeModal()" class="menu-btn">닫기</button>
  </div>
</div>

<script>
function openDetail(idx){
  fetch("/detail/"+idx)
    .then(r=>r.json())
    .then(d=>{
      document.getElementById("m_title").innerText = d["프로그램명칭"] || "";
      document.getElementById("m_org").innerText   = d["서비스제공기관명"] || "";
      document.getElementById("m_tel").innerText   = d["기관연락처"] || "";
      document.getElementById("m_addr").innerText  = d["기관주소"] || "";
      document.getElementById("m_other").innerText = d["기타"] || "";

      const addr = d["기관주소"] || "";
      document.getElementById("m_map").src =
        "https://www.google.com/maps?q=" + encodeURIComponent(addr) + "&output=embed";

// 📞 모바일에서만 전화 아이콘 활성화
function isMobile(){
  return /Android|iPhone|iPad|iPod/i.test(navigator.userAgent);
}

const telLink = document.getElementById("tel_link");
const tel = d["기관연락처"] || "";

if(isMobile() && tel){
  const numMatch = tel.match(/[0-9-]+/);
  if(numMatch){
    telLink.href = "tel:" + numMatch[0];
    telLink.style.display = "inline";
  } else {
    telLink.style.display = "none";
  }
} else {
  telLink.style.display = "none";
}

      document.getElementById("modal").style.display="block";
    });
}
function closeModal(){
  document.getElementById("modal").style.display="none";
}
</script>

</body>
</html>
"""

def normalize_sigungu(text: str) -> str:
    if not text:
        return ""
    t = str(text).strip()
    mapping = {"나주":"나주시", "목포":"목포시", "영암":"영암군"}
    if t in mapping:
        return mapping[t]
    return t

def normalize_health(text: str) -> str:
    if not text:
        return ""

    t = str(text).strip()

    # 공백 제거
    t = t.replace(" ", "")

    # 불필요 단어 제거
    t = t.replace("어르신", "")
    t = t.replace("노인", "")
    t = t.replace("고령자", "")

    # 거동불편 변형 통합
    if "거동" in t and "불편" in t:
        return "거동불편"

    return t


# =========================
# ③ 사전조사 (UI 유지)
# =========================
CARE_QUESTIONS = [
    "의자나 소파에서 걸터앉은 상태에서 무릎을 짚고 일어설 수 있습니까?",
    "집안에서 6걸음을 이동할 수 있습니까?",
    "등을 제외한 몸 전체를 씻을 수 있습니까?",
    "상의 입고 단추를 잠글 수 있습니까?",
    "하의를 입고 지퍼를 올릴 수 있습니까?",
    "소변실수를 하지 않고 화장실에 갈 수 있습니까?",
    "화장실에서 변기에 앉아 용변을 볼 수 있습니까?"
]

CARE_HTML = """
<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>통합돌봄 사전조사</title>
<style>{{style}}</style>
</head>
<body>
<div class="container">
<a href="/home" class="home-btn">← 홈으로</a>
<h2>통합돌봄 사전조사</h2>

<form id="careForm">
<label>치매 관련 약 복용 여부</label>
<select name="dementia" required>
  <option value="">선택</option>
  <option value="y">예</option>
  <option value="n">아니오</option>
</select>

<hr>

{% for i,q in questions %}
<label>{{i+1}}. {{q}}</label>
<select name="q{{i}}" required>
  <option value="">선택</option>
  <option value="0">도움 없이 가능</option>
  <option value="1">보조도구/준비 필요</option>
  <option value="2">타인 도움 필요</option>
</select>
{% endfor %}

<button type="submit" class="menu-btn">검사하기</button>
</form>
</div>

<!-- 결과 팝업 -->
<div id="resultModal" style="display:none;position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,.5)">
  <div style="background:white;margin:10% auto;padding:25px;width:90%;max-width:420px;border-radius:12px;text-align:center">
    <h3>사전조사 결과</h3>
    <p id="r_text" style="font-size:20px;font-weight:bold"></p>
    <p id="r_score"></p>

    <div style="margin-top:18px;text-align:left;">
      <b>빠른 검색</b>
      <div class="small" style="margin-top:6px;">※ 아래 버튼을 눌러 바로 검색할 수 있습니다.</div>

      <button class="choice-btn" onclick="goToDementia(event)">건강상태 '치매' 검색</button>
      <button class="choice-btn" onclick="goToMedical(event)">대분류 '보건의료' 검색</button>
    </div>

    <button style="margin-top:15px;" onclick="closeModal()" class="menu-btn">닫기</button>
  </div>
</div>

<script>
function closeModal(){
  document.getElementById("resultModal").style.display="none";
}
function goToDementia(e){
  e.preventDefault();
  window.location.href = "/combo?health_kw=치매";
}
function goToMedical(e){
  e.preventDefault();
  window.location.href = "/combo?main_category=보건의료";
}

document.getElementById("careForm").onsubmit = async function(e){
  e.preventDefault();
  const formData = new FormData(this);

  const res = await fetch("/care_check", { method:"POST", body:formData });
  const data = await res.json();

  document.getElementById("r_text").innerText = data.result;
  document.getElementById("r_score").innerText = "총점: " + data.score;

  document.getElementById("resultModal").style.display="block";
}
</script>
</body>
</html>
"""

@app.route("/care")
def care():
    check = login_required()
    if check:
        return check
    return render_template_string(
        CARE_HTML,
        style=BASE_STYLE,
        questions=list(enumerate(CARE_QUESTIONS))
    )

@app.route("/care_check", methods=["POST"])
def care_check():
    check = login_required()
    if check:
        return check

    score = 0
    dementia = request.form.get("dementia", "n")

    for i in range(7):
        val = request.form.get(f"q{i}")
        if val is None or val == "":
            val = 0
        score += int(val)

    if dementia == "y":
        return jsonify({"result":"통합돌봄 지원 대상 (치매약 복용)","score":"검사 제외"})

    if score <= 1:
        result = "지원 대상 아님"
    elif score <= 3:
        result = "지자체 자체조사 대상"
    else:
        result = "통합판정조사 대상"

    return jsonify({"result":result,"score":score})

if __name__ == "__main__":
    app.run(debug=True)