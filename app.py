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

  <form method="post">
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
*{box-sizing:border-box;}

body{
  font-family:'Pretendard',sans-serif;
  margin:0;
  padding:16px;
  background:#f7f9fc;
}

.container{
  max-width:600px;
  margin:auto;
}

h1,h2{
  text-align:center;
  color:#2c3e50;
  margin-bottom:12px;
}

@media (max-width:480px){
  .half-menu-row{
    flex-direction:column;
    gap:6px;        /* 간격 줄이기 */
    margin-top:10px;
  }

  .half-menu-row button{
    margin-top:0;   /* 버튼 기본 margin 제거 */
  }
}

h3{
  margin:16px 0 8px;
  color:#111827;
}

label{
  display:block;
  margin-top:12px;
  font-weight:600;
}

input[type=text],
input[type=password],
textarea,
select{
  width:100%;
  padding:9px 12px;
  font-size:15px;
  border-radius:8px;
  border:1px solid #ccc;
  margin-top:3px;
}

button{
  width:100%;
  height:50px;
  border:none;
  border-radius:8px;
  font-size:17px;
  cursor:pointer;
  margin-top:9px;
}

.menu-btn{
  background:#0078d7;
  color:white;
}

.menu-btn:hover{
  opacity:0.95;
}

.pdf-btn{
  width:100%;
  height:50px;
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

.pdf-btn:hover{
  background:#f1f5f9;
}

.pdf-btn img{
  width:32px;
  height:auto;
}

.home-btn{
  display:inline-block;
  background:#2c3e50;
  color:white;
  padding:10px 16px;
  border-radius:6px;
  margin-bottom:14px;
  text-decoration:none;
}

.result{
  margin-top:20px;
  background:white;
  padding:18px;
  border-radius:8px;
  box-shadow:0 2px 6px rgba(0,0,0,0.1);
}

.item{
  cursor:pointer;
  color:#0078d7;
  margin-top:6px;
  margin-left:8px;
}

.small{
  font-size:13px;
  color:#6b7280;
  margin-top:4px;
}

.choice-btn{
  width:100%;
  margin-top:8px;
  height:46px;
  padding:0 12px;
  border-radius:10px;
  border:1px solid #cfd8e3;
  background:#ffffff;
  cursor:pointer;
  font-size:15px;
  color:#111827;
}

.choice-btn:hover{
  background:#f1f5f9;
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
<style>{{style}}</style>
<style>
/* ✅ 홈 메뉴: 버튼 중앙 유지 + ①②③ 세로선 정렬 + 라벨 시작점 동일 */
/* ✅ 홈 메뉴: 버튼 중앙 유지 + ①②③ 세로선 정렬 + 라벨 시작점 동일 */
/* ✅ 홈 메뉴: 1/2/3을 "같이" 오른쪽으로 밀어서 PDF 아이콘 시작점과 정렬 */
/* 🔥 메뉴 버튼 전체를 중앙 정렬 */
.home-menu-btn{
  display:flex;
  justify-content:center;  /* 버튼 내용 중앙 */
  align-items:center;
}

/* 번호+텍스트 묶음 */
.home-menu-btn .wrap{
  display:grid;
  grid-template-columns: 40px auto;
  column-gap:1px;
  align-items:center;

  width: 320px;
  max-width:100%;

  padding-left: 70px;   /* 데스크탑 기준 */
}

/* 📱 모바일 보정 */
@media (max-width:480px){
  .home-menu-btn .wrap{
    padding-left: 55px;  /* 모바일은 덜 밀기 */
  }
}
/* 번호/라벨 */
.home-menu-btn .num{
  justify-self:center;
}
.home-menu-btn .label{
  justify-self:start;
  white-space:nowrap;
}

/* ✅ 하단 2개 반쪽 버튼(좌/우) */
/* 하단 반쪽 메뉴 */
.half-menu-row{
  display:flex;
  gap:12px;
  margin-top:14px;
}

/* 모바일 간격 조정 */
@media (max-width:480px){
  .half-menu-row{
    flex-direction:column;
    gap:10px;   /* ← 이게 핵심 */
  }
}.half-menu-row a{
  flex:1;
}

/* 버튼 크기 맞추기 */
.half-btn{
  width:100%;
  height:52px;
  justify-content:center;
}

/* 모바일에서는 세로로 쌓기 */
@media (max-width:480px){
  .half-menu-row{
    flex-direction:column;
  }
}
.half-btn img{
  width:28px;
  height:auto;
}

</style>
</head>
<body>
<div class="container">
<h1>통합돌봄 서비스 자원검색</h1>

<a href="/desc" style="text-decoration:none;display:block;">
  <button class="menu-btn home-menu-btn">
    <span class="wrap">
      <span class="num">①</span>
      <span class="label">사례기반 자원검색(AI)</span>
    </span>
  </button>
</a>

<a href="/combo" style="text-decoration:none;display:block;">
  <button class="menu-btn home-menu-btn">
    <span class="wrap">
      <span class="num">②</span>
      <span class="label">조건기반 자원검색</span>
    </span>
  </button>
</a>

<a href="/care" style="text-decoration:none;display:block;">
  <button class="menu-btn home-menu-btn">
    <span class="wrap">
      <span class="num">③</span>
      <span class="label">통합돌봄 사전조사</span>
    </span>
  </button>
</a>
<div class="half-menu-row">
  <a href="/guide" target="_blank" style="text-decoration:none;display:block;">
    <button class="pdf-btn half-btn">
      <img src="/static/pdf_icon.png" alt="PDF">
      통합돌봄 사업안내
    </button>
  </a>

  <a href="/nhis25" style="text-decoration:none;display:block;">
    <button class="pdf-btn half-btn">
      <img src="/static/nhis_heart.png" alt="건강보험">
      건강보험 25시
    </button>
  </a>
</div>
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
@media (min-width: 768px) {
  #tel_link {
    display: none !important;
  }
}
</style>
</head>
<body>
<div class="container">
<a href="/home" class="home-btn">홈으로</a>
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
역할: 통합돌봄 자원검색 조건 추출기.
반드시 JSON만 출력한다. 설명, 문장, 코드블록 금지.

출력 형식:
{{
  "시군구": string|null,
  "대분류": "보건의료"|"생활지원"|"요양"|"주거지원"|null,
  "건강상태": string|null,
  "건강확장키워드": [string]
}}

규칙:
1. 문장에 지역이 있으면 반드시 표준 행정명으로 변환해 "시군구"에 채워라.
2. 요양/의료/주거/생활 관련 단어가 있으면 대분류에 정확히 매칭.
3. "어르신","노인","고령자"는 조건에서 제외.
4. "거동"과 "불편"이 함께 있으면 반드시 "거동불편".
5. 건강 표현이 있으면 가장 일반적인 질환명으로 정규화.
6. 건강상태가 추출되면 의미적으로 함께 검색될 키워드 3~5개 생성.
7. 건강상태가 null이면 건강확장키워드는 빈 배열.
8. 가능한 한 최소 1개 이상 채워라.
9. 사용자가 명시하지 않은 대분류는 추론하여 채우지 말 것.

입력:
{query}
"""

        data = {"시군구": None, "대분류": None, "건강상태": None, "건강확장키워드": []}

        try:
            res = client.chat.completions.create(
                model="gpt-4.1-mini",
                messages=[{"role":"user","content":prompt}],
                temperature=0,
                response_format={"type":"json_object"}
            )

            text = res.choices[0].message.content
            print("GPT 원문:", text)   # ✅ 이 줄 추가
            m = re.search(r"\{.*\}", text, re.S)

            if m:
                parsed = json.loads(m.group())
                data["시군구"] = parsed.get("시군구")
                data["대분류"] = parsed.get("대분류")
                data["건강상태"] = parsed.get("건강상태")
                data["건강확장키워드"] = parsed.get("건강확장키워드", [])

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

        # 🔎 건강 + 기타 OR 검색 (항상 실행)

        # 🔎 건강 + 기타 OR 검색 (프로그램명 제외)

        keywords = []

        if data.get("건강상태"):
            keywords.append(str(data["건강상태"]))

        if data.get("건강확장키워드"):
            keywords.extend(data["건강확장키워드"])

        keywords = list(set([k for k in keywords if k]))

        if keywords:

            import pandas as pd
            condition = pd.Series(False, index=filtered.index)

            for kw in keywords:
                condition |= (
                    filtered["건강상태"].astype(str).str.contains(kw, na=False)
                    | filtered["기타"].astype(str).str.contains(kw, na=False)
                )

            filtered = filtered[condition]

            # 🔥 조건 표시에도 기타 포함 표시
            cond_display.append("검색열: 건강상태 + 기타")


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
<title>사례기반 자원검색(AI)</title>
<style>{{style}}</style>
<style>
@media (min-width: 768px) {
  #tel_link {
    display: none !important;
  }
}
</style>
</head>
<body>
<div class="container">
<a href="/home" class="home-btn">홈으로</a>
<h2>사례기반 자원검색(AI)</h2>

<form method="post">
<textarea id="queryBox" name="query" placeholder="예: 담양에 사는거동불편한 어르신이 이용가능한 서비스">{{query}}</textarea>
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
  <div style="background:white;margin:5% auto;padding:20px;width:90%;max-width:520px;border-radius:10px;max-height:85vh;overflow-y:auto;-webkit-overflow-scrolling:touch;">
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
document.getElementById("queryBox").addEventListener("keydown", function(e) {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    this.form.submit();
  }
});
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
/* ====== 사전조사 전용 스타일 ====== */

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
</style>
</head>

<body>
<div class="container">

  <a href="/home" class="home-btn">홈으로</a>
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
            top:2%;
            left:0;
            right:0;
            padding:28px;
            width:92%;
            max-width:460px;
            border-radius:14px;
            text-align:center;
            box-shadow:0 10px 25px rgba(0,0,0,0.15)">
    <h3 id="modalTitle" style="margin-bottom:15px;">사전조사 결과 안내</h3>

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
      showGuide("치매약을 복약 중인 경우 일상생활 수행능력과 <br class='pc-br'> 관계없이 <b>통합돌봄 대상</b>입니다.");
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
  <a href="/home" class="home-btn">홈으로</a>
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

