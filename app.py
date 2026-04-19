from flask import Flask, render_template_string, request, jsonify, redirect, url_for, session, send_file
import pandas as pd
import os
import re
import json
from io import BytesIO
from collections import defaultdict

from dotenv import load_dotenv
load_dotenv()

from openai import OpenAI
import requests

def make_cache_key(text):
    text = str(text or "")
    text = text.strip()
    text = re.sub(r"\s+", " ", text)
    return text
def compress_text(s, max_len=60):
    s = str(s).strip()
    if len(s) <= max_len:
        return s

    half = max_len // 2
    return s[:half] + " … " + s[-half:]


app = Flask(__name__)
DESC_CACHE = {}
import datetime

                           
SUPABASE_URL = "https://iiktpwqncvwvrzytfssb.supabase.co"
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

SUPABASE_HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json"
}

def update_visitors():
    now = datetime.datetime.now()

    # 🔥 로컬 테스트용
    if os.getenv("RENDER") is None:
        return 100, 5

    # 같은 브라우저에서 1시간 이내 재방문이면 카운트 안 함
    last_visit_str = session.get("last_visit_time", "")
    if last_visit_str:
        try:
            last_visit = datetime.datetime.fromisoformat(last_visit_str)
            if (now - last_visit).total_seconds() < 3600:
                select_url = f"{SUPABASE_URL}/rest/v1/visit_stats?id=eq.1&select=*"
                res = requests.get(select_url, headers=SUPABASE_HEADERS)
                rows = res.json()

                if rows:
                    data = rows[0]
                    return int(data.get("total_count", 0)), int(data.get("today_count", 0))
                else:
                    return 0, 0
        except:
            pass

    today = now.strftime("%Y-%m-%d")

    select_url = f"{SUPABASE_URL}/rest/v1/visit_stats?id=eq.1&select=*"
    res = requests.get(select_url, headers=SUPABASE_HEADERS)
    rows = res.json()

    if not rows:
        total = 1
        today_count = 1

        insert_url = f"{SUPABASE_URL}/rest/v1/visit_stats"
        requests.post(
            insert_url,
            headers={**SUPABASE_HEADERS, "Prefer": "return=representation"},
            json={
                "id": 1,
                "total_count": total,
                "today_date": today,
                "today_count": today_count
            }
        )
    else:
        data = rows[0]
        total = int(data.get("total_count", 0)) + 1

        if data.get("today_date") == today:
            today_count = int(data.get("today_count", 0)) + 1
        else:
            today_count = 1

        patch_url = f"{SUPABASE_URL}/rest/v1/visit_stats?id=eq.1"
        requests.patch(
            patch_url,
            headers=SUPABASE_HEADERS,
            json={
                "total_count": total,
                "today_date": today,
                "today_count": today_count
            }
        )

    # 방문 로그 저장
    log_url = f"{SUPABASE_URL}/rest/v1/visit_logs"
    requests.post(
        log_url,
        headers=SUPABASE_HEADERS,
        json={
            "ip": request.remote_addr
        }
    )

    # 마지막 방문 시각 저장
    session["last_visit_time"] = now.isoformat()

    return total, today_count

app.secret_key = "super_secret_key"

@app.before_request
def require_login_all_pages():
    if (
        request.path == "/"
        or request.path == "/login"
        or request.path == "/admin"
        or request.path.startswith("/static")
    ):
        return None

    if request.path.startswith("/stats"):
        if not session.get("is_admin"):
            return redirect(url_for("admin_login"))
        return None

    if not session.get("logged_in"):
        return redirect(url_for("login"))

FILE_PATH = "service_resources.xlsx"
# =========================
# 서비스 그룹 엑셀 로드 (AI 추천용)
# =========================
SERVICE_GROUP_FILE = "service_group.xlsx"

service_df = pd.read_excel(SERVICE_GROUP_FILE).fillna("")
service_df.columns = service_df.columns.astype(str).str.replace(" ", "").str.strip()


# =========================
# 로그인 체크
# =========================
from functools import wraps
from flask import session, redirect, url_for

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated_function
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
  margin:0;
  min-height:100vh;
  font-family:'Pretendard',sans-serif;
  background:#f5f6f7;
  color:#1f2937;
  display:flex;
  justify-content:center;
  align-items:center;
  padding:24px 16px;
}

.admin-link{
  position:absolute;
  top:14px;
  right:14px;
  display:inline-flex;
  align-items:center;
  justify-content:center;
  height:32px;
  padding:0 12px;
  border:none;
  border-radius:999px;
  background:rgba(255,255,255,0.88);
  color:#1f2937;
  font-size:13px;
  font-weight:700;
  text-decoration:none;
  box-shadow:0 4px 14px rgba(0,0,0,0.12);
  transition:all .18s ease;
  z-index:2;
}

.admin-link:hover{
  background:#ffffff;
  transform:translateY(-1px);
}

.admin-link:active{
  transform:translateY(0);
}

.box{
  position:relative;
  width:100%;
  max-width:420px;
  background:#ffffff;
  border:1px solid #e5e7eb;
  border-radius:22px;
  padding:40px 24px 28px 24px;
  text-align:center;
  box-shadow:0 4px 16px rgba(15,23,42,0.04);
}

.simple-logo{
  font-size:30px;
  font-weight:800;
  letter-spacing:-0.8px;
  color:#111827;
  margin-bottom:8px;
}

.logo-line{
  width:40px;
  height:3px;
  margin:6px auto 8px auto;
  border-radius:999px;
  background:linear-gradient(135deg,#3b82f6,#2563eb);
}

.sub-title{
  font-size:14px;
  color:#6b7280;
  margin-bottom:48px;
  line-height:1.5;
}


.error-msg{
  background:#fff4f4;
  color:#d93025;
  border:1px solid #ffd9d6;
  padding:12px 14px;
  border-radius:12px;
  font-size:14px;
  margin:0 0 14px 0;
  text-align:left;
}

.form-area{
  text-align:left;
}
.input-label{
  display:block;
  font-size:14px;
  font-weight:700;
  color:#374151;
  margin-bottom:8px;
}

input{
  width:100%;
  height:54px;
  padding:0 16px;
  border:1px solid #d1d5db;
  border-radius:12px;
  font-size:16px;
  color:#111827;
  background:#fff;
  outline:none;
  transition:border-color 0.15s, box-shadow 0.15s;
  margin-bottom:14px;
}

input::placeholder{
  color:#9ca3af;
}

input:focus{
  border-color:#2563eb;
  box-shadow:0 0 0 3px rgba(37,99,235,0.08);
}

button{
  width:100%;
  height:54px;
  border:none;
  border-radius:12px;
  background:linear-gradient(135deg,#3b82f6,#2563eb);
  color:#ffffff;
  font-size:17px;
  font-weight:700;
  cursor:pointer;
  transition:all 0.15s;
  box-shadow:0 4px 14px rgba(37,99,235,0.25);
}

button:hover{
  opacity:0.9;
}

.notice{
  margin-top:22px;
  padding-top:18px;
  border-top:1px solid #f1f5f9;
  font-size:12px;
  color:#6b7280;
  line-height:1.65;
  word-break:keep-all;
}

.bottom-logo{
  margin-top:16px;
}

.bottom-logo img{
  width:100%;
  max-width:210px;
  display:block;
  margin:0 auto;
  opacity:0.82;
}

@media (max-width:480px){
  body{
    min-height:100dvh;
    padding:16px;
    align-items:center;
  }

.box{
  box-shadow:0 10px 30px rgba(0,0,0,0.06);
  padding:48px 24px 36px 24px;
}

  .simple-logo{
    font-size:28px;
  }

  .sub-title{
    font-size:13px;
    margin-bottom:40px;
  }

  .input-label{
    font-size:13px;
  }

  input{
    height:50px;
    font-size:15px;
    border-radius:10px;
  }

  button{
    height:50px;
    font-size:16px;
    border-radius:10px;
  }

  .notice{
    font-size:11.5px;
  }

  .bottom-logo img{
    max-width:190px;
  }
}

</style>
</head>

<body>
<div class="box">
  <a href="/admin" class="admin-link">관리자</a>

  <div class="simple-logo">케어네비</div>
  <div class="logo-line"></div>
  <div class="sub-title">통합돌봄 지원 시스템 사용자 로그인</div>

  {% if error %}
    <div class="error-msg">❌ {{error}}</div>
  {% endif %}

  <form method="post" class="form-area">
    <input type="password" name="password" placeholder="비밀번호를 입력하세요">
    <button type="submit">로그인</button>
  </form>

  <div class="notice">
    ※ 본 서비스는 광주전라제주지역본부<br>
    관할 지자체, 지사 직원만 이용 가능합니다.
  </div>


<div class="bottom-bar">

  <div class="bottom-logo">
    <img src="/static/ci.png" alt="CI">
  </div>

  
</div>

</div>
</body>
</html>
"""
ADMIN_LOGIN_HTML = """
<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>관리자 인증</title>

<style>
*{ box-sizing:border-box; }

body{
  margin:0;
  min-height:100vh;
  font-family:'Pretendard',sans-serif;
  background:#f5f6f7;
  color:#1f2937;
  display:flex;
  justify-content:center;
  align-items:center;
  padding:24px 16px;
}

.box{
  position:relative;
  width:100%;
  max-width:420px;
  background:#ffffff;
  border:1px solid #e5e7eb;
  border-radius:22px;
  padding:40px 24px 28px 24px;
  text-align:center;
  box-shadow:0 4px 16px rgba(15,23,42,0.04);
}

.simple-logo{
  font-size:28px;
  font-weight:800;
  letter-spacing:-0.8px;
  color:#111827;
  margin-bottom:8px;
}

.logo-line{
  width:40px;
  height:3px;
  margin:6px auto 8px auto;
  border-radius:999px;
  background:linear-gradient(135deg,#3b82f6,#2563eb);
}

.sub-title{
  font-size:14px;
  color:#6b7280;
  margin-bottom:40px;
  line-height:1.5;
}

.error-msg{
  background:#fff4f4;
  color:#d93025;
  border:1px solid #ffd9d6;
  padding:12px 14px;
  border-radius:12px;
  font-size:14px;
  margin:0 0 14px 0;
  text-align:left;
}

.form-area{
  text-align:left;
}

input{
  width:100%;
  height:54px;
  padding:0 16px;
  border:1px solid #d1d5db;
  border-radius:12px;
  font-size:16px;
  color:#111827;
  background:#fff;
  outline:none;
  transition:border-color 0.15s, box-shadow 0.15s;
  margin-bottom:14px;
}

input::placeholder{
  color:#9ca3af;
}

input:focus{
  border-color:#2563eb;
  box-shadow:0 0 0 3px rgba(37,99,235,0.08);
}

button{
  width:100%;
  height:54px;
  border:none;
  border-radius:12px;
  background:linear-gradient(135deg,#3b82f6,#2563eb);
  color:#ffffff;
  font-size:17px;
  font-weight:700;
  cursor:pointer;
  transition:all 0.15s;
  box-shadow:0 4px 14px rgba(37,99,235,0.25);
}

button:hover{
  opacity:0.9;
}

.back-link{
  display:inline-block;
  margin-top:14px;
  font-size:13px;
  color:#6b7280;
  text-decoration:none;
}

.back-link:hover{
  color:#2563eb;
}

@media (max-width:480px){
  body{
    min-height:100dvh;
    padding:16px;
  }

  .box{
    box-shadow:0 10px 30px rgba(0,0,0,0.06);
    padding:48px 24px 36px 24px;
  }

  .simple-logo{
    font-size:26px;
  }

  .sub-title{
    font-size:13px;
    margin-bottom:34px;
  }

  input{
    height:50px;
    font-size:15px;
    border-radius:10px;
  }

  button{
    height:50px;
    font-size:16px;
    border-radius:10px;
  }
}
</style>
</head>

<body>
<div class="box">
  <div class="simple-logo">관리자 인증</div>
  <div class="logo-line"></div>
  <div class="sub-title">통계 페이지 접근을 위해 관리자 암호를 입력하세요.</div>

  {% if error %}
    <div class="error-msg">❌ {{error}}</div>
  {% endif %}

  <form method="post" class="form-area">
    <input type="password" name="password" placeholder="관리자 암호를 입력하세요">
    <button type="submit">통계 페이지로 이동</button>
  </form>

  <a href="/login" class="back-link">로그인 페이지로 돌아가기</a>
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

    return render_template_string(LOGIN_HTML, error="", total=0, today=0)

@app.route("/admin", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        pw = request.form.get("password", "")

        if pw == "admin":
            session["is_admin"] = True
            return redirect(url_for("stats"))
        else:
            return render_template_string(
                ADMIN_LOGIN_HTML,
                error="관리자 암호가 올바르지 않습니다."
            )

    return render_template_string(ADMIN_LOGIN_HTML, error="")

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
  max-width:860px;
  margin:auto;
  padding:30px 20px 40px 20px;
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
  margin-top:16px;
  width:100%;
  height:46px;
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
  display:flex;
  align-items:flex-start;
  gap:6px;
  padding:8px 0;
  cursor:pointer;
  line-height:1.6;
  color:#111827;
}

.item::before{
  content:"-";
  flex:0 0 auto;
  margin-top:0;
}

.item-text{
  flex:1;
  min-width:0;
  white-space:normal;
  word-break:keep-all;
  overflow-wrap:break-word;
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
def find_col(*names):
    for name in names:
        clean_name = str(name).replace("\ufeff", "").replace("\n", "").replace("\r", "").replace(" ", "").strip()
        for c in df.columns:
            clean_c = str(c).replace("\ufeff", "").replace("\n", "").replace("\r", "").replace(" ", "").strip()
            if clean_c == clean_name:
                return c
    return None


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


def normalize_sido(text):
    t = str(text or "")

    t = (
        t.replace("\u00a0", "")
         .replace("\ufeff", "")
         .replace("\n", "")
         .replace("\r", "")
         .strip()
    )

    mapping = {
        "광주": "광주광역시",
        "광주시": "광주광역시",
        "광주 광역시": "광주광역시",
        "광주광역시": "광주광역시",

        "전남": "전라남도",
        "전라남도": "전라남도",

        "전북": "전북특별자치도",
        "전라북도": "전북특별자치도",
        "전북특별자치도": "전북특별자치도",

        "제주": "제주특별자치도",
        "제주도": "제주특별자치도",
        "제주특별자치도": "제주특별자치도"
    }

    return mapping.get(t, t)


def normalize_sigungu(text):
    t = str(text or "").strip()

    mapping = {
        "나주": "나주시",
        "목포": "목포시",
        "순천": "순천시",
        "여수": "여수시",
        "광양": "광양시",
        "담양": "담양군",
        "곡성": "곡성군",
        "구례": "구례군",
        "고흥": "고흥군",
        "보성": "보성군",
        "화순": "화순군",
        "장흥": "장흥군",
        "강진": "강진군",
        "해남": "해남군",
        "영암": "영암군",
        "무안": "무안군",
        "함평": "함평군",
        "영광": "영광군",
        "장성": "장성군",
        "완도": "완도군",
        "진도": "진도군",
        "신안": "신안군",
        "전주": "전주시",
        "군산": "군산시",
        "익산": "익산시",
        "정읍": "정읍시",
        "남원": "남원시",
        "김제": "김제시",
        "완주": "완주군",
        "진안": "진안군",
        "무주": "무주군",
        "장수": "장수군",
        "임실": "임실군",
        "순창": "순창군",
        "고창": "고창군",
        "부안": "부안군",
        "제주": "제주시",
        "서귀포": "서귀포시"
    }

    return mapping.get(t, t)


SIGUNGU_MAP = {
    "광주광역시": ["동구", "서구", "남구", "북구", "광산구"],

    "전라남도": [
        "강진군", "고흥군", "곡성군", "광양시", "구례군",
        "나주시", "담양군", "목포시", "무안군",
        "보성군", "순천시", "신안군",
        "여수시", "영광군", "영암군", "완도군",
        "장성군", "장흥군", "진도군",
        "함평군", "해남군", "화순군"
    ],

    "전북특별자치도": [
        "고창군", "군산시", "김제시", "남원시",
        "무주군", "부안군",
        "순창군",
        "완주군", "익산시", "임실군",
        "장수군", "전주시", "정읍시", "진안군"
    ],

    "제주특별자치도": ["제주시", "서귀포시"]
}

SIDO_OPTIONS = ["광주광역시", "전라남도", "전북특별자치도", "제주특별자치도"]
SIGUNGU_OPTIONS = sorted(set(
    normalize_sigungu(v) for v in sorted_unique_values("시군구") if str(v).strip()
))

MAIN_CATEGORY_OPTIONS = sorted_unique_values("대분류")
MIDDLE_CATEGORY_OPTIONS = sorted_unique_values("중분류")
MANAGER_OPTIONS = sorted_unique_values("관리주체")

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
  margin-top:18px;   /* 👈 여기 추가 */
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

  padding:16px;

  border-radius:16px;

  margin-bottom:10px;

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
  min-height:50px;
}

  .icon{
    width:44px;
    height:44px;
    font-size:20px;
  }

}
.text span{
  display:block;
  font-size:13px;
  color:#6b7280;
  line-height:1.5;

  word-break:keep-all;      /* 🔥 단어 안깨짐 (핵심) */
  overflow-wrap:break-word; /* 🔥 줄 필요하면 자연스럽게 */
}

@media (max-width:480px){
  .text span{
    font-size:12.5px;
    line-height:1.45;
  }
}

/* ===== 카피라이트 (HOME 전용 추가) ===== */
.copyright{
  text-align:right;
  margin-top:22px;
  margin-bottom:6px;
  padding:0 12px;
}

.copyright-line{
  width:44px;
  height:2px;
  margin:0 0 12px auto;
  border-radius:999px;
  background:linear-gradient(135deg,#93c5fd,#2563eb);
  opacity:0.9;
}

.copyright-main{
  font-size:12.5px;
  color:#9ca3af;
  line-height:1.5;
  font-weight:500;
  word-break:keep-all;
}

.copyright-sub{
  margin-top:4px;
  font-size:15px;
  color:#374151;
  font-weight:600;
}

.copyright-sub span{
  color:#2563eb;
  font-weight:800;
}


.bottom-footer{
  margin-top:22px;
  padding:0 12px;
  display:flex;
  justify-content:space-between;
  align-items:flex-end;
  gap:16px;
}

.visitor-box{
  display:flex;
  gap:8px;
  flex-wrap:wrap;
}

.visitor-box div{
  padding:4px 10px;
  border-radius:999px;
  background:#f1f5f9;
  color:#6b7280;
  font-size:12px;
  line-height:1.2;
  white-space:nowrap;
}

@media (max-width:480px){
  .bottom-footer{
    flex-direction:column-reverse;
    align-items:flex-end;
    gap:10px;
    padding:0 8px;
  }

  .visitor-box{
    width:100%;
    justify-content:flex-end;
  }

  .visitor-box div{
    font-size:11px;
    padding:4px 8px;
  }

  .copyright{
    width:100%;
    text-align:right;
    margin-top:0;
    margin-bottom:4px;
    padding:0;
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
<b>사례기반 서비스내용 검색(AI)</b>
<span>입력한 사례를 분석하여 적합한 통합돌봄 서비스를 추천합니다.</span>
</div>

</a>

<a href="/combo" class="card">

<div class="icon">🔎</div>

<div class="text">
<b>조건기반 자원검색</b>
<span>시도, 시군구, 대분류, 중분류, 프로그램, 기관명 조건으로 서비스 자원을 검색합니다.</span>
</div>

</a>

<a href="/care" class="card">

<div class="icon">📝</div>

<div class="text">
<b>통합돌봄 사전조사</b>
<span>일상생활 수행능력(ADL) 기반 사전조사를 진행합니다.</span>
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
<div class="bottom-footer">

  <div class="visitor-box">
    <div>총 {{total}}</div>
    <div>오늘 {{today}}</div>
  </div>

  <div class="copyright">
    <div class="copyright-line"></div>
    <div class="copyright-main">
      ©국민건강보험공단 광주전라제주지역본부
    </div>
    <div class="copyright-sub">
      통합돌봄 연구반 <span>돌봄곳간</span>
    </div>
  </div>

</div>

<style>
@media (max-width:480px){
  a[style*="position:fixed"]{
    right:14px !important;
    bottom:14px !important;
    width:54px !important;
    height:54px !important;
    font-size:22px !important;
  }
}
</style>
<!-- ===== Floating Button ===== -->
<div id="reportBtn">
  <svg xmlns="http://www.w3.org/2000/svg" width="26" height="26" fill="white" viewBox="0 0 24 24">
    <path d="M21 6h-2V3H5v3H3v15h18V6zM7 5h10v1H7V5zm12 14H5V8h14v11z"/>
  </svg>
</div>

<!-- ===== Modal ===== -->
<div id="reportModal">
  <div id="reportBox">

    <div class="report-header">
      오류제보 / 의견보내기
      <span onclick="closeReport()">✕</span>
    </div>

    <iframe 
      src="https://docs.google.com/forms/d/e/1FAIpQLSfDa2M6edO0btvy5tWsOlE_H5Y2u0WaBSLfP2yz58_DwMfwWA/viewform?embedded=true"
      frameborder="0">
    </iframe>

  </div>
</div>

<style>

/* ===== 버튼 ===== */
#reportBtn{
  position:fixed;
  right:30px;
  bottom:50px;
  width:60px;
  height:60px;
  border-radius:50%;
  background:linear-gradient(135deg,#3b82f6,#2563eb);
  display:flex;
  align-items:center;
  justify-content:center;
  box-shadow:0 10px 24px rgba(0,0,0,0.25);
  cursor:pointer;
  z-index:9999;
  transition:0.2s;
}

#reportBtn:hover{
  transform:scale(1.08);
}

/* ===== 모달 ===== */
#reportModal{
  display:none;
  position:fixed;
  inset:0;
  background:rgba(0,0,0,0.55);
  z-index:9998;
  justify-content:center;
  align-items:center;
}

/* ===== 박스 ===== */
#reportBox{
  width:90%;
  max-width:520px;
  height:80vh;
  background:white;
  border-radius:16px;
  overflow:hidden;
  display:flex;
  flex-direction:column;
  animation:fadeUp 0.25s ease;
}

/* ===== 헤더 ===== */
.report-header{
  padding:14px 16px;
  font-weight:700;
  background:#f3f6fb;
  display:flex;
  justify-content:space-between;
  align-items:center;
}

.report-header span{
  cursor:pointer;
  font-size:18px;
}

/* ===== iframe ===== */
#reportBox iframe{
  flex:1;
  width:100%;
  border:none;
}

/* ===== 애니메이션 ===== */
@keyframes fadeUp{
  from{
    opacity:0;
    transform:translateY(20px);
  }
  to{
    opacity:1;
    transform:translateY(0);
  }
}

/* ===== 모바일 ===== */
@media (max-width:480px){

  #reportBtn{
    left:14px;     /* 👈 추가 */
    right:auto;    /* 👈 추가 */
    bottom:50px;
    width:54px;
    height:54px;
  }

  #reportBox{
    width:100%;
    height:100%;
    border-radius:0;
  }

}

</style>

<script>
const reportBtn = document.getElementById("reportBtn");
const reportModal = document.getElementById("reportModal");

/* 홈 진입 시 현재 상태를 홈으로 고정하고, 홈 상태를 하나 더 쌓아둠 */
history.replaceState({ page: "home-root" }, "", location.href);
history.pushState({ page: "home" }, "", location.href);

/* 오류제보 버튼 클릭 → 모달 열기 */
reportBtn.onclick = () => {
  reportModal.style.display = "flex";
  history.pushState({ modal: "report" }, "", location.href);
};

function closeReport(){
  if(reportModal.style.display === "flex"){
    reportModal.style.display = "none";
  }
}

/* 배경 클릭 시 닫기 */
reportModal.addEventListener("click", function(e){
  if(e.target === reportModal){
    closeReport();
  }
});

/* 뒤로가기 처리 */
window.addEventListener("popstate", function (e) {
  /* 모달 상태에서 뒤로가기 → 모달만 닫고 홈 유지 */
  if (e.state && e.state.page === "home") {
    if (reportModal.style.display === "flex") {
      reportModal.style.display = "none";
    }
    return;
  }

  /* 홈에서 뒤로가기 → 다시 홈 상태를 쌓아서 로그인으로 못 가게 함 */
  if (e.state && e.state.page === "home-root") {
    if (reportModal.style.display === "flex") {
      reportModal.style.display = "none";
    }
    history.pushState({ page: "home" }, "", location.href);
    return;
  }

  /* 혹시 예외 상태여도 홈 유지 */
  if (reportModal.style.display === "flex") {
    reportModal.style.display = "none";
  }
  history.pushState({ page: "home" }, "", location.href);
});
</script>


</body>
</html>
"""
@app.route("/home")
@login_required
def home():
    total, today = update_visitors()

    return render_template_string(HOME_HTML, style=BASE_STYLE, total=total, today=today)

STATS_HTML = """
<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>통계 페이지</title>
<style>
body{
  margin:0;
  background:#f4f6fb;
  font-family:'Pretendard',sans-serif;
  color:#111827;
}
.container{
  max-width:900px;
  margin:0 auto;
  padding:24px 16px 40px 16px;
}
.top-bar{
  display:flex;
  justify-content:space-between;
  align-items:center;
  margin-bottom:18px;
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
.card{
  background:#ffffff;
  border-radius:16px;
  padding:18px;
  margin-bottom:16px;
  box-shadow:0 6px 18px rgba(0,0,0,0.06);
}
.summary-row{
  display:flex;
  gap:12px;
  flex-wrap:wrap;
}
.summary-box{
  flex:1;
  min-width:180px;
  background:#f8fafc;
  border:1px solid #e5e7eb;
  border-radius:12px;
  padding:14px;
}
.summary-label{
  font-size:13px;
  color:#6b7280;
  margin-bottom:6px;
}
.summary-value{
  font-size:24px;
  font-weight:800;
  color:#111827;
}
table{
  width:100%;
  border-collapse:collapse;
  margin-top:10px;
}
th, td{
  padding:10px 8px;
  border-bottom:1px solid #e5e7eb;
  text-align:left;
  font-size:14px;
}
th{
  background:#f8fafc;
  font-weight:700;
}
h2{
  margin:0 0 10px 0;
  font-size:18px;
}
.small{
  font-size:12px;
  color:#6b7280;
}
@media (max-width:480px){
  .container{
    padding:16px 12px 28px 12px;
  }
  th, td{
    font-size:13px;
    padding:8px 6px;
  }
  .summary-value{
    font-size:22px;
  }
}
</style>
</head>
<body>
<div class="container">

  <div class="top-bar" style="display:flex;justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap;">
    <a href="/home" class="home-button">홈으로</a>

    <div style="display:flex;gap:8px;flex-wrap:wrap;">
      <a href="/stats/export/visits" class="home-button">방문자 엑셀</a>
      <a href="/stats/export/regions" class="home-button">지역클릭 엑셀</a>
    </div>
  </div>

  <div class="card">
    <h2>요약 통계</h2>
    <div class="summary-row">
      <div class="summary-box">
        <div class="summary-label">총 방문자수</div>
        <div class="summary-value">{{ total_count }}</div>
      </div>
      <div class="summary-box">
        <div class="summary-label">오늘 방문자수</div>
        <div class="summary-value">{{ today_count }}</div>
      </div>
    </div>
  </div>

  <div class="card">
    <h2>일자별 방문자수</h2>
    <table>
      <thead>
        <tr>
          <th>날짜</th>
          <th>방문자수</th>
        </tr>
      </thead>
      <tbody>
        {% for row in daily_visits %}
        <tr>
          <td>{{ row["date"] }}</td>
          <td>{{ row["count"] }}</td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
  </div>

  <div class="card">
    <h2>일자별 지역 클릭수</h2>
    <table>
      <thead>
        <tr>
          <th>날짜</th>
          <th>시도</th>
          <th>시군구</th>
          <th>검색구분</th>
          <th>클릭수</th>
        </tr>
      </thead>
      <tbody>
        {% for row in daily_regions %}
        <tr>
          <td>{{ row["date"] }}</td>
          <td>{{ row["sido"] }}</td>
          <td>{{ row["sigungu"] }}</td>
          <td>{{ row["search_type"] }}</td>
          <td>{{ row["count"] }}</td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
  </div>

</div>
</body>
</html>
"""
@app.route("/stats")
def stats():

    if os.getenv("RENDER") is None:
        total_count = 100
        today_count = 5

        daily_visits = [
            {"date": "2026-04-17", "count": 12},
            {"date": "2026-04-18", "count": 18},
            {"date": "2026-04-19", "count": 5}
        ]

        daily_regions = [
            {"date": "2026-04-18", "sido": "광주광역시", "sigungu": "북구", "search_type": "조건기반", "count": 3},
            {"date": "2026-04-18", "sido": "전라남도", "sigungu": "나주시", "search_type": "사례기반", "count": 2},
            {"date": "2026-04-19", "sido": "광주광역시", "sigungu": "서구", "search_type": "조건기반", "count": 1}
        ]

        return render_template_string(
            STATS_HTML,
            total_count=total_count,
            today_count=today_count,
            daily_visits=daily_visits,
            daily_regions=daily_regions
        )

    stats_res = requests.get(
        f"{SUPABASE_URL}/rest/v1/visit_stats?id=eq.1&select=*",
        headers=SUPABASE_HEADERS
    )
    stats_rows = stats_res.json() if stats_res.ok else []
    stats_row = stats_rows[0] if stats_rows else {}

    total_count = int(stats_row.get("total_count", 0))
    today_count = int(stats_row.get("today_count", 0))

    visit_res = requests.get(
        f"{SUPABASE_URL}/rest/v1/visit_logs?select=created_at,ip&order=created_at.desc",
        headers=SUPABASE_HEADERS
    )
    visit_rows = visit_res.json() if visit_res.ok else []

    daily_visit_map = defaultdict(int)
    for row in visit_rows:
        created_at = str(row.get("created_at", ""))
        if created_at:
            date_str = created_at[:10]
            daily_visit_map[date_str] += 1

    daily_visits = []
    for date_str in sorted(daily_visit_map.keys(), reverse=True):
        daily_visits.append({
            "date": date_str,
            "count": daily_visit_map[date_str]
        })

    region_res = requests.get(
        f"{SUPABASE_URL}/rest/v1/region_logs?select=created_at,sido,sigungu,search_type&order=created_at.desc",
        headers=SUPABASE_HEADERS
    )
    region_rows = region_res.json() if region_res.ok else []

    daily_region_map = defaultdict(int)
    for row in region_rows:
        created_at = str(row.get("created_at", ""))
        date_str = created_at[:10] if created_at else ""
        sido = str(row.get("sido", "") or "")
        sigungu = str(row.get("sigungu", "") or "")
        raw_search_type = str(row.get("search_type", "") or "").strip()

        if raw_search_type == "combo":
            search_type = "조건기반"
        elif raw_search_type == "desc":
            search_type = "사례기반"
        else:
            search_type = raw_search_type or "-"

        key = (date_str, sido, sigungu, search_type)
        daily_region_map[key] += 1

    daily_regions = []
    for key in sorted(daily_region_map.keys(), reverse=True):
        date_str, sido, sigungu, search_type = key
        daily_regions.append({
            "date": date_str,
            "sido": sido,
            "sigungu": sigungu,
            "search_type": search_type,
            "count": daily_region_map[key]
        })

    return render_template_string(
        STATS_HTML,
        total_count=total_count,
        today_count=today_count,
        daily_visits=daily_visits,
        daily_regions=daily_regions
    )

@app.route("/stats/export/visits")
def export_stats_visits():

    if os.getenv("RENDER") is None:
        daily_visits = [
            {"날짜": "2026-04-17", "방문자수": 12},
            {"날짜": "2026-04-18", "방문자수": 18},
            {"날짜": "2026-04-19", "방문자수": 5}
        ]
    else:
        visit_res = requests.get(
            f"{SUPABASE_URL}/rest/v1/visit_logs?select=created_at,ip&order=created_at.desc",
            headers=SUPABASE_HEADERS
        )
        visit_rows = visit_res.json() if visit_res.ok else []

        daily_visit_map = defaultdict(int)
        for row in visit_rows:
            created_at = str(row.get("created_at", ""))
            if created_at:
                date_str = created_at[:10]
                daily_visit_map[date_str] += 1

        daily_visits = []
        for date_str in sorted(daily_visit_map.keys(), reverse=True):
            daily_visits.append({
                "날짜": date_str,
                "방문자수": daily_visit_map[date_str]
            })

    df_export = pd.DataFrame(daily_visits)

    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df_export.to_excel(writer, index=False, sheet_name="일자별방문자수")

    output.seek(0)

    return send_file(
        output,
        as_attachment=True,
        download_name="일자별_방문자수.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

@app.route("/stats/export/regions")
def export_stats_regions():

    if os.getenv("RENDER") is None:
        daily_regions = [
            {"날짜": "2026-04-18", "시도": "광주광역시", "시군구": "북구", "검색구분": "조건기반", "클릭수": 3},
            {"날짜": "2026-04-18", "시도": "전라남도", "시군구": "나주시", "검색구분": "사례기반", "클릭수": 2},
            {"날짜": "2026-04-19", "시도": "광주광역시", "시군구": "서구", "검색구분": "조건기반", "클릭수": 1}
        ]
    else:
        region_res = requests.get(
            f"{SUPABASE_URL}/rest/v1/region_logs?select=created_at,sido,sigungu,search_type&order=created_at.desc",
            headers=SUPABASE_HEADERS
        )
        region_rows = region_res.json() if region_res.ok else []

        daily_region_map = defaultdict(int)
        for row in region_rows:
            created_at = str(row.get("created_at", ""))
            date_str = created_at[:10] if created_at else ""
            sido = str(row.get("sido", "") or "")
            sigungu = str(row.get("sigungu", "") or "")
            raw_search_type = str(row.get("search_type", "") or "").strip()

            if raw_search_type == "combo":
                search_type = "조건기반"
            elif raw_search_type == "desc":
                search_type = "사례기반"
            else:
                search_type = raw_search_type or "-"

            key = (date_str, sido, sigungu, search_type)
            daily_region_map[key] += 1

        daily_regions = []
        for key in sorted(daily_region_map.keys(), reverse=True):
            date_str, sido, sigungu, search_type = key
            daily_regions.append({
                "날짜": date_str,
                "시도": sido,
                "시군구": sigungu,
                "검색구분": search_type,
                "클릭수": daily_region_map[key]
            })

    df_export = pd.DataFrame(daily_regions)

    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df_export.to_excel(writer, index=False, sheet_name="일자별지역클릭수")

    output.seek(0)

    return send_file(
        output,
        as_attachment=True,
        download_name="일자별_지역클릭수.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

@app.route("/guide")
def guide():
    return redirect("/static/guide.pdf")

# =========================
# 상세 API (팝업에서 사용)
# =========================
@app.route("/detail/<int:idx>")
def detail(idx):
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
        "프로그램명칭": str(r.get("프로그램명(사업명)", "")),
        "서비스제공기관명": str(r.get("서비스제공기관명", "")),
        "기관연락처": str(r.get("기관연락처", "")),
        "기관주소": str(r.get("기관주소", "")),
        "기타": str(r.get("기타", "")),
    })

@app.route("/combo", methods=["GET","POST"])
def combo():
    source = request.form if request.method == "POST" else request.args

    sido = normalize_sido((source.get("sido", "") or "").strip())
    sigungu = (source.get("sigungu", "") or "").strip()
    main_category = (source.get("main_category", "") or "").strip()
    manager = (source.get("manager", "") or "").strip()
    middle_category = (source.get("middle_category", "") or "").strip()
    program_kw = (source.get("program_kw", "") or "").strip()
    org_kw = (source.get("org_kw", "") or "").strip()
    action = (source.get("action", "") or "").strip()

    results = {}
    sorted_managers_by_region = {}
    count = 0
    show_results = (action == "search")

    sigungu_options = []

    if sido and sido in SIGUNGU_MAP:
        sigungu_options = SIGUNGU_MAP[sido]

    middle_category_options = MIDDLE_CATEGORY_OPTIONS
    if main_category and "대분류" in df.columns and "중분류" in df.columns:
        temp = df[
            df["대분류"].fillna("").astype(str).str.strip() == main_category
        ]
        middle_category_options = sorted(
            set(
                temp["중분류"].fillna("").astype(str).str.strip()
            ),
            key=lambda x: (x == "기타", x)
        )
        middle_category_options = [v for v in middle_category_options if v]

    if show_results:
        filtered = df.copy()

        if sido and "시도" in filtered.columns:
            filtered = filtered[
                filtered["시도"].fillna("").astype(str).apply(normalize_sido) == sido
            ]

        if sigungu and "시군구" in filtered.columns:
            filtered = filtered[
                filtered["시군구"].fillna("").astype(str).apply(normalize_sigungu) == sigungu
            ]

        if main_category and "대분류" in filtered.columns:
            filtered = filtered[
                filtered["대분류"].fillna("").astype(str).str.strip() == main_category
            ]

        if middle_category and "중분류" in filtered.columns:
            filtered = filtered[
                filtered["중분류"].fillna("").astype(str).str.strip() == middle_category
            ]

        if manager and "관리주체" in filtered.columns:
            filtered = filtered[
                filtered["관리주체"].fillna("").astype(str).str.strip() == manager
            ]

        if program_kw and "프로그램명(사업명)" in filtered.columns:
            filtered = filtered[
                filtered["프로그램명(사업명)"]
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
            row_sido = normalize_sido(str(row.get("시도", "")).strip())
            row_sigungu = normalize_sigungu(str(row.get("시군구", "")).strip())
            manager_key = str(row.get("관리주체", "")).strip() or "기타"

            if row_sido and row_sigungu:
                region_key = f"{row_sido}({row_sigungu})"
            elif row_sido:
                region_key = row_sido
            elif row_sigungu:
                region_key = row_sigungu
            else:
                region_key = "기타"

            results.setdefault(region_key, {})
            results[region_key].setdefault(manager_key, [])
            results[region_key][manager_key].append({
                "index": int(row["index"]),
                "label": f"{row.get('프로그램명(사업명)','')} ({row.get('서비스제공기관명','')})"
            })

        sorted_managers_by_region = {}
        for rk, mgrs in results.items():
            sorted_managers_by_region[rk] = sorted(
                mgrs.keys(),
                key=lambda x: (x != "공단", x)
            )

        
        count = sum(
            len(items)
            for manager_groups in results.values()
            for items in manager_groups.values()
        )

        if os.getenv("RENDER") is not None:
            requests.post(
                f"{SUPABASE_URL}/rest/v1/region_logs",
                headers=SUPABASE_HEADERS,
                json={
                    "sido": sido,
                    "sigungu": sigungu,
                    "result_count": count,
                    "ip": request.remote_addr,
                    "search_type": "combo"
               }
            )

    return render_template_string(
        COMBO_HTML,
        style=BASE_STYLE,
        sido=sido,
        sigungu=sigungu,
        main_category=main_category,
        middle_category=middle_category,
        manager=manager,
        program_kw=program_kw,
        org_kw=org_kw,
        sido_options=SIDO_OPTIONS,
        sigungu_options=sigungu_options,
        main_category_options=MAIN_CATEGORY_OPTIONS,
        middle_category_options=middle_category_options,
        manager_options=MANAGER_OPTIONS,
        results=results,
        sorted_managers_by_region=sorted_managers_by_region,
        count=count,
        show_results=show_results
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

.result h3{
  margin:18px 0 8px 0;
  font-size:18px;
  font-weight:800;
  color:#111827;
}

.manager-badge{
  display:inline-block;
  padding:4px 12px;
  border-radius:999px;
  background:#dbeafe;
  color:#1d4ed8;
  font-size:13px;
  font-weight:900;
  letter-spacing:0.3px;

  margin:14px 0 10px 0;   /* 🔥 위아래 간격 늘림 */
}

.manager-badge[data-type="공단"]{
  background:#fce7f3;
  color:#be185d;
}

.item{
  display:flex;
  align-items:flex-start;
  gap:6px;
  padding:8px 0;
  cursor:pointer;
  line-height:1.6;
  color:#111827;
}


.combo-top-bar{
  display:flex;
  justify-content:space-between;
  align-items:center;
  gap:12px;
  margin-top:12px;
}

.combo-reset-button{
  display:inline-block;
  width:auto;
  height:auto;
  margin-top:0;
  padding:8px 14px;
  border-radius:8px;
  background:#e5e7eb;
  color:#111827;
  font-size:14px;
  font-weight:500;
  border:none;
  cursor:pointer;
  flex:0 0 auto;
}

.combo-reset-button:hover{
  background:#d1d5db;
}

@media (max-width:480px){
  .combo-reset-button{
    font-size:13px;
    padding:6px 12px;
  }
}

.combo-warning{
  margin:18px 0 16px 0;
  padding:14px 20px;
  border-radius:12px;
  background:#fff7ed;
  border:1px solid #fdba74;
  color:#9a3412;
  font-size:14px;
  line-height:1.7;

  display:flex;
  align-items:flex-start;
  gap:8px;
}

@media (max-width:480px){
  .combo-warning{
    font-size:13px;
    line-height:1.65;
    padding:13px 14px;
  }
}


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

/* ===== 카피라이트 ===== */
.copyright{
  text-align:right;   /* 🔥 핵심 */
  margin-top:22px;
  margin-bottom:6px;
  padding:0 12px;
}

.copyright-line{
  width:44px;
  height:2px;
  margin:0 0 12px auto;   /* 🔥 오른쪽 정렬 */
  border-radius:999px;
  background:linear-gradient(135deg,#93c5fd,#2563eb);
  opacity:0.9;
}

.copyright-main{
  font-size:12.5px;
  color:#9ca3af;
  line-height:1.5;
  font-weight:500;
  word-break:keep-all;
  letter-spacing:0.2px;
}

.copyright-sub{
  margin-top:4px;
  font-size:15px;
  color:#374151;
  font-weight:600;
  letter-spacing:-0.2px;
}

.copyright-sub span{
  color:#2563eb;
  font-weight:800;
}

@media (max-width:480px){
  .copyright{
    margin-top:18px;
    margin-bottom:4px;
    padding:0 8px;
  }

  .copyright-line{
    margin-bottom:10px;
  }

  .copyright-main{
    font-size:11.5px;
    line-height:1.45;
  }

  .copyright-sub{
    margin-top:3px;
    font-size:13px;
  }
}
</style>
</head>
<body>
<div class="container">

<div class="top-bar combo-top-bar">
  <a href="/home" class="home-button">홈으로</a>
  <button type="button" class="combo-reset-button" onclick="resetDescPage()">초기화</button>
</div>

<div class="card">
<h2>조건기반 자원검색</h2>

<form method="post">
<input type="hidden" name="action" id="comboAction" value="">

<div class="section-box">
  <div class="section-title">지역조건</div>
  <div class="section-desc">시도와 시군구를 선택하여 지역 기준으로 검색합니다.</div>

  <label>시도</label>
  <select name="sido" onchange="handleSidoChange(this.form)">
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
<select name="main_category" onchange="handleMainCategoryChange(this.form)">
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

<label>관리주체</label>
<select name="manager">
  <option value="">전체</option>
  {% for m in manager_options %}
  <option value="{{m}}" {% if m==manager %}selected{% endif %}>{{m}}</option>
  {% endfor %}
</select>

  <label>프로그램</label>
  <input type="text" name="program_kw" value="{{program_kw}}" placeholder="프로그램명 포함 검색">

  <label>기관명</label>
  <input type="text" name="org_kw" value="{{org_kw}}" placeholder="기관명 포함 검색">
</div>

<button type="submit" class="menu-btn" onclick="setSearchAction()">검색하기</button>

</form>

{% if show_results %}
<div class="result" id="desc-result">

<p><b>총 {{count}}건이 조회되었습니다.</b></p>

<div class="combo-warning">
  <span style="flex:0 0 auto;">⚠️</span>
  <div style="flex:1; word-break:keep-all;">
    서비스 제공기관 정보는 현재 운영 중인 기관이며,
    실제 정보와 차이가 있을 수 있으니 정확한 사항은 해당 기관에 직접 확인하시기 바랍니다.
  </div>
</div>

{% if count == 0 %}
<p style="color:#6b7280;">조건에 맞는 서비스가 없습니다.</p>
{% endif %}


{% for region, manager_groups in results.items() %}
<h3>📍 {{region}}</h3>

{% for manager_name in sorted_managers_by_region[region] %}
{% set items = manager_groups[manager_name] %}

<div class="manager-badge" data-type="{{manager_name}}">{{manager_name}}</div>

{% for r in items %}
<div class="item" onclick="openDetail({{r['index']}})">
  <span class="item-bullet">-</span>
  <span class="item-text">{{r['label']}}</span>
</div>
{% endfor %}

{% endfor %}
{% endfor %}

</div>
{% endif %}
</div>

<div id="modal" style="display:none;position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,.5);">
  <div style="background:white;margin:0% auto;padding:20px;width:90%;max-width:520px;border-radius:10px;max-height:85vh;overflow-y:auto;-webkit-overflow-scrolling:touch;">
    <h3 id="m_title"></h3>
    <p style="margin:0 0 14px 0; line-height:1.6;">
      <b>기관명:</b> <span id="m_org" style="white-space:normal; word-break:keep-all;"></span>
    </p>
    <p>
      <b>기관 연락처:</b> <span id="m_tel"></span>
      <a id="tel_link" style="display:none; font-size:20px; margin-left:8px; text-decoration:none;">📞</a>
    </p>
    <p><b>기관주소:</b> <span id="m_addr"></span></p>
    <iframe id="m_map" width="100%" height="250" style="border:0;margin-top:10px;display:none;"></iframe>
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

      const addr = (d["기관주소"] || "").trim();
      const mapFrame = document.getElementById("m_map");

      if(addr){
        mapFrame.src =
          "https://www.google.com/maps?q=" + encodeURIComponent(addr) + "&output=embed";
        mapFrame.style.display = "block";
      } else {
        mapFrame.src = "";
        mapFrame.style.display = "none";
      }

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

function handleSidoChange(form){
  document.getElementById("comboAction").value = "change_sido";
  form.submit();
}

function handleMainCategoryChange(form){
  form.middle_category.value = "";
  document.getElementById("comboAction").value = "change_main_category";
  form.submit();
}

function setSearchAction(){
  document.getElementById("comboAction").value = "search";
}

function resetDescPage(){
  window.location.href = "/combo";
}


window.addEventListener("load", function(){
  const resultBox = document.getElementById("desc-result");
  if(resultBox){
    setTimeout(function(){
      resultBox.scrollIntoView({
        behavior: "smooth",
        block: "start"
      });
    }, 120);
  }
});
</script>

</body>
</html>
"""


@app.route("/desc", methods=["GET","POST"])
def desc():
    query = (request.values.get("query", "") or "").strip()

    results = {}
    cond_display = None
    count = 0
    service_results = []
    warning_msg = ""
    selected_sido = normalize_sido((request.values.get("sido", "") or "").strip())
    selected_sigungu = (request.values.get("sigungu", "") or "").strip()
    action = (request.values.get("action", "") or "").strip()
    cache_key = make_cache_key(query + "|" + selected_sido + "|" + selected_sigungu)
    do_search = (action == "search")
        
    if request.method == "POST" and do_search:
        import time

        if cache_key in DESC_CACHE:
            cached = DESC_CACHE[cache_key]

            if time.time() - cached["time"] < 600:
                service_results = cached["results"]
                count = len(service_results)
                warning_msg = cached["warning"]

                return render_template_string(
                    DESC_HTML,
                    style=BASE_STYLE,
                    query=query,
                    results=results,
                    cond_display=cond_display,
                    count=count,
                    service_results=service_results,
                    warning_msg=warning_msg,
                    selected_sido=selected_sido,
                    selected_sigungu=selected_sigungu,
                    sigungu_options=SIGUNGU_OPTIONS
                )
            else:
                del DESC_CACHE[cache_key]


        import time

        now = time.time()
        last_time = session.get("last_search_time", 0)

        if now - last_time < 10:
            warning_msg = "너무 빠르게 검색할 수 없습니다.\n10초 후 다시 시도해 주세요."

            return render_template_string(
                DESC_HTML,
                style=BASE_STYLE,
                query=query,
                results=results,
                cond_display=cond_display,
                count=count,
                service_results=service_results,
                warning_msg=warning_msg,
                selected_sido=selected_sido,
                selected_sigungu=selected_sigungu,
                sigungu_options=SIGUNGU_OPTIONS
            )

        session["last_search_time"] = now

        cond_display = []

        # ======================
        # 검색어 보강 (튜브/줄 + 복지용구 관련 표현 보정)
        # ======================
        query_for_ai = query
        q_norm = query.replace(" ", "")

        wound_context = any(k in q_norm for k in [
            "상처", "상처소독", "드레싱", "욕창", "염증", "감염", "고름",
            "진물", "봉합", "절개", "베임", "찰과상", "화상", "욕창관리"
        ])

        extra_aliases = []
        extra_aliases += expand_query_aliases(query)

        # ---- 튜브/의료처치 관련 ----
        if any(k in q_norm for k in ["콧줄", "비위관", "위관", "경관급식", "콧줄영양", "비위관영양"]):
            extra_aliases += ["튜브관리", "비위관", "경관영양", "위관관리"]

        if any(k in q_norm for k in ["소변줄", "유치도뇨", "도뇨줄", "폴리", "foley", "배뇨줄"]):
            extra_aliases += ["튜브관리", "유치도뇨관", "도뇨관관리", "배뇨관리"]

        if any(k in q_norm for k in ["기관절개", "석션", "흡인", "루", "장루", "요루", "튜브"]):
            extra_aliases += ["튜브관리", "루관리", "기관절개관리", "흡인", "감염관리"]

        # ---- 복지용구 관련 ----
        if any(k in q_norm for k in ["지팡이", "워커", "보행기", "보행차", "휠체어"]):
            extra_aliases += ["복지용구", "보행보조", "대여", "구입"]

        if any(k in q_norm for k in ["안전손잡이", "손잡이", "욕실손잡이", "화장실손잡이"]):
            extra_aliases += ["복지용구", "안전손잡이", "욕실안전", "낙상예방", "구입"]

        if any(k in q_norm for k in ["미끄럼방지", "미끄럼방지매트", "욕실매트", "논슬립", "미끄럼"]):
            extra_aliases += ["복지용구", "미끄럼방지", "욕실안전", "낙상예방", "구입"]

        if any(k in q_norm for k in ["목욕의자", "샤워의자", "목욕", "샤워"]):
            extra_aliases += ["복지용구", "목욕의자", "욕실안전", "구입"]

        if any(k in q_norm for k in ["이동변기", "간이변기", "변기", "좌변기"]):
            extra_aliases += ["복지용구", "이동변기", "배변보조", "구입"]

        if any(k in q_norm for k in ["기저귀", "요실금", "패드"]):
            extra_aliases += ["복지용구", "배변보조", "위생", "구입"]

        if any(k in q_norm for k in ["전동침대", "침대", "병원침대"]):
            extra_aliases += ["복지용구", "전동침대", "대여"]

        if any(k in q_norm for k in ["욕창", "욕창매트", "욕창방지", "자세변환", "체위변경"]):
            extra_aliases += ["복지용구", "욕창예방", "자세변환", "대여"]

        if any(k in q_norm for k in ["경사로", "문턱", "턱", "이동불편", "출입불편"]):
            extra_aliases += ["복지용구", "경사로", "이동보조", "구입"]

        # ---- 상처/감염/드레싱 관련 ----
        if wound_context:
            extra_aliases += ["감염관리", "상처관리", "드레싱", "의료처치", "방문진료"]

        extra_aliases = list(dict.fromkeys(extra_aliases))

        if extra_aliases:
            query_for_ai = query + " / 연관표현: " + ", ".join(extra_aliases)

        # ======================
        # 서비스 목록 문자열 생성
        # ======================

        service_text = ""

        for idx, r in service_df.iterrows():
            service_text += (
                f"{idx}. "
                f"{compress_text(r.get('서비스내용',''),18)} | "
                f"{compress_text(r.get('서비스설명',''),28)} | "
                f"{compress_text(r.get('검색어',''),28)}\n"
            )

        # ======================
        # 서비스 그룹 데이터 문자열 생성
        # ======================
        cond_display = []

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
                selected_sido=selected_sido,
                selected_sigungu=selected_sigungu,
                sigungu_options=SIGUNGU_OPTIONS
            )

        client = OpenAI(api_key=api_key)


        prompt = f"""
너는 통합돌봄 서비스 추천 전문가다.

사용자의 사례를 분석하고,
아래 서비스 목록 전체를 검토하여
적합한 서비스들을 폭넓게 추천하라.

중요:
- 파이썬이 미리 판단하지 않는다.
- 반드시 서비스목록의 '서비스설명'과 '검색어'를 적극적으로 참고하고, 사용자가 정확한 행정용어를 쓰지 않아도 의미가 비슷하면 연결해서 판단한다.
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
   - "반찬을 못함", "식사 준비 어려움", "도시락이 필요함", "밥배달", "식사배달", "배달식" → 식사지원, 반찬지원, 영양지원 계열을 우선 검토한다
   - "자주 배고파함", "허기짐", "굶는 편", "잘 못 먹음", "영양이 부족해 보임" → 영양지원, 식사지원, 반찬지원, 방문형지원 계열을 우선 검토한다
   - "지팡이", "워커", "보행기", "보행차", "휠체어" → 복지용구(보행보조, 대여/구입) 적극 고려
   - "안전손잡이", "손잡이", "욕실손잡이", "화장실손잡이" → 복지용구(안전손잡이, 욕실안전, 낙상예방) 적극 고려
   - "도구가 필요함", "보조도구 필요", "이동 도구 필요" → 복지용구(지팡이, 보행기, 휠체어 등)를 적극 우선 검토한다
   - "미끄럼방지", "미끄럼방지매트", "욕실매트", "논슬립", "미끄럼" → 복지용구(욕실안전, 낙상예방, 구입) 적극 고려
   - "목욕의자", "샤워의자", "목욕", "샤워" → 복지용구(목욕의자, 욕실안전, 구입) 고려
   - "이동변기", "간이변기", "변기", "좌변기" → 복지용구(배변보조, 구입) 고려
   - "기저귀", "요실금", "패드" → 복지용구(위생, 배변보조, 구입) 고려
   - "전동침대", "침대", "병원침대" → 복지용구(전동침대, 대여) 우선 고려
   - "욕창", "욕창매트", "욕창방지", "자세변환", "체위변경" → 복지용구(욕창예방, 자세변환, 대여) 및 의료처치 함께 고려
   - "경사로", "문턱", "턱", "이동불편", "출입불편" → 복지용구(경사로, 이동보조, 구입) 고려
   - "콧줄", "비위관", "위관", "경관급식", "소변줄", "도뇨줄", "유치도뇨", "장루", "요루", "기관절개", "석션", "흡인", "복막투석" → 방문진료의 의료처치(욕창, 루, 튜브관리 등)를 적극 우선 고려
   - 의료처치(욕창, 루, 튜브관리 등)가 적합하면 감염관리도 함께 검토한다
   - 매우 중요: 서비스내용의 "소독"은 기본적으로 집안/주거환경 관련 소독으로 본다
   - "상처 소독", "드레싱", "욕창 소독", "감염", "염증", "고름", "진물"처럼 의료적 맥락의 소독은 서비스내용 "소독"으로 연결하지 말고, 반드시 "감염관리" 또는 "의료처치(욕창, 루, 튜브관리 등)" 쪽으로 판단한다
   - 반대로 집 청소, 방역, 주거 위생, 해충, 집안 환경개선 맥락이면 서비스내용 "소독"을 검토한다
   - "무릎통증", "통증", "거동불편", "움직이기 어려움" → 재활, 기능회복, 방문보건, 이동지원 계열 고려
   - "요통", "허리가 자주 아픔", "허리 통증", "허리 불편" → 통증관리, 재활, 기능회복, 방문보건 계열을 우선 검토한다
   - "외로움", "말벗 필요", "혼자 지냄", "고립" → 정서지원, 안부확인, 돌봄연계를 우선 검토한다
   - 표현이 다르더라도 의미가 비슷하면 대표 욕구로 묶어서 판단한다
   - "다리가 저림", "다리 저림", "발 저림", "손발 저림", "찌릿함", "감각이상" → 신경증상, 통증, 재활, 기능회복, 방문보건, 이동지원 계열을 우선 검토한다
   - "오줌을 지림", "소변을 지림", "소변 실수", "배뇨 실수", "요실금" → 배뇨관리, 위생지원, 기저귀·패드 등 복지용구, 방문보건 계열을 우선 검토한다
   - "변을 지림", "대변 실수", "배변 실수", "배변 불편" → 배변관리, 위생지원, 복지용구, 방문보건 계열을 우선 검토한다
   - "자주 넘어진다", "휘청거린다", "낙상이 걱정된다", "균형이 불안하다" → 낙상예방, 안전지원, 보행보조 복지용구, 이동지원 계열을 우선 검토한다
   - "기억을 잘 못한다", "자꾸 깜빡한다", "약을 자주 잊는다" → 인지지원, 복약관리, 안부확인, 돌봄연계를 우선 검토한다
   - "약 챙기기 어렵다", "병원 가기 어렵다", "병원 동행이 필요하다" → 복약관리, 병원동행, 이동지원, 방문보건 계열을 우선 검토한다
   - "차려 먹기 어렵다", "챙겨 먹기 어렵다", "기운이 없다", "체중이 준다" → 영양지원, 식사지원, 반찬지원 계열을 우선 검토한다
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
{query_for_ai}
"""

        try:
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

            deduped = []
            seen_keys = set()

            for item in final_results:
                key = (
                    str(item.get("대분류", "")).strip(),
                    str(item.get("중분류", "")).strip(),
                    str(item.get("서비스내용", "")).strip()
                )
                if key not in seen_keys:
                    seen_keys.add(key)
                    deduped.append(item)



            final_results = deduped

            if os.getenv("RENDER") is not None:
                requests.post(
                    f"{SUPABASE_URL}/rest/v1/region_logs",
                    headers=SUPABASE_HEADERS,
                    json={
                        "sido": selected_sido,
                        "sigungu": selected_sigungu,
                        "result_count": len(final_results),
                        "ip": request.remote_addr,
                        "search_type": "desc"
                    }
                )

            if wound_context:
                wound_filtered = []

                for item in final_results:
                    service_name = str(item.get("서비스내용", "")).strip()

                    if service_name == "소독":
                        continue

                    wound_filtered.append(item)

                final_results = wound_filtered

            has_medical_tube = any(
                str(item.get("대분류", "")).strip() == "보건의료" and
                str(item.get("중분류", "")).strip() == "방문진료" and
                str(item.get("서비스내용", "")).strip() == "의료처치(욕창, 루, 튜브관리 등)"
                for item in final_results
            )

            has_infection = any(
                str(item.get("대분류", "")).strip() == "보건의료" and
                str(item.get("중분류", "")).strip() == "방문진료" and
                str(item.get("서비스내용", "")).strip() == "감염관리"
                for item in final_results
            )

            if has_medical_tube and not has_infection:
                final_results.append({
                    "대분류": "보건의료",
                    "중분류": "방문진료",
                    "서비스내용": "감염관리",
                    "선택이유": "의료처치(욕창, 루, 튜브관리 등)가 필요한 경우 감염관리도 함께 검토가 필요함"
                })

            filtered_results = final_results


            if selected_sido or selected_sigungu:
                region_df = df.copy()

                sido_col = find_col("시도", "시도명", "광역시도")
                sigungu_col = find_col("시군구")
                main_col = find_col("대분류")
                middle_col = find_col("중분류")

                if selected_sido:
                    if sido_col:
                        region_df = region_df[
                            region_df[sido_col].fillna("").astype(str).apply(normalize_sido) == selected_sido
                        ]
                    elif sigungu_col and selected_sido in SIGUNGU_MAP:
                        region_df = region_df[
                            region_df[sigungu_col].fillna("").astype(str).apply(normalize_sigungu).isin(SIGUNGU_MAP[selected_sido])
                        ]
                    else:
                        region_df = region_df.iloc[0:0]

                if selected_sigungu and sigungu_col:
                    region_df = region_df[
                        region_df[sigungu_col].fillna("").astype(str).apply(normalize_sigungu) == selected_sigungu
                    ]

                region_keys = set(
                    (region_df[main_col].fillna("").astype(str).str.strip() if main_col else pd.Series(dtype=str)) + "|" +
                    (region_df[middle_col].fillna("").astype(str).str.strip() if middle_col else pd.Series(dtype=str))
                )

                filtered_results = [
                    item for item in filtered_results
                    if (
                        str(item.get("대분류", "")).strip() + "|" +
                        str(item.get("중분류", "")).strip()
                    ) in region_keys
                ]
            print("검색어 =", repr(query))
            print("선택 지역(시도) =", repr(selected_sido))
            print("선택 지역(시군구) =", repr(selected_sigungu))
            print("지역필터 전 전체 추천 개수 =", len(final_results))

            service_results = filtered_results
            print("최종 service_results 개수 =", len(service_results))
            for r in service_results:
                print("→", r.get("대분류",""), "|", r.get("중분류",""), "|", r.get("서비스내용",""))


        except Exception as e:
            cond_display.append(f"GPT 오류: {e}")


        count = len(service_results)

        if count == 0:
            warning_msg = "검색 결과가 없습니다.\n어르신의 건강상태, 생활불편, 돌봄 필요 상황 등을 조금 더 구체적으로 입력해 주세요."

        elif count >= 15:
            warning_msg = "15개 이상의 서비스가 검색되었습니다.\n복합적인 서비스 연계가 필요한 대상일 수 있습니다."

        DESC_CACHE[cache_key] = {
            "results": service_results,
            "warning": warning_msg,
            "time": time.time()
        }

    sigungu_options = SIGUNGU_OPTIONS

    if selected_sido and selected_sido in SIGUNGU_MAP:
        sigungu_options = SIGUNGU_MAP[selected_sido]
    else:
        sigungu_options = []

    return render_template_string(
        DESC_HTML,
        style=BASE_STYLE,
        query=query,
        results=results,
        cond_display=cond_display,
        count=count,
        service_results=service_results,
        warning_msg=warning_msg,
        selected_sido=selected_sido,
        selected_sigungu=selected_sigungu,
        sigungu_options=sigungu_options
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

.item{
  display:flex;
  align-items:flex-start;
  gap:6px;
  padding:8px 0;
  cursor:pointer;
  line-height:1.6;
}

.item-bullet{
  flex:0 0 auto;
}

.item-text{
  flex:1;
  min-width:0;
  white-space:normal;
  word-break:keep-all;
  overflow-wrap:break-word;
}

.mobile-br{
  display:none;
}

@media (max-width:480px){
  .mobile-br{
    display:inline;
  }
}

*{
  box-sizing: border-box;
}

.loading-ci{
  width:132px;
  margin-top:22;
  opacity:0.82;
  display:block;
}

.top-bar{
  margin-bottom:35px;
}

.home-button,
.reset-button{
  display:inline-flex;
  align-items:center;
  justify-content:center;
  width:auto;
  height:34px;
  margin-top:0;
  padding:0 14px;
  border-radius:8px;
  background:#e5e7eb;
  color:#111827;
  text-decoration:none;
  font-size:14px;
  font-weight:500;
  border:none;
  cursor:pointer;
  transition:0.15s;
  flex:0 0 auto;
}

.desc-top-bar{
  display:flex;
  justify-content:space-between;
  align-items:center;
  gap:12px;
}

.reset-button:hover{
  background:#d1d5db;
}

@media (max-width:480px){
  .home-button,
  .reset-button{
    display:inline-flex;
    align-items:center;
    justify-content:center;
    width:auto;
    height:32px;
    margin-top:0;
    padding:0 12px;
    font-size:13px;
    line-height:1;
    flex:0 0 auto;
  }
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
  margin-bottom:0;
  padding-bottom:14px;
}

.title h2{
  margin:0;
  font-size:24px;
}

.title-row{
  display:flex;
  align-items:flex-start;
  justify-content:center;
  gap:8px;
}

.title-row h2{
  margin:0;
  line-height:1.2;
  white-space:nowrap;
  word-break:keep-all;
  flex:0 0 auto;
}

.tip-btn{
  display:inline-flex;
  align-items:center;
  justify-content:center;
  width:auto;
  min-width:52px;
  height:30px;
  padding:0 12px;
  margin-top:-1px;
  border:1px solid #dbeafe;
  border-radius:999px;
  background:linear-gradient(135deg,#eff6ff,#dbeafe);
  color:#2563eb;
  font-size:12px;
  font-weight:800;
  letter-spacing:0.3px;
  line-height:1;
  cursor:pointer;
  box-shadow:0 4px 12px rgba(37,99,235,0.14);
  flex:0 0 auto;
  white-space:nowrap;
}

.tip-btn:hover{
  transform:translateY(-1px);
  box-shadow:0 10px 22px rgba(37,99,235,0.34);
}

.tip-btn:active{
  transform:translateY(0);
}

.tip-modal{
  display:none;
  position:fixed;
  inset:0;
  background:rgba(15,23,42,0.48);
  z-index:9999;
  padding:20px;
  align-items:center;
  justify-content:center;
}

.tip-modal.show{
  display:flex;
}

.tip-modal-box{
  width:100%;
  max-width:620px;
  max-height:85vh;
  background:#ffffff;
  border-radius:22px;
  box-shadow:0 20px 50px rgba(15,23,42,0.22);
  overflow:hidden;
  display:flex;
  flex-direction:column;
  animation:tipFadeUp 0.18s ease;
}

.tip-modal-head{
  display:flex;
  align-items:center;
  justify-content:space-between;
  gap:12px;
  padding:18px 20px 14px 20px;
  border-bottom:1px solid #eef2f7;
  flex:0 0 auto;
}

.tip-modal-title{
  display:flex;
  align-items:center;
  gap:12px;
  font-size:17px;
  font-weight:800;
  color:#111827;
}

.tip-modal-title span{
  display:inline-block;
  line-height:1.2;
}

.tip-badge{
  display:inline-flex;
  align-items:center;
  justify-content:center;
  width:auto;
  min-width:52px;
  height:30px;
  padding:0 12px;
  border:1px solid #dbeafe;
  border-radius:999px;
  background:linear-gradient(135deg,#eff6ff,#dbeafe);
  color:#2563eb;
  font-size:12px;
  font-weight:800;
  letter-spacing:0.3px;
  line-height:1;
  box-shadow:0 4px 12px rgba(37,99,235,0.14);
  flex:0 0 auto;
  white-space:nowrap;
}

.tip-close{
  width:40px;
  height:40px;
  border:none;
  border-radius:999px;
  background:#f3f4f6;
  color:#64748b;
  font-size:24px;
  line-height:1;
  cursor:pointer;
  flex:0 0 auto;
}

.tip-modal-body{
  padding:18px 20px 18px 20px;
  overflow-y:auto;
  -webkit-overflow-scrolling:touch;
  flex:1 1 auto;
}

.tip-notice{
  margin:0 0 16px 0;
  padding:14px 16px;
  border-radius:14px;
  background:#f8fbff;
  border:1px solid #dbeafe;
  color:#1f2937;
  font-size:14px;
  line-height:1.75;
  word-break:keep-all;
}

.tip-notice p{
  margin:0;
  padding-left:1.1em;
  text-indent:-1.4em;
}

.tip-example-title{
  margin:0 0 10px 0;
  font-size:14px;
  font-weight:800;
  color:#2563eb;
}

.tip-example-box{
  background:#f9fafb;
  border:1px solid #e5e7eb;
  border-radius:16px;
  padding:16px;
}

.tip-example-text{
  font-size:14px;
  line-height:1.78;
  color:#374151;
  word-break:keep-all;
}

.tip-row{
  display:flex;
  align-items:flex-start;
  gap:8px;
  margin:0 0 8px 0;
}

.tip-num{
  width:22px;
  flex:0 0 22px;
  text-align:right;
  font-weight:700;
  color:#374151;
}

.tip-text{
  flex:1 1 auto;
  min-width:0;
}

.tip-heading{
  margin:10px 0 6px 0;
  font-weight:700;
  color:#374151;
}

.tip-bullet{
  display:flex;
  align-items:flex-start;
  gap:8px;
  margin:0 0 6px 18px;
}

.tip-dash{
  width:10px;
  flex:0 0 10px;
}

.tip-bullet-text{
  flex:1 1 auto;
  min-width:0;
}

.tip-subblock{
  margin:2px 0 6px 18px;
  font-weight:700;
  color:#4b5563;
}


.tip-modal-foot{
  padding:14px 20px 20px 20px;
  border-top:1px solid #eef2f7;
  background:#ffffff;
  flex:0 0 auto;
}

.tip-confirm{
  display:block;
  width:100%;
  height:46px;
  border:none;
  border-radius:12px;
  background:linear-gradient(135deg,#3b82f6,#2563eb);
  color:#ffffff;
  font-size:15px;
  font-weight:700;
  line-height:1;
  cursor:pointer;
}

@keyframes tipFadeUp{
  from{
    opacity:0;
    transform:translateY(14px);
  }
  to{
    opacity:1;
    transform:translateY(0);
  }
}

@media (max-width:480px){
  .title-row{
    gap:8px;
  }

  .title h2{
    font-size:21px;
  }

  .title-row h2{
    white-space:nowrap;
  }

.tip-btn{
  min-width:54px;
  height:30px;
  padding:0 12px;
  margin-top:-3px;
  font-size:11px;
  border:1px solid #dbeafe;
  box-shadow:0 4px 12px rgba(37,99,235,0.14);
}


  .tip-modal{
    padding:14px;
  }

  .tip-modal-box{
    max-height:88vh;
    border-radius:18px;
  }

  .tip-modal-head{
    padding:16px 16px 12px 16px;
  }

  .tip-modal-title{
    gap:10px;
    font-size:16px;
  }

  .tip-modal-body{
    padding:16px 16px 16px 16px;
  }

  .tip-modal-foot{
    padding:12px 16px 16px 16px;
  }

  .tip-notice{
    font-size:13px;
    line-height:1.72;
  }

  .tip-example-text{
    font-size:12.5px;
    line-height:1.72;
  }

  .tip-num{
    width:20px;
    flex:0 0 20px;
  }

.tip-bullet{
  margin:0 0 6px 18px;
}

.tip-subblock{
  margin:2px 0 6px 18px;
}

.tip-confirm{
  height:44px;
  font-size:14px;
}
}



/* 검색 카드 */
.search-box{
  background:white;
  padding:24px 18px;
  border-radius:20px;
  box-shadow:0 8px 24px rgba(0,0,0,0.08);
}

/* 텍스트 입력 */
#queryInput{
  width:100%;
  height:150px;
  padding:14px 58px 14px 14px;

  border-radius:12px;
  border:1px solid #cbd5e1;

  background:#ffffff;

  font-size:15px;
  line-height:1.7;

  box-shadow:none;
  resize:none;
}

#queryInput:focus{
  border-color:#2563eb;
  box-shadow:0 0 0 3px rgba(37,99,235,0.10);
}

#queryInput:hover{
  border-color:#94a3b8;
}

@media (max-width:768px){

  #queryInput{
    height:140px;
  }
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
  z-index:99999;
}

.loading-box{
  background:white;
  width:86%;
  max-width:320px;
  padding:34px 24px 26px 24px;
  border-radius:20px;
  text-align:center;

  display:flex;
  flex-direction:column;
  align-items:center;
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

@media (min-width:769px){
  #voiceBtn{
    display:none !important;
  }
}

.voice-inline{
  display:none;
  margin-top:14px;
  padding:16px 18px;
  border-radius:18px;
  background:#f8fbff;
  border:1px solid #dbeafe;
  box-shadow:0 10px 24px rgba(37,99,235,0.08);
  animation:voiceInlineShow 0.22s ease;
}

@keyframes voiceInlineShow{
  from{
    opacity:0;
    transform:translateY(6px);
  }
  to{
    opacity:1;
    transform:translateY(0);
  }
}

.voice-inline-box{
  display:flex;
  align-items:center;
  gap:14px;
}

.voice-wave-wrap{
  position:relative;
  width:92px;
  height:42px;
  flex:0 0 auto;
  display:flex;
  align-items:center;
  justify-content:center;
}

.voice-wave{
  height:34px;
  display:flex;
  align-items:flex-end;
  gap:4px;
}

.voice-bar{
  width:5px;
  border-radius:999px;
  background:linear-gradient(180deg,#93c5fd 0%, #60a5fa 50%, #2563eb 100%);
  animation:voiceWave 1s ease-in-out infinite;
  transform-origin:center bottom;
}

.voice-bar:nth-child(1){ height:12px; animation-delay:0s; }
.voice-bar:nth-child(2){ height:20px; animation-delay:0.12s; }
.voice-bar:nth-child(3){ height:30px; animation-delay:0.24s; }
.voice-bar:nth-child(4){ height:22px; animation-delay:0.36s; }
.voice-bar:nth-child(5){ height:14px; animation-delay:0.48s; }

@keyframes voiceWave{
  0%,100%{
    transform:scaleY(0.55);
    opacity:0.45;
  }
  50%{
    transform:scaleY(1.08);
    opacity:1;
  }
}

.voice-inline-text{
  min-width:0;
}

.voice-inline-title{
  font-size:14px;
  font-weight:700;
  color:#1e3a8a;
  margin-bottom:2px;
}

.voice-inline-subtitle{
  font-size:12px;
  color:#64748b;
  line-height:1.45;
}

@media (max-width:480px){
  .voice-inline{
    margin-top:12px;
    padding:14px 14px;
    border-radius:16px;
  }

  .voice-inline-box{
    gap:12px;
  }

  .voice-wave-wrap{
    width:80px;
    height:38px;
  }

  .voice-wave{
    height:30px;
    gap:3px;
  }

  .voice-bar{
    width:4px;
  }

  .voice-inline-title{
    font-size:13px;
  }

  .voice-inline-subtitle{
    font-size:11px;
  }
}

@media (min-width:769px){
  #queryInput::placeholder{
    white-space:nowrap;
    color:#6b7280;
    line-height:1.65;
  }
}

@media (max-width:768px){
  #queryInput::placeholder{
    white-space:pre-wrap;
    color:#6b7280;
    line-height:1.7;
  }
}

.ai-model-wrap{
  margin-top:8px;
  margin-bottom:28px;
  width:100%;
  display:flex;
  justify-content:center;
}

.ai-model-badge{
  display:flex;
  align-items:center;
  justify-content:center;
  padding:0;
  margin:0 auto;
  background:transparent;
  border:none;
  box-shadow:none;
}

.ai-model-top{
  display:flex;
  align-items:center;
  justify-content:center;
  gap:5px;
  margin:0 auto;
  font-size:9px;
  font-weight:400;
  color:#94a3b8;
  line-height:1;
  text-align:center;
}

.ai-model-icon{
  width:4px;
  height:4px;
  border-radius:50%;
  background:#94a3b8;
  box-shadow:none;
  flex:0 0 auto;
}

.ai-engine-text{
  font-size:10px !important;
  font-weight:400 !important;
  color:#94a3b8 !important;
  letter-spacing:0;
  line-height:1;
  text-align:center;
}

.ai-logo{
  width:13px;
  height:13px;
  object-fit:contain;
}

.ai-model-top{
  gap:3px;
}

/* ===== 사례기반 지역선택 박스 ===== */

.desc-warning{
  margin:0 0 16px 0;
  padding:14px 16px;
  border-radius:12px;
  background:#fff7ed;
  border:1px solid #fdba74;
  color:#9a3412;
  font-size:14px;
  line-height:1.65;
  display:flex;
  align-items:flex-start;
  gap:8px;
}

.desc-warning-icon{
  flex:0 0 auto;
  font-size:15px;
  line-height:1.4;
  margin-top:1px;
}

.desc-warning-text{
  flex:1;
  white-space:pre-line;
  word-break:keep-all;
}

@media (max-width:480px){
  .desc-warning{
    margin:0 0 14px 0;
    padding:13px 14px;
    font-size:13px;
    line-height:1.6;
  }

  .desc-warning-icon{
    font-size:14px;
    margin-top:1px;
  }
}

.desc-warning{
  margin:12px 0 0 0;
  padding:14px 16px;
  border-radius:12px;
  background:#fff7ed;
  border:1px solid #fdba74;
  color:#9a3412;
  font-size:14px;
  line-height:1.65;
  display:flex;
  align-items:flex-start;
  gap:8px;
}

.desc-warning-icon{
  flex:0 0 auto;
  font-size:15px;
  line-height:1.4;
  margin-top:1px;
}

.desc-warning-text{
  flex:1;
  white-space:pre-line;
  word-break:keep-all;
}

@media (max-width:480px){
  .desc-warning{
    margin:12px 0 0 0;
    padding:13px 14px;
    font-size:13px;
    line-height:1.6;
  }

  .desc-warning-icon{
    font-size:14px;
    margin-top:1px;
  }
}

.desc-region-box{
  margin-bottom:18px;
  padding:14px 14px 12px 14px;
  border-radius:16px;
  background:#eef4ff;
  border:1px solid #c7d7ff;
}

.desc-region-title{
  font-size:16px;
  font-weight:800;
  color:#111827;
  margin-bottom:10px;
}

.desc-region-row{
  display:grid;
  grid-template-columns:1fr 1fr;
  gap:10px;
}

.desc-region-item{
  display:flex;
  flex-direction:column;
}

.desc-region-item label{
  margin:0 0 6px 0;
  font-size:13px;
  font-weight:700;
  color:#374151;
  line-height:1.2;
}

.desc-region-item select{
  width:100%;
  height:40px;
  margin:0;
  padding:0 10px;
  border-radius:10px;
  border:1px solid #cbd5e1;
  font-size:14px;
  background:#ffffff;
  box-sizing:border-box;
}

@media (max-width:480px){
  .desc-region-box{
    padding:14px 12px 12px 12px;
    border-radius:16px;
  }

  .desc-region-row{
    grid-template-columns:1fr 1fr;
    gap:8px;
    align-items:start;
  }

  .desc-region-title{
    margin-bottom:10px;
    font-size:15px;
  }

  .desc-region-item label{
    margin:0 0 5px 0;
    font-size:12px;
    line-height:1.2;
  }

  .desc-region-item select{
    width:100%;
    height:40px;
    margin:0;
    padding:0 10px;
    font-size:13px;
  }
}



</style>
</head>

<body>

<div class="container">

<div class="top-bar desc-top-bar">
  <a href="/home" class="home-button">홈으로</a>
  <button type="button" class="reset-button" onclick="resetDescPage()">초기화</button>
</div>

<div class="title">
  <div class="title-row">
    <h2>사례기반 서비스내용 검색</h2>
    <button type="button" class="tip-btn" onclick="openTipModal()" aria-label="입력 팁 보기">TIP</button>
  </div>
</div>

<div class="search-box">

<form method="post" id="searchForm">
<input type="hidden" name="action" id="descAction" value="">

<div class="desc-region-box">

  <div class="desc-region-title">지역 설정</div>
  
  <div class="desc-region-row">

    <div class="desc-region-item">
      <label>시도</label>
      <select name="sido" onchange="handleDescSidoChange(this.form)">
        <option value="">전체</option>
        <option value="광주광역시" {% if selected_sido=="광주광역시" %}selected{% endif %}>광주광역시</option>
        <option value="전라남도" {% if selected_sido=="전라남도" %}selected{% endif %}>전라남도</option>
        <option value="전북특별자치도" {% if selected_sido=="전북특별자치도" %}selected{% endif %}>전북특별자치도</option>
        <option value="제주특별자치도" {% if selected_sido=="제주특별자치도" %}selected{% endif %}>제주특별자치도</option>
      </select>
    </div>

    <div class="desc-region-item">
      <label>시군구</label>
      <select name="sigungu">
        <option value="">전체</option>
        {% for g in sigungu_options %}
        <option value="{{g}}" {% if g==selected_sigungu %}selected{% endif %}>{{g}}</option>
        {% endfor %}
      </select>
    </div>

  </div>

</div>

<div style="position:relative;">

<textarea id="queryInput" name="query" placeholder="예) 식사도움이 필요한&#10;    어르신에게 맞는 서비스">{{query}}</textarea>


<button type="button" id="voiceBtn" onclick="startVoiceInput(event)"
style="
position:absolute;
right:12px;
top:12px;
width:42px;
height:42px;
display:flex;
align-items:center;
justify-content:center;
border-radius:50%;
border:none;
background:rgba(37,99,235,0.92);
backdrop-filter:blur(6px);
box-shadow:0 4px 12px rgba(0,0,0,0.15);
cursor:pointer;
z-index:10;
transition:0.2s;
">

<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" fill="white" viewBox="0 0 24 24">
  <path d="M12 14a3 3 0 0 0 3-3V5a3 3 0 1 0-6 0v6a3 3 0 0 0 3 3zm5-3a1 1 0 0 0-2 0 3 3 0 0 1-6 0 1 1 0 0 0-2 0 5 5 0 0 0 4 4.9V19H8a1 1 0 0 0 0 2h8a1 1 0 0 0 0-2h-3v-3.1A5 5 0 0 0 17 11z"/>
</svg>

</button>

</div>

<div class="voice-inline" id="voiceOverlay">
  <div class="voice-inline-box">
    <div class="voice-wave-wrap">
      <div class="voice-wave">
        <span class="voice-bar"></span>
        <span class="voice-bar"></span>
        <span class="voice-bar"></span>
        <span class="voice-bar"></span>
        <span class="voice-bar"></span>
      </div>
    </div>

    <div class="voice-inline-text">
      <div class="voice-inline-title">음성 듣는 중</div>
      <div class="voice-inline-subtitle">말씀하시면 자동으로 입력됩니다.</div>
    </div>
  </div>
</div>

<button type="submit" id="descSubmitBtn" onclick="setDescSearchAction()">AI 검색</button>

{% if warning_msg %}
<div class="desc-warning">
  <span class="desc-warning-icon">⚠️</span>
  <div class="desc-warning-text">{{warning_msg}}</div>
</div>
{% endif %}

</form>
</div>

<div class="notice">

※ 입력한 사례와 유사한 <b>통합돌봄 서비스를<span class="mobile-br"><br></span>
최대 30가지</b> 추천합니다.<br>
지자체 개인별지원계획 수립 참고용입니다.
</div>


<div id="searchResultSection">

{% if service_results %}

<div class="result" id="resultArea">

<h3>{{count}}건의 추천 서비스</h3>



{% for r in service_results %}

<div class="result-card">

  <div style="display:flex; justify-content:space-between; align-items:flex-start; gap:12px; margin-bottom:10px;">

    <div style="font-weight:700; font-size:16px; line-height:1.5; flex:1;">
      {{loop.index}}. {{r["대분류"]}} > {{r["중분류"]}} > {{r["서비스내용"]}}
    </div>

    <a
      href="/combo?sido={{selected_sido|urlencode}}&sigungu={{selected_sigungu|urlencode}}&main_category={{r['대분류']|urlencode}}&middle_category={{r['중분류']|urlencode}}&from_desc=1"
     style="
        display:inline-block;
        padding:9px 13px;
        border-radius:10px;
        background:#eff6ff;
        border:1px solid #bfdbfe;
        color:#1d4ed8;
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

<p style="margin:14px 0 0 0;font-weight:700;font-size:15px;line-height:1.35;text-align:center;">
  AI가 사례를 분석 중입니다
</p>

<div class="ai-model-wrap">
  <div class="ai-model-badge">
    <div class="ai-model-top">
      <img src="/static/gpt.png" class="ai-logo">
      <span class="ai-engine-text">검색엔진: GPT-4.1</span>
    </div>
  </div>
</div>

<img src="/static/ci.png" class="loading-ci">
  </div>

</div>

<script>
const searchForm = document.getElementById("searchForm");
const loading = document.getElementById("loading");
const queryInput = document.getElementById("queryInput");
const voiceBtn = document.getElementById("voiceBtn");
const descSubmitBtn = document.getElementById("descSubmitBtn");

const originalIcon = voiceBtn ? voiceBtn.innerHTML : "";
let recognition = null;
let isRecording = false;

function handleDescSidoChange(form){
  document.getElementById("descAction").value = "change_sido";
  form.submit();
}

window.addEventListener("load", function(){
  const resultBox = document.getElementById("resultArea");
  const warningBox = document.querySelector("#searchResultSection .warning-box");

  if (resultBox) {
    setTimeout(function(){
      resultBox.scrollIntoView({
        behavior: "smooth",
        block: "start"
      });
    }, 250);
    return;
  }

  if (warningBox) {
    setTimeout(function(){
      warningBox.scrollIntoView({
        behavior: "smooth",
        block: "start"
      });
    }, 250);
  }
});


function setDescSearchAction(){
  document.getElementById("descAction").value = "search";
}


function playBeep(type="start"){
  try{
    const AudioContextClass = window.AudioContext || window.webkitAudioContext;
    if(!AudioContextClass) return;

    const ctx = new AudioContextClass();
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();

    osc.type = "sine";
    osc.frequency.value = (type === "start") ? 880 : 660;

    gain.gain.setValueAtTime(0.001, ctx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.7, ctx.currentTime + 0.01);
    gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.18);

    osc.connect(gain);
    gain.connect(ctx.destination);

    osc.start();
    osc.stop(ctx.currentTime + 0.18);
  }catch(e){
    console.log("beep error:", e);
  }
}

function setVoiceButtonRecording(active){
  if(!voiceBtn) return;

  if(active){
    voiceBtn.style.background = "rgba(220,38,38,0.92)";
    voiceBtn.style.transform = "scale(0.96)";
    voiceBtn.innerHTML = "■";
  }else{
    voiceBtn.style.background = "rgba(37,99,235,0.92)";
    voiceBtn.style.transform = "scale(1)";
    voiceBtn.innerHTML = originalIcon;
  }
}

function startVoiceInput(event){
  if(event) event.preventDefault();

  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;

  if(!SpeechRecognition){
    alert("이 브라우저는 음성인식을 지원하지 않습니다.");
    return;
  }

  if(isRecording && recognition){
    recognition.stop();
    return;
  }

  recognition = new SpeechRecognition();
  recognition.lang = "ko-KR";

recognition.onstart = function(){
  isRecording = true;
  setVoiceButtonRecording(true);
  playBeep("start");

  const overlay = document.getElementById("voiceOverlay");
  if(overlay){
    overlay.style.display = "block";
  }
};

recognition.onresult = function(e){
  const transcript = e.results[0][0].transcript;
  queryInput.value = transcript;

  const overlay = document.getElementById("voiceOverlay");
  if(overlay){
    overlay.style.display = "none";
  }
};

recognition.onend = function(){
  isRecording = false;
  setVoiceButtonRecording(false);
  playBeep("end");

  const overlay = document.getElementById("voiceOverlay");
  if(overlay){
    overlay.style.display = "none";
  }
};


  recognition.start();
}

if(searchForm){
  searchForm.addEventListener("submit", function(){
    if(descSubmitBtn){
      descSubmitBtn.disabled = true;
      descSubmitBtn.innerText = "검색 중...";
      descSubmitBtn.style.opacity = "0.7";
      descSubmitBtn.style.cursor = "not-allowed";
    }

    if(loading){
      loading.style.display = "flex";
    }
  });
}

function resetDescPage(){
  window.location.href = "/desc";
}

window.addEventListener("load", function(){
  const hasResults =
    {{ 'true' if service_results else 'false' }} ||
    {{ 'true' if warning_msg else 'false' }};

  if (hasResults) {
    history.replaceState({ page: "desc-root" }, "", "/desc");
    history.pushState({ page: "desc-result" }, "", "/desc");
  }
});

window.addEventListener("popstate", function(e){
  if (e.state && e.state.page === "desc-root") {
    window.location.replace("/desc");
  }
});

function openTipModal(){
  document.getElementById("tipModal").classList.add("show");
  document.body.style.overflow = "hidden";
}

function closeTipModal(){
  document.getElementById("tipModal").classList.remove("show");
  document.body.style.overflow = "";
}

function handleTipBackdrop(event){
  if(event.target.id === "tipModal"){
    closeTipModal();
  }
}

</script>

<div id="tipModal" class="tip-modal" onclick="handleTipBackdrop(event)">
  <div class="tip-modal-box">
    <div class="tip-modal-head">
      <div class="tip-modal-title">
        <div class="tip-badge">TIP</div>
        <span>입력 팁</span>
      </div>
      <button type="button" class="tip-close" onclick="closeTipModal()">✕</button>
    </div>

<div class="tip-modal-body">
  <div class="tip-notice">
    <p>※ 통합판정조사, 지자체 조사의 
<b class="highlight">참고사항 전문</b>을 모두 입력해도 
<b class="highlight">AI가 추천서비스를 안내</b>합니다.</p>
  </div>

  <div class="tip-example-title">입력 예시)</div>

  <div class="tip-example-box">
    <div class="tip-example-text">

      <div class="tip-row">
        <div class="tip-num">1.</div>
        <div class="tip-text">병력: 약 10년 전 뇌졸중으로 쓰러진 뒤 좌측 편마비 있음.</div>
      </div>

      <div class="tip-row">
        <div class="tip-num">2.</div>
        <div class="tip-text">복용약물: 고혈압, 당뇨, 요통, 골다공증으로 관련약 및 진통제 복약 중</div>
      </div>

      <div class="tip-row">
        <div class="tip-num">3.</div>
        <div class="tip-text">인지저하 기능: 의사소통 가능하나 단기기억능력은 다소 저하되어 있음.</div>
      </div>

      <div class="tip-row">
        <div class="tip-num">4.</div>
        <div class="tip-text">신체 저하기능</div>
      </div>

      <div class="tip-bullet">
        <div class="tip-dash">-</div>
        <div class="tip-bullet-text">주1회 소변실수 있으며 편마비로 천천히 난간 등을 잡고 걸어야해서 가끔 화장실 가다 참지못하고 소변을 보기도 함.</div>
      </div>

      <div class="tip-bullet">
        <div class="tip-dash">-</div>
        <div class="tip-bullet-text">편마비가 있으나 간단한 일상생활정도는 스스로 천천히 하면 수행가능함. 다만 옷은 혼자갈아입지 못해 도움이 필요함.</div>
      </div>

      <div class="tip-row">
        <div class="tip-num">5.</div>
        <div class="tip-text">행동심리증상: 없음</div>
      </div>

      <div class="tip-row">
        <div class="tip-num">6.</div>
        <div class="tip-text">수발부담행동심리 증상: 없음</div>
      </div>

      <div class="tip-row">
        <div class="tip-num">7.</div>
        <div class="tip-text">간호 주요처치 및 증상: 최근 편마비로 인한 거동불편으로 낙상 후 좌측 발등이 벗겨져 상처 소독을 하고 있음.</div>
      </div>

      <div class="tip-row">
        <div class="tip-num">8.</div>
        <div class="tip-text">도움이 필요한 수단적 일상생활 기능: 이동도움, 반찬 도움</div>
      </div>

      <div class="tip-row">
        <div class="tip-num">9.</div>
        <div class="tip-text">구강 건강문제: 없음</div>
      </div>

      <div class="tip-row">
        <div class="tip-num">10.</div>
        <div class="tip-text">영양 관련문제: 평소 시장에서 장을봐서 혼자 밥을 해먹고 있지만 컨디션이 좋지 않거나 귀찮으면 끼니를 거르기도 하며 과일, 채소 등 불충분한 섭취가 이루어지고 있음.</div>
      </div>

      <div class="tip-row">
        <div class="tip-num">11.</div>
        <div class="tip-text">사회문화적 관계: 배우자가 2년전 사망하였으며 슬하에 2남 1녀 있으나 다들 타지에 살고 소원한 관계라고 함.</div>
      </div>

      <div class="tip-row">
        <div class="tip-num">12.</div>
        <div class="tip-text">정신건강문제: 없음</div>
      </div>

      <div class="tip-row">
        <div class="tip-num">13.</div>
        <div class="tip-text">주거환경</div>
      </div>

      <div class="tip-bullet">
        <div class="tip-dash">-</div>
        <div class="tip-bullet-text">편마비로 거동이 불편함에도 꼼꼼한 성격 탓에 집안 위생상태는 청결한편</div>
      </div>

      <div class="tip-bullet">
        <div class="tip-dash">-</div>
        <div class="tip-bullet-text">오래된 다가구 주택에 살고 있어 벽지가 벗겨지거나 곰팡이가 피어있는 등 노후로 인한 주거 환경 개선은 필요함.</div>
      </div>

      <div class="tip-bullet">
        <div class="tip-dash">-</div>
        <div class="tip-bullet-text">최근 낙상하는 횟수가 늘어 집안에 의자나 테이블 같은 잡기 쉬운 물건 들을 중간 중간 두고 생활함.</div>
      </div>

      <div class="tip-row">
        <div class="tip-num">14.</div>
        <div class="tip-text">안정성 평가:</div>
      </div>

      <div class="tip-bullet">
        <div class="tip-dash">-</div>
        <div class="tip-bullet-text">문틀이 있고 장판이 오래되어 바닥이 굴곡진 부분 등이 있어 낙상의 위험이 있음.</div>
      </div>

      <div class="tip-row">
        <div class="tip-num">15.</div>
        <div class="tip-text">서비스 이용과 희망</div>
      </div>

      <div class="tip-subblock">(이용 서비스)</div>

      <div class="tip-bullet">
        <div class="tip-dash">-</div>
        <div class="tip-bullet-text">최근 주민센터를 통해 도시락 지원서비스를 받았으나 좀 더 횟수가 늘길 희망함.</div>
      </div>

      <div class="tip-bullet">
        <div class="tip-dash">-</div>
        <div class="tip-bullet-text">장기요양 4등급으로 방문요양 이용하고 있음.</div>
      </div>

      <div class="tip-subblock">(희망 서비스)</div>

      <div class="tip-bullet">
        <div class="tip-dash">-</div>
        <div class="tip-bullet-text">벽지 교체 등 주택개선 사업에 참여하길 희망함.</div>
      </div>

      <div class="tip-bullet">
        <div class="tip-dash">-</div>
        <div class="tip-bullet-text">반찬지원 횟수가 늘기를 희망하며 거동이 불편해 택시 등 이동 서비스 이용 희망함.</div>
      </div>

      <div class="tip-row">
        <div class="tip-num">16.</div>
        <div class="tip-text">가족지지 정도: 슬하에 2남 1녀 있으며 자주 왕래하지는 않음.</div>
      </div>

      <div class="tip-row">
        <div class="tip-num">17.</div>
        <div class="tip-text">기타사항</div>
      </div>

      <div class="tip-bullet">
        <div class="tip-dash">-</div>
        <div class="tip-bullet-text">편마비로 거동이 불편하나 천천히 수행하면 대부분 일상생활은 수행하기도 함.</div>
      </div>

    </div>
  </div>

  <div class="tip-modal-foot">
    <button type="button" class="tip-confirm" onclick="closeTipModal()">확인</button>
  </div>
</div>
</div>

</body>
</html>
"""

def normalize_query_text(text: str) -> str:
    text = str(text or "")
    text = text.strip().lower()
    text = re.sub(r"\s+", "", text)
    return text


SYNONYM_GROUPS = {
    "pain_back": {
        "keywords": [
            "요통", "허리통증", "허리아픔", "허리아프", "허리불편",
            "허리쑤심", "허리가아픔", "허리가자주아픔"
        ],
        "aliases": [
            "허리통증", "허리아픔", "근골격통증", "통증",
            "재활", "기능회복", "방문보건"
        ]
    },

    "pain_knee": {
        "keywords": [
            "무릎통증", "무릎아픔", "무릎이아픔", "관절통증", "관절아픔"
        ],
        "aliases": [
            "무릎통증", "관절통증", "통증",
            "재활", "기능회복", "방문보건"
        ]
    },

    "pain_shoulder_arm": {
        "keywords": [
            "어깨통증", "어깨아픔", "팔통증", "팔아픔", "손목통증",
            "손목아픔", "팔저림", "손저림"
        ],
        "aliases": [
            "상지통증", "근골격통증", "감각이상",
            "재활", "기능회복", "방문보건"
        ]
    },

    "neuro_numbness": {
        "keywords": [
            "저리", "저림", "저린", "찌릿", "찌릿함", "화끈거림",
            "감각이상", "감각저하", "감각둔함", "감각무딤",
            "다리저림", "다리가저림", "다리가저린", "종아리저림",
            "발저림", "발바닥저림", "허벅지저림", "엉덩이저림",
            "손저림", "손발저림"
        ],
        "aliases": [
            "저림", "감각이상", "신경증상", "말초신경", "통증",
            "이동불편", "보행불편", "재활", "기능회복", "방문보건"
        ]
    },

    "mobility": {
        "keywords": [
            "거동불편", "보행불편", "걷기힘듦", "걷기힘들",
            "움직이기힘듦", "움직이기힘들", "이동불편",
            "다리가불편", "허리가불편", "무릎이불편",
            "일어나기힘들", "앉았다일어나기힘들", "계단오르기힘들"
        ],
        "aliases": [
            "이동지원", "보행지원", "재활", "기능회복", "복지용구"
        ]
    },

    "fall_safety": {
        "keywords": [
            "낙상", "넘어짐", "자주넘어짐", "비틀거림", "휘청거림",
            "균형이안맞", "균형불안", "넘어질까걱정", "낙상걱정"
        ],
        "aliases": [
            "낙상예방", "안전지원", "보행보조", "복지용구",
            "방문보건", "이동지원"
        ]
    },

    "meal_support": {
        "keywords": [
            "도시락", "도시락필요", "식사배달", "밥배달", "배달식",
            "식사도움", "식사지원", "반찬", "반찬지원", "끼니",
            "식사를못함", "밥을못함", "차려먹기힘들", "챙겨먹기힘들"
        ],
        "aliases": [
            "식사지원", "반찬지원", "영양지원", "도시락",
            "식사배달", "방문형지원"
        ]
    },

    "nutrition_loss": {
        "keywords": [
            "배고프", "배가고프", "허기", "허기짐", "굶", "굶고",
            "못먹", "못먹음", "입맛없", "식욕없", "식욕부진",
            "영양부족", "영양불량", "체중감소", "기운없음"
        ],
        "aliases": [
            "영양지원", "식사지원", "반찬지원", "방문형지원", "건강관리"
        ]
    },

    "emotional_support": {
        "keywords": [
            "외로움", "외롭", "고립", "말벗", "우울", "혼자지냄",
            "혼자있음", "고독", "불안", "적적함", "심심함"
        ],
        "aliases": [
            "정서지원", "안부확인", "말벗", "돌봄연계", "사회적고립"
        ]
    },

    "social_relation": {
        "keywords": [
            "잘어울리지못", "어울리지못", "대인관계", "관계어려움",
            "사람만나기싫", "사회활동어려움", "밖에안나감", "외출안함"
        ],
        "aliases": [
            "정서지원", "사회참여지원", "안부확인", "돌봄연계"
        ]
    },

    "hygiene": {
        "keywords": [
            "목욕힘듦", "목욕힘들", "씻기힘듦", "씻기힘들",
            "청소힘듦", "청소힘들", "세탁힘듦", "세탁힘들",
            "위생관리어려움"
        ],
        "aliases": [
            "위생지원", "목욕지원", "청소지원", "세탁지원", "생활지원"
        ]
    },

    "urinary_incontinence": {
        "keywords": [
            "요실금", "실금", "소변실수", "배뇨실수", "오줌실수",
            "오줌지림", "오줌을지림", "오줌을지린", "소변지림",
            "소변을지림", "소변을지린", "지린다", "지림",
            "쉬를지림", "쉬실수", "소변이샘", "소변이새",
            "오줌이샘", "오줌이새"
        ],
        "aliases": [
            "요실금", "배뇨장애", "배뇨관리", "위생지원",
            "기저귀", "패드", "복지용구", "방문보건"
        ]
    },

    "urinary_difficulty": {
        "keywords": [
            "소변보기힘듦", "소변보기힘들", "배뇨곤란", "오줌이안나옴",
            "잔뇨감", "소변불편", "화장실을자주감", "빈뇨", "야간뇨"
        ],
        "aliases": [
            "배뇨관리", "방문보건", "건강관리", "위생지원"
        ]
    },

    "bowel_difficulty": {
        "keywords": [
            "변실수", "대변실수", "변을지림", "변지림", "변비",
            "설사", "배변힘듦", "배변불편", "화장실실수"
        ],
        "aliases": [
            "배변관리", "위생지원", "복지용구", "방문보건"
        ]
    },

    "tube_care": {
        "keywords": [
            "콧줄", "비위관", "위관", "경관급식", "콧줄영양",
            "비위관영양", "소변줄", "유치도뇨", "도뇨줄",
            "장루", "요루", "기관절개", "석션", "흡인", "튜브"
        ],
        "aliases": [
            "튜브관리", "의료처치", "감염관리", "방문진료", "방문보건"
        ]
    },

    "wound_infection": {
        "keywords": [
            "상처", "상처소독", "드레싱", "욕창", "염증", "감염",
            "고름", "진물", "봉합", "절개", "찰과상", "화상"
        ],
        "aliases": [
            "감염관리", "상처관리", "드레싱", "의료처치", "방문진료"
        ]
    },

    "cognitive_dementia": {
        "keywords": [
            "치매", "깜빡", "기억못", "기억력저하", "인지저하",
            "헷갈려", "길을잃", "약을까먹", "약을잊"
        ],
        "aliases": [
            "인지지원", "복약관리", "안부확인", "돌봄연계", "방문보건"
        ]
    },

    "medication_hospital": {
        "keywords": [
            "약챙기기힘들", "복약어려움", "병원가기힘들", "병원동행",
            "통원어려움", "진료받기힘들"
        ],
        "aliases": [
            "복약관리", "병원동행", "이동지원", "방문보건", "건강관리"
        ]
    },

    "welfare_aid": {
        "keywords": [
            "지팡이", "워커", "보행기", "보행차", "휠체어",
            "도구", "보조도구", "보조기구", "도구필요", "보조필요",
            "안전손잡이", "손잡이", "욕실손잡이", "화장실손잡이",
            "미끄럼방지", "미끄럼방지매트", "욕실매트", "논슬립",
            "목욕의자", "샤워의자", "이동변기", "간이변기",
            "기저귀", "패드", "전동침대", "병원침대",
            "욕창매트", "욕창방지", "자세변환", "체위변경",
            "경사로", "문턱", "턱"
        ],
        "aliases": [
            "복지용구", "구입", "대여", "안전지원", "이동보조"
        ]
    }
}


def expand_query_aliases(query: str):
    q_norm = normalize_query_text(query)
    aliases = []

    for group in SYNONYM_GROUPS.values():
        if any(keyword in q_norm for keyword in group["keywords"]):
            aliases.extend(group["aliases"])

    if "아프" in q_norm or "통증" in q_norm or "쑤시" in q_norm or "결리" in q_norm:
        aliases.extend(["통증", "방문보건", "재활", "기능회복"])

    if "저리" in q_norm or "저림" in q_norm or "찌릿" in q_norm:
        aliases.extend(["저림", "감각이상", "신경증상", "방문보건", "재활", "기능회복", "이동불편"])

    if "다리" in q_norm and ("저리" in q_norm or "저림" in q_norm):
        aliases.extend(["다리저림", "보행불편", "이동지원", "재활", "기능회복"])

    if "손" in q_norm and ("저리" in q_norm or "저림" in q_norm):
        aliases.extend(["손저림", "감각이상", "신경증상", "방문보건"])

    if (
        "지리" in q_norm or "지림" in q_norm or "실금" in q_norm
        or "소변실수" in q_norm or "오줌실수" in q_norm
        or "오줌" in q_norm or "소변" in q_norm or "배뇨" in q_norm
    ):
        aliases.extend([
            "요실금", "배뇨장애", "배뇨관리", "위생지원",
            "기저귀", "패드", "복지용구", "방문보건"
        ])

    if "변" in q_norm and ("실수" in q_norm or "지리" in q_norm or "지림" in q_norm):
        aliases.extend(["배변관리", "위생지원", "복지용구", "방문보건"])

    if "혼자" in q_norm or "외롭" in q_norm or "고립" in q_norm or "말벗" in q_norm:
        aliases.extend(["정서지원", "안부확인", "돌봄연계"])

    if "밥" in q_norm or "식사" in q_norm or "반찬" in q_norm or "도시락" in q_norm:
        aliases.extend(["식사지원", "반찬지원", "영양지원"])

    if "낙상" in q_norm or "넘어" in q_norm or "휘청" in q_norm:
        aliases.extend(["낙상예방", "안전지원", "이동지원", "복지용구"])

    if "약" in q_norm or "병원" in q_norm or "복약" in q_norm:
        aliases.extend(["복약관리", "병원동행", "방문보건", "건강관리"])

    if "배고프" in q_norm or "배고파" in q_norm or "허기" in q_norm or "허기지" in q_norm or "굶" in q_norm or "못먹" in q_norm or "식욕없" in q_norm:
        aliases.extend([
            "영양지원", "식사지원", "반찬지원",
            "도시락", "식사배달", "방문형지원", "건강관리"
        ])

    if "도구" in q_norm or "보조도구" in q_norm or "보조기구" in q_norm:
        aliases.extend([
            "복지용구", "보행보조", "지팡이", "워커",
            "보행기", "휠체어", "안전손잡이",
            "이동지원", "낙상예방"
        ])

    return list(dict.fromkeys(aliases))


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

def is_irrelevant_query(query: str) -> bool:
    q = str(query or "").strip()
    q_norm = q.replace(" ", "").lower()

    if not q_norm:
        return True

    # 너무 짧은 입력
    if len(q_norm) <= 1:
        return True

    # 완전히 무관한 짧은 입력들
    short_block_words = [
        "트럼프", "윤석열", "이재명", "정치", "대통령",
        "주식", "코인", "비트코인", "나스닥", "s&p",
        "축구", "야구", "농구", "연예인", "아이돌",
        "영화", "드라마", "날씨", "로또", "게임"
    ]

    if q_norm in short_block_words:
        return True

    # 케어네비 관련 기본 키워드
    care_keywords = [
        "어르신", "노인", "고령", "돌봄", "통합돌봄", "복지", "복지용구",
        "장기요양", "요양", "건강", "질환", "통증", "병원", "의료", "간호",
        "간병", "치매", "약", "복약", "식사", "영양", "반찬", "목욕", "위생",
        "청소", "세탁", "이동", "거동", "보행", "낙상", "배뇨", "배변",
        "욕창", "상처", "감염", "튜브", "비위관", "콧줄", "도뇨", "소변줄",
        "외로움", "고립", "말벗", "독거", "보호자", "가족", "주거", "안전",
        "방문", "재활", "장애", "지원", "서비스"
    ]

    # 의미상 돌봄/생활불편/정서지원으로 볼 수 있는 표현
    meaning_keywords = [
        "잘어울리지못", "어울리지못", "대인관계", "관계어려움",
        "혼자지냄", "혼자있음", "혼자생활", "외출안", "밖에안나감",
        "고립", "고독", "우울", "불안", "외롭", "말상대", "말벗",
        "도구필요", "보조도구", "보조기구", "지팡이필요",
        "보행기필요", "휠체어필요",

        "밥못", "식사못", "반찬못", "끼니", "먹기힘들", "챙겨먹기힘들",
        "배고프", "배고파", "배가고프", "배가고파", "허기", "허기짐", "허기지", "굶", "굶고", "못먹", "못먹음",
        "입맛없", "식욕없", "식욕부진", "영양부족", "영양불량",
        "도시락", "도시락필요", "식사배달", "밥배달", "배달식", "배달도시락",
        "반찬지원", "식사지원", "영양지원",

        "씻기힘들", "목욕힘들", "청소힘들", "세탁힘들",
        "걷기힘들", "움직이기힘들", "거동불편", "보행불편",
        "이동불편", "허리불편", "무릎불편",
        "넘어질까", "낙상걱정", "화장실힘들", "배변힘들", "배뇨힘들",
        "병원가기힘들", "병원동행", "약챙기기힘들",

        "아프", "통증", "쑤시", "결리", "저리", "불편", "불편함",
        "허리아프", "무릎아프", "어깨아프", "다리아프", "손목아프",
        "허리통증", "무릎통증", "어깨통증", "다리통증", "관절통증",
        "요통", "허리아픔", "허리가아픔", "허리가자주아픔", "허리쑤심",

        "다리저림", "다리가저림", "발저림", "손저림", "손발저림",
        "찌릿", "감각이상", "감각저하",

        "요실금", "실금", "소변실수", "배뇨실수", "오줌실수",
        "오줌지림", "소변지림", "지린다", "지림", "쉬를지림",
        "소변이샘", "소변이새", "오줌이샘", "오줌이새",

        "변실수", "대변실수", "변지림", "변을지림", "배변불편",

        "낙상", "넘어짐", "자주넘어짐", "휘청거림", "비틀거림",
        "균형불안", "낙상걱정",

        "깜빡", "기억못", "기억력저하", "인지저하", "헷갈림",

        "약챙기기힘들", "복약어려움", "병원가기힘들", "병원동행",
        "통원어려움",

        "차려먹기힘들", "챙겨먹기힘들", "체중감소", "기운없음",

        "소변줄", "콧줄", "비위관", "도뇨줄", "장루", "요루",
    ]


    # 질병/치료/후유증 문맥 표현
    disease_context_keywords = [
        "진단", "진단받", "앓고", "앓음", "병력", "후유증",
        "수술후", "수술 후", "입원후", "입원 후",
        "치료중", "치료 중", "재활필요", "재활 필요",
        "투석", "마비", "편마비", "통원", "복약",
        "약복용", "약 복용", "지병", "기저질환", "후유장애",
        "있다고함", "있다고 함", "라고함", "라고 함"
    ]

    # 자주 나오는 대표 질환명만 최소한으로
    disease_keywords = [
        "뇌출혈", "뇌경색", "중풍", "치매", "파킨슨",
        "당뇨", "고혈압", "암", "골절", "관절염",
        "심부전", "심근경색", "폐렴", "신부전", "투석",
        "편마비", "사지마비"
    ]

    # 1. 기본 케어 키워드가 있으면 통과
    if any(word in q_norm for word in care_keywords):
        return False

    # 2. 의미상 돌봄 관련 표현이면 통과
    if any(word in q_norm for word in meaning_keywords):
        return False

    # 3. 질병/치료 문맥 표현이 있으면 통과
    if any(word in q for word in disease_context_keywords):
        return False

    # 4. 대표 질환명이 있으면 통과
    if any(word in q_norm for word in disease_keywords):
        return False

    # 완전히 무관해 보이는 일반 질문 패턴
    irrelevant_patterns = [
        r"^트럼프[\?\!\.\~]*$",
        r"^날씨[\?\!\.\~]*$",
        r"^주식[\?\!\.\~]*$",
        r"^로또[\?\!\.\~]*$",
        r"^안녕[\?\!\.\~]*$",
        r"^뭐야[\?\!\.\~]*$",
        r"^누구야[\?\!\.\~]*$",
        r"^오늘뭐하냐[\?\!\.\~]*$",
        r"^뭐함[\?\!\.\~]*$",
        r"^심심하다[\?\!\.\~]*$"
    ]

    for pattern in irrelevant_patterns:
        if re.match(pattern, q_norm):
            return True

    # 위 조건들에 안 걸리면 기본적으로 무관 질문으로 처리
    return True


def make_no_result_response(query, results, cond_display, count, service_results, found_sido, found_sigungu):
    warning_msg = "검색 결과가 없습니다.\n어르신의 건강상태, 생활불편, 돌봄 필요 상황 등을 구체적으로 입력해 주세요."

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
        "광주동구": ("광주광역시", "동구"),
        "광주서구": ("광주광역시", "서구"),
        "광주남구": ("광주광역시", "남구"),
        "광주북구": ("광주광역시", "북구"),
        "광주광역시동구": ("광주광역시", "동구"),
        "광주광역시서구": ("광주광역시", "서구"),
        "광주광역시남구": ("광주광역시", "남구"),
        "광주광역시북구": ("광주광역시", "북구"),

        "제주시": ("제주특별자치도", "제주시"),
        "제주시청": ("제주특별자치도", "제주시"),
        "제주": ("제주특별자치도", "제주시"),
        "서귀포시": ("제주특별자치도", "서귀포시"),
        "서귀포": ("제주특별자치도", "서귀포시")
    }


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

.highlight{
  font-weight:700;
  color:#1d4ed8;
}
.desc-warning{
  margin-top:14px;
  padding:14px 18px;
  border-radius:12px;
  background:#fff7ed;
  border:1px solid #fdba74;
  color:#9a3412;
  font-size:14px;
  line-height:1.7;

  display:flex;
  align-items:flex-start;
  gap:8px;
}

.ai-model-wrap{
  margin-top:10px;
  display:flex;
  justify-content:center;
}

.ai-model-badge{
  display:inline-flex;
  flex-direction:column;
  align-items:center;
  gap:4px;
  padding:8px 14px;
  border-radius:14px;
  background:#f8fafc;
  border:1px solid #e5e7eb;
}

.ai-model-top{
  display:flex;
  align-items:center;
  gap:7px;
  font-size:13px;
  font-weight:700;
  color:#111827;
  line-height:1.2;
}

.ai-logo{
  width:9px;
  height:9px;
  object-fit:contain;
  opacity:0.9;
}

.ai-model-icon{
  width:10px;
  height:10px;
  border-radius:50%;
  background:#2563eb;
  box-shadow:0 0 0 3px rgba(37,99,235,0.12);
  flex:0 0 auto;
}

.ai-model-sub{
  font-size:11px;
  color:#6b7280;
  line-height:1.2;
  letter-spacing:0.2px;
}

.ai-model-label{
  margin-top:6px;
  font-size:12px;
  color:#6b7280;
  letter-spacing:0.3px;

  display:inline-block;
  padding:4px 10px;
  border-radius:999px;

  background:linear-gradient(135deg,#e0f2fe,#dbeafe);
  border:1px solid #bfdbfe;

  font-weight:600;
}

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

.question-title{
  display:block;
  font-size:16px;
  line-height:1.6;
  word-break:keep-all;
  overflow-wrap:break-word;
  padding-left:26px;
  text-indent:-26px;
}

@media (max-width:480px){
  .question-title{
    font-size:15px;
    line-height:1.55;
    padding-left:19px;
    text-indent:-19px;
  }
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
    position:fixed;
    top:10px;
    right:10px;
    
    width:85px;
    padding:8px 6px;
    border-radius:16px;

    z-index:10;
  }

  #careForm{
    padding-bottom:160px;
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
      <b class="question-title">{{i+1}}) {{q}}</b>

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
    return render_template_string(
        CARE_HTML,
        style=BASE_STYLE,
        questions=list(enumerate(CARE_QUESTIONS))
    )

@app.route("/care_check", methods=["POST"])
def care_check():
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
.ai-engine-text{
  font-size:14px !important;   /* 🔥 핵심: 확 줄임 */
  font-weight:500 !important;
  color:#6b7280 !important;    /* 🔥 회색톤 */
  letter-spacing:0.2px;
}

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