from flask import Flask, render_template_string, request, jsonify, redirect, url_for, session
import pandas as pd
import os
import re
import json

from dotenv import load_dotenv
load_dotenv()

from openai import OpenAI
cache = {}

def compress_text(s, max_len=60):
    s = str(s).strip()
    if len(s) <= max_len:
        return s

    half = max_len // 2
    return s[:half] + " … " + s[-half:]


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
    ※ 본 서비스는 광주전라제주지역본부<br>
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

        if pw == "nhis":  # 원하는 비밀번호
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
  padding:10px 20px 20px 20px;

  position:relative;   /* 🔥 여기도 추가 */
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
df.columns = [
    str(c).replace("\ufeff", "").replace("\n", "").replace("\r", "").replace(" ", "").strip()
    for c in df.columns
]
print("현재 컬럼명:", list(df.columns))


# =========================
# 조건기반 검색용 옵션 정리
# =========================
def sorted_unique_values(column_name):
    real_col = None

    for c in df.columns:
        clean_c = str(c).replace("\ufeff", "").replace("\n", "").replace("\r", "").replace(" ", "").strip()
        if clean_c == column_name:
            real_col = c
            break

    if real_col is None:
        return []

    values = (
        df[real_col]
        .fillna("")
        .astype(str)
        .str.replace("\ufeff", "", regex=False)
        .str.replace("\n", "", regex=False)
        .str.replace("\r", "", regex=False)
        .str.strip()
    )

    values = [v for v in values if v]

    unique_values = list(set(values))

    unique_values.sort(key=lambda x: (x == "기타", x))

    return unique_values


SIDO_OPTIONS = sorted_unique_values("시도")
SIGUNGU_OPTIONS = sorted_unique_values("시군구")
MAIN_CATEGORY_OPTIONS = sorted_unique_values("대분류")
MIDDLE_CATEGORY_OPTIONS = sorted_unique_values("중분류")

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
  margin-top:-100px; }

@media (max-width:480px){

  .bottom-img{
    margin-top:-50px;   /* 🔥 -80 → -20으로 줄이기 */
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
  padding:10px 20px 20px 20px;

  position:relative;   /* 🔥 이거 추가 */
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
<span>시도, 시군구, 대분류, 중분류, 프로그램, 기관명 조건으로 서비스 자원을 검색합니다</span>
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

    sido = (request.values.get("sido", "") or "").strip()
    sigungu = (request.values.get("sigungu", "") or "").strip()
    main_category = (request.values.get("main_category", "") or "").strip()
    middle_category = (request.values.get("middle_category", "") or "").strip()
    program_kw = (request.values.get("program_kw", "") or "").strip()
    org_kw = (request.values.get("org_kw", "") or "").strip()

    results = {}
    count = 0

    sigungu_options = SIGUNGU_OPTIONS
    if sido and "시도" in df.columns and "시군구" in df.columns:
        temp = df[
            df["시도"].fillna("").astype(str).str.strip() == sido
        ]
        sigungu_options = sorted(
            set(
                temp["시군구"].fillna("").astype(str).str.strip()
            )
        )
        sigungu_options = [v for v in sigungu_options if v]

    middle_category_options = MIDDLE_CATEGORY_OPTIONS
    if main_category and "대분류" in df.columns and "중분류" in df.columns:
        temp = df[
            df["대분류"].fillna("").astype(str).str.strip() == main_category
        ]
        middle_category_options = sorted(
            set(
                temp["중분류"].fillna("").astype(str).str.strip()
            )
        )
        middle_category_options = [v for v in middle_category_options if v]

    if request.method == "POST" or any([sido, sigungu, main_category, middle_category, program_kw, org_kw]):
        filtered = df.copy()

        if sido and "시도" in filtered.columns:
            filtered = filtered[
                filtered["시도"].fillna("").astype(str).str.strip() == sido
            ]

        if sigungu and "시군구" in filtered.columns:
            filtered = filtered[
                filtered["시군구"].fillna("").astype(str).str.strip() == sigungu
            ]

        if main_category and "대분류" in filtered.columns:
            filtered = filtered[
                filtered["대분류"].fillna("").astype(str).str.strip() == main_category
            ]

        if middle_category and "중분류" in filtered.columns:
            filtered = filtered[
                filtered["중분류"].fillna("").astype(str).str.strip() == middle_category
            ]

        if program_kw and "프로그램명칭" in filtered.columns:
            filtered = filtered[
                filtered["프로그램명칭"]
                .fillna("")
                .astype(str)
                .str.contains(program_kw, case=False, na=False)
            ]

        if org_kw and "서비스제공기관명" in filtered.columns:
            filtered = filtered[
                filtered["서비스제공기관명"]
                .fillna("")
                .astype(str)
                .str.contains(org_kw, case=False, na=False)
            ]

        for _, row in filtered.reset_index().iterrows():
            region_key = str(row.get("시군구", "")).strip() or str(row.get("시도", "")).strip() or "기타"

            results.setdefault(region_key, []).append({
                "index": int(row["index"]),
                "label": f"{row.get('프로그램명칭','')} ({row.get('서비스제공기관명','')})"
            })

        count = sum(len(v) for v in results.values())

    return render_template_string(
        COMBO_HTML,
        style=BASE_STYLE,
        sido=sido,
        sigungu=sigungu,
        main_category=main_category,
        middle_category=middle_category,
        program_kw=program_kw,
        org_kw=org_kw,
        sido_options=SIDO_OPTIONS,
        sigungu_options=sigungu_options,
        main_category_options=MAIN_CATEGORY_OPTIONS,
        middle_category_options=middle_category_options,
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
  box-sizing:border-box;
}

@media (max-width:480px){
  input, select{
    height:44px;
    font-size:15px;
  }
}

@media (min-width: 768px) {
  #tel_link {
    display: none !important;
  }
}

.section-box{
  margin-top:18px;
  padding:16px;
  background:#f8fafc;
  border:1px solid #e5e7eb;
  border-radius:12px;
}

.section-title{
  font-size:16px;
  font-weight:700;
  margin-bottom:8px;
  color:#111827;
}

.section-desc{
  font-size:12px;
  color:#6b7280;
  margin-bottom:8px;
  line-height:1.5;
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

<div class="section-box">
  <div class="section-title">지역조건</div>
  <div class="section-desc">시도와 시군구를 선택하여 지역 기준으로 검색합니다.</div>

  <label>시도</label>
  <select name="sido">
    <option value="">전체</option>
    {% if sido and sido not in sido_options %}
    <option value="{{sido}}" selected>{{sido}}</option>
    {% endif %}
    {% for s in sido_options %}
    <option value="{{s}}" {% if s==sido %}selected{% endif %}>{{s}}</option>
    {% endfor %}
  </select>

  <label>시군구</label>
  <select name="sigungu">
    <option value="">전체</option>
    {% if sigungu and sigungu not in sigungu_options %}
    <option value="{{sigungu}}" selected>{{sigungu}}</option>
    {% endif %}
    {% for g in sigungu_options %}
    <option value="{{g}}" {% if g==sigungu %}selected{% endif %}>{{g}}</option>
    {% endfor %}
  </select>
</div>


<div class="section-box">
  <div class="section-title">상세 조건</div>
  <div class="section-desc">대분류와 중분류(선택형), 프로그램과 기관명(서술형)으로 검색합니다.</div>

<label>대분류</label>
<select name="main_category">
  <option value="">전체</option>
  {% if main_category and main_category not in main_category_options %}
  <option value="{{main_category}}" selected>{{main_category}}</option>
  {% endif %}
  {% for c in main_category_options %}
  <option value="{{c}}" {% if c==main_category %}selected{% endif %}>{{c}}</option>
  {% endfor %}
</select>


<label>중분류</label>
<select name="middle_category">
  <option value="">전체</option>
  {% if middle_category and middle_category not in middle_category_options %}
  <option value="{{middle_category}}" selected>{{middle_category}}</option>
  {% endif %}
  {% for c in middle_category_options %}
  <option value="{{c}}" {% if c==middle_category %}selected{% endif %}>{{c}}</option>
  {% endfor %}
</select>

  <label>프로그램</label>
  <input type="text" name="program_kw" value="{{program_kw}}" placeholder="프로그램명 포함 검색">

  <label>기관명</label>
  <input type="text" name="org_kw" value="{{org_kw}}" placeholder="기관명 포함 검색">
</div>

<button type="submit" class="menu-btn">검색하기</button>
</form>

{% if request.method == "POST" or count > 0 or (sido or sigungu or main_category or middle_category or program_kw or org_kw) %}
<div class="result">

<p><b>총 {{count}}건이 조회되었습니다.</b></p>

{% if count == 0 %}
<p style="color:#6b7280;">조건에 맞는 서비스가 없습니다.</p>
{% endif %}

{% for region, items in results.items() %}
<h3>📍 {{region}}</h3>
{% for r in items %}
<div class="item" onclick="openDetail({{r['index']}})">- {{r['label']}}</div>
{% endfor %}
{% endfor %}

</div>
{% endif %}
</div>

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
  fetch("/detail/" + idx)
    .then(r => r.json())
    .then(d => {
      document.getElementById("m_title").innerText = d["프로그램명칭"] || "";
      document.getElementById("m_org").innerText = d["서비스제공기관명"] || "";
      document.getElementById("m_tel").innerText = d["기관연락처"] || "";
      document.getElementById("m_addr").innerText = d["기관주소"] || "";
      document.getElementById("m_other").innerText = d["기타"] || "";

      const addr = d["기관주소"] || "";
      document.getElementById("m_map").src =
        "https://www.google.com/maps?q=" + encodeURIComponent(addr) + "&output=embed";

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
    warning_msg = ""
    found_sido = ""
    found_sigungu = ""

    if request.method == "POST":

        query = (request.form.get("query") or "").strip()
        found_sido, found_sigungu = extract_region_from_query(query)
        print("추출된 지역:", found_sido, found_sigungu)

        # ======================
        # 서비스 목록 문자열 생성
        # ======================
        service_text = ""

        for idx, r in service_df.iterrows():
            service_text += (
                f"{idx}. {compress_text(r.get('서비스설명',''),40)} / "
                f"{compress_text(r.get('검색어',''),40)}\n"
            )

        # ======================
        # 서비스 그룹 데이터 문자열 생성
        # ======================
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
                service_results=service_results,
                warning_msg=warning_msg,
                found_sido=found_sido,
                found_sigungu=found_sigungu
            )

        client = OpenAI(api_key=api_key)


        prompt = f"""
너는 통합돌봄 서비스 추천 전문가다.

사용자의 사례를 분석하고,
아래 서비스 목록 전체를 검토하여
적합한 서비스들을 폭넓게 추천하라.

중요:
- 파이썬이 미리 판단하지 않는다.
- 반드시 서비스목록의 '서비스설명'과 '검색어'를 적극적으로 참고하여 판단한다.
- 사용자가 직접 정확한 행정용어를 쓰지 않아도 의미가 비슷하면 연결해서 판단한다.
- 너무 보수적으로 2~4개만 고르지 말고, 실제 현장에서 함께 검토할 만한 서비스는 넓게 포함한다.
- 단, 완전히 무관한 서비스는 제외한다.

판단 원칙:
1. 사례의 핵심 욕구를 먼저 정리한다.
   - 건강/통증/질환
   - 이동/거동
   - 식사/영양
   - 위생/청결
   - 정서/사회적 고립
   - 돌봄부담/가족지원
   - 주거환경
   - 안전
2. 서비스설명과 검색어를 보고 사례와 의미적으로 맞는 서비스를 찾는다.
3. 같은 사례에 대해 하나의 서비스만 고르지 말고, 함께 필요한 연관 서비스도 포함할 수 있다.
4. 특히 아래 표현은 적극 반영한다.
   - "집으로 와주길 원함" → 방문형 서비스 우선 고려
   - "반찬을 못함", "식사 준비 어려움" → 식사지원/반찬지원/영양지원 우선 고려
   - "지팡이", "워커", "휠체어", "보행보조" → 복지용구 계열 우선 고려
   - "무릎통증", "통증", "거동불편", "움직이기 어려움" → 재활, 기능회복, 방문보건, 이동지원 계열 고려
   - "혼자 지냄", "외로움", "고립" → 정서지원, 안부확인, 돌봄연계 고려
5. 결과는 너무 적게 내지 말고, 관련성이 있으면 충분히 제시한다.
6. 우선순위가 높은 순서대로 정렬한다.
7. 최대 30개까지 추천한다.
8. 가능하면 동일 유형 서비스는 중복 추천하지 말고, 서로 다른 유형의 서비스가 균형 있게 포함되도록 한다.

반드시 JSON만 출력한다.
설명문, 코드블록, 마크다운 없이 JSON만 출력한다.

출력 형식:
{{
  "results": [
    {{
      "index": 12,
      "선택이유": "사용자의 무릎통증과 이동불편, 방문 희망 욕구에 맞아 우선 검토할 필요가 있음"
    }}
  ]
}}

서비스 목록:
{service_text}

사용자 사례:
{query}
"""


        try:
            if query in cache:
                service_results = cache[query]

            else:
                res = client.responses.create(
                    model="gpt-4.1-mini",
                    input=prompt,
                    temperature=0
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
                        parsed = {"results": []}

                raw_results = parsed.get("results", [])[:50]

                final_results = []

                for r in raw_results:
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
                cache[query] = service_results

        except Exception as e:
            cond_display.append(f"GPT 오류: {e}")



        count = len(service_results)

        if count >= 15:
            warning_msg = "15개 이상의 서비스내용이 검색되었습니다. 결과를 더 정확하게 확인하려면 대상자의 건강상태, 돌봄 상황, 지역, 기능 상태 등을 조금 더 구체적으로 입력해 주세요."

    return render_template_string(
        DESC_HTML,
        style=BASE_STYLE,
        query=query,
        results=results,
        cond_display=cond_display,
        count=count,
        service_results=service_results,
        warning_msg=warning_msg,
        found_sido=found_sido,
        found_sigungu=found_sigungu
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
  padding-right:64px;
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

<div style="position:relative;">

<textarea id="queryInput" name="query" placeholder="예) 나주에 살고 식사도움이 필요한 어르신에게 필요한 서비스">{{query}}</textarea>

<button type="button" id="voiceBtn"
style="
position:absolute;
right:10px;
bottom:10px;
width:44px;
height:44px;
margin-top:0;
padding:0;
border-radius:50%;
border:none;
background:#2563eb;
color:white;
font-size:20px;
display:none;
cursor:pointer;
z-index:10;
">
🎤
</button>

</div>

<button type="submit">AI 검색</button>

</form>

<div class="notice">
※ 입력한 사례와 유사한 <b>통합돌봄 서비스 최대 30가지</b>를 추천합니다.<br>
지자체 개인별지원계획 수립 참고용입니다.
</div>

</div>


{% if service_results %}

<div class="result">

<h3>{{count}}건의 추천 서비스</h3>

{% if warning_msg %}
<div style="
  margin:12px 0 16px 0;
  padding:14px 16px;
  border-radius:12px;
  background:#fff7ed;
  border:1px solid #fdba74;
  color:#9a3412;
  font-size:14px;
  line-height:1.6;
">
  ⚠️ {{warning_msg}}
</div>
{% endif %}


{% for r in service_results %}

<div class="result-card">

  <div style="display:flex; justify-content:space-between; align-items:flex-start; gap:12px; margin-bottom:10px;">

    <div style="font-weight:700; font-size:16px; line-height:1.5; flex:1;">
      {{loop.index}}. {{r["대분류"]}} > {{r["중분류"]}} > {{r["서비스내용"]}}
    </div>

    <a
      href="/combo?sido={{found_sido|urlencode}}&sigungu={{found_sigungu|urlencode}}&main_category={{r['대분류']|urlencode}}&middle_category={{r['중분류']|urlencode}}&from_desc=1"
      style="
        display:inline-block;
        padding:10px 14px;
        border-radius:10px;
        background:#2563eb;
        color:white;
        text-decoration:none;
        font-size:13px;
        font-weight:600;
        white-space:nowrap;
        flex:0 0 auto;
      "
    >
      조건검색
    </a>

  </div>

  <div style="font-size:13px; line-height:1.6; color:#6b7280;">

    <div>
      <span style="color:#6b7280;">대분류:</span>
      <b>{{r["대분류"]}}</b>
    </div>

    <div>
      <span style="color:#6b7280;">중분류:</span>
      <b>{{r["중분류"]}}</b>
    </div>

    <div>
      <span style="color:#6b7280;">소분류:</span>
      <b>{{r["서비스내용"]}}</b>
    </div>

  </div>

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

(function(){

  const ua = navigator.userAgent || navigator.vendor || window.opera;
  const isMobile = /Android|iPhone|iPad|iPod/i.test(ua);

  if(!isMobile) return;

  const btn = document.getElementById("voiceBtn");
  const input = document.getElementById("queryInput");

  if(!btn || !input) return;

  btn.style.display = "block";

  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;

  if(!SpeechRecognition){
    btn.style.display = "none";
    return;
  }

  const recognition = new SpeechRecognition();
  recognition.lang = "ko-KR";
  recognition.interimResults = false;
  recognition.maxAlternatives = 1;

  btn.addEventListener("click", function(e){
    e.preventDefault();
    btn.innerText = "🎙️";
    recognition.start();
  });

  recognition.onresult = function(event){
    const text = event.results[0][0].transcript;
    input.value = text;
  };

  recognition.onerror = function(){
    btn.innerText = "🎤";
  };

  recognition.onend = function(){
    btn.innerText = "🎤";
  };

})();
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

def extract_region_from_query(query: str):
    q = str(query or "").strip()
    q = q.replace(" ", "")

    found_sido = ""
    found_sigungu = ""

    sido_alias_map = {
        "전라남도": "전라남도",
        "전남": "전라남도",
        "전라북도": "전라북도",
        "전북": "전라북도",
        "광주광역시": "광주광역시",
        "광주": "광주광역시",
        "제주특별자치도": "제주특별자치도",
        "제주도": "제주특별자치도",
        "제주": "제주특별자치도"
    }

    sigungu_alias_map = {
        "목포시": ("전라남도", "목포시"),
        "목포": ("전라남도", "목포시"),
        "여수시": ("전라남도", "여수시"),
        "여수": ("전라남도", "여수시"),
        "순천시": ("전라남도", "순천시"),
        "순천": ("전라남도", "순천시"),
        "나주시": ("전라남도", "나주시"),
        "나주": ("전라남도", "나주시"),
        "광양시": ("전라남도", "광양시"),
        "광양": ("전라남도", "광양시"),
        "담양군": ("전라남도", "담양군"),
        "담양": ("전라남도", "담양군"),
        "곡성군": ("전라남도", "곡성군"),
        "곡성": ("전라남도", "곡성군"),
        "구례군": ("전라남도", "구례군"),
        "구례": ("전라남도", "구례군"),
        "고흥군": ("전라남도", "고흥군"),
        "고흥": ("전라남도", "고흥군"),
        "보성군": ("전라남도", "보성군"),
        "보성": ("전라남도", "보성군"),
        "화순군": ("전라남도", "화순군"),
        "화순": ("전라남도", "화순군"),
        "장흥군": ("전라남도", "장흥군"),
        "장흥": ("전라남도", "장흥군"),
        "강진군": ("전라남도", "강진군"),
        "강진": ("전라남도", "강진군"),
        "해남군": ("전라남도", "해남군"),
        "해남": ("전라남도", "해남군"),
        "영암군": ("전라남도", "영암군"),
        "영암": ("전라남도", "영암군"),
        "무안군": ("전라남도", "무안군"),
        "무안": ("전라남도", "무안군"),
        "함평군": ("전라남도", "함평군"),
        "함평": ("전라남도", "함평군"),
        "영광군": ("전라남도", "영광군"),
        "영광": ("전라남도", "영광군"),
        "장성군": ("전라남도", "장성군"),
        "장성": ("전라남도", "장성군"),
        "완도군": ("전라남도", "완도군"),
        "완도": ("전라남도", "완도군"),
        "진도군": ("전라남도", "진도군"),
        "진도": ("전라남도", "진도군"),
        "신안군": ("전라남도", "신안군"),
        "신안": ("전라남도", "신안군"),

        "전주시": ("전라북도", "전주시"),
        "전주": ("전라북도", "전주시"),
        "군산시": ("전라북도", "군산시"),
        "군산": ("전라북도", "군산시"),
        "익산시": ("전라북도", "익산시"),
        "익산": ("전라북도", "익산시"),
        "정읍시": ("전라북도", "정읍시"),
        "정읍": ("전라북도", "정읍시"),
        "남원시": ("전라북도", "남원시"),
        "남원": ("전라북도", "남원시"),
        "김제시": ("전라북도", "김제시"),
        "완산구": ("전라북도", "전주시 완산구"),
        "덕진구": ("전라북도", "전주시 덕진구"),
        "김제": ("전라북도", "김제시"),
        "완주군": ("전라북도", "완주군"),
        "완주": ("전라북도", "완주군"),
        "진안군": ("전라북도", "진안군"),
        "진안": ("전라북도", "진안군"),
        "무주군": ("전라북도", "무주군"),
        "무주": ("전라북도", "무주군"),
        "장수군": ("전라북도", "장수군"),
        "장수": ("전라북도", "장수군"),
        "임실군": ("전라북도", "임실군"),
        "임실": ("전라북도", "임실군"),
        "순창군": ("전라북도", "순창군"),
        "순창": ("전라북도", "순창군"),
        "고창군": ("전라북도", "고창군"),
        "고창": ("전라북도", "고창군"),
        "부안군": ("전라북도", "부안군"),
        "부안": ("전라북도", "부안군"),

        "동구": ("광주광역시", "동구"),
        "서구": ("광주광역시", "서구"),
        "남구": ("광주광역시", "남구"),
        "북구": ("광주광역시", "북구"),
        "광산구": ("광주광역시", "광산구"),
        "광산": ("광주광역시", "광산구"),

        "제주시": ("제주특별자치도", "제주시"),
        "제주시청": ("제주특별자치도", "제주시"),
        "제주": ("제주특별자치도", "제주시"),
        "서귀포시": ("제주특별자치도", "서귀포시"),
        "서귀포": ("제주특별자치도", "서귀포시")
    }

    for key in list(sigungu_alias_map.keys()):
        if key.endswith("시") or key.endswith("군") or key.endswith("구"):
            base = key[:-1]
            if base and base not in sigungu_alias_map:
                sigungu_alias_map[base] = sigungu_alias_map[key]

    for alias in sorted(sido_alias_map.keys(), key=len, reverse=True):
        if alias in q:
            found_sido = sido_alias_map[alias]
            break

    for alias in sorted(sigungu_alias_map.keys(), key=len, reverse=True):
        if alias in q:
            found_sido = sigungu_alias_map[alias][0]
            found_sigungu = sigungu_alias_map[alias][1]
            break

    return found_sido, found_sigungu



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

.dementia-options{
  display:flex;
  width:100%;
  align-items:center;
  justify-content:space-between;
  gap:0;
}

.dementia-options label{
  flex:1;
  display:flex;
  justify-content:center;
  align-items:center;
  gap:6px;
  white-space:nowrap;
  margin:0;
}

.dementia-options input[type=radio]{
  width:auto !important;
  margin:0;
  flex:0 0 auto;
  transform:scale(1.1);
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

.pc-br{
  display:inline;
}

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
  line-height:1.5;
}

.options input[type=radio]{
  width:auto !important;
  flex:0 0 auto;
  transform:scale(1.1);
}

.question-box{
  background:#f5faff;
  padding:22px;
  border-radius:16px;
  margin-top:18px;
  box-shadow:0 8px 24px rgba(15, 23, 42, 0.06);
  border:1px solid #dbeafe;
  transition:0.18s ease;
}

.question-box.active{
  border:2px solid #2563eb;
  background:#eef6ff;
  box-shadow:0 12px 28px rgba(37,99,235,0.12);
}

.dementia-box{
  background:linear-gradient(135deg,#fff7ed,#fff1f2);
  padding:18px;
  border-radius:14px;
  margin-top:15px;
  border:1px solid #fed7aa;
  box-shadow:0 6px 18px rgba(251,146,60,0.08);
}

.dementia-options{
  display:flex;
  width:100%;
  align-items:center;
  justify-content:space-between;
  gap:0;
  margin-top:10px;
}

/* ====== 예쁜 점수 배너 ====== */
.score-banner{
  position:fixed;
  top:100px;
  right:80px;
  z-index:998;
  width:132px;
  padding:14px 12px;
  border-radius:22px;
  background:rgba(255,255,255,0.92);
  backdrop-filter:blur(10px);
  -webkit-backdrop-filter:blur(10px);
  border:1px solid rgba(191,219,254,0.95);
  box-shadow:0 18px 38px rgba(37,99,235,0.18);
  text-align:center;
  transition:all 0.2s ease;
}

.score-banner.disabled{
  opacity:0.62;
  transform:scale(0.98);
}

.score-badge{
  width:72px;
  height:72px;
  margin:0 auto 10px auto;
  border-radius:50%;
  background:linear-gradient(135deg,#2563eb,#60a5fa);
  display:flex;
  flex-direction:column;
  align-items:center;
  justify-content:center;
  color:white;
  box-shadow:0 10px 22px rgba(37,99,235,0.28);
}

.score-badge-label{
  font-size:10px;
  opacity:0.92;
  line-height:1;
  margin-bottom:4px;
}

.score-value{
  font-size:28px;
  font-weight:800;
  line-height:1;
}

.score-meta{
  display:none;   /* 🔥 이걸로 완전히 숨김 */
}

.score-progress-wrap{
  width:100%;
  height:8px;
  background:#e5edf9;
  border-radius:999px;
  overflow:hidden;
  margin-bottom:3px;
}

.score-progress-bar{
  height:100%;
  width:0%;
  border-radius:999px;
  background:linear-gradient(90deg,#60a5fa,#2563eb);
  transition:width 0.22s ease;
}

.score-status{
  font-size:11px;
  color:#1e3a8a;
  line-height:1.45;
  word-break:keep-all;
  min-height:34px;
  font-weight:600;
}

.score-chip{
  margin-top:8px;
  display:inline-block;
  padding:5px 8px;
  border-radius:999px;
  font-size:10px;
  font-weight:700;
  background:#eff6ff;
  color:#2563eb;
}

/* ===== 상태별 색감 ===== */
.score-banner.state-low .score-badge{
  background:linear-gradient(135deg,#22c55e,#4ade80);
  box-shadow:0 10px 22px rgba(34,197,94,0.24);
}
.score-banner.state-low .score-progress-bar{
  background:linear-gradient(90deg,#86efac,#22c55e);
}
.score-banner.state-low .score-status{
  color:#166534;
}
.score-banner.state-low .score-chip{
  background:#f0fdf4;
  color:#16a34a;
}

.score-banner.state-mid .score-badge{
  background:linear-gradient(135deg,#f59e0b,#fbbf24);
  box-shadow:0 10px 22px rgba(245,158,11,0.24);
}
.score-banner.state-mid .score-progress-bar{
  background:linear-gradient(90deg,#fde68a,#f59e0b);
}
.score-banner.state-mid .score-status{
  color:#92400e;
}
.score-banner.state-mid .score-chip{
  background:#fffbeb;
  color:#d97706;
}

.score-banner.state-high .score-badge{
  background:linear-gradient(135deg,#ef4444,#f87171);
  box-shadow:0 10px 22px rgba(239,68,68,0.24);
}
.score-banner.state-high .score-progress-bar{
  background:linear-gradient(90deg,#fca5a5,#ef4444);
}
.score-banner.state-high .score-status{
  color:#991b1b;
}
.score-banner.state-high .score-chip{
  background:#fef2f2;
  color:#dc2626;
}

.score-banner.state-dementia .score-badge{
  background:linear-gradient(135deg,#7c3aed,#a78bfa);
  box-shadow:0 10px 22px rgba(124,58,237,0.24);
}
.score-banner.state-dementia .score-progress-bar{
  background:linear-gradient(90deg,#c4b5fd,#7c3aed);
  width:100% !important;
}
.score-banner.state-dementia .score-status{
  color:#5b21b6;
}
.score-banner.state-dementia .score-chip{
  background:#f5f3ff;
  color:#7c3aed;
}

@media (max-width:480px){
  .dementia-options{
    width:100%;
    gap:0;
  }
}

@media (max-width:480px){

  #resultModal{
    padding-top:0 !important;
  }

  #resultModal > div{
    top:2% !important;
  }

.score-banner{
  position:fixed;   /* 🔥 fixed → absolute */
  top:10px;            /* 🔥 위쪽으로 딱 붙이기 */
  right:10px;          /* 🔥 우측 여백 */
  
  width:85px;          /* 🔥 작게 */
  padding:8px 6px;
  border-radius:16px;

  z-index:10;
}

@media (max-width:480px){
  #careForm{
    padding-bottom:160px;
  }
}

.score-badge{
  width:44px;
  height:44px;
}

.score-value{
  font-size:18px;
}

.score-meta{
  font-size:9px;
}

.score-status{
  font-size:10px;
  line-height:1.2;
  min-height:20px;   /* 🔥 높이 줄이기 */
}

.score-chip{
  font-size:10px;
  padding:3px 6px;
}}

</style>
</head>

<body>
<div class="container">

<div class="top-bar">
  <a href="/home" class="home-button">홈으로</a>
</div>

<h2>통합돌봄 사전조사</h2>

<div id="scoreBanner" class="score-banner disabled">
  <div class="score-badge">
    <div class="score-badge-label">점수</div>
    <div id="scoreValue" class="score-value">0</div>
  </div>

  <div class="score-meta">
    응답 <span id="answeredCount">0</span>/7 · 최대 14점
  </div>

  <div class="score-progress-wrap">
    <div id="scoreProgressBar" class="score-progress-bar"></div>
  </div>

  <div id="scoreStatus" class="score-status">치매 여부를 먼저 선택하세요</div>
  <div id="scoreChip" class="score-chip">사전 확인 필요</div>
</div>

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
  document.getElementById("resultModal").style.display = "none";
}

function getCurrentScore(){
  let score = 0;
  for(let i=0; i<7; i++){
    const checked = document.querySelector('input[name="q'+i+'"]:checked');
    if(checked){
      score += Number(checked.value);
    }
  }
  return score;
}

function getAnsweredCount(){
  let count = 0;
  for(let i=0; i<7; i++){
    const checked = document.querySelector('input[name="q'+i+'"]:checked');
    if(checked){
      count += 1;
    }
  }
  return count;
}

function getBannerState(score, dementiaValue){
  if(!dementiaValue){
    return "disabled";
  }
  if(dementiaValue === "y"){
    return "state-dementia";
  }
  if(score <= 1){
    return "state-low";
  }else if(score <= 3){
    return "state-mid";
  }else{
    return "state-high";
  }
}

function getScoreStatusText(score, dementiaValue){
  if(!dementiaValue){
    return "치매 여부를 먼저 선택하세요";
  }

  if(dementiaValue === "y"){
    return "치매약 복용으로 별도 조사 없이 대상입니다";
  }

  if(score <= 1){
    return "지자체 사업 안내 후 종결 구간입니다";
  }else if(score <= 3){
    return "지자체 자체조사 대상 구간입니다";
  }else{
    return "통합판정조사 대상 구간입니다";
  }
}

function getChipText(score, dementiaValue){
  if(!dementiaValue){
    return "사전 확인 필요";
  }

  if(dementiaValue === "y"){
    return "치매약 복용";
  }

  if(score <= 1){
    return "0~1점";
  }else if(score <= 3){
    return "2~3점";
  }else{
    return "4점 이상";
  }
}

function updateScoreBanner(){
  const banner = document.getElementById("scoreBanner");
  const scoreValue = document.getElementById("scoreValue");
  const answeredCount = document.getElementById("answeredCount");
  const scoreStatus = document.getElementById("scoreStatus");
  const scoreChip = document.getElementById("scoreChip");
  const scoreProgressBar = document.getElementById("scoreProgressBar");
  const dementia = document.querySelector('input[name="dementia"]:checked');

  const score = getCurrentScore();
  const answered = getAnsweredCount();
  const dementiaValue = dementia ? dementia.value : "";

  scoreValue.innerText = score;
  answeredCount.innerText = answered;
  scoreStatus.innerText = getScoreStatusText(score, dementiaValue);
  scoreChip.innerText = getChipText(score, dementiaValue);

  let progress = Math.min((score / 14) * 100, 100);
  if(dementiaValue === "y"){
    progress = 100;
  }
  scoreProgressBar.style.width = progress + "%";

  banner.classList.remove("disabled","state-low","state-mid","state-high","state-dementia");

  const nextState = getBannerState(score, dementiaValue);

  if(nextState === "disabled"){
    banner.classList.add("disabled");
  }else{
    banner.classList.add(nextState);
  }
}

/* 1) 치매 선택 안 했는데 ADL 누르면 차단 */
document.querySelectorAll('#adlSection .options input[type="radio"]').forEach(radio => {
  radio.addEventListener("change", function(){
    const dementia = document.querySelector('input[name="dementia"]:checked');

    if(!dementia){
      this.checked = false;
      showGuide("먼저 <b>치매 관련 약 복용 여부(예/아니오)</b>를<br> 선택해주세요.");
      updateScoreBanner();
      return;
    }

    const box = this.closest(".question-box");
    if(box){
      box.classList.add("active");
    }

    updateScoreBanner();
  });
});

/* 2) 치매 선택 처리 */
document.querySelectorAll('input[name="dementia"]').forEach(radio => {
  radio.addEventListener("change", function(){
    if(this.value === "y"){
      document.getElementById("adlSection").style.opacity = "0.4";
      showGuide("치매약을 복약 중인 경우 일상생활 수행능력과 관계없이 <b>통합돌봄 대상</b>입니다.");
    }else{
      document.getElementById("adlSection").style.opacity = "1";
    }

    updateScoreBanner();
  });
});

/* 3) 검사하기 클릭 시 */
document.getElementById("careForm").onsubmit = async function(e){
  e.preventDefault();

  const dementia = document.querySelector('input[name="dementia"]:checked');

  if(!dementia){
    showGuide("먼저 <b>치매 관련 약 복용 여부(예/아니오)</b>를 선택해주세요.");
    return;
  }

  if(dementia.value === "y"){
    return;
  }

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

  updateScoreBanner();
  showResult("사전조사 결과 안내", data.result + "\\n총점: " + data.score);
};

updateScoreBanner();
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

<style>
.app-box{
  background:white;
  padding:22px;
  border-radius:14px;
  text-align:center;
  margin-top:20px;
  box-shadow:0 6px 18px rgba(0,0,0,0.08);
}

.desc{
  font-size:15px;
  line-height:1.7;
  color:#374151;
  margin-bottom:18px;
}

.notice{
  margin-top:14px;
  font-size:13px;
  color:#6b7280;
  line-height:1.6;
}

.btn{
  display:block;
  width:100%;
  padding:14px;
  margin-top:10px;
  border:none;
  border-radius:10px;
  text-decoration:none;
  font-weight:600;
  font-size:15px;
  cursor:pointer;
  box-sizing:border-box;
}

.primary-btn{
  background:#2563eb;
  color:white;
}

.hidden{
  display:none;
}
</style>
</head>

<body>
<div class="container">

<div class="top-bar">
  <a href="/home" class="home-button">홈으로</a>
</div>

<h2>건강보험 25시</h2>

<div class="app-box">

  <div id="pcBox" class="hidden">
    <p class="desc">
      현재는 <b>PC 환경</b>입니다.<br>
      건강보험 25시는 <b>모바일 앱 기반 서비스</b>입니다.<br>
      스마트폰에서 접속하면 앱 실행 또는 설치 화면으로 이동합니다.
    </p>

    <div class="notice">
      ※ 모바일에서 QR코드 또는 링크로 접속해 주세요.
    </div>
  </div>

  <div id="mobileBox" class="hidden">
    <p class="desc">
      모바일 환경이 확인되었습니다.<br>
      버튼을 누르면 건강보험 25시로 이동합니다.<br>
    </p>

    <button id="goBtn" class="btn primary-btn">
      건강보험 25시 열기
    </button>

    <div class="notice">
      ※ 앱 미설치 시 설치페이지로 이동합니다.
    </div>
  </div>

</div>

</div>

<script>
(function () {

  const ua = navigator.userAgent || navigator.vendor || window.opera;

  const isAndroid = /Android/i.test(ua);
  const isIOS = /iPhone|iPad|iPod/i.test(ua);
  const isMobile = isAndroid || isIOS;

  const pcBox = document.getElementById("pcBox");
  const mobileBox = document.getElementById("mobileBox");
  const goBtn = document.getElementById("goBtn");

  const NHIS_URL = "https://m.nhis.or.kr/index4.html?path=%2Fmg%2Fwbmmb0010%2FmainApp.do";

  if (!isMobile) {
    pcBox.classList.remove("hidden");
    return;
  }

  mobileBox.classList.remove("hidden");

  goBtn.addEventListener("click", function () {
    window.location.href = NHIS_URL;
  });

})();
</script>

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