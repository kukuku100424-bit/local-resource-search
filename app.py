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
# 서비스 그룹 엑셀 로드 (AI 추천용)
# =========================
SERVICE_GROUP_FILE = "service_group.xlsx"

service_df = pd.read_excel(SERVICE_GROUP_FILE).fillna("")
service_df.columns = service_df.columns.astype(str).str.replace(" ", "").str.strip()

print("서비스그룹 컬럼:", list(service_df.columns))

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
# =========================
# 로그인 페이지
# =========================
LOGIN_HTML = """
<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>케어네비 로그인</title>

<style>
*{ box-sizing:border-box; }

body{
  font-family:'Pretendard',sans-serif;
  background:#f2f4f7;
  display:flex;
  justify-content:center;
  align-items:center;
  min-height:100vh;
  margin:0;
  padding:20px;
}
/* 카드 */
.box{
  background:white;
  width:100%;
  max-width:460px;
  padding:30px 40px 40px 40px;
  border-radius:20px;
  box-shadow:0 15px 40px rgba(0,0,0,0.08);
  text-align:center;
}

/* 로고 */
.logo-wrapper{
  margin-bottom:-40px; /* 너무 겹치면 -20~0 으로 */
}

.logo-wrapper img{
  width:100%;
  max-width:440px;
  display:block;
  margin:0 auto;
}

/* 타이틀 */
.main-title{
  font-size:26px;
  font-weight:700;
  margin-top:0px;
}
.sub-title{
  font-size:15px;
  color:#666;
  margin-bottom:18px;
}

/* 에러 메시지 */
.error-msg{
  background:#fff1f2;
  color:#b91c1c;
  border:1px solid #fecdd3;
  padding:10px 12px;
  border-radius:10px;
  font-size:14px;
  margin:10px 0 14px 0;
  text-align:left;
}

/* 입력창 */
input{
  width:100%;
  padding:14px;
  border-radius:10px;
  border:1px solid #ddd;
  font-size:16px;
  margin-bottom:16px;
}

button{
  width:100%;
  padding:14px;
  border:none;
  border-radius:10px;
  background:#1e73be;
  color:white;
  font-size:16px;
  font-weight:600;
  cursor:pointer;
  transition:0.2s;
}
button:hover{ background:#155fa0; }

.notice{
  font-size:12px;
  color:#888;
  margin-top:22px;
  line-height:1.5;
}

@media (max-width:480px){

  .notice{
    font-size:12px;
    padding:6px;
  }

}

.bottom-logo img{
  width:100%;
  max-width:220px;
  margin-top:18px;
}

/* 모바일 */
@media (max-width: 480px){
  .main-title{ font-size:22px; }

  .logo-wrapper{
    margin-bottom:-20px;
  }

  .logo-wrapper img{
    max-width:260px;
    margin-bottom:10px;
  }

  .box{
    padding:34px 20px 28px 20px;
  }
}

</style>
</head>

<body>
<div class="box">

  <div class="logo-wrapper">
    <img src="/static/compass_logo.png" alt="케어네비 로고">
  </div>

  <div class="main-title">케어네비</div>
  <div class="sub-title">사용자 로그인</div>

  {% if error %}
    <div class="error-msg">❌ {{error}}</div>
  {% endif %}

  <form method="post" id="searchForm">
    <input type="password" name="password" placeholder="비밀번호 입력">
    <button type="submit">로그인</button>
  </form>


  <div class="notice">
    ※ 본 서비스는 국민건강보험공단 광주전라제주지역본부<br>
    관할 지자체, 지사 직원만 이용 가능합니다.
  </div>

  <div class="bottom-logo">
    <img src="/static/ci.png" style="width:260px;margin-top:15px;" alt="CI">
  </div>

</div>
</body>
</html>
"""

# =========================
# 로그인 라우트
# =========================
@app.route("/", methods=["GET", "POST"])
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        pw = request.form.get("password", "")

        if pw == "admin":  # 원하는 비밀번호
            session["logged_in"] = True
            return redirect(url_for("home"))
        else:
            # ✅ alert 대신 페이지 내부 에러 문구로 표시 (주소 안 뜸)
            return render_template_string(LOGIN_HTML, error="비밀번호가 올바르지 않습니다.")

    return render_template_string(LOGIN_HTML, error="")

# =========================
# 공통 CSS
# =========================
BASE_STYLE = """

body{
  margin:0;
  background:#f4f6fb;
  font-family:'Pretendard',sans-serif;
  color:#111827;
}

.container{
  max-width:700px;
  margin:auto;
  padding:10px 20px 20px 20px;   /* 👈 위만 줄임 */
}

h2{
  margin-top:0;
  margin-bottom:20px;
}

label{
  display:block;
  margin-top:14px;
  font-size:14px;
  font-weight:600;
}

input, select{
  width:100%;
  padding:12px;
  margin-top:6px;
  border-radius:8px;
  border:1px solid #d1d5db;
  font-size:14px;
}

.small{
  font-size:12px;
  color:#6b7280;
  margin-top:4px;
}

.menu-btn{
  margin-top:18px;
  width:100%;
  height:44px;
  border:none;
  border-radius:10px;
  background:#2563eb;
  color:white;
  font-size:15px;
  font-weight:600;
  cursor:pointer;
}

.menu-btn:hover{
  background:#1e40af;
}

.result{
  margin-top:24px;
  background:white;
  padding:20px;
  border-radius:14px;
  box-shadow:0 6px 18px rgba(0,0,0,0.08);
}

.item{
  padding:8px 0;
  cursor:pointer;
}

.item:hover{
  color:#2563eb;
}

.top-bar{
  margin-bottom:20px;
}

.home-button{
  display:inline-block;
  padding:8px 14px;
  border-radius:8px;
  background:#e5e7eb;
  color:#111827;
  text-decoration:none;
  font-size:14px;
  font-weight:500;
}

.home-button:hover{
  background:#d1d5db;
}

/* =========================
   모바일 최적화 (핵심)
========================= */
@media (max-width:480px){

  /* 전체 여백 줄이기 */
  .container{
    padding:12px 12px 20px 12px;
  }

  /* 타이틀 */
  h1{
    font-size:20px !important;
  }

  h2{
    font-size:18px !important;
  }

  /* 카드 */
  .card{
    padding:14px !important;
    gap:12px;
    border-radius:14px;
  }

  /* 아이콘 */
  .icon{
    width:42px;
    height:42px;
    font-size:20px;
  }

  /* 카드 텍스트 */
  .text b{
    font-size:14px;
  }

  .text span{
    font-size:12px;
    line-height:1.4;
    word-break:keep-all;   /* 🔥 핵심 */
  }

  /* 하단 카드 */
  .bottom-card{
    padding:12px;
    font-size:13px;
  }

  /* 버튼 */
  button, .menu-btn{
    height:48px;
    font-size:15px;
  }

  /* 입력창 */
  input, select, textarea{
    font-size:15px;
  }

  textarea{
    height:100px;
    line-height:1.5;
    word-break:keep-all;   /* 🔥 핵심 */
  }

  /* 안내문 */
  .notice{
    font-size:12px;
    line-height:1.5;
    padding:0 4px;
    word-break:keep-all;   /* 🔥 핵심 */
  }

  /* 결과 카드 */
  .result-card{
    padding:14px;
  }

  /* 홈 버튼 */
  .home-button{
    font-size:13px;
    padding:6px 12px;
  }

}


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
<title>통합돌봄 서비스 자원검색</title>

<style>

.bottom-img{
  width:100%;
  margin-top:-80px; }

@media (max-width:480px){

  .bottom-img{
    margin-top:-30px;   /* 🔥 -80 → -20으로 줄이기 */
  }

}


/* 전체 배경 */
body{
  margin:0;
  padding:0;
  background:#f4f6fb;
  font-family:'Pretendard',sans-serif;
  color:#111827;
}

/* 컨테이너 */
.container{
  max-width:700px;
  margin:auto;
  padding:30px 20px;
}

/* 타이틀 */
.title{
  text-align:center;
  margin-bottom:24px;
}

.title + .card{
  margin-top:30px;   /* 👈 여기 추가 */
}

.title h1{
  margin:0;
  font-size:26px;
}

.title p{
  margin-top:6px;
  color:#6b7280;
  font-size:14px;
}

/* 메뉴 카드 */
.card{
  display:flex;
  align-items:center;
  gap:16px;

  background:white;

  padding:16px;        /* 👈 20 → 16 (카드 높이 줄임) */

  border-radius:16px;

  margin-bottom:10px;  /* 👈 16 → 10 (카드 간격 줄임) */

  box-shadow:0 8px 20px rgba(0,0,0,0.08);

  text-decoration:none;
  color:inherit;

  transition:0.18s;
}

.card:hover{
  transform:translateY(-3px);
  box-shadow:0 14px 32px rgba(0,0,0,0.12);
}

/* 아이콘 */
.icon{
  width:50px;
  height:50px;

  border-radius:14px;

  background:#e8f1ff;

  display:flex;
  align-items:center;
  justify-content:center;

  font-size:24px;
}

/* 텍스트 */
.text{
  flex:1;
}

.text b{
  font-size:16px;
  display:block;
}

.text span{
  font-size:13px;
  color:#6b7280;
}

/* 하단 카드 */
.bottom-row{
  display:flex;
  gap:12px;
  margin-top:10px;
  margin-bottom:12px;   /* 🔥 이거 추가 */
}
.bottom-card{
  flex:1;

  background:white;

  border-radius:14px;

  padding:16px;

  text-align:center;

  text-decoration:none;

  color:#111827;

  box-shadow:0 6px 16px rgba(0,0,0,0.08);

  transition:0.15s;
}

.bottom-card:hover{
  transform:translateY(-2px);
}

.bottom-card img{
  width:30px;
  margin-bottom:6px;
}

.bottom-card div{
  font-size:14px;
}

/* 모바일 */
@media (max-width:480px){

  .title h1{
    font-size:22px;
  }

  .card{
    padding:16px;
  }

  .icon{
    width:44px;
    height:44px;
    font-size:20px;
  }

}

</style>
</head>

<body>

<div class="container">

<div class="title">
<h1>NHIS-G 케어네비</h1>
<p>국민건강보험공단 통합돌봄 지원 시스템</p>
</div>

<a href="/desc" class="card">

<div class="icon">🤖</div>

<div class="text">
<b>사례기반 서비스내용 검색 (AI)</b>
<span>입력한 사례를 분석하여 적합한 통합돌봄 서비스를 추천합니다</span>
</div>

</a>

<a href="/combo" class="card">

<div class="icon">🔎</div>

<div class="text">
<b>조건기반 자원검색</b>
<span>지역, 건강상태, 관리기관 조건으로 서비스 자원을 검색합니다</span>
</div>

</a>

<a href="/care" class="card">

<div class="icon">📝</div>

<div class="text">
<b>통합돌봄 사전조사</b>
<span>일상생활 수행능력(ADL) 기반 사전조사를 진행합니다</span>
</div>

</a>

<div class="bottom-row">

<a href="/guide" target="_blank" class="bottom-card">

<img src="/static/pdf_icon.png">

<div>사업 안내</div>

</a>

<a href="/nhis25" class="bottom-card">

<img src="/static/nhis_heart.png">

<div>건강보험 25시</div>

</a>

</div>

<img src="/static/bottom.png" class="bottom-img">

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
    return redirect("/static/guide.pdf")
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
    manager = (request.values.get("manager","") or "").strip()

    if region == "나주":
        region = "나주시"

    results = {}
    count = 0

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

        if manager and "관리주체" in filtered.columns:
            filtered = filtered[
                filtered["관리주체"].astype(str) == manager
            ]

        if health_kw and "건강상태" in filtered.columns:
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

        count = sum(len(v) for v in results.values())

    return render_template_string(
        COMBO_HTML,
        style=BASE_STYLE,
        region=region,
        main_category=main_category,
        health_kw=health_kw,
        manager=manager,   # ← 이 줄 추가
        results=results,
        count=count
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
<title>조건기반 자원검색</title>
<style>{{style}}</style>
<style>
input, select{
  width:100%;
  padding:12px;
  border-radius:8px;
  border:1px solid #d1d5db;
  font-size:14px;

  box-sizing:border-box;   /* 🔥 핵심 */
}

/* 🔥 모바일에서 높이 통일 */
@media (max-width:480px){
  input, select{
    height:44px;
    font-size:15px;
  }
}

/* 기존 */
@media (min-width: 768px) {
  #tel_link {
    display: none !important;
  }
}
</style>
</head>
<body>
<div class="container">
<div class="top-bar">
<a href="/home" class="home-button">홈으로</a>
</div>

<div class="card">
<h2>조건기반 자원검색</h2>

<form method="post">
<label>지역(시군구)</label>
<input type="text" name="region" value="{{region}}" placeholder="예) 나주시">

<div class="small">※ 예: '나주' 입력 시 자동으로 '나주시'로 검색됩니다.</div>

<label>대분류</label>
<select name="main_category">
  <option value="">전체</option>
  {% for c in ["보건의료","생활지원","요양","주거지원"] %}
  <option value="{{c}}" {% if c==main_category %}selected{% endif %}>{{c}}</option>
  {% endfor %}
</select>

<label>관리기관</label>
<select name="manager">
  <option value="">전체</option>
  {% for m in ["국민건강보험공단","지자체"] %}
  <option value="{{m}}" {% if m==manager %}selected{% endif %}>{{m}}</option>
  {% endfor %}
</select>

<label>건강상태</label>
<input type="text" name="health_kw" value="{{health_kw}}" placeholder="예) 고혈압">
<button type="submit" class="menu-btn">검색하기</button>
</form>

{% if request.method == "POST" %}
<div class="result">

<p><b>총 {{count}}건이 조회되었습니다.</b></p>

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
</div> 


<!-- 팝업 -->
<div id="modal" style="display:none;position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,.5);">
  <div style="background:white;margin:0% auto;padding:20px;width:90%;max-width:520px;border-radius:10px;max-height:85vh;overflow-y:auto;-webkit-overflow-scrolling:touch;">
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

      // 📞 전화버튼 항상 표시 (모바일/아이폰/안드로이드 모두 가능)
      const telLink = document.getElementById("tel_link");
      const tel = d["기관연락처"] || "";

      if(tel){
        const cleanNumber = tel.replace(/[^0-9]/g, "");
        if(cleanNumber){
          telLink.href = "tel:" + cleanNumber;
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

window.addEventListener("load", function(){

  const form = document.querySelector("form[method='post']");

  if(form){
    form.addEventListener("submit", function(e){

  const box = document.getElementById("loadingBox");

  if(box){
    box.style.display = "flex";
  }

  // 로딩창 보이게 0.2초 지연
  e.preventDefault();

  setTimeout(()=>{
    form.submit();
      },200);

    });
  }

});</script>
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
    service_results = []

    if request.method == "POST":

        query = (request.form.get("query") or "").strip()

        # ======================
        # 서비스 목록 문자열 생성
        # ======================
        # ======================
        # 서비스 1차 필터 (토큰 절약 + 정확도 상승)
        # ======================

        q = query.lower()

        candidate_rows = []

        for idx, r in service_df.iterrows():

            text = (
                str(r.get("서비스설명","")) +
                " " +
                str(r.get("검색어",""))
            ).lower()

            score = 0

            for word in q.split():

                if word in text:
                    score += 1

            candidate_rows.append((score, idx, r))

        # 점수 높은 순 정렬
        candidate_rows.sort(reverse=True)

        # 상위 25개만 사용
        candidate_rows = candidate_rows[:40]

        service_text = ""

        for score, idx, r in candidate_rows:

            desc = str(r.get('서비스설명',''))[:60]
            kw = str(r.get('검색어',''))[:30]

            service_text += f"""
        index:{idx}
        설명:{desc}
        키워드:{kw}
---
"""

        # ======================
        # 서비스 그룹 데이터 문자열 생성
        # ======================
# 서비스 1차 필터 (토큰 절약)
        cond_display = []

        api_key = os.getenv("OPENAI_API_KEY")

        if not api_key:
            cond_display.append("OPENAI_API_KEY가 설정되어 있지 않습니다.")
            return render_template_string(
                DESC_HTML,
                style=BASE_STYLE,
                query=query,
                results=results,
                cond_display=cond_display,
                count=count,
                service_results=service_results
            )

        client = OpenAI(api_key=api_key)

        prompt = f"""
너는 통합돌봄 서비스 추천 전문가다.

사용자의 사례를 분석하여
아래 서비스 목록 중에서 가장 유사한 서비스를
유사도가 높은 순서대로 최대 10개 추천한다.

반드시 유사도가 높은 순서대로 정렬해서 추천해야 한다.

반드시 JSON만 출력한다.

출력 형식

출력 형식

{{
  "results": [
    {{
      "index": "",
      "선택이유": ""
    }}
  ]
}}

추천 기준
1. 사용자 상황과의 의미적 유사성
2. 서비스설명과의 일치 정도
3. 검색어와의 관련성
4. 실제 통합돌봄 연계 가능성

주의사항
- 최대 10개만 추천한다.
- 가장 유사한 것을 1번으로 둔다.
- 불필요한 설명은 하지 말고 JSON만 출력한다.

서비스 목록

{service_text}

사용자 사례
{query}
"""

        try:

            res = client.responses.create(
                model="gpt-4.1-mini",
                input=prompt
            )
            if hasattr(res, "usage"):

                try:

                    print("입력 토큰:", res.usage.input_tokens)
                    print("출력 토큰:", res.usage.output_tokens)
                    print("총 토큰:", res.usage.total_tokens)

                except:

                    print("토큰 정보:", res.usage)
            text = res.output_text
            print("GPT 원문:", text)

            try:
                parsed = json.loads(text)

            except:
                match = re.search(r'\{.*\}', text, re.DOTALL)

                if match:
                    parsed = json.loads(match.group())
                else:
                    parsed = {"results":[]}

            service_results = parsed.get("results", [])[:10]

            final_results = []

            for r in service_results:

                idx = int(r.get("index", -1))

                if 0 <= idx < len(service_df):

                    row = service_df.iloc[idx]

                    final_results.append({
                        "대분류": row.get("대분류", ""),
                        "중분류": row.get("중분류", ""),
                        "서비스내용": row.get("서비스내용", ""),
                        "선택이유": r.get("선택이유", "")
                    })

            service_results = final_results

        except Exception as e:

            cond_display.append(f"GPT 오류: {e}")
        count = len(service_results)

    return render_template_string(
        DESC_HTML,
        style=BASE_STYLE,
        query=query,
        results=results,
        cond_display=cond_display,
        count=count,
        service_results=service_results
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
<title>사례기반 서비스내용 검색</title>

<style>

*{
  box-sizing: border-box;
}

.m-br{
  display:none;
}

@media (max-width:480px){
  .m-br{
    display:block;
  }
}

.loading-ci{
  width:160px;
  margin-top:18px;
  opacity:0.85;
}

.top-bar{
  margin-bottom:20px;
}

.home-button{
  display:inline-block;
  padding:8px 14px;
  border-radius:8px;
  background:#e5e7eb;
  color:#111827;
  text-decoration:none;
  font-size:14px;
  font-weight:500;
  transition:0.15s;
}

.home-button:hover{
  background:#d1d5db;
}


body{
  margin:0;
  background:#f4f6fb;
  font-family:'Pretendard',sans-serif;
  color:#111827;
}

.container{
  max-width:720px;
  margin:auto;
  padding:30px 20px;
}

/* 홈버튼 */
.home{
  display:inline-block;
  margin-bottom:20px;
  text-decoration:none;
  color:#2563eb;
  font-size:14px;
}

/* 제목 */
.title{
  text-align:center;
  margin-bottom:0;     /* 기존 제거 */
  padding-bottom:30px; /* 👈 이걸로 공간 만든다 */
}

.title h2{
  margin:0;
  font-size:24px;
}

/* 검색 카드 */
.search-box{
  background:white;
  padding:24px;
  border-radius:16px;
  box-shadow:0 8px 24px rgba(0,0,0,0.08);
}

/* 텍스트 입력 */
textarea{
  width:100%;
  height:110px;
  padding:14px;
  border-radius:10px;
  border:1px solid #d1d5db;
  font-size:15px;
  resize:none;

  line-height:1.5;         /* ✅ 줄 간격 안정 */
  word-break:keep-all;     /* ✅ 한글 끊김 방지 (핵심) */
  white-space:pre-wrap;    /* ✅ 줄바꿈 자연스럽게 */

}

textarea:focus{
  outline:none;
  border-color:#2563eb;
}

/* 버튼 */
button{
  width:100%;
  height:48px;
  margin-top:12px;
  border:none;
  border-radius:10px;
  background:linear-gradient(135deg,#3b82f6,#2563eb);
  color:white;
  font-size:16px;
  font-weight:600;
  cursor:pointer;
}

button:hover{
  opacity:0.9;
}

/* 설명 */
.notice{
  text-align:center;
  margin-top:14px;
  font-size:13px;
  color:#6b7280;
  line-height:1.6;
}

/* 결과 카드 */
.result{
  margin-top:24px;
}

.result-card{
  background:white;
  padding:18px;
  border-radius:14px;
  margin-bottom:12px;
  box-shadow:0 6px 18px rgba(0,0,0,0.08);
}

.result-card b{
  font-size:15px;
}

.reason{
  margin-top:6px;
  font-size:13px;
  color:#6b7280;
  line-height:1.6;
}

/* 로딩 */
.loading{
  display:none;
  position:fixed;
  inset:0;
  background:rgba(0,0,0,0.5);
  align-items:center;
  justify-content:center;
}

.loading-box{
  background:white;
  padding:30px;
  border-radius:14px;
  text-align:center;
}

.spinner{
  border:5px solid #eee;
  border-top:5px solid #2563eb;
  border-radius:50%;
  width:42px;
  height:42px;
  margin:auto;
  animation:spin 1s linear infinite;
}

@keyframes spin{
  0%{transform:rotate(0deg)}
  100%{transform:rotate(360deg)}
}

</style>
</head>

<body>

<div class="container">

<div class="top-bar">
<a href="/home" class="home-button">홈으로</a>
</div>

<div class="title">
<h2>사례기반 서비스내용 검색 (AI)</h2>
</div>

<div class="search-box">

<form method="post" id="searchForm">

<textarea name="query" placeholder="예) 관절염이 있고 정서적으로 고립된 어르신에게 필요한 서비스">{{query}}</textarea>

<button type="submit">AI 검색</button>

</form>

<div class="notice">
※ 입력한 사례와 유사한<br class="m-br"> <b>통합돌봄 서비스 최대 10가지</b>
를 추천합니다.<br>
지자체 통합지원 계획 수립 참고용입니다.
</div>


{% if service_results %}

<div class="result">

<h3>{{count}}건의 추천 서비스</h3>

{% for r in service_results %}

<div class="result-card">

<b>{{loop.index}}. {{r["대분류"]}} / {{r["중분류"]}} / {{r["서비스내용"]}}</b>

<div class="reason">
추천 이유: {{r["선택이유"]}}
</div>

</div>

{% endfor %}

</div>

{% endif %}

</div>


<div class="loading" id="loading">

  <div class="loading-box">

    <div class="spinner"></div>

    <p style="margin-top:12px;font-weight:600">
      AI가 사례를 분석 중입니다
    </p>

    <img src="/static/ci.png" class="loading-ci">

  </div>

</div>


<script>

document.getElementById("searchForm").addEventListener("submit",function(){

document.getElementById("loading").style.display="flex"

})

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

<style>

.dementia-options label{
  display:flex;
  align-items:center;
  gap:6px;
  white-space:nowrap;   /* 🔥 이거 추가 */
}

.dementia-options{
  display:flex;
  gap:24px;
  align-items:center;
  flex-wrap:nowrap;   /* 줄바꿈 방지 */
}

/* ====== 사전조사 전용 스타일 ====== */

.top-bar{
  margin-bottom:20px;
}

.home-button{
  display:inline-block;
  padding:8px 14px;
  border-radius:8px;
  background:#e5e7eb;
  color:#111827;
  text-decoration:none;
  font-size:14px;
  font-weight:500;
}

.home-button:hover{
  background:#d1d5db;
}

/* PC에서만 줄바꿈 */
.pc-br{
  display:inline;
}

/* 모바일에서는 줄바꿈 제거 */
@media (max-width:480px){
  .pc-br{
    display:none;
  }
}

.options{
  margin-top:12px;
  display:flex;
  flex-direction:column;
  gap:10px;
}

.options label{
  display:flex;
  align-items:center;
  gap:10px;
  cursor:pointer;
}

.options input[type=radio]{
  width:auto !important;
  flex:0 0 auto;
  transform:scale(1.1);
}

.question-box{
  background:#f5faff;              /* ✅ 기본 파란톤 배경 복구 */
  padding:22px;
  border-radius:12px;
  margin-top:18px;
  box-shadow:0 2px 6px rgba(0,0,0,0.08);
  border:1px solid #dbeafe;
}

.question-box.active{
  border:2px solid #1e73be;
  background:#eaf4ff;
}

.dementia-box{
  background:#fff7ed;
  padding:18px;
  border-radius:10px;
  margin-top:15px;
  border:1px solid #fed7aa;
}

.dementia-options{
  display:flex;
  gap:30px;
  margin-top:10px;
}

/* 모바일에서 치매 선택 박스가 답답하면 줄바꿈 */
@media (max-width:480px){
  .dementia-options{ gap:18px; }
}
@media (max-width:480px){

  #resultModal{
    padding-top:0 !important;
  }

  #resultModal > div{
    top:2% !important;
  }

}

</style>
</head>

<body>
<div class="container">

<div class="top-bar">
  <a href="/home" class="home-button">홈으로</a>
</div>

<h2>통합돌봄 사전조사</h2>

  <form id="careForm">
    <div class="dementia-box">
      <b>치매 관련 약 복용 여부</b>

      <div class="dementia-options">
        <label>
          <input type="radio" name="dementia" value="y">
          예
        </label>

        <label>
          <input type="radio" name="dementia" value="n">
          아니오
        </label>
      </div>
    </div>

    <div id="adlSection">
      {% for i,q in questions %}
      <div class="question-box">
        <b>{{i+1}}) {{q}}</b>

        <div class="options">
          <label>
            <input type="radio" name="q{{i}}" value="0">
            도움 없이 혼자서 수행 가능 (0점)
          </label>

          <label>
            <input type="radio" name="q{{i}}" value="1">
            보조도구(지팡이 등)를 잡고 수행 가능 (1점)
          </label>

          <label>
            <input type="radio" name="q{{i}}" value="2">
            타인이 도와줘야 수행 가능 (2점)
          </label>
        </div>
      </div>
      {% endfor %}

      <button type="submit" class="menu-btn">검사하기</button>
    </div>
  </form>

</div>

<!-- 결과/안내 팝업 -->
<div id="resultModal"
     style="display:none;position:fixed;inset:0;
            background:rgba(0,0,0,.5);z-index:999;
            padding-top:6vh; overflow:auto; -webkit-overflow-scrolling:touch;">

  <div style="background:white;
            margin:0 auto;
            position:absolute;
            top:8%;
            left:0;
            right:0;
            padding:18px 22px 22px 22px;
            width:92%;
            max-width:460px;
            border-radius:14px;
            text-align:center;
            box-shadow:0 10px 25px rgba(0,0,0,0.15)">
    <h3 id="modalTitle" style="margin-top:0;margin-bottom:12px;">사전조사 결과 안내</h3>

    <div style="background:#f4f8ff;border-radius:10px;padding:14px;margin-bottom:18px">
      <p id="r_text" style="font-size:18px;line-height:1.6;margin:0"></p>
    </div>

    <div style="text-align:left;font-size:14px;line-height:1.6;color:#444;
                background:#fafafa;padding:14px;border-radius:8px">
      <b>통합돌봄 지원 기준</b><br><br>

      ① 치매약 복약 중인 경우<br>
      → 일상생활 수행능력과 관계없이 통합돌봄 지원 대상<br><br>

      ② 일상생활수행능력(ADL) 점수 기준<br>
      • 0~1점 : 지자체 사업 안내 후 종결<br>
      • 2~3점 : 지자체 자체조사 후 지원 검토<br>
      • 4점 이상 : 통합판정조사 대상<br><br>

      <span style="font-size:12px;color:#666;">
        ※ 본 결과는 통합돌봄 서비스 안내를 위한 참고용 사전조사입니다.<br>
        최종 지원 여부는 지자체 및 공단의 추가 조사 후 결정됩니다.
      </span>
    </div>

    <button onclick="closeModal()" class="menu-btn" style="margin-top:22px">확인</button>
  </div>
</div>

<script>
/* ====== 공통 팝업 열기 ====== */
function showGuide(messageHtml){
  document.getElementById("modalTitle").innerText = "안내";
  document.getElementById("r_text").innerHTML = messageHtml;
  document.getElementById("resultModal").style.display = "block";
}

function showResult(title, messageText){
  document.getElementById("modalTitle").innerText = title;
  document.getElementById("r_text").innerText = messageText;
  document.getElementById("resultModal").style.display = "block";
}

function closeModal(){
  document.getElementById("resultModal").style.display="none";
}

/* ====== 1) 치매 선택 안 했는데 ADL 누르면 '차단' ====== */
document.querySelectorAll('#adlSection .options input[type="radio"]').forEach(radio => {
  radio.addEventListener("change", function(){
    const dementia = document.querySelector('input[name="dementia"]:checked');

    if(!dementia){
      // ✅ ADL 선택 자체를 취소하고 안내
      this.checked = false;
      showGuide("먼저 <b>치매 관련 약 복용 여부(예/아니오)</b>를<br> 선택해주세요.");
      return;
    }

    // 치매 선택이 되어 있으면 카드 강조
    const box = this.closest(".question-box");
    if(box) box.classList.add("active");
  });
});

/* ====== 2) 치매 '예'면 즉시 안내 팝업 + ADL 흐리게 ====== */
document.querySelectorAll('input[name="dementia"]').forEach(radio=>{
  radio.addEventListener("change",function(){
    if(this.value === "y"){
      document.getElementById("adlSection").style.opacity="0.4";
      showGuide("치매약을 복약 중인 경우 일상생활 수행능력과 관계없이 <b>통합돌봄 대상</b>입니다.");
    }else{
      document.getElementById("adlSection").style.opacity="1";
    }
  });
});

/* ====== 3) 검사하기 클릭 시: 치매 미선택이면 막기 ====== */
document.getElementById("careForm").onsubmit = async function(e){
  e.preventDefault();

  const dementia = document.querySelector('input[name="dementia"]:checked');

  if(!dementia){
    showGuide("먼저 <b>치매 관련 약 복용 여부(예/아니오)</b>를 선택해주세요.");
    return;
  }

  // 치매 '예'는 이미 팝업으로 안내했으니 여기선 종료
  if(dementia.value === "y"){
    return;
  }

  // ✅ 치매 '아니오'면 ADL 응답이 7개 다 되었는지 체크
  for(let i=0; i<7; i++){
    const checked = document.querySelector('input[name="q'+i+'"]:checked');
    if(!checked){
      showGuide((i+1) + "번 문항을 선택해주세요.");
      return;
    }
  }

  const formData = new FormData(this);

  const res = await fetch("/care_check",{
    method:"POST",
    body:formData
  });

  const data = await res.json();

  showResult("사전조사 결과 안내", data.result + "\\n총점: " + data.score);
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

NHIS25_HTML = """
<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>건강보험 25시</title>
<style>{{style}}</style>
</head>
<body>
<div class="container">
  <a href="/home" class="home-button">홈으로</a>
  <h2>건강보험 25시</h2>

  <div class="result" style="text-align:center;font-size:18px;">
    준비 중입니다.
  </div>
</div>
</body>
</html>
"""

@app.route("/nhis25")
def nhis25():
    check = login_required()
    if check:
        return check
    return render_template_string(NHIS25_HTML, style=BASE_STYLE)


if __name__ == "__main__":
    app.run()
