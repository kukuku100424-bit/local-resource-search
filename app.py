from flask import Flask, render_template_string, request, jsonify, redirect, url_for, session, send_file
import pandas as pd
import os
import re
import json
import time
from io import BytesIO
from collections import defaultdict

from dotenv import load_dotenv
load_dotenv()

from openai import OpenAI
import requests
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email.mime.text import MIMEText
from email import encoders

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

def trim_desc_cache(max_size=100):
    """DESC_CACHE가 max_size 초과 시 오래된 항목부터 제거"""
    if len(DESC_CACHE) > max_size:
        sorted_keys = sorted(DESC_CACHE, key=lambda k: DESC_CACHE[k].get("time", 0))
        for k in sorted_keys[:len(DESC_CACHE) - max_size]:
            del DESC_CACHE[k]

import datetime
from zoneinfo import ZoneInfo

                           
SUPABASE_URL = "https://iiktpwqncvwvrzytfssb.supabase.co"
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

SUPABASE_HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json"
}

def update_visitors():
    now = datetime.datetime.now(ZoneInfo("Asia/Seoul"))

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

@app.route("/favicon.ico")
def favicon():
    return "", 204

import logging
logging.getLogger('werkzeug').setLevel(logging.ERROR)
logging.getLogger('flask.app').setLevel(logging.ERROR)

@app.before_request
def require_login_all_pages():
    if (
        request.path == "/"
        or request.path == "/login"
        or request.path == "/admin"
        or request.path == "/app-version.json"
        or request.path.startswith("/static")
    ):
        return None

    if request.path.startswith("/stats"):
        if not session.get("is_admin"):
            return redirect(url_for("admin_login"))
        return None
    if request.path.startswith("/board/admin"):
        if not session.get("is_admin"):
            return redirect(url_for("admin_login"))
        return None
    if request.path.startswith("/notice/admin"):
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
<meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
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
  top:16px;
  right:18px;
  color:#9ca3af;
  font-size:12px;
  font-weight:600;
  text-decoration:none;
  z-index:2;
  transition:color .15s ease;
}

.admin-link:hover{
  color:#6b7280;
  text-decoration:underline;
}

.admin-link:active{
  color:#374151;
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

<div id="cn-app-version" style="position:fixed;bottom:8px;right:10px;font-size:11px;color:#aaa;pointer-events:none;z-index:9999;"></div>
<script>
(function(){
  /* 로그인 페이지 진입 시 가이드투어 세션 dismiss 해제 → 재로그인하면 다시 보임 */
  try { sessionStorage.removeItem('careNaviTourSessionDismissed'); } catch(e){}

  if(window.AndroidAppInfo){
    try{
      var name = window.AndroidAppInfo.getVersionName();
      var el = document.getElementById('cn-app-version');
      if(el) el.textContent = '케어네비 v' + name;
    }catch(e){}
  }
})();
</script>
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

        if pw == "1234":  # 원하는 비밀번호
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

        if pw == "qwer":
            session["is_admin"] = True
            return redirect(url_for("stats"))
        else:
            return render_template_string(
                ADMIN_LOGIN_HTML,
                error="관리자 암호가 올바르지 않습니다."
            )

    return render_template_string(ADMIN_LOGIN_HTML, error="")

# =========================
# 서버 오류 안내 페이지
# =========================
ERROR_500_HTML = """
<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>서버 오류 안내</title>
<style>
body{
  margin:0;
  min-height:100vh;
  background:#f4f6fb;
  font-family:'Pretendard',sans-serif;
  display:flex;
  align-items:center;
  justify-content:center;
  padding:20px;
  color:#111827;
}
.error-box{
  width:100%;
  max-width:460px;
  background:white;
  border-radius:18px;
  padding:26px 22px;
  box-shadow:0 8px 24px rgba(0,0,0,0.08);
  text-align:center;
}
.error-icon{
  font-size:38px;
  margin-bottom:12px;
}
.error-title{
  font-size:20px;
  font-weight:800;
  margin-bottom:10px;
}
.error-msg{
  font-size:14px;
  line-height:1.7;
  color:#4b5563;
  word-break:keep-all;
  margin-bottom:20px;
}
.home-btn{
  display:inline-flex;
  align-items:center;
  justify-content:center;
  gap:5px;
  height:34px;
  padding:0 15px;
  border-radius:8px;
  background:#ffffff;
  border:1px solid #e5e7eb;
  color:#6b7280;
  text-decoration:none;
  font-size:13px;
  font-weight:600;
  box-shadow:0 2px 6px rgba(15,23,42,0.08);
  transition:all .15s;
}
</style>
</head>
<body>
  <div class="error-box">
    <div class="error-icon">⚠️</div>
    <div class="error-title">일시적인 오류가 발생했습니다</div>
    <div class="error-msg">
      서버 사용량이 많거나 일시적인 오류로 요청을 처리하지 못했습니다.<br>
      잠시 후 다시 시도해 주세요.
    </div>
    <a href="/home" class="home-btn">홈으로 이동</a>
  </div>
</body>
</html>
"""

@app.errorhandler(404)
def handle_404(e):
    return "", 204

@app.errorhandler(Exception)
def handle_all_errors(e):
    app.logger.exception(e)
    return render_template_string(ERROR_500_HTML), 500


# =========================
# 서버 오류 테스트용
# =========================
@app.route("/test500")
def test500():
    raise Exception("서버 오류 테스트")

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
  display:inline-flex;
  align-items:center;
  justify-content:center;
  gap:5px;
  height:34px;
  padding:0 15px;
  border-radius:8px;
  background:#ffffff;
  border:1px solid #e5e7eb;
  color:#6b7280;
  text-decoration:none;
  font-size:13px;
  font-weight:600;
  box-shadow:0 2px 6px rgba(15,23,42,0.08);
  transition:all .15s;
}

.home-button:hover{
  background:#f3f4f6;
  color:#374151;
}

/* 앱(standalone/CareNaviApp) 모드: 상단 여백 축소 */
body.app-mode .container{
  padding-top:6px !important;
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
    height:30px;
    font-size:11.5px;
    padding:0 10px;
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


def clean_notices_for_template(notices):
    """공지사항 날짜값이 없거나 None이어도 템플릿이 터지지 않게 정리"""
    cleaned = []
    for n in notices or []:
        if not isinstance(n, dict):
            continue

        item = dict(n)
        raw = item.get("created_at") or item.get("inserted_at") or item.get("updated_at") or ""
        raw = str(raw) if raw is not None else ""

        item["created_date"] = raw[:10] if raw else ""
        item["created_datetime"] = raw[:19].replace("T", " ") if raw else ""
        item["title"] = item.get("title") or "제목 없음"
        item["content"] = item.get("content") or ""
        item["is_active"] = bool(item.get("is_active", True))
        cleaned.append(item)
    return cleaned

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
  margin-top:-120px;
  margin-bottom:-140px;
  pointer-events:none;
  position:relative;
  z-index:0;
}


.bottom-row{
  position:relative;
  z-index:2;
}

@media (max-width:480px){

  .bottom-img{
    margin-top:-40px;
    margin-bottom:-40px;
  }

  .bottom-footer{
    margin-top:-10px;
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
  padding:calc(28px + env(safe-area-inset-top)) 20px 20px 20px;

  position:relative;
}

/* 앱(CareNaviApp/PWA) 모드: 상단 여백 축소 */
body.app-mode .container{
  padding-top:28px !important;
}
/* 타이틀 */
/* 타이틀 */
.title{
  position:relative;
  text-align:center;
  margin-bottom:24px;
}

.home-admin-hidden{
  position:absolute;
  top:-14px;
  left:-2px;
  font-size:9px;
  color:#e5e7eb;
  text-decoration:none;
  font-weight:500;
  opacity:0.5;
}

.home-admin-hidden:hover{
  color:#94a3b8;
  opacity:1;
}

/* 사용설명서 버튼 (동그란 ? 버튼) */
.home-help-btn{
  position:absolute;
  top:-2px;
  right:0;
  width:34px;
  height:34px;
  display:inline-flex;
  align-items:center;
  justify-content:center;
  background:#2563eb;
  border:none;
  border-radius:50%;
  color:#fff;
  font-size:18px;
  font-weight:900;
  line-height:1;
  cursor:pointer;
  text-decoration:none;
  z-index:5;
  box-shadow:0 2px 6px rgba(37,99,235,0.3);
  transition:background 0.15s, transform 0.1s;
}
.home-help-btn:hover{
  background:#1d4ed8;
}
.home-help-btn:active{
  transform:scale(0.94);
}

/* 공지사항 버튼 */
.home-notice-btn{
  position:absolute;
  top:-2px;
  right:42px;
  width:34px;
  height:34px;
  display:inline-flex;
  align-items:center;
  justify-content:center;
  background:#2563eb;
  border:none;
  border-radius:50%;
  color:#fff;
  font-size:16px;
  font-weight:900;
  line-height:1;
  cursor:pointer;
  text-decoration:none;
  z-index:5;
  box-shadow:0 2px 6px rgba(37,99,235,0.3);
  transition:background 0.15s, transform 0.1s;
}
.home-notice-btn:hover{ background:#1d4ed8; }
.home-notice-btn:active{ transform:scale(0.94); }
.home-notice-btn .notice-dot{
  position:absolute;
  top:0px;
  right:0px;
  width:9px;
  height:9px;
  background:#ef4444;
  border-radius:50%;
  border:2px solid #fff;
}

/* 공지사항 버튼 임시 숨김 */
.home-notice-btn{
  display:none !important;
}

/* 모바일: 종+물음표 버튼 축소 */
@media (max-width:480px){
  .home-help-btn{
    width:27px !important;
    height:27px !important;
    font-size:14px !important;
    top:-10px !important;
    right:0 !important;
  }

  .home-notice-btn{
    width:27px !important;
    height:27px !important;
    top:-10px !important;
    right:34px !important;
  }

  .home-notice-btn svg{
    width:13px !important;
    height:13px !important;
  }

  .home-notice-btn .notice-dot{
    width:6px;
    height:6px;
    top:-1px;
    right:-1px;
  }
}

/* 공지사항 모달 */
.notice-modal{
  display:none;
  position:fixed;
  inset:0;
  background:rgba(0,0,0,0.5);
  z-index:10000;
  align-items:center;
  justify-content:center;
  padding:16px;
}
.notice-modal.open{ display:flex; }
.notice-box{
  background:#fff;
  border-radius:18px;
  max-width:480px;
  width:100%;
  max-height:80vh;
  display:flex;
  flex-direction:column;
  overflow:hidden;
  box-shadow:0 20px 50px rgba(15,23,42,0.22);
}
.notice-header{
  display:flex;
  align-items:center;
  justify-content:space-between;
  padding:16px 20px;
  border-bottom:1px solid #e5e7eb;
}
.notice-header-title{
  font-size:16px;
  font-weight:800;
  color:#111827;
}
.notice-close{
  background:none;
  border:none;
  font-size:22px;
  color:#6b7280;
  cursor:pointer;
  padding:4px 8px;
}
.notice-body{
  flex:1;
  overflow-y:auto;
  padding:16px 20px;
}
.notice-item{
  padding:14px 0;
  border-bottom:1px solid #f3f4f6;
}
.notice-item:last-child{ border-bottom:none; }
.notice-item-title{
  font-size:14px;
  font-weight:700;
  color:#111827;
  margin-bottom:5px;
}
.notice-item-date{
  font-size:11px;
  color:#9ca3af;
  margin-bottom:6px;
}
.notice-item-content{
  font-size:13px;
  color:#4b5563;
  line-height:1.65;
  white-space:pre-line;
  word-break:keep-all;
}
.notice-empty{
  text-align:center;
  color:#9ca3af;
  font-size:13px;
  padding:30px 0;
}

/* 가이드(설명서) 모달 */
.guide-modal{
  display:none;
  position:fixed;
  inset:0;
  background:rgba(0,0,0,0.75);
  z-index:10000;
  align-items:center;
  justify-content:center;
  padding:16px;
}
.guide-modal.open{ display:flex; }
.guide-box{
  background:#fff;
  border-radius:16px;
  max-width:560px;
  width:100%;
  max-height:92vh;
  display:flex;
  flex-direction:column;
  overflow:hidden;
}
.guide-header{
  display:flex;
  align-items:center;
  justify-content:space-between;
  padding:12px 16px;
  border-bottom:1px solid #e5e7eb;
}
.guide-title{
  font-size:15px;
  font-weight:800;
  color:#111827;
}
.guide-close{
  background:none;
  border:none;
  font-size:22px;
  color:#6b7280;
  cursor:pointer;
  padding:4px 8px;
}
.guide-image-wrap{
  flex:1;
  overflow:auto;
  background:#f9fafb;
  display:flex;
  align-items:flex-start;
  justify-content:center;
  padding:8px;
}
.guide-image-wrap img{
  max-width:100%;
  height:auto;
  display:block;
}
.guide-nav{
  display:flex;
  align-items:center;
  justify-content:space-between;
  padding:10px 14px;
  border-top:1px solid #e5e7eb;
  background:#fff;
}
.guide-nav-btn{
  padding:8px 16px;
  border-radius:10px;
  background:#2563eb;
  color:#fff;
  border:none;
  font-size:14px;
  font-weight:700;
  cursor:pointer;
}
.guide-nav-btn:disabled{
  background:#cbd5e1;
  cursor:not-allowed;
}
.guide-page-indicator{
  font-size:13px;
  color:#6b7280;
  font-weight:600;
}

/* 첫방문 가이드 투어 */
.tour-overlay{
  display:none;
  position:fixed;
  inset:0;
  background:rgba(0,0,0,0.65);
  z-index:9998;
  pointer-events:auto;
}
.tour-overlay.open{ display:block; }
.tour-spotlight{
  position:fixed;
  border-radius:24px;
  box-shadow:0 0 0 9999px rgba(0,0,0,0.65);
  pointer-events:none;
  z-index:9999;
  transition:all 0.25s ease;
}
.tour-popup{
  display:none;
  position:fixed;
  z-index:10001;
  background:#fff;
  border-radius:14px;
  padding:18px 18px 14px;
  max-width:300px;
  box-shadow:0 12px 36px rgba(0,0,0,0.3);
}
.tour-popup.open{ display:block; }
.tour-popup-title{
  font-size:15px;
  font-weight:800;
  color:#111827;
  margin-bottom:6px;
}
.tour-popup-text{
  font-size:13px;
  color:#475569;
  line-height:1.5;
  margin-bottom:14px;
}
.tour-popup-buttons{
  display:flex;
  gap:8px;
  justify-content:flex-end;
}
.tour-btn{
  border:none;
  border-radius:8px;
  padding:7px 12px;
  font-size:12.5px;
  font-weight:700;
  cursor:pointer;
}
.tour-btn-primary{
  background:#2563eb;
  color:#fff;
}
.tour-btn-secondary{
  background:#f1f5f9;
  color:#475569;
}
.tour-btn-dismiss{
  background:transparent;
  color:#94a3b8;
  font-weight:600;
}

/* 팝업 안내문구의 미니 ? 아이콘 (실제 버튼처럼 보이게) */
.tour-q-icon{
  display:inline-flex;
  align-items:center;
  justify-content:center;
  width:18px;
  height:18px;
  border-radius:50%;
  background:#2563eb;
  color:#fff;
  font-size:11px;
  font-weight:900;
  vertical-align:middle;
  line-height:1;
}

.title + .card{
  margin-top:18px;   /* 👈 여기 추가 */
}

.title h1{
  margin:0;
  font-size:32px;
  font-weight:900;
  letter-spacing:-1px;
  color:#111827;
}

.title h1 span{
  color:#2563eb;
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
  gap:14px;
  background:white;
  padding:13px 16px;
  border-radius:14px;
  margin-bottom:9px;
  box-shadow:0 6px 16px rgba(0,0,0,0.07);
  text-decoration:none;
  color:inherit;
  transition:0.18s;
}

.card:hover{
  transform:translateY(-3px);
  box-shadow:0 14px 32px rgba(0,0,0,0.12);
}
.main-menu-card{
  background:white;
  border:1px solid #e5e7eb;
  border-left:8px solid #60a5fa;
  color:#111827;
}


.main-menu-card span{
  color:#4b5563;
}

.main-menu-card .icon{
  background:#eff6ff;
}

.main-menu-card:hover{
  background:#f8fbff;
  border-left-color:#3b82f6;
}

.sub-card{
  background:white;
  border:1px solid #e5e7eb;
  border-left:8px solid #fb7185;
  color:#111827;
}

.sub-card span{
  color:#4b5563;
}

.sub-card .icon{
  background:#fff1f2;
}

.sub-card:hover{
  background:#fff7f8;
  border-left-color:#f43f5e;
}

/* 아이콘 */
.icon{
  width:44px;
  height:44px;
  flex-shrink:0;
  border-radius:12px;
  background:#e8f1ff;
  display:flex;
  align-items:center;
  justify-content:center;
  font-size:22px;
}

/* 텍스트 */
.text{
  flex:1;
}

.text b{
  font-size:14.5px;
  display:block;
  margin-bottom:2px;
}

.text span{
  font-size:12px;
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
  border-radius:12px;
  padding:11px 10px;
  text-align:center;
  text-decoration:none;
  color:#111827;
  box-shadow:0 4px 12px rgba(0,0,0,0.07);
  transition:0.15s;
}

.bottom-card:hover{
  transform:translateY(-2px);
}

.bottom-card img{
  width:26px;
  margin-bottom:4px;
}

.bottom-card div{
  font-size:13px;
}

/* 모바일 */
@media (max-width:480px){

.container{
    padding-top:calc(26px + env(safe-area-inset-top)) !important;
  }

.main-menu-card,
.sub-card{
  height:65px !important;
  min-height:0 !important;
  padding:0 12px !important;
  align-items:center !important;
  box-sizing:border-box !important;
}
.main-menu-card .icon,
.sub-card .icon{
  width:40px !important;
  height:40px !important;
  flex-shrink:0 !important;
  font-size:19px !important;
}
.main-menu-card .text b,
.sub-card .text b{
  font-size:13px !important;
  margin-bottom:1px !important;
}
.main-menu-card .text span,
.sub-card .text span{
  font-size:11px !important;
  overflow:visible !important;
  display:block !important;
  white-space:normal !important;
}

.bottom-card{
  flex:1;
  background:white;
  border-radius:14px;
  height:65px !important;
  min-height:0 !important;
  padding:0 10px !important;
  box-sizing:border-box !important;
  text-align:center;
  text-decoration:none;
  color:#111827;
  box-shadow:0 6px 16px rgba(0,0,0,0.08);
  transition:0.15s;
  display:flex !important;
  flex-direction:column !important;
  justify-content:center !important;
  align-items:center !important;
}

.bottom-card img{
  width:20px !important;
  margin-bottom:2px !important;
}
  .title h1{
    font-size:22px;
  }

.card{
  padding:10px 12px !important;
  margin-bottom:8px !important;
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
  letter-spacing:-0.2px;
}

.copyright-sub .brand{
  color:#2563eb;
  font-weight:800;
}

.copyright-sub .tf-label{
  font-size:13px;
}


.bottom-footer{
  margin-top:-40px;
  padding:0 12px;
  display:flex;
  justify-content:space-between;
  align-items:flex-start;
  gap:16px;
}

.visitor-box{
  display:flex;
  gap:8px;
  flex-wrap:wrap;
}

.visitor-box-top{
  justify-content:center;
  margin-top:0;
}

.visitor-box div{
  padding:4px 10px;
  border-radius:999px;
  background:transparent;
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
<a href="/admin" class="home-admin-hidden">관리자</a>
<button type="button" class="home-notice-btn" onclick="openNotice()" aria-label="공지사항">
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="M12 2C10.9 2 10 2.9 10 4V4.29C7.12 5.14 5 7.82 5 11V17L3 19V20H21V19L19 17V11C19 7.82 16.88 5.14 14 4.29V4C14 2.9 13.1 2 12 2Z" fill="white"/><path d="M12 24C13.66 24 15 22.66 15 21H9C9 22.66 10.34 24 12 24Z" fill="white"/></svg>
  {% if notices %}<span class="notice-dot"></span>{% endif %}
</button>
<button type="button" class="home-help-btn" onclick="openGuide()" aria-label="사용설명서">?</button>
<h1>NHIS-G <span>케어네비</span></h1>
<p>통합돌봄 자원 검색 및 안내 서비스</p>
</div>

<a href="/desc" class="card main-menu-card">

<div class="icon">🤖</div>

<div class="text">
<b>사례별 AI 추천 서비스 찾기</b>
<span>사례분석을 통해 적합한 서비스를 추천합니다.</span>
</div>

</a>

<a href="/combo" class="card main-menu-card">

<div class="icon">🔎</div>

<div class="text">
<b>통합돌봄 서비스 기관 찾기</b>
<span>시도, 대분류 등 조건으로 서비스 자원을 검색합니다.</span>
</div>

</a>

<a href="/survey" class="card sub-card">

<div class="icon">📋</div>

<div class="text">
<b>통합돌봄 지자체 조사 서식</b>
<span>사전조사, 자체조사, 연계조사를 진행하고 저장합니다.</span>
</div>

</a>

<div class="bottom-row">

<a href="/guide" class="bottom-card">

<img src="/static/pdf_icon.png">

<div>통합돌봄 사업 안내</div>

</a>

<a href="/nhis25" class="bottom-card">

<img src="/static/nhis_heart.png">

<div>건강보험 25시</div>

</a>

</div>



<img src="/static/bottom.png" class="bottom-img">
<div class="bottom-footer">

  <div class="visitor-left">
    <div id="reportBtn">
      <svg xmlns="http://www.w3.org/2000/svg" width="26" height="26" fill="white" viewBox="0 0 24 24">
        <path d="M21 6h-2V3H5v3H3v15h18V6zM7 5h10v1H7V5zm12 14H5V8h14v11z"/>
      </svg>
    </div>
    <div id="singleReportBtn" style="display:none;">
      <svg xmlns="http://www.w3.org/2000/svg" width="26" height="26" fill="white" viewBox="0 0 24 24">
        <path d="M21 6h-2V3H5v3H3v15h18V6zM7 5h10v1H7V5zm12 14H5V8h14v11z"/>
      </svg>
    </div>
    <div id="fabWrap" style="display:none;">
      <div id="fabItems" style="display:none;">
        <div id="fabItem_notice" class="fab-item">
          <div class="fab-item-btn" style="position:relative;">
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="M12 2C10.9 2 10 2.9 10 4V4.29C7.12 5.14 5 7.82 5 11V17L3 19V20H21V19L19 17V11C19 7.82 16.88 5.14 14 4.29V4C14 2.9 13.1 2 12 2Z" fill="white"/><path d="M12 24C13.66 24 15 22.66 15 21H9C9 22.66 10.34 24 12 24Z" fill="white"/></svg>
            {% if notices %}<span class="fab-item-dot"></span>{% endif %}
          </div>
          <span class="fab-item-label">공지사항</span>
        </div>
        <div id="fabItem_report" class="fab-item">
          <div class="fab-item-btn">
            <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" fill="white" viewBox="0 0 24 24">
              <path d="M21 6h-2V3H5v3H3v15h18V6zM7 5h10v1H7V5zm12 14H5V8h14v11z"/>
            </svg>
          </div>
          <span class="fab-item-label">의견보내기</span>
        </div>
        <div id="fabItem_apk" class="fab-item">
          <div class="fab-item-btn">
            <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" fill="white" viewBox="0 0 24 24">
              <path d="M17.5 2.5L15.5 1l-1.3 2.1C13.5 2.8 12.8 2.6 12 2.6s-1.5.2-2.2.5L8.5 1 6.5 2.5l1.2 2C6.1 5.7 5 7.5 5 9.5h14c0-2-.9-3.8-2.7-5l1.2-2zM9 7.5c-.6 0-1-.4-1-1s.4-1 1-1 1 .4 1 1-.4 1-1 1zm6 0c-.6 0-1-.4-1-1s.4-1 1-1 1 .4 1 1-.4 1-1 1z"/>
              <rect x="2" y="11" width="2.5" height="6" rx="1.2" fill="white"/>
              <rect x="19.5" y="11" width="2.5" height="6" rx="1.2" fill="white"/>
              <path d="M5 11v8c0 1.1.9 2 2 2h1v3h2v-3h4v3h2v-3h1c1.1 0 2-.9 2-2v-8H5z"/>
            </svg>
          </div>
          <span class="fab-item-label">앱 설치</span>
        </div>
      </div>
      <div id="fabMain">
        {% if notices %}<span id="fabMainDot" class="fab-main-dot"></span>{% endif %}
        <svg id="fabIconPlus" xmlns="http://www.w3.org/2000/svg" width="26" height="26" fill="white" viewBox="0 0 24 24">
          <path d="M19 13H13v6h-2v-6H5v-2h6V5h2v6h6v2z"/>
        </svg>
        <svg id="fabIconClose" xmlns="http://www.w3.org/2000/svg" width="26" height="26" fill="white" viewBox="0 0 24 24" style="display:none;">
          <path d="M19 6.41L17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z"/>
        </svg>
      </div>
    </div>
    <div class="visitor-box">
      <div>총 {{total}}</div>
      <div>오늘 {{today}}</div>
    </div>
  </div>

  <div class="copyright">
    <div class="copyright-line"></div>
    <div class="copyright-main">
      ©국민건강보험공단 광주전라제주지역본부
    </div>
    <div class="copyright-sub">
      통합돌봄부<span class="tf-label">(TF)</span> &amp; 연구반 <span class="brand">돌봄곳간</span>
    </div>
  </div>

</div>

<style>
</style>


<!-- ===== 단일 의견보내기 버튼 (PC/아이폰/앱) ===== -->




<!-- ===== Modal ===== -->

<!-- ===== 앱 설치 안내 모달 ===== -->
<div id="apkInstallModal" onclick="closeApkInstallModalByBg(event)">
  <div class="apk-install-box">

    <div class="apk-install-icon">📱</div>

    <div class="apk-install-title">케어네비 앱 설치 안내</div>

    <div class="apk-install-subtitle">
      안드로이드용 설치 파일을 다운로드합니다.
    </div>

    <div class="apk-install-text">
      다운로드 후 설치 화면이 나오면<br>
      <b>'설치'</b>를 눌러주세요.<br><br>
      휴대폰 설정에 따라<br>
      <b>'출처를 알 수 없는 앱 설치 허용'</b>이<br>
      필요할 수 있습니다.
    </div>

    <div class="apk-install-buttons">
  <button type="button" class="apk-confirm-btn" onclick="confirmApkDownload()">다운로드</button>
  <button type="button" class="apk-cancel-btn" onclick="closeApkInstallModal()">취소</button>
</div>

  </div>
</div>

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

/* ===== visitor-left 컨테이너 ===== */
.visitor-left{
  display:flex;
  flex-direction:column;
  align-items:flex-start;
  gap:8px;
  padding-bottom:40px;
}

/* PC/아이폰/앱 단일 의견보내기 버튼 */
#singleReportBtn{
  width:54px;
  height:54px;
  border-radius:50%;
  background:linear-gradient(135deg,#3b82f6,#2563eb);
  box-shadow:0 8px 20px rgba(37,99,235,0.4);
  cursor:pointer;
  z-index:9999;
  display:none;
  align-items:center;
  justify-content:center;
  transition:transform 0.2s;
  flex-shrink:0;
}
#singleReportBtn:hover{
  transform:scale(1.08);
}

/* 모바일/앱: fixed 왼쪽 하단 (+ 버튼 위치) */
@media (max-width:600px){
  #singleReportBtn{
    position:fixed;
    left:14px;
    bottom:60px;
    width:54px;
    height:54px;
    border-radius:50%;
  }
}

/* PC: bottom-footer 안 static, 알약 모양 */
@media (min-width:601px){
  #singleReportBtn{
    position:static;
    width:auto;
    height:38px;
    border-radius:999px;
    padding:0 16px 0 12px;
    gap:7px;
    font-size:13px;
    font-weight:700;
    color:#fff;
    letter-spacing:-0.2px;
    white-space:nowrap;
    align-self:flex-end;
  }
  #singleReportBtn::after{
    content:'의견보내기';
  }
}

/* PC 오류제보 버튼 (visitor-left 안 구버튼 - 숨김) */
#reportBtn{
  display:none !important;
}

#reportBtn:hover{
  transform:scale(1.08);
}

/* ===== 스피드다이얼 FAB ===== */
#fabWrap{
  position:fixed;
  left:14px;
  bottom:60px;
  display:flex;
  flex-direction:column;
  align-items:flex-start;
  gap:12px;
  z-index:9999;
}

/* 메인 버튼 */
#fabMain{
  width:54px;
  height:54px;
  border-radius:50%;
  background:linear-gradient(135deg,#3b82f6,#2563eb);
  display:flex;
  align-items:center;
  justify-content:center;
  box-shadow:0 8px 20px rgba(37,99,235,0.4);
  cursor:pointer;
  transition:transform 0.2s, box-shadow 0.2s;
  flex-shrink:0;
}

#fabMain:hover{
  transform:scale(1.08);
}

#fabMain.open{
  background:linear-gradient(135deg,#64748b,#475569);
  box-shadow:0 8px 20px rgba(0,0,0,0.25);
}

/* 서브 아이템 */
/* 서브 아이템 감싸는 박스 */
#fabItems{
  display:flex;
  flex-direction:column;
  gap:8px;
  background:rgba(255,255,255,0.92);
  backdrop-filter:blur(8px);
  -webkit-backdrop-filter:blur(8px);
  border-radius:16px;
  padding:10px 12px;
  box-shadow:0 4px 20px rgba(0,0,0,0.18);
  min-width:120px;
}

#fabItems:empty{
  display:none;
}

.fab-item{
  display:none;
  align-items:center;
  gap:10px;
  flex-direction:row;
}

.fab-item.show{
  display:flex;
  animation:fabItemIn 0.18s ease;
}

@keyframes fabItemIn{
  from{ opacity:0; transform:translateY(8px); }
  to{ opacity:1; transform:translateY(0); }
}

.fab-item-btn{
  width:40px;
  height:40px;
  border-radius:50%;
  background:linear-gradient(135deg,#3b82f6,#2563eb);
  display:flex;
  align-items:center;
  justify-content:center;
  box-shadow:0 4px 12px rgba(37,99,235,0.35);
  cursor:pointer;
  transition:transform 0.15s;
  flex-shrink:0;
}

.fab-item-btn:hover{
  transform:scale(1.08);
}

.fab-item-label{
  color:#1e293b;
  font-size:13px;
  font-weight:700;
  white-space:nowrap;
  pointer-events:none;
}

/* PC에서 visitor-left 안 reportBtn은 그대로 표시 */
/* 모바일에서 visitor-left 안 reportBtn 숨김 */
@media (max-width:600px){
  .visitor-left #reportBtn{
    display:none !important;
  }
  .visitor-left{
    flex-direction:row;
    align-items:center;
    padding-bottom:0;
  }
  #reportBox{
    width:100%;
    height:100%;
    border-radius:0;
  }
}

/* PC: + 버튼을 원래 의견보내기 자리(푸터 visitor-left)로 — fixed 해제 */
@media (min-width:601px){
  #fabWrap{
    display:inline-flex !important;
    position:relative !important;
    left:auto !important;
    bottom:auto !important;
    z-index:1;
    align-self:flex-start;
    gap:0;
  }
  /* 메뉴는 + 버튼 위로 떠서 펼쳐짐 (푸터 레이아웃 안 밀림) */
  #fabItems{
    position:absolute;
    bottom:calc(100% + 12px);
    left:0;
  }
}

/* 단일 의견보내기 버튼/알약 완전 폐지 */
#singleReportBtn{ display:none !important; }

/* 공지 빨간점 — 메뉴 안 공지사항 항목 */
.fab-item-dot{
  position:absolute;
  top:-2px;
  right:-2px;
  width:11px;
  height:11px;
  background:#ef4444;
  border-radius:50%;
  border:2px solid #fff;
}

/* 공지 빨간점 — 메인 + 버튼 */
#fabMain{ position:relative; }
.fab-main-dot{
  position:absolute;
  top:4px;
  right:4px;
  width:12px;
  height:12px;
  background:#ef4444;
  border-radius:50%;
  border:2px solid #fff;
  z-index:1;
}

/* 모바일 웹에서 fabWrap 위치 */
@media (max-width:600px){
  #fabWrap{
    bottom:60px !important;
  }
}

/* ===== 앱 설치 안내 모달 ===== */
#apkInstallModal{
  position:fixed;
  inset:0;
  background:rgba(15,23,42,0.55);
  display:none;
  align-items:center;
  justify-content:center;
  z-index:10050;
  backdrop-filter:blur(3px);
  -webkit-backdrop-filter:blur(3px);
}

.apk-install-box{
  background:#ffffff;
  border-radius:22px;
  padding:34px 28px 26px;
  width:88%;
  max-width:360px;
  text-align:center;
  box-shadow:0 18px 50px rgba(0,0,0,0.24);
  font-family:inherit;
  animation:apkModalIn 0.2s ease;
}

.apk-install-icon{
  font-size:38px;
  margin-bottom:12px;
}

.apk-install-title{
  font-size:18px;
  font-weight:900;
  color:#111827;
  margin-bottom:8px;
  letter-spacing:-0.3px;
}

.apk-install-subtitle{
  font-size:13px;
  color:#6b7280;
  line-height:1.5;
  margin-bottom:18px;
}

.apk-install-text{
  font-size:13.5px;
  color:#374151;
  line-height:1.7;
  word-break:keep-all;
  margin-bottom:22px;
}

.apk-install-text b{
  color:#2563eb;
  font-weight:800;
}

.apk-install-buttons{
  display:grid;
  grid-template-columns:1fr 1fr;
  gap:10px;
}

.apk-cancel-btn,
.apk-confirm-btn{
  height:42px;
  border-radius:10px;
  font-size:14px;
  font-weight:800;
  cursor:pointer;
  border:none;
}

.apk-cancel-btn{
  background:#f3f4f6;
  color:#4b5563;
}

.apk-confirm-btn{
  background:linear-gradient(135deg,#3b82f6,#2563eb);
  color:#ffffff;
  box-shadow:0 6px 16px rgba(37,99,235,0.28);
}

@keyframes apkModalIn{
  from{
    opacity:0;
    transform:translateY(14px) scale(0.98);
  }
  to{
    opacity:1;
    transform:translateY(0) scale(1);
  }
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

</style>

<script>
/* ===== FAB 초기화 (항상 + 버튼, 환경별 항목만 분기) ===== */
(function(){
  var ua = navigator.userAgent || "";
  var isAndroid    = /Android/i.test(ua);
  var isIOS        = /iPhone|iPad|iPod/i.test(ua);
  var isApp        = ua.indexOf("CareNaviApp") !== -1;
  var isStandalone = window.matchMedia && window.matchMedia('(display-mode: standalone)').matches;

  // 앱 모드 body 클래스 (상단 여백 축소용)
  if(isApp || isStandalone){
    document.body.classList.add("app-mode");
  }

  // 앱다운(APK)은 안드로이드 일반 브라우저에서만 (아이폰/앱/PWA 제외)
  var showApk = isAndroid && !isIOS && !isApp && !isStandalone;

  var fabWrap       = document.getElementById("fabWrap");
  var fabMain       = document.getElementById("fabMain");
  var fabItems      = document.getElementById("fabItems");
  var fabItemNotice = document.getElementById("fabItem_notice");
  var fabItemRep    = document.getElementById("fabItem_report");
  var fabItemApk    = document.getElementById("fabItem_apk");
  var fabIconPlus   = document.getElementById("fabIconPlus");
  var fabIconClose  = document.getElementById("fabIconClose");
  var singleBtn     = document.getElementById("singleReportBtn");
  var isOpen        = false;

  // 단일버튼/PC 알약 폐지 → 모든 환경에서 + FAB
  if(singleBtn) singleBtn.style.display = "none";
  if(fabWrap)   fabWrap.style.display   = "flex";

  // 앱다운 항목은 안드로이드 일반 브라우저에서만 노출
  if(fabItemApk) fabItemApk.style.display = showApk ? "" : "none";

  // 열렸을 때 보여줄 항목 (공지/의견은 항상, 앱다운은 조건부)
  var activeItems = [fabItemNotice, fabItemRep];
  if(showApk) activeItems.push(fabItemApk);

  function openFab(){
    isOpen = true;
    if(fabMain)      fabMain.classList.add("open");
    if(fabIconPlus)  fabIconPlus.style.display  = "none";
    if(fabIconClose) fabIconClose.style.display = "";
    if(fabItems)     fabItems.style.display = "flex";
    activeItems.forEach(function(it){ if(it) it.classList.add("show"); });
  }
  function closeFab(){
    isOpen = false;
    if(fabMain)      fabMain.classList.remove("open");
    if(fabIconPlus)  fabIconPlus.style.display  = "";
    if(fabIconClose) fabIconClose.style.display = "none";
    if(fabItems)     fabItems.style.display = "none";
    activeItems.forEach(function(it){ if(it) it.classList.remove("show"); });
  }

  if(fabMain){
    fabMain.addEventListener("click", function(e){
      e.stopPropagation();
      isOpen ? closeFab() : openFab();
    });
  }
  if(fabItemNotice){
    fabItemNotice.addEventListener("click", function(e){
      e.stopPropagation();
      closeFab();
      openNotice();
    });
  }
  if(fabItemRep){
    fabItemRep.addEventListener("click", function(e){
      e.stopPropagation();
      closeFab();
      location.href = "/board/write";
    });
  }
  if(fabItemApk){
    fabItemApk.addEventListener("click", function(e){
      e.stopPropagation();
      closeFab();
      openApkInstallModal();
    });
  }

  document.addEventListener("click", function(){ if(isOpen) closeFab(); });
})();

/* ===== 공지 빨간점 읽음 처리 (localStorage) ===== */
(function(){
  var KEY = "carenavi_seen_notice";
  var latest = {{ latest_notice_key|tojson }};
  function hideDots(){
    var d1 = document.getElementById("fabMainDot");
    var d2 = document.querySelector("#fabItem_notice .fab-item-dot");
    if(d1) d1.style.display = "none";
    if(d2) d2.style.display = "none";
  }
  // 이미 본 최신 공지면 점 숨김
  try{
    if(!latest || localStorage.getItem(KEY) === latest){
      hideDots();
    }
  }catch(e){}
  // 공지 열면 본 것으로 기록 + 점 제거
  window.__careNaviMarkNoticeSeen = function(){
    try{ if(latest) localStorage.setItem(KEY, latest); }catch(e){}
    hideDots();
  };
})();

/* 홈 진입 시 현재 상태를 홈으로 고정하고, 홈 상태를 하나 더 쌓아둠 */
history.replaceState({ page: "home-root" }, "", location.href);
history.pushState({ page: "home" }, "", location.href);

/* 오류제보 버튼 클릭 → 모달 열기 */
reportBtn.onclick = () => {
  location.href = "/board";
};

function openApkInstallModal(){
  var modal = document.getElementById("apkInstallModal");
  if(modal){
    modal.style.display = "flex";
  }
}

function closeApkInstallModal(){
  var modal = document.getElementById("apkInstallModal");
  if(modal){
    modal.style.display = "none";
  }
}

function closeApkInstallModalByBg(e){
  if(e.target && e.target.id === "apkInstallModal"){
    closeApkInstallModal();
  }
}

function confirmApkDownload(){
  closeApkInstallModal();
  window.location.href = "/static/carenavi.apk";
}

function openReport(){
  location.href = "/board/write";
}

function closeReport(){
  var reportModal = document.getElementById("reportModal");
  if(reportModal) reportModal.style.display = "none";
}

/* 배경 클릭 시 닫기 */
document.addEventListener("click", function(e){
  var reportModal = document.getElementById("reportModal");
  if(reportModal && e.target === reportModal){
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

<!-- 공지사항 모달 -->
<div id="noticeModal" class="notice-modal" onclick="if(event.target===this)closeNotice()">
  <div class="notice-box" onclick="event.stopPropagation()">
    <div class="notice-header">
      <div class="notice-header-title">공지사항</div>
      <button type="button" class="notice-close" onclick="closeNotice()">×</button>
    </div>
    <div class="notice-body">
      {% if notices %}
        {% for n in notices %}
        <div class="notice-item">
          <div class="notice-item-date">{{ n.created_date }}</div>
          <div class="notice-item-title">{{ n.title }}</div>
          <div class="notice-item-content">{{ n.content }}</div>
        </div>
        {% endfor %}
      {% else %}
        <div class="notice-empty">등록된 공지사항이 없습니다.</div>
      {% endif %}
    </div>
  </div>
</div>

<!-- 사용설명서 모달 -->
<div id="guideModal" class="guide-modal" onclick="onGuideBgClick(event)">
  <div class="guide-box" onclick="event.stopPropagation()">
    <div class="guide-header">
      <div class="guide-title">사용설명서</div>
      <button type="button" class="guide-close" onclick="closeGuide()">×</button>
    </div>
    <div class="guide-image-wrap">
      <img id="guideImage" src="" alt="사용설명서" />
    </div>
    <div class="guide-nav">
      <button type="button" class="guide-nav-btn" id="guidePrev" onclick="prevGuidePage()">이전</button>
      <div class="guide-page-indicator" id="guidePageIndicator">1</div>
      <button type="button" class="guide-nav-btn" id="guideNext" onclick="nextGuidePage()">다음</button>
    </div>
  </div>
</div>

<!-- 첫방문 가이드 투어 -->
<div id="tourOverlay" class="tour-overlay" onclick="closeTour()"></div>
<div id="tourSpotlight" class="tour-spotlight" style="display:none;"></div>
<div id="tourPopup" class="tour-popup">
  <div class="tour-popup-title">케어네비를 처음 방문해주셨네요 👋</div>
  <div class="tour-popup-text">사용법이 궁금하시면 우측 상단의 <span class="tour-q-icon">?</span> 버튼을 눌러보세요.</div>
  <div class="tour-popup-buttons">
    <button type="button" class="tour-btn tour-btn-primary" onclick="openGuideFromTour()">설명서 보기</button>
    <button type="button" class="tour-btn tour-btn-dismiss" onclick="dismissTourForever()">다시 보지 않기</button>
  </div>
</div>

<script>
/* ===== 공지사항 ===== */
function openNotice(){
  if(window.__careNaviMarkNoticeSeen) window.__careNaviMarkNoticeSeen();
  document.getElementById('noticeModal').classList.add('open');
}
function closeNotice(){
  document.getElementById('noticeModal').classList.remove('open');
}

/* ===== 사용설명서 ===== */
var guideTotalPages = 0;       // 동적으로 탐지됨
var guideCurrentPage = 1;
var guideMaxKnown = 0;          // 지금까지 존재 확인된 최대 페이지

function openGuide(){
  closeTour();
  guideCurrentPage = 1;
  loadGuidePage(1);
  document.getElementById('guideModal').classList.add('open');
}
function closeGuide(){
  document.getElementById('guideModal').classList.remove('open');
}
function onGuideBgClick(e){
  if(e.target && e.target.id === 'guideModal'){ closeGuide(); }
}
function loadGuidePage(n){
  var img = document.getElementById('guideImage');
  var indicator = document.getElementById('guidePageIndicator');
  var nextBtn = document.getElementById('guideNext');
  var prevBtn = document.getElementById('guidePrev');

  img.onload = function(){
    if(n > guideMaxKnown) guideMaxKnown = n;
    indicator.textContent = n + (guideTotalPages ? ' / ' + guideTotalPages : '');
    prevBtn.disabled = (n <= 1);
    /* 다음 페이지 존재 여부 미리 확인 */
    var probe = new Image();
    probe.onload = function(){ nextBtn.disabled = false; };
    probe.onerror = function(){
      nextBtn.disabled = true;
      guideTotalPages = n;
      indicator.textContent = n + ' / ' + guideTotalPages;
    };
    probe.src = '/static/' + (n + 1) + '.jpg?v=' + Date.now();
  };
  img.onerror = function(){
    /* 페이지가 없으면 이전 페이지로 */
    if(n > 1){
      guideTotalPages = n - 1;
      guideCurrentPage = n - 1;
      loadGuidePage(guideCurrentPage);
    }
  };
  img.src = '/static/' + n + '.jpg?v=' + Date.now();
}
function nextGuidePage(){
  guideCurrentPage += 1;
  loadGuidePage(guideCurrentPage);
}
function prevGuidePage(){
  if(guideCurrentPage > 1){
    guideCurrentPage -= 1;
    loadGuidePage(guideCurrentPage);
  }
}

/* ===== 첫방문 가이드 투어 ===== */
var TOUR_STORAGE_KEY = 'careNaviTourDismissed';        /* 영구 - "다시 보지 않기" */
var TOUR_SESSION_KEY = 'careNaviTourSessionDismissed'; /* 세션 - 그냥 닫음 (재로그인 전까지) */

function tourDismissed(){
  try {
    if(localStorage.getItem(TOUR_STORAGE_KEY) === '1') return true;
    if(sessionStorage.getItem(TOUR_SESSION_KEY) === '1') return true;
  } catch(e){}
  return false;
}
function dismissTourForever(){
  try { localStorage.setItem(TOUR_STORAGE_KEY, '1'); } catch(e){}
  try { sessionStorage.removeItem(TOUR_SESSION_KEY); } catch(e){}
  closeTour();
}
function dismissTourThisSession(){
  try { sessionStorage.setItem(TOUR_SESSION_KEY, '1'); } catch(e){}
}
function openTour(){
  var btn = document.querySelector('.home-help-btn');
  if(!btn) return;
  var rect = btn.getBoundingClientRect();

  var spotlight = document.getElementById('tourSpotlight');
  var pad = 6;
  spotlight.style.display = 'block';
  spotlight.style.top    = (rect.top  - pad) + 'px';
  spotlight.style.left   = (rect.left - pad) + 'px';
  spotlight.style.width  = (rect.width  + pad*2) + 'px';
  spotlight.style.height = (rect.height + pad*2) + 'px';

  var popup = document.getElementById('tourPopup');
  popup.classList.add('open');

  /* 팝업을 화면 중앙에 배치 (버튼 아래쪽) */
  var viewportW = window.innerWidth;
  var actualWidth = popup.offsetWidth || 300;
  var top  = rect.bottom + 14;
  var left = (viewportW - actualWidth) / 2;
  if(left < 12) left = 12;
  popup.style.top  = top + 'px';
  popup.style.left = left + 'px';

  document.getElementById('tourOverlay').classList.add('open');
}
function closeTour(){
  document.getElementById('tourOverlay').classList.remove('open');
  document.getElementById('tourPopup').classList.remove('open');
  document.getElementById('tourSpotlight').style.display = 'none';
  /* "그냥 닫기"는 이번 세션 동안만 안 보이게 (재로그인 시 다시 보임) */
  dismissTourThisSession();
}
function openGuideFromTour(){
  closeTour();
  openGuide();
}

/* 페이지 로드시 첫방문 체크 */
window.addEventListener('load', function(){
  if(!tourDismissed()){
    /* 약간 딜레이 줘서 레이아웃 안정화 후 띄움 */
    setTimeout(openTour, 350);
  }
});
</script>


</body>
</html>
"""
@app.route("/home")
@login_required
def home():
    total, today = update_visitors()

    notices = []
    try:
        if os.getenv("RENDER") is not None:
            res = requests.get(
                f"{SUPABASE_URL}/rest/v1/notices?select=*&is_active=eq.true&order=created_at.desc&limit=10",
                headers=SUPABASE_HEADERS
            )
            if res.ok:
                notices = res.json()
        else:
            notices = [{"id":1,"title":"테스트 공지","content":"로컬 테스트용 공지사항입니다.","created_at":"2026-06-04T00:00:00"}]
    except Exception as e:
        app.logger.exception(e)
        notices = []

    notices = clean_notices_for_template(notices)
    latest_notice_key = ""
    if notices:
        n0 = notices[0]
        latest_notice_key = str(
            n0.get("id")
            or n0.get("created_at")
            or n0.get("created_datetime")
            or ""
        )
    return render_template_string(HOME_HTML, style=BASE_STYLE, total=total, today=today, notices=notices, latest_notice_key=latest_notice_key)

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
  gap:8px;
  flex-wrap:nowrap;
  margin-bottom:18px;
  overflow-x:auto;
  -webkit-overflow-scrolling:touch;
  padding:2px 2px 8px 2px;
}

.top-right-menu{
  display:flex;
  align-items:center;
  gap:6px;
  flex-wrap:nowrap;
  flex-shrink:0;
}

.home-button{
  display:inline-flex !important;
  align-items:center !important;
  justify-content:center !important;
  height:34px !important;
  padding:0 13px !important;
  border-radius:999px !important;

  background:#ffffff !important;
  border:1px solid #e5e7eb !important;
  color:#6b7280 !important;

  text-decoration:none !important;
  font-size:13px !important;
  font-weight:700 !important;
  box-shadow:0 3px 10px rgba(15,23,42,0.08) !important;
}

.home-button:hover{
  background:#f3f4f6 !important;
  color:#374151 !important;
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

.table-scroll{
  max-height:360px;
  overflow-y:auto;
  overflow-x:auto;
  border:1px solid #e5e7eb;
  border-radius:12px;
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
    padding:16px 10px 28px 10px;
  }

  .top-bar{
    gap:6px !important;
    flex-wrap:nowrap !important;
    justify-content:flex-start !important;
    overflow-x:auto !important;
    white-space:nowrap !important;
    margin-bottom:14px !important;
    padding-bottom:8px !important;
  }

  .top-right-menu{
    gap:6px !important;
    flex-wrap:nowrap !important;
    flex-shrink:0 !important;
  }

  .home-button{
    height:34px !important;
    padding:0 12px !important;
    font-size:13px !important;
    white-space:nowrap !important;
    flex:0 0 auto !important;
  }

  th, td{
    font-size:13px;
    padding:8px 6px;
  }
  .summary-value{
    font-size:22px;
  }
}

@media (max-width:380px){
  .home-button{
    padding:0 10px !important;
    font-size:12.5px !important;
  }
  .top-bar,
  .top-right-menu{
    gap:5px !important;
  }
}

.pager{
  display:flex;
  justify-content:center;
  align-items:center;
  gap:6px;
  margin-top:12px;
  flex-wrap:wrap;
}

.pager button{
  min-width:32px;
  height:32px;
  border:1px solid #d1d5db;
  background:#ffffff;
  color:#374151;
  border-radius:8px;
  font-size:13px;
  font-weight:700;
  cursor:pointer;
}

.pager button.active{
  background:#2563eb;
  color:#ffffff;
  border-color:#2563eb;
}

.pager button:hover{
  background:#eff6ff;
}

.pager button.active:hover{
  background:#2563eb;
}

</style>
</head>
<body>
<div class="container">

  <div class="top-bar">
    <a href="/home" class="home-button">홈으로</a>

    <div class="top-right-menu">
      <a href="/board/admin" class="home-button">게시판</a>
      <a href="/notice/admin" class="home-button">공지관리</a>
      <a href="/stats/export/visits" class="home-button">엑셀</a>
      <a href="/stats/export/regions" class="home-button">엑셀2</a>
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
    <div>
    <table>
      <thead>
        <tr>
          <th>날짜</th>
          <th>방문자수</th>
        </tr>
      </thead>
      <tbody id="visitTableBody">
        {% for row in daily_visits %}
        <tr>
          <td>{{ row["date"] }}</td>
          <td>{{ row["count"] }}</td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
    </div>
    <div id="visitPager" class="pager"></div>
  </div>

<div class="card">
    <h2>일자별 지역 클릭수</h2>
    <div>
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
      <tbody id="regionTableBody">
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
    <div id="regionPager" class="pager"></div>
  </div>


</div>
<script>
function setupPagination(tbodyId, pagerId, rowsPerPage){
  const tbody = document.getElementById(tbodyId);
  const pager = document.getElementById(pagerId);

  if(!tbody || !pager) return;

  const rows = Array.from(tbody.querySelectorAll("tr"));
  const totalPages = Math.ceil(rows.length / rowsPerPage);

  if(totalPages <= 1){
    pager.style.display = "none";
    return;
  }

  let currentPage = 1;

  function renderPage(page){
    currentPage = page;

    rows.forEach(function(row, index){
      const start = (currentPage - 1) * rowsPerPage;
      const end = start + rowsPerPage;
      row.style.display = index >= start && index < end ? "" : "none";
    });

    renderPager();
  }

  function renderPager(){
    pager.innerHTML = "";

    const maxVisible = 5;
    let startPage = Math.max(1, currentPage - 2);
    let endPage = Math.min(totalPages, startPage + maxVisible - 1);

    if(endPage - startPage < maxVisible - 1){
      startPage = Math.max(1, endPage - maxVisible + 1);
    }

    const prevBtn = document.createElement("button");
    prevBtn.type = "button";
    prevBtn.textContent = "‹";
    prevBtn.disabled = currentPage === 1;
    prevBtn.onclick = function(){
      if(currentPage > 1) renderPage(currentPage - 1);
    };
    pager.appendChild(prevBtn);

    for(let i = startPage; i <= endPage; i++){
      const btn = document.createElement("button");
      btn.type = "button";
      btn.textContent = i;
      if(i === currentPage){
        btn.classList.add("active");
      }
      btn.onclick = function(){
        renderPage(i);
      };
      pager.appendChild(btn);
    }

    const nextBtn = document.createElement("button");
    nextBtn.type = "button";
    nextBtn.textContent = "›";
    nextBtn.disabled = currentPage === totalPages;
    nextBtn.onclick = function(){
      if(currentPage < totalPages) renderPage(currentPage + 1);
    };
    pager.appendChild(nextBtn);
  }

  renderPage(1);
}

document.addEventListener("DOMContentLoaded", function(){
  setupPagination("visitTableBody", "visitPager", 10);
  setupPagination("regionTableBody", "regionPager", 10);
});
</script>
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

BOARD_HTML = """
<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>비공개 게시판</title>
<style>
body{
  margin:0;
  background:#f4f6fb;
  font-family:'Pretendard',sans-serif;
  color:#111827;
}
.container{
  max-width:640px;
  margin:0 auto;
  padding:24px 16px 40px 16px;
}
.card{
  background:#fff;
  border-radius:18px;
  padding:22px;
  box-shadow:0 6px 18px rgba(0,0,0,0.06);
}
.top-bar{
  display:flex;
  justify-content:space-between;
  align-items:center;
  margin-bottom:16px;
}

.home-button{
  display:inline-flex;
  align-items:center;
  justify-content:center;
  gap:5px;
  height:34px;
  padding:0 15px;
  border-radius:8px;
  background:#5b7ee5;
  border:none;
  color:#fff;
  text-decoration:none;
  font-size:13px;
  font-weight:500;
  transition:all .15s;
}
.home-button:hover{
  background:#f3f4f6;
  color:#374151;
}
h2{
  margin:0 0 8px 0;
  font-size:22px;
}
.desc{
  margin:0 0 18px 0;
  font-size:13px;
  color:#6b7280;
  line-height:1.6;
}
label{
  display:block;
  margin-top:14px;
  font-size:14px;
  font-weight:700;
}
input, textarea{
  width:100%;
  box-sizing:border-box;
  margin-top:7px;
  border:1px solid #d1d5db;
  border-radius:12px;
  padding:12px;
  font-size:15px;
  font-family:inherit;
}
textarea{
  min-height:180px;
  resize:vertical;
  line-height:1.6;
}
button{
  width:100%;
  height:50px;
  margin-top:18px;
  border:none;
  border-radius:12px;
  background:linear-gradient(135deg,#3b82f6,#2563eb);
  color:white;
  font-size:16px;
  font-weight:800;
  cursor:pointer;
}
.success{
  padding:18px;
  background:#eff6ff;
  border:1px solid #bfdbfe;
  border-radius:14px;
  color:#1d4ed8;
  font-size:15px;
  font-weight:700;
  line-height:1.6;
}
</style>
</head>
<body>
<div class="container">

  <div class="top-bar">
    <a href="/stats" class="home-button">통계로</a>
  </div>

  <div class="card">
    {% if saved %}
      <div class="success">
        의견이 등록되었습니다.<br>
        남겨주신 내용은 관리자만 확인할 수 있습니다.
      </div>
      <a href="/home" class="home-button" style="margin-top:16px;">홈으로 돌아가기</a>
    {% else %}
      <h2>오류제보 / 의견보내기</h2>
      <p class="desc">
        작성하신 내용은 공개되지 않으며 관리자만 확인할 수 있습니다.
      </p>

      <form method="post">
        <label>작성자</label>
        <input type="text" name="writer" placeholder="이름 또는 소속을 입력하세요">

        <label>제목</label>
        <input type="text" name="title" placeholder="제목을 입력하세요" required>

        <label>내용</label>
        <textarea name="content" placeholder="오류 내용이나 의견을 입력하세요" required></textarea>

        <button type="submit">등록하기</button>
      </form>
    {% endif %}
  </div>

</div>
</body>
</html>
"""

BOARD_LIST_HTML = """
<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>비공개 게시판</title>
<style>
body{
  margin:0;
  background:#f4f6fb;
  font-family:'Pretendard',sans-serif;
  color:#111827;
}
.container{
  max-width:760px;
  margin:0 auto;
  padding:24px 16px 40px 16px;
}
.top-bar{
  display:flex;
  justify-content:space-between;
  align-items:center;
  gap:8px;
  flex-wrap:nowrap;
  margin-bottom:18px;
  overflow-x:auto;
  -webkit-overflow-scrolling:touch;
  padding:2px 2px 8px 2px;
}

.top-right-menu{
  display:flex;
  align-items:center;
  gap:6px;
  flex-wrap:nowrap;
  flex-shrink:0;
}
.home-button{
  display:inline-flex !important;
  align-items:center !important;
  justify-content:center !important;
  gap:5px !important;
  height:34px !important;
  padding:0 15px !important;
  border-radius:8px !important;
  background:#ffffff !important;
  border:1px solid #e5e7eb !important;
  color:#6b7280 !important;
  text-decoration:none !important;
  font-size:13px !important;
  font-weight:600 !important;
  box-shadow:0 2px 6px rgba(15,23,42,0.08) !important;
  transition:all .15s !important;
}
.home-button:hover{
  background:#f3f4f6 !important;
  color:#374151 !important;
}
h2{
  margin:0 0 16px 0;
  font-size:24px;
}
.board-card{
  background:#fff;
  border-radius:16px;
  padding:16px 18px;
  margin-bottom:10px;
  box-shadow:0 6px 18px rgba(0,0,0,0.06);
  text-decoration:none;
  color:#111827;
  display:block;
}
.board-title{
  font-size:16px;
  font-weight:800;
  margin-bottom:7px;
}
.board-meta{
  font-size:12px;
  color:#6b7280;
}
.empty{
  background:#fff;
  border-radius:16px;
  padding:24px;
  text-align:center;
  color:#6b7280;
}
</style>
</head>
<body>
<div class="container">

  <div class="top-bar">
    <a href="/home" class="home-button">홈으로</a>
    <a href="/board/write" class="home-button">의견보내기</a>
  </div>

  <h2>오류제보 / 의견게시판</h2>

  {% if posts %}
    {% for post in posts %}
      <a href="/board/view/{{ post['id'] }}" class="board-card">
        <div class="board-title">{{ post["title"] }}</div>
        <div class="board-meta">
          {{ post["created_at"][:19].replace("T", " ") }}
          · 작성자: {{ post["writer"] or "미입력" }}
        </div>
      </a>
    {% endfor %}
  {% else %}
    <div class="empty">등록된 글이 없습니다.</div>
  {% endif %}

</div>
</body>
</html>
"""

BOARD_WRITE_HTML = """
<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>의견보내기</title>
<style>
body{
  margin:0;
  background:#f4f6fb;
  font-family:'Pretendard',sans-serif;
  color:#111827;
}
.container{
  max-width:640px;
  margin:0 auto;
  padding:24px 16px 40px 16px;
}
.card{
  background:#fff;
  border-radius:18px;
  padding:22px;
  box-shadow:0 6px 18px rgba(0,0,0,0.06);
}
.top-bar{
  display:flex;
  justify-content:space-between;
  align-items:center;
  margin-bottom:16px;
}
.home-button{
  display:inline-flex !important;
  align-items:center !important;
  justify-content:center !important;
  height:34px !important;
  padding:0 13px !important;
  border-radius:999px !important;
  background:#ffffff !important;
  border:1px solid #e5e7eb !important;
  color:#6b7280 !important;
  text-decoration:none !important;
  font-size:13px !important;
  font-weight:700 !important;
  box-shadow:0 3px 10px rgba(15,23,42,0.08) !important;
}
h2{
  margin:0 0 8px 0;
  font-size:22px;
}
.desc{
  margin:0 0 18px 0;
  font-size:13px;
  color:#6b7280;
  line-height:1.6;
}
label{
  display:block;
  margin-top:14px;
  font-size:14px;
  font-weight:700;
}
input, textarea{
  width:100%;
  box-sizing:border-box;
  margin-top:7px;
  border:1px solid #d1d5db;
  border-radius:12px;
  padding:12px;
  font-size:15px;
  font-family:inherit;
}
textarea{
  min-height:180px;
  resize:vertical;
  line-height:1.6;
}
button{
  width:100%;
  height:50px;
  margin-top:18px;
  border:none;
  border-radius:12px;
  background:linear-gradient(135deg,#3b82f6,#2563eb);
  color:white;
  font-size:16px;
  font-weight:800;
  cursor:pointer;
}
</style>
</head>
<body>
<div class="container">

  <div class="top-bar">
    <a href="/home" class="home-button">⌂ 홈으로</a>
  </div>

  <div class="card">
    <h2>의견보내기</h2>
    <p class="desc">작성하신 내용은 관리자만 확인할 수 있습니다.</p>

    <form method="post">
      <label>소속기관 <span style="color:#ef4444;">*</span></label>
      <select name="org_type" required style="width:100%;box-sizing:border-box;margin-top:7px;border:1px solid #d1d5db;border-radius:12px;padding:12px;font-size:15px;font-family:inherit;background:#fff;color:#111827;">
        <option value="" disabled selected>소속기관을 선택하세요</option>
        <option value="지자체">지자체</option>
        <option value="공단">공단</option>
      </select>

      <label>작성자</label>
      <input type="text" name="writer" placeholder="이름 또는 소속을 입력하세요">

      <label>제목 <span style="color:#ef4444;">*</span></label>
      <input type="text" name="title" placeholder="제목을 입력하세요" required>

      <label>내용 <span style="color:#ef4444;">*</span></label>
      <textarea name="content" placeholder="오류 내용이나 의견을 입력하세요" required></textarea>

      <label>회신연락처</label>
      <div style="font-size:12px;color:#9ca3af;margin-top:2px;margin-bottom:4px;">회신이 필요한 경우만 작성해주세요</div>
      <input type="text" name="reply_contact" placeholder="이메일 또는 전화번호">

      <button type="submit">등록하기</button>
    </form>
  </div>

</div>
</body>
</html>
"""
BOARD_SUCCESS_HTML = """
<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>등록 완료</title>
<style>
body{
  margin:0;
  background:#f4f6fb;
  font-family:'Pretendard',sans-serif;
  color:#111827;
}
.container{
  max-width:640px;
  margin:0 auto;
  padding:24px 16px 40px 16px;
}
.card{
  background:#fff;
  border-radius:18px;
  padding:24px;
  box-shadow:0 6px 18px rgba(0,0,0,0.06);
}
.success{
  padding:18px;
  background:#eff6ff;
  border:1px solid #bfdbfe;
  border-radius:14px;
  color:#1d4ed8;
  font-size:15px;
  font-weight:700;
  line-height:1.6;
}
.home-button{
  display:inline-flex !important;
  align-items:center !important;
  justify-content:center !important;
  gap:5px !important;
  height:34px !important;
  padding:0 15px !important;
  margin-top:16px;
  border-radius:8px !important;
  background:#ffffff !important;
  border:1px solid #e5e7eb !important;
  color:#6b7280 !important;
  text-decoration:none !important;
  font-size:13px !important;
  font-weight:600 !important;
  box-shadow:0 2px 6px rgba(15,23,42,0.08) !important;
  transition:all .15s !important;
}
</style>
</head>
<body>
<div class="container">
  <div class="card">
    <div class="success">
      의견이 등록되었습니다.<br>
      남겨주신 내용은 관리자만 확인할 수 있습니다.
    </div>
    <a href="/home" class="home-button">⌂ 홈으로</a>
  </div>
</div>
</body>
</html>
"""



BOARD_VIEW_HTML = """
<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>게시글 보기</title>
<style>
body{
  margin:0;
  background:#f4f6fb;
  font-family:'Pretendard',sans-serif;
  color:#111827;
}
.container{
  max-width:760px;
  margin:0 auto;
  padding:24px 16px 40px 16px;
}
.top-bar{
  display:flex;
  justify-content:space-between;
  align-items:center;
  gap:8px;
  flex-wrap:nowrap;
  margin-bottom:18px;
  overflow-x:auto;
  -webkit-overflow-scrolling:touch;
  padding:2px 2px 8px 2px;
}

.top-right-menu{
  display:flex;
  align-items:center;
  gap:6px;
  flex-wrap:nowrap;
  flex-shrink:0;
}
.home-button{
  display:inline-flex !important;
  align-items:center !important;
  justify-content:center !important;
  height:34px !important;
  padding:0 13px !important;
  border-radius:999px !important;
  background:#ffffff !important;
  border:1px solid #e5e7eb !important;
  color:#6b7280 !important;
  text-decoration:none !important;
  font-size:13px !important;
  font-weight:700 !important;
  box-shadow:0 3px 10px rgba(15,23,42,0.08) !important;
}
.card{
  background:#fff;
  border-radius:18px;
  padding:22px;
  box-shadow:0 6px 18px rgba(0,0,0,0.06);
}
.title{
  font-size:22px;
  font-weight:900;
  margin-bottom:10px;
}
.meta{
  font-size:12px;
  color:#6b7280;
  margin-bottom:18px;
}
.content{
  font-size:15px;
  line-height:1.8;
  white-space:pre-wrap;
  word-break:break-word;
  overflow-wrap:anywhere;
}

</style>
</head>
<body>
<div class="container">

  <div class="top-bar">
    <a href="/board/admin" class="home-button">목록으로</a>
  </div>

  <div class="card">
    <div class="title">{{ post["title"] }}</div>
    <div class="meta">
      {{ post["created_at"][:19].replace("T", " ") }}
      · 작성자: {{ post["writer"] or "미입력" }}
    </div>
    <div class="content">{{ post["content"] }}</div>
  </div>

</div>
</body>
</html>
"""

BOARD_ADMIN_HTML = """
<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>게시판 관리자</title>
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
  justify-content:flex-start;
  align-items:center;
  margin-bottom:16px;
}
.home-button{
  display:inline-flex !important;
  align-items:center !important;
  justify-content:center !important;
  height:34px !important;
  padding:0 13px !important;
  border-radius:999px !important;
  background:#ffffff !important;
  border:1px solid #e5e7eb !important;
  color:#6b7280 !important;
  text-decoration:none !important;
  font-size:13px !important;
  font-weight:700 !important;
  box-shadow:0 3px 10px rgba(15,23,42,0.08) !important;
}
.card{
  background:#fff;
  border-radius:16px;
  padding:18px;
  margin-bottom:14px;
  box-shadow:0 6px 18px rgba(0,0,0,0.06);
  cursor:pointer;
}
.meta{
  font-size:12px;
  color:#6b7280;
  margin-bottom:8px;
}
.title{
  font-size:17px;
  font-weight:800;
  margin-bottom:10px;
}
.content{
  font-size:14px;
  line-height:1.7;
  word-break:keep-all;
  margin-bottom:14px;

  display:-webkit-box;
  -webkit-line-clamp:2;
  -webkit-box-orient:vertical;
  overflow:hidden;
  text-overflow:ellipsis;
  white-space:normal;
}
.delete-btn{
  display:inline-flex;
  align-items:center;
  justify-content:center;
  height:32px;
  padding:0 12px;
  border:none;
  border-radius:999px;
  background:#fee2e2;
  color:#b91c1c;
  font-size:13px;
  font-weight:800;
  cursor:pointer;
}
.empty{
  background:#fff;
  border-radius:16px;
  padding:22px;
  color:#6b7280;
  text-align:center;
}
</style>
</head>
<body>
<div class="container">

  <div class="top-bar">
    <a href="/stats" class="home-button">통계로</a>
  </div>

  <h2>비공개 게시판 관리</h2>

  {% if posts %}
    {% for post in posts %}
    <div class="card" onclick="location.href='/board/admin/view/{{ post['id'] }}'">
      <div class="meta">
        {{ post["created_at"][:19].replace("T", " ") }}
        · 작성자: {{ post["writer"] or "미입력" }}
        {% if post.get("org_type") %} · 소속: {{ post["org_type"] }}{% endif %}
        {% if post.get("reply_contact") %}<br>회신연락처: {{ post["reply_contact"] }}{% endif %}
      </div>
      <div class="title">{{ post["title"] }}</div>
      <div class="content">{{ post["content"] }}</div>

      <form method="post" action="/board/delete/{{ post['id'] }}" onclick="event.stopPropagation();" onsubmit="return confirm('이 글을 삭제할까요?');">
        <button type="submit" class="delete-btn">삭제</button>
      </form>
    </div>
    {% endfor %}
  {% else %}
    <div class="empty">등록된 글이 없습니다.</div>
  {% endif %}

</div>
</body>
</html>
"""


@app.route("/board")
def board():
    return redirect(url_for("board_write"))

@app.route("/board/write", methods=["GET", "POST"])
def board_write():
    if request.method == "POST":
        writer = (request.form.get("writer", "") or "").strip()
        title = (request.form.get("title", "") or "").strip()
        content = (request.form.get("content", "") or "").strip()
        org_type = (request.form.get("org_type", "") or "").strip()
        reply_contact = (request.form.get("reply_contact", "") or "").strip()

        if title and content and org_type:
            if os.getenv("RENDER") is not None:
                requests.post(
                    f"{SUPABASE_URL}/rest/v1/board_posts",
                    headers=SUPABASE_HEADERS,
                    json={
                        "writer": writer,
                        "title": title,
                        "content": content,
                        "org_type": org_type,
                        "reply_contact": reply_contact,
                        "ip": request.remote_addr
                    }
                )

        return render_template_string(BOARD_SUCCESS_HTML)

    return render_template_string(BOARD_WRITE_HTML)

@app.route("/board/view/<int:post_id>")
def board_view(post_id):
    return redirect(url_for("board"))

@app.route("/board/admin")
def board_admin():
    posts = []

    if os.getenv("RENDER") is not None:
        res = requests.get(
            f"{SUPABASE_URL}/rest/v1/board_posts?select=*&is_deleted=eq.false&order=created_at.desc",
            headers=SUPABASE_HEADERS
        )
        posts = res.json() if res.ok else []
    else:
        posts = [
            {
                "id": 1,
                "created_at": "2026-05-17T00:00:00",
                "writer": "테스트",
                "title": "로컬 테스트 글",
                "content": "Render 환경에서는 Supabase에 저장됩니다."
            }
        ]

    return render_template_string(BOARD_ADMIN_HTML, posts=posts)


@app.route("/board/admin/view/<int:post_id>")
def board_admin_view(post_id):
    if not session.get("is_admin"):
        return redirect(url_for("admin_login"))

    post = None

    if os.getenv("RENDER") is not None:
        res = requests.get(
            f"{SUPABASE_URL}/rest/v1/board_posts?select=*&id=eq.{post_id}&is_deleted=eq.false",
            headers=SUPABASE_HEADERS
        )
        rows = res.json() if res.ok else []
        post = rows[0] if rows else None
    else:
        post = {
            "id": 1,
            "created_at": "2026-05-17T00:00:00",
            "writer": "테스트",
            "title": "로컬 테스트 글",
            "content": "Render 환경에서는 Supabase에 저장됩니다."
        }

    if not post:
        return redirect(url_for("board_admin"))

    return render_template_string(BOARD_VIEW_HTML, post=post)

@app.route("/board/delete/<int:post_id>", methods=["POST"])
def board_delete(post_id):
    if not session.get("is_admin"):
        return redirect(url_for("admin_login"))

    if os.getenv("RENDER") is not None:
        requests.patch(
            f"{SUPABASE_URL}/rest/v1/board_posts?id=eq.{post_id}",
            headers=SUPABASE_HEADERS,
            json={
                "is_deleted": True
            }
        )

    return redirect(url_for("board_admin"))

# =========================
# 공지사항 관리 (관리자 전용)
# =========================
NOTICE_ADMIN_HTML = """
<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>공지사항 관리</title>
<style>
body{ margin:0; background:#f4f6fb; font-family:'Pretendard',sans-serif; color:#111827; }
.container{ max-width:640px; margin:0 auto; padding:24px 16px 40px 16px; }
.top-bar{ display:flex; justify-content:space-between; align-items:center; margin-bottom:16px; gap:10px; }
.home-button{ display:inline-flex;align-items:center;justify-content:center;height:34px;padding:0 13px;border-radius:999px;background:#fff;border:1px solid #e5e7eb;color:#6b7280;text-decoration:none;font-size:13px;font-weight:700;box-shadow:0 3px 10px rgba(15,23,42,0.08); }
h2{ margin:0 0 16px 0; font-size:20px; }
.card{ background:#fff; border-radius:16px; padding:18px; margin-bottom:12px; box-shadow:0 4px 12px rgba(0,0,0,0.06); }
.card .meta{ font-size:11px; color:#9ca3af; margin-bottom:4px; }
.card .title{ font-size:15px; font-weight:700; margin-bottom:4px; }
.card .content{ font-size:13px; color:#4b5563; line-height:1.6; white-space:pre-line; word-break:keep-all; }
.status{ display:inline-block; font-size:11px; padding:2px 8px; border-radius:6px; font-weight:600; margin-top:6px; }
.status-active{ background:#dcfce7; color:#166534; }
.status-inactive{ background:#f3f4f6; color:#6b7280; }
.btn-row{ display:flex; gap:6px; margin-top:10px; }
.btn-sm{ height:30px; padding:0 12px; border:none; border-radius:8px; font-size:12px; font-weight:700; cursor:pointer; }
.btn-del{ background:#fee2e2; color:#991b1b; }
.btn-toggle{ background:#e0e7ff; color:#3730a3; }
.write-card{ background:#fff; border-radius:16px; padding:22px; box-shadow:0 6px 18px rgba(0,0,0,0.06); margin-bottom:20px; }
.write-card h3{ margin:0 0 14px 0; font-size:16px; font-weight:800; }
.write-card label{ display:block; margin-top:10px; font-size:13px; font-weight:700; }
.write-card input,.write-card textarea{ width:100%; box-sizing:border-box; margin-top:5px; border:1px solid #d1d5db; border-radius:10px; padding:10px 12px; font-size:14px; font-family:inherit; }
.write-card textarea{ min-height:100px; resize:vertical; line-height:1.6; }
.write-card button{ margin-top:14px; width:100%; height:42px; border:none; border-radius:10px; background:#2563eb; color:#fff; font-size:14px; font-weight:700; cursor:pointer; }
.empty{ background:#fff; border-radius:16px; padding:22px; color:#9ca3af; text-align:center; font-size:13px; }
</style>
</head>
<body>
<div class="container">
  <div class="top-bar">
    <a href="/stats" class="home-button">통계로</a>
  </div>
  <h2>공지사항 관리</h2>
  <div class="write-card">
    <h3>새 공지 작성</h3>
    <form method="post" action="/notice/admin/write">
      <label>제목</label>
      <input type="text" name="title" placeholder="공지 제목" required>
      <label>내용</label>
      <textarea name="content" placeholder="공지 내용을 입력하세요" required></textarea>
      <button type="submit">등록하기</button>
    </form>
  </div>
  {% if notices %}
    {% for n in notices %}
    <div class="card">
      <div class="meta">{{ n.created_datetime }}</div>
      <div class="title">{{ n.title }}</div>
      <div class="content">{{ n.content }}</div>
      <span class="status {% if n.is_active %}status-active{% else %}status-inactive{% endif %}">
        {% if n.is_active %}게시중{% else %}숨김{% endif %}
      </span>
      <div class="btn-row">
        <form method="post" action="/notice/admin/toggle/{{ n.id }}">
          <button type="submit" class="btn-sm btn-toggle">{% if n.is_active %}숨기기{% else %}게시하기{% endif %}</button>
        </form>
        <form method="post" action="/notice/admin/delete/{{ n.id }}" onsubmit="return confirm('삭제할까요?');">
          <button type="submit" class="btn-sm btn-del">삭제</button>
        </form>
      </div>
    </div>
    {% endfor %}
  {% else %}
    <div class="empty">등록된 공지가 없습니다.</div>
  {% endif %}
</div>
</body>
</html>
"""

@app.route("/notice/admin")
def notice_admin():
    if not session.get("is_admin"):
        return redirect(url_for("admin_login"))
    notices = []
    if os.getenv("RENDER") is not None:
        res = requests.get(
            f"{SUPABASE_URL}/rest/v1/notices?select=*&order=created_at.desc",
            headers=SUPABASE_HEADERS
        )
        if res.ok:
            notices = res.json()
    else:
        notices = [{"id":1,"title":"테스트 공지","content":"로컬 테스트","created_at":"2026-06-04T00:00:00","is_active":True}]
    notices = clean_notices_for_template(notices)
    return render_template_string(NOTICE_ADMIN_HTML, notices=notices)

@app.route("/notice/admin/write", methods=["POST"])
def notice_admin_write():
    if not session.get("is_admin"):
        return redirect(url_for("admin_login"))
    title = (request.form.get("title","") or "").strip()
    content = (request.form.get("content","") or "").strip()
    if title and content and os.getenv("RENDER") is not None:
        try:
            now = datetime.datetime.now(ZoneInfo("Asia/Seoul")).isoformat()
            res = requests.post(
                f"{SUPABASE_URL}/rest/v1/notices",
                headers=SUPABASE_HEADERS,
                json={"title": title, "content": content, "is_active": True, "created_at": now}
            )
            if not res.ok:
                app.logger.error("notice insert failed: %s %s", res.status_code, res.text)
        except Exception as e:
            app.logger.exception(e)
    return redirect(url_for("notice_admin"))

@app.route("/notice/admin/toggle/<int:notice_id>", methods=["POST"])
def notice_admin_toggle(notice_id):
    if not session.get("is_admin"):
        return redirect(url_for("admin_login"))
    if os.getenv("RENDER") is not None:
        res = requests.get(
            f"{SUPABASE_URL}/rest/v1/notices?id=eq.{notice_id}&select=is_active",
            headers=SUPABASE_HEADERS
        )
        if res.ok and res.json():
            current = res.json()[0].get("is_active", True)
            requests.patch(
                f"{SUPABASE_URL}/rest/v1/notices?id=eq.{notice_id}",
                headers=SUPABASE_HEADERS,
                json={"is_active": not current}
            )
    return redirect(url_for("notice_admin"))

@app.route("/notice/admin/delete/<int:notice_id>", methods=["POST"])
def notice_admin_delete(notice_id):
    if not session.get("is_admin"):
        return redirect(url_for("admin_login"))
    if os.getenv("RENDER") is not None:
        requests.delete(
            f"{SUPABASE_URL}/rest/v1/notices?id=eq.{notice_id}",
            headers=SUPABASE_HEADERS
        )
    return redirect(url_for("notice_admin"))


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

    program_name = str(r.get("프로그램명(사업명)", "")).strip()
    org_name = str(r.get("서비스제공기관명", "")).strip()

    service_price = str(r.get("서비스단가", "")).strip()
    service_content = str(r.get("주요내용", "")).strip()
    service_target = str(r.get("지원대상", "")).strip()

    return jsonify({
        "프로그램명칭": program_name,
        "서비스제공기관명": org_name,
        "기관연락처": str(r.get("기관연락처", "")),
        "기관주소": str(r.get("기관주소", "")),
        "기타": "",
        "서비스단가": service_price,
        "주요내용": service_content,
        "대상": service_target,
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
<title>통합돌봄 서비스 기관 찾기</title>
<style>
*{ box-sizing:border-box; margin:0; padding:0; }
body{ background:#f4f6fb; font-family:'Pretendard',sans-serif; color:#111827; font-size:13px; }
.page-wrap{ max-width:860px; margin:0 auto; padding:20px 16px 60px 16px; min-width:0; word-break:keep-all; }

/* ── 상단 바 ── */
.top-bar{ display:flex; justify-content:space-between; align-items:center; margin-bottom:14px; gap:10px; flex-wrap:wrap; padding:6px 0; }
.bottom-action-bar{ margin-top:20px; margin-bottom:0; }
.home-btn{ display:inline-flex; align-items:center; justify-content:center; gap:5px; height:34px; padding:0 15px; border-radius:8px; background:#ffffff; border:1px solid #e5e7eb; color:#6b7280; text-decoration:none; font-size:13px; font-weight:600; box-shadow:0 2px 6px rgba(15,23,42,0.08); transition:all .15s; }
.home-btn:hover{ background:#f3f4f6; color:#374151; }
.btn-group{ display:flex; gap:10px; }
.reset-btn{ display:inline-flex; align-items:center; justify-content:center; gap:5px; height:34px; padding:0 15px; border-radius:8px; background:#ffffff; border:1px solid #e5e7eb; color:#6b7280; font-size:13px; font-weight:600; cursor:pointer; box-shadow:0 2px 6px rgba(15,23,42,0.08); transition:all .15s; }
.reset-btn:hover{ background:#f3f4f6; color:#374151; }

/* ── 폼 카드 ── */
.form-card{ background:#fff; border-radius:16px; padding:28px 24px; box-shadow:0 6px 18px rgba(0,0,0,0.07); overflow-x:auto; }
.form-title{ text-align:left; font-size:18px; font-weight:900; margin-bottom:20px; letter-spacing:-0.3px; border:none; border-left:5px solid #5b7ee5; padding:6px 0 6px 14px; color:#2d3a6e; }
.section-header{ background:#5b7ee5; color:#fff; font-size:13px; font-weight:700; padding:6px 10px; border-radius:4px; margin:18px 0 8px 0; }
.section-header:first-of-type{ margin-top:0; }

/* ── 폼 입력 ── */
label.field-label{ display:block; margin-top:12px; font-size:13px; font-weight:700; color:#374151; margin-bottom:4px; }
label.field-label:first-of-type{ margin-top:8px; }
.field-select, .field-input{
  width:100%; padding:10px 12px; border-radius:8px; border:1px solid #d1d5db; font-size:14px; font-family:inherit; background:#fff; color:#111827; outline:none; box-sizing:border-box;
}
.field-select:focus, .field-input:focus{ border-color:#5b7ee5; box-shadow:0 0 0 2px rgba(75,110,220,0.15); }
.section-desc{ font-size:12px; color:#6b7280; margin-bottom:6px; line-height:1.5; }

/* ── 검색 버튼 ── */
.submit-btn{ margin-top:18px; width:100%; height:44px; border:none; border-radius:10px; background:#5b7ee5; color:#fff; font-size:14px; font-weight:700; cursor:pointer; box-shadow:0 2px 8px rgba(75,110,220,0.25); transition:all .15s; }
.submit-btn:hover{ background:#4a6cd4; transform:translateY(-1px); }

/* ── 결과 영역 ── */
.result-card{ margin-top:18px; background:#fff; border-radius:16px; padding:22px 20px; box-shadow:0 6px 18px rgba(0,0,0,0.07); }
.result-card h3{ margin:18px 0 8px 0; font-size:16px; font-weight:800; color:#111827; }
.result-card h3:first-child{ margin-top:0; }
.result-count{ font-size:14px; font-weight:700; margin-bottom:12px; }

.combo-warning{ margin:10px 0 14px 0; padding:12px 16px; border-radius:10px; background:#eef2ff; border:1px solid #c7d2fe; color:#3b5cc0; font-size:13px; line-height:1.65; display:flex; align-items:flex-start; gap:8px; }

.manager-badge{ display:inline-block; padding:4px 12px; border-radius:999px; background:#e0e7ff; color:#3b5cc0; font-size:12px; font-weight:900; letter-spacing:0.3px; margin:14px 0 8px 0; }
.manager-badge[data-type="공단"]{ background:#fce7f3; color:#be185d; }

.item{ display:flex; align-items:flex-start; gap:6px; padding:7px 0; cursor:pointer; line-height:1.6; color:#111827; font-size:13px; }
.item:hover{ color:#5b7ee5; }
.item-bullet{ flex:0 0 auto; }
.item-text{ flex:1; min-width:0; white-space:normal; word-break:keep-all; overflow-wrap:break-word; }

/* ── 모달 ── */
.modal-overlay{ display:none; position:fixed; top:0; left:0; width:100%; height:100%; background:rgba(0,0,0,.5); z-index:999; }
.modal-box{ background:white; margin:0 auto; padding:20px; width:90%; max-width:520px; border-radius:14px; max-height:85vh; overflow-y:auto; -webkit-overflow-scrolling:touch; position:relative; top:8%; overscroll-behavior:contain; }

/* PC 화면에서는 팝업을 더 크게 (지도 등이 시원하게 보이도록) */
@media (min-width:768px){
  .modal-box{ max-width:760px; padding:24px 28px; }
  /* 기관 상세 지도 iframe 도 PC 에서 세로로 더 크게 */
  #m_map{ height:260px !important; }
}
.modal-box h3{ margin-top:0; margin-bottom:12px; font-size:16px; }
.modal-box p{ margin:0 0 10px 0; line-height:1.6; font-size:13px; }
.m-acc-row{ display:flex; gap:6px; margin:2px 0 0; }
.m-acc-btn{ flex:1; display:flex; align-items:center; justify-content:center; gap:4px; min-width:0; padding:9px 6px; border:1px solid #e3e7ef; border-radius:8px; background:#f7f8fb; color:#333; font-size:12px; font-weight:700; white-space:nowrap; cursor:pointer; }
.m-acc-btn:hover{ background:#eef1f6; }
.m-acc-btn.open{ background:#eef2ff; border-color:#c7d4f5; color:#4a6cd4; }
.m-acc-ico{ flex:none; transition:transform .15s; color:#9aa1b0; }
.m-acc-btn.open .m-acc-ico{ transform:rotate(180deg); color:#5b7ee5; }
.m-acc-body{ display:none; margin-top:8px; padding:9px 12px; border:1px solid #e3e7ef; border-radius:8px; background:#fafbfc; font-size:13px; line-height:1.6; color:#333; word-break:keep-all; }
.modal-btn{ margin-top:14px; width:100%; height:44px; border:none; border-radius:10px; background:#5b7ee5; color:#fff; font-size:14px; font-weight:700; cursor:pointer; }
.modal-btn:hover{ background:#4a6cd4; }

/* ── 카피라이트 ── */
.copyright{ text-align:right; margin-top:22px; margin-bottom:6px; padding:0 12px; }
.copyright-line{ width:44px; height:2px; margin:0 0 12px auto; border-radius:999px; background:linear-gradient(135deg,#a5b4fc,#5b7ee5); opacity:0.9; }
.copyright-main{ font-size:12.5px; color:#9ca3af; line-height:1.5; font-weight:500; word-break:keep-all; letter-spacing:0.2px; }
.copyright-sub{ margin-top:4px; font-size:15px; color:#374151; font-weight:600; letter-spacing:-0.2px; }
.copyright-sub span{ color:#5b7ee5; font-weight:800; }

@media (min-width:768px){
  #tel_link{ display:none !important; }
}

/* ── 인쇄 ── */
@media print{
  body{ background:white; }
  .top-bar{ display:none !important; }
  .page-wrap{ padding:0; }
  .form-card,.result-card{ box-shadow:none; border-radius:0; padding:10px; }
}

/* ── 모바일 ── */
@media (max-width:600px){
  .page-wrap{ padding:10px 6px 60px 6px; }
  .form-card{ padding:14px 10px; }
  .result-card{ padding:14px 10px; }
  .form-title{ font-size:14px; padding:4px 0 4px 12px; }
  .top-bar{ flex-wrap:wrap; gap:6px; }
  .home-btn,.reset-btn{ height:30px; font-size:11.5px; padding:0 10px; }
  .section-header{ font-size:11.5px; padding:5px 8px; }
  .field-select,.field-input{ height:42px; font-size:14px; }
  .combo-warning{ font-size:12px; line-height:1.6; padding:10px 12px; }
  .copyright{ margin-top:18px; margin-bottom:4px; padding:0 8px; }
  .copyright-line{ margin-bottom:10px; }
  .copyright-main{ font-size:11.5px; line-height:1.45; }
  .copyright-sub{ margin-top:3px; font-size:13px; }
}
</style>
</head>
<body>
<div class="page-wrap">

  <div class="top-bar">
    <a href="/home" class="home-btn">&#8962; 홈으로</a>
    <div class="btn-group">
      <button type="button" class="reset-btn" onclick="resetDescPage()">&#8635; 다시 입력</button>
    </div>
  </div>


  <div class="form-card">
    <div class="form-title" style="display:flex;align-items:center;justify-content:space-between;">
      <span>통합돌봄 서비스 기관 찾기</span>
      <button type="button" onclick="openComboInfo()" style="width:28px;height:28px;border-radius:50%;border:none;background:#2563eb;color:#fff;font-size:15px;font-weight:900;cursor:pointer;display:inline-flex;align-items:center;justify-content:center;box-shadow:0 2px 6px rgba(37,99,235,0.3);flex-shrink:0;margin-right:4px;" aria-label="안내">!</button>
    </div>

    <form method="post">
    <input type="hidden" name="action" id="comboAction" value="">

    <div id="cgt-region">
    <div class="section-header">&#9632; 지역 조건</div>
    <div class="section-desc">시도와 시군구를 선택하여 지역 기준으로 검색합니다.</div>

    <label class="field-label">시도</label>
    <select name="sido" class="field-select" onchange="handleSidoChange(this.form)">
      <option value="">전체</option>
      {% if sido and sido not in sido_options %}
      <option value="{{sido}}" selected>{{sido}}</option>
      {% endif %}
      {% for s in sido_options %}
      <option value="{{s}}" {% if s==sido %}selected{% endif %}>{{s}}</option>
      {% endfor %}
    </select>

    <label class="field-label">시군구</label>
    <select name="sigungu" class="field-select">
      <option value="">전체</option>
      {% for g in sigungu_options %}
      <option value="{{g}}" {% if g==sigungu %}selected{% endif %}>{{g}}</option>
      {% endfor %}
    </select>
    </div>

    <div id="cgt-detail">
    <div class="section-header" style="margin-top:22px;">&#9632; 상세 조건</div>
    <div class="section-desc">대분류와 중분류(선택형), 프로그램과 기관명(서술형)으로 검색합니다.</div>

    <label class="field-label">대분류</label>
    <select name="main_category" class="field-select" onchange="handleMainCategoryChange(this.form)">
      <option value="">전체</option>
      {% if main_category and main_category not in main_category_options %}
      <option value="{{main_category}}" selected>{{main_category}}</option>
      {% endif %}
      {% for c in main_category_options %}
      <option value="{{c}}" {% if c==main_category %}selected{% endif %}>{{c}}</option>
      {% endfor %}
    </select>

    <label class="field-label">중분류</label>
    <select name="middle_category" class="field-select">
      <option value="">전체</option>
      {% if middle_category and middle_category not in middle_category_options %}
      <option value="{{middle_category}}" selected>{{middle_category}}</option>
      {% endif %}
      {% for c in middle_category_options %}
      <option value="{{c}}" {% if c==middle_category %}selected{% endif %}>{{c}}</option>
      {% endfor %}
    </select>

    <label class="field-label">관리주체</label>
    <select name="manager" class="field-select">
      <option value="">전체</option>
      {% for m in manager_options %}
      <option value="{{m}}" {% if m==manager %}selected{% endif %}>{{m}}</option>
      {% endfor %}
    </select>

    <label class="field-label">프로그램</label>
    <input type="text" name="program_kw" class="field-input" value="{{program_kw}}" placeholder="프로그램명 포함 검색">

    <label class="field-label">기관명</label>
    <input type="text" name="org_kw" class="field-input" value="{{org_kw}}" placeholder="기관명 포함 검색">
    </div>

    <button type="submit" class="submit-btn" onclick="return setSearchAction()">검색하기</button>

    </form>
  </div>

  {% if show_results %}
  <div class="result-card" id="desc-result">

    <p class="result-count">총 {{count}}건이 조회되었습니다.</p>

    <div class="combo-warning">
      <span style="flex:0 0 auto;">&#9888;&#65039;</span>
      <div style="flex:1; word-break:keep-all;">
        서비스 제공기관 정보는 현재 운영 중인 기관이며,
        실제 정보와 차이가 있을 수 있으니 정확한 사항은 해당 기관에 직접 확인하시기 바랍니다.
      </div>
    </div>

    {% if count == 0 %}
    <p style="color:#6b7280;">조건에 맞는 서비스가 없습니다.</p>
    {% endif %}

    {% for region, manager_groups in results.items() %}
    <h3>&#128205; {{region}}</h3>

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

<!-- 기관찾기 안내 모달 -->
<div id="comboInfoModal" style="display:none;position:fixed;inset:0;background:rgba(15,23,42,0.45);z-index:99999;align-items:center;justify-content:center;padding:20px;">
  <div style="width:100%;max-width:400px;background:#fff;border-radius:18px;box-shadow:0 20px 50px rgba(15,23,42,0.22);overflow:hidden;" onclick="event.stopPropagation()">
    <div style="padding:20px 22px 10px 22px;border-bottom:1px solid #f3f4f6;">
      <div style="display:flex;align-items:center;gap:8px;">
        <span style="width:28px;height:28px;border-radius:50%;background:#eff6ff;display:inline-flex;align-items:center;justify-content:center;font-size:14px;font-weight:900;color:#2563eb;">!</span>
        <span style="font-size:16px;font-weight:800;color:#111827;">서비스 자원 안내</span>
      </div>
    </div>
    <div style="padding:18px 22px;font-size:13.5px;line-height:1.75;color:#374151;word-break:keep-all;">
      본 서비스 자원 데이터는 <b>지자체 현행화 자료</b> 및 <b>통합돌봄 전용누리집의 서비스 메뉴판</b>을 기준으로 제작되었습니다.<br><br>
      조회 시기에 따라 <b>실제 운영 기관과 차이</b>가 있을 수 있으므로, 정확한 서비스 운영 여부는 해당 기관에 직접 확인하시기 바랍니다.
    </div>
    <div style="padding:10px 22px 20px 22px;">
      <button type="button" onclick="closeComboInfo()" style="width:100%;height:42px;border:none;border-radius:10px;background:#2563eb;color:#fff;font-size:14px;font-weight:700;cursor:pointer;">확인</button>
    </div>
  </div>
</div>

<!-- 상세 모달 -->
<div id="modal" class="modal-overlay">
  <div class="modal-box">
    <h3 id="m_title"></h3>
    <p style="margin:0 0 10px 0; line-height:1.6;">
      <b>기관명:</b> <span id="m_org" style="white-space:normal; word-break:keep-all;"></span>
    </p>
    <p>
      <b>기관 연락처:</b> <span id="m_tel"></span>
      <a id="tel_link" style="display:none; font-size:20px; margin-left:8px; text-decoration:none;">&#128222;</a>
    </p>
    <p><b>기관주소:</b> <span id="m_addr"></span></p>
    <div class="m-acc-row">
      <button type="button" id="m_target_row" class="m-acc-btn" style="display:none;" onclick="toggleAcc('m_target_row','m_target_wrap')"><span>대상</span><svg class="m-acc-ico" viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M6 9l6 6 6-6"/></svg></button>
      <button type="button" id="m_content_row" class="m-acc-btn" style="display:none;" onclick="toggleAcc('m_content_row','m_content_wrap')"><span>주요내용</span><svg class="m-acc-ico" viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M6 9l6 6 6-6"/></svg></button>
      <button type="button" id="m_price_row" class="m-acc-btn" style="display:none;" onclick="toggleAcc('m_price_row','m_price_wrap')"><span>서비스단가</span><svg class="m-acc-ico" viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M6 9l6 6 6-6"/></svg></button>
    </div>
    <div class="m-acc-body" id="m_target_wrap"><span id="m_target"></span></div>
    <div class="m-acc-body" id="m_content_wrap"><span id="m_content"></span></div>
    <div class="m-acc-body" id="m_price_wrap"><span id="m_price"></span></div>
    <iframe id="m_map" width="100%" height="170" style="border:0;margin-top:10px;display:none;border-radius:8px;"></iframe>
    <button onclick="closeModal()" class="modal-btn">닫기</button>
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
      const priceRow = document.getElementById("m_price_row");
      const contentRow = document.getElementById("m_content_row");
      const targetRow = document.getElementById("m_target_row");

      const price = d["서비스단가"] || "";
      const content = d["주요내용"] || "";
      const target = d["대상"] || "";

      document.getElementById("m_price").innerText = price;
      document.getElementById("m_content").innerText = content;
      document.getElementById("m_target").innerText = target;

      priceRow.style.display = price ? "flex" : "none";
      contentRow.style.display = content ? "flex" : "none";
      targetRow.style.display = target ? "flex" : "none";

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
      document.body.style.overflow = "hidden";
      resetAccAll();
    });
}

var ACC_PAIRS = [["m_target_row","m_target_wrap"],["m_content_row","m_content_wrap"],["m_price_row","m_price_wrap"]];

function resetAccAll(){
  ACC_PAIRS.forEach(function(pair){
    var btn = document.getElementById(pair[0]);
    var body = document.getElementById(pair[1]);
    if(btn) btn.classList.remove("open");
    if(body) body.style.display = "none";
  });
}

function toggleAcc(btnId, bodyId){
  var btn = document.getElementById(btnId);
  var body = document.getElementById(bodyId);
  if(!btn || !body) return;
  var willOpen = body.style.display !== "block";
  resetAccAll();
  if(willOpen){
    body.style.display = "block";
    btn.classList.add("open");
  }
}

function closeModal(){
  document.getElementById("modal").style.display = "none";
  document.body.style.overflow = "";
}

function handleSidoChange(form){
  form.sigungu.value = "";
  document.getElementById("comboAction").value = "change_sido";
  form.submit();
}

function handleMainCategoryChange(form){
  form.middle_category.value = "";
  document.getElementById("comboAction").value = "change_main_category";
  form.submit();
}

function setSearchAction(){
  var f = document.querySelector('form');
  var sido = f.sido.value;
  var sigungu = f.sigungu.value;
  var main_cat = f.main_category.value;
  var mid_cat = f.middle_category.value;
  var mgr = f.manager.value;
  var prog = f.program_kw.value.trim();
  var org = f.org_kw.value.trim();
  if(!sido && !sigungu && !main_cat && !mid_cat && !mgr && !prog && !org){
    showComboValidationAlert();
    return false;
  }
  document.getElementById("comboAction").value = "search";
  return true;
}

function showComboValidationAlert(){
  var existing = document.getElementById('comboValidationModal');
  if(existing) existing.remove();
  var overlay = document.createElement('div');
  overlay.id = 'comboValidationModal';
  overlay.style.cssText = 'position:fixed;inset:0;background:rgba(15,23,42,0.45);z-index:99999;display:flex;align-items:center;justify-content:center;padding:20px;';
  var box = document.createElement('div');
  box.style.cssText = 'width:100%;max-width:360px;background:#fff;border-radius:18px;box-shadow:0 20px 50px rgba(15,23,42,0.22);overflow:hidden;text-align:center;';
  box.innerHTML =
    '<div style="padding:28px 24px 12px 24px;">' +
      '<div style="font-size:36px;margin-bottom:10px;">&#9888;&#65039;</div>' +
      '<div style="font-size:16px;font-weight:800;color:#111827;margin-bottom:8px;">검색 조건을 입력해주세요</div>' +
      '<div style="font-size:13px;color:#6b7280;line-height:1.6;">최소 하나 이상의 조건을 선택하거나<br>입력한 후 검색해주세요.</div>' +
    '</div>' +
    '<div style="padding:16px 24px 22px 24px;">' +
      '<button type="button" id="comboValidCloseBtn" style="width:100%;height:42px;border:none;border-radius:10px;background:#5b7ee5;color:#fff;font-size:14px;font-weight:700;cursor:pointer;">확인</button>' +
    '</div>';
  overlay.appendChild(box);
  document.body.appendChild(overlay);
  document.getElementById('comboValidCloseBtn').addEventListener('click', function(){ overlay.remove(); });
  overlay.addEventListener('click', function(e){ if(e.target === overlay) overlay.remove(); });
}

function resetDescPage(){
  window.location.href = "/combo";
}

function openComboInfo(){
  var m = document.getElementById('comboInfoModal');
  m.style.display = 'flex';
  m.onclick = function(e){ if(e.target === m) closeComboInfo(); };
}
function closeComboInfo(){
  document.getElementById('comboInfoModal').style.display = 'none';
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

/* ── 콤보 가이드 투어 ── */
var COMBO_GUIDE_ITEMS = [
  {
    target: 'cgt-region',
    title: '지역 조건 선택',
    text: '<b>시도</b>와 <b>시군구</b>를 선택하여 지역 기준으로 검색 범위를 설정하세요.'
  },
  {
    target: 'cgt-detail',
    title: '상세 조건 입력',
    text: '<b>대분류·중분류</b>(선택형)와 <b>프로그램·기관명</b>(서술형)으로 세부 조건을 설정하세요.'
  }
];

function comboGuideStart() {
  if (sessionStorage.getItem('combo_guide_done')) return;

  var isMobile = window.innerWidth < 600;
  var vw = window.innerWidth;
  var vh = window.innerHeight;

  window.scrollTo(0, 0);

  var overlay = document.createElement('div');
  overlay.style.cssText = 'position:fixed;inset:0;z-index:9998;background:rgba(0,0,0,0.62);';
  document.body.appendChild(overlay);

  var prevOverflow = document.body.style.overflow;
  document.body.style.overflow = 'hidden';

  var bubbles = [];
  var bubbleW = isMobile ? Math.min(Math.floor(vw * 0.6), 240) : 230;

  /* ── 공통 헬퍼 ── */
  function addHighlight(elId) {
    var el = document.getElementById(elId);
    if (!el) return null;
    var pad = isMobile ? 4 : 6;
    var r = el.getBoundingClientRect();
    var hl = document.createElement('div');
    hl.style.cssText = [
      'position:fixed;z-index:9999;pointer-events:none;border-radius:7px;',
      'border:2px solid rgba(255,255,255,0.9);',
      'box-shadow:0 0 0 3px rgba(75,110,220,0.55);',
      'top:'+(r.top-pad)+'px;left:'+(r.left-pad)+'px;',
      'width:'+(r.width+pad*2)+'px;height:'+(r.height+pad*2)+'px;'
    ].join('');
    document.body.appendChild(hl);
    bubbles.push(hl);
    return r;
  }

  function makeBubble(title, text, w) {
    var fs      = isMobile ? '11px'   : '12px';
    var fsTitle = isMobile ? '11.5px' : '12.5px';
    var bpd     = isMobile ? '9px 12px 8px' : '13px 16px 12px';
    var b = document.createElement('div');
    b.style.cssText = [
      'position:fixed;z-index:10000;background:#fff;border-radius:11px;',
      'padding:'+bpd+';width:'+w+'px;',
      'box-shadow:0 5px 20px rgba(0,0,0,0.22);',
      'font-family:inherit;pointer-events:none;'
    ].join('');
    b.innerHTML =
      '<div style="font-size:'+fsTitle+';font-weight:700;color:#3b5cc0;margin-bottom:4px;">&#128161; '+title+'</div>'+
      '<div style="font-size:'+fs+';color:#374151;line-height:1.6;word-break:keep-all;">'+text+'</div>';
    document.body.appendChild(b);
    bubbles.push(b);
    return b;
  }

  function addArrow(bubble, dir, pos) {
    var a = document.createElement('div');
    a.style.position = 'absolute';
    a.style.width = '0';
    a.style.height = '0';
    if (dir === 'up') {
      a.style.borderLeft = '8px solid transparent';
      a.style.borderRight = '8px solid transparent';
      a.style.borderBottom = '8px solid #fff';
      a.style.top = '-8px';
      a.style.left = pos + 'px';
    } else if (dir === 'down') {
      a.style.borderLeft = '8px solid transparent';
      a.style.borderRight = '8px solid transparent';
      a.style.borderTop = '8px solid #fff';
      a.style.bottom = '-8px';
      a.style.left = pos + 'px';
    }
    bubble.appendChild(a);
  }

  /* ── ① 지역 조건 ── */
  var r1 = addHighlight('cgt-region');

  /* ── ② 상세 조건 ── */
  var r2 = addHighlight('cgt-detail');

  if (isMobile) {
    /* ===== 모바일 배치 =====
       두 하이라이트 경계(r1.bottom ~ r2.top)의 중간 지점을 기준으로
       지역 조건 말풍선은 중간 위에, 상세 조건 말풍선은 중간 아래에 */

    if (r1 && r2) {
      var midY = (r1.bottom + r2.top) / 2;

      var b_region = makeBubble(COMBO_GUIDE_ITEMS[0].title, COMBO_GUIDE_ITEMS[0].text, bubbleW);
      var b_detail = makeBubble(COMBO_GUIDE_ITEMS[1].title, COMBO_GUIDE_ITEMS[1].text, bubbleW);

      requestAnimationFrame(function(){
        var bh1 = b_region.offsetHeight;
        var bh2 = b_detail.offsetHeight;
        var spacing = 28;

        var top1 = midY - spacing - bh1;
        var top2 = midY + spacing;

        if (top1 < 6) top1 = 6;
        if (top2 + bh2 > vh - 90) top2 = vh - 90 - bh2;

        var bubbleLeft = Math.max(8, (vw - bubbleW) / 2);

        b_region.style.top = top1 + 'px';
        b_region.style.left = bubbleLeft + 'px';
        var arrowLeft1 = Math.max(10, Math.min(r1.left + r1.width/2 - bubbleLeft - 8, bubbleW - 26));
        addArrow(b_region, 'down', arrowLeft1);

        b_detail.style.top = top2 + 'px';
        b_detail.style.left = bubbleLeft + 'px';
        var arrowLeft2 = Math.max(10, Math.min(r2.left + r2.width/2 - bubbleLeft - 8, bubbleW - 26));
        addArrow(b_detail, 'up', arrowLeft2);
      });
    }

  } else {
    /* ===== PC 배치 =====
       동일하게 두 하이라이트 경계의 중간 기준으로 위/아래 배치 */

    if (r1 && r2) {
      var midY = (r1.bottom + r2.top) / 2;

      var b_pc_region = makeBubble(COMBO_GUIDE_ITEMS[0].title, COMBO_GUIDE_ITEMS[0].text, bubbleW);
      var b_pc_detail = makeBubble(COMBO_GUIDE_ITEMS[1].title, COMBO_GUIDE_ITEMS[1].text, bubbleW);

      requestAnimationFrame(function(){
        var bh1 = b_pc_region.offsetHeight;
        var bh2 = b_pc_detail.offsetHeight;
        var spacing = 30;

        var top1 = midY - spacing - bh1;
        var top2 = midY + spacing;

        if (top1 < 10) top1 = 10;
        if (top2 + bh2 > vh - 60) top2 = vh - 60 - bh2;

        var targetMidX = r1.left + r1.width / 2;
        var bubbleLeft = Math.max(10, Math.min(targetMidX - bubbleW/2, vw - bubbleW - 10));

        b_pc_region.style.top = top1 + 'px';
        b_pc_region.style.left = bubbleLeft + 'px';
        var arrowLeft1 = Math.max(10, Math.min(targetMidX - bubbleLeft - 8, bubbleW - 26));
        addArrow(b_pc_region, 'down', arrowLeft1);

        b_pc_detail.style.top = top2 + 'px';
        b_pc_detail.style.left = bubbleLeft + 'px';
        var arrowLeft2 = Math.max(10, Math.min(targetMidX - bubbleLeft - 8, bubbleW - 26));
        addArrow(b_pc_detail, 'up', arrowLeft2);
      });
    }
  }

  var confirmBtn = document.createElement('button');
  confirmBtn.textContent = '확인';
  confirmBtn.style.cssText = [
    'position:fixed;z-index:10001;',
    'left:50%;transform:translateX(-50%);bottom:14%;',
    'background:#5b7ee5;color:#fff;border:none;',
    'border-radius:10px;',
    'padding:'+(isMobile?'10px 40px':'11px 52px')+';',
    'font-size:'+(isMobile?'13px':'14px')+';font-weight:700;cursor:pointer;',
    'box-shadow:0 4px 16px rgba(75,110,220,0.35);white-space:nowrap;'
  ].join('');
  document.body.appendChild(confirmBtn);
  bubbles.push(confirmBtn);

  function closeGuide() {
    bubbles.forEach(function(b){ b.remove(); });
    overlay.remove();
    document.body.style.overflow = prevOverflow;
    sessionStorage.setItem('combo_guide_done', '1');
  }

  confirmBtn.addEventListener('click', function(e){ e.stopPropagation(); closeGuide(); });
  overlay.addEventListener('click', closeGuide);
}

// 가이드 투어 제거: 자동 실행하지 않음
</script>

</body>
</html>
"""

@app.route("/ocr", methods=["POST"])
def ocr():
    file = request.files.get("image")
    if not file:
        return {"text": ""}

    import base64
    from openai import OpenAI
    client = OpenAI()

    img_bytes = file.read()
    img_base64 = base64.b64encode(img_bytes).decode("utf-8")

    try:
        res = client.responses.create(
            model="gpt-4.1-mini",
            input=[{
                "role": "user",
                "content": [
                    {"type": "input_text", "text": "이미지의 한글 텍스트를 그대로 추출해줘. 줄바꿈 유지."},
                    {"type": "input_image", "image_url": f"data:{file.mimetype};base64,{img_base64}"}
                ]
            }]
        )

        text = res.output[0].content[0].text

        usage = getattr(res, "usage", None)

        input_tokens = getattr(usage, "input_tokens", 0) if usage else 0
        output_tokens = getattr(usage, "output_tokens", 0) if usage else 0
        total_tokens = getattr(usage, "total_tokens", 0) if usage else 0

        print("OCR 입력 토큰:", input_tokens)
        print("OCR 출력 토큰:", output_tokens)
        print("OCR 총 토큰:", total_tokens)

        return {
            "text": text,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": total_tokens
        }

    except Exception as e:
        print("OCR 오류:", e)
        return {"text": ""}

def build_grouped_service_results(service_results):
    grouped_service_results = []
    group_map = {}
    seen_sub = {}  # key -> set of 서비스내용 (소분류 중복 방지)

    for item in service_results:
        main_cat = str(item.get("대분류", "")).strip()
        middle_cat = str(item.get("중분류", "")).strip()
        key = main_cat + "|" + middle_cat

        if key not in group_map:
            group_id = "group_" + str(len(grouped_service_results))
            group_map[key] = {
                "group_id": group_id,
                "대분류": main_cat,
                "중분류": middle_cat,
                "direct_need": False,
                "items": []
            }
            seen_sub[key] = set()
            grouped_service_results.append(group_map[key])

        if item.get("direct_need"):
            group_map[key]["direct_need"] = True

        # 같은 소분류(서비스내용)가 이미 있으면 건너뜀 (중복 방지)
        sub = str(item.get("서비스내용", "")).strip()
        if sub not in seen_sub[key]:
            seen_sub[key].add(sub)
            group_map[key]["items"].append(item)

    return grouped_service_results

@app.route("/desc", methods=["GET","POST"])
def desc():
    query = (request.values.get("query", "") or "").strip()

    results = {}
    cond_display = None
    count = 0
    service_results = []
    warning_msg = ""
    action = (request.values.get("action", "") or "").strip()

    input_sido = normalize_sido((request.values.get("sido", "") or "").strip())
    input_sigungu = (request.values.get("sigungu", "") or "").strip()

    selected_sido = session.get("desc_selected_sido", "")
    selected_sigungu = session.get("desc_selected_sigungu", "")

    if action == "reset_region":
        session.pop("desc_selected_sido", None)
        session.pop("desc_selected_sigungu", None)
        return redirect(url_for("desc"))

    else:
        if action == "change_sido":
            session["desc_selected_sido"] = input_sido
            selected_sido = input_sido
            session.pop("desc_selected_sigungu", None)
            selected_sigungu = ""

        elif action == "change_sigungu":
            session["desc_selected_sigungu"] = input_sigungu
            selected_sigungu = input_sigungu

    cache_key = make_cache_key(query + "|" + selected_sido + "|" + selected_sigungu)
    do_search = (action == "search")
        
    if request.method == "POST" and do_search:
        now_time = time.time()
        last_search_time = session.get("desc_last_search_time", 0)

        if now_time - float(last_search_time or 0) < 10:
            warning_msg = "검색 요청이 너무 빠릅니다.\n잠시 후 다시 검색해 주세요."

            return render_template_string(
                DESC_HTML,
                style=BASE_STYLE,
                query=query,
                results=results,
                cond_display=cond_display,
                count=0,
                service_results=[],
                warning_msg=warning_msg,
                selected_sido=selected_sido,
                selected_sigungu=selected_sigungu,
                sido_options=SIDO_OPTIONS,
                sigungu_options=SIGUNGU_MAP.get(selected_sido, [])
            )

        session["desc_last_search_time"] = now_time

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
                                 grouped_service_results=build_grouped_service_results(service_results),
                    warning_msg=warning_msg,
                    selected_sido=selected_sido,
                    selected_sigungu=selected_sigungu,
                    sigungu_options=SIGUNGU_OPTIONS
                )
            else:
                del DESC_CACHE[cache_key]

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

        if any(k in q_norm for k in ["기관절개", "기관절개관", "석션", "흡인", "장루", "요루", "튜브", "루관리", "장루관리", "요루관리"]):
            extra_aliases += ["튜브관리", "루관리", "기관절개관리", "흡인", "감염관리"]

        # ---- 복지용구 관련 ----
        if any(k in q_norm for k in ["지팡이", "워커", "보행기", "보행차", "휠체어"]):
            extra_aliases += ["복지용구", "보행보조", "대여", "구입"]

        if any(k in q_norm for k in ["배회", "길을잃", "길잃", "집을못찾", "집에못오", "실종", "위치확인", "위치추적", "gps", "인지저하", "치매"]):
            extra_aliases += [
                "복지용구",
                "배회감지기",
                "위치확인",
                "위치추적",
                "GPS",
                "실종예방",
                "안전지원",
                "대여",
                "구입"
            ]

        if any(k in q_norm for k in ["안전손잡이", "손잡이", "욕실손잡이", "화장실손잡이"]):
            extra_aliases += ["복지용구", "안전손잡이", "욕실안전", "낙상예방", "구입"]

        if any(k in q_norm for k in ["미끄럼방지", "미끄럼방지매트", "욕실매트", "논슬립", "미끄럼"]):
            extra_aliases += ["복지용구", "미끄럼방지", "욕실안전", "낙상예방", "구입"]

        if any(k in q_norm for k in ["목욕의자", "샤워의자", "목욕", "샤워"]):
            extra_aliases += ["복지용구", "목욕의자", "욕실안전", "구입"]

        if any(k in q_norm for k in ["이동변기", "간이변기", "변기", "좌변기"]):
            extra_aliases += ["복지용구", "이동변기", "배변보조", "구입"]

        if any(k in q_norm for k in ["요실금", "패드"]):
            extra_aliases += ["복지용구", "배변보조", "위생", "구입"]

        if any(k in q_norm for k in ["전동침대", "침대", "병원침대"]):
            extra_aliases += ["복지용구", "전동침대", "대여"]

        if any(k in q_norm for k in ["욕창", "욕창매트", "욕창방지", "자세변환", "체위변경"]):
            extra_aliases += ["복지용구", "욕창예방", "자세변환", "대여"]

        if any(k in q_norm for k in ["목욕차", "방문목욕", "목욕도움", "씻기기", "씻겨", "씻겨줬으면", "목욕시켜", "목욕"]):
            extra_aliases += ["요양", "방문목욕", "장기요양", "목욕지원", "신체청결"]

        if any(k in q_norm for k in ["식사", "식사도움", "식사 준비", "식사준비", "밥", "반찬", "도시락", "영양"]):
            extra_aliases += ["가사지원", "일상생활지원", "식사도움"]

        if any(k in q_norm for k in ["청소", "청소도움"]):
            extra_aliases += ["요양", "방문요양", "장기요양", "가사지원", "일상생활지원", "청소도움"]

        if any(k in q_norm for k in ["빨래", "세탁", "빨래도움"]):
            extra_aliases += ["요양", "방문요양", "장기요양", "가사지원", "일상생활지원", "빨래도움"]

        if any(k in q_norm for k in ["가사일", "집안일", "생활도움", "집에누가와서도와", "도와줬으면"]):
            extra_aliases += ["요양", "방문요양", "장기요양", "가사지원", "일상생활지원"]

        if any(k in q_norm for k in ["돌봄", "간병", "부축", "옆에서도움", "집에서돌봐", "일상생활도움"]):
            extra_aliases += ["요양", "방문요양", "장기요양", "신체활동지원", "일상생활지원"]

        if any(k in q_norm for k in ["스마트폰", "핸드폰", "휴대폰", "휴대전화", "앱", "어플", "디지털", "비대면", "온라인"]):
            extra_aliases += ["IoT", "IOT", "사물인터넷", "스마트기기", "돌봄기기", "AI", "비대면", "응급안전", "응급안전안심서비스", "스마트돌봄", "안전확인"]

        if any(k in q_norm for k in ["경사로", "문턱", "턱", "이동불편", "출입불편"]):
            extra_aliases += ["복지용구", "경사로", "이동보조", "구입"]

        if any(k in q_norm for k in ["주간보호", "주야간보호", "데이케어", "낮동안보호", "낮에맡김", "센터다님", "센터에다님", "주간센터"]):
            extra_aliases += ["주야간보호", "신체활동지원", "인지관리", "기능회복훈련"]

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
                f"대분류: {str(r.get('대분류','')).strip()} | "
                f"중분류: {str(r.get('중분류','')).strip()} | "
                f"서비스내용: {compress_text(r.get('서비스내용',''),25)} | "
                f"서비스설명: {compress_text(r.get('서비스설명',''),77)} | "
                f"검색어: {compress_text(r.get('검색어',''),100)}\n"
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
                          grouped_service_results=build_grouped_service_results(service_results),
                warning_msg=warning_msg,
                selected_sido=selected_sido,
                selected_sigungu=selected_sigungu,
                sigungu_options=SIGUNGU_OPTIONS
            )

        client = OpenAI(api_key=api_key)


        prompt = f"""
너는 통합돌봄 서비스 추천 전문가다.

[돌봄 사례 판단]
아래 조건을 모두 충족해야 추천한다. 애매하면 {{"results": []}} 반환.
- 어르신·환자·장애인 등 돌봄 대상자가 있거나, 일상생활 어려움이 명확할 것
- 식사·이동·위생·건강·주거·안전·정서 중 하나 이상의 구체적 어려움이 있을 것
- 스스로 해결하기 어렵거나 도움·지원이 필요한 상황일 것
- 단순 상태(배고픔·피곤함·통증 등)만 있거나, 책 내용·정보 나열·무관한 텍스트면 제외

[추천 방식]
- 서비스 목록의 '서비스설명'과 '검색어'를 적극 참고한다
- 정확한 행정용어를 쓰지 않아도 의미가 비슷하면 연결한다 (예: "씻는 것 도와줬으면" → 방문목욕, "가사일 도와줬으면" → 방문요양)
- 의료·요양 맥락만 있으면 방역·환경소독 서비스 제외 (집 위생·악취·해충 언급 시 포함)
- 배회·길을 잃음·귀가 어려움 → 배회감지기, 위치확인 복지용구, 인지안전지원 연결

[추천사유 작성]
- 사례에 실제로 적힌 내용만 근거로 쓴다 (없는 내용 추측 금지)
- "사례의 어려움 → 서비스가 필요한 이유" 흐름으로 간결하게 작성

[판단 원칙]
1. 사례의 핵심 욕구(건강/이동/식사/위생/정서/주거/안전/돌봄부담)를 먼저 정리한다
2. 서비스설명·검색어와 의미적으로 맞는 서비스를 찾는다
3. 연관 서비스도 함께 포함하고, 관련성 있으면 충분히 제시한다
4. 직접 욕구 서비스 외에도 사례에 언급된 건강상태·질환·불편에 해당하는 서비스도 반드시 함께 추천한다
   (예: '관절염으로 힘들어하며 집수리 욕구가 있음' → 집수리 관련 + 관절염 관련 재활·이동지원·방문보건도 포함)
5. 특히 아래 표현은 적극 반영한다.
   - "집으로 와주길 원함" → 방문형 서비스 우선 고려
   - 복지용구 추천 시 아래 품목 목록 기준으로 반드시 대여/구입을 구분한다 (없는 품목명 절대 사용 금지):
     · 대여 품목: 수동휠체어, 전동침대, 수동침대, 이동욕조, 목욕리프트, 배회감지기(GPS형·메트형)
     · 구입 또는 대여 품목: 욕창예방매트리스, 경사로(실외), 경사로(실내), 이승보조기기, 대화형정서지원기기
     · 구입 품목: 이동변기, 목욕의자, 성인용보행기, 안전손잡이, 미끄럼방지용품, 간이변기, 지팡이, 욕창예방방석, 자세변환용구, 요실금팬티, 구강청정기(마우스피스형), 기저귀센서, 배회감지기(태그형), 고관절보호대, 낙상알림시스템
   - 복지용구 서비스 선택 기준 (매우 중요):
     · 필요한 품목이 대여 품목만 해당 → "복지용구 대여"만 추천
     · 필요한 품목이 구입 품목만 해당 → "복지용구 구입"만 추천
     · 필요한 품목이 "구입 또는 대여" 품목이거나 대여·구입 둘 다 해당 → 둘 다 추천
     · 품목이 명확하지 않은 일반적 보조기구 필요 표현 → 둘 다 추천
   - "지팡이", "워커", "보행기", "보행차" → 복지용구 구입(지팡이, 성인용보행기)만 추천, 대여 품목 추천 금지
   - "휠체어" → 복지용구 대여(수동휠체어)만 추천, 구입 품목 추천 금지
   - "안전손잡이", "손잡이", "욕실손잡이", "화장실손잡이" → 복지용구 구입(안전손잡이) 적극 고려
   - "도구가 필요함", "보조도구 필요", "이동 도구 필요", "집에서 활용가능한 도구", "활용가능한 도구" → 지팡이·보행기 등 구입 품목 우선 검토, 휠체어 언급 없으면 복지용구 대여 추천 금지
   - "미끄럼방지", "미끄럼방지매트", "욕실매트", "논슬립", "미끄럼" → 복지용구 구입(미끄럼방지용품) 적극 고려
   - "목욕의자", "샤워의자" → 복지용구 구입(목욕의자) 고려
   - 방문목욕 소분류 판단 기준 (매우 중요):
     · "차량", "목욕차", "차가 와서" 등 차량 방문 표현 → 반드시 "차량내 목욕"만 선택
     · "집에서", "가정에서", "가정내" 등 가정 방문 표현 → 반드시 "가정내 목욕"만 선택
     · 그 외 일반 목욕 표현("목욕이 필요", "목욕 도움" 등) → "차량내 목욕"과 "가정내 목욕" 둘 다 선택
   - "이동변기", "간이변기" → 복지용구 구입(이동변기, 간이변기) 고려
   - "요실금", "패드" → 복지용구 구입(요실금팬티) 고려
   - "전동침대", "침대", "병원침대" → 복지용구 대여(전동침대, 수동침대) 우선 고려
   - "욕창", "욕창매트", "욕창방지" → 복지용구 구입 또는 대여(욕창예방매트리스, 욕창예방방석) 및 의료처치 함께 고려
   - "자세변환", "체위변경" → 복지용구 구입(자세변환용구) 고려
   - "경사로", "문턱", "턱" → 복지용구 구입 또는 대여(경사로) 고려
   - "배회", "길을 잃", "실종", "위치확인", "GPS" → 복지용구 대여(배회감지기 GPS형·메트형) 또는 구입(배회감지기 태그형) 고려
   - "낙상", "넘어짐" → 복지용구 구입(고관절보호대, 낙상알림시스템, 미끄럼방지용품) 고려
   - "콧줄", "비위관", "위관", "경관급식", "소변줄", "도뇨줄", "유치도뇨", "장루", "요루", "기관절개", "석션", "흡인", "복막투석" → 방문진료의 의료처치(욕창, 루, 튜브관리 등)를 적극 우선 고려
   - 의료처치(욕창, 루, 튜브관리 등)가 적합하면 감염관리도 함께 검토한다
   - 매우 중요: 서비스내용의 "소독"은 기본적으로 집안/주거환경 관련 소독으로 본다
   - "상처 소독", "드레싱", "욕창 소독", "감염", "염증", "고름", "진물"처럼 의료적 맥락의 소독은 서비스내용 "소독"으로 연결하지 말고, 반드시 "감염관리" 또는 "의료처치(욕창, 루, 튜브관리 등)" 쪽으로 판단한다
   - 반대로 집 청소, 방역, 주거 위생, 해충, 집안 환경개선 맥락이면 서비스내용 "소독"을 검토한다
   - "무릎통증", "통증", "거동불편", "움직이기 어려움" → 재활, 기능회복, 방문보건, 이동지원 계열 고려 (단, 약 복용 언급만으로는 이 규칙 적용 금지 — 신체 불편이 명확히 언급된 경우에만 적용)
   - "요통", "허리가 자주 아픔", "허리 통증", "허리 불편" → 통증관리, 재활, 기능회복, 방문보건 계열을 우선 검토한다
   - "외로움", "말벗 필요", "혼자 지냄", "고립" → 정서지원, 안부확인, 돌봄연계를 우선 검토한다
   - "주간보호", "주야간보호", "센터 다님", "낮에 센터", "데이케어" → 주야간보호(신체활동지원, 인지관리, 기능회복훈련 등) 계열을 우선 검토한다
   - 표현이 다르더라도 의미가 비슷하면 대표 욕구로 묶어서 판단한다
   - "다리가 저림", "다리 저림", "발 저림", "손발 저림", "찌릿함", "감각이상" → 신경증상, 통증, 재활, 기능회복, 방문보건, 이동지원 계열을 우선 검토한다
   - "오줌을 지림", "소변을 지림", "소변 실수", "배뇨 실수", "요실금" → 배뇨관리, 위생지원, 패드 등 복지용구, 방문보건 계열을 우선 검토한다
   - "변을 지림", "대변 실수", "배변 실수", "배변 불편" → 배변관리, 위생지원, 복지용구, 방문보건 계열을 우선 검토한다
   - "자주 넘어진다", "휘청거린다", "낙상이 걱정된다", "균형이 불안하다" → 낙상예방, 안전지원, 보행보조 복지용구, 이동지원 계열을 우선 검토한다
   - "기억을 잘 못한다", "자꾸 깜빡한다", "약을 자주 잊는다" → 인지지원, 복약관리, 안부확인, 돌봄연계를 우선 검토한다
   - "약 챙기기 어렵다", "복약 관리 어렵다", "약을 많이 먹는다", "약이 많다", "다약제" → 복약관리, 방문보건 계열만 검토한다 (이동지원·재활 포함 금지)
   - "병원 가기 어렵다", "병원 동행이 필요하다", "통원이 어렵다" → 병원동행, 이동지원, 방문보건 계열을 우선 검토한다
   - "반찬을 못함", "식사 준비 어려움", "자주 배고파함", "잘 못 먹음", "차려 먹기 어렵다", "챙겨 먹기 어렵다" → 식사지원, 반찬지원, 영양지원 계열을 추천 대상으로 검토한다
   - 스마트폰·앱·디지털기기 언급 → IoT, 스마트돌봄, 응급안전안심서비스, AI 돌봄기기 검토
   - 입력에 "치매", "인지저하", "기억력 저하", "배회", "인지기능", "알츠하이머" 등이 직접 언급되지 않으면 치매 관련 서비스는 추천하지 않는다
6. 결과는 너무 적게 내지 말고, 관련성이 있으면 충분히 제시한다
7. 우선순위가 높은 순서대로 정렬한다
8. 최대 30개까지 추천한다
9. 동일 유형 서비스는 중복 추천하지 말고 균형 있게 포함한다

[direct_need 판정]
direct_need=true 조건: 수급자·보호자가 특정 서비스나 도움을 직접 원하거나 필요로 한다고 표현한 경우
- 해당 표현: '원함', '희망함', '받고 싶어함', '원한다고 함', '희망한다고 함', '지원 희망', '욕구가 있음', '욕구가 있는', '욕구 있음', '~욕구', '원하고 있음', '희망하고 있음', '바라고 있음', '필요함', '필요하다', '필요로 함', '필요로 한다', '~가 필요한', '~이 필요한'
- 예: '외출 욕구가 있는 어르신' → 외출 관련 서비스 전체 direct_need=true
- 예: '휠체어가 필요한 어르신' → 복지용구 관련 서비스 direct_need=true
- 예: '식사도움이 필요하고 외출 욕구가 있는' → 식사 관련과 외출 관련 모두 true
- 희망/필요 표현은 바로 앞에 연결된 대상에만 적용
- 욕구 표현이 연결된 대상이 중분류 자체인 경우(예: "방문요양이 필요함", "주야간보호를 원함") → 그 중분류 안의 모든 소분류를 true로 표시한다
- 욕구 표현이 연결된 대상이 특정 소분류인 경우(예: "정서 지원이 필요함", "식사 도움을 원함") → 그 소분류만 true, 같은 중분류의 다른 소분류는 false
  (예: '외출욕구가 있음' → 이동지원 중분류의 기타·외출동행·차량지원 전부 true)
  (예: '방문요양이 필요함' → 방문요양 중분류의 모든 소분류 true)
  (예: '목욕을 원함' → 방문목욕 중분류의 모든 소분류 true)
  (예: '정서 지원이 필요함' → 정서지원 소분류만 true, 방문요양의 다른 소분류는 false)
  (예: '식사도움을 희망' → 식사 관련 소분류만 true, 같은 중분류의 인지관리 등은 false)
- 직접 욕구/필요 표현이 특정 영역(식사, 외출, 목욕 등)에 해당하면 해당 영역의 관련 서비스만 true로 표시한다

direct_need=false 조건 (아래는 절대 true로 처리하지 않는다):
- 식사·영양 관련 상태 표현: "반찬을 못함", "식사 준비 어려움", "자주 배고파함", "허기짐", "굶는 편", "잘 못 먹음", "영양이 부족해 보임", "차려 먹기 어렵다", "챙겨 먹기 어렵다", "기운이 없다", "체중이 준다"
- 환경·건강·위생·낙상·영양 문제를 조사자 또는 시스템이 필요하다고 판단한 경우
- 벌레·주거 문제 등으로 방역소독이 추천되더라도 사용자가 직접 원한다고 표현하지 않은 경우

설명문, 코드블록, 마크다운 없이 JSON만 출력한다.

출력 형식:
{{
  "results": [
    {{
      "index": 12,
      "선택이유": "무릎통증으로 이동이 어렵다고 하였으므로 이동지원 서비스를 검토할 수 있음",
      "direct_need": false
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
                temperature=0,
                timeout=90
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
                        "선택이유": r.get("선택이유", ""),
                        "direct_need": bool(r.get("direct_need", False)),
                        "_ai_picked": True
                    })

            # direct_need 기준: AI가 판단한 값 그대로 사용

            # 선택이유에서 실제 존재하지 않는 복지용구 품목명 제거
            INVALID_WELFARE_TERMS = ["욕실안전", "보행보조", "배변보조", "이동보조", "욕창예방", "위생지원"]
            for item in final_results:
                reason = str(item.get("선택이유", ""))
                for term in INVALID_WELFARE_TERMS:
                    reason = reason.replace(term + ", ", "").replace(", " + term, "").replace(term, "")
                item["선택이유"] = reason

            final_results.sort(
                key=lambda x: (
                    0 if x.get("direct_need") else 1,
                    str(x.get("대분류", "")).strip(),
                    1 if str(x.get("중분류", "")).strip() == "기타" else 0,
                    str(x.get("중분류", "")).strip(),
                    0 if x.get("_ai_picked") else 1,
                    str(x.get("서비스내용", "")).strip()
                )
            )

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

            # ======================
            # [규칙 1] 기초사정 자동 포함
            # 같은 중분류 안에 다른 소분류가 이미 검색된 경우,
            # "기초사정"이 service_df에 존재하면 무조건 함께 포함
            # ======================
            existing_keys = set(
                (str(item.get("대분류", "")).strip(),
                 str(item.get("중분류", "")).strip(),
                 str(item.get("서비스내용", "")).strip())
                for item in final_results
            )
            middle_cats_in_results = set(k[1] for k in existing_keys)

            for _, srow in service_df.iterrows():
                s_main = str(srow.get("대분류", "")).strip()
                s_mid  = str(srow.get("중분류", "")).strip()
                s_sub  = str(srow.get("서비스내용", "")).strip()
                if s_sub == "기초사정" and s_mid in middle_cats_in_results:
                    if (s_main, s_mid, s_sub) not in existing_keys:
                        final_results.append({
                            "대분류": s_main,
                            "중분류": s_mid,
                            "서비스내용": s_sub,
                            "선택이유": f"{s_mid} 서비스 제공 전 기초사정을 통해 대상자의 상태와 필요를 파악하는 것이 필요함",
                            "direct_need": False,
                            "_ai_picked": False
                        })
                        existing_keys.add((s_main, s_mid, s_sub))

            # ======================
            # [규칙 1-2] 목욕 도움/지원 필요 맥락이 있을 때만 방문목욕 소분류 강제 포함
            # 단순히 목욕 단어가 나오는 것만으로는 강제 추가하지 않는다.
            # "혼자 목욕 가능", "스스로 씻기 가능" 같은 자립 표현이 있으면 제외한다.
            # ======================
            q_norm_bath_pre = query.replace(" ", "").lower()

            # 목욕 도움/지원이 필요한 맥락 키워드
            bath_need_keywords = [
                "목욕도움", "목욕지원", "목욕희망", "목욕원함", "방문목욕",
                "씻겨", "씻기도움", "씻기지원", "목욕케어", "목욕서비스",
                "샤워도움", "샤워지원", "목욕어려움", "목욕힘듦", "목욕불가",
                "목욕못함", "목욕스스로어렵", "혼자씻기어렵", "혼자목욕어렵",
                "목욕필요", "목욕욕구", "목욕바람",
            ]
            # 목욕 자립 표현 (이런 표현이 있으면 방문목욕 강제 추가 안 함)
            bath_independent_keywords = [
                "혼자목욕가능", "혼자씻기가능", "혼자씻을수있", "스스로목욕가능",
                "목욕혼자가능", "씻기혼자가능", "혼자목욕함", "혼자씻음",
                "목욕스스로가능", "목욕독립적", "목욕도혼자가능",
            ]
            has_bath_keyword = any(k in q_norm_bath_pre for k in bath_need_keywords)
            # 자립 표현이 명시적으로 있으면 강제 추가 취소
            if any(k in q_norm_bath_pre for k in bath_independent_keywords):
                has_bath_keyword = False
            if has_bath_keyword:
                is_car_bath_pre = any(k in q_norm_bath_pre for k in [
                    "차량목욕", "목욕차", "차가와서", "차로목욕",
                    "차량으로목욕", "차가오는", "차량이와서", "차량"
                ])
                is_home_bath_pre = any(k in q_norm_bath_pre for k in [
                    "집에서목욕", "가정에서목욕", "가정내목욕",
                    "집에서씻", "가정방문목욕", "집에서하는목욕", "가정에서", "집에서"
                ])
                # 희망욕구 여부 — 목욕 관련 표현 근처에 희망/요청 표현이 함께 있을 때만 직접욕구로 인정
                # 예: "목욕 도움을 원함", "방문목욕 희망", "씻겨주기를 바람" → True
                # 예: "혼자 목욕 가능", "거의 매일 목욕함" → False (방문목욕 서비스를 요청한 게 아님)
                bath_direct_patterns = [
                    "목욕도움", "목욕지원", "목욕희망", "목욕원함", "목욕원한다",
                    "목욕받고싶", "목욕욕구", "목욕바람", "목욕필요",
                    "방문목욕희망", "방문목욕원함", "방문목욕필요",
                    "씻겨주기희망", "씻겨주기원함", "씻겨주기바람",
                    "씻기도움희망", "씻기도움원함",
                    "목욕서비스희망", "목욕서비스원함",
                ]
                is_bath_direct = any(p in q_norm_bath_pre for p in bath_direct_patterns)

                # 기존에 AI가 추가한 방문목욕 소분류를 전부 제거하고 새로 통제
                final_results = [
                    item for item in final_results
                    if not (str(item.get("대분류","")).strip() == "요양"
                            and str(item.get("중분류","")).strip() == "방문목욕")
                ]
                existing_keys = set(
                    (str(item.get("대분류","")).strip(),
                     str(item.get("중분류","")).strip(),
                     str(item.get("서비스내용","")).strip())
                    for item in final_results
                )

                for _, srow in service_df.iterrows():
                    s_main = str(srow.get("대분류", "")).strip()
                    s_mid  = str(srow.get("중분류", "")).strip()
                    s_sub  = str(srow.get("서비스내용", "")).strip()
                    if s_main != "요양" or s_mid != "방문목욕":
                        continue
                    if is_car_bath_pre and not is_home_bath_pre:
                        if "차량" not in s_sub:
                            continue
                    # 그 외(가정 명시 또는 일반 목욕): 둘 다 포함
                    if (s_main, s_mid, s_sub) not in existing_keys:
                        final_results.append({
                            "대분류": s_main,
                            "중분류": s_mid,
                            "서비스내용": s_sub,
                            "선택이유": f"방문목욕 서비스 제공 시 {s_sub}을 통해 대상자의 목욕 지원이 필요함",
                            "direct_need": is_bath_direct,
                            "_ai_picked": False
                        })
                        existing_keys.add((s_main, s_mid, s_sub))

            # ======================
            # [규칙 2] 요양 대분류 → 해당 중분류 소분류 전체 포함
            # 검색 결과에 "요양" 대분류가 있으면,
            # 그 중분류의 모든 소분류를 service_df에서 자동 추가
            # 단, "방문목욕" 중분류는 쿼리 문맥에 따라 구분
            # ======================
            lt_middles_in_results = set(
                str(item.get("중분류", "")).strip()
                for item in final_results
                if str(item.get("대분류", "")).strip() == "요양"
            )

            if lt_middles_in_results:
                q_norm_bath = query.replace(" ", "").lower()

                for _, srow in service_df.iterrows():
                    s_main = str(srow.get("대분류", "")).strip()
                    s_mid  = str(srow.get("중분류", "")).strip()
                    s_sub  = str(srow.get("서비스내용", "")).strip()

                    if s_main != "요양":
                        continue
                    if s_mid not in lt_middles_in_results:
                        continue

                    # 방문목욕은 규칙1-2에서 이미 처리 → 여기선 제외
                    if s_mid == "방문목욕":
                        continue

                    if (s_main, s_mid, s_sub) not in existing_keys:
                        final_results.append({
                            "대분류": s_main,
                            "중분류": s_mid,
                            "서비스내용": s_sub,
                            "선택이유": f"{s_mid} 서비스를 이용하는 경우 {s_sub}도 함께 검토할 수 있음",
                            "direct_need": False,
                            "_ai_picked": False
                        })
                        existing_keys.add((s_main, s_mid, s_sub))

            # 추가 후 다시 정렬
            final_results.sort(
                key=lambda x: (
                    0 if x.get("direct_need") else 1,
                    str(x.get("대분류", "")).strip(),
                    1 if str(x.get("중분류", "")).strip() == "기타" else 0,
                    str(x.get("중분류", "")).strip(),
                    0 if x.get("_ai_picked") else 1,
                    str(x.get("서비스내용", "")).strip()
                )
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
                    "선택이유": "의료처치(욕창, 루, 튜브관리 등)가 필요한 경우 감염관리도 함께 검토가 필요함",
                    "_ai_picked": False
                })

            # ======================
            # ======================
            # [후처리] 목욕 키워드만 있을 때 주거환경개선 제외
            # ======================
            if has_bath_keyword:
                final_results = [
                    item for item in final_results
                    if str(item.get("중분류", "")).strip() != "주거환경개선"
                ]

            # 복지용구 대여/구입 후처리
            # 쿼리에 휠체어·침대·욕조 등 대여 품목 명시 없으면 복지용구 대여 제거
            # ======================
            q_norm_welfare = query.replace(" ", "").lower()
            rental_keywords = [
                "휠체어", "전동침대", "수동침대", "침대", "이동욕조", "목욕리프트",
                "배회감지기", "욕창예방매트리스", "경사로", "이승보조기기", "대화형정서지원기기"
            ]
            has_rental_keyword = any(k in q_norm_welfare for k in rental_keywords)

            if not has_rental_keyword:
                final_results = [
                    item for item in final_results
                    if not (
                        str(item.get("대분류","")).strip() == "요양" and
                        str(item.get("중분류","")).strip() == "복지용구" and
                        str(item.get("서비스내용","")).strip() == "복지용구 대여"
                    )
                ]

            # ======================
            # [후처리] "기관" 글자 오탐 방지 — 방문진료·방문간호 제거
            # 검색어에 "기관"이 포함되어 있지만 실제 의료처치 키워드가 없을 때
            # AI가 "기관절개" 맥락으로 오해하여 방문진료·방문간호를 추천하는 것을 제거
            # ======================
            real_medical_keywords = [
                "기관절개", "기관절개관", "석션", "흡인", "콧줄", "비위관", "위관",
                "경관급식", "소변줄", "도뇨줄", "유치도뇨", "장루", "요루", "복막투석",
                "욕창", "상처", "드레싱", "감염", "의료처치", "튜브"
            ]
            q_norm_medical = query.replace(" ", "")
            has_real_medical = any(k in q_norm_medical for k in real_medical_keywords)

            if "기관" in q_norm_medical and not has_real_medical:
                final_results = [
                    item for item in final_results
                    if not (
                        str(item.get("중분류", "")).strip() in ("방문진료", "방문간호")
                    )
                ]

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
            print("=== 목욕 디버그 ===")
            q_debug = query.replace(" ", "").lower()
            _bath_need_kw = ["목욕도움","목욕지원","목욕희망","목욕원함","방문목욕","씻겨","씻기도움","씻기지원","목욕케어","목욕서비스","샤워도움","샤워지원","목욕어려움","목욕힘듦","목욕불가","목욕못함","목욕스스로어렵","혼자씻기어렵","혼자목욕어렵","목욕필요","목욕욕구","목욕바람"]
            _bath_indep_kw = ["혼자목욕가능","혼자씻기가능","혼자씻을수있","스스로목욕가능","목욕혼자가능","씻기혼자가능","혼자목욕함","혼자씻음","목욕스스로가능","목욕독립적","목욕도혼자가능"]
            print("has_bath_need =", any(k in q_debug for k in _bath_need_kw))
            print("has_bath_independent =", any(k in q_debug for k in _bath_indep_kw))
            print("has_bath_keyword(최종) =", has_bath_keyword)
            print("is_bath_direct =", any(p in q_debug for p in bath_direct_patterns) if has_bath_keyword else "N/A")
            bath_items = [r for r in final_results if str(r.get("중분류","")).strip() == "방문목욕"]
            print("방문목욕 항목 수 =", len(bath_items))
            for b in bath_items:
                print("  방문목욕 →", b.get("서비스내용",""), "| direct_need =", b.get("direct_need",""))
            print("==================")

            service_results = filtered_results
            # _ai_picked는 정렬용 내부 플래그이므로 결과에서 제거
            for item in service_results:
                item.pop("_ai_picked", None)
            print("최종 service_results 개수 =", len(service_results))
            for r in service_results:
                print("→", r.get("대분류",""), "|", r.get("중분류",""), "|", r.get("서비스내용",""), "|", r.get("direct_need",""))


        except Exception as e:
            app.logger.exception(e)
            return render_template_string(ERROR_500_HTML), 500


        count = len(service_results)

        if count == 0:
            warning_msg = "검색 결과가 없습니다.\n어르신의 건강상태, 생활환경, 돌봄 필요 상황 등을 조금 더 구체적으로 입력해 주세요."

        elif count >= 15:
            warning_msg = "15개 이상의 서비스가 검색되었습니다.\n복합적인 서비스 연계가 필요한 대상일 수 있습니다."
            if not service_results:
                warning_msg = "검색 결과가 없습니다.\n어르신의 건강상태, 생활불편, 돌봄 필요 상황 등을 구체적으로 입력해 주세요."
                count = 0

        DESC_CACHE[cache_key] = {
            "results": service_results,
            "warning": warning_msg,
            "time": time.time()
        }
        trim_desc_cache()

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
             grouped_service_results=build_grouped_service_results(service_results),
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
<title>사례별 AI 추천 서비스 찾기</title>

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

.desc-top-bar{
  display:flex;
  justify-content:space-between;
  align-items:center;
  gap:12px;
  margin-bottom:28px;
}

.desc-top-bar .home-button,
.desc-top-bar .reset-button{
  display:inline-flex !important;
  align-items:center;
  justify-content:center;
  gap:5px;
  width:auto !important;
  height:34px !important;
  margin:0 !important;
  padding:0 15px !important;

  background:#ffffff !important;
  border:1px solid #e5e7eb !important;
  border-radius:8px !important;
  color:#6b7280 !important;
  backdrop-filter:none;

  font-size:13px !important;
  font-weight:600 !important;
  line-height:1 !important;
  text-decoration:none !important;
  box-shadow:0 2px 6px rgba(15,23,42,0.08) !important;

  cursor:pointer;
  transition:all .15s;
}

.desc-top-bar .home-button:hover,
.desc-top-bar .reset-button:hover{
  background:#f3f4f6 !important;
  color:#374151 !important;
}

.desc-title-row{
  width:100%;
  max-width:680px;
  margin:0 auto 18px auto;
  display:grid;
  grid-template-columns:1fr auto 1fr;
  align-items:center;
}

.desc-title-row h2{
  grid-column:2;
  margin:0;
}

.desc-title-row .service-table-icon-btn{
  grid-column:3;
  justify-self:end;
  transform:translate(-10px, 24px);
}

.service-table-icon-btn{
  width:auto !important;
  height:26px !important;
  padding:0 8px !important;
  border-radius:999px;
  border:1px solid #e5e7eb;
  background:#ffffff;
  color:#6b7280;
  font-size:11.5px;
  font-weight:600;
  cursor:pointer;
  display:inline-flex;
  align-items:center;
  justify-content:center;
  gap:3px;
  box-shadow:none;
}

.service-table-icon-btn em{
  font-style:normal;
  font-size:11.5px;
}

.service-table-icon-btn:hover{
  background:#f9fafb;
  color:#374151;
}

.service-table-modal{
  display:none;
  position:fixed !important;
  inset:0 !important;
  z-index:99999 !important;
  background:rgba(15,23,42,0.58) !important;
  align-items:center !important;
  justify-content:center !important;
  padding:18px !important;
}

.service-table-box{
  width:100%;
  max-width:820px;
  max-height:86vh;
  background:#ffffff;
  border-radius:18px;
  overflow:hidden;
  box-shadow:0 18px 50px rgba(0,0,0,0.28);
  display:flex;
  flex-direction:column;
}

.service-table-header{
  height:48px;
  padding:0 16px;
  background:#f8fafc;
  border-bottom:1px solid #e5e7eb;
  display:flex;
  align-items:center;
  justify-content:space-between;
  font-size:15px;
  font-weight:800;
  color:#111827;
}

.service-table-close{
  width:34px !important;
  height:34px !important;
  padding:0 !important;
  border:none !important;
  border-radius:999px !important;
  background:transparent !important;
  color:#374151 !important;
  font-size:22px !important;
  font-weight:800 !important;
  line-height:1 !important;
  box-shadow:none !important;
  cursor:pointer;
}

.service-table-body{
  padding:14px;
  overflow:auto;
}

.service-table-body img{
  width:100%;
  display:block;
  border-radius:12px;
  margin-bottom:14px;
  border:1px solid #e5e7eb;
}

.service-table-body img:last-child{
  margin-bottom:0;
}

@media (max-width:480px){
  .service-table-box{
    max-height:88vh;
    border-radius:14px;
  }

  .service-table-header{
    height:44px;
    font-size:14px;
  }
}

@media (max-width:480px){
  .desc-title-row{
    gap:6px;
    margin-bottom:14px;
  }

  .service-table-icon-btn{
    width:28px;
    height:28px;
    font-size:13px;
  }
}
@media (max-width:480px){
  .desc-top-bar{
    gap:8px;
    margin-bottom:20px;
  }

  .desc-top-bar .home-button,
  .desc-top-bar .reset-button{
    height:34px !important;
    padding:0 13px !important;
    font-size:13px !important;
  }
}

.home-button{
  display:inline-flex;
  align-items:center;
  justify-content:center;
  gap:5px;
  width:auto;
  height:34px;
  margin-top:0;
  padding:0 15px;
  border-radius:8px;
  background:#5b7ee5;
  color:#fff;
  text-decoration:none;
  font-size:13px;
  font-weight:500;
  border:none;
  cursor:pointer;
  transition:all .15s;
  flex:0 0 auto;
}

.reset-button{
  display:inline-flex;
  align-items:center;
  justify-content:center;
  gap:5px;
  width:auto;
  height:34px;
  margin-top:0;
  padding:0 15px;
  border-radius:8px;
  background:#ffffff;
  border:1px solid #e5e7eb;
  color:#6b7280;
  text-decoration:none;
  font-size:13px;
  font-weight:600;
  box-shadow:0 2px 6px rgba(15,23,42,0.08);
  cursor:pointer;
  transition:all .15s;
  flex:0 0 auto;
}

.desc-top-bar{
  display:flex;
  justify-content:space-between;
  align-items:center;
  gap:12px;
}

.reset-button:hover{
  background:#f3f4f6;
  color:#374151;
}

@media (max-width:480px){
  .home-button,
  .reset-button{
    display:inline-flex;
    align-items:center;
    justify-content:center;
    width:auto;
    height:30px;
    margin-top:0;
    padding:0 10px;
    font-size:11.5px;
    line-height:1;
    flex:0 0 auto;
  }
}


.home-button:hover{
  background:#f3f4f6;
  color:#374151;
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
  margin-top:18px;
  padding:16px 18px;
  border-radius:14px;
  background:#f1f5f9;
  border:1px solid #dbeafe;
}

.tip-notice{
  margin:18px 0 0 0;              /* 위 박스랑 간격 맞춤 */
  padding:16px 18px;              /* 내부 여백 통일 */
  border-radius:16px;             /* 위 박스랑 비슷하게 */
  background:#f8fbff;
  border:1px solid #dbeafe;
  color:#1f2937;
  font-size:14px;
  line-height:1.7;
  word-break:keep-all;
  overflow-wrap:break-word;       /* 줄바꿈 자연스럽게 */
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

.warning-box{
  margin:18px 0 16px 0;
  padding:14px 20px;
  border-radius:12px;
  background:#fff7ed;
  border:1px solid #fdba74;
  color:#9a3412;
  font-size:14px;
  font-weight:700;
  line-height:1.7;

  display:flex;
  align-items:flex-start;
  gap:8px;

  word-break:keep-all;
  overflow-wrap:break-word;
}

.warning-icon{
  flex:0 0 auto;
  line-height:1.7;
}

.warning-text{
  flex:1;
  min-width:0;
  white-space:pre-line;
  word-break:keep-all;
  overflow-wrap:break-word;
}

@media (max-width:480px){
  .warning-box{
    font-size:13px;
    line-height:1.65;
    padding:13px 14px;
  }

  .warning-icon{
    line-height:1.65;
  }

  .warning-text{
    line-height:1.65;
  }
}

/* 👇 여기다 붙여 */
#voiceBtn,
#imgBtn{
  display:none !important;
}

@media (max-width:768px){
  #voiceBtn,
  #imgBtn{
    position:absolute !important;
    right:12px !important;
    width:42px !important;
    height:42px !important;
    min-width:42px !important;
    max-width:42px !important;
    margin:0 !important;
    padding:0 !important;
    border-radius:50% !important;
    border:none !important;
    background:rgba(37,99,235,0.92) !important;
    color:white !important;
    display:flex !important;
    align-items:center !important;
    justify-content:center !important;
    box-shadow:0 4px 12px rgba(0,0,0,0.15) !important;
    cursor:pointer !important;
    z-index:30 !important;
    line-height:1 !important;
  }

  #voiceBtn{
    top:20px !important;
  }

  #imgBtn{
    top:80px !important;
  }
}

#imgBtn{
  display:none;
}

@media (max-width:768px){
  #imgBtn{
    position:absolute;
    right:12px;
    top:90px;
    width:42px;
    height:42px;
    margin:0;
    padding:0;
    display:flex;
    align-items:center;
    justify-content:center;
    border-radius:50%;
    border:none;
    background:rgba(37,99,235,0.92);
    color:white;
    font-size:18px;
    box-shadow:0 4px 12px rgba(0,0,0,0.15);
    cursor:pointer;
    z-index:10;
  }
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
.loading-step-bar{
  display:flex;
  justify-content:center;
  gap:6px;
  margin:16px auto 0 auto;
  width:150px;
}

.loading-step{
  flex:1;
  height:6px;
  border-radius:999px;
  background:#e5e7eb;
  transition:background 0.3s ease, transform 0.3s ease;
}

.loading-step.active{
  background:#2563eb;
  transform:scaleY(1.15);
}

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

.privacy-warning{
  margin:12px 0 0 0;
  padding:12px 18px;
  border-radius:12px;
  background:#fff1f2;
  border:1px solid #fb7185;
  color:#9f1239;
  font-size:14px;
  font-weight:700;
  line-height:1.55;
  display:flex;
  align-items:center;
  gap:12px;
}

.privacy-warning-icon{
  flex:0 0 auto;
  line-height:1.65;
}

.privacy-warning-text{
  flex:1;
  min-width:0;
  word-break:keep-all;
  overflow-wrap:break-word;
}

@media (max-width:480px){
  .privacy-warning{
    margin:12px 0 0 0;
    padding:13px 14px;
    font-size:13px;
    line-height:1.6;
  }

  .privacy-warning-icon{
    line-height:1.6;
  }

  .privacy-warning-text{
    line-height:1.6;
  }
}
.siren-icon{
  width:54px;
  height:56px;
  flex:0 0 54px;
  display:inline-flex;
  align-items:center;
  justify-content:center;
  margin-top:0;
}

.siren-svg{
  width:54px;
  height:56px;
  display:block;
}
@media (max-width:480px){
  .siren-icon{
    width:48px;
    height:50px;
    flex-basis:48px;
  }

  .siren-svg{
    width:48px;
    height:50px;
  }
}

.ray-left{
  left:0;
  top:9px;
  transform:rotate(45deg);
}

.ray-right{
  right:0;
  top:9px;
  transform:rotate(-45deg);
}

.ray-top{
  left:24px;
  top:0;
  width:5px;
  height:20px;
}

@keyframes sirenBlink{
  0%, 100%{
    background:#ef4444;
  }
  50%{
    background:#dc2626;
  }
}

@media (max-width:480px){
  .siren-icon{
    width:48px;
    height:43px;
    flex-basis:48px;
  }

  .siren-light{
    left:12px;
    top:11px;
    width:24px;
    height:25px;
    border-width:4px;
  }

  .siren-base{
    left:4px;
    bottom:3px;
    width:40px;
    height:14px;
    border-width:4px;
  }

  .siren-ray{
    width:17px;
    height:5px;
  }

  .ray-left{
    left:0;
    top:8px;
  }

  .ray-right{
    right:0;
    top:8px;
  }

  .ray-top{
    left:22px;
    top:0;
    width:5px;
    height:17px;
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


.direct-need-box{
  margin:14px 0 18px 0;
  padding:14px;

  background:#eef4ff;

  border:2px solid #5b8ff9;

  border-radius:16px;
}

.direct-need-title{
  display:inline-flex;
  align-items:center;
  justify-content:center;
  gap:2px;

  height:32px;
  padding:0 14px 0 10px;

  border-radius:999px;

  background:#ffffff;
  border:1px solid #93c5fd;

  color:#2563eb;

  font-size:12px;
  font-weight:800;
  line-height:1;
  margin-bottom:16px;
}


.direct-need-tooltip-wrap{
  position:relative;
  display:inline-flex;
  align-items:center;
}
.direct-need-tooltip-icon{
  display:inline-flex;
  align-items:center;
  justify-content:center;
  width:18px;
  height:18px;
  border-radius:50%;
  background:#93c5fd;
  color:#1e40af;
  font-size:11px;
  font-weight:800;
  cursor:default;
  flex-shrink:0;
  user-select:none;
}
.direct-need-tooltip-box{
  display:none;
  position:absolute;
  left:24px;
  top:50%;
  transform:translateY(-50%);
  background:#1e3a8a;
  color:#fff;
  font-size:12px;
  font-weight:500;
  line-height:1.55;
  padding:8px 12px;
  border-radius:8px;
  width:max-content;
  max-width:min(360px, calc(100vw - 64px));
  white-space:normal;
  word-break:keep-all;
  overflow-wrap:break-word;
  z-index:999;
  box-shadow:0 4px 14px rgba(0,0,0,0.18);
  pointer-events:none;
}
.direct-need-tooltip-wrap:hover .direct-need-tooltip-box{
  display:block;
}

@media (max-width:480px){
  .direct-need-box{
    position:relative;
  }

  .direct-need-tooltip-wrap{
    position:static;
  }

  .direct-need-tooltip-box{
    left:12px;
    right:12px;
    top:56px;
    transform:none;
    width:auto;
    max-width:none;
    box-sizing:border-box;
    text-align:left;
    z-index:5000;
  }
}
.cute-star{
  display:inline-flex;
  align-items:center;
  justify-content:center;
  width:17px;
  height:17px;
  margin-right:0px;
  color:#f59e0b;
  font-size:15px;
  font-weight:900;
  line-height:1;
  text-shadow:0 1px 2px rgba(180,83,9,0.25);
  transform:rotate(-8deg);
}

.mini-cute-star{
  display:inline-flex;
  align-items:center;
  justify-content:center;
  width:auto;
  height:auto;
  margin-right:4px;
  color:#f59e0b;
  font-size:12px;
  font-weight:900;
  line-height:1;
  text-shadow:0 1px 2px rgba(180,83,9,0.25);
  vertical-align:0;
  transform:rotate(-8deg);
}

.direct-need-card{
  border:1px solid #bfdbfe !important;
  background:#ffffff !important;
  margin-bottom:14px !important;
}

.direct-need-card:last-child{
  margin-bottom:0 !important;
}

.grouped-result-card{
  background:#ffffff !important;
  border:0.5px solid #e5e7eb !important;
  border-radius:16px !important;
  padding:0 !important;
  box-shadow:none !important;
  overflow:hidden;
  transition:none !important;
}

.grouped-result-card:hover{
  border:0.5px solid #e5e7eb !important;
  box-shadow:none !important;
}

.direct-need-card{
  border:1px solid #85B7EB !important;
}

.group-card-top{
  display:flex;
  justify-content:space-between;
  align-items:center;
  padding:11px 14px 10px;
  gap:10px;
  border-bottom:0.5px solid #f1f5f9;
}

.group-title-area{
  flex:1;
  min-width:0;
  display:flex;
  flex-direction:column;
  gap:2px;
}

.group-title-meta{
  font-size:10px;
  color:#9ca3af;
  letter-spacing:0.3px;
}

.group-title-grid{
  display:flex;
  align-items:flex-start;
  gap:4px;
  flex-wrap:wrap;
}

.group-title-col{
  min-width:0;
}

.group-title-label{
  display:none;
}

.group-title-value{
  font-size:15px;
  font-weight:700;
  color:#111827;
  line-height:1.35;
  letter-spacing:-0.3px;
  white-space:normal;
  overflow:visible;
  text-overflow:clip;
  word-break:keep-all;
  overflow-wrap:break-word;
}

.group-title-value.main-val{
  font-size:12px;
  font-weight:400;
  color:#6b7280;
}

.group-title-arrow{
  font-size:12px;
  font-weight:400;
  color:#d1d5db;
  line-height:1;
  flex-shrink:0;
}

.group-search-btn{
  display:inline-flex;
  align-items:center;
  justify-content:center;
  height:28px;
  padding:0 10px;
  border:0.5px solid #d1d5db;
  border-radius:999px;
  background:#f9fafb;
  color:#6b7280;
  font-size:12px;
  font-weight:500;
  text-decoration:none;
  white-space:nowrap;
  flex-shrink:0;
  cursor:pointer;
}

.sub-service-section{
  padding:10px 14px 12px;
}

.sub-service-label{
  font-size:10px;
  font-weight:500;
  color:#9ca3af;
  letter-spacing:0.4px;
  text-transform:uppercase;
  margin-bottom:7px;
}

.sub-service-tabs{
  display:flex;
  flex-wrap:wrap;
  gap:6px;
  margin-bottom:10px;
}

.sub-service-tab{
  display:inline-flex;
  align-items:center;
  gap:3px;
  width:auto !important;
  height:auto !important;
  margin-top:0 !important;
  min-height:30px;
  padding:4px 12px;
  border-radius:999px;
  border:0.5px solid #e5e7eb;
  background:#f9fafb;
  font-size:13px;
  color:#6b7280;
  cursor:pointer;
  white-space:normal;
  word-break:keep-all;
  line-height:1.4;
}

.sub-service-tab.active{
  background:#185FA5;
  border-color:#185FA5;
  color:#ffffff;
}

.sub-service-tab.direct{
  background:#ffffff;
  border:1.5px solid #EF9F27;
  color:#633806;
  font-weight:500;
}

.wish-star-sm{
  width:11px;
  height:11px;
  flex-shrink:0;
}

.reason-box{
  background:#f9fafb;
  padding:10px 12px;
  border-left:2.5px solid #378ADD;
  border-radius:0 8px 8px 0;
}

.reason-title{
  font-size:11px;
  font-weight:500;
  color:#9ca3af;
  margin-bottom:4px;
  letter-spacing:0.3px;
  text-transform:uppercase;
}

.reason-text{
  font-size:13px;
  color:#374151;
  line-height:1.6;
  word-break:keep-all;
}


@media (max-width:480px){
  .group-card-top{
    flex-direction:row;
    align-items:flex-start;
    justify-content:space-between;
    gap:6px;
    padding:10px 10px 6px !important;
  }

  .group-title-area{
    flex:1 1 auto;
    width:auto;
    min-width:0;
  }

  .group-title-grid{
    gap:3px;
    align-items:flex-start;
  }

  .group-title-value{
    font-size:14px;
    font-weight:750;
    line-height:1.35;
  }

  .group-title-value.main-val{
    font-size:11px;
    line-height:1.35;
  }

  .group-title-arrow{
    font-size:11px;
    line-height:1.35;
  }

  .group-search-btn{
    align-self:flex-start;
    height:24px;
    min-height:24px;
    padding:0 8px;
    font-size:11px;
    margin-top:2px;
    flex-shrink:0;
  }

  .sub-service-section{
    padding:6px 10px 10px !important;
  }

  .sub-service-label{
    margin-bottom:5px;
  }

  .sub-service-tabs{
    gap:5px;
    margin-bottom:8px;
  }

  .sub-service-tab{
    font-size:12.5px !important;
    padding:6px 10px !important;
    min-height:28px;
  }

  .direct-need-box{
    margin:14px 0 18px 0;
    padding:14px;
    background:#eef4ff;
    border:2px solid #5b8ff9;
    border-radius:16px;
  }

  .direct-need-title{
    display:inline-flex;
    align-items:center;
    justify-content:center;
    gap:2px;
    height:32px;
    padding:0 14px 0 10px;
    border-radius:999px;
    background:#ffffff;
    border:1px solid #93c5fd;
    color:#2563eb;
    font-size:12px;
    font-weight:800;
    line-height:1;
    margin-bottom:16px;
  }

  .cute-star{
    width:auto;
    height:auto;
    margin-right:0;
    font-size:11px;
  }
}


/* ===== 개인정보 입력 주의 팝업 ===== */
#privacyModal{
  display:none;
  position:fixed;
  inset:0;
  background:rgba(15,23,42,0.48);
  z-index:9999;
  align-items:center;
  justify-content:center;
  padding:18px;
}

#privacyBox{
  width:100%;
  max-width:390px;
  background:#ffffff;
  border-radius:24px;
  padding:30px 24px 24px 24px;
  text-align:center;
  box-shadow:0 20px 50px rgba(0,0,0,0.22);
}

.privacy-icon{
  width:46px;
  height:46px;
  margin:0 auto 14px auto;
  border-radius:50%;
  background:#fee2e2;
  color:#dc2626;
  display:flex;
  align-items:center;
  justify-content:center;
  font-size:28px;
  font-weight:900;
}

.privacy-icon.siren-icon{
  background:#ffffff;
  border-radius:0;
  width:56px;
  height:62px;
  margin:0 auto 4px auto;
}

.privacy-icon.siren-icon .siren-svg{
  width:56px;
  height:62px;
  display:block;
}

.privacy-title{
  font-size:22px;
  font-weight:900;
  color:#111827;
  margin-bottom:8px;
}

.privacy-subtitle{
  font-size:14px;
  color:#6b7280;
  line-height:1.55;
  margin-bottom:18px;
  word-break:keep-all;
}

.privacy-text{
  font-size:14px;
  line-height:1.7;
  color:#374151;
  word-break:keep-all;
  background:#f8fafc;
  border:1px solid #e5e7eb;
  border-radius:16px;
  padding:16px 15px;
  margin-bottom:14px;
}

.privacy-text b{
  color:#dc2626;
}

.privacy-notice{
  margin:8px 0 12px 0;
  color:#6b7280;
  font-size:12px;
  line-height:1.45;
  word-break:keep-all;
}

.privacy-check{
  display:flex;
  align-items:center;
  justify-content:center;
  gap:8px;
  margin:12px 0 18px 0;
  font-size:13px;
  color:#4b5563;
  cursor:pointer;
}

.privacy-check input{
  width:16px;
  height:16px;
  margin:0;
}

.privacy-confirm{
  width:100%;
  height:48px;
  border:none;
  border-radius:14px;
  background:#2563eb;
  color:#ffffff;
  font-size:15px;
  font-weight:800;
  cursor:pointer;
  box-shadow:0 8px 18px rgba(37,99,235,0.22);
}

@media (max-width:480px){
  #privacyBox{
    max-width:360px;
    padding:28px 22px 22px 22px;
    border-radius:22px;
  }

  .privacy-title{
    font-size:21px;
  }

  .privacy-text,
  .privacy-subtitle{
    font-size:13px;
  }
}

@media (max-width:480px){

  .desc-title-row{
    width:100%;
    max-width:380px;
    grid-template-columns:1fr;
    justify-items:center;
    row-gap:8px;
    margin-bottom:4px;
  }

  .desc-title-row h2{
    grid-column:1;
    margin-bottom:0;
  }

  .desc-title-row .service-table-icon-btn{
    grid-column:1;
    justify-self:end;
    margin-right:5px;
    margin-bottom:-8px;
    transform:translateX(-2px);
    white-space:nowrap;
    width:auto !important;
  }

}
/* ===== 일반욕구 카드 색상 분리 ===== */

.normal-need-card{
  border:1.5px solid #94a3b8 !important;
}

.normal-need-card:hover{
  border:1.5px solid #94a3b8 !important;
  box-shadow:none !important;
}

.normal-need-card .group-search-btn{
  border-color:#cbd5e1 !important;
  color:#475569 !important;
}

.normal-need-card .group-search-btn:hover{
  background:#f1f5f9 !important;
  border-color:#94a3b8 !important;
  color:#334155 !important;
}

.normal-need-card .sub-service-tab{
  border-color:#cbd5e1 !important;
  background:#ffffff !important;
  color:#475569 !important;
}

.normal-need-card .sub-service-tab:hover{
  background:#f1f5f9 !important;
  border-color:#94a3b8 !important;
  color:#334155 !important;
}

.normal-need-card .sub-service-tab.active{
  background:#64748b !important;
  border-color:#64748b !important;
  color:#ffffff !important;
}

.normal-need-card .reason-box{
  border-left:2.5px solid #94a3b8 !important;
}
</style>
</head>

<body>

<!-- ===== 개인정보 입력 주의 팝업 ===== -->
<div id="privacyModal">
  <div id="privacyBox">

    <div class="privacy-icon siren-icon">
  <svg class="siren-svg" viewBox="0 0 96 110" xmlns="http://www.w3.org/2000/svg">
    <line x1="48" y1="6" x2="48" y2="20" stroke="#111827" stroke-width="7" stroke-linecap="round"/>
    <line x1="17" y1="22" x2="28" y2="33" stroke="#111827" stroke-width="7" stroke-linecap="round"/>
    <line x1="79" y1="22" x2="68" y2="33" stroke="#111827" stroke-width="7" stroke-linecap="round"/>

    <path d="M28 80V62C28 48 36.8 39 48 39C59.2 39 68 48 68 62V80Z"
          fill="#ef4444"
          stroke="#111827"
          stroke-width="6"
          stroke-linejoin="round"/>

    <path d="M39 42C45 44 51 56 52 80H28V62C28 52 32.5 45 39 42Z"
          fill="rgba(255,255,255,0.18)"/>

    <rect x="18" y="76" width="60" height="20" rx="10"
          fill="#e5e7eb"
          stroke="#111827"
          stroke-width="6"/>
  </svg>
</div>

    <div class="privacy-title">개인정보 유출 주의</div>

<div class="privacy-subtitle">
  ※ 개인정보 입력에 따른 책임은 사용자에게 있습니다.
</div>

<div class="privacy-text">
  <b>이름, 주민등록번호, 연락처, 상세주소</b> 등<br>
  개인정보 입력 시 주의해 주세요.<br>
  건강, 환경 등 돌봄필요 상황만 입력해 주세요.
</div>

    <label class="privacy-check">
      <input type="checkbox" id="hidePrivacyToday">
      오늘 하루 보지 않기
    </label>

    <button type="button" class="privacy-confirm" onclick="closePrivacyModal()">
      확인
    </button>

  </div>
</div>

<div class="container">

<div class="top-bar desc-top-bar">
  <a href="/home" class="home-button">⌂ 홈으로</a>
  <button type="button" class="reset-button" onclick="resetDescPage()">↻ 다시 입력</button>
</div>

<div class="title">
  <div class="title-row">
    <div class="desc-title-row">
  <h2>사례별 AI 추천 서비스 찾기</h2>
  <button type="button" class="service-table-icon-btn" onclick="openServiceTableModal()" title="서비스 분류표">
  <span>📋</span>
  <em> 분류표</em>
</button>
</div>
  </div>
</div>

<div id="serviceTableModal" class="service-table-modal" onclick="closeServiceTableModalByBg(event)">
  <div class="service-table-box">
    <div class="service-table-header">
      <span>서비스 분류표</span>
      <button type="button" class="service-table-close" onclick="closeServiceTableModal()">×</button>
    </div>

    <div class="service-table-body">
      <img src="/static/service_table_1.png" alt="서비스 분류표 1">
      <img src="/static/service_table_2.png" alt="서비스 분류표 2">
    </div>
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
      <select name="sigungu" onchange="handleDescSigunguChange(this.form)">
        <option value="">전체</option>
        {% for g in sigungu_options %}
        <option value="{{g}}" {% if g==selected_sigungu %}selected{% endif %}>{{g}}</option>
        {% endfor %}
      </select>
    </div>

  </div>

</div>

<div style="position:relative;">

<div class="textarea-wrap">

<textarea id="queryInput" name="query" maxlength="2000" placeholder="예) 식사도움이 필요한&#10;    어르신에게 맞는 서비스">{{query}}</textarea>


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

<input type="file" id="imgInput" accept="image/*" capture="environment" style="display:none;">

<button type="button" onclick="openImage()" id="imgBtn">
  <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" fill="white" viewBox="0 0 24 24">
    <path d="M20 5h-3.2l-1.6-2H8.8L7.2 5H4c-1.1 0-2 .9-2 2v12c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V7c0-1.1-.9-2-2-2zm-8 13c-2.8 0-5-2.2-5-5s2.2-5 5-5 5 2.2 5 5-2.2 5-5 5zm0-8.2c-1.8 0-3.2 1.4-3.2 3.2s1.4 3.2 3.2 3.2 3.2-1.4 3.2-3.2-1.4-3.2-3.2-3.2z"/>
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

</form>
</div>

<div id="searchResultSection">
{% if warning_msg %}
<div class="warning-box">
  <span class="warning-icon">⚠️</span>
  <span class="warning-text">{{ warning_msg }}</span>
</div>
{% endif %}
{% if service_results %}

<div class="result" id="resultArea">

<h3>{{count}}건의 추천 서비스</h3>

{% set ns = namespace(direct_box_open=false) %}

{% for group in grouped_service_results|default([]) %}

{% if not group.direct_need and ns.direct_box_open %}
</div>
{% set ns.direct_box_open = false %}
{% endif %}

{% if group.direct_need and not ns.direct_box_open %}
<div class="direct-need-box">
  <div style="display:flex;align-items:center;gap:7px;margin-bottom:16px;">
    <div class="direct-need-title" style="margin-bottom:0;">
      <svg style="width:17px;height:17px;flex-shrink:0;vertical-align:-3px;" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
        <polygon points="12,2 15.09,8.26 22,9.27 17,14.14 18.18,21.02 12,17.77 5.82,21.02 7,14.14 2,9.27 8.91,8.26" fill="#EF9F27"/>
      </svg>
      <span>직접욕구</span>
    </div>
    <div class="direct-need-tooltip-wrap">
      <span class="direct-need-tooltip-icon">?</span>
      <div class="direct-need-tooltip-box">대상자·보호자의 희망욕구와 담당자 판단 필요 서비스가 모두 포함되었습니다.</div>
    </div>
  </div>
{% set ns.direct_box_open = true %}
{% endif %}

<div class="result-card grouped-result-card {% if group.direct_need %}direct-need-card{% else %}normal-need-card{% endif %}">

  <div class="group-card-top">
    <div class="group-title-area">
      <div class="group-title-meta">대분류 · 중분류</div>
      <div class="group-title-grid">
        <div class="group-title-col">
          <div class="group-title-value main-val">{{group["대분류"]}}</div>
        </div>
        <div class="group-title-arrow">›</div>
        <div class="group-title-col">
          <div class="group-title-value">{{group["중분류"]}}</div>
        </div>
      </div>
    </div>

    <a
  href="/combo?sido={{selected_sido|urlencode}}&sigungu={{selected_sigungu|urlencode}}&main_category={{group['대분류']|urlencode}}&middle_category={{group['중분류']|urlencode}}&from_desc=1"
  class="group-search-btn"
  onclick="return openComboGuideModal(this.href)"
>
  기관검색
</a>
  </div>

  <div class="sub-service-section">
    <div class="sub-service-label">소분류</div>

    <div class="sub-service-tabs">
    {% for item in group["items"] %}
    <button
      type="button"
      class="sub-service-tab {% if loop.first %}active{% endif %} {% if item.direct_need %}direct{% endif %}"
      onclick="showReason(this, 'reason-{{group['group_id']}}-{{loop.index0}}')"
    >
      {% if item.direct_need %}
      <svg class="wish-star-sm" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
        <polygon points="12,2 15.09,8.26 22,9.27 17,14.14 18.18,21.02 12,17.77 5.82,21.02 7,14.14 2,9.27 8.91,8.26" fill="#EF9F27"/>
      </svg>
      {% endif %}
      {{item["서비스내용"]}}
    </button>
    {% endfor %}
    </div>

    <div class="reason-box-wrap">
    {% for item in group["items"] %}
    <div
      id="reason-{{group['group_id']}}-{{loop.index0}}"
      class="reason-box"
      style="{% if not loop.first %}display:none;{% endif %}"
    >
      <div class="reason-title">추천 이유</div>
      <div class="reason-text">{{item["선택이유"]}}</div>
    </div>
    {% endfor %}
    </div>
  </div>

</div>

{% endfor %}

{% if ns.direct_box_open %}
</div>
{% endif %}
</div>

{% endif %}



<div id="comboGuideModal" style="display:none;position:fixed;inset:0;background:rgba(15,23,42,0.45);z-index:99999;align-items:center;justify-content:center;padding:20px;">
  <div style="width:100%;max-width:420px;background:#ffffff;border-radius:20px;box-shadow:0 20px 50px rgba(15,23,42,0.22);overflow:hidden;">
    
    <div style="padding:18px 20px 12px 20px;border-bottom:1px solid #eef2f7;">
      <div style="font-size:17px;font-weight:800;color:#111827;">기관검색 안내</div>
      <div style="font-size:13px;color:#6b7280;margin-top:4px;">사례기반 검색 결과 연동</div>
    </div>

    <div style="padding:18px 20px 8px 20px;font-size:14px;line-height:1.7;color:#374151;word-break:keep-all;">
      기관검색은 <b>대분류와 중분류만</b> 반영됩니다.<br>
      소분류 등 세부 서비스 필요 시 <b>프로그램명</b>을 입력해 주세요.
    </div>

    <div style="display:flex;gap:10px;justify-content:flex-end;padding:16px 20px 20px 20px;">
      <button type="button" onclick="moveComboGuideModal()" style="height:42px;padding:0 16px;border:none;border-radius:10px;background:#2563eb;color:#ffffff;font-size:14px;font-weight:700;cursor:pointer;">
        확인
      </button>
      <button type="button" onclick="closeComboGuideModal()" style="height:42px;padding:0 16px;border:none;border-radius:10px;background:#e5e7eb;color:#374151;font-size:14px;font-weight:700;cursor:pointer;">
        취소
      </button>
    </div>

  </div>
</div>

<div class="loading" id="loading">


  <div class="loading-box">

    <div class="spinner"></div>

<p id="loadingText" style="margin:14px 0 0 0;font-weight:700;font-size:15px;line-height:1.35;text-align:center;">
  AI가 사례를 분석 중입니다
</p>

<p id="loadingSubText" style="margin:8px 0 0 0;font-size:13px;line-height:1.5;color:#6b7280;text-align:center;word-break:keep-all;">
  어르신의 건강상태와 생활불편을 확인하고 있습니다.
</p>

<div class="loading-step-bar">
  <div class="loading-step active"></div>
  <div class="loading-step"></div>
  <div class="loading-step"></div>
  <div class="loading-step"></div>
</div>

<div class="ai-model-wrap" style="margin-top:28px;">
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

const loadingText = document.getElementById("loadingText");
const loadingSubText = document.getElementById("loadingSubText");
const loadingSteps = document.querySelectorAll(".loading-step");

const loadingMessages = [
  ["AI가 사례를 분석 중입니다", "어르신의 건강상태와 생활불편을 확인하고 있습니다."],
  ["욕구를 분류하고 있습니다", "식사, 이동, 건강, 정서 등 돌봄 필요 상황을 살펴보고 있습니다."],
  ["서비스 목록과 비교 중입니다", "입력한 사례와 관련 있는 통합돌봄 서비스를 찾고 있습니다."],
  ["추천 결과를 정리하고 있습니다", "대분류, 중분류, 서비스내용, 추천이유를 정리하고 있습니다."]
];

let loadingMessageIndex = 0;
let loadingMessageTimer = null;

function startLoadingMessages(){
  loadingMessageIndex = 0;

  if(loadingText && loadingSubText){
    loadingText.innerText = loadingMessages[0][0];
    loadingSubText.innerText = loadingMessages[0][1];
  }

  loadingSteps.forEach(function(step, idx){
    if(idx === 0){
      step.classList.add("active");
    }else{
      step.classList.remove("active");
    }
  });

  loadingMessageTimer = setInterval(function(){
    loadingMessageIndex++;

    if(loadingMessageIndex >= loadingMessages.length){
      loadingMessageIndex = loadingMessages.length - 1;
      clearInterval(loadingMessageTimer);
    }

    if(loadingText && loadingSubText){
      loadingText.innerText = loadingMessages[loadingMessageIndex][0];
      loadingSubText.innerText = loadingMessages[loadingMessageIndex][1];
    }
    loadingSteps.forEach(function(step, idx){
      if(idx <= loadingMessageIndex){
        step.classList.add("active");
      }else{
        step.classList.remove("active");
      }
    });

  }, 4500);
}

const originalIcon = voiceBtn ? voiceBtn.innerHTML : "";
let recognition = null;
let isRecording = false;

function handleDescSidoChange(form){
  document.getElementById("descAction").value = "change_sido";
  form.submit();
}

function handleDescSigunguChange(form){
  document.getElementById("descAction").value = "change_sigungu";
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


let serviceTableHistoryOpen = false;

function openServiceTableModal(){
  const modal = document.getElementById("serviceTableModal");
  if(modal){
    modal.style.display = "flex";
  }

  if(!serviceTableHistoryOpen){
    history.pushState({ modal: "serviceTable" }, "", location.href);
    serviceTableHistoryOpen = true;
  }
}

function closeServiceTableModal(){
  const modal = document.getElementById("serviceTableModal");
  if(modal){
    modal.style.display = "none";
  }

  serviceTableHistoryOpen = false;
}

function closeServiceTableModalByBg(e){
  if(e.target.id === "serviceTableModal"){
    closeServiceTableModal();
  }
}

window.addEventListener("popstate", function(e){
  const modal = document.getElementById("serviceTableModal");

  if(modal && modal.style.display === "flex"){
    modal.style.display = "none";
    serviceTableHistoryOpen = false;
    history.pushState({ page: "desc" }, "", location.href);
    return;
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

let comboGuideTargetHref = "";

function openComboGuideModal(href){
  comboGuideTargetHref = href || "";

  const modal = document.getElementById("comboGuideModal");
  if(modal){
    modal.style.display = "flex";
  }

  return false;
}

function closeComboGuideModal(){
  const modal = document.getElementById("comboGuideModal");
  if(modal){
    modal.style.display = "none";
  }
}

function moveComboGuideModal(){
  const modal = document.getElementById("comboGuideModal");
  if(modal){
    modal.style.display = "none";
  }

  if(comboGuideTargetHref){
    window.location.href = comboGuideTargetHref;
  }
}

function showReason(btn, targetId){
  const card = btn.closest(".result-card");
  if(!card) return;

  const tabs = card.querySelectorAll(".sub-service-tab");
  const reasons = card.querySelectorAll(".reason-box");

  tabs.forEach(function(tab){
    tab.classList.remove("active");
  });

  reasons.forEach(function(reason){
    reason.style.display = "none";
  });

  btn.classList.add("active");

  const target = document.getElementById(targetId);
  if(target){
    target.style.display = "block";
  }
}


window.addEventListener("pageshow", function(){
  const modal = document.getElementById("comboGuideModal");
  if(modal){
    modal.style.display = "none";
  }
});

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

function finishVoiceUI(){
  isRecording = false;
  setVoiceButtonRecording(false);
  playBeep("end");

  const overlay = document.getElementById("voiceOverlay");
  if(overlay){
    overlay.style.display = "none";
  }
}

function submitVoiceText(transcript){
  if(!transcript) {
    finishVoiceUI();
    return;
  }

  queryInput.value = transcript;

  finishVoiceUI();

  if(loading){
    loading.style.display = "flex";
  }

  startLoadingMessages();

  document.getElementById("descAction").value = "search";
  searchForm.submit();
}

window.__careNaviVoiceResult = function(text){
  submitVoiceText(text);
};

window.__careNaviVoiceEnd = function(){
  finishVoiceUI();
};

function startVoiceInput(event){
  if(event) event.preventDefault();

  const isCareNaviApp = navigator.userAgent.indexOf("CareNaviApp") !== -1;

  if(isCareNaviApp && window.AndroidVoice){
    if(isRecording){
      if(window.AndroidVoice.stopVoiceSearch){
        window.AndroidVoice.stopVoiceSearch();
      }
      finishVoiceUI();
      return;
    }

    isRecording = true;
    setVoiceButtonRecording(true);
    playBeep("start");

    const overlay = document.getElementById("voiceOverlay");
    if(overlay){
      overlay.style.display = "block";
    }

    window.AndroidVoice.startVoiceSearch();
    return;
  }

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
    submitVoiceText(transcript);
  };

  recognition.onend = function(){
    finishVoiceUI();
  };

  recognition.start();
}

function openImage(){
  document.getElementById("imgInput").click();
}

document.getElementById("imgInput").addEventListener("change", async function(){
  const file = this.files[0];
  if(!file) return;

  const formData = new FormData();
  formData.append("image", file);

  if(loading){
    loading.style.display = "flex";
  }

  if(loadingText){
    loadingText.innerText = "사진 속 글자를 분석하고 있습니다";
  }

  if(loadingSubText){
    loadingSubText.innerText = "촬영한 이미지에서 사례 내용을 추출하는 중입니다.";
  }

  loadingSteps.forEach(function(step){
    step.classList.remove("active");
  });

  try{
    const res = await fetch("/ocr", {
      method: "POST",
      body: formData
    });

    const data = await res.json();
    const ocrText = (data.text || "").trim();

    if(!ocrText){
      if(loading){
        loading.style.display = "none";
      }

      alert("사진에서 글자를 인식하지 못했습니다. 다시 촬영해 주세요.");
      return;
    }

    queryInput.value = ocrText;

    startLoadingMessages();

    document.getElementById("descAction").value = "search";
    searchForm.submit();

  }catch(e){
    if(loading){
      loading.style.display = "none";
    }

    alert("이미지 인식 실패");
  }
});

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
      startLoadingMessages();
    }
  });
}

function resetDescPage(){
  window.location.href = "/desc?action=reset_region";
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

function getPrivacyTodayKey(){
  const d = new Date();
  return "privacy_hide_" + d.getFullYear() + "-" + (d.getMonth()+1) + "-" + d.getDate();
}

function closePrivacyModal(){
  const modal = document.getElementById("privacyModal");
  const check = document.getElementById("hidePrivacyToday");

  if(check && check.checked){
    localStorage.setItem(getPrivacyTodayKey(), "Y");
  }

  // 확인 눌렀으면 이 세션 동안 /desc 내부 재로드 시 다시 안 뜨게
  try{ sessionStorage.setItem("desc_privacy_shown", "Y"); }catch(e){}

  if(modal){
    modal.style.display = "none";
  }
}

window.addEventListener("load", function(){
  const modal = document.getElementById("privacyModal");
  if(!modal) return;

  // /desc 밖에서 새로 진입한 경우(홈 등) → desc_privacy_shown 초기화
  const ref = document.referrer;
  const comingFromDesc = ref && ref.indexOf("/desc") !== -1;
  if(!comingFromDesc){
    try{ sessionStorage.removeItem("desc_privacy_shown"); }catch(e){}
  }

  // 오늘 안 보기 체크했으면 무조건 숨김
  if(localStorage.getItem(getPrivacyTodayKey()) === "Y"){
    modal.style.display = "none";
    return;
  }

  // 이 세션에서 이미 확인 눌렀고, /desc 내부 이동이면 숨김
  try{
    if(sessionStorage.getItem("desc_privacy_shown") === "Y"){
      modal.style.display = "none";
      return;
    }
  }catch(e){}

  modal.style.display = "flex";
});

</script>

  <div class="tip-notice">
    <p>※ 입력한 사례와 유사한 <b class="highlight">통합돌봄 서비스를 최대 30가지</b> 추천합니다.</p>
    <p>※ 통합판정조사, 지자체 조사의 <b class="highlight">참고사항 전문</b>을 모두 입력해도 <b class="highlight">AI가 추천서비스를 안내</b>합니다.</p>

    <div class="privacy-warning">
      <span class="privacy-warning-icon siren-icon" aria-hidden="true">
        <svg class="siren-svg" viewBox="0 0 96 110" xmlns="http://www.w3.org/2000/svg">
          <line x1="48" y1="6" x2="48" y2="20" stroke="#111827" stroke-width="7" stroke-linecap="round"/>
          <line x1="17" y1="22" x2="28" y2="33" stroke="#111827" stroke-width="7" stroke-linecap="round"/>
          <line x1="79" y1="22" x2="68" y2="33" stroke="#111827" stroke-width="7" stroke-linecap="round"/>

          <path d="M28 80V62C28 48 36.8 39 48 39C59.2 39 68 48 68 62V80Z"
                fill="#ef4444"
                stroke="#111827"
                stroke-width="6"
                stroke-linejoin="round"/>

          <path d="M39 42C45 44 51 56 52 80H28V62C28 52 32.5 45 39 42Z"
                fill="rgba(255,255,255,0.18)"/>

          <rect x="18" y="76" width="60" height="20" rx="10"
                fill="#e5e7eb"
                stroke="#111827"
                stroke-width="6"/>
        </svg>
      </span>

      <span class="privacy-warning-text"> 성명, 주민등록번호 등 개인정보를 입력하지 마세요. <br>개인정보 입력으로 인한 책임은 사용자에게 있습니다.</span>
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
            "패드", "복지용구", "방문보건"
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
            "요실금팬티", "패드", "전동침대", "병원침대",
            "욕창매트", "욕창방지", "자세변환", "체위변경",
            "경사로", "문턱", "턱",
            "배회감지기", "배회", "길잃음", "길 잃", "길을 잃",
            "길을 잃어버림", "집을 못 찾", "집에 못 오",
            "실종", "위치확인", "위치 확인", "위치추적", "GPS", "gps"
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
            "패드", "복지용구", "방문보건"
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
             grouped_service_results=build_grouped_service_results(service_results),
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
<style>
*{ box-sizing:border-box; margin:0; padding:0; }
body{ background:#f4f6fb; font-family:'Pretendard',sans-serif; color:#111827; font-size:13px; }
.page-wrap{ max-width:860px; margin:0 auto; padding:20px 16px 60px 16px; min-width:0; word-break:keep-all; }

/* ── 상단 바 ── */
.top-bar{ display:flex; justify-content:space-between; align-items:center; margin-bottom:14px; gap:10px; flex-wrap:wrap; padding:6px 0; }
.home-btn{ display:inline-flex; align-items:center; justify-content:center; gap:5px; height:34px; padding:0 15px; border-radius:8px; background:#ffffff; border:1px solid #e5e7eb; color:#6b7280; text-decoration:none; font-size:13px; font-weight:600; box-shadow:0 2px 6px rgba(15,23,42,0.08); transition:all .15s; }
.home-btn:hover{ background:#f3f4f6; color:#374151; }
.btn-group{ display:flex; gap:10px; }
.reset-btn{ display:inline-flex; align-items:center; justify-content:center; gap:5px; height:34px; padding:0 15px; border-radius:8px; background:#ffffff; border:1px solid #e5e7eb; color:#6b7280; font-size:13px; font-weight:600; cursor:pointer; box-shadow:0 2px 6px rgba(15,23,42,0.08); transition:all .15s; }
.reset-btn:hover{ background:#f3f4f6; color:#374151; }

/* ── 폼 카드 ── */
.form-card{ background:#fff; border-radius:16px; padding:28px 24px; box-shadow:0 6px 18px rgba(0,0,0,0.07); overflow-x:auto; }
.form-title{ text-align:left; font-size:18px; font-weight:900; margin-bottom:20px; letter-spacing:-0.3px; border:none; border-left:5px solid #5b7ee5; padding:6px 0 6px 14px; color:#2d3a6e; }
.section-header{ background:#5b7ee5; color:#fff; font-size:13px; font-weight:700; padding:6px 10px; border-radius:4px; margin:18px 0 8px 0; }
.section-header:first-of-type{ margin-top:0; }

/* ── 치매 박스 ── */
.dementia-box{ background:linear-gradient(135deg,#eef2ff,#e0e7ff); padding:16px 18px; border-radius:12px; margin-bottom:16px; border:1px solid #c7d2fe; }
.dementia-box b{ font-size:13.5px; display:block; margin-bottom:10px; }
.dementia-options{ display:flex; width:100%; align-items:center; justify-content:space-between; gap:0; }
.dementia-options label{ flex:1; display:flex; justify-content:center; align-items:center; gap:6px; white-space:nowrap; margin:0; font-size:13px; cursor:pointer; }
.dementia-options input[type=radio]{ width:auto !important; margin:0; flex:0 0 auto; transform:scale(1.1); border:revert; padding:revert; border-radius:revert; }

/* ── 질문 박스 ── */
.question-box{ background:#f8fafc; padding:18px; border-radius:12px; margin-bottom:10px; border:1px solid #e5e7eb; transition:0.18s ease; }
.question-box.active{ border:2px solid #5b7ee5; background:#eef2ff; box-shadow:0 6px 18px rgba(75,110,220,0.12); }
.question-title{ display:block; font-size:13.5px; line-height:1.6; word-break:keep-all; overflow-wrap:break-word; padding-left:22px; text-indent:-22px; }
.options{ margin-top:10px; display:flex; flex-direction:column; gap:8px; }
.options label{ display:flex; align-items:center; gap:8px; cursor:pointer; line-height:1.5; font-size:12.5px; }
.options input[type=radio]{ width:auto !important; flex:0 0 auto; transform:scale(1.05); border:revert; padding:revert; border-radius:revert; }

/* ── 검사 버튼 ── */
.submit-btn{ margin-top:18px; width:100%; height:44px; border:none; border-radius:10px; background:#5b7ee5; color:#fff; font-size:14px; font-weight:700; cursor:pointer; box-shadow:0 2px 8px rgba(75,110,220,0.25); transition:all .15s; }
.submit-btn:hover{ background:#4a6cd4; transform:translateY(-1px); }

/* ── 점수 배너 ── */
.score-banner{ position:fixed; top:100px; right:80px; z-index:998; width:132px; padding:14px 12px; border-radius:22px; background:rgba(255,255,255,0.92); backdrop-filter:blur(10px); -webkit-backdrop-filter:blur(10px); border:1px solid rgba(191,219,254,0.95); box-shadow:0 18px 38px rgba(75,110,220,0.18); text-align:center; transition:all 0.2s ease; }
.score-banner.disabled{ opacity:0.62; transform:scale(0.98); }
.score-badge{ width:72px; height:72px; margin:0 auto 10px auto; border-radius:50%; background:linear-gradient(135deg,#5b7ee5,#a5b4fc); display:flex; flex-direction:column; align-items:center; justify-content:center; color:white; box-shadow:0 10px 22px rgba(75,110,220,0.28); }
.score-badge-label{ font-size:10px; opacity:0.92; line-height:1; margin-bottom:4px; }
.score-value{ font-size:28px; font-weight:800; line-height:1; }
.score-meta{ display:none; }
.score-progress-wrap{ width:100%; height:8px; background:#eef2ff; border-radius:999px; overflow:hidden; margin-bottom:3px; }
.score-progress-bar{ height:100%; width:0%; border-radius:999px; background:linear-gradient(90deg,#a5b4fc,#5b7ee5); transition:width 0.22s ease; }
.score-status{ font-size:11px; color:#2d3a6e; line-height:1.45; word-break:keep-all; min-height:34px; font-weight:600; }
.score-chip{ margin-top:8px; display:inline-block; padding:5px 8px; border-radius:999px; font-size:10px; font-weight:700; background:#eef2ff; color:#5b7ee5; }

/* 상태별 색감 */
.score-banner.state-low .score-badge{ background:linear-gradient(135deg,#22c55e,#4ade80); box-shadow:0 10px 22px rgba(34,197,94,0.24); }
.score-banner.state-low .score-progress-bar{ background:linear-gradient(90deg,#86efac,#22c55e); }
.score-banner.state-low .score-status{ color:#166534; }
.score-banner.state-low .score-chip{ background:#f0fdf4; color:#16a34a; }

.score-banner.state-mid .score-badge{ background:linear-gradient(135deg,#f59e0b,#fbbf24); box-shadow:0 10px 22px rgba(245,158,11,0.24); }
.score-banner.state-mid .score-progress-bar{ background:linear-gradient(90deg,#fde68a,#f59e0b); }
.score-banner.state-mid .score-status{ color:#92400e; }
.score-banner.state-mid .score-chip{ background:#fffbeb; color:#d97706; }

.score-banner.state-high .score-badge{ background:linear-gradient(135deg,#ef4444,#f87171); box-shadow:0 10px 22px rgba(239,68,68,0.24); }
.score-banner.state-high .score-progress-bar{ background:linear-gradient(90deg,#fca5a5,#ef4444); }
.score-banner.state-high .score-status{ color:#991b1b; }
.score-banner.state-high .score-chip{ background:#fef2f2; color:#dc2626; }

.score-banner.state-dementia .score-badge{ background:linear-gradient(135deg,#7c3aed,#a78bfa); box-shadow:0 10px 22px rgba(124,58,237,0.24); }
.score-banner.state-dementia .score-progress-bar{ background:linear-gradient(90deg,#c4b5fd,#7c3aed); width:100% !important; }
.score-banner.state-dementia .score-status{ color:#5b21b6; }
.score-banner.state-dementia .score-chip{ background:#f5f3ff; color:#7c3aed; }

/* ── 결과 안내 박스 ── */
.guide-box{ margin-top:16px; padding:14px 18px; border-radius:12px; background:#fff7ed; border:1px solid #fdba74; color:#9a3412; font-size:13px; line-height:1.7; display:flex; align-items:flex-start; gap:8px; }

/* ── 모달 ── */
.modal-overlay{ display:none; position:fixed; inset:0; background:rgba(0,0,0,.5); z-index:999; padding-top:6vh; overflow:auto; -webkit-overflow-scrolling:touch; }
.modal-box{ background:white; margin:0 auto; position:absolute; top:8%; left:0; right:0; padding:18px 22px 22px 22px; width:92%; max-width:460px; border-radius:14px; text-align:center; box-shadow:0 10px 25px rgba(0,0,0,0.15); }
.modal-result-area{ background:#eef2ff; border-radius:10px; padding:14px; margin-bottom:18px; }
.modal-result-area p{ font-size:18px; line-height:1.6; margin:0; }
.modal-criteria{ text-align:left; font-size:13px; line-height:1.6; color:#444; background:#fafafa; padding:14px; border-radius:8px; }
.modal-btn{ margin-top:18px; width:100%; height:44px; border:none; border-radius:10px; background:#5b7ee5; color:#fff; font-size:14px; font-weight:700; cursor:pointer; }
.modal-btn:hover{ background:#4a6cd4; }

/* ── 인쇄 ── */
@media print{
  body{ background:white; }
  .top-bar,.score-banner{ display:none !important; }
  .page-wrap{ padding:0; }
  .form-card{ box-shadow:none; border-radius:0; padding:10px; }
}

/* ── 모바일 ── */
@media (max-width:600px){
  .page-wrap{ padding:10px 6px 60px 6px; }
  .form-card{ padding:14px 10px; }
  .form-title{ font-size:14px; padding:4px 0 4px 12px; }
  .top-bar{ flex-wrap:wrap; gap:6px; justify-content:flex-start; }
  .btn-group{ margin-left:0; }
  .home-btn,.reset-btn{ height:30px; font-size:11.5px; padding:0 10px; }
  .section-header{ font-size:11.5px; padding:5px 8px; }
  .question-title{ font-size:12.5px; line-height:1.55; padding-left:18px; text-indent:-18px; }
  .options label{ font-size:11.5px; }
  .dementia-box{ padding:12px 14px; }
  .dementia-box b{ font-size:12.5px; }
  .dementia-options label{ font-size:12px; }

  .score-banner{ position:fixed; top:10px; right:10px; width:85px; padding:8px 6px; border-radius:16px; z-index:10; }
  .score-badge{ width:44px; height:44px; }
  .score-value{ font-size:18px; }
  .score-meta{ font-size:9px; }
  .score-status{ font-size:10px; line-height:1.2; min-height:20px; }
  .score-chip{ font-size:10px; padding:3px 6px; }

  .modal-overlay{ padding-top:0 !important; }
  .modal-box{ top:2% !important; }
}
</style>
</head>

<body>
<div class="page-wrap">

  <div class="top-bar">
    <a href="/home" class="home-btn">&#8962; 홈으로</a>
    <div class="btn-group">
      <button type="button" id="gt-reset" class="reset-btn" onclick="resetCarePage()">&#8635; 다시 입력</button>
    </div>
  </div>

  <div class="form-card">
    <div class="form-title">통합돌봄 사전조사</div>

    <div id="scoreBanner" class="score-banner disabled">
      <div class="score-badge">
        <div class="score-badge-label">점수</div>
        <div id="scoreValue" class="score-value">0</div>
      </div>
      <div class="score-meta">응답 <span id="answeredCount">0</span>/7 · 최대 14점</div>
      <div class="score-progress-wrap">
        <div id="scoreProgressBar" class="score-progress-bar"></div>
      </div>
      <div id="scoreStatus" class="score-status">치매 여부를 먼저 선택하세요</div>
      <div id="scoreChip" class="score-chip">사전 확인 필요</div>
    </div>

    <form id="careForm">

      <div id="gt-dementia">
      <div class="section-header">&#9632; 치매 관련 약 복용 여부</div>
      <div class="dementia-box">
        <b>치매 관련 약을 복용 중이십니까?</b>
        <div class="dementia-options">
          <label><input type="radio" name="dementia" value="y"> 예</label>
          <label><input type="radio" name="dementia" value="n"> 아니오</label>
        </div>
      </div>
      </div>

      <div id="gt-adl" class="section-header">&#9632; 일상생활 수행능력(ADL) 조사</div>
      <div id="adlSection">
        {% for i,q in questions %}
        <div class="question-box">
          <b class="question-title">{{i+1}}) {{q}}</b>
          <div class="options">
            <label><input type="radio" name="q{{i}}" value="0"> 도움 없이 혼자서 수행 가능 (0점)</label>
            <label><input type="radio" name="q{{i}}" value="1"> 보조도구(지팡이 등)를 잡고 수행 가능 (1점)</label>
            <label><input type="radio" name="q{{i}}" value="2"> 타인이 도와줘야 수행 가능 (2점)</label>
          </div>
        </div>
        {% endfor %}

        <button type="submit" class="submit-btn">검사하기</button>
      </div>

    </form>
  </div>

</div>

<!-- 결과 모달 -->
<div id="resultModal" class="modal-overlay">
  <div class="modal-box">
    <h3 id="modalTitle" style="margin-top:0;margin-bottom:12px;">사전조사 결과 안내</h3>
    <div class="modal-result-area">
      <p id="r_text"></p>
    </div>
    <div class="modal-criteria">
      <b>통합돌봄 지원 기준</b><br><br>
      ① 치매약 복약 중인 경우<br>
      → 일상생활 수행능력과 관계없이 통합돌봄 지원 대상<br><br>
      ② 일상생활수행능력(ADL) 점수 기준<br>
      • 0~1점 : 지자체 사업 안내 후 종결<br>
      • 2~3점 : 지자체 자체조사 후 지원 검토<br>
      • 4점 이상 : 통합판정조사 대상<br><br>
      <span style="font-size:11px;color:#666;">
        ※ 본 결과는 통합돌봄 서비스 안내를 위한 참고용 사전조사입니다.<br>
        최종 지원 여부는 지자체 및 공단의 추가 조사 후 결정됩니다.
      </span>
    </div>
    <button onclick="closeModal()" class="modal-btn">확인</button>
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
    if(checked){ score += Number(checked.value); }
  }
  return score;
}

function getAnsweredCount(){
  let count = 0;
  for(let i=0; i<7; i++){
    const checked = document.querySelector('input[name="q'+i+'"]:checked');
    if(checked){ count += 1; }
  }
  return count;
}

function getBannerState(score, dementiaValue){
  if(!dementiaValue) return "disabled";
  if(dementiaValue === "y") return "state-dementia";
  if(score <= 1) return "state-low";
  else if(score <= 3) return "state-mid";
  else return "state-high";
}

function getScoreStatusText(score, dementiaValue){
  if(!dementiaValue) return "치매 여부를 먼저 선택하세요";
  if(dementiaValue === "y") return "치매약 복용으로 별도 조사 없이 대상입니다";
  if(score <= 1) return "지자체 사업 안내 후 종결 구간입니다";
  else if(score <= 3) return "지자체 자체조사 대상 구간입니다";
  else return "통합판정조사 대상 구간입니다";
}

function getChipText(score, dementiaValue){
  if(!dementiaValue) return "사전 확인 필요";
  if(dementiaValue === "y") return "치매약 복용";
  if(score <= 1) return "0~1점";
  else if(score <= 3) return "2~3점";
  else return "4점 이상";
}

function resetCarePage(){
  try{ sessionStorage.removeItem("care_form_state"); }catch(e){}
  window.location.href = "/care";
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
  if(dementiaValue === "y") progress = 100;
  scoreProgressBar.style.width = progress + "%";

  banner.classList.remove("disabled","state-low","state-mid","state-high","state-dementia");
  const nextState = getBannerState(score, dementiaValue);
  if(nextState === "disabled") banner.classList.add("disabled");
  else banner.classList.add(nextState);
}

/* ── 상태 저장/복원 ── */
var CARE_STORAGE_KEY = "care_form_state";

function saveCareState(){
  var state = {};
  var dementia = document.querySelector('input[name="dementia"]:checked');
  state.dementia = dementia ? dementia.value : null;
  state.adl = {};
  for(var i=0;i<7;i++){
    var r = document.querySelector('input[name="q'+i+'"]:checked');
    state.adl[i] = r ? r.value : null;
  }
  try{ sessionStorage.setItem(CARE_STORAGE_KEY, JSON.stringify(state)); }catch(e){}
}

function restoreCareState(){
  var raw;
  try{ raw = sessionStorage.getItem(CARE_STORAGE_KEY); }catch(e){}
  if(!raw) return;
  var state;
  try{ state = JSON.parse(raw); }catch(e){ return; }

  if(state.dementia){
    var dr = document.querySelector('input[name="dementia"][value="'+state.dementia+'"]');
    if(dr){
      dr.checked = true;
      if(state.dementia === "y"){
        document.getElementById("adlSection").style.opacity = "0.4";
      }
    }
  }

  for(var i=0;i<7;i++){
    if(state.adl && state.adl[i]){
      var ar = document.querySelector('input[name="q'+i+'"][value="'+state.adl[i]+'"]');
      if(ar){
        ar.checked = true;
        var box = ar.closest(".question-box");
        if(box) box.classList.add("active");
      }
    }
  }

  updateScoreBanner();
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
    if(box) box.classList.add("active");

    updateScoreBanner();
    saveCareState();
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
    saveCareState();
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

  if(dementia.value === "y") return;

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

/* 페이지 로드 시 상태 복원 */
restoreCareState();
updateScoreBanner();

/* ── 사전조사 가이드 (한 화면에 전체 표시) ── */
function careGuideStart() {
  if (sessionStorage.getItem('cg_done')) return;

  var isMobile = window.innerWidth < 600;
  var vw = window.innerWidth;
  var vh = window.innerHeight;

  window.scrollTo(0, 0);

  var overlay = document.createElement('div');
  overlay.style.cssText = 'position:fixed;inset:0;z-index:9998;background:rgba(0,0,0,0.62);';
  document.body.appendChild(overlay);

  var prevOverflow = document.body.style.overflow;
  document.body.style.overflow = 'hidden';

  var bubbles = [];

  /* ── 공통 헬퍼: 하이라이트 ── */
  function addHighlight(elId) {
    var el = document.getElementById(elId);
    if (!el) return null;
    var pad = isMobile ? 4 : 6;
    var r = el.getBoundingClientRect();
    var hl = document.createElement('div');
    hl.style.cssText = [
      'position:fixed;z-index:9999;pointer-events:none;border-radius:7px;',
      'border:2px solid rgba(255,255,255,0.9);',
      'box-shadow:0 0 0 3px rgba(75,110,220,0.55);',
      'top:'+(r.top-pad)+'px;left:'+(r.left-pad)+'px;',
      'width:'+(r.width+pad*2)+'px;height:'+(r.height+pad*2)+'px;'
    ].join('');
    document.body.appendChild(hl);
    bubbles.push(hl);
    return r;
  }

  /* ── 공통 헬퍼: 말풍선 만들기 ── */
  function makeBubble(title, text, w) {
    var fs      = isMobile ? '10.5px' : '12px';
    var fsTitle = isMobile ? '11px'   : '12.5px';
    var bpd     = isMobile ? '8px 10px 7px' : '13px 16px 12px';
    var b = document.createElement('div');
    b.style.cssText = [
      'position:fixed;z-index:10000;background:#fff;border-radius:11px;',
      'padding:'+bpd+';width:'+w+'px;',
      'box-shadow:0 5px 20px rgba(0,0,0,0.22);',
      'font-family:inherit;pointer-events:none;'
    ].join('');
    b.innerHTML =
      '<div style="font-size:'+fsTitle+';font-weight:700;color:#3b5cc0;margin-bottom:4px;">&#128161; '+title+'</div>'+
      '<div style="font-size:'+fs+';color:#374151;line-height:1.55;word-break:keep-all;">'+text+'</div>';
    document.body.appendChild(b);
    bubbles.push(b);
    return b;
  }

  /* ── 공통 헬퍼: 화살표 ── */
  function addArrow(bubble, dir, posFromEdge) {
    var arrow = document.createElement('div');
    arrow.style.position = 'absolute';
    arrow.style.width = '0';
    arrow.style.height = '0';
    if (dir === 'left') {
      /* 화살표가 말풍선 왼쪽에서 왼쪽으로 뾰족 → 왼쪽의 타겟을 가리킴 */
      arrow.style.borderTop = '8px solid transparent';
      arrow.style.borderBottom = '8px solid transparent';
      arrow.style.borderRight = '8px solid #fff';
      arrow.style.left = '-8px';
      arrow.style.top = posFromEdge + 'px';
    } else if (dir === 'right') {
      /* 화살표가 말풍선 오른쪽에서 오른쪽으로 뾰족 → 오른쪽의 타겟을 가리킴 */
      arrow.style.borderTop = '8px solid transparent';
      arrow.style.borderBottom = '8px solid transparent';
      arrow.style.borderLeft = '8px solid #fff';
      arrow.style.right = '-8px';
      arrow.style.top = posFromEdge + 'px';
    } else if (dir === 'up') {
      /* 화살표가 말풍선 위에서 위로 뾰족 → 위의 타겟을 가리킴 */
      arrow.style.borderLeft = '8px solid transparent';
      arrow.style.borderRight = '8px solid transparent';
      arrow.style.borderBottom = '8px solid #fff';
      arrow.style.top = '-8px';
      arrow.style.left = posFromEdge + 'px';
    } else if (dir === 'down') {
      arrow.style.borderLeft = '8px solid transparent';
      arrow.style.borderRight = '8px solid transparent';
      arrow.style.borderTop = '8px solid #fff';
      arrow.style.bottom = '-8px';
      arrow.style.left = posFromEdge + 'px';
    }
    bubble.appendChild(arrow);
  }

  /* ========================================
     ① 치매약 복약 여부 — 말풍선을 타겟의 오른쪽 반에 배치, 꼬리는 왼쪽 옆면
     ======================================== */
  var r1 = addHighlight('gt-dementia');
  if (r1) {
    var bw1 = isMobile ? Math.min(Math.floor(vw * 0.48), 195) : 230;
    var b1 = makeBubble('치매약 복약 여부', '치매약을 복약하고 있는지 여부를 <b>먼저 체크</b>해 주세요.', bw1);
    requestAnimationFrame(function(){
      var bh1 = b1.offsetHeight;
      /* 가로: 타겟 오른쪽 절반 영역에 배치 (화면 안에 들어오게 clamp) */
      var bubbleLeft = Math.min(r1.left + r1.width * 0.55, vw - bw1 - 6);
      bubbleLeft = Math.max(6, bubbleLeft);
      /* 세로: 타겟 세로 중앙 */
      var bubbleTop = Math.max(6, r1.top + r1.height/2 - bh1/2);
      if (bubbleTop + bh1 > vh - 60) bubbleTop = vh - 60 - bh1;
      b1.style.top = bubbleTop + 'px';
      b1.style.left = bubbleLeft + 'px';
      /* 꼬리: 왼쪽 옆면 → 타겟 왼쪽 부분을 가리킴 */
      var arrowTop = Math.max(8, Math.min(r1.top + r1.height/2 - bubbleTop - 8, bh1 - 24));
      addArrow(b1, 'left', arrowTop);
    });
  }

  /* ========================================
     ② ADL 조사 — 섹션헤더 + 1~2번 문항까지 큰 하이라이트
     ======================================== */
  var adlHeader = document.getElementById('gt-adl');
  var adlQuestions = document.querySelectorAll('#adlSection .question-box');
  var r2 = null;
  if (adlHeader && adlQuestions.length >= 3) {
    var rH = adlHeader.getBoundingClientRect();
    var rQ2 = adlQuestions[2].getBoundingClientRect(); /* 3번 문항 */
    /* 헤더 top ~ 3번 문항 bottom 을 합친 영역 */
    var pad2 = isMobile ? 4 : 6;
    var unionTop = Math.min(rH.top, rQ2.top);
    var unionBottom = Math.max(rH.bottom, rQ2.bottom);
    var unionLeft = Math.min(rH.left, rQ2.left);
    var unionRight = Math.max(rH.right, rQ2.right);
    r2 = { top: unionTop, bottom: unionBottom, left: unionLeft, right: unionRight,
           width: unionRight - unionLeft, height: unionBottom - unionTop };
    var hl2 = document.createElement('div');
    hl2.style.cssText = [
      'position:fixed;z-index:9999;pointer-events:none;border-radius:7px;',
      'border:2px solid rgba(255,255,255,0.9);',
      'box-shadow:0 0 0 3px rgba(75,110,220,0.55);',
      'top:'+(r2.top-pad2)+'px;left:'+(r2.left-pad2)+'px;',
      'width:'+(r2.width+pad2*2)+'px;height:'+(r2.height+pad2*2)+'px;'
    ].join('');
    document.body.appendChild(hl2);
    bubbles.push(hl2);
  }
  if (r2) {
    var bw2 = isMobile ? Math.min(Math.floor(vw * 0.48), 195) : 230;
    var b2 = makeBubble('ADL 조사', '일상생활 수행능력(ADL) 항목에서 <b>해당하는 항목을 눌러</b> 주세요.', bw2);
    requestAnimationFrame(function(){
      var bh2 = b2.offsetHeight;
      /* 가로: 타겟 왼쪽 절반 영역에 배치 */
      var bubbleLeft = Math.max(6, r2.left + r2.width * 0.45 - bw2);
      /* 세로: 타겟 세로 중앙 */
      var bubbleTop = isMobile
              ? Math.max(6, r2.top + 100)
              : Math.max(6, r2.top + r2.height/2 - bh2/2);
      if (bubbleTop + bh2 > vh - 60) bubbleTop = vh - 60 - bh2;
      b2.style.top = bubbleTop + 'px';
      b2.style.left = bubbleLeft + 'px';
      /* 꼬리: 오른쪽 옆면 → 타겟 오른쪽 부분을 가리킴 */
      var arrowTop = Math.max(8, Math.min(r2.top + r2.height/2 - bubbleTop - 8, bh2 - 24));
      addArrow(b2, 'right', arrowTop);
    });
  }

  /* ========================================
     ③ 다시 입력 — 말풍선을 타겟 아래에
     ======================================== */
  var r3 = addHighlight('gt-reset');
  if (r3) {
    var bw3 = isMobile ? Math.min(Math.floor(vw * 0.48), 190) : 220;
    var b3 = makeBubble('다시 입력', '체크를 초기화하고 싶을 경우 이 버튼을 눌러주세요.', bw3);
    requestAnimationFrame(function(){
      var bh3 = b3.offsetHeight;
      var bubbleTop = r3.bottom + 18;
      if (bubbleTop + bh3 > vh - 60) bubbleTop = r3.top - bh3 - 18;
      var bubbleLeft = Math.max(4, Math.min(r3.left + r3.width/2 - bw3/2, vw - bw3 - 4));
      b3.style.top = bubbleTop + 'px';
      b3.style.left = bubbleLeft + 'px';
      var arrowLeft = Math.max(10, Math.min(r3.left + r3.width/2 - bubbleLeft - 8, bw3 - 26));
      if (bubbleTop > r3.bottom) {
        addArrow(b3, 'up', arrowLeft);
      } else {
        addArrow(b3, 'down', arrowLeft);
      }
    });
  }

  /* 확인 버튼 */
  var confirmBtn = document.createElement('button');
  confirmBtn.textContent = '확인';
  confirmBtn.style.cssText = [
    'position:fixed;z-index:10001;',
    'left:50%;transform:translateX(-50%);bottom:18%;',
    'background:#4a6cd4;color:#fff;border:none;',
    'border-radius:10px;',
    'padding:'+(isMobile?'10px 40px':'11px 52px')+';',
    'font-size:'+(isMobile?'13px':'14px')+';font-weight:700;cursor:pointer;',
    'box-shadow:0 4px 16px rgba(75,110,220,0.35);white-space:nowrap;'
  ].join('');
  document.body.appendChild(confirmBtn);
  bubbles.push(confirmBtn);

  function closeGuide() {
    bubbles.forEach(function(b){ b.remove(); });
    overlay.remove();
    document.body.style.overflow = prevOverflow;
    sessionStorage.setItem('cg_done', '1');
  }

  confirmBtn.addEventListener('click', function(e){ e.stopPropagation(); closeGuide(); });
  overlay.addEventListener('click', closeGuide);
}

// 가이드 투어 제거: 자동 실행하지 않음
</script>

</body>
</html>
"""

@app.route("/care")
def care():
    return render_template_string(
        CARE_HTML,
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
  background:#4a6cd4;
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
  <a href="/home" class="home-button">⌂ 홈으로</a>
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



# =========================
# 지자체 자체조사 서식
# =========================
SURVEY_HTML = """
<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>지자체 조사 서식</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/html2pdf.js/0.10.1/html2pdf.bundle.min.js"></script>
<style>
*{ box-sizing:border-box; margin:0; padding:0; }
body{ background:#f4f6fb; font-family:'Pretendard',sans-serif; color:#111827; font-size:13px; }
.page-wrap{ max-width:860px; margin:0 auto; padding:20px 16px 60px 16px; min-width:0; word-break:keep-all; }
.top-bar{ display:flex; justify-content:space-between; align-items:center; margin-bottom:14px; gap:10px; flex-wrap:wrap; padding:6px 0; }
.home-btn{ display:inline-flex; align-items:center; justify-content:center; gap:5px; height:34px; padding:0 15px; border-radius:8px; background:#ffffff; border:1px solid #e5e7eb; color:#6b7280; text-decoration:none; font-size:13px; font-weight:600; box-shadow:0 2px 6px rgba(15,23,42,0.08); transition:all .15s; }
.home-btn:hover{ background:#f3f4f6; color:#374151; }
.btn-group{ display:flex; gap:10px; }
.print-btn{ display:inline-flex; align-items:center; justify-content:center; gap:5px; height:34px; padding:0 15px; border-radius:8px; background:#ffffff; border:1px solid #e5e7eb; color:#6b7280; font-size:13px; font-weight:600; cursor:pointer; box-shadow:0 2px 6px rgba(15,23,42,0.08); transition:all .15s; }
.print-btn:hover{ background:#f3f4f6; color:#374151; }
.reset-btn{ display:inline-flex; align-items:center; justify-content:center; gap:5px; height:34px; padding:0 15px; border-radius:8px; background:#ffffff; border:1px solid #e5e7eb; color:#6b7280; font-size:13px; font-weight:600; cursor:pointer; box-shadow:0 2px 6px rgba(15,23,42,0.08); transition:all .15s; }
.reset-btn:hover{ background:#f3f4f6; color:#374151; }
.tab-bar{ display:flex; gap:4px; border-bottom:2px solid #5b7ee5; padding-top:4px; }
.tab-btn{ padding:9px 20px; font-size:13px; font-weight:700; border:1px solid #d1d5db; border-bottom:none; background:#eef2ff; color:#6b7280; cursor:pointer; border-radius:8px 8px 0 0; transition:all .15s; }
.tab-btn.active{ background:#5b7ee5; color:#fff; border-color:#5b7ee5; }
.tab-btn:hover:not(.active){ background:#e0e7ff; color:#374151; }
.tab-panel{ display:none; }
.tab-panel.active{ display:block; }
.form-card{ background:#fff; border-radius:0 16px 16px 16px; padding:28px 24px; box-shadow:0 6px 18px rgba(0,0,0,0.07); overflow-x:auto; }
.form-title{ text-align:left; font-size:18px; font-weight:900; margin-bottom:20px; letter-spacing:-0.3px; border:none; border-left:5px solid #5b7ee5; padding:6px 0 6px 14px; color:#2d3a6e; }
.section-header{ background:#5b7ee5; color:#fff; font-size:13px; font-weight:700; padding:6px 10px; border-radius:4px; margin:18px 0 8px 0; }
.form-table{ width:100%; border-collapse:collapse; margin-bottom:4px; }
.form-table th,.form-table td{ border:1px solid #d1d5db; padding:7px 10px; vertical-align:middle; line-height:1.5; }
.form-table th{ background:#f8fafc; font-weight:700; text-align:center; white-space:nowrap; min-width:72px; }
.form-table td{ color:#374151; }
.form-table input[type=text],.form-table input[type=date],.form-table select{ width:100%; border:none; border-bottom:1px solid #94a3b8; padding:2px 4px; font-size:13px; font-family:inherit; background:transparent; outline:none; }
.form-table input[type=text]:focus,.form-table input[type=date]:focus{ border-bottom-color:#4a6cd4; }
.radio-group,.check-group{ display:flex; flex-wrap:wrap; gap:6px 14px; align-items:center; }
.radio-group label,.check-group label{ display:inline-flex; align-items:center; gap:3px; cursor:pointer; white-space:nowrap; font-size:12.5px; }
.radio-group input,.check-group input{ width:auto; border:none; border-bottom:none; flex-shrink:0; }
.etc-input{ display:inline-block; width:80px; border:none !important; border-bottom:1px solid #94a3b8 !important; padding:0 4px !important; font-size:12.5px; font-family:inherit; background:transparent; outline:none; vertical-align:middle; }
.adl-table{ width:100%; border-collapse:collapse; margin-bottom:4px; }
.adl-table th,.adl-table td{ border:1px solid #d1d5db; padding:6px 8px; text-align:center; font-size:12px; vertical-align:middle; }
.adl-table th{ background:#f8fafc; font-weight:700; }
.adl-table td:first-child{ text-align:left; }
.form-textarea{ width:100%; border:1px solid #d1d5db; border-radius:6px; padding:8px; font-size:13px; font-family:inherit; resize:vertical; min-height:60px; outline:none; }
.form-textarea:focus{ border-color:#4a6cd4; }
.service-table{ width:100%; border-collapse:collapse; margin-bottom:8px; }
.service-table th,.service-table td{ border:1px solid #d1d5db; padding:8px; text-align:center; font-size:12.5px; }
.service-table th{ background:#f8fafc; font-weight:700; }
.relay-note{ font-size:11px; color:#6b7280; margin-top:6px; line-height:1.6; }
.th-internet-pc{ display:block; }
.th-internet-mo{ display:none !important; }
@media print{
  body{ background:white; }
  .top-bar,.tab-bar{ display:none !important; }
  .score-banner,.care-modal-overlay{ display:none !important; }
  .page-wrap{ padding:0; }
  .form-card{ box-shadow:none; border-radius:0; padding:10px; }
  .tab-panel{ display:none !important; }
  .tab-panel.print-target{ display:block !important; }
  .section-header{ -webkit-print-color-adjust:exact; print-color-adjust:exact; }
}
/* 연령 칸 */
.age-td{ white-space:nowrap; }
.age-input{ display:inline-block; width:32px !important; padding:0 2px !important; border:none; border-bottom:1px solid #94a3b8; background:transparent; font-size:inherit; font-family:inherit; outline:none; vertical-align:middle; }
@media (max-width:600px){
  /* 성별·연령·생년월일 th 동일 폭 */
  .th-gender, .age-th, .th-birth{ width:2.8em !important; font-size:10px !important; padding:3px 2px !important; }
  .age-th{ letter-spacing:-0.3px; }
  /* 성명 td 넓게, 생년월일 td 좁게 */
  .td-name{ width:6em !important; padding:3px 2px !important; }
  .td-birth{ width:4em !important; padding:3px 2px !important; }
  /* 성별 td, 연령 td */
  .td-gender{ width:4em !important; padding:3px 2px !important; font-size:10px !important; }
  .age-td{ width:5em !important; font-size:10px !important; padding:3px 2px !important; }
  .age-input{ width:22px !important; padding:0 1px !important; }
}
@media (max-width:600px){
  .page-wrap{ padding:10px 6px 60px 6px; }
  .form-card{ padding:12px 8px; }
  .form-title{ font-size:14px; padding:4px 0 4px 12px; }
  .tab-btn{ padding:7px 11px; font-size:11.5px; }
  .form-table,.adl-table,.service-table{ table-layout:fixed; width:100%; word-break:keep-all; overflow-wrap:break-word; }
  .form-table th{ min-width:0; font-size:11px; padding:5px 4px; white-space:normal; word-break:keep-all; overflow-wrap:anywhere; width:5em; text-align:center; }
  .form-table td{ font-size:11px; padding:5px 4px; word-break:keep-all; }
  .radio-group,.check-group{ gap:5px 8px; }
  .radio-group label,.check-group label{ font-size:11px; white-space:normal; }
  .adl-table th,.adl-table td{ font-size:10px; padding:4px 3px; }
  .service-table th,.service-table td{ font-size:10px; padding:4px 3px; }
  .section-header{ font-size:11.5px; padding:5px 8px; }
  .top-bar{
    flex-wrap:nowrap !important;
    gap:5px !important;
    align-items:center !important;
  }

.btn-group{
  display:flex !important;
  gap:5px !important;
  flex-wrap:nowrap !important;
  align-items:center !important;
}

  .home-btn,
  .reset-btn,
  .print-btn{
    height:30px !important;
    font-size:10.5px !important;
    padding:0 6px !important;
    white-space:nowrap !important;
  }

  .home-btn{
    flex:0 0 auto !important;
  }

  .btn-group .print-btn,
.btn-group .reset-btn{
  flex:0 0 auto !important;
}
  .etc-input{ width:56px !important; font-size:11px; }
  .adl-table thead tr th:nth-child(n+5),.adl-table tbody tr td:nth-child(n+5){ display:none; }
  .adl-table thead tr th:first-child{ width:50%; }
  .th-internet-pc{ display:none !important; }
  .th-internet-mo{ display:block !important; font-size:10px; }
  span.th-internet-mo{ display:inline !important; }
  .th-internet{ font-size:10px !important; }
  .th-internet-mo input[type=checkbox]{ margin:0 !important; padding:0 !important; vertical-align:middle !important; }

}

/* ── 사전조사 전용 스타일 ── */
.dementia-box{ background:linear-gradient(135deg,#eef2ff,#e0e7ff); padding:16px 18px; border-radius:12px; margin-bottom:16px; border:1px solid #c7d2fe; }
.dementia-options{ display:flex; width:100%; align-items:center; justify-content:space-between; gap:0; }
.dementia-options label{ flex:1; display:flex; justify-content:center; align-items:center; gap:6px; white-space:nowrap; margin:0; font-size:13px; cursor:pointer; }
.dementia-options input[type=radio]{ width:auto !important; margin:0; flex:0 0 auto; transform:scale(1.1); border:revert; padding:revert; border-radius:revert; }
.question-box{ background:#f8fafc; padding:18px; border-radius:12px; margin-bottom:10px; border:1px solid #e5e7eb; transition:0.18s ease; }
.question-box.active{ border:2px solid #5b7ee5; background:#eef2ff; box-shadow:0 6px 18px rgba(75,110,220,0.12); }
.question-title{ display:block; font-size:13.5px; line-height:1.6; word-break:keep-all; overflow-wrap:break-word; padding-left:22px; text-indent:-22px; }
.options{ margin-top:10px; display:flex; flex-direction:column; gap:8px; }
.options label{ display:flex; align-items:center; gap:8px; cursor:pointer; line-height:1.5; font-size:12.5px; }
.options input[type=radio]{ width:auto !important; flex:0 0 auto; transform:scale(1.05); border:revert; padding:revert; border-radius:revert; }
.guide-box{ display:flex; }

/* ── 점수 배너 ── */
.score-banner{ position:fixed; top:100px; right:80px; z-index:998; width:132px; padding:14px 12px; border-radius:22px; background:rgba(255,255,255,0.92); backdrop-filter:blur(10px); -webkit-backdrop-filter:blur(10px); border:1px solid rgba(191,219,254,0.95); box-shadow:0 18px 38px rgba(75,110,220,0.18); text-align:center; transition:all 0.2s ease; }
.score-banner.disabled{ opacity:0.62; transform:scale(0.98); }
.score-banner.hidden-banner{ display:none !important; }
.score-badge{ width:72px; height:72px; margin:0 auto 10px auto; border-radius:50%; background:linear-gradient(135deg,#5b7ee5,#a5b4fc); display:flex; flex-direction:column; align-items:center; justify-content:center; color:white; box-shadow:0 10px 22px rgba(75,110,220,0.28); }
.score-badge-label{ font-size:10px; opacity:0.92; line-height:1; margin-bottom:4px; }
.score-value-text{ font-size:28px; font-weight:800; line-height:1; }
.score-meta{ display:none; }
.score-progress-wrap{ width:100%; height:8px; background:#eef2ff; border-radius:999px; overflow:hidden; margin-bottom:3px; }
.score-progress-bar{ height:100%; width:0%; border-radius:999px; background:linear-gradient(90deg,#a5b4fc,#5b7ee5); transition:width 0.22s ease; }
.score-status{ font-size:11px; color:#2d3a6e; line-height:1.45; word-break:keep-all; min-height:34px; font-weight:600; }
.score-chip{ margin-top:8px; display:inline-block; padding:5px 8px; border-radius:999px; font-size:10px; font-weight:700; background:#eef2ff; color:#5b7ee5; }

.score-banner.state-low .score-badge{ background:linear-gradient(135deg,#22c55e,#4ade80); box-shadow:0 10px 22px rgba(34,197,94,0.24); }
.score-banner.state-low .score-progress-bar{ background:linear-gradient(90deg,#86efac,#22c55e); }
.score-banner.state-low .score-status{ color:#166534; }
.score-banner.state-low .score-chip{ background:#f0fdf4; color:#16a34a; }

.score-banner.state-mid .score-badge{ background:linear-gradient(135deg,#f59e0b,#fbbf24); box-shadow:0 10px 22px rgba(245,158,11,0.24); }
.score-banner.state-mid .score-progress-bar{ background:linear-gradient(90deg,#fde68a,#f59e0b); }
.score-banner.state-mid .score-status{ color:#92400e; }
.score-banner.state-mid .score-chip{ background:#fffbeb; color:#d97706; }

.score-banner.state-high .score-badge{ background:linear-gradient(135deg,#ef4444,#f87171); box-shadow:0 10px 22px rgba(239,68,68,0.24); }
.score-banner.state-high .score-progress-bar{ background:linear-gradient(90deg,#fca5a5,#ef4444); }
.score-banner.state-high .score-status{ color:#991b1b; }
.score-banner.state-high .score-chip{ background:#fef2f2; color:#dc2626; }

.score-banner.state-dementia .score-badge{ background:linear-gradient(135deg,#7c3aed,#a78bfa); box-shadow:0 10px 22px rgba(124,58,237,0.24); }
.score-banner.state-dementia .score-progress-bar{ background:linear-gradient(90deg,#c4b5fd,#7c3aed); width:100% !important; }
.score-banner.state-dementia .score-status{ color:#5b21b6; }
.score-banner.state-dementia .score-chip{ background:#f5f3ff; color:#7c3aed; }

/* ── 사전조사 결과 모달 ── */
.care-modal-overlay{ display:none; position:fixed; inset:0; background:rgba(0,0,0,.5); z-index:999; padding-top:6vh; overflow:auto; -webkit-overflow-scrolling:touch; }
.care-modal-box{ background:white; margin:0 auto; position:absolute; top:8%; left:0; right:0; padding:18px 22px 22px 22px; width:92%; max-width:460px; border-radius:14px; text-align:center; box-shadow:0 10px 25px rgba(0,0,0,0.15); }
.care-modal-result-area{ background:#eef2ff; border-radius:10px; padding:14px; margin-bottom:18px; }
.care-modal-result-area p{ font-size:18px; line-height:1.6; margin:0; }
.care-modal-criteria{ text-align:left; font-size:13px; line-height:1.6; color:#444; background:#fafafa; padding:14px; border-radius:8px; }
.care-modal-btn{ margin-top:18px; width:100%; height:44px; border:none; border-radius:10px; background:#5b7ee5; color:#fff; font-size:14px; font-weight:700; cursor:pointer; }

@media (max-width:600px){
  .score-banner{ position:fixed; top:80px; right:10px; width:85px; padding:8px 6px; border-radius:16px; z-index:10; }
  .score-badge{ width:44px; height:44px; }
  .score-value-text{ font-size:18px; }
  .score-meta{ font-size:9px; }
  .score-status{ font-size:10px; line-height:1.2; min-height:20px; }
  .score-chip{ font-size:10px; padding:3px 6px; }
  .question-title{ font-size:12.5px; line-height:1.55; padding-left:18px; text-indent:-18px; }
  .options label{ font-size:11.5px; }
  .dementia-box{ padding:12px 14px; }
  .dementia-options label{ font-size:12px; }
  .care-modal-overlay{ padding-top:0 !important; }
  .care-modal-box{ top:2% !important; }
}

/* ── 개인정보 비활성화 스타일 ── */
.personal-disabled{
  background:#f3f4f6 !important;
  color:#9ca3af !important;
  cursor:not-allowed;
  position:relative;
}
.personal-disabled input,
.personal-disabled select{
  background:#f3f4f6 !important;
  color:#9ca3af !important;
  cursor:not-allowed;
  pointer-events:none;
}
.personal-disabled label{
  color:#9ca3af !important;
  cursor:not-allowed;
  pointer-events:none;
}

</style>
</head>
<body>
<div class="page-wrap">

  <div class="top-bar" id="gt-topbar">
    <a href="/home" class="home-btn">&#8962; 홈으로</a>
    <div class="btn-group">
      <button type="button" class="print-btn" id="gt-email" onclick="openEmailPopup()">&#9993; 메일 보내기</button>
      <button type="button" class="print-btn" id="gt-print" onclick="doPrint()">&#128196; 출력 / pdf 저장</button>
      <button type="button" class="reset-btn" id="gt-reset" onclick="resetForm()">&#8635; 다시 입력</button>
    </div>
  </div>

  <div class="tab-bar" id="gt-tabs">
    <button class="tab-btn active" onclick="switchTab('care')" id="tab-care">사전조사</button>
    <button class="tab-btn" onclick="switchTab('self')" id="tab-self">자체조사</button>
    <button class="tab-btn" onclick="switchTab('relay')" id="tab-relay">연계조사</button>
  </div>

  <div class="form-card">

    <!-- ══ 탭0: 사전조사 ══ -->
    <div class="tab-panel active" id="panel-care">
      <div class="form-title">통합돌봄 사전조사</div>

      <div id="scoreBanner" class="score-banner disabled">
        <div class="score-badge">
          <div class="score-badge-label">점수</div>
          <div id="scoreValue" class="score-value">0</div>
        </div>
        <div class="score-meta">응답 <span id="answeredCount">0</span>/7 · 최대 14점</div>
        <div class="score-progress-wrap">
          <div id="scoreProgressBar" class="score-progress-bar"></div>
        </div>
        <div id="scoreStatus" class="score-status">치매 여부를 먼저 선택하세요</div>
        <div id="scoreChip" class="score-chip">사전 확인 필요</div>
      </div>

      <form id="careForm">
        <div id="gt-dementia">
        <div class="section-header">&#9632; 치매 관련 약 복용 여부</div>
        <div class="dementia-box">
          <b style="font-size:13.5px;display:block;margin-bottom:10px;">치매 관련 약을 복용 중이십니까?</b>
          <div class="dementia-options">
            <label><input type="radio" name="dementia" value="y"> 예</label>
            <label><input type="radio" name="dementia" value="n"> 아니오</label>
          </div>
        </div>
        </div>

        <div id="gt-adl" class="section-header">&#9632; 일상생활 수행능력(ADL) 조사</div>
        <div id="adlSection">
          {% for i,q in questions %}
          <div class="question-box">
            <b class="question-title">{{i+1}}) {{q}}</b>
            <div class="options">
              <label><input type="radio" name="q{{i}}" value="0"> 도움 없이 혼자서 수행 가능 (0점)</label>
              <label><input type="radio" name="q{{i}}" value="1"> 보조도구(지팡이 등)를 잡고 수행 가능 (1점)</label>
              <label><input type="radio" name="q{{i}}" value="2"> 타인이 도와줘야 수행 가능 (2점)</label>
            </div>
          </div>
          {% endfor %}

          <button type="submit" class="submit-btn" style="margin-top:18px;width:100%;height:44px;border:none;border-radius:10px;background:#5b7ee5;color:#fff;font-size:14px;font-weight:700;cursor:pointer;box-shadow:0 2px 8px rgba(75,110,220,0.25);">검사하기</button>
        </div>
      </form>

      <!-- 결과 안내 박스 영역 -->
      <div id="careGuideBox" class="guide-box" style="display:none;margin-top:16px;padding:14px 18px;border-radius:12px;background:#fff7ed;border:1px solid #fdba74;color:#9a3412;font-size:13px;line-height:1.7;align-items:flex-start;gap:8px;"></div>

    </div><!-- /panel-care -->

    <!-- ══ 탭1: 자체조사 ══ -->
    <div class="tab-panel" id="panel-self">
      <div class="form-title" id="gt-title">지자체 자체조사 서식</div>
      <div id="gt-section-wrap">
      <div class="section-header" id="gt-section">&#9632; 대상자 기본사항</div>
      <table class="form-table">
        <tr>
          <th>성명</th><td class="td-name personal-disabled"><input type="text" name="s_name" disabled></td>
          <th class="th-gender">성별</th>
          <td class="td-gender personal-disabled"><div class="radio-group"><label><input type="radio" name="s_gender" value="남" disabled> 남</label><label><input type="radio" name="s_gender" value="여" disabled> 여</label></div></td>
          <th class="age-th">연령</th>
          <td class="age-td personal-disabled">만<input type="text" name="s_age_d" class="age-input" disabled>&thinsp;세</td>
          <th class="th-birth">생년<br>월일</th><td class="td-birth personal-disabled"><input type="text" name="s_birth" disabled></td>
        </tr>
        <tr><th>주소</th><td colspan="7" class="personal-disabled"><input type="text" name="s_address" disabled></td></tr>
        <tr><th>실거주지</th><td colspan="7" class="personal-disabled"><input type="text" name="s_real_addr" disabled></td></tr>
        <tr>
          <th rowspan="2">연락처</th>
          <td colspan="3" class="personal-disabled">자택: <input type="text" name="s_tel_home" class="etc-input" style="width:120px" disabled></td>
          <td colspan="4" class="personal-disabled">핸드폰: <input type="text" name="s_tel_mobile" class="etc-input" style="width:120px" disabled></td>
        </tr>
        <tr><td colspan="7" class="personal-disabled">비상연락처: <input type="text" name="s_tel_emg" class="etc-input" style="width:150px" disabled> (관계: <input type="text" name="s_tel_rel" class="etc-input" style="width:70px" disabled>)</td></tr>
        <tr><th>주수<br>발자</th><td colspan="7"><div class="check-group">
          <label><input type="checkbox" name="s_care" value="없음"> 없음</label>
          <label><input type="checkbox" name="s_care" value="배우자"> 배우자</label>
          <label><input type="checkbox" name="s_care" value="자녀"> 자녀(며느리·사위 포함)</label>
          <label><input type="checkbox" name="s_care" value="손자녀"> 손자녀</label>
          <label><input type="checkbox" name="s_care" value="친인척"> 친인척</label>
          <label><input type="checkbox" name="s_care" value="친구이웃"> 친구·이웃</label>
          <label><input type="checkbox" name="s_care" value="사적간병인"> 사적 간병인</label>
          <label><input type="checkbox" name="s_care" value="공적서비스"> 공적서비스 돌봄제공자</label>
          <label><input type="checkbox" name="s_care" value="형제자매"> 형제·자매</label>
          <label><input type="checkbox" name="s_care" value="자원봉사자"> 자원봉사자</label>
          <label><input type="checkbox" name="s_care" value="기타"> 기타(<input type="text" class="etc-input">)</label>
        </div></td></tr>
        <tr><th>가구<br>형태</th><td colspan="7"><div class="radio-group">
          <label><input type="radio" name="s_hh" value="독거"> 독거</label>
          <label><input type="radio" name="s_hh" value="비독거부부"> 비독거(부부)</label>
          <label><input type="radio" name="s_hh" value="노부모"> 노부모</label>
          <label><input type="radio" name="s_hh" value="자녀"> 자녀</label>
          <label><input type="radio" name="s_hh" value="조손"> 조손</label>
          <label><input type="radio" name="s_hh" value="형제자매"> 형제자매</label>
          <label><input type="radio" name="s_hh" value="장애인가구"> 장애인가구</label>
          <label><input type="radio" name="s_hh" value="다문화가구"> 다문화가구</label>
          <label><input type="radio" name="s_hh" value="친척지인"> 친척·지인</label>
          <label><input type="radio" name="s_hh" value="기타"> 기타(<input type="text" class="etc-input">)</label>
        </div></td></tr>
        <tr><th>사회보장<br>수급권</th><td colspan="7"><div class="check-group" style="flex-direction:column;align-items:flex-start;gap:6px;">
          <div style="display:flex;flex-wrap:wrap;align-items:center;gap:4px 6px;">
            <label><input type="checkbox" name="s_wf" value="국민기초"> 국민기초생활보장제도</label>
            <span style="display:inline-flex;flex-wrap:nowrap;align-items:center;gap:2px;">
            <span style="color:#6b7280;">(</span>
            <label><input type="checkbox" name="s_wf_sub" value="생계급여"> 생계급여</label>
            <label><input type="checkbox" name="s_wf_sub" value="의료급여"> 의료급여</label>
            <label><input type="checkbox" name="s_wf_sub" value="주거급여"> 주거급여</label>
            <span style="color:#6b7280;">)</span>
            </span>
            <label><input type="checkbox" name="s_wf" value="차상위"> 차상위</label>
            <label><input type="checkbox" name="s_wf" value="일반보훈"> 일반(보훈)</label>
            <label><input type="checkbox" name="s_wf" value="기초연금"> 기초연금</label>
            <label><input type="checkbox" name="s_wf" value="일반가구"> 일반가구</label>
          </div>
        </div></td></tr>
        <tr><th>대상자<br>유형</th><td colspan="7"><div class="check-group" style="flex-direction:column;align-items:flex-start;gap:6px;">
          <div style="display:flex;flex-wrap:wrap;align-items:center;gap:4px 10px;">
            <label><input type="checkbox" name="s_tt" value="장기요양재가"> 장기요양 재가급여자</label>
            <span class="th-internet-pc" style="display:inline;">(</span><label class="th-internet-pc"><input type="checkbox" name="s_tg" value="1등급" style="width:auto;"> 1등급</label><label class="th-internet-pc"><input type="checkbox" name="s_tg" value="2등급" style="width:auto;"> 2등급</label><label class="th-internet-pc"><input type="checkbox" name="s_tg" value="3등급" style="width:auto;"> 3등급</label><label class="th-internet-pc"><input type="checkbox" name="s_tg" value="4등급" style="width:auto;"> 4등급</label><label class="th-internet-pc"><input type="checkbox" name="s_tg" value="5등급" style="width:auto;"> 5등급</label><label class="th-internet-pc"><input type="checkbox" name="s_tg" value="인지등급" style="width:auto;"> 인지등급</label><span class="th-internet-pc" style="display:inline;">)</span>
            <div class="th-internet-mo" style="display:flex;flex-wrap:nowrap;align-items:center;gap:5px;font-size:10px;overflow-x:auto;max-width:100%;"><span style="color:#6b7280;flex-shrink:0;">(</span><label style="font-size:10px;white-space:nowrap;flex-shrink:0;display:inline-flex;align-items:center;gap:1px;line-height:1;"><input type="checkbox" name="s_tg" value="1등급" style="width:11px;height:11px;margin:0;padding:0;vertical-align:middle;flex-shrink:0;"><span>1등급</span></label><label style="font-size:10px;white-space:nowrap;flex-shrink:0;display:inline-flex;align-items:center;gap:1px;line-height:1;"><input type="checkbox" name="s_tg" value="2등급" style="width:11px;height:11px;margin:0;padding:0;vertical-align:middle;flex-shrink:0;"><span>2등급</span></label><label style="font-size:10px;white-space:nowrap;flex-shrink:0;display:inline-flex;align-items:center;gap:1px;line-height:1;"><input type="checkbox" name="s_tg" value="3등급" style="width:11px;height:11px;margin:0;padding:0;vertical-align:middle;flex-shrink:0;"><span>3등급</span></label><label style="font-size:10px;white-space:nowrap;flex-shrink:0;display:inline-flex;align-items:center;gap:1px;line-height:1;"><input type="checkbox" name="s_tg" value="4등급" style="width:11px;height:11px;margin:0;padding:0;vertical-align:middle;flex-shrink:0;"><span>4등급</span></label><label style="font-size:10px;white-space:nowrap;flex-shrink:0;display:inline-flex;align-items:center;gap:1px;line-height:1;"><input type="checkbox" name="s_tg" value="5등급" style="width:11px;height:11px;margin:0;padding:0;vertical-align:middle;flex-shrink:0;"><span>5등급</span></label><label style="font-size:10px;white-space:nowrap;flex-shrink:0;display:inline-flex;align-items:center;gap:1px;line-height:1;"><input type="checkbox" name="s_tg" value="인지등급" style="width:11px;height:11px;margin:0;padding:0;vertical-align:middle;flex-shrink:0;"><span>인지등급</span></label><span style="color:#6b7280;flex-shrink:0;">)</span></div>
          </div>
          <div style="display:flex;flex-wrap:wrap;align-items:center;gap:4px 10px;">
            <label><input type="checkbox" name="s_tt" value="장기요양등급외"> 장기요양 등급외(A, B)</label>
            <label><input type="checkbox" name="s_tt" value="기각각하"> 기각·각하</label>
            <label><input type="checkbox" name="s_tt" value="등급판정신청중"> 장기요양 등급판정 신청 중</label>
          </div>
          <div style="display:flex;flex-wrap:wrap;align-items:center;gap:4px 10px;">
            <label><input type="checkbox" name="s_tt" value="노인맞춤돌봄"> 노인맞춤돌봄서비스</label>
            <span style="display:inline-flex;flex-wrap:nowrap;align-items:center;gap:2px;"><span style="color:#6b7280;">(</span><label><input type="checkbox" name="s_tc" value="일반돌봄군"> 일반돌봄군</label>
            <label><input type="checkbox" name="s_tc" value="중점돌봄군"> 중점돌봄군</label><span style="color:#6b7280;">)</span></span>
            <label><input type="checkbox" name="s_tt" value="퇴원예정자"> 퇴원(예정)자</label>
            <span style="display:inline-flex;flex-wrap:nowrap;align-items:center;gap:2px;"><span style="color:#6b7280;">(</span><label><input type="checkbox" name="s_td" value="의료기관연계"> 의료기관 연계</label>
            <label><input type="checkbox" name="s_td" value="지역사회발굴"> 지역사회 발굴</label><span style="color:#6b7280;">)</span></span>
          </div>
          <div style="display:flex;flex-wrap:wrap;align-items:center;gap:4px 10px;">
            <label><input type="checkbox" name="s_tt" value="장애등록"> 장애등록·정도</label>
            <span style="display:inline-flex;flex-wrap:nowrap;align-items:center;gap:2px;"><span style="color:#6b7280;">(</span><label><input type="checkbox" name="s_tdi" value="심한장애"> 심한 장애</label>
            <label><input type="checkbox" name="s_tdi" value="심하지않은장애"> 심하지 않은 장애</label><span style="color:#6b7280;">)</span></span>
          </div>
          <label><input type="checkbox" name="s_tt" value="기타"> 기타(<input type="text" class="etc-input" style="width:100px">)</label>
          <label><input type="checkbox" name="s_tt" value="해당없음"> 해당 없음</label>
        </div></td></tr>
        <tr><th>현재 이용중인<br>서비스</th><td colspan="7"><div class="check-group">
          <label><input type="checkbox" name="s_cs" value="없음"> 없음</label>
          <label><input type="checkbox" name="s_cs" value="있음"> 있음</label>
          <label><input type="checkbox" name="s_cs" value="노인맞춤돌봄"> 노인맞춤돌봄서비스</label>
          <label><input type="checkbox" name="s_cs" value="치매안심센터"> 치매안심센터</label>
          <label><input type="checkbox" name="s_cs" value="급식도시락반찬"> 급식 및 도시락 반찬</label>
          <label><input type="checkbox" name="s_cs" value="활동보조"> 활동보조</label>
          <label><input type="checkbox" name="s_cs" value="말벗"> 말벗</label>
          <label><input type="checkbox" name="s_cs" value="보건사업"> 보건사업</label>
          <label><input type="checkbox" name="s_cs" value="주거개선사업"> 주거개선사업</label>
          <label><input type="checkbox" name="s_cs" value="건강운동교실"> 건강운동교실</label>
          <label><input type="checkbox" name="s_cs" value="목욕이미용"> 목욕·이미용</label>
          <label><input type="checkbox" name="s_cs" value="이동지원"> 이동지원</label>
          <label><input type="checkbox" name="s_cs" value="노인일자리사업"> 노인일자리 사업</label>
          <label><input type="checkbox" name="s_cs" value="무료진료연계"> 무료진료연계</label>
          <label><input type="checkbox" name="s_cs" value="가사간병방문도움"> 가사간병방문도움</label>
          <label><input type="checkbox" name="s_cs" value="여가문화교육"> 여가, 문화, 교육</label>
          <label><input type="checkbox" name="s_cs" value="기타"> 기타(<input type="text" class="etc-input" style="width:80px">)</label>
        </div></td></tr>
      </table>

      <div class="section-header">&#9632; 주거환경상태<br><span style="font-weight:400;font-size:11px;">(현장조사 시 조사자가 확인 / 병원조사인 경우 생략 가능)</span></div>
      <table class="form-table">
        <tr><th>생활방식</th><td colspan="5"><div class="radio-group">
          <label><input type="radio" name="s_ls" value="단독보행"> 단독보행</label>
          <label><input type="radio" name="s_ls" value="클러치사용"> 클러치사용</label>
          <label><input type="radio" name="s_ls" value="좌식생활"> 좌식생활</label>
          <label><input type="radio" name="s_ls" value="휠체어사용"> 휠체어사용</label>
          <label><input type="radio" name="s_ls" value="와상생활"> 와상생활</label>
        </div></td></tr>
        <tr>
          <th>주거상태</th>
          <td colspan="2"><div class="radio-group"><label><input type="radio" name="s_hs" value="노후"> 노후</label><label><input type="radio" name="s_hs" value="보통"> 보통</label><label><input type="radio" name="s_hs" value="양호"> 양호</label></div></td>
          <th class="th-internet"><span style="display:inline;" class="th-internet-pc">인터넷가능여부<br>(스마트폰 포함)</span><span class="th-internet-mo">인터넷<br>가능여부<br>(스마트폰<br>포함)</span></th>
          <td colspan="2"><div class="radio-group"><label><input type="radio" name="s_net" value="가능"> 가능</label><label><input type="radio" name="s_net" value="불가능"> 불가능</label></div></td>
        </tr>
        <tr><th>주택형태</th><td colspan="5"><div class="radio-group">
          <label><input type="radio" name="s_ht" value="단독주택"> 단독주택</label>
          <label><input type="radio" name="s_ht" value="아파트"> 아파트</label>
          <label><input type="radio" name="s_ht" value="연립주택"> 연립주택</label>
          <label><input type="radio" name="s_ht" value="다가구주택"> 다가구주택</label>
          <label><input type="radio" name="s_ht" value="비주택"> 비주택</label>
          <label><input type="radio" name="s_ht" value="기타"> 기타(<input type="text" class="etc-input">)</label>
        </div></td></tr>
        <tr><th>주거지<br>상태</th><td colspan="5"><div class="radio-group">
          <label><input type="radio" name="s_hf" value="지하"> 지하</label>
          <label><input type="radio" name="s_hf" value="1층"> 1층</label>
          <label><input type="radio" name="s_hf" value="2층이상"> 2층이상</label>
          <label style="white-space:nowrap;">(계단 <input type="checkbox" name="s_hf_stair" value="계단" style="width:auto;border:none;border-bottom:none;"> / 승강기 <input type="checkbox" name="s_hf_elev" value="승강기" style="width:auto;border:none;border-bottom:none;">)</label>
        </div></td></tr>
        <tr><th>난방형태</th><td colspan="5"><div class="radio-group">
          <label><input type="radio" name="s_heat" value="가스보일러"> 가스보일러</label>
          <label><input type="radio" name="s_heat" value="연탄보일러"> 연탄보일러</label>
          <label><input type="radio" name="s_heat" value="기름보일러"> 기름보일러</label>
          <label><input type="radio" name="s_heat" value="아궁이"> 아궁이(연탄/장작)</label>
          <label><input type="radio" name="s_heat" value="난방없음"> 난방없음</label>
          <label><input type="radio" name="s_heat" value="기타"> 기타(<input type="text" class="etc-input" style="width:120px">)</label>
        </div></td></tr>
        <tr><th>화장실<br>형태</th><td colspan="5"><div class="radio-group">
          <label><input type="radio" name="s_tlt" value="공용"> 공용</label>
          <label><input type="radio" name="s_tlt" value="전용"> 전용</label>
          <label><input type="radio" name="s_tlt" value="수세식"> 수세식</label>
          <label><input type="radio" name="s_tlt" value="재래식"> 재래식</label>
        </div></td></tr>
        <tr>
          <th rowspan="3">주요<br>주거환경</th>
          <td>조명</td><td><div class="radio-group"><label><input type="radio" name="s_light" value="양호"> 양호</label><label><input type="radio" name="s_light" value="불량"> 불량</label></div></td>
          <td><span style="display:inline;" class="th-internet-pc">문턱여부(현관, 방, 화장실)</span><span class="th-internet-mo" style="font-size:11px;">문턱여부<br><span style="font-size:10px;">(현관, 방,<br>화장실)</span></span></td><td colspan="2"><div class="radio-group"><label><input type="radio" name="s_thr" value="양호"> 양호</label><label><input type="radio" name="s_thr" value="불량"> 불량</label></div></td>
        </tr>
        <tr>
          <td><span style="display:inline;" class="th-internet-pc">계단(난간위치)</span><span class="th-internet-mo" style="font-size:11px;">계단<br><span style="font-size:10px;">(난간위치)</span></span></td><td><div class="radio-group"><label><input type="radio" name="s_stair" value="양호"> 양호</label><label><input type="radio" name="s_stair" value="불량"> 불량</label></div></td>
          <td><span style="display:inline;" class="th-internet-pc">집안의 안전손잡이</span><span class="th-internet-mo" style="font-size:11px;">집안의<br><span style="font-size:10px;">안전손잡이</span></span></td><td colspan="2"><div class="radio-group"><label><input type="radio" name="s_hdl" value="양호"> 양호</label><label><input type="radio" name="s_hdl" value="불량"> 불량</label></div></td>
        </tr>
        <tr><td colspan="4"><input type="text" name="s_house_etc" placeholder="기타 특이사항"></td></tr>
      </table>
      </div><!-- /gt-section-wrap -->

      <div class="section-header">&#9632; 일상생활기능 (ADL)</div>
      <table class="adl-table">
        <thead><tr>
          <th style="width:30%">구분</th><th>완전자립</th><th>부분도움</th><th>완전도움</th>
          <th style="width:30%">구분</th><th>완전자립</th><th>부분도움</th><th>완전도움</th>
        </tr></thead>
        <tbody>
          <tr>
            <td>옷 입기</td>
            <td><input type="radio" name="s_adl_dress" value="완전자립"></td><td><input type="radio" name="s_adl_dress" value="부분도움"></td><td><input type="radio" name="s_adl_dress" value="완전도움"></td>
            <td>누웠다 일어나 방 밖으로 나가기</td>
            <td><input type="radio" name="s_adl_move" value="완전자립"></td><td><input type="radio" name="s_adl_move" value="부분도움"></td><td><input type="radio" name="s_adl_move" value="완전도움"></td>
          </tr>
          <tr>
            <td>세수, 양치질, 머리감기</td>
            <td><input type="radio" name="s_adl_wash" value="완전자립"></td><td><input type="radio" name="s_adl_wash" value="부분도움"></td><td><input type="radio" name="s_adl_wash" value="완전도움"></td>
            <td>화장실 출입과 대소변 후 옷 입기</td>
            <td><input type="radio" name="s_adl_toilet" value="완전자립"></td><td><input type="radio" name="s_adl_toilet" value="부분도움"></td><td><input type="radio" name="s_adl_toilet" value="완전도움"></td>
          </tr>
          <tr>
            <td>목욕 또는 샤워하기</td>
            <td><input type="radio" name="s_adl_bath" value="완전자립"></td><td><input type="radio" name="s_adl_bath" value="부분도움"></td><td><input type="radio" name="s_adl_bath" value="완전도움"></td>
            <td>대소변 조절하기</td>
            <td><input type="radio" name="s_adl_exc" value="완전자립"></td><td><input type="radio" name="s_adl_exc" value="부분도움"></td><td><input type="radio" name="s_adl_exc" value="완전도움"></td>
          </tr>
          <tr>
            <td>차려 놓은 음식먹기</td>
            <td><input type="radio" name="s_adl_eat" value="완전자립"></td><td><input type="radio" name="s_adl_eat" value="부분도움"></td><td><input type="radio" name="s_adl_eat" value="완전도움"></td>
            <td></td><td></td><td></td><td></td>
          </tr>
        </tbody>
      </table>

      <div class="section-header">&#9632; 인지기능 (MMSE)</div>
      <table class="form-table"><tr><td colspan="2"><div class="radio-group">
        <label><input type="radio" name="s_mmse" value="정상"> &#9312; 정상(24점 이상)</label>
        <label><input type="radio" name="s_mmse" value="경도인지장애"> &#9313; 경도인지장애(18~23점)</label>
        <label><input type="radio" name="s_mmse" value="치매의심"> &#9314; 치매 의심(17점 이하)</label>
        <label><input type="radio" name="s_mmse" value="미실시"> &#9315; 미실시</label>
      </div></td></tr></table>

      <div class="section-header">&#9632; 의사소통 및 행동변화</div>
      <table class="form-table">
        <tr><td>1) 의사소통</td><td><div class="radio-group"><label><input type="radio" name="s_comm" value="가능"> &#9312; 가능</label><label><input type="radio" name="s_comm" value="불가능"> &#9313; 불가능</label></div></td></tr>
        <tr><td>2) 문제행동 여부</td><td><div class="radio-group"><label><input type="radio" name="s_beh" value="없음"> &#9312; 없음</label><label><input type="radio" name="s_beh" value="있음"> &#9313; 있음</label></div></td></tr>
      </table>

      <div class="section-header">&#9632; 건강상태</div>
      <table class="form-table">
        <tr><td>1) 정기적으로 방문하는 병원이 있습니까?</td><td><div class="radio-group"><label><input type="radio" name="s_hosp1" value="예"> &#9312; 예</label><label><input type="radio" name="s_hosp1" value="아니오"> &#9313; 아니오</label></div></td></tr>
        <tr><td>2) (최근 1년) 아프면 병원에 가지 못하고 참았던 적이 있습니까?</td><td><div class="radio-group"><label><input type="radio" name="s_hosp2" value="예"> &#9312; 예(2-1번으로)</label><label><input type="radio" name="s_hosp2" value="아니오"> &#9313; 아니오(3번으로)</label></div></td></tr>
        <tr><td style="padding-left:20px;">2-1) 병원에 가지 못한 이유</td><td><div class="check-group">
          <label><input type="checkbox" name="s_hr" value="경제적어려움"> &#9312; 경제적 어려움</label>
          <label><input type="checkbox" name="s_hr" value="거동불편"> &#9313; 거동이 불편해서</label>
          <label><input type="checkbox" name="s_hr" value="의료정보부족"> &#9314; 의료정보 부족</label>
          <label><input type="checkbox" name="s_hr" value="병원예약어려움"> &#9315; 병원 예약이 어려워서</label>
          <label><input type="checkbox" name="s_hr" value="증상가벼움"> &#9316; 증상이 가벼워서</label>
          <label><input type="checkbox" name="s_hr" value="기타"> &#9317; 기타(<input type="text" class="etc-input">)</label>
        </div></td></tr>
        <tr><td>3) 다른 사람이 병원에서 약을 처방받아준 적이 있습니까?</td><td><div class="radio-group"><label><input type="radio" name="s_prx" value="예"> &#9312; 예</label><label><input type="radio" name="s_prx" value="아니오"> &#9313; 아니오</label></div></td></tr>
        <tr><td>4) 기타 통증 및 불편 사항</td><td><div class="radio-group"><label><input type="radio" name="s_pain" value="없음"> &#9312; 없음</label><label><input type="radio" name="s_pain" value="다소있음"> &#9313; 다소 있음</label><label><input type="radio" name="s_pain" value="매우심함"> &#9314; 매우 심함</label></div></td></tr>
        <tr><td>5) 병명 및 복용 중인 약</td><td>병명: <input type="text" name="s_disease" class="etc-input" style="width:180px"><span class="th-internet-mo"><br></span><span class="th-internet-pc">&nbsp;</span>복용약: <input type="text" name="s_meds" class="etc-input" style="width:180px"></td></tr>
      </table>

      <div class="section-header">&#9632; 이동지원</div>
      <table class="form-table">
        <tr><td>1) 누군가의 도움 없이 실외 보행에 어려움이 있습니까?</td><td><div class="radio-group"><label><input type="radio" name="s_mob1" value="예"> &#9312; 예</label><label><input type="radio" name="s_mob1" value="아니오"> &#9313; 아니오</label></div></td></tr>
        <tr><td>2) 기존 이동지원서비스 수혜여부</td><td><div class="radio-group"><label><input type="radio" name="s_mob2" value="예"> &#9312; 예</label><label><input type="radio" name="s_mob2" value="아니오"> &#9313; 아니오</label></div></td></tr>
      </table>

      <div class="section-header">&#9632; 서비스 유형별 필요여부 <span style="font-weight:400;font-size:11px;">(조사자가 종합적으로 판단)</span></div>
      <table class="service-table">
        <thead><tr><th>보건의료</th><th><span class="th-internet-pc">건강관리·예방</span><span class="th-internet-mo">건강관리·<br>예방</span></th><th>장기요양</th><th><span class="th-internet-pc" style="white-space:nowrap;">일상생활돌봄</span><span class="th-internet-mo" style="white-space:nowrap;">일상생활<br>돌봄</span></th><th>주거복지</th><th>기타</th></tr></thead>
        <tbody><tr>
          <td><input type="checkbox" name="s_sn" value="보건의료"></td><td><input type="checkbox" name="s_sn" value="건강관리예방"></td>
          <td><input type="checkbox" name="s_sn" value="장기요양"></td><td><input type="checkbox" name="s_sn" value="일상생활돌봄"></td>
          <td><input type="checkbox" name="s_sn" value="주거복지"></td><td><input type="checkbox" name="s_sn" value="기타"></td>
        </tr></tbody>
      </table>

      <div class="section-header">&#9632; 주요 욕구</div>
      <table class="service-table">
        <thead><tr><th>일상생활기능</th><th>인지심리기능</th><th>의료적욕구</th><th>주거환경</th></tr></thead>
        <tbody><tr>
          <td><textarea class="form-textarea" name="s_n_adl" style="min-height:50px;"></textarea></td>
          <td><textarea class="form-textarea" name="s_n_cog" style="min-height:50px;"></textarea></td>
          <td><textarea class="form-textarea" name="s_n_med" style="min-height:50px;"></textarea></td>
          <td><textarea class="form-textarea" name="s_n_hsg" style="min-height:50px;"></textarea></td>
        </tr></tbody>
      </table>

      <div class="section-header">&#9632; 종합의견</div>
      <textarea class="form-textarea" name="s_opinion" style="min-height:80px;" placeholder="조사담당자가 대상자의 현재 생활현황 및 필요 서비스 내용을 종합적으로 기입합니다."></textarea>
      <div class="top-bar bottom-action-bar">
  <a href="/home" class="home-btn">&#8962; 홈으로</a>
  <div class="btn-group">
    <button type="button" class="print-btn" onclick="openEmailPopup()">&#9993; 메일 보내기</button>
    <button type="button" class="print-btn" onclick="doPrint()">&#128196; 출력 / PDF 저장</button>
    <button type="button" class="reset-btn" onclick="resetForm()">&#8635; 다시 입력</button>
  </div>
</div>
    </div><!-- /panel-self -->

    <!-- ══ 탭2: 연계조사 ══ -->
    <div class="tab-panel" id="panel-relay">
      <div class="form-title">통합(종합)판정조사 관련 지자체 연계조사 서식</div>
      <div class="section-header">&#9632; 대상자 기본사항</div>
      <table class="form-table">
        <tr>
          <th>성명</th><td class="td-name personal-disabled"><input type="text" name="r_name" disabled></td>
          <th class="th-gender">성별</th>
          <td class="td-gender personal-disabled"><div class="radio-group"><label><input type="radio" name="r_gender" value="남" disabled> 남</label><label><input type="radio" name="r_gender" value="여" disabled> 여</label></div></td>
          <th class="age-th">연령</th>
          <td class="age-td personal-disabled">만<input type="text" name="r_age_d" class="age-input" disabled>&thinsp;세</td>
          <th class="th-birth">생년<br>월일</th><td class="td-birth personal-disabled"><input type="text" name="r_birth" disabled></td>
        </tr>
        <tr><th>주소</th><td colspan="7" class="personal-disabled"><input type="text" name="r_address" disabled></td></tr>
        <tr><th>실거주지</th><td colspan="7" class="personal-disabled"><input type="text" name="r_real_addr" disabled></td></tr>
        <tr>
          <th rowspan="2">연락처</th>
          <td colspan="3" class="personal-disabled">자택: <input type="text" name="r_tel_home" class="etc-input" style="width:120px" disabled></td>
          <td colspan="4" class="personal-disabled">핸드폰: <input type="text" name="r_tel_mobile" class="etc-input" style="width:120px" disabled></td>
        </tr>
        <tr><td colspan="7" class="personal-disabled">비상연락처: <input type="text" name="r_tel_emg" class="etc-input" style="width:150px" disabled> (관계: <input type="text" name="r_tel_rel" class="etc-input" style="width:70px" disabled>)</td></tr>
        <tr><th>주수<br>발자</th><td colspan="7"><div class="check-group">
          <label><input type="checkbox" name="r_care" value="없음"> 없음</label>
          <label><input type="checkbox" name="r_care" value="배우자"> 배우자</label>
          <label><input type="checkbox" name="r_care" value="자녀"> 자녀(며느리·사위 포함)</label>
          <label><input type="checkbox" name="r_care" value="손자녀"> 손자녀</label>
          <label><input type="checkbox" name="r_care" value="친인척"> 친인척</label>
          <label><input type="checkbox" name="r_care" value="친구이웃"> 친구·이웃</label>
          <label><input type="checkbox" name="r_care" value="사적간병인"> 사적 간병인</label>
          <label><input type="checkbox" name="r_care" value="공적서비스"> 공적서비스 돌봄제공자</label>
          <label><input type="checkbox" name="r_care" value="형제자매"> 형제·자매</label>
          <label><input type="checkbox" name="r_care" value="자원봉사자"> 자원봉사자</label>
          <label><input type="checkbox" name="r_care" value="기타"> 기타(<input type="text" class="etc-input">)</label>
        </div></td></tr>
        <tr><th>가구<br>형태</th><td colspan="7"><div class="radio-group">
          <label><input type="radio" name="r_hh" value="독거"> 독거</label>
          <label><input type="radio" name="r_hh" value="비독거부부"> 비독거(부부)</label>
          <label><input type="radio" name="r_hh" value="노부모"> 노부모</label>
          <label><input type="radio" name="r_hh" value="자녀"> 자녀</label>
          <label><input type="radio" name="r_hh" value="조손"> 조손</label>
          <label><input type="radio" name="r_hh" value="형제자매"> 형제자매</label>
          <label><input type="radio" name="r_hh" value="장애인가구"> 장애인가구</label>
          <label><input type="radio" name="r_hh" value="다문화가구"> 다문화가구</label>
          <label><input type="radio" name="r_hh" value="친척지인"> 친척·지인</label>
          <label><input type="radio" name="r_hh" value="기타"> 기타(<input type="text" class="etc-input">)</label>
        </div></td></tr>
        <tr><th>사회보장<br>수급권</th><td colspan="7"><div class="check-group" style="flex-direction:column;align-items:flex-start;gap:5px;">
          <div class="th-internet-pc" style="display:flex;flex-wrap:wrap;gap:4px 6px;align-items:center;">
            <label><input type="checkbox" name="r_wf" value="국민기초"> 국민기초생활보장제도</label>
            <span style="display:inline-flex;flex-wrap:nowrap;align-items:center;gap:2px;">
            <span style="color:#6b7280;">(</span>
            <label><input type="checkbox" name="r_wf_sub" value="생계급여"> 생계급여</label>
            <label><input type="checkbox" name="r_wf_sub" value="의료급여"> 의료급여</label>
            <label><input type="checkbox" name="r_wf_sub" value="주거급여"> 주거급여</label>
            <span style="color:#6b7280;">)</span>
            </span>
            <label><input type="checkbox" name="r_wf" value="차상위"> 차상위</label>
            <label><input type="checkbox" name="r_wf" value="일반보훈"> 일반(보훈)</label>
          </div>
          <div class="th-internet-mo" style="display:flex;flex-wrap:wrap;gap:4px 6px;align-items:center;">
            <label><input type="checkbox" name="r_wf" value="국민기초"> 국민기초생활보장제도</label>
            <span style="display:inline-flex;flex-wrap:nowrap;align-items:center;gap:2px;">
            <span style="color:#6b7280;">(</span>
            <label><input type="checkbox" name="r_wf_sub" value="생계급여"> 생계급여</label>
            <label><input type="checkbox" name="r_wf_sub" value="의료급여"> 의료급여</label>
            <label><input type="checkbox" name="r_wf_sub" value="주거급여"> 주거급여</label>
            <span style="color:#6b7280;">)</span>
            </span>
          </div>
          <div class="th-internet-mo" style="display:flex;flex-wrap:wrap;gap:4px 6px;align-items:center;">
            <label><input type="checkbox" name="r_wf" value="차상위"> 차상위</label>
            <label><input type="checkbox" name="r_wf" value="일반보훈"> 일반(보훈)</label>
          </div>
          <div style="display:flex;flex-wrap:wrap;gap:4px 10px;align-items:center;">
            <span>주수입원:</span>
            <label><input type="checkbox" name="r_inc" value="공적지원"> 공적지원(사적지원/가족지원)</label>
            <label><input type="checkbox" name="r_inc" value="근로수입"> 근로수입</label>
            <label><input type="checkbox" name="r_inc" value="기타"> 기타(<input type="text" class="etc-input" style="width:80px">)</label>
          </div>
          <div class="th-internet-pc" style="display:flex;flex-wrap:wrap;gap:4px 10px;align-items:center;">
            <span>본인부담 가능여부:</span>
            <label><input type="radio" name="r_copay" value="부담가능"> 부담가능</label>
            <label><input type="radio" name="r_copay" value="일부부담가능"> 일부 부담가능</label>
            <label><input type="radio" name="r_copay" value="부담어려움"> 부담어려움</label>
          </div>
          <div class="th-internet-mo" style="display:flex;flex-wrap:wrap;gap:4px 10px;align-items:center;">
            <span>본인부담 가능여부:</span>
          </div>
          <div class="th-internet-mo" style="display:flex;flex-wrap:wrap;gap:4px 10px;align-items:center;">
            <label><input type="radio" name="r_copay" value="부담가능"> 부담가능</label>
            <label><input type="radio" name="r_copay" value="일부부담가능"> 일부 부담가능</label>
            <label><input type="radio" name="r_copay" value="부담어려움"> 부담어려움</label>
          </div>
        </div></td></tr>
        <tr><th>대상자<br>유형</th><td colspan="7"><div class="check-group" style="flex-direction:column;align-items:flex-start;gap:5px;">
          <div style="display:flex;flex-wrap:wrap;gap:4px 10px;align-items:center;">
            <label><input type="checkbox" name="r_tt" value="해당없음"> 해당없음</label>
            <label><input type="checkbox" name="r_tt" value="장기요양재가"> 장기요양 재가급여자</label>
            <span class="th-internet-pc" style="display:inline;">(</span><label class="th-internet-pc"><input type="checkbox" name="r_tg" value="1등급" style="width:auto;"> 1등급</label><label class="th-internet-pc"><input type="checkbox" name="r_tg" value="2등급" style="width:auto;"> 2등급</label><label class="th-internet-pc"><input type="checkbox" name="r_tg" value="3등급" style="width:auto;"> 3등급</label><label class="th-internet-pc"><input type="checkbox" name="r_tg" value="4등급" style="width:auto;"> 4등급</label><label class="th-internet-pc"><input type="checkbox" name="r_tg" value="5등급" style="width:auto;"> 5등급</label><label class="th-internet-pc"><input type="checkbox" name="r_tg" value="인지등급" style="width:auto;"> 인지등급</label><span class="th-internet-pc" style="display:inline;">)</span>
            <div class="th-internet-mo" style="display:flex;flex-wrap:nowrap;align-items:center;gap:5px;font-size:10px;overflow-x:auto;max-width:100%;"><span style="color:#6b7280;flex-shrink:0;">(</span><label style="font-size:10px;white-space:nowrap;flex-shrink:0;display:inline-flex;align-items:center;gap:1px;line-height:1;"><input type="checkbox" name="r_tg" value="1등급" style="width:11px;height:11px;margin:0;padding:0;vertical-align:middle;flex-shrink:0;"><span>1등급</span></label><label style="font-size:10px;white-space:nowrap;flex-shrink:0;display:inline-flex;align-items:center;gap:1px;line-height:1;"><input type="checkbox" name="r_tg" value="2등급" style="width:11px;height:11px;margin:0;padding:0;vertical-align:middle;flex-shrink:0;"><span>2등급</span></label><label style="font-size:10px;white-space:nowrap;flex-shrink:0;display:inline-flex;align-items:center;gap:1px;line-height:1;"><input type="checkbox" name="r_tg" value="3등급" style="width:11px;height:11px;margin:0;padding:0;vertical-align:middle;flex-shrink:0;"><span>3등급</span></label><label style="font-size:10px;white-space:nowrap;flex-shrink:0;display:inline-flex;align-items:center;gap:1px;line-height:1;"><input type="checkbox" name="r_tg" value="4등급" style="width:11px;height:11px;margin:0;padding:0;vertical-align:middle;flex-shrink:0;"><span>4등급</span></label><label style="font-size:10px;white-space:nowrap;flex-shrink:0;display:inline-flex;align-items:center;gap:1px;line-height:1;"><input type="checkbox" name="r_tg" value="5등급" style="width:11px;height:11px;margin:0;padding:0;vertical-align:middle;flex-shrink:0;"><span>5등급</span></label><label style="font-size:10px;white-space:nowrap;flex-shrink:0;display:inline-flex;align-items:center;gap:1px;line-height:1;"><input type="checkbox" name="r_tg" value="인지등급" style="width:11px;height:11px;margin:0;padding:0;vertical-align:middle;flex-shrink:0;"><span>인지등급</span></label><span style="color:#6b7280;flex-shrink:0;">)</span></div>
          </div>
          <div style="display:flex;flex-wrap:wrap;gap:4px 10px;align-items:center;">
            <label><input type="checkbox" name="r_tt" value="장기요양등급외"> 장기요양 등급외(A, B)</label>
            <label><input type="checkbox" name="r_tt" value="기각각하"> 기각·각하</label>
            <label><input type="checkbox" name="r_tt" value="등급판정신청중"> 장기요양 등급판정 신청 중</label>
          </div>
          <div style="display:flex;flex-wrap:wrap;gap:4px 10px;align-items:center;">
            <label><input type="checkbox" name="r_tt" value="노인맞춤돌봄"> 노인맞춤돌봄서비스</label>
            <span style="display:inline-flex;flex-wrap:nowrap;align-items:center;gap:2px;"><span style="color:#6b7280;">(</span><label><input type="checkbox" name="r_tc" value="일반돌봄군"> 일반돌봄군</label>
            <label><input type="checkbox" name="r_tc" value="중점돌봄군"> 중점돌봄군</label><span style="color:#6b7280;">)</span></span>
            <label><input type="checkbox" name="r_tt" value="퇴원예정자"> 퇴원(예정)자</label>
            <span style="display:inline-flex;flex-wrap:nowrap;align-items:center;gap:2px;"><span style="color:#6b7280;">(</span><label><input type="checkbox" name="r_td" value="의료기관연계"> 의료기관 연계</label>
            <label><input type="checkbox" name="r_td" value="지역사회발굴"> 지역사회 발굴</label><span style="color:#6b7280;">)</span></span>
          </div>
          <div style="display:flex;flex-wrap:wrap;gap:4px 10px;align-items:center;">
            <label><input type="checkbox" name="r_tt" value="장애등록"> 장애등록·정도</label>
            <span style="display:inline-flex;flex-wrap:nowrap;align-items:center;gap:2px;"><span style="color:#6b7280;">(</span><label><input type="checkbox" name="r_tdi" value="심한장애"> 심한 장애</label>
            <label><input type="checkbox" name="r_tdi" value="심하지않은장애"> 심하지 않은 장애</label><span style="color:#6b7280;">)</span></span>
          </div>
          <label><input type="checkbox" name="r_tt" value="기타"> 기타(<input type="text" class="etc-input" style="width:120px">)</label>
        </div></td></tr>
        <tr><th>현재 이용중인<br>서비스</th><td colspan="7"><div class="check-group" style="flex-direction:column;align-items:flex-start;gap:5px;">
          <div style="display:flex;flex-wrap:wrap;gap:4px 10px;align-items:center;">
            <label><input type="checkbox" name="r_sv" value="없음"> 없음</label>
            <label><input type="checkbox" name="r_sv" value="있음"> 있음</label>
            <span class="th-internet-pc" style="display:inline;">— 필요서비스 이용 사유 (사용확인): <input type="text" name="r_sv_confirm" class="etc-input" style="width:130px"></span>
          </div>
          <div class="th-internet-mo" style="display:flex;flex-wrap:wrap;gap:4px 10px;align-items:center;">
            <span style="color:#6b7280;">— 필요서비스 이용 사유 (사용확인):</span>
            <input type="text" name="r_sv_confirm" class="etc-input" style="width:130px">
          </div>
          <div style="display:flex;flex-wrap:wrap;gap:4px 10px;align-items:center;">
            <label><input type="checkbox" name="r_svd" value="노인맞춤돌봄"> 노인맞춤돌봄서비스</label>
            <label><input type="checkbox" name="r_svd" value="치매안심센터"> 치매안심센터</label>
            <label><input type="checkbox" name="r_svd" value="급식도시락반찬"> 급식 및 도시락 반찬</label>
            <label><input type="checkbox" name="r_svd" value="활동보조"> 활동보조</label>
            <label><input type="checkbox" name="r_svd" value="말벗"> 말벗</label>
            <label><input type="checkbox" name="r_svd" value="보건사업"> 보건사업</label>
            <label><input type="checkbox" name="r_svd" value="주거개선사업"> 주거개선사업</label>
            <label><input type="checkbox" name="r_svd" value="건강운동교실"> 건강운동교실</label>
            <label><input type="checkbox" name="r_svd" value="목욕이미용"> 목욕·이미용</label>
            <label><input type="checkbox" name="r_svd" value="이동지원"> 이동지원</label>
            <label><input type="checkbox" name="r_svd" value="노인일자리사업"> 노인일자리 사업</label>
            <label><input type="checkbox" name="r_svd" value="무료진료연계"> 무료진료연계</label>
            <label><input type="checkbox" name="r_svd" value="가사간병방문도움"> 가사간병방문도움</label>
            <label><input type="checkbox" name="r_svd" value="여가문화교육"> 여가, 문화, 교육</label>
            <label><input type="checkbox" name="r_svd" value="기타"> 기타(<input type="text" class="etc-input" style="width:80px">)</label>
          </div>
        </div></td></tr>
        <tr><th>희망<br>서비스</th><td colspan="7"><input type="text" name="r_wish" placeholder="희망하는 서비스를 기입하세요"></td></tr>
      </table>

      <div class="section-header">&#9632; 서비스 유형별 필요여부 <span style="font-weight:400;font-size:11px;">(조사자가 종합적으로 판단)</span></div>
      <table class="service-table">
        <thead><tr><th>보건의료</th><th><span class="th-internet-pc">건강관리·예방</span><span class="th-internet-mo">건강관리·<br>예방</span></th><th>장기요양</th><th><span class="th-internet-pc" style="white-space:nowrap;">일상생활돌봄</span><span class="th-internet-mo" style="white-space:nowrap;">일상생활<br>돌봄</span></th><th>주거복지</th><th>기타</th></tr></thead>
        <tbody><tr>
          <td><input type="checkbox" name="r_sn" value="보건의료"></td><td><input type="checkbox" name="r_sn" value="건강관리예방"></td>
          <td><input type="checkbox" name="r_sn" value="장기요양"></td><td><input type="checkbox" name="r_sn" value="일상생활돌봄"></td>
          <td><input type="checkbox" name="r_sn" value="주거복지"></td><td><input type="checkbox" name="r_sn" value="기타"></td>
        </tr></tbody>
      </table>

      <div class="section-header">&#9632; 종합의견</div>
      <textarea class="form-textarea" name="r_opinion" style="min-height:80px;" placeholder="조사자(지자체 담당자)가 국민건강보험공단 지사 담당자와 동행 시 확인한 사항을 기술하고, 이를 통합지원계획 종합의견에 반영함"></textarea>
      <p class="relay-note" style="display:flex;gap:0.3em;align-items:flex-start;"><span style="flex-shrink:0;">&#10071;</span><span>조사자(지자체 담당자)가 국민건강보험공단 지사 담당자와 동행 시 확인한 사항을 기술하고, 이를 통합지원계획 종합의견에 반영함</span></p>
      <div style="margin-top:20px;display:flex;gap:10px;justify-content:space-between;flex-wrap:wrap;">
        <a href="/home" class="home-btn">&#8962; 홈으로</a>
        <div style="display:flex;gap:10px;flex-wrap:wrap;">
          <button type="button" class="print-btn" onclick="openEmailPopup()">&#9993; 메일 보내기</button>
          <button type="button" class="print-btn" onclick="doPrint()">&#128196; 출력 / PDF 저장</button>
          <button type="button" class="reset-btn" onclick="resetForm()">&#8635; 다시 입력</button>
        </div>
      </div>
    </div><!-- /panel-relay -->

  </div><!-- /form-card -->

<!-- 사전조사 결과 모달 -->
<div id="careResultModal" class="care-modal-overlay">
  <div class="care-modal-box">
    <h3 id="careModalTitle" style="margin-top:0;margin-bottom:12px;">사전조사 결과 안내</h3>
    <div class="care-modal-result-area">
      <p id="care_r_text"></p>
    </div>
    <div class="care-modal-criteria">
      <b>통합돌봄 지원 기준</b><br><br>
      ① 치매약 복약 중인 경우<br>
      → 일상생활 수행능력과 관계없이 통합돌봄 지원 대상<br><br>
      ② 일상생활수행능력(ADL) 점수 기준<br>
      • 0~1점 : 지자체 사업 안내 후 종결<br>
      • 2~3점 : 지자체 자체조사 후 지원 검토<br>
      • 4점 이상 : 통합판정조사 대상<br><br>
      <span style="font-size:11px;color:#666;">
        ※ 본 결과는 통합돌봄 서비스 안내를 위한 참고용 사전조사입니다.<br>
        최종 지원 여부는 지자체 및 공단의 추가 조사 후 결정됩니다.
      </span>
    </div>
    <button onclick="closeCareModal()" class="care-modal-btn">확인</button>
  </div>
</div>

</div><!-- /page-wrap -->

<script>
var currentTab = 'care';
var SURVEY_STORAGE_KEY = 'survey_form_state';

/* ── 개인정보 비활성 셀 클릭 시 안내 팝업 ── */
document.addEventListener('click', function(e){
  var cell = e.target.closest('.personal-disabled');
  if(cell){
    e.preventDefault();
    e.stopPropagation();
    showPersonalBlockAlert();
  }
}, true);

function showPersonalBlockAlert(){
  var existing = document.getElementById('personalBlockToast');
  if(existing) existing.remove();

  var toast = document.createElement('div');
  toast.id = 'personalBlockToast';
  toast.style.cssText = [
    'position:fixed;top:50%;left:50%;transform:translate(-50%,-50%);z-index:10020;',
    'background:#fff;border-radius:14px;padding:32px 28px 24px;width:88%;max-width:340px;',
    'box-shadow:0 12px 40px rgba(0,0,0,0.22);text-align:center;font-family:inherit;',
    'animation:fadeInToast 0.2s ease;'
  ].join('');
  toast.innerHTML = [
    '<div style="font-size:32px;margin-bottom:12px;">🔒</div>',
    '<div style="font-size:15px;font-weight:700;color:#1f2937;line-height:1.6;margin-bottom:8px;">',
    '개인정보 보호를 위해<br>해당 항목은 입력이 제한됩니다.</div>',
    '<div style="font-size:12.5px;color:#6b7280;line-height:1.5;margin-bottom:20px;">',
    '성명·연락처 등 민감정보는<br>본 시스템에서 수집하지 않습니다.</div>',
    '<button onclick="this.parentElement.remove()" ',
    'style="padding:9px 36px;border:none;border-radius:8px;background:#5b7ee5;color:#fff;',
    'font-size:13px;font-weight:600;cursor:pointer;">확인</button>'
  ].join('');
  document.body.appendChild(toast);

  /* 바깥 클릭 시 닫기 */
  setTimeout(function(){
    document.addEventListener('click', function handler(ev){
      if(!toast.contains(ev.target)){
        toast.remove();
        document.removeEventListener('click', handler);
      }
    });
  }, 100);
}

function switchTab(tab) {
  currentTab = tab;
  document.querySelectorAll('.tab-panel').forEach(function(p){ p.classList.remove('active'); });
  document.querySelectorAll('.tab-btn').forEach(function(b){ b.classList.remove('active'); });
  document.getElementById('panel-' + tab).classList.add('active');
  document.getElementById('tab-' + tab).classList.add('active');

  /* 채점배너: 사전조사 탭에서만 표시 */
  var banner = document.getElementById('scoreBanner');
  if(banner){
    if(tab === 'care'){
      banner.classList.remove('hidden-banner');
    } else {
      banner.classList.add('hidden-banner');
    }
  }
}

/* ══════════════════════════════════
   사전조사 로직
   ══════════════════════════════════ */
function showCareGuide(messageHtml){
  document.getElementById("careModalTitle").innerText = "안내";
  document.getElementById("care_r_text").innerHTML = messageHtml;
  document.getElementById("careResultModal").style.display = "block";
}

function showCareResult(title, messageText){
  document.getElementById("careModalTitle").innerText = title;
  document.getElementById("care_r_text").innerText = messageText;
  document.getElementById("careResultModal").style.display = "block";
}

function closeCareModal(){
  document.getElementById("careResultModal").style.display = "none";
}

function getCurrentScore(){
  var score = 0;
  for(var i=0; i<7; i++){
    var checked = document.querySelector('input[name="q'+i+'"]:checked');
    if(checked){ score += Number(checked.value); }
  }
  return score;
}

function getAnsweredCount(){
  var count = 0;
  for(var i=0; i<7; i++){
    var checked = document.querySelector('input[name="q'+i+'"]:checked');
    if(checked){ count += 1; }
  }
  return count;
}

function getBannerState(score, dementiaValue){
  if(!dementiaValue) return "disabled";
  if(dementiaValue === "y") return "state-dementia";
  if(score <= 1) return "state-low";
  else if(score <= 3) return "state-mid";
  else return "state-high";
}

function getScoreStatusText(score, dementiaValue){
  if(!dementiaValue) return "치매 여부를 먼저 선택하세요";
  if(dementiaValue === "y") return "치매약 복용으로 별도 조사 없이 대상입니다";
  if(score <= 1) return "지자체 사업 안내 후 종결 구간입니다";
  else if(score <= 3) return "지자체 자체조사 대상 구간입니다";
  else return "통합판정조사 대상 구간입니다";
}

function getChipText(score, dementiaValue){
  if(!dementiaValue) return "사전 확인 필요";
  if(dementiaValue === "y") return "치매약 복용";
  if(score <= 1) return "0~1점";
  else if(score <= 3) return "2~3점";
  else return "4점 이상";
}

function updateScoreBanner(){
  var banner = document.getElementById("scoreBanner");
  var scoreValue = document.getElementById("scoreValue");
  var answeredCount = document.getElementById("answeredCount");
  var scoreStatus = document.getElementById("scoreStatus");
  var scoreChip = document.getElementById("scoreChip");
  var scoreProgressBar = document.getElementById("scoreProgressBar");
  var dementia = document.querySelector('input[name="dementia"]:checked');

  var score = getCurrentScore();
  var answered = getAnsweredCount();
  var dementiaValue = dementia ? dementia.value : "";

  scoreValue.innerText = score;
  answeredCount.innerText = answered;
  scoreStatus.innerText = getScoreStatusText(score, dementiaValue);
  scoreChip.innerText = getChipText(score, dementiaValue);

  var progress = Math.min((score / 14) * 100, 100);
  if(dementiaValue === "y") progress = 100;
  scoreProgressBar.style.width = progress + "%";

  banner.classList.remove("disabled","state-low","state-mid","state-high","state-dementia");
  var nextState = getBannerState(score, dementiaValue);
  if(nextState === "disabled") banner.classList.add("disabled");
  else banner.classList.add(nextState);
}

/* 사전조사 상태 저장/복원 키 */
var CARE_STORAGE_KEY = "care_form_state";

function saveCareState(){
  var state = {};
  var dementia = document.querySelector('input[name="dementia"]:checked');
  state.dementia = dementia ? dementia.value : null;
  state.adl = {};
  for(var i=0;i<7;i++){
    var r = document.querySelector('input[name="q'+i+'"]:checked');
    state.adl[i] = r ? r.value : null;
  }
  try{ sessionStorage.setItem(CARE_STORAGE_KEY, JSON.stringify(state)); }catch(e){}
}

function restoreCareState(){
  var raw;
  try{ raw = sessionStorage.getItem(CARE_STORAGE_KEY); }catch(e){}
  if(!raw) return;
  var state;
  try{ state = JSON.parse(raw); }catch(e){ return; }

  if(state.dementia){
    var dr = document.querySelector('input[name="dementia"][value="'+state.dementia+'"]');
    if(dr){
      dr.checked = true;
      if(state.dementia === "y"){
        document.getElementById("adlSection").style.opacity = "0.4";
      }
    }
  }

  for(var i=0;i<7;i++){
    if(state.adl && state.adl[i]){
      var ar = document.querySelector('input[name="q'+i+'"][value="'+state.adl[i]+'"]');
      if(ar){
        ar.checked = true;
        var box = ar.closest(".question-box");
        if(box) box.classList.add("active");
      }
    }
  }

  updateScoreBanner();
}

/* 치매 선택 안 했는데 ADL 누르면 차단 */
document.querySelectorAll('#adlSection .options input[type="radio"]').forEach(function(radio){
  radio.addEventListener("change", function(){
    var dementia = document.querySelector('input[name="dementia"]:checked');

    if(!dementia){
      this.checked = false;
      showCareGuide("먼저 <b>치매 관련 약 복용 여부(예/아니오)</b>를<br> 선택해주세요.");
      updateScoreBanner();
      return;
    }

    var box = this.closest(".question-box");
    if(box) box.classList.add("active");

    updateScoreBanner();
    saveCareState();
  });
});

/* 치매 선택 처리 */
document.querySelectorAll('input[name="dementia"]').forEach(function(radio){
  radio.addEventListener("change", function(){
    if(this.value === "y"){
      document.getElementById("adlSection").style.opacity = "0.4";
      showCareGuide("치매약을 복약 중인 경우 일상생활 수행능력과 관계없이 <b>통합돌봄 대상</b>입니다.");
    }else{
      document.getElementById("adlSection").style.opacity = "1";
    }

    updateScoreBanner();
    saveCareState();
  });
});

/* 검사하기 클릭 시 */
document.getElementById("careForm").onsubmit = async function(e){
  e.preventDefault();

  var dementia = document.querySelector('input[name="dementia"]:checked');

  if(!dementia){
    showCareGuide("먼저 <b>치매 관련 약 복용 여부(예/아니오)</b>를 선택해주세요.");
    return;
  }

  if(dementia.value === "y") return;

  for(var i=0; i<7; i++){
    var checked = document.querySelector('input[name="q'+i+'"]:checked');
    if(!checked){
      showCareGuide((i+1) + "번 문항을 선택해주세요.");
      return;
    }
  }

  var formData = new FormData(this);

  var res = await fetch("/care_check",{
    method:"POST",
    body:formData
  });

  var data = await res.json();

  updateScoreBanner();
  showCareResult("사전조사 결과 안내", data.result + "\\n총점: " + data.score);
};

/* 사전조사 상태 복원 */
restoreCareState();
updateScoreBanner();

/* ══════════════════════════════════
   서식(자체/연계) 상태 저장/복원
   ══════════════════════════════════ */
function saveSurveyState(){
  var state = { tab: currentTab, self: {}, relay: {} };
  ['self','relay'].forEach(function(tabName){
    var panel = document.getElementById('panel-' + tabName);
    var s = state[tabName];
    panel.querySelectorAll('input[type=radio]:checked, input[type=checkbox]:checked').forEach(function(el){
      if(!s[el.name]) s[el.name] = [];
      s[el.name].push(el.value);
    });
    panel.querySelectorAll('input[type=text], input[type=date], textarea').forEach(function(el){
      if(el.name) s[el.name] = el.value;
    });
  });
  try{ sessionStorage.setItem(SURVEY_STORAGE_KEY, JSON.stringify(state)); }catch(e){}
}

/* ── 서식 상태 복원 ── */
function restoreSurveyState(){
  var raw;
  try{ raw = sessionStorage.getItem(SURVEY_STORAGE_KEY); }catch(e){}
  if(!raw) return;
  var state;
  try{ state = JSON.parse(raw); }catch(e){ return; }

  if(state.tab && state.tab !== 'care'){
    switchTab(state.tab);
  }

  ['self','relay'].forEach(function(tabName){
    var panel = document.getElementById('panel-' + tabName);
    var s = state[tabName];
    if(!s) return;

    panel.querySelectorAll('input[type=radio], input[type=checkbox]').forEach(function(el){
      if(s[el.name] && s[el.name].indexOf(el.value) !== -1){
        el.checked = true;
      }
    });
    panel.querySelectorAll('input[type=text], input[type=date]').forEach(function(el){
      if(el.name && s[el.name] !== undefined) el.value = s[el.name];
    });
    panel.querySelectorAll('textarea').forEach(function(el){
      if(el.name && s[el.name] !== undefined) el.value = s[el.name];
    });
  });
}

/* 입력 이벤트마다 저장 (debounce) */
var surveyDebounceTimer = null;
function debouncedSave(){
  clearTimeout(surveyDebounceTimer);
  surveyDebounceTimer = setTimeout(saveSurveyState, 300);
}
document.addEventListener('change', function(e){
  if(e.target.closest('#panel-self, #panel-relay')) debouncedSave();
});
document.addEventListener('input', function(e){
  if(e.target.closest('#panel-self, #panel-relay')) debouncedSave();
});

function resetForm() {
  if (!confirm("입력한 내용을 모두 초기화하시겠습니까?")) return;

  if(currentTab === 'care'){
    /* 사전조사 탭 초기화 */
    var carePanel = document.getElementById('panel-care');
    carePanel.querySelectorAll("input[type=radio], input[type=checkbox]").forEach(function(el){ el.checked = false; });
    carePanel.querySelectorAll("input[type=text], input[type=date], textarea").forEach(function(el){ el.value = ""; });
    carePanel.querySelectorAll(".question-box").forEach(function(el){ el.classList.remove("active"); });
    document.getElementById("adlSection").style.opacity = "1";
    try{ sessionStorage.removeItem(CARE_STORAGE_KEY); }catch(e){}
    updateScoreBanner();
    return;
  }

  var panel = document.getElementById('panel-' + currentTab);
  panel.querySelectorAll("input[type=radio], input[type=checkbox]").forEach(function(el){ el.checked = false; });
  panel.querySelectorAll("input[type=text], input[type=date], textarea").forEach(function(el){ el.value = ""; });
  /* 해당 탭 저장 상태도 지우기 */
  try{
    var raw = sessionStorage.getItem(SURVEY_STORAGE_KEY);
    if(raw){
      var st = JSON.parse(raw);
      st[currentTab] = {};
      sessionStorage.setItem(SURVEY_STORAGE_KEY, JSON.stringify(st));
    }
  }catch(e){}
}
function doPrint() {
  document.querySelectorAll('.tab-panel').forEach(function(p){ p.classList.remove('print-target'); });
  document.getElementById('panel-' + currentTab).classList.add('print-target');
  window.print();
}

/* ── 메일 보내기 팝업 ── */
function openEmailPopup() {
  var existing = document.getElementById('emailModal');
  if (existing) existing.remove();

  /* 기본 파일명 생성 */
  var tabLabels = { care: '사전조사', self: '자체조사', relay: '연계조사' };
  var now = new Date();
  var pad2 = function(n){ return n < 10 ? '0'+n : ''+n; };
  var dateStr = now.getFullYear() + pad2(now.getMonth()+1) + pad2(now.getDate())
              + '_' + pad2(now.getHours()) + pad2(now.getMinutes());
  var defaultFileName = (tabLabels[currentTab] || '조사서식') + '_' + dateStr;

  var modal = document.createElement('div');
  modal.id = 'emailModal';
  modal.style.cssText = 'position:fixed;inset:0;z-index:10010;background:rgba(0,0,0,0.5);display:flex;align-items:center;justify-content:center;';
  modal.innerHTML = [
    '<div style="background:#fff;border-radius:14px;padding:28px 24px 22px;width:90%;max-width:380px;box-shadow:0 8px 32px rgba(0,0,0,0.18);font-family:inherit;">',
    '  <h3 style="margin:0 0 6px;font-size:16px;color:#1f2937;">&#9993; 메일로 보내기</h3>',
    '  <p style="margin:0 0 18px;font-size:12.5px;color:#6b7280;line-height:1.5;">현재 탭의 서식을 PDF로 변환하여<br>입력한 이메일 주소로 발송합니다.</p>',
    '  <label style="display:block;font-size:12px;font-weight:600;color:#374151;margin-bottom:4px;">수신자 이메일</label>',
    '  <input type="email" id="emailInput" placeholder="수신자 이메일 주소" ',
    '    style="width:100%;padding:10px 12px;border:1.5px solid #d1d5db;border-radius:8px;font-size:14px;outline:none;box-sizing:border-box;margin-bottom:12px;">',
    '  <label style="display:block;font-size:12px;font-weight:600;color:#374151;margin-bottom:4px;">첨부 파일명</label>',
    '  <div style="display:flex;align-items:center;gap:0;margin-bottom:16px;">',
    '    <input type="text" id="pdfFileNameInput" value="' + defaultFileName + '" ',
    '      style="flex:1;padding:10px 12px;border:1.5px solid #d1d5db;border-radius:8px 0 0 8px;font-size:13px;outline:none;box-sizing:border-box;">',
    '    <span style="padding:10px 12px;background:#f3f4f6;border:1.5px solid #d1d5db;border-left:none;border-radius:0 8px 8px 0;font-size:13px;color:#6b7280;white-space:nowrap;">.pdf</span>',
    '  </div>',
    '  <div id="emailStatus" style="display:none;margin-bottom:12px;padding:8px 12px;border-radius:8px;font-size:12.5px;line-height:1.5;"></div>',
    '  <div style="display:flex;gap:8px;justify-content:flex-end;">',
    '    <button onclick="closeEmailPopup()" style="padding:8px 18px;border:1.5px solid #d1d5db;border-radius:8px;background:#fff;color:#374151;font-size:13px;font-weight:600;cursor:pointer;">취소</button>',
    '    <button id="emailSendBtn" onclick="sendEmailPDF()" style="padding:8px 18px;border:none;border-radius:8px;background:#2563eb;color:#fff;font-size:13px;font-weight:600;cursor:pointer;">발송</button>',
    '  </div>',
    '</div>'
  ].join('');
  document.body.appendChild(modal);
  modal.querySelector('#emailInput').focus();
}

function closeEmailPopup() {
  var m = document.getElementById('emailModal');
  if (m) m.remove();
}

function sendEmailPDF() {
  var emailVal = document.getElementById('emailInput').value.trim();
  if (!emailVal) {
    showEmailStatus('이메일 주소를 입력해주세요.', false);
    return;
  }
  if (!/^[^\\s@]+@[^\\s@]+\\.[^\\s@]+$/.test(emailVal)) {
    showEmailStatus('올바른 이메일 형식이 아닙니다.', false);
    return;
  }

  var btn = document.getElementById('emailSendBtn');
  btn.disabled = true;
  btn.textContent = '발송 중...';
  btn.style.opacity = '0.6';
  showEmailStatus('PDF를 생성하고 메일을 발송 중입니다...', null);

  /* 현재 탭 패널을 html2pdf로 실제 PDF 변환 후 서버로 전송 */
  var panel = document.getElementById('panel-' + currentTab);

  /* 사용자가 입력한 파일명 사용 */
  var fileNameInput = document.getElementById('pdfFileNameInput');
  var pdfFileName = (fileNameInput ? fileNameInput.value.trim() : '') || '조사서식';
  if(!pdfFileName.endsWith('.pdf')) pdfFileName += '.pdf';

  var opt = {
    margin:       [8, 6, 8, 6],
    filename:     pdfFileName,
    image:        { type: 'jpeg', quality: 0.95 },
    html2canvas:  { scale: 2, useCORS: true, scrollY: 0 },
    jsPDF:        { unit: 'mm', format: 'a4', orientation: 'portrait' }
  };

  html2pdf().set(opt).from(panel).outputPdf('blob').then(function(pdfBlob) {
    var formData = new FormData();
    formData.append('to_email', emailVal);
    formData.append('pdf_file', pdfBlob, pdfFileName);
    formData.append('pdf_filename', pdfFileName);

    fetch('/send_email_pdf', {
      method: 'POST',
      body: formData
    })
    .then(function(res){ return res.json(); })
    .then(function(data){
      showEmailStatus(data.message, data.success);
      if (data.success) {
        btn.textContent = '발송 완료';
        btn.style.background = '#22c55e';
        setTimeout(closeEmailPopup, 1500);
      } else {
        btn.disabled = false;
        btn.textContent = '발송';
        btn.style.opacity = '1';
      }
    })
    .catch(function(err){
      btn.disabled = false;
      btn.textContent = '발송';
      btn.style.opacity = '1';
      showEmailStatus('네트워크 오류가 발생했습니다.', false);
    });
  }).catch(function(err){
    btn.disabled = false;
    btn.textContent = '발송';
    btn.style.opacity = '1';
    showEmailStatus('PDF 생성 중 오류가 발생했습니다.', false);
  });
}

function showEmailStatus(msg, success) {
  var st = document.getElementById('emailStatus');
  st.style.display = 'block';
  st.textContent = msg;
  if (success === true) {
    st.style.background = '#ecfdf5';
    st.style.color = '#065f46';
    st.style.border = '1px solid #6ee7b7';
  } else if (success === false) {
    st.style.background = '#fef2f2';
    st.style.color = '#991b1b';
    st.style.border = '1px solid #fca5a5';
  } else {
    st.style.background = '#eff6ff';
    st.style.color = '#1e40af';
    st.style.border = '1px solid #93c5fd';
  }
}

/* 페이지 로드 시 상태 복원 */
restoreSurveyState();

/* ── 은행 앱 스타일 가이드 (한 화면에 전체 표시) ── */
/* ── 4번 카드 가이드 (개별 위치 계산) ── */
function guideStart() {
  if (sessionStorage.getItem('sg_done')) return;

  var isMobile = window.innerWidth < 600;
  var vw = window.innerWidth;
  var vh = window.innerHeight;

  window.scrollTo(0, 0);

  var overlay = document.createElement('div');
  overlay.style.cssText = 'position:fixed;inset:0;z-index:9998;background:rgba(0,0,0,0.62);';
  document.body.appendChild(overlay);

  var prevOverflow = document.body.style.overflow;
  document.body.style.overflow = 'hidden';

  var bubbles = [];

  /* ── 헬퍼: 하이라이트 ── */
  function addHighlight(elId) {
    var el = document.getElementById(elId);
    if (!el) return null;
    var pad = isMobile ? 4 : 6;
    var r = el.getBoundingClientRect();
    var hl = document.createElement('div');
    hl.style.cssText = [
      'position:fixed;z-index:9999;pointer-events:none;border-radius:7px;',
      'border:2px solid rgba(255,255,255,0.9);',
      'box-shadow:0 0 0 3px rgba(91,126,229,0.45);',
      'top:'+(r.top-pad)+'px;left:'+(r.left-pad)+'px;',
      'width:'+(r.width+pad*2)+'px;height:'+(r.height+pad*2)+'px;'
    ].join('');
    document.body.appendChild(hl);
    bubbles.push(hl);
    return r;
  }

  /* ── 헬퍼: 말풍선 ── */
  function makeBubble(title, text, w) {
    var fs      = isMobile ? '10.5px' : '12px';
    var fsTitle = isMobile ? '11px'   : '12.5px';
    var bpd     = isMobile ? '8px 10px 7px' : '13px 16px 12px';
    var b = document.createElement('div');
    b.style.cssText = [
      'position:fixed;z-index:10000;background:#fff;border-radius:11px;',
      'padding:'+bpd+';width:'+w+'px;',
      'box-shadow:0 5px 20px rgba(0,0,0,0.22);',
      'font-family:inherit;pointer-events:none;'
    ].join('');
    b.innerHTML =
      '<div style="font-size:'+fsTitle+';font-weight:700;color:#4a6cd4;margin-bottom:4px;">&#128161; '+title+'</div>'+
      '<div style="font-size:'+fs+';color:#374151;line-height:1.55;word-break:keep-all;">'+text+'</div>';
    document.body.appendChild(b);
    bubbles.push(b);
    return b;
  }

  /* ── 헬퍼: 화살표 ── */
  function addArrow(bubble, dir, posFromEdge) {
    var arrow = document.createElement('div');
    arrow.style.position = 'absolute';
    arrow.style.width = '0';
    arrow.style.height = '0';
    if (dir === 'left') {
      arrow.style.borderTop = '8px solid transparent';
      arrow.style.borderBottom = '8px solid transparent';
      arrow.style.borderRight = '8px solid #fff';
      arrow.style.left = '-8px';
      arrow.style.top = posFromEdge + 'px';
    } else if (dir === 'right') {
      arrow.style.borderTop = '8px solid transparent';
      arrow.style.borderBottom = '8px solid transparent';
      arrow.style.borderLeft = '8px solid #fff';
      arrow.style.right = '-8px';
      arrow.style.top = posFromEdge + 'px';
    } else if (dir === 'up') {
      arrow.style.borderLeft = '8px solid transparent';
      arrow.style.borderRight = '8px solid transparent';
      arrow.style.borderBottom = '8px solid #fff';
      arrow.style.top = '-8px';
      arrow.style.left = posFromEdge + 'px';
    } else if (dir === 'down') {
      arrow.style.borderLeft = '8px solid transparent';
      arrow.style.borderRight = '8px solid transparent';
      arrow.style.borderTop = '8px solid #fff';
      arrow.style.bottom = '-8px';
      arrow.style.left = posFromEdge + 'px';
    }
    bubble.appendChild(arrow);
  }

  /* ========================================
     ① 조사 유형 전환 (탭바) — 말풍선 아래에 여유 있게
     ======================================== */
  var r1 = addHighlight('gt-tabs');
  var b1 = null;
  if (r1) {
    var bw1 = isMobile ? Math.min(Math.floor(vw * 0.72), 260) : 230;
    b1 = makeBubble('조사 유형 전환', '탭을 눌러 <b>사전조사</b>, <b>자체조사</b>, <b>연계조사</b> 서식을 전환할 수 있어요.', bw1);
    if (!isMobile) {
      /* PC: 기존 로직 그대로 */
      requestAnimationFrame(function(){
        var bh1 = b1.offsetHeight;
        var gap1 = 20;
        var bubbleTop = r1.bottom + gap1;
        if (bubbleTop + bh1 > vh - 80) bubbleTop = r1.top - bh1 - gap1;
        var bubbleLeft = Math.max(6, Math.min(r1.left, vw - bw1 - 6));
        b1.style.top = bubbleTop + 'px';
        b1.style.left = bubbleLeft + 'px';
        var arrowLeft = Math.max(10, Math.min(r1.left + r1.width/2 - bubbleLeft - 8, bw1 - 26));
        if (bubbleTop > r1.bottom) { addArrow(b1, 'up', arrowLeft); }
        else { addArrow(b1, 'down', arrowLeft); }
      });
    }
    /* 모바일은 b3 배치 완료 후 아래에서 처리 */
  }

  /* ========================================
     ③ 상단 버튼 그룹 (메일보내기 · 출력/PDF · 다시입력)
     — 3개 버튼을 하나로 묶어 하이라이트, 말풍선 1개로 안내
     ======================================== */
  var btnGroupEl = document.querySelector('.btn-group');
  var r3 = null;
  if (btnGroupEl) {
    var pad3 = isMobile ? 4 : 6;
    var bgR = btnGroupEl.getBoundingClientRect();
    r3 = { top: bgR.top, bottom: bgR.bottom, left: bgR.left, right: bgR.right,
           width: bgR.width, height: bgR.height };
    var hl3 = document.createElement('div');
    hl3.style.cssText = [
      'position:fixed;z-index:9999;pointer-events:none;border-radius:7px;',
      'border:2px solid rgba(255,255,255,0.9);',
      'box-shadow:0 0 0 3px rgba(91,126,229,0.45);',
      'top:'+(r3.top-pad3)+'px;left:'+(r3.left-pad3)+'px;',
      'width:'+(r3.width+pad3*2)+'px;height:'+(r3.height+pad3*2)+'px;'
    ].join('');
    document.body.appendChild(hl3);
    bubbles.push(hl3);
  }
  if (r3) {
    var bw3 = isMobile ? Math.min(Math.floor(vw * 0.72), 260) : 260;
    var b3 = makeBubble('상단 버튼 안내',
      '<b>메일 보내기</b> : 서식을 PDF로 변환하여 이메일 발송<br>' +
      '<b>출력 / PDF 저장</b> : 현재 탭 서식을 인쇄하거나 PDF로 저장<br>' +
      '<b>다시 입력</b> : 입력 내용을 초기화', bw3);
    requestAnimationFrame(function(){
      var bh3 = b3.offsetHeight;
      var gap3 = isMobile ? 14 : 20;

      if (isMobile) {
        /* ── 모바일 전용: b3(우측) / b1(좌측) 완전 분리 배치 ──
           좌우 절반씩 차지하므로 가로로 겹쳐도 시각적으로 구분됨 */
        var halfW = Math.floor((vw - 18) / 2);

        /* b3: 상단 버튼 안내 → 우측 고정, r3 우측 끝 가리킴 */
        var left3 = vw - halfW - 6;
        var top3  = r3.bottom + gap3;
        b3.style.width = halfW + 'px';
        b3.style.top   = top3 + 'px';
        b3.style.left  = left3 + 'px';
        addArrow(b3, 'up', Math.max(10, Math.min(
          Math.round(r3.right) - left3 - 16, halfW - 26
        )));

        /* b1: 조사 유형 전환 → 좌측 고정, r1 바로 아래에 붙임 (밀림 없음) */
        if (b1 && r1) {
          var top1  = r1.bottom + gap3;
          var left1 = 6;
          b1.style.width = halfW + 'px';
          b1.style.top   = top1 + 'px';
          b1.style.left  = left1 + 'px';
          addArrow(b1, 'up', Math.max(10, Math.min(
            Math.round(r1.left) - left1 + 12, halfW - 26
          )));
        }
      } else {
        /* PC: 기존처럼 바로 아래에 말풍선 + 화살표 */
        var bubbleLeft = Math.max(6, Math.min(r3.left + r3.width/2 - bw3/2, vw - bw3 - 6));
        var bubbleTop3 = r3.bottom + gap3;
        if (bubbleTop3 + bh3 > vh - 80) bubbleTop3 = r3.top - bh3 - gap3;
        b3.style.top = bubbleTop3 + 'px';
        b3.style.left = bubbleLeft + 'px';
        var arrowLeft3 = Math.max(10, Math.min(r3.left + r3.width/2 - bubbleLeft - 8, bw3 - 26));
        if (bubbleTop3 > r3.bottom) {
          addArrow(b3, 'up', arrowLeft3);
        } else {
          addArrow(b3, 'down', arrowLeft3);
        }
      }
    });
  }

  /* 확인 버튼 */
  var confirmBtn = document.createElement('button');
  confirmBtn.textContent = '확인';
  confirmBtn.style.cssText = [
    'position:fixed;z-index:10001;',
    'left:50%;transform:translateX(-50%);bottom:14%;',
    'background:#2563eb;color:#fff;border:none;',
    'border-radius:10px;',
    'padding:'+(isMobile?'10px 40px':'11px 52px')+';',
    'font-size:'+(isMobile?'13px':'14px')+';font-weight:700;cursor:pointer;',
    'box-shadow:0 4px 16px rgba(37,99,235,0.35);white-space:nowrap;'
  ].join('');
  document.body.appendChild(confirmBtn);
  bubbles.push(confirmBtn);

  function closeGuide() {
    bubbles.forEach(function(b){ b.remove(); });
    overlay.remove();
    document.body.style.overflow = prevOverflow;
    sessionStorage.setItem('sg_done', '1');
  }

  confirmBtn.addEventListener('click', function(e){ e.stopPropagation(); closeGuide(); });
  overlay.addEventListener('click', closeGuide);
}


// 직접욕구 툴팁 — 모바일 탭 지원
document.querySelectorAll('.direct-need-tooltip-icon').forEach(function(icon){
  icon.addEventListener('click', function(e){
    e.stopPropagation();
    var box = icon.parentElement.querySelector('.direct-need-tooltip-box');
    if(!box) return;
    var visible = box.style.display === 'block';
    document.querySelectorAll('.direct-need-tooltip-box').forEach(function(b){ b.style.display='none'; });
    box.style.display = visible ? 'none' : 'block';
  });
});
document.addEventListener('click', function(){
  document.querySelectorAll('.direct-need-tooltip-box').forEach(function(b){ b.style.display='none'; });
});

// 가이드 투어 제거: 자동 실행하지 않음
</script>
</body>
</html>
"""

@app.route("/send_email_pdf", methods=["POST"])
@login_required
def send_email_pdf():
    """클라이언트에서 생성한 PDF를 메일로 전송"""
    try:
        to_email = request.form.get("to_email", "").strip()
        if not to_email:
            return jsonify({"success": False, "message": "수신 이메일 주소를 입력해주세요."})

        pdf_file = request.files.get("pdf_file")
        if not pdf_file:
            return jsonify({"success": False, "message": "PDF 파일이 전송되지 않았습니다."})

        gmail_user = os.getenv("GMAIL_USER", "")
        gmail_app_pw = os.getenv("GMAIL_APP_PASSWORD", "")
        if not gmail_user or not gmail_app_pw:
            return jsonify({"success": False, "message": "메일 설정이 되어있지 않습니다. 관리자에게 문의하세요."})

        pdf_bytes = pdf_file.read()

        # 클라이언트에서 보낸 파일명 사용 (없으면 기본값)
        pdf_filename = request.form.get("pdf_filename", "").strip()
        if not pdf_filename:
            now_kst = datetime.datetime.now(ZoneInfo("Asia/Seoul"))
            pdf_filename = f"조사서식_{now_kst.strftime('%Y%m%d_%H%M')}.pdf"

        msg = MIMEMultipart()
        msg["From"] = gmail_user
        msg["To"] = to_email
        msg["Subject"] = "통합돌봄 지자체 조사 서식"

        body = MIMEText("통합돌봄 지자체 조사 서식 PDF를 첨부합니다.\n\n※ 본 메일은 케어네비 시스템에서 자동 발송되었습니다.", "plain", "utf-8")
        msg.attach(body)

        part = MIMEBase("application", "pdf")
        part.set_payload(pdf_bytes)
        encoders.encode_base64(part)
        part.add_header("Content-Disposition", "attachment", filename=pdf_filename)
        msg.attach(part)

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(gmail_user, gmail_app_pw)
            server.sendmail(gmail_user, to_email, msg.as_string())

        return jsonify({"success": True, "message": f"{to_email}로 메일이 발송되었습니다."})

    except Exception as e:
        return jsonify({"success": False, "message": f"메일 발송 중 오류가 발생했습니다: {str(e)}"})


@app.route("/survey")
@login_required
def survey():
    return render_template_string(
        SURVEY_HTML,
        questions=list(enumerate(CARE_QUESTIONS))
    )

@app.route("/nhis25")
@login_required
def nhis25():
    return render_template_string(NHIS25_HTML, style=BASE_STYLE)

@app.route("/app-version.json")
def app_version():
    return {
        "latestAppVersionCode": 8,
        "latestAppVersionName": "1.8",
        "apkUrl": "https://carenavi.kr/static/carenavi.apk",
        "message": "케어네비 새 버전이 있습니다. 업데이트해 주세요."
    }

if __name__ == "__main__":
    app.run()