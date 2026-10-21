from flask import Flask, render_template_string, request, jsonify, redirect, url_for, session, send_file, Response
import pandas as pd
import os
import hashlib
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
from werkzeug.security import generate_password_hash, check_password_hash

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

# =========================
# 점검 모드 (서버 점검 시 전체 이용자 접근 차단)
# - Supabase에 상태 저장 → 재배포/재시작 후에도 유지됨
# - 관리자(is_admin)는 점검 중에도 전체 페이지 접근 가능 (테스트용)
# - 매 요청마다 DB 조회하지 않도록 짧은 캐시(_MAINT_TTL초) 사용
# =========================
import time as _maint_time

_MAINT_CACHE = {"data": {"on": False, "message": "", "resume_at": ""}, "ts": 0}
_MAINT_TTL = 5  # 초

def _load_maintenance_state():
    now = _maint_time.time()
    if now - _MAINT_CACHE["ts"] < _MAINT_TTL:
        return _MAINT_CACHE["data"]

    if os.getenv("RENDER") is not None:
        try:
            res = requests.get(
                f"{SUPABASE_URL}/rest/v1/maintenance_mode?select=*&id=eq.1",
                headers=SUPABASE_HEADERS,
                timeout=3
            )
            rows = res.json() if res.ok else []
            if rows:
                row = rows[0]
                _MAINT_CACHE["data"] = {
                    "on": bool(row.get("is_on")),
                    "message": row.get("message") or "",
                    "resume_at": row.get("resume_at") or "",
                }
        except Exception:
            pass

    _MAINT_CACHE["ts"] = now
    return _MAINT_CACHE["data"]

def _save_maintenance_state(on, message, resume_at):
    _MAINT_CACHE["data"] = {"on": on, "message": message, "resume_at": resume_at}
    _MAINT_CACHE["ts"] = _maint_time.time()

    if os.getenv("RENDER") is not None:
        try:
            requests.patch(
                f"{SUPABASE_URL}/rest/v1/maintenance_mode?id=eq.1",
                headers=SUPABASE_HEADERS,
                json={"is_on": on, "message": message, "resume_at": resume_at},
                timeout=3
            )
        except Exception:
            pass

# =========================
# 설문조사 ON/OFF (메인화면 + 메뉴 노출 여부)
# - maintenance_mode 테이블의 id=2 행을 재사용 (is_on=True 이면 노출). 행이 없으면 기본 ON
# =========================
_SURVEY_CACHE = {"on": True, "ts": 0}
_SURVEY_TTL = 5  # 초

def _survey_is_on():
    now = _maint_time.time()
    if now - _SURVEY_CACHE["ts"] < _SURVEY_TTL:
        return _SURVEY_CACHE["on"]
    if os.getenv("RENDER") is not None:
        try:
            res = requests.get(
                f"{SUPABASE_URL}/rest/v1/maintenance_mode?select=is_on&id=eq.2",
                headers=SUPABASE_HEADERS, timeout=3
            )
            rows = res.json() if res.ok else []
            if rows:
                _SURVEY_CACHE["on"] = bool(rows[0].get("is_on"))
        except Exception:
            pass
    _SURVEY_CACHE["ts"] = now
    return _SURVEY_CACHE["on"]

def _survey_set_on(on):
    _SURVEY_CACHE["on"] = bool(on)
    _SURVEY_CACHE["ts"] = _maint_time.time()
    if os.getenv("RENDER") is not None:
        try:
            requests.post(
                f"{SUPABASE_URL}/rest/v1/maintenance_mode?on_conflict=id",
                headers={**SUPABASE_HEADERS, "Prefer": "resolution=merge-duplicates,return=minimal"},
                json={"id": 2, "is_on": bool(on), "message": "survey", "resume_at": ""},
                timeout=5
            )
        except Exception:
            pass

# === GPT 토큰 단가/환율 (변동 시 여기만 수정) ===
GPT_PRICE_INPUT_USD = 0.40    # 입력 100만 토큰당 USD (gpt-4.1-mini)
GPT_PRICE_OUTPUT_USD = 1.60   # 출력 100만 토큰당 USD (gpt-4.1-mini)
USD_TO_KRW = 1500             # 환율(원/$), 현재 약 1,540원

def add_token_usage(input_tokens, output_tokens):
    """GPT 호출 토큰을 날짜별로 Supabase token_usage 테이블에 누적 (best-effort)."""
    if os.getenv("RENDER") is None:
        return
    try:
        input_tokens = int(input_tokens or 0)
        output_tokens = int(output_tokens or 0)
        if input_tokens <= 0 and output_tokens <= 0:
            return
        today = datetime.datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d")
        r = requests.get(
            f"{SUPABASE_URL}/rest/v1/token_usage?usage_date=eq.{today}&select=input_tokens,output_tokens",
            headers=SUPABASE_HEADERS, timeout=8
        )
        rows = r.json() if r.ok else []
        if rows:
            cur_in = int(rows[0].get("input_tokens", 0) or 0)
            cur_out = int(rows[0].get("output_tokens", 0) or 0)
            requests.patch(
                f"{SUPABASE_URL}/rest/v1/token_usage?usage_date=eq.{today}",
                headers=SUPABASE_HEADERS,
                json={"input_tokens": cur_in + input_tokens, "output_tokens": cur_out + output_tokens},
                timeout=8
            )
        else:
            requests.post(
                f"{SUPABASE_URL}/rest/v1/token_usage",
                headers=SUPABASE_HEADERS,
                json={"usage_date": today, "input_tokens": input_tokens, "output_tokens": output_tokens},
                timeout=8
            )
    except Exception as e:
        app.logger.exception(e)


def classify_client_env():
    """User-Agent 원문은 저장하지 않고 접속 환경만 4개 범주로 분류."""
    ua = (request.headers.get("User-Agent", "") or "").lower()

    if "iphone" in ua or "ipad" in ua or "ipod" in ua:
        return "iOS"
    if "android" in ua:
        return "Android"
    if "mobile" in ua:
        return "Other"
    return "PC"


def add_env_usage():
    """총 방문자수 기준 접속 환경 집계. User-Agent 원문/IP/검색어는 저장하지 않음."""
    if os.getenv("RENDER") is None:
        return

    try:
        env = classify_client_env()
        res = requests.get(
            f"{SUPABASE_URL}/rest/v1/env_stats?env=eq.{env}&select=count",
            headers=SUPABASE_HEADERS,
            timeout=5
        )
        rows = res.json() if res.ok else []

        if rows:
            cur = int(rows[0].get("count", 0) or 0)
            requests.patch(
                f"{SUPABASE_URL}/rest/v1/env_stats?env=eq.{env}",
                headers=SUPABASE_HEADERS,
                json={"count": cur + 1},
                timeout=5
            )
        else:
            requests.post(
                f"{SUPABASE_URL}/rest/v1/env_stats",
                headers=SUPABASE_HEADERS,
                json={"env": env, "count": 1},
                timeout=5
            )
    except Exception:
        pass

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
                res = requests.get(select_url, headers=SUPABASE_HEADERS, timeout=5)
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
    res = requests.get(select_url, headers=SUPABASE_HEADERS, timeout=5)
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
            },
            timeout=5
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
            },
            timeout=5
        )

    # 접속 환경 집계 — User-Agent 원문은 저장하지 않고 PC/Android/iOS/기타 카운트만 누적
    add_env_usage()

    # 방문 로그 저장 — 일자별 방문자수 집계용 (IP 미수집, 방문 시각만)
    # (총/오늘 방문자 수는 visit_stats 카운터로 계속 집계됨)
    _pv_threading.Thread(target=_visit_log_insert, daemon=True).start()

    # 마지막 방문 시각 저장
    session["last_visit_time"] = now.isoformat()

    return total, today_count

# 운영환경에서는 반드시 환경변수로 설정하세요.
# Render 운영환경에서는 USER_PASSWORD_HASH, ADMIN_PASSWORD_HASH가 비어 있으면 로그인이 되지 않습니다.
app.secret_key = os.getenv("FLASK_SECRET_KEY", "local_dev_secret_key_change_me")
USER_PASSWORD_HASH = os.getenv("USER_PASSWORD_HASH", "")
ADMIN_PASSWORD_HASH = os.getenv("ADMIN_PASSWORD_HASH", "")

# 로컬 테스트가 필요할 때만 .env에 LOCAL_DEV=1을 넣으세요.
# - 사용자: 1234
# - 관리자: qwer
# 주의: Render에는 LOCAL_DEV를 절대 넣지 마세요.
if os.getenv("LOCAL_DEV") == "1":
    USER_PASSWORD_HASH = generate_password_hash("1234")
    ADMIN_PASSWORD_HASH = generate_password_hash("qwer")

@app.route("/favicon.ico")
def favicon():
    return "", 204

@app.errorhandler(405)
def method_not_allowed(e):
    app.logger.error(f"405 - {request.method} {request.path}")
    return e, 405

import logging

# =========================
# 운영 로그 최소화
# - Render/Gunicorn/Flask 기본 요청 로그를 최대한 차단
# - 검색어, 토큰, 추천 결과 같은 민감 정보는 print로 남기지 않음
# =========================
logging.getLogger('werkzeug').disabled = True
logging.getLogger('werkzeug').setLevel(logging.CRITICAL)
logging.getLogger('gunicorn.access').disabled = True
logging.getLogger('gunicorn.access').setLevel(logging.CRITICAL)
logging.getLogger('flask.app').setLevel(logging.ERROR)

@app.before_request
def require_login_all_pages():
    # ---- 점검 모드: 관리자 관련 경로/정적 파일 제외 전체 차단 ----
    maint = _load_maintenance_state()
    if maint["on"]:
        if not (
            request.path.startswith("/admin")
            or request.path.startswith("/static")
            or request.path == "/favicon.ico"
            or request.path == "/app-version.json"
            or session.get("is_admin")
        ):
            return render_template_string(
                MAINTENANCE_HTML,
                message=maint["message"],
                resume_at=maint["resume_at"],
            ), 503

    if (
        request.path == "/"
        or request.path == "/login"
        or request.path == "/admin"
        or request.path == "/privacy"
        or request.path == "/satisfaction"
        or request.path == "/satisfaction/submit"
        or request.path == "/app-version.json"
        or request.path.startswith("/static")
    ):
        return None

    if request.path.startswith("/admin/maintenance"):
        if not session.get("is_admin"):
            return redirect(url_for("admin_login"))
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

# =========================
# 페이지뷰(PV) 집계 — 메인 방문자수와 별개. 관리자 통계용.
# 응답 지연 방지를 위해 비동기 스레드로 적재. (테이블 없으면 조용히 무시)
# =========================
import threading as _pv_threading

# 페이지뷰로 집계할 화이트리스트 (이 6개만 수집). path → 표시이름
# /manual 은 사용설명서 모달(openGuide)에서 핑(/pv/guide)으로 적재됨 (실제 라우트 아님)
_PV_TRACK = {
    "/desc": "사례검색",
    "/combo": "기관검색",
    "/survey": "조사서식",
    "/guide": "사업안내",
    "/nhis25": "건강보험25시",
    "/manual": "사용설명서",
    "/pill": "알약확인",
    "/dolbomon": "돌봄온",
}

def _pv_insert(path):
    try:
        # 페이지뷰에는 실제 접속 시각을 수집하지 않고 한국 날짜만 전송.
        # created_at은 기존 통계 조회 호환을 위해 날짜 문자열로 유지.
        # DB가 timestamp형이면 날짜를 자정으로 표시할 수 있지만 실제 시각은 수집하지 않음.
        _today_kst = datetime.datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d")
        requests.post(
            f"{SUPABASE_URL}/rest/v1/page_view_logs",
            headers=SUPABASE_HEADERS,
            json={"path": path, "created_at": _today_kst},
            timeout=5
        )
    except Exception:
        pass

def _visit_log_insert():
    """일자별 방문자수 집계용. 개별 방문 시각(타임스탬프)은 전혀 저장하지 않고,
    '오늘 날짜'의 합계 카운트만 +1 한다 (visit_stats/env_stats와 동일한 방식)."""
    try:
        today = datetime.datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d")
        res = requests.get(
            f"{SUPABASE_URL}/rest/v1/visit_daily_counts?visit_date=eq.{today}&select=count",
            headers=SUPABASE_HEADERS,
            timeout=5
        )
        rows = res.json() if res.ok else []

        if rows:
            cur = int(rows[0].get("count", 0) or 0)
            requests.patch(
                f"{SUPABASE_URL}/rest/v1/visit_daily_counts?visit_date=eq.{today}",
                headers=SUPABASE_HEADERS,
                json={"count": cur + 1},
                timeout=5
            )
        else:
            requests.post(
                f"{SUPABASE_URL}/rest/v1/visit_daily_counts",
                headers=SUPABASE_HEADERS,
                json={"visit_date": today, "count": 1},
                timeout=5
            )
    except Exception:
        pass

def _region_log_insert(sido, sigungu, search_type):
    """일자별 지역 클릭수 집계용. 지역(시도/시군구)·검색구분만 적재 (IP 미수집)."""
    try:
        requests.post(
            f"{SUPABASE_URL}/rest/v1/region_logs",
            headers=SUPABASE_HEADERS,
            json={"sido": sido, "sigungu": sigungu, "search_type": search_type},
            timeout=5
        )
    except Exception:
        pass

def fetch_all_rows(path_and_query, step=1000, timeout=8):
    """PostgREST 기본 행수 상한(1000) 우회 — Range 헤더로 전체 행을 나눠 받는다.
    path_and_query 예: "region_logs?select=created_at,sido&order=created_at.desc"
    (테이블이 1000행을 넘으면 단일 요청은 일부만 돌려줘 집계가 틀어지므로 필수)"""
    rows = []
    try:
        offset = 0
        while True:
            res = requests.get(
                f"{SUPABASE_URL}/rest/v1/{path_and_query}",
                headers={
                    **SUPABASE_HEADERS,
                    "Range-Unit": "items",
                    "Range": f"{offset}-{offset + step - 1}",
                },
                timeout=timeout
            )
            if not res.ok:
                break
            batch = res.json()
            if not isinstance(batch, list) or not batch:
                break
            rows.extend(batch)
            if len(batch) < step:      # 마지막 페이지
                break
            offset += step
            if offset > 500000:        # 안전장치 (무한루프 방지)
                break
    except Exception:
        pass
    return rows

def cleanup_old_board_posts():
    """의견보내기 게시글 1년 경과 시 자동 삭제"""
    if os.getenv("RENDER") is None:
        return

    try:
        cutoff = (
            datetime.datetime.now(datetime.timezone.utc)
            - datetime.timedelta(days=365)
        ).isoformat()

        requests.delete(
            f"{SUPABASE_URL}/rest/v1/board_posts?created_at=lt.{cutoff}",
            headers=SUPABASE_HEADERS,
            timeout=5
        )
    except Exception:
        pass

@app.before_request
def track_page_view():
    if os.getenv("RENDER") is None:
        return None
    if request.method != "GET":
        return None
    if not (session.get("logged_in") or session.get("is_admin")):
        return None
    path = request.path or ""
    # 허용목록에 있는 실제 페이지만 집계 (/manual은 핑 라우트에서 직접 적재)
    if path not in _PV_TRACK or path == "/manual":
        return None
    try:
        _pv_threading.Thread(target=_pv_insert, args=(path,), daemon=True).start()
    except Exception:
        pass
    return None

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
<title>케어내비 로그인</title>

<style>
*{ box-sizing:border-box; }

body{
  margin:0;
  min-height:100vh;
  font-family:'Pretendard',sans-serif;
  background:#e8ecf4;
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
  box-shadow:0 16px 38px rgba(15,23,42,0.15);
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

/* 일반 사용자 로그인: 비밀번호 확인 버튼 (기본값은 숨김) */
.login-pw-wrap{ position:relative; }
.login-pw-wrap input{ padding-right:58px; }
.login-pw-toggle{
  position:absolute;
  right:8px;
  top:7px;
  width:42px;
  height:40px;
  display:flex;
  align-items:center;
  justify-content:center;
  margin:0;
  padding:0;
  border:0;
  border-radius:8px;
  background:transparent;
  color:#b0b9c6;
  box-shadow:none;
  cursor:pointer;
}
.login-pw-toggle:hover{ background:#f1f5f9; }
.login-pw-toggle svg{ width:20px; height:20px; stroke:currentColor; fill:none; stroke-width:1.5; stroke-linecap:round; stroke-linejoin:round; }
.login-pw-toggle[aria-pressed="true"]::after{
  content:"";
  position:absolute;
  width:27px;
  height:1.5px;
  background:currentColor;
  transform:rotate(-43deg);
  border-radius:2px;
  box-shadow:0 -2px #fff;
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
  box-shadow:0 16px 38px rgba(15,23,42,0.15);
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


/* === 버튼 누름 효과 B (디자인 전용) === */
button, input[type="submit"], input[type="button"], a.card, .btn, .home-btn, .home-button, .reset-btn, .home-help-btn, .home-notice-btn, .tip-btn, #fabMain, .fab-item, [class*="-btn"], [class*="-button"] { transition:transform .12s ease, box-shadow .12s ease; }
button:active, input[type="submit"]:active, input[type="button"]:active, .btn:active, .home-btn:active, .home-button:active, .reset-btn:active, .home-help-btn:active, .home-notice-btn:active, .tip-btn:active, #fabMain:active, .fab-item:active, [class*="-btn"]:active, [class*="-button"]:active { transform:scale(0.92) !important; }
</style>
</head>

<body>
<div class="box">
  <a href="/admin" class="admin-link">관리자</a>

  <div class="simple-logo">케어내비</div>
  <div class="logo-line"></div>
  <div class="sub-title">통합돌봄 지원 프로그램 사용자 로그인</div>

  {% if error %}
    <div class="error-msg">❌ {{error}}</div>
  {% endif %}
  <div id="care-login-error" class="error-msg" role="alert" style="display:none;"></div>

  <form method="post" class="form-area">
    <div class="login-pw-wrap">
      <input type="password" id="care-login-password" name="password" placeholder="비밀번호를 입력하세요" autocapitalize="off" autocomplete="off" autocorrect="off" spellcheck="false">
      <button type="button" id="care-login-pw-toggle" class="login-pw-toggle" aria-label="비밀번호 보기" aria-pressed="false"><svg aria-hidden="true" viewBox="0 0 24 24"><path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12Z"/><circle cx="12" cy="12" r="3"/></svg></button>
    </div>
    <button type="submit">로그인</button>
  </form>

  <div class="notice">
    ※ 본 서비스는 광주전라제주지역본부<br>
    관할 지자체, 지사 직원을 대상으로 운영됩니다.
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

  var pwInput = document.getElementById('care-login-password');
  var pwToggle = document.getElementById('care-login-pw-toggle');
  var loginForm = pwInput && pwInput.form;
  var loginError = document.getElementById('care-login-error');
  if(loginForm && loginError && window.fetch){
    loginForm.addEventListener('submit', function(event){
      event.preventDefault();
      var submitButton = loginForm.querySelector('button[type="submit"]');
      if(submitButton.disabled) return;
      submitButton.disabled = true;
      fetch(loginForm.action || window.location.href, {
        method: 'POST',
        headers: {'X-CareNavi-Async-Login': '1', 'Accept': 'application/json'},
        body: new FormData(loginForm),
        credentials: 'same-origin'
      }).then(function(response){
        return response.json();
      }).then(function(data){
        if(data.ok && data.redirect){
          window.location.assign(data.redirect);
          return;
        }
        loginError.textContent = '❌ ' + (data.error || '로그인에 실패했습니다.');
        loginError.style.display = 'block';
        // 입력창과 눈 아이콘의 상태를 유지해 사용자가 입력 내용을 확인할 수 있게 합니다.
      }).catch(function(){
        loginError.textContent = '❌ 연결 오류가 발생했습니다. 잠시 후 다시 시도해 주세요.';
        loginError.style.display = 'block';
      }).finally(function(){
        submitButton.disabled = false;
      });
    });
  }
  if(pwInput && pwToggle){
    pwToggle.addEventListener('click', function(){
      var show = pwInput.type === 'password';
      pwInput.type = show ? 'text' : 'password';
      pwToggle.setAttribute('aria-label', show ? '비밀번호 숨기기' : '비밀번호 보기');
      pwToggle.setAttribute('aria-pressed', show ? 'true' : 'false');
    });
  }

  if(window.AndroidAppInfo){
    try{
      var name = window.AndroidAppInfo.getVersionName();
      var el = document.getElementById('cn-app-version');
      if(el) el.textContent = '케어내비 v' + name;
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
  background:#e8ecf4;
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
  box-shadow:0 16px 38px rgba(15,23,42,0.15);
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
  background:linear-gradient(135deg,#334155,#0f172a);
  color:#ffffff;
  font-size:17px;
  font-weight:700;
  cursor:pointer;
  transition:all 0.15s;
  box-shadow:0 4px 14px rgba(15,23,42,0.3);
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
    box-shadow:0 16px 38px rgba(15,23,42,0.15);
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

/* === 버튼 누름 효과 B (디자인 전용) === */
button, input[type="submit"], input[type="button"], a.card, .btn, .home-btn, .home-button, .reset-btn, .home-help-btn, .home-notice-btn, .tip-btn, #fabMain, .fab-item, [class*="-btn"], [class*="-button"] { transition:transform .12s ease, box-shadow .12s ease; }
button:active, input[type="submit"]:active, input[type="button"]:active, .btn:active, .home-btn:active, .home-button:active, .reset-btn:active, .home-help-btn:active, .home-notice-btn:active, .tip-btn:active, #fabMain:active, .fab-item:active, [class*="-btn"]:active, [class*="-button"]:active { transform:scale(0.92) !important; }
</style>
</head>

<body>
<div class="box">
  <div class="simple-logo">관리자 인증</div>
  <div class="logo-line"></div>
  <div class="sub-title">관리자 페이지 접근을 위해 관리자 암호를 입력하세요.</div>

  {% if error %}
    <div class="error-msg">❌ {{error}}</div>
  {% endif %}

  <form method="post" class="form-area">
    <input type="password" name="password" placeholder="관리자 암호를 입력하세요" autocapitalize="off" autocomplete="off" autocorrect="off" spellcheck="false">
    <button type="submit">관리자 페이지로 이동</button>
  </form>

  <a href="/login" class="back-link">로그인 페이지로 돌아가기</a>
</div>
</body>
</html>
"""



# =========================
# 로그인 라우트
# =========================
# 비밀번호 원문이나 검증용 값을 로그에 저장하지 않고, 직전 입력과 동일했는지만 비교합니다.
# 비밀 키는 서버 프로세스 메모리에만 존재하고 재시작 시 교체됩니다.
_LOGIN_DIAG_KEY = os.urandom(32)
_LOGIN_DIAG_INSTANCE = os.urandom(8).hex()

def _login_diag_input_tag(password):
    return hashlib.blake2b(
        password.encode("utf-8"), key=_LOGIN_DIAG_KEY, digest_size=16
    ).hexdigest()

def _login_diag_same_previous(password):
    if (session.get("_user_login_diag_instance") != _LOGIN_DIAG_INSTANCE or
            session.get("_user_login_diag_at", 0) < time.time() - 120 or
            not session.get("_user_login_diag_tag")):
        return "unknown"
    current_tag = _login_diag_input_tag(password)
    return "true" if secrets_compare_digest(
        session["_user_login_diag_tag"], current_tag
    ) else "false"

from hmac import compare_digest as secrets_compare_digest

@app.route("/", methods=["GET", "POST"])
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        pw = request.form.get("password", "").strip()
        # 문자열이 동일한지만 진단합니다. 원문/비밀번호 식별값은 로그에 남기지 않습니다.
        same_as_previous = _login_diag_same_previous(pw)

        if USER_PASSWORD_HASH and check_password_hash(USER_PASSWORD_HASH, pw):
            # 직전 로그인 실패가 있었다면 재시도 성공을 한 번만 기록합니다.
            if session.pop("_user_login_diag_failed", False):
                app.logger.error(
                    "[CARE_LOGIN_DIAG] result=success_after_failure input_length=%d "
                    "hash_configured=%s worker_pid=%d same_input_as_previous=%s",
                    len(pw), bool(USER_PASSWORD_HASH), os.getpid(), same_as_previous
                )
            # 세션의 이전 입력 비교값은 로그인 성공 시 즉시 폐기합니다.
            session.pop("_user_login_diag_tag", None)
            session.pop("_user_login_diag_instance", None)
            session.pop("_user_login_diag_at", None)
            session["logged_in"] = True
            if request.headers.get("X-CareNavi-Async-Login") == "1":
                return jsonify({"ok": True, "redirect": url_for("home")})
            return redirect(url_for("home"))
        else:
            # 입력값/해시/IP/User-Agent는 기록하지 않고 실패 원인만 구분합니다.
            reason = ("hash_not_configured" if not USER_PASSWORD_HASH else
                      "empty_input" if not pw else "password_mismatch")
            app.logger.error(
                "[CARE_LOGIN_DIAG] result=failed reason=%s input_length=%d "
                "hash_configured=%s worker_pid=%d same_input_as_previous=%s",
                reason, len(pw), bool(USER_PASSWORD_HASH), os.getpid(), same_as_previous
            )
            session["_user_login_diag_failed"] = True
            session["_user_login_diag_tag"] = _login_diag_input_tag(pw)
            session["_user_login_diag_instance"] = _LOGIN_DIAG_INSTANCE
            session["_user_login_diag_at"] = time.time()
            if request.headers.get("X-CareNavi-Async-Login") == "1":
                return jsonify({"ok": False, "error": "비밀번호가 올바르지 않습니다."}), 401
            # ✅ alert 대신 페이지 내부 에러 문구로 표시 (주소 안 뜸)
            return render_template_string(LOGIN_HTML, error="비밀번호가 올바르지 않습니다.")

    return render_template_string(LOGIN_HTML, error="", total=0, today=0)

@app.route("/admin", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        pw = request.form.get("password", "").strip()

        if ADMIN_PASSWORD_HASH and check_password_hash(ADMIN_PASSWORD_HASH, pw):
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
  background:#e8ecf4;
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

/* === 버튼 누름 효과 B (디자인 전용) === */
button, input[type="submit"], input[type="button"], a.card, .btn, .home-btn, .home-button, .reset-btn, .home-help-btn, .home-notice-btn, .tip-btn, #fabMain, .fab-item, [class*="-btn"], [class*="-button"] { transition:transform .12s ease, box-shadow .12s ease; }
button:active, input[type="submit"]:active, input[type="button"]:active, .btn:active, .home-btn:active, .home-button:active, .reset-btn:active, .home-help-btn:active, .home-notice-btn:active, .tip-btn:active, #fabMain:active, .fab-item:active, [class*="-btn"]:active, [class*="-button"]:active { transform:scale(0.92) !important; }
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

# =========================
# 점검 모드 안내 페이지
# =========================
MAINTENANCE_HTML = """
<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>서버 점검 중입니다</title>
<style>
body{
  margin:0;
  min-height:100vh;
  min-height:100dvh;
  background:#e8ecf4;
  font-family:'Pretendard',sans-serif;
  display:flex;
  align-items:center;
  justify-content:center;
  padding:20px;
  color:#111827;
}
.box{
  width:100%;
  max-width:460px;
  background:white;
  border-radius:18px;
  padding:32px 24px;
  box-shadow:0 8px 24px rgba(0,0,0,0.08);
  text-align:center;
}
.icon{ font-size:40px; margin-bottom:12px; }
.title{ font-size:20px; font-weight:800; margin-bottom:12px; }
.msg{
  font-size:14px;
  line-height:1.7;
  color:#4b5563;
  word-break:keep-all;
  white-space:pre-line;
  margin-bottom:14px;
}
.resume{
  font-size:13px;
  color:#2563eb;
  font-weight:700;
  background:#eff6ff;
  border-radius:10px;
  padding:10px 12px;
  margin-bottom:16px;
}
.admin-link{
  display:inline-block;
  margin-top:6px;
  font-size:12px;
  color:#9ca3af;
  text-decoration:none;
}
</style>
</head>
<body>
  <div class="box">
    <div class="icon">🛠️</div>
    <div class="title">서버 점검 중입니다</div>
    <div class="msg">{{ message if message else "더 나은 서비스 제공을 위해 시스템 점검을 진행하고 있습니다.\\n잠시 후 다시 이용해 주세요." }}</div>
    {% if resume_at %}
      <div class="resume">예상 재개 시간: {{ resume_at }}</div>
    {% endif %}
    <a href="/admin" class="admin-link">관리자 로그인</a>
  </div>
</body>
</html>
"""

# =========================
# 점검 모드 관리자 패널
# =========================
MAINTENANCE_ADMIN_HTML = """
<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>점검 모드 관리</title>
<style>
*{ box-sizing:border-box; }
body{
  margin:0;
  min-height:100vh;
  font-family:'Pretendard',sans-serif;
  background:#e8ecf4;
  color:#1f2937;
  display:flex;
  justify-content:center;
  padding:40px 16px;
}
.box{
  width:100%;
  max-width:460px;
  background:#ffffff;
  border:1px solid #e5e7eb;
  border-radius:22px;
  padding:28px 24px;
  box-shadow:0 16px 38px rgba(15,23,42,0.12);
}
h1{ font-size:19px; font-weight:800; margin:0 0 6px 0; }
.status{
  display:inline-block;
  font-size:13px;
  font-weight:700;
  padding:4px 10px;
  border-radius:999px;
  margin-bottom:20px;
}
.on{ background:#fee2e2; color:#dc2626; }
.off{ background:#dcfce7; color:#16a34a; }
label{ font-size:13px; font-weight:600; color:#374151; display:block; margin:14px 0 6px; }
textarea, input[type=text]{
  width:100%;
  border:1px solid #d1d5db;
  border-radius:10px;
  padding:10px 12px;
  font-size:14px;
  font-family:inherit;
  resize:vertical;
}
textarea{ min-height:80px; }
.btn-row{ display:flex; gap:8px; margin-top:20px; }
button{
  flex:1;
  height:48px;
  border:none;
  border-radius:12px;
  font-size:15px;
  font-weight:700;
  cursor:pointer;
}
.btn-on{ background:linear-gradient(135deg,#ef4444,#b91c1c); color:#fff; }
.btn-off{ background:linear-gradient(135deg,#334155,#0f172a); color:#fff; }
.back-link{
  display:inline-block;
  margin-top:16px;
  font-size:13px;
  color:#6b7280;
  text-decoration:none;
}
</style>
</head>
<body>
<div class="box">
  <h1>점검 모드 관리</h1>
  <span class="status {{ 'on' if mode.on else 'off' }}">{{ '점검 중 (사용자 접근 차단됨)' if mode.on else '정상 운영 중' }}</span>

  <form method="post" action="/admin/maintenance/on">
    <label>점검 안내 문구 (선택)</label>
    <textarea name="message" placeholder="예: 서버 데이터 정비 작업 중입니다.">{{ mode.message }}</textarea>
    <label>예상 재개 시간 (선택)</label>
    <input type="text" name="resume_at" placeholder="예: 오늘 밤 11시" value="{{ mode.resume_at }}">
    <div class="btn-row">
      <button type="submit" class="btn-on">점검 모드 켜기</button>
    </div>
  </form>

  <form method="post" action="/admin/maintenance/off">
    <div class="btn-row">
      <button type="submit" class="btn-off">점검 모드 끄기</button>
    </div>
  </form>

  <a href="/stats" class="back-link">통계 페이지로 돌아가기</a>
</div>
</body>
</html>
"""

@app.route("/admin/maintenance", methods=["GET"])
def maintenance_panel():
    if not session.get("is_admin"):
        return redirect(url_for("admin_login"))
    maint = _load_maintenance_state()
    return render_template_string(MAINTENANCE_ADMIN_HTML, mode=maint)

@app.route("/admin/maintenance/on", methods=["POST"])
def maintenance_on():
    if not session.get("is_admin"):
        return redirect(url_for("admin_login"))
    message = request.form.get("message", "").strip()
    resume_at = request.form.get("resume_at", "").strip()
    _save_maintenance_state(True, message, resume_at)
    return redirect(url_for("maintenance_panel"))

@app.route("/admin/maintenance/off", methods=["POST"])
def maintenance_off():
    if not session.get("is_admin"):
        return redirect(url_for("admin_login"))
    maint = _load_maintenance_state()
    _save_maintenance_state(False, maint["message"], maint["resume_at"])
    return redirect(url_for("maintenance_panel"))

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
  background:#e8ecf4;
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
  box-shadow:0 10px 26px rgba(15,23,42,0.10);
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
        "광주": "전남광주통합특별시",
        "광주시": "전남광주통합특별시",
        "광주 광역시": "전남광주통합특별시",
        "광주광역시": "전남광주통합특별시",
        "전남": "전남광주통합특별시",
        "전라남도": "전남광주통합특별시",
        "전남광주통합특별시": "전남광주통합특별시",

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


SIDO_PRIORITY_ORDER = ["전남광주통합특별시", "전북특별자치도", "제주특별자치도"]

SIGUNGU_PRIORITY = {
    "전남광주통합특별시": ["광주동구", "광주서구", "광주남구", "광주북구", "광주광산구"],
    "전북특별자치도": ["전주시 덕진구", "전주시 완산구"],
    "제주특별자치도": ["제주시", "서귀포시"],
}


def _order_sigungu(sido_val, values):
    priority = SIGUNGU_PRIORITY.get(sido_val, [])
    ordered = [v for v in priority if v in values]
    ordered += sorted(v for v in values if v not in priority)
    return ordered


def _build_region_options():
    """실제 엑셀의 시도/시군구 컬럼 값에서만 옵션을 생성 (하드코딩·기본값 없음).
    엑셀에 값이 없으면 드롭박스도 비게 되고, 이는 엑셀 데이터 오류를 바로 알아챌 수 있게 하기 위한 의도."""
    sido_col = find_col("시도", "시도명", "광역시도")
    sigungu_col = find_col("시군구")

    if not sido_col:
        return [], {}

    sido_series = df[sido_col].fillna("").astype(str).apply(normalize_sido).str.strip()

    if sigungu_col:
        sigungu_series = df[sigungu_col].fillna("").astype(str).apply(normalize_sigungu).str.strip()
    else:
        sigungu_series = pd.Series([""] * len(df))

    grouped = {}
    for sido_val, sigungu_val in zip(sido_series, sigungu_series):
        if not sido_val:
            continue
        grouped.setdefault(sido_val, set())
        if sigungu_val:
            grouped[sido_val].add(sigungu_val)

    ordered_sido = [s for s in SIDO_PRIORITY_ORDER if s in grouped]
    ordered_sido += sorted(s for s in grouped if s not in SIDO_PRIORITY_ORDER)

    sigungu_map = {
        sido_val: _order_sigungu(sido_val, vals)
        for sido_val, vals in grouped.items()
    }

    return ordered_sido, sigungu_map


SIDO_OPTIONS, SIGUNGU_MAP = _build_region_options()
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

        kst_date = ""
        kst_dt = ""
        if raw:
            try:
                s = raw.replace("Z", "+00:00")
                dt = datetime.datetime.fromisoformat(s)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=datetime.timezone.utc)
                dt = dt.astimezone(ZoneInfo("Asia/Seoul"))
                kst_date = dt.strftime("%Y-%m-%d")
                kst_dt = dt.strftime("%Y-%m-%d %H:%M")
            except Exception:
                kst_date = raw[:10]
                kst_dt = raw[:19].replace("T", " ")

        item["created_date"] = kst_date
        item["created_datetime"] = kst_dt
        item["title"] = item.get("title") or "제목 없음"
        item["content"] = item.get("content") or ""
        item["content_lines"] = item["content"].split("\n")
        item["is_active"] = bool(item.get("is_active", True))
        item["is_pinned"] = bool(item.get("is_pinned", False))
        cleaned.append(item)
    return cleaned

MAIN_CATEGORY_OPTIONS = sorted_unique_values("대분류")
MIDDLE_CATEGORY_OPTIONS = sorted_unique_values("중분류")
MANAGER_OPTIONS = sorted_unique_values("관리주체")

# =========================
# 공단자원 연관검색어 + 돌봄온 팝업 (사례검색 화면 전용)
# - dolbomon_resources.xlsx 를 읽어 사례검색 입력창 아래 연관검색어로 표시
# - 이미지는 static/dolbomon/ 폴더에 저장, 엑셀 '돌봄온파일' 열에 파일명 기입 (여러 장은 쉼표 구분)
# - 엑셀 수정 시 파일 수정시각을 확인해 자동 재로드 (서버 재시작 불필요)
# =========================
DOLBOMON_FILE = "dolbomon_resources.xlsx"
_DOLBOMON_CACHE = {"mtime": None, "items": []}

def load_dolbomon_items():
    try:
        mtime = os.path.getmtime(DOLBOMON_FILE)
    except OSError:
        return []
    if _DOLBOMON_CACHE["mtime"] == mtime:
        return _DOLBOMON_CACHE["items"]
    try:
        ddf = pd.read_excel(DOLBOMON_FILE, sheet_name=0, dtype=str).fillna("")
    except Exception as e:
        app.logger.exception(e)
        return _DOLBOMON_CACHE["items"]
    ddf.columns = [str(c).replace(" ", "").strip() for c in ddf.columns]

    def _split(v):
        return [x.strip() for x in re.split(r"[,，]", str(v or "")) if x.strip()]

    def _expand_images(v):
        """돌봄온파일 열 해석
        - 확장자 생략 시 .png 자동 추가     예) 가족휴가제1 → 가족휴가제1.png
        - 물결(~)로 번호 범위 지정          예) 가족휴가제1~3 → 가족휴가제1.png, 가족휴가제2.png, 가족휴가제3.png
        - 쉼표로 여러 개 나열도 그대로 가능  예) 가족휴가제1, 안내.jpg"""
        out = []
        for tok in _split(v):
            m = re.match(r"^(.*?)(\d+)\s*~\s*(\d+)(.*)$", tok)
            if m and int(m.group(2)) <= int(m.group(3)) and int(m.group(3)) - int(m.group(2)) < 50:
                prefix, a, b, suffix = m.group(1), int(m.group(2)), int(m.group(3)), m.group(4).strip()
                names = [f"{prefix}{n}{suffix}" for n in range(a, b + 1)]
            else:
                names = [tok]
            for nm in names:
                if "." not in nm.rsplit("/", 1)[-1]:
                    nm += ".png"
                out.append(nm)
        return out

    # 자원 엑셀(service_resources.xlsx)에 실제 기관이 있는지 확인용
    # → 기관찾기와 같은 조건(대분류·중분류 일치 + 프로그램명 포함)으로 1건이라도 있으면 True
    def _has_org(main, middle, kw):
        if not kw:
            return False
        try:
            sub = df
            if main and "대분류" in sub.columns:
                sub = sub[sub["대분류"].fillna("").astype(str).str.strip() == main]
            if middle and "중분류" in sub.columns:
                sub = sub[sub["중분류"].fillna("").astype(str).str.strip() == middle]
            if "관리주체" in sub.columns:  # 기관찾기로 넘길 때 관리주체=공단으로 넘기므로 같은 조건으로 확인
                sub = sub[sub["관리주체"].fillna("").astype(str).str.strip() == "공단"]
            col = "프로그램명(사업명)"
            if col not in sub.columns:
                return False
            return bool(sub[col].fillna("").astype(str)
                        .str.contains(kw, case=False, na=False, regex=False).any())
        except Exception:
            return True  # 확인 실패 시 기존처럼 버튼 표시

    items = []
    for _, r in ddf.iterrows():
        name = str(r.get("표시명", "")).strip()
        if not name:
            continue
        if str(r.get("사용", "Y")).strip().upper() == "N":
            continue
        items.append({
            "name": name,
            "keywords": _split(r.get("매칭어", "")),
            "main": str(r.get("대분류", "")).strip(),
            "middle": str(r.get("중분류", "")).strip(),
            # 기관찾기 '프로그램' 칸에 넣을 값 (예전 열 이름 '기관검색어'도 인식)
            "kw": str(r.get("프로그램명", "") or r.get("기관검색어", "")).strip(),
            "images": _expand_images(r.get("돌봄온파일", "")),
        })
        items[-1]["has_org"] = _has_org(items[-1]["main"], items[-1]["middle"], items[-1]["kw"])
    _DOLBOMON_CACHE["mtime"] = mtime
    _DOLBOMON_CACHE["items"] = items
    return items

@app.context_processor
def inject_dolbomon_items():
    # 알약 확인 팝업: 홈(/home)·지자체 조사서식(/survey)
    if request.path in ("/home", "/survey"):
        return {"pill_html": PILL_HTML}
    # 사례검색(/desc)·기관찾기(/combo) 화면에서만 사용
    if request.path not in ("/desc", "/combo"):
        return {}
    ctx = {"dolbomon_items": load_dolbomon_items(), "dbo_viewer": DBO_VIEWER_HTML}
    if request.path == "/desc":
        ctx["cam_return"] = CAM_RETURN_HTML
    return ctx

# 돌봄온 이미지 팝업 + 통합돌봄ON 선택창 (사례검색·기관찾기 공용)
# - 템플릿에서 {{ dbo_viewer|safe }} 로 삽입. 자원 목록은 각 페이지에서 dolbomon_items 로 전달
DBO_VIEWER_HTML = """
<style>
.dbo-modal, .dbo-picker{ display:none; position:fixed; inset:0; background:rgba(15,23,42,0.6); align-items:center; justify-content:center; padding:16px; }
.dbo-picker{ z-index:100000; }
.dbo-modal{ z-index:100001; }
.dbo-modal.show, .dbo-picker.show{ display:flex; }
.dbo-box{ width:100%; max-width:560px; max-height:90vh; background:#fff; border-radius:16px; display:flex; flex-direction:column; overflow:hidden; box-shadow:0 20px 50px rgba(0,0,0,0.25); font-family:inherit; }
.dbo-head{ display:flex; align-items:center; gap:8px; padding:12px 14px; border-bottom:1px solid #e5e7eb; }
.dbo-title{ flex:1; min-width:0; font-size:15px; font-weight:800; color:#111827; word-break:keep-all; text-align:left; }
.dbo-search-btn{ flex:none; display:inline-flex; align-items:center; justify-content:center; height:32px; padding:0 12px; border-radius:999px; background:#93c5fd; color:#1e40af; font-size:13px; font-weight:700; text-decoration:none; white-space:nowrap; box-shadow:0 2px 6px rgba(37,99,235,0.3); }
.dbo-search-btn:hover{ background:#7fb6fb; }
.dbo-search-btn.disabled{ background:#e5e7eb; color:#9ca3af; box-shadow:none; cursor:default; pointer-events:none; animation:none; }
/* 기관검색 강조: 손가락이 좌우로 움직이며 버튼을 가리키고, 버튼은 은은하게 빛남 */
.dbo-hand{ flex:none; font-size:18px; line-height:1; margin-right:-2px; animation:dboHand 1s ease-in-out infinite; }
@keyframes dboHand{ 0%,100%{ transform:translateX(-4px); } 50%{ transform:translateX(3px); } }
.dbo-search-btn:not(.disabled){ animation:dboGlow 1.6s ease-in-out infinite; }
@keyframes dboGlow{ 0%,100%{ box-shadow:0 2px 6px rgba(37,99,235,0.3), 0 0 0 0 rgba(59,130,246,0.45); } 50%{ box-shadow:0 2px 6px rgba(37,99,235,0.3), 0 0 0 6px rgba(59,130,246,0); } }
@media (prefers-reduced-motion: reduce){ .dbo-hand, .dbo-search-btn{ animation:none !important; } }
.dbo-close{ flex:none; width:34px !important; height:34px !important; margin:0 !important; padding:0 !important; border:none !important; border-radius:999px !important; background:#f3f4f6 !important; color:#374151 !important; font-size:20px !important; line-height:1 !important; box-shadow:none !important; cursor:pointer; }
.dbo-body{ flex:1; overflow:auto; background:#f9fafb; padding:8px; }
.dbo-body img{ display:block; width:100%; height:auto; border-radius:8px; }
.dbo-empty{ padding:40px 10px; text-align:center; color:#9ca3af; font-size:13px; }
.dbo-nav{ display:none; align-items:center; justify-content:space-between; gap:10px; padding:10px 14px; border-top:1px solid #e5e7eb; }
.dbo-nav.show{ display:flex; }
.dbo-nav-btn{ width:auto !important; min-width:72px; height:36px !important; margin:0 !important; padding:0 16px !important; border:none !important; border-radius:10px !important; background:#2563eb !important; color:#fff !important; font-size:14px !important; font-weight:700 !important; box-shadow:none !important; cursor:pointer; }
.dbo-nav-btn:disabled{ background:#cbd5e1 !important; cursor:not-allowed; }
.dbo-page{ font-size:13px; font-weight:700; color:#6b7280; }
.dbo-pick-body{ flex:1; overflow:auto; padding:14px; }
.dbo-pick-label{ font-size:12px; font-weight:800; color:#6b7280; margin:4px 0 8px; }
.dbo-chips{ display:flex; flex-wrap:wrap; gap:6px; margin-bottom:14px; }
.dbo-chips:empty{ display:none; }
.dbo-picker .dbo-head{ padding:14px 16px; }
.dbo-picker .dbo-pick-body{ padding:16px 16px 2px; }
.dbo-picker .dbo-foot{ padding:8px 16px; }
.dbo-chip{ padding:7px 13px; border:1px solid #d1d5db; border-radius:999px; background:#f9fafb; color:#374151; font-size:13px; font-weight:600; cursor:pointer; user-select:none; }
.dbo-chip.active{ background:#2563eb; border-color:#2563eb; color:#fff; }
.dbo-item{ display:flex; align-items:center; gap:6px; padding:11px 10px; border-bottom:1px solid #f1f5f9; font-size:14px; font-weight:700; color:#1e3a8a; cursor:pointer; word-break:keep-all; }
.dbo-item:hover{ background:#eef2ff; }
.dbo-sub{ margin-top:3px; font-size:12px; font-weight:500; color:#6b7280; line-height:1.4; word-break:keep-all; }
.dbo-foot{ flex:none; padding:8px 14px; border-top:1px solid #f1f5f9; text-align:right; font-size:11px; color:#9ca3af; }
.dbo-foot a{ color:#6b7280; text-decoration:none; }
.dbo-foot a:hover{ color:#2563eb; text-decoration:underline; }
.dbo-search-input{ display:block; width:100%; box-sizing:border-box; height:42px; margin:0 0 14px; padding:0 12px; border:1px solid #d1d5db; border-radius:10px; font-size:14px; font-family:inherit; color:#111827; background:#fff; outline:none; }
.dbo-search-input:focus{ border-color:#2563eb; box-shadow:0 0 0 3px rgba(37,99,235,0.10); }
/* 모바일: 팝업 전체를 조금 작게 + 주소창 높이를 뺀 실제 화면(dvh) 기준으로 맞춤 */
@media (max-width:767px){
  .dbo-modal{ padding:12px; }
  .dbo-modal .dbo-box{ width:92vw; max-width:440px; max-height:82vh; max-height:82dvh; border-radius:14px; }
  .dbo-modal .dbo-head{ padding:8px 10px; gap:6px; }
  .dbo-modal .dbo-title{ font-size:14px; }
  .dbo-modal .dbo-search-btn{ height:28px; padding:0 10px; font-size:12px; }
  .dbo-modal .dbo-close{ width:28px !important; height:28px !important; font-size:17px !important; }
  .dbo-modal .dbo-body{ padding:6px; }
  .dbo-modal .dbo-nav{ padding:6px 10px; }
  .dbo-modal .dbo-nav-btn{ min-width:64px; height:32px !important; padding:0 12px !important; font-size:13px !important; }
  .dbo-modal .dbo-page{ font-size:12px; }
  .dbo-modal .dbo-foot{ padding:4px 10px; font-size:10.5px; }
}
/* PC: 이미지 한 장이 스크롤 없이 화면 안에 다 보이도록 */
@media (min-width:768px){
  /* 팝업 폭을 이미지 폭에 맞춤 (세로로 긴 이미지일 때 양옆 여백 제거) */
  .dbo-modal{ padding:8px; }
  .dbo-modal .dbo-box{ width:auto; min-width:380px; max-width:94vw; max-height:97vh; }
  .dbo-modal .dbo-head{ padding:8px 12px; }
  .dbo-modal .dbo-nav{ padding:6px 12px; }
  .dbo-modal .dbo-nav-btn{ height:32px !important; }
  .dbo-modal .dbo-foot{ padding:4px 12px; }
  .dbo-body{ display:flex; align-items:center; justify-content:center; overflow:auto; min-height:0; padding:4px; }
  /* 97vh에서 상단(제목)·하단(이전/다음, 출처) 높이를 뺀 만큼만 이미지 높이 허용 */
  .dbo-body img{ width:auto; max-width:100%; max-height:calc(97vh - 160px); object-fit:contain; cursor:zoom-in; }
  /* 이미지 클릭 시 크게 보기 (PC 전용): 폭을 넓히고 세로 스크롤 */
  .dbo-modal.zoom .dbo-box{ width:min(1000px, 94vw); }
  .dbo-modal.zoom .dbo-body{ display:block; }
  .dbo-modal.zoom .dbo-body img{ width:100%; max-height:none; cursor:zoom-out; }
}
</style>

<div id="dboModal" class="dbo-modal">
  <div class="dbo-box">
    <div class="dbo-head">
      <div class="dbo-title" id="dboTitle"></div>
      <span class="dbo-hand" id="dboHand" aria-hidden="true">👉</span>
      <a href="#" class="dbo-search-btn" id="dboSearchBtn">기관검색</a>
      <button type="button" class="dbo-close" onclick="closeDbo()" aria-label="닫기">×</button>
    </div>
    <div class="dbo-body" id="dboBody"></div>
    <div class="dbo-nav" id="dboNav">
      <button type="button" class="dbo-nav-btn" id="dboPrev">◀ 이전</button>
      <span class="dbo-page" id="dboPage"></span>
      <button type="button" class="dbo-nav-btn" id="dboNext">다음 ▶</button>
    </div>
    <div class="dbo-foot">자료 출처: <a href="https://care1234.my.canva.site/2026v1" target="_blank" rel="noopener noreferrer">통합돌봄ON ↗</a></div>
  </div>
</div>

<script>
(function(){
  var modal = document.getElementById("dboModal");
  var body = document.getElementById("dboBody");
  var nav = document.getElementById("dboNav");
  var page = document.getElementById("dboPage");
  var prevBtn = document.getElementById("dboPrev");
  var nextBtn = document.getElementById("dboNext");
  if(!modal) return;
  var cur = null, idx = 0;

  /* 현재 화면에서 선택된 지역 (사례검색·기관찾기 모두 select name=sido/sigungu) */
  function regionVal(name){
    var el = document.querySelector('select[name="' + name + '"]');
    return el ? el.value : "";
  }

  function syncBodyScroll(){
    var anyOpen = document.querySelector(".dbo-modal.show, .dbo-picker.show");
    document.body.style.overflow = anyOpen ? "hidden" : "";
  }
  window.dboSyncScroll = syncBodyScroll;

  function showImg(){
    var imgs = (cur && cur.images) || [];
    body.innerHTML = "";
    if(!imgs.length){
      body.innerHTML = '<div class="dbo-empty">등록된 이미지가 없습니다.</div>';
    }else{
      var im = document.createElement("img");
      im.alt = cur.name + " " + (idx + 1);
      im.onerror = function(){ body.innerHTML = '<div class="dbo-empty">이미지를 불러올 수 없습니다.</div>'; };
      im.src = "/static/dolbomon/" + encodeURIComponent(imgs[idx]);
      /* PC: 클릭하면 크게 보기 ↔ 한 화면에 맞추기 (모바일은 두 손가락 확대 사용) */
      im.addEventListener("click", function(e){
        if(!window.matchMedia("(min-width:768px)").matches) return;
        var rect = im.getBoundingClientRect();
        var ratio = rect.height ? (e.clientY - rect.top) / rect.height : 0;  /* 클릭한 세로 위치 (0~1) */
        var zoomIn = !modal.classList.contains("zoom");
        modal.classList.toggle("zoom");
        if(!zoomIn){ body.scrollTop = 0; return; }
        /* 확대 후 클릭했던 지점이 화면 가운데 오도록 스크롤 */
        requestAnimationFrame(function(){
          var imgTop = im.getBoundingClientRect().top - body.getBoundingClientRect().top + body.scrollTop;
          body.scrollTop = Math.max(0, imgTop + ratio * im.offsetHeight - body.clientHeight / 2);
        });
      });
      if(window.matchMedia("(min-width:768px)").matches) im.title = "클릭하면 크게 / 작게 보기";
      body.appendChild(im);
    }
    body.scrollTop = 0;
    if(imgs.length > 1){
      nav.classList.add("show");
      page.textContent = (idx + 1) + " / " + imgs.length;
      prevBtn.disabled = (idx === 0);
      nextBtn.disabled = (idx === imgs.length - 1);
    }else{
      nav.classList.remove("show");
    }
  }

  function step(d){
    var imgs = (cur && cur.images) || [];
    var n = idx + d;
    if(n < 0 || n >= imgs.length) return;
    idx = n;
    showImg();
  }

  /* 기관검색: 검색은 실행하지 않고 기관찾기 화면에 값만 채워서 이동 */
  window.openDbo = function(it){
    try{ if(navigator.sendBeacon){ navigator.sendBeacon("/pv/dbo"); } else { fetch("/pv/dbo", {method:"POST"}); } }catch(e){}
    cur = it; idx = 0;
    modal.classList.remove("zoom");
    document.getElementById("dboTitle").textContent = it.name;
    var params = new URLSearchParams({
      sido: regionVal("sido"),
      sigungu: regionVal("sigungu"),
      main_category: it.main || "",
      middle_category: it.middle || "",
      manager: "공단",   /* 돌봄온 자원은 모두 공단자원 */
      program_kw: it.kw || ""
    });
    var sBtn = document.getElementById("dboSearchBtn");
    if(it.has_org === false){
      /* 자원 엑셀에 등록된 기관이 없는 사업: 버튼 비활성화 */
      sBtn.removeAttribute("href");
      sBtn.classList.add("disabled");
      sBtn.textContent = "등록된 기관 없음";
      document.getElementById("dboHand").style.display = "none";
    }else{
      document.getElementById("dboHand").style.display = "";
      sBtn.href = "/combo?" + params.toString();
      sBtn.classList.remove("disabled");
      sBtn.textContent = "기관검색";
    }
    showImg();
    modal.classList.add("show");
    syncBodyScroll();
  };

  window.closeDbo = function(){
    modal.classList.remove("show");
    syncBodyScroll();
  };

  prevBtn.addEventListener("click", function(){ step(-1); });
  nextBtn.addEventListener("click", function(){ step(1); });
  modal.addEventListener("click", function(e){ if(e.target === modal) window.closeDbo(); });
  document.addEventListener("keydown", function(e){
    if(!modal.classList.contains("show")) return;
    if(e.key === "Escape") window.closeDbo();
  });
  /* 페이지 넘김은 '이전 / 다음' 버튼으로만 (스와이프·방향키로 넘기지 않음. 위아래 밀기는 스크롤 전용) */
})();
</script>
"""


# =========================
# 알약 확인 (식약처 의약품 낱알식별 정보 대조)
# - pills.csv : 식약처 낱알식별 API 전체 목록에서 필요한 열만 추린 파일 (app.py 옆에 둠)
# - 사진 → GPT는 약 이름을 맞히지 않고 '각인·색·모양'만 읽음 → 서버가 pills.csv 와 점수 비교
# - 결과는 참고용 후보. 사진은 저장하지 않음
# =========================
PILL_FILE = "pills.csv"
_PILL_CACHE = {"mtime": None, "rows": []}
PILL_DEMENTIA_KW = ["도네페질", "리바스티그민", "갈란타민", "메만틴", "아리셉트", "엑셀론", "레미닐", "에빅사"]
PILL_COLORS = ["하양", "노랑", "주황", "분홍", "빨강", "갈색", "연두", "초록", "청록", "파랑", "남색", "자주", "보라", "회색", "검정", "투명"]
PILL_SHAPES = ["원형", "타원형", "장방형", "반원형", "삼각형", "사각형", "마름모형", "오각형", "육각형", "팔각형", "기타"]
PILL_FORMS = ["정제", "경질캡슐", "연질캡슐"]


def _pill_form_kind(form_name):
    """식약처 제형명(FORM_CODE_NAME) → 정제 / 경질캡슐 / 연질캡슐 (그 외는 빈 값)"""
    f = str(form_name or "")
    if "연질" in f:
        return "연질캡슐"
    if "캡슐" in f:
        return "경질캡슐"
    if "정" in f:
        return "정제"
    return ""


def _pill_norm(s):
    """각인 비교용 정규화: 대문자, '분할선'·'마크' 등 설명어 제거, 글자·숫자만 남김"""
    s = str(s or "").upper()
    for w in ("분할선", "마크", "각인", "없음"):
        s = s.replace(w, "")
    return re.sub(r"[^0-9A-Z가-힣]", "", s)


def load_pills():
    try:
        mtime = os.path.getmtime(PILL_FILE)
    except OSError:
        return []
    if _PILL_CACHE["mtime"] == mtime:
        return _PILL_CACHE["rows"]
    try:
        pdf = pd.read_csv(PILL_FILE, dtype=str).fillna("")
    except Exception as e:
        app.logger.exception(e)
        return _PILL_CACHE["rows"]
    rows = []
    for r in pdf.to_dict("records"):
        name = r.get("ITEM_NAME", "")
        prints = [p for p in (_pill_norm(r.get("PRINT_FRONT")), _pill_norm(r.get("PRINT_BACK"))) if p]
        colors = set()
        for c in (r.get("COLOR_CLASS1", ""), r.get("COLOR_CLASS2", "")):
            for x in str(c).split(","):
                x = x.strip()
                if x and x != "옅은":
                    colors.add(x)
        rows.append({
            "seq": r.get("ITEM_SEQ", ""),
            "name": name,
            "company": r.get("ENTP_NAME", ""),
            "cls": r.get("CLASS_NAME", ""),
            "etc_otc": r.get("ETC_OTC_NAME", ""),
            "form": r.get("FORM_CODE_NAME", ""),
            "shape": r.get("DRUG_SHAPE", ""),
            "color": r.get("COLOR_CLASS1", ""),
            "print_front": r.get("PRINT_FRONT", ""),
            "print_back": r.get("PRINT_BACK", ""),
            "image": r.get("ITEM_IMAGE", ""),
            "_prints": prints,
            "_colors": colors,
            "_capsule": "캡슐" in r.get("FORM_CODE_NAME", ""),
            "_kind": _pill_form_kind(r.get("FORM_CODE_NAME", "")),
            "dementia": any(k in name for k in PILL_DEMENTIA_KW),
        })
    _PILL_CACHE["mtime"] = mtime
    _PILL_CACHE["rows"] = rows
    return rows


# 사진에서 자주 헷갈리는 글자 → 같은 대표 글자로 바꿔 비교 (정확히 같은 글자보다는 낮게 인정)
_PILL_CONFUSE = str.maketrans({"O": "0", "Q": "0", "I": "1", "L": "1", "B": "8",
                               "S": "5", "Z": "2", "T": "7", "G": "6"})


def _pill_canon(s):
    return s.translate(_PILL_CONFUSE)


def _pill_imprint_score(photo_prints, pill_prints):
    """사진에서 읽은 각인들과 알약 각인(앞/뒤)의 일치도 0~1
    - 정확히 같음 1.0 / 헷갈리는 글자만 다름(0↔O, 1↔I·L, 8↔B, 5↔S, 2↔Z, 7↔T, 6↔G) 0.8
    - 한쪽이 다른 쪽에 포함 0.7 / 그 외 비슷한 정도에 따라 최대 0.6"""
    import difflib
    if not photo_prints or not pill_prints:
        return 0.0
    total = 0.0
    for p in photo_prints:
        best = 0.0
        for d in pill_prints:
            if p == d:
                best = 1.0
                break
            cp, cd = _pill_canon(p), _pill_canon(d)
            if cp == cd:
                best = max(best, 0.8)
                continue
            if len(p) >= 2 and len(d) >= 2 and (p in d or d in p):
                best = max(best, 0.7)
                continue
            if len(cp) >= 2 and len(cd) >= 2 and (cp in cd or cd in cp):
                best = max(best, 0.65)
                continue
            sm = difflib.SequenceMatcher(None, cp, cd)
            if sm.real_quick_ratio() >= 0.6 and sm.quick_ratio() >= 0.6:
                r = sm.ratio()
                if r >= 0.6:
                    best = max(best, r * 0.6)
        total += best
    score = total / len(photo_prints)
    # 사진의 앞·뒤 각인 수와 알약의 각인 수가 같으면 약간 가산
    if len(photo_prints) == len(pill_prints) and score >= 0.7:
        score = min(1.0, score + 0.05)
    return score


# 식약처 약 분류명(CLASS_NAME) → 쉬운 이름, 돌봄 관점에서 검토할 신호
# - 의학적 판단이 아니라 '검토해 볼 돌봄'을 안내하기 위한 참고용 표. 분류명이 바뀌면 여기만 고치면 됨
PILL_CARE_MAP = {
    "최면진정제": ("수면제", ["낙상 주의"]),
    "정신신경용제": ("신경정신과 약", ["낙상 주의"]),
    "항전간제": ("뇌전증약", ["낙상 주의"]),
    "골격근이완제": ("근육이완제", ["낙상 주의"]),
    "항히스타민제": ("알레르기약", ["낙상 주의"]),
    "혈압강하제": ("혈압약", ["어지럼 주의"]),
    "이뇨제": ("이뇨제", ["야간 화장실 낙상 주의"]),
    "당뇨병용제": ("당뇨약", ["식사·영양 관리"]),
    "혈액응고저지제": ("항응고제", ["넘어짐 시 출혈 주의"]),
    "동맥경화용제": ("고지혈증약", []),
    "부정맥용제": ("심장약", []),
    "관상혈관확장제": ("심장약", []),
    "해열.진통.소염제": ("진통소염제", []),
    "소화성궤양용제": ("위장약", []),
    "진해거담제": ("기침·가래약", []),
}


def _pill_care(cls, dementia=False):
    """약 1개의 쉬운 이름과 돌봄 신호. 치매약은 이름으로 판별(분류명이 '기타의 중추신경용약' 등으로 흩어져 있음)"""
    if dementia:
        return {"kind": "치매약", "signals": ["인지 지원"]}
    cls = str(cls or "").strip()
    for key, (kind, signals) in PILL_CARE_MAP.items():
        if key in cls:
            return {"kind": kind, "signals": list(signals)}
    kind = re.sub(r"^\[\d+\]\s*", "", cls).replace("기타의 ", "").strip() or "기타 약"
    return {"kind": kind, "signals": []}


def search_pills(imprints, color="", shape="", capsule=None, limit=3, form=""):
    """각인(필수) + 색·모양(보조)으로 후보를 점수순으로 반환
    form: 사용자가 고른 제형(정제/경질캡슐/연질캡슐). 고르면 해당 제형만, 빈 값이면 전체"""
    photo_prints = [p for p in (_pill_norm(x) for x in (imprints or [])) if p]
    if not photo_prints:
        return []
    results = []
    for row in load_pills():
        if form and row["_kind"] != form:
            continue
        s_imp = _pill_imprint_score(photo_prints, row["_prints"])
        if s_imp <= 0:
            continue
        score = s_imp * 70
        if color and color in row["_colors"]:
            score += 15
        if shape and shape == row["shape"]:
            score += 10
        if capsule is not None and capsule == row["_capsule"]:
            score += 5
        if score >= 40:
            results.append((score, row))
    results.sort(key=lambda x: -x[0])
    # 1등보다 확연히 낮은 후보(20점 이상 차이)는 혼동을 줄이기 위해 제외
    if results:
        cut = max(40, results[0][0] - 20)
        results = [x for x in results if x[0] >= cut]
    # 확신도: 입력한 단서(각인·색·모양·제형)로 받을 수 있는 최고점 대비 비율
    #   거의 확실(90%↑, 단 1등이 2등보다 3점 이상 앞설 때만) / 유력(70%↑) / 참고
    max_score = 70 + (15 if color else 0) + (10 if shape else 0) + (5 if capsule is not None else 0)
    top = results[:limit]
    lead_ok = len(top) == 1 or (len(top) > 1 and top[0][0] - top[1][0] >= 3)
    out = []
    for score, row in top:
        item = {k: v for k, v in row.items() if not k.startswith("_")}
        item["score"] = round(score)
        ratio = score / max_score
        if ratio >= 0.9 and lead_ok and row is top[0][1]:
            item["conf"], item["conf_label"] = "high", "거의 확실"
        elif ratio >= 0.7:
            item["conf"], item["conf_label"] = "mid", "유력"
        else:
            item["conf"], item["conf_label"] = "low", "참고"
        item["detail_url"] = "https://nedrug.mfds.go.kr/pbp/CCBBB01/getItemDetail?itemSeq=" + row["seq"]
        item["care"] = _pill_care(row["cls"], row["dementia"])
        out.append(item)
    return out


PILL_MAX = 10          # 한 번에 처리하는 최대 알약 수
PILL_RECOMMEND = 5     # 권장 알약 수 (넘으면 안내)


def _pill_features_from_images(images):
    """GPT로 알약 사진의 '보이는 특징'만 읽음 (약 이름 추정 금지).
    images: [(label, mimetype, bytes)]  label = "front" | "back"
    한 사진에 알약이 여러 개일 수 있음 → 알약마다 각인·색·모양·위치(x, y)를 따로 읽음"""
    import base64
    client = OpenAI()
    labels = [lb for lb, _, _ in images]
    if labels == ["front", "back"]:
        desc = ("첫 번째 사진은 알약들의 앞면, 두 번째 사진은 같은 알약들을 놓인 자리 그대로 하나씩 뒤집어 찍은 뒷면이다.\n")
    else:
        desc = "사진은 알약들을 한쪽 면만 찍은 것이다.\n"
    content = [{"type": "input_text", "text": (
        "사진 속 알약의 겉모습만 읽어서 JSON으로만 답해. 약 이름은 절대 추측하지 마.\n"
        + desc +
        f"사진마다 보이는 알약을 하나씩 모두 적어 (최대 {PILL_MAX}개).\n"
        "알약 1개는 반드시 1개로만 적어. 한 알약의 글자가 분할선 등으로 나뉘어 있어도 별도 알약으로 나누지 말고, 같은 알약을 두 번 적지 마.\n"
        "알약마다 imprint(알약에 새겨지거나 인쇄된 글자·숫자를 보이는 그대로, 로고나 그림이면 빈 문자열, "
        "분할선으로 나뉜 글자는 이어서), color, shape, form, 그리고 사진 안에서 알약 중심의 위치 x, y"
        "(사진 너비·높이 대비 비율 0~1, 왼쪽 위가 0)를 적어.\n"
        f"color는 다음 중 하나: {', '.join(PILL_COLORS)}\n"
        f"shape는 다음 중 하나: {', '.join(PILL_SHAPES)}\n"
        "form은 '정제', '캡슐', '모름' 중 하나.\n"
        "photos 배열은 사진 순서대로 하나씩, 각 사진의 pills 배열에 알약을 넣어.\n"
        '형식: {"photos":[{"pills":[{"imprint":"","color":"","shape":"","form":"정제","x":0.5,"y":0.5}]}]}'
    )}]
    for _, mime, data in images:
        b64 = base64.b64encode(data).decode("utf-8")
        content.append({"type": "input_image", "image_url": f"data:{mime};base64,{b64}", "detail": "high"})

    res = client.responses.create(model="gpt-4.1-mini", input=[{"role": "user", "content": content}], temperature=0)
    usage = getattr(res, "usage", None)
    if usage:
        add_token_usage(getattr(usage, "input_tokens", 0), getattr(usage, "output_tokens", 0))
    text = res.output_text or ""
    try:
        data = json.loads(text)
    except Exception:
        m = re.search(r"\{.*\}", text, re.DOTALL)
        data = json.loads(m.group()) if m else {"photos": []}

    def _num(v):
        try:
            return min(1.0, max(0.0, float(v)))
        except Exception:
            return None

    out = {}
    photos = data.get("photos") or []
    for i, lb in enumerate(labels):
        pills = (photos[i].get("pills") if i < len(photos) and isinstance(photos[i], dict) else None) or []
        clean = []
        for p in pills[:PILL_MAX]:
            if not isinstance(p, dict):
                continue
            form = p.get("form", "모름")
            clean.append({
                "imprint": str(p.get("imprint", "") or "").strip(),
                "color": p.get("color") if p.get("color") in PILL_COLORS else "",
                "shape": p.get("shape") if p.get("shape") in PILL_SHAPES else "",
                "capsule": True if form == "캡슐" else (False if form == "정제" else None),
                "x": _num(p.get("x")),
                "y": _num(p.get("y")),
            })
        out[lb] = clean
    return out


def _pill_norm_positions(pills):
    """알약 위치를 '알약들이 놓인 범위' 기준으로 0~1 정규화
    (앞·뒷면을 찍을 때 거리·위치가 조금 달라도 배치 모양으로 비교되도록)"""
    pts = [(p["x"], p["y"]) for p in pills]
    if any(x is None or y is None for x, y in pts):
        return None
    out = []
    xs, ys = [x for x, _ in pts], [y for _, y in pts]
    for x, y in pts:
        rx, ry = max(xs) - min(xs), max(ys) - min(ys)
        nx = (x - min(xs)) / rx if rx > 0.05 else 0.5      # 한 줄로 놓였으면 그 방향은 비교 안 함
        ny = (y - min(ys)) / ry if ry > 0.05 else 0.5
        out.append((nx, ny))
    return out


def _pill_pair_by_position(front, back):
    """같은 자리에서 뒤집었으므로 '배치상 같은 위치'끼리 앞·뒷면 짝을 맞춤.
    반환: [(앞면 index 또는 None, 뒷면 index 또는 None), ...]  앞면 순서 유지"""
    from itertools import permutations
    fp, bp = _pill_norm_positions(front), _pill_norm_positions(back)
    pairs = []
    if fp is None or bp is None or not front or not back:
        # 위치 정보가 없으면 AI가 적은 순서대로
        n = max(len(front), len(back))
        return [(i if i < len(front) else None, i if i < len(back) else None) for i in range(n)]

    def d(i, j):
        return (fp[i][0] - bp[j][0]) ** 2 + (fp[i][1] - bp[j][1]) ** 2

    nf, nb = len(front), len(back)
    best = None
    if min(nf, nb) <= 8 and max(nf, nb) <= 8:
        # 가능한 짝을 모두 비교해 전체 거리가 가장 작은 조합 (최대 8개면 충분히 빠름)
        if nf <= nb:
            for perm in permutations(range(nb), nf):
                cost = sum(d(i, perm[i]) for i in range(nf))
                if best is None or cost < best[0]:
                    best = (cost, {i: perm[i] for i in range(nf)})
        else:
            for perm in permutations(range(nf), nb):
                cost = sum(d(perm[j], j) for j in range(nb))
                if best is None or cost < best[0]:
                    best = (cost, {perm[j]: j for j in range(nb)})
        match = best[1]
    else:
        # 9개 이상: 가까운 것부터 차례로 짝
        cand = sorted((d(i, j), i, j) for i in range(nf) for j in range(nb))
        match, used_f, used_b = {}, set(), set()
        for _, i, j in cand:
            if i not in used_f and j not in used_b:
                match[i] = j; used_f.add(i); used_b.add(j)
    for i in range(nf):
        pairs.append((i, match.get(i)))
    for j in range(nb):
        if j not in match.values():
            pairs.append((None, j))
    return pairs


def _pill_group(no, imprints, color, shape, capsule=None):
    """알약 1개 결과 묶음 만들기"""
    # AI가 '정제'로 읽은 경우만 제형을 미리 채움 (캡슐은 경질/연질 구분이 어려워 '전체'로 둠)
    feats = {"imprint": " / ".join(imprints), "color": color, "shape": shape,
             "form": "정제" if capsule is False else ""}
    if not imprints:
        return {"no": no, "features": feats, "candidates": [],
                "message": "각인(글자)을 읽지 못했습니다. 이 알약은 글자가 보이도록 가까이 따로 찍거나, 위에 각인을 직접 입력해 주세요."}
    cands = search_pills(imprints, color, shape, capsule)
    return {"no": no, "features": feats, "candidates": cands,
            "message": "" if cands else "일치하는 알약을 찾지 못했습니다. 인식된 각인을 직접 고쳐서 다시 찾아보세요."}


def _pill_build_groups(front, back):
    """앞·뒷면을 배치 위치로 짝지어 알약마다 결과 묶음 만들기 (1알이면 기존과 동일)"""
    if not front and back:
        front, back = back, []
    groups = []
    for fi, bi in _pill_pair_by_position(front, back):
        if fi is None:
            continue   # 뒷면에서만 보인 것(바닥 무늬 오인식 등)은 별도 알약으로 만들지 않음
        sides = ([front[fi]] if fi is not None else []) + ([back[bi]] if bi is not None else [])
        imprints = [s["imprint"] for s in sides if s["imprint"]]
        color = next((s["color"] for s in sides if s["color"]), "")
        shape = next((s["shape"] for s in sides if s["shape"]), "")
        capsule = next((s["capsule"] for s in sides if s["capsule"] is not None), None)
        groups.append(_pill_group(len(groups) + 1, imprints, color, shape, capsule))
    return groups


def _pill_locate_boxes(images):
    """알약이 사진 어디에 있는지만 대략 찾음 (저해상도·저비용). 결과는 사진 대비 비율 [왼, 위, 오른, 아래] 또는 None
    → 휴대폰에서 원본 해상도로 알약 주변만 잘라 다시 보내 각인 판독 정확도를 높임"""
    import base64
    client = OpenAI()
    content = [{"type": "input_text", "text": (
        "각 사진에서 알약이 있는 영역을 찾아 JSON으로만 답해. 알약이 여러 개면 모두 포함하는 하나의 영역으로.\n"
        "좌표는 사진 전체 너비·높이 대비 비율(0~1)로 [왼쪽, 위, 오른쪽, 아래]. 알약이 없으면 null.\n"
        '형식: {"boxes":[[0.1,0.2,0.3,0.4]]}  (사진 순서대로)'
    )}]
    for mime, data in images:
        b64 = base64.b64encode(data).decode("utf-8")
        content.append({"type": "input_image", "image_url": f"data:{mime};base64,{b64}", "detail": "low"})
    res = client.responses.create(model="gpt-4.1-mini", input=[{"role": "user", "content": content}], temperature=0)
    usage = getattr(res, "usage", None)
    if usage:
        add_token_usage(getattr(usage, "input_tokens", 0), getattr(usage, "output_tokens", 0))
    text = res.output_text or ""
    m = re.search(r"\{.*\}", text, re.DOTALL)
    data = json.loads(m.group()) if m else {}
    out = []
    for b in (data.get("boxes") or [])[:len(images)]:
        try:
            x0, y0, x1, y1 = [min(1.0, max(0.0, float(v))) for v in b]
            out.append([x0, y0, x1, y1] if x1 > x0 and y1 > y0 else None)
        except Exception:
            out.append(None)
    while len(out) < len(images):
        out.append(None)
    return out


@app.route("/pill/locate", methods=["POST"])
@login_required
def pill_locate():
    """알약 위치 찾기 (실패해도 됨: 휴대폰은 원래 사진 그대로 보냄)"""
    if not os.getenv("OPENAI_API_KEY"):
        return jsonify({"ok": False})
    images = []
    for key in ("front", "back"):
        f = request.files.get(key)
        if not f:
            continue
        data = f.read()
        if not (f.mimetype or "").startswith("image/") or len(data) > 2 * 1024 * 1024:
            return jsonify({"ok": False})
        images.append((key, f.mimetype, data))
    if not images:
        return jsonify({"ok": False})
    try:
        boxes = _pill_locate_boxes([(m, d) for _, m, d in images])
    except Exception as e:
        app.logger.exception(e)
        return jsonify({"ok": False})
    return jsonify({"ok": True, "boxes": {k: b for (k, _, _), b in zip(images, boxes)}})


def _pill_throttle():
    """연속 호출 방지 (토큰 비용 보호): 같은 세션 5초 이내 재요청 차단"""
    now = time.time()
    if now - float(session.get("pill_last_time", 0) or 0) < 5:
        return True
    session["pill_last_time"] = now
    return False


@app.route("/pill/identify", methods=["POST"])
@login_required
def pill_identify():
    if not load_pills():
        return jsonify({"ok": False, "message": "알약 데이터(pills.csv)가 없습니다. 관리자에게 문의하세요."})
    if not os.getenv("OPENAI_API_KEY"):
        return jsonify({"ok": False, "message": "AI 설정이 되어 있지 않습니다. 관리자에게 문의하세요."})
    if _pill_throttle():
        return jsonify({"ok": False, "message": "요청이 너무 빠릅니다. 잠시 후 다시 시도해 주세요."})

    images = []
    for key in ("front", "back"):
        f = request.files.get(key)
        if not f:
            continue
        if not (f.mimetype or "").startswith("image/"):
            return jsonify({"ok": False, "message": "이미지 파일만 올릴 수 있습니다."})
        data = f.read()
        if len(data) > 8 * 1024 * 1024:
            return jsonify({"ok": False, "message": "이미지 용량은 8MB 이하만 가능합니다."})
        images.append((key, f.mimetype, data))
    if not images:
        return jsonify({"ok": False, "message": "알약 사진을 찍어주세요."})

    try:
        feat = _pill_features_from_images(images)
    except Exception as e:
        app.logger.exception(e)
        return jsonify({"ok": False, "message": "사진 분석 중 오류가 발생했습니다. 다시 시도해 주세요."})

    front, back = feat.get("front", []), feat.get("back", [])
    if not front and not back:
        return jsonify({"ok": True, "groups": [], "message": "사진에서 알약을 찾지 못했습니다. 알약이 잘 보이도록 밝은 곳에서 다시 찍어주세요."})
    groups = _pill_build_groups(front, back)
    count = len(front) or len(back)
    msg = ""
    if count > PILL_RECOMMEND:
        msg = (f"알약이 {count}개로 많아 정확도가 떨어질 수 있습니다. "
               f"{PILL_RECOMMEND}알 이하로 나눠 찍으면 더 정확합니다.")
    if front and back and len(front) != len(back):
        msg = (msg + " " if msg else "") + (f"앞면에서 {len(front)}개, 뒷면에서 {len(back)}개를 찾아 앞면 기준 {len(front)}개로 정리했습니다. "
                                            "알약끼리 떨어뜨리고 무늬 없는 바닥에서 찍으면 더 정확합니다.")
    return jsonify({"ok": True, "groups": groups, "message": msg})


@app.route("/pill/search", methods=["POST"])
@login_required
def pill_search():
    """인식된 정보를 사용자가 고쳐서 다시 찾기 / 직접 입력 검색 (AI 호출 없음)"""
    d = request.get_json(silent=True) or {}
    imprints = [x.strip() for x in str(d.get("imprint", "")).split("/") if x.strip()]
    color = d.get("color") if d.get("color") in PILL_COLORS else ""
    shape = d.get("shape") if d.get("shape") in PILL_SHAPES else ""
    form = d.get("form") if d.get("form") in PILL_FORMS else ""
    if not imprints:
        return jsonify({"ok": True, "candidates": [], "message": "각인(알약에 새겨진 글자)을 입력해 주세요."})
    cands = search_pills(imprints, color, shape, form=form)
    return jsonify({"ok": True, "candidates": cands,
                    "message": "" if cands else "일치하는 알약을 찾지 못했습니다."})


# 카메라 앱 복귀 처리 (알약 확인·사례검색 공용)
# - 휴대폰은 카메라 앱을 쓰는 동안 메모리가 부족하면 이 화면을 강제로 새로 엽니다(사진도 사라짐).
# - 카메라를 열기 직전 표시를 남겨 두고, 새로 열린 경우 원래 화면·팝업으로 되돌린 뒤 안내합니다.
# - 안내창의 '다시 촬영' 버튼으로 카메라 앱을 바로 다시 엽니다.
CAM_RETURN_HTML = """
<style>
#camRetry{ display:none; position:fixed; inset:0; z-index:100010; background:rgba(15,23,42,0.55); align-items:center; justify-content:center; padding:16px; box-sizing:border-box; }
#camRetry .cr-box{ width:100%; max-width:320px; background:#fff; border-radius:16px; padding:22px 18px 16px; box-sizing:border-box; text-align:center; box-shadow:0 12px 32px rgba(0,0,0,0.2); }
#camRetry .cr-t{ font-size:16px; font-weight:800; color:#111827; margin:0 0 8px; }
#camRetry .cr-s{ font-size:14px; color:#4b5563; line-height:1.55; margin:0 0 16px; word-break:keep-all; }
#camRetry .cr-btns{ display:flex; gap:8px; }
#camRetry button{ flex:1; height:44px !important; margin:0 !important; border-radius:10px !important; font-size:15px !important; font-weight:700 !important; cursor:pointer; box-shadow:none !important; }
#camRetryClose{ background:#f3f4f6 !important; color:#374151 !important; border:1px solid #e5e7eb !important; }
#camRetryGo{ background:#2563eb !important; color:#fff !important; border:none !important; }
</style>
<div id="camRetry">
  <div class="cr-box">
    <p class="cr-t">📷 사진이 전달되지 않았어요</p>
    <p class="cr-s">사진을 찍는 동안 휴대폰이 화면을 새로 열었습니다.<br>다시 촬영해 주세요.</p>
    <div class="cr-btns">
      <button type="button" id="camRetryClose">닫기</button>
      <button type="button" id="camRetryGo">다시 촬영</button>
    </div>
  </div>
</div>
<script>
(function(){
  if(window.camPending) return;
  var KEY = "cam_pending", LIMIT = 5*60*1000;
  function read(){
    try{
      var p = JSON.parse(localStorage.getItem(KEY) || "null");
      if(p && Date.now() - p.t < LIMIT) return p;
      localStorage.removeItem(KEY);
    }catch(e){}
    return null;
  }
  window.camPending = {
    /* 카메라 열기 직전 호출 */
    set: function(kind, extra){
      try{ localStorage.setItem(KEY, JSON.stringify({ kind: kind, path: location.pathname, t: Date.now(), extra: extra || null })); }catch(e){}
    },
    clear: function(){ try{ localStorage.removeItem(KEY); }catch(e){} },
    /* 새로 열린 화면에서 해당 종류의 표시가 있으면 꺼내고 지움 */
    take: function(kind){
      var p = read();
      if(p && p.kind === kind && p.path === location.pathname){
        try{ localStorage.removeItem(KEY); }catch(e){}
        return p;
      }
      return null;
    },
    /* 촬영 실패 안내창: '다시 촬영'을 누르면 카메라 앱을 다시 엶
       (휴대폰은 사용자가 버튼을 눌러야만 카메라를 열 수 있어 자동으로는 못 엶) */
    notice: function(onRetry){
      var box = document.getElementById("camRetry");
      if(!box) return;
      function show(){
        /* 다른 안내창(개인정보 동의 등)이 떠 있으면 닫힌 뒤에 표시 */
        var pm = document.getElementById("privacyModal");
        if(pm && getComputedStyle(pm).display !== "none"){ setTimeout(show, 300); return; }
        box.style.display = "flex";
      }
      document.getElementById("camRetryGo").onclick = function(){ box.style.display = "none"; if(onRetry) onRetry(); };
      document.getElementById("camRetryClose").onclick = function(){ box.style.display = "none"; };
      show();
    }
  };
  /* 카메라 앱에서 정상적으로 돌아오면 표시를 지움 */
  document.addEventListener("visibilitychange", function(){
    if(document.visibilityState === "visible"){ setTimeout(window.camPending.clear, 2000); }
  });
  /* 다른 화면으로 정상 이동하면 지움 (휴대폰이 강제로 새로 열 때는 발생하지 않음) */
  var redirecting = false;
  window.addEventListener("pagehide", function(){ if(!redirecting) window.camPending.clear(); });
  /* 메인화면으로 새로 열렸으면 원래 화면으로 이동 */
  var p = read();
  if(p && location.pathname === "/home" && p.path !== "/home"){
    redirecting = true;
    location.replace(p.path);
  }
})();
</script>
"""


# 알약 확인 팝업 (홈·사전조사 공용). 템플릿에서 {{ pill_html|safe }} 로 삽입
PILL_HTML = """
<style>
.pill-modal{ display:none; position:fixed; inset:0; z-index:100002; background:rgba(15,23,42,0.6); align-items:center; justify-content:center; padding:12px; font-family:inherit; }
.pill-modal.show{ display:flex; }
.pill-box{ width:100%; max-width:520px; max-height:92vh; max-height:92dvh; background:#fff; border-radius:16px; display:flex; flex-direction:column; overflow:hidden; box-shadow:0 20px 50px rgba(0,0,0,0.25); text-align:left; color:#111827; }
.pill-head{ display:flex; flex-wrap:wrap; align-items:center; gap:2px 8px; padding:14px 16px; border-bottom:1px solid #e5e7eb; }
.pill-title{ font-size:16px; font-weight:800; }
.pill-sub{ flex-basis:100%; margin-top:8px; font-size:12px; color:#6b7280; line-height:1.45; word-break:keep-all; }
.pill-x{ flex:none; margin-left:auto; width:28px !important; height:28px !important; min-width:0 !important; padding:0 !important; margin-top:0 !important; border:none !important; border-radius:999px !important; background:#f3f4f6 !important; color:#374151 !important; font-size:17px !important; line-height:1 !important; box-shadow:none !important; cursor:pointer; }
.pill-body{ flex:1; overflow:auto; padding:14px 16px; min-height:0; }
/* 오른쪽 위 '직접 입력 / 사진으로' 전환 버튼 */
.pill-head-btns{ flex:none; margin-left:auto; margin-top:-4px; display:flex; align-items:center; gap:5px; }
.pill-head-btns .pill-x{ margin-left:0; }
.pill-mode{ width:auto !important; height:28px !important; min-width:0 !important; margin:0 !important; padding:0 10px !important; border:1px solid #c7d7ff !important; border-radius:999px !important; background:#eef4ff !important; color:#1d4ed8 !important; font-size:12px !important; font-weight:700 !important; white-space:nowrap; box-shadow:none !important; cursor:pointer; }
.pill-feat.pill-manual{ display:none; margin-top:0; }
.pill-manual .pill-go{ margin-top:10px !important; }
.pill-shots{ display:grid; grid-template-columns:1fr 1fr; gap:10px; }
.pill-shot{ position:relative; display:flex; flex-direction:column; align-items:center; justify-content:center; height:120px; padding:6px 8px 34px; box-sizing:border-box; border:1.5px dashed #93c5fd; border-radius:12px; background:#f8fbff; color:#1d4ed8; font-size:13px; font-weight:700; cursor:pointer; overflow:hidden; text-align:center; }
.pill-shot input{ display:none; }
.pill-shot img{ position:absolute; inset:0; width:100%; height:100%; object-fit:cover; }
.pill-shot small{ font-size:11px; font-weight:500; color:#6b7280; margin-top:3px; padding:0 6px; word-break:keep-all; }
.pill-shot.drag{ background:#eff6ff; border-color:#2563eb; border-style:solid; }
.pill-gal{ position:absolute; right:5px; bottom:5px; z-index:2; width:30px !important; height:30px !important; min-width:0 !important; margin:0 !important; padding:0 !important; border:1px solid #c7d7ff !important; border-radius:8px !important; background:rgba(255,255,255,0.95) !important; color:#1d4ed8 !important; display:flex; align-items:center; justify-content:center; box-shadow:0 1px 4px rgba(15,23,42,0.15) !important; cursor:pointer; }
.pill-gal svg{ width:18px; height:18px; display:block; }
.pill-tip{ display:flex; gap:4px; margin:10px 0 0; font-size:12px; color:#6b7280; line-height:1.5; word-break:keep-all; overflow-wrap:break-word; }
.pill-tip span:first-child{ flex:none; }  /* ※ 뒤로 줄바꿈된 글이 윗줄 첫 글자에 맞춰짐 */
.pill-go{ display:block; width:100% !important; height:44px !important; margin:12px 0 0 !important; padding:0 !important; border:none !important; border-radius:10px !important; background:#2563eb !important; color:#fff !important; font-size:15px !important; font-weight:800 !important; box-shadow:none !important; cursor:pointer; }
.pill-go:disabled{ background:#93c5fd !important; cursor:wait; }
.pill-msg{ display:none; margin-top:12px; padding:10px 12px; border-radius:10px; background:#fff7ed; border:1px solid #fdba74; color:#9a3412; font-size:13px; line-height:1.55; word-break:keep-all; }
.pill-feat{ display:none; margin-top:14px; padding:10px 12px; border-radius:12px; background:#eef4ff; border:1px solid #c7d7ff; }
.pill-feat-title{ font-size:12.5px; font-weight:800; color:#1e3a8a; }
.pill-feat-help{ margin:3px 0 8px; font-size:11.5px; color:#4b5563; line-height:1.45; word-break:keep-all; }
.pill-feat-row{ display:grid; grid-template-columns:1fr 1fr 1fr; gap:6px; }
.pill-feat-row input{ grid-column:1 / -1; }
/* 앞면·뒷면 글자 두 칸 */
.pill-imp2{ display:grid; grid-template-columns:1fr 1fr; gap:6px; margin-bottom:6px; }
.pill-imp2 label{ display:flex; flex-direction:column; gap:3px; min-width:0; font-size:11.5px; font-weight:700; color:#1e3a8a; }
.pill-imp2 input{ width:100%; height:38px; margin:0; padding:0 10px; border:1px solid #c7d7ff; border-radius:8px; font-size:14px; font-family:inherit; background:#fff; box-sizing:border-box; }
.pill-imp2 input:focus{ outline:none; border-color:#2563eb; box-shadow:0 0 0 3px rgba(37,99,235,0.10); }
.pill-imp2 input.err, .pill-imp2 input.err:focus{ border-color:#ef4444; box-shadow:0 0 0 3px rgba(239,68,68,0.15); }
/* 상단 찾기 방식 탭 */
.pill-tabs{ flex-basis:100%; display:grid; grid-template-columns:1fr 1fr; gap:4px; margin-top:12px; padding:4px; background:#f1f5f9; border-radius:12px; }
.pill-tab{ display:flex !important; align-items:center; justify-content:center; gap:6px; width:auto !important; height:40px !important; margin:0 !important; padding:0 6px !important; border:none !important; border-radius:9px !important; background:transparent !important; color:#64748b !important; font-size:14px !important; font-weight:700 !important; font-family:inherit; box-shadow:none !important; cursor:pointer; white-space:nowrap; }
.pill-tab svg{ width:18px; height:18px; flex:none; }
.pill-tab.on{ background:#fff !important; color:#1d4ed8 !important; box-shadow:0 1px 4px rgba(15,23,42,0.12) !important; }
/* 모양 선택: 모양 그림이 보이는 선택창 (원래 select는 숨겨 두고 값만 사용) */
.ps-wrap{ position:relative; min-width:0; }
.ps-btn{ width:100% !important; height:36px !important; margin:0 !important; padding:0 8px !important; display:flex !important; align-items:center; gap:5px; border:1px solid #c7d7ff !important; border-radius:8px !important; background:#fff !important; color:#111827 !important; font-size:13px !important; font-weight:400 !important; font-family:inherit; box-shadow:none !important; cursor:pointer; text-align:left; }
.ps-btn svg{ flex:none; width:22px; height:16px; }
.ps-btn .ps-name{ flex:1; min-width:0; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.ps-btn .ps-caret{ flex:none; color:#6b7280; font-size:10px; }
.ps-pop{ display:none; position:fixed; z-index:100005; width:252px; max-width:calc(100vw - 24px); padding:6px; background:#fff; border:1px solid #c7d7ff; border-radius:12px; box-shadow:0 10px 26px rgba(15,23,42,0.18); grid-template-columns:repeat(4, 1fr); gap:4px; }
.ps-pop.open{ display:grid; }
.ps-opt{ display:flex !important; flex-direction:column; align-items:center; justify-content:center; gap:3px; width:auto !important; height:auto !important; margin:0 !important; padding:6px 2px !important; border:1px solid transparent !important; border-radius:8px !important; background:#fff !important; color:#374151 !important; font-size:11px !important; font-weight:600 !important; font-family:inherit; box-shadow:none !important; cursor:pointer; white-space:nowrap; }
.ps-opt svg{ width:30px; height:22px; }
.ps-opt:hover{ background:#f5f8ff !important; }
.ps-opt.sel{ background:#eef4ff !important; border-color:#93c5fd !important; color:#1d4ed8 !important; }
.pill-feat-row input, .pill-feat-row select{ width:100%; height:36px; margin:0; padding:0 8px; border:1px solid #c7d7ff; border-radius:8px; font-size:13px; font-family:inherit; background:#fff; box-sizing:border-box; }
.pill-re{ width:100% !important; height:34px !important; margin:8px 0 0 !important; padding:0 !important; border:1px solid #93c5fd !important; border-radius:8px !important; background:#fff !important; color:#1d4ed8 !important; font-size:13px !important; font-weight:700 !important; box-shadow:none !important; cursor:pointer; }
.pill-list{ margin-top:12px; display:flex; flex-direction:column; gap:10px; }
.pill-group + .pill-group{ margin-top:18px; padding-top:14px; border-top:2px dashed #e5e7eb; }
.pill-group-title{ font-size:15px; font-weight:800; color:#111827; }
.pill-group .pill-feat{ display:block; }
.pill-card{ display:flex; gap:12px; padding:10px; border:1px solid #e5e7eb; border-radius:12px; }
.pill-card img{ flex:none; width:112px; height:62px; object-fit:contain; border-radius:6px; background:#f9fafb; }
.pill-info{ flex:1; min-width:0; }
.pill-name{ font-size:14px; font-weight:800; line-height:1.35; word-break:keep-all; }
.pill-meta{ margin-top:3px; font-size:12px; color:#6b7280; line-height:1.45; word-break:keep-all; }
.pill-conf{ display:inline-block; margin-right:4px; padding:1px 7px; border-radius:6px; font-size:11px; font-weight:800; vertical-align:1px; }
.pill-conf.high{ background:#dcfce7; color:#15803d; }
.pill-conf.mid{ background:#dbeafe; color:#1d4ed8; }
.pill-conf.low{ background:#f3f4f6; color:#6b7280; }
.pill-badge{ display:inline-block; margin-right:4px; padding:1px 7px; border-radius:6px; background:#ede9fe; color:#6d28d9; font-size:11px; font-weight:800; vertical-align:1px; }
.pill-actions{ display:flex; flex-wrap:wrap; gap:6px; margin-top:6px; }
.pill-link{ font-size:12px; font-weight:700; color:#2563eb; text-decoration:none; }
.pill-kind{ display:inline-block; margin-right:4px; padding:0 6px; border-radius:5px; background:#fef3c7; color:#92400e; font-size:11px; font-weight:800; }
.pill-card.picked{ border-color:#2563eb; box-shadow:0 0 0 2px rgba(37,99,235,0.15); }
.pill-pick{ width:auto !important; height:26px !important; margin:0 !important; padding:0 10px !important; border:1px solid #93c5fd !important; border-radius:999px !important; background:#fff !important; color:#1d4ed8 !important; font-size:12px !important; font-weight:700 !important; box-shadow:none !important; cursor:pointer; }
.pill-card.picked .pill-pick{ background:#2563eb !important; border-color:#2563eb !important; color:#fff !important; }
.pill-pick-help{ margin:8px 0 2px; font-size:12px; color:#92400e; font-weight:700; word-break:keep-all; }
.pill-care{ margin-top:18px; padding:14px; border-radius:14px; background:#fffbeb; border:1px solid #fcd34d; }
.pill-care-t{ font-size:14px; font-weight:800; color:#111827; }
.pill-care-kinds{ margin-top:6px; font-size:13px; color:#374151; line-height:1.6; word-break:keep-all; }
.pill-care-sub{ margin-top:12px; font-size:13px; font-weight:800; color:#92400e; }
.pill-care-sig{ margin:4px 0 0; padding-left:18px; font-size:13px; color:#374151; line-height:1.6; }
.pill-care-go{ display:block; width:100% !important; height:42px !important; margin:12px 0 0 !important; padding:0 !important; border:none !important; border-radius:10px !important; background:#d97706 !important; color:#fff !important; font-size:14px !important; font-weight:800 !important; box-shadow:none !important; cursor:pointer; }
.pill-care-go:disabled{ background:#fcd34d !important; cursor:default; }
.pill-care-note{ margin-top:8px; font-size:11px; color:#92400e; line-height:1.5; word-break:keep-all; }
.pill-yes{ width:auto !important; height:26px !important; margin:0 !important; padding:0 10px !important; border:none !important; border-radius:999px !important; background:#7c3aed !important; color:#fff !important; font-size:12px !important; font-weight:700 !important; box-shadow:none !important; cursor:pointer; }
.pill-loading{ display:none; position:fixed; inset:0; z-index:100003; background:rgba(0,0,0,0.5); align-items:center; justify-content:center; }
.pill-loading.show{ display:flex; }
.pill-loading-box{ box-sizing:border-box; width:86%; max-width:320px; background:#fff; border-radius:20px; padding:34px 24px 26px; text-align:center; display:flex; flex-direction:column; align-items:center; }
.pill-spinner{ width:42px; height:42px; border:5px solid #eee; border-top-color:#2563eb; border-radius:50%; animation:pillSpin 1s linear infinite; }
@keyframes pillSpin{ to{ transform:rotate(360deg); } }
.pill-load-title{ margin:14px 0 0; font-size:15px; font-weight:700; line-height:1.35; color:#111827; }
.pill-load-sub{ margin:8px 0 0; font-size:13px; line-height:1.5; color:#6b7280; word-break:keep-all; }
.pill-steps{ display:flex; gap:6px; width:150px; margin:16px auto 0; }
.pill-step{ flex:1; height:6px; border-radius:999px; background:#e5e7eb; transition:background .3s; }
.pill-step.on{ background:#2563eb; }
.pill-load-ci{ width:132px; margin-top:28px; opacity:0.82; display:block; }
.pill-foot{ flex:none; padding:8px 16px; border-top:1px solid #f1f5f9; font-size:11px; color:#9ca3af; line-height:1.5; word-break:keep-all; }
@media (max-width:480px){
  .pill-shot{ height:118px; }
  .pill-feat-row{ gap:5px; }
  .ps-btn{ padding:0 6px !important; gap:4px; font-size:12.5px !important; }
  .ps-btn .ps-caret{ display:none; }
  .pill-card img{ width:96px; height:54px; }
}
</style>

<div id="pillModal" class="pill-modal">
  <div class="pill-box">
    <div class="pill-head">
      <div>
        <div class="pill-title"><svg viewBox="0 0 24 24" style="width:1.15em;height:1.15em;vertical-align:-0.2em;margin-right:2px" aria-hidden="true"><g transform="rotate(-45 12 12)"><path d="M7 7h5v10H7a5 5 0 0 1 0-10z" fill="#3b82f6"/><path d="M12 7h5a5 5 0 0 1 0 10h-5z" fill="#fb923c"/><rect x="2" y="7" width="20" height="10" rx="5" fill="none" stroke="rgba(15,23,42,0.18)" stroke-width="1"/><path d="M4.8 10.6a2.4 2.4 0 0 1 2.2-1.6" stroke="#ffffff" stroke-width="1" stroke-linecap="round" fill="none" opacity=".8"/></g></svg> 알약 확인</div>
      </div>
      <div class="pill-head-btns">
        <button type="button" class="pill-x" onclick="closePill()" aria-label="닫기">×</button>
      </div>
      <div class="pill-sub" id="pillSub">알약의 앞·뒷면을 찍으면 식약처 낱알식별 정보에서 비슷한 약을 찾아드립니다.</div>
      <div class="pill-tabs" role="tablist">
        <button type="button" class="pill-tab on" data-m="photo" role="tab"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 8h3l2-3h6l2 3h3v11H4z"/><circle cx="12" cy="13" r="3.5"/></svg> 사진으로 찾기</button>
        <button type="button" class="pill-tab" data-m="text" role="tab"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="5" y="4" width="14" height="17" rx="2"/><path d="M9 4h6v3H9z"/><path d="M9 12h6M9 16h4"/></svg> 알약정보로 찾기</button>
      </div>
    </div>
    <div class="pill-body">
      <!-- 직접 입력: 사진 없이 각인 글자로 바로 검색 -->
      <div class="pill-feat pill-manual" id="pillManualPane">
        <div class="pill-feat-title">알약 정보 입력</div>
        <div class="pill-feat-help">알약에 새겨진 글자(각인)를 입력하세요. 한쪽 면에만 있으면 그 칸만 쓰면 됩니다. 색·모양·제형은 모르면 '전체'로 두세요.</div>
        <div class="pill-imp2">
          <label>앞면 글자<input type="text" id="pmImpF" placeholder="예: CT" autocomplete="off"></label>
          <label>뒷면 글자<input type="text" id="pmImpB" placeholder="(없으면 비움)" autocomplete="off"></label>
        </div>
        <div class="pill-feat-row">
          <select id="pmColor"></select>
          <select id="pmShape"></select>
          <select id="pmForm"></select>
        </div>
        <button type="button" class="pill-go" id="pmGo">검색</button>
      </div>
      <div id="pillPhotoPane">
      <div class="pill-shots">
        <div class="pill-shot" id="pillShotFront" data-side="front" role="button" tabindex="0">
          <input type="file" accept="image/*" capture="environment" data-side="front">
          <input type="file" accept="image/*" class="pill-gal-input" data-side="front">
          <span class="ps-t">📷 앞면</span><small class="ps-s">알약 1~5알</small>
          <button type="button" class="pill-gal" data-side="front" aria-label="갤러리에서 앞면 사진 선택"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="3" y="4" width="18" height="16" rx="2"/><circle cx="8.5" cy="9.5" r="1.5"/><path d="M21 16l-5-5-8 8"/></svg></button>
        </div>
        <div class="pill-shot" id="pillShotBack" data-side="back" role="button" tabindex="0">
          <input type="file" accept="image/*" capture="environment" data-side="back">
          <input type="file" accept="image/*" class="pill-gal-input" data-side="back">
          <span class="ps-t">📷 뒷면</span><small class="ps-s">(선택) 놓은 자리 그대로 뒤집어서 촬영</small>
          <button type="button" class="pill-gal" data-side="back" aria-label="갤러리에서 뒷면 사진 선택"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="3" y="4" width="18" height="16" rx="2"/><circle cx="8.5" cy="9.5" r="1.5"/><path d="M21 16l-5-5-8 8"/></svg></button>
        </div>
      </div>
      <p class="pill-tip"><span>※</span><span id="pillTipText">한 알도, 여러 알(최대 5알)도 됩니다. 여러 알이면 서로 떨어뜨려 놓고 찍은 뒤, 뒷면은 놓인 자리 그대로 하나씩 뒤집어 찍어주세요. 사진은 저장되지 않습니다.</span></p>
      <button type="button" class="pill-go" id="pillGo">검색</button>
      </div>

      <div class="pill-msg" id="pillMsg"></div>

      <div class="pill-list" id="pillList"></div>
    </div>
    <div class="pill-foot">참고용 후보입니다. 정확한 확인은 약사·의사에게 문의하세요.<br>자료: 식품의약품안전처 의약품 낱알식별 정보</div>
  </div>
</div>

<div id="pillLoading" class="pill-loading">
  <div class="pill-loading-box">
    <div class="pill-spinner"></div>
    <p class="pill-load-title" id="pillLoadTitle"></p>
    <p class="pill-load-sub" id="pillLoadSub"></p>
    <div class="pill-steps"><div class="pill-step"></div><div class="pill-step"></div><div class="pill-step"></div><div class="pill-step"></div></div>
    <img src="/static/ci.png" class="pill-load-ci" alt="" onerror="this.style.display='none'">
  </div>
</div>

<script>
(function(){
  var COLORS = ["하양","노랑","주황","분홍","빨강","갈색","연두","초록","청록","파랑","남색","자주","보라","회색","검정","투명"];
  var SHAPES = ["원형","타원형","장방형","반원형","삼각형","사각형","마름모형","오각형","육각형","팔각형","기타"];
  var FORMS = ["정제","경질캡슐","연질캡슐"];
  var modal = document.getElementById("pillModal");
  if(!modal) return;
  var files = { front:null, back:null };
  var surveyMode = false;
  var goBtn = document.getElementById("pillGo");
  var msg = document.getElementById("pillMsg");
  var list = document.getElementById("pillList");

  /* ── 직접 입력 모드: 사진 없이 각인·색·모양으로 바로 검색 ── */
  var manualPane = document.getElementById("pillManualPane");
  var photoPane = document.getElementById("pillPhotoPane");
  var tabs = modal.querySelectorAll(".pill-tab");
  /* 각인을 비우고 검색하면 앞면 칸에 빨간 테두리 + 커서 이동, 글자를 입력하면 테두리 해제 */
  function markImpEmpty(inp){
    if(!inp) return;
    inp.classList.add("err");
    try{ inp.focus(); inp.scrollIntoView({ block:"center", behavior:"smooth" }); }catch(e){}
  }
  modal.addEventListener("input", function(e){
    var t = e.target;
    if(!t || !t.closest || !t.closest(".pill-imp2")) return;
    Array.prototype.forEach.call(t.closest(".pill-imp2").querySelectorAll("input.err"), function(x){ x.classList.remove("err"); });
  });
  function joinImp(a, b){ return [a, b].map(function(x){ return String(x || "").trim(); }).filter(function(x){ return x; }).join(" / "); }
  var subEl = document.getElementById("pillSub");
  var photoSub = null;
  function setManual(on){
    if(photoSub === null) photoSub = subEl.textContent;   /* PC/모바일 문구 그대로 보관 */
    manualPane.style.display = on ? "block" : "none";
    photoPane.style.display = on ? "none" : "";
    Array.prototype.forEach.call(tabs, function(t){ t.classList.toggle("on", (t.getAttribute("data-m") === "text") === on); });
    subEl.textContent = on ? "알약의 글자(각인)·색·모양·제형을 입력하면 식약처 낱알식별 정보에서 찾아드립니다." : photoSub;
    showMsg(""); list.innerHTML = "";
  }
  Array.prototype.forEach.call(tabs, function(t){
    t.addEventListener("click", function(){
      var wantText = t.getAttribute("data-m") === "text";
      if(wantText !== (manualPane.style.display === "block")) setManual(wantText);
    });
  });
  function manualSearch(){
    var imp = joinImp(document.getElementById("pmImpF").value, document.getElementById("pmImpB").value);
    if(!imp.trim()){ showMsg("각인(알약에 새겨진 글자)을 입력해 주세요."); markImpEmpty(document.getElementById("pmImpF")); return; }
    showMsg(""); list.innerHTML = "";
    var btn = document.getElementById("pmGo");
    btn.disabled = true; btn.textContent = "검색 중...";
    fetch("/pill/search", {
      method:"POST", credentials:"same-origin",
      headers:{ "Content-Type":"application/json" },
      body: JSON.stringify({ imprint: imp, color: document.getElementById("pmColor").value, shape: document.getElementById("pmShape").value, form: document.getElementById("pmForm").value })
    }).then(function(r){ return r.json(); }).then(function(d){
      if(!d || !d.ok){ showMsg((d && d.message) || "오류가 발생했습니다."); return; }
      renderCards(list, d.candidates);
      showMsg(d.message || "");
      scrollToResult();
    }).catch(function(){ showMsg("연결 오류가 발생했습니다."); })
      .finally(function(){ btn.disabled = false; btn.textContent = "검색"; });
  }
  document.getElementById("pmGo").addEventListener("click", manualSearch);
  ["pmImpF", "pmImpB"].forEach(function(id){
    document.getElementById(id).addEventListener("keydown", function(e){ if(e.key === "Enter"){ e.preventDefault(); manualSearch(); } });
  });

  function opts(arr, all, sel){
    return '<option value="">' + all + '</option>' + arr.map(function(v){
      return '<option value="' + v + '"' + (v === sel ? ' selected' : '') + '>' + v + '</option>';
    }).join("");
  }
  /* 모양 그림 (알약 모양을 눈으로 고를 수 있게) */
  var SHAPE_ICON = {
    "": '<circle cx="12" cy="12" r="8" stroke-dasharray="3 2.5"/>',
    "원형": '<circle cx="12" cy="12" r="8"/>',
    "타원형": '<ellipse cx="12" cy="12" rx="10" ry="6.5"/>',
    "장방형": '<rect x="2" y="7" width="20" height="10" rx="3"/>',
    "반원형": '<path d="M3 16 A9 9 0 0 1 21 16 Z"/>',
    "삼각형": '<polygon points="12,4 21,19 3,19"/>',
    "사각형": '<rect x="5" y="5" width="14" height="14" rx="2"/>',
    "마름모형": '<polygon points="12,3 21,12 12,21 3,12"/>',
    "오각형": '<polygon points="12,3 21,10 17.5,20 6.5,20 3,10"/>',
    "육각형": '<polygon points="7,4 17,4 22,12 17,20 7,20 2,12"/>',
    "팔각형": '<polygon points="8.5,3 15.5,3 21,8.5 21,15.5 15.5,21 8.5,21 3,15.5 3,8.5"/>',
    "기타": '<path d="M6 8 Q12 2 18 8 Q22 14 15 18 Q8 22 5 15 Z"/>'
  };
  function shapeSvg(v){
    var on = !!v;
    return '<svg viewBox="0 0 24 24" aria-hidden="true" fill="' + (on ? '#dbeafe' : 'none') + '" stroke="' + (on ? '#2563eb' : '#9ca3af') + '" stroke-width="1.6" stroke-linejoin="round">' + (SHAPE_ICON[v] || SHAPE_ICON["기타"]) + '</svg>';
  }
  /* 색 견본 */
  var COLOR_HEX = {
    "하양":"#ffffff", "노랑":"#facc15", "주황":"#fb923c", "분홍":"#f9a8d4", "빨강":"#ef4444", "갈색":"#92400e",
    "연두":"#a3e635", "초록":"#16a34a", "청록":"#14b8a6", "파랑":"#3b82f6", "남색":"#1e3a8a", "자주":"#a21caf",
    "보라":"#8b5cf6", "회색":"#9ca3af", "검정":"#111827"
  };
  function colorSvg(v){
    if(!v) return '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="8" fill="none" stroke="#9ca3af" stroke-width="1.6" stroke-dasharray="3 2.5"/></svg>';
    if(v === "투명") return '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="8" fill="rgba(219,234,254,0.45)" stroke="#93c5fd" stroke-width="1.6"/><path d="M8.5 9.5 A4.5 4.5 0 0 1 12 7.5" fill="none" stroke="#ffffff" stroke-width="1.8" stroke-linecap="round"/></svg>';
    return '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="8" fill="' + (COLOR_HEX[v] || "#e5e7eb") + '" stroke="rgba(15,23,42,0.25)" stroke-width="1.2"/></svg>';
  }
  /* 제형 그림: 정제(분할선 있는 알약) / 경질캡슐(두 색 캡슐) / 연질캡슐(말랑한 반투명 캡슐) */
  function formSvg(v){
    if(v === "정제") return '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="8" fill="#f8fafc" stroke="#64748b" stroke-width="1.6"/><line x1="12" y1="5" x2="12" y2="19" stroke="#94a3b8" stroke-width="1.4"/></svg>';
    if(v === "경질캡슐") return '<svg viewBox="0 0 24 24" aria-hidden="true"><g transform="rotate(-35 12 12)"><path d="M7 8h5v8H7a4 4 0 0 1 0-8z" fill="#3b82f6"/><path d="M12 8h5a4 4 0 0 1 0 8h-5z" fill="#f8fafc"/><rect x="3" y="8" width="18" height="8" rx="4" fill="none" stroke="#475569" stroke-width="1.2"/></g></svg>';
    if(v === "연질캡슐") return '<svg viewBox="0 0 24 24" aria-hidden="true"><ellipse cx="12" cy="12" rx="9.5" ry="6" fill="#fbbf24" fill-opacity="0.85" stroke="#d97706" stroke-width="1.2" transform="rotate(-25 12 12)"/><ellipse cx="9" cy="10" rx="3" ry="1.3" fill="#ffffff" fill-opacity="0.75" transform="rotate(-25 9 10)"/></svg>';
    return '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="8" fill="none" stroke="#9ca3af" stroke-width="1.6" stroke-dasharray="3 2.5"/></svg>';
  }
  function enhanceShape(sel){ enhancePicker(sel, SHAPES, shapeSvg, "모양 전체"); }
  function enhanceForm(sel){ enhancePicker(sel, FORMS, formSvg, "제형 전체"); }
  function enhanceColor(sel){ enhancePicker(sel, COLORS, colorSvg, "색 전체"); }

  /* select 를 그림 선택창으로 바꿈. select 는 숨긴 채 값만 보관하므로 기존 검색 코드는 그대로 동작 */
  function enhancePicker(sel, LIST, iconFn, allLabel){
    if(!sel || sel.getAttribute("data-ps")) return;
    sel.setAttribute("data-ps", "1");
    sel.style.display = "none";
    var wrap = document.createElement("div");
    wrap.className = "ps-wrap";
    sel.parentNode.insertBefore(wrap, sel);
    wrap.appendChild(sel);
    var btn = document.createElement("button");
    btn.type = "button"; btn.className = "ps-btn";
    var pop = document.createElement("div");
    pop.className = "ps-pop";
    wrap.appendChild(btn); wrap.appendChild(pop);
    function label(v){ return v || allLabel; }
    function update(){
      btn.innerHTML = iconFn(sel.value) + '<span class="ps-name">' + label(sel.value) + '</span><span class="ps-caret">▼</span>';
      Array.prototype.forEach.call(pop.children, function(o){ o.classList.toggle("sel", o.getAttribute("data-v") === sel.value); });
    }
    [""].concat(LIST).forEach(function(v){
      var o = document.createElement("button");
      o.type = "button"; o.className = "ps-opt"; o.setAttribute("data-v", v);
      o.innerHTML = iconFn(v) + '<span>' + (v || "전체") + '</span>';
      o.addEventListener("click", function(e){
        e.stopPropagation();
        sel.value = v;
        sel.dispatchEvent(new Event("change", { bubbles:true }));
        pop.classList.remove("open");
        update();
      });
      pop.appendChild(o);
    });
    btn.addEventListener("click", function(e){
      e.stopPropagation();
      var willOpen = !pop.classList.contains("open");
      Array.prototype.forEach.call(modal.querySelectorAll(".ps-pop.open"), function(x){ x.classList.remove("open"); });
      if(!willOpen) return;
      pop.classList.add("open");
      /* 팝업 안쪽 스크롤 영역에 잘리지 않도록 화면 기준으로 위치 계산 (아래 공간이 부족하면 위로) */
      var r = btn.getBoundingClientRect(), w = pop.offsetWidth, h = pop.offsetHeight;
      var left = Math.max(12, Math.min(r.right - w, window.innerWidth - w - 12));
      var top = (r.bottom + 4 + h <= window.innerHeight - 8) ? r.bottom + 4 : Math.max(8, r.top - 4 - h);
      pop.style.left = left + "px"; pop.style.top = top + "px";
    });
    update();
  }
  /* 바깥을 누르거나 스크롤하면 모양 선택창 닫기 */
  function closeShapePops(){
    Array.prototype.forEach.call(modal.querySelectorAll(".ps-pop.open"), function(x){ x.classList.remove("open"); });
  }
  document.addEventListener("click", closeShapePops);
  modal.querySelector(".pill-body").addEventListener("scroll", closeShapePops);
  window.addEventListener("resize", closeShapePops);

  document.getElementById("pmColor").innerHTML = opts(COLORS, "색 전체", "");
  document.getElementById("pmShape").innerHTML = opts(SHAPES, "모양 전체", "");
  enhanceColor(document.getElementById("pmColor"));
  enhanceShape(document.getElementById("pmShape"));
  document.getElementById("pmForm").innerHTML = opts(FORMS, "제형 전체", "");
  enhanceForm(document.getElementById("pmForm"));

  /* 큰 사진은 휴대폰에서 줄여서 전송 (각인 판독에 충분한 1600px) */
  function shrink(file){
    return new Promise(function(resolve){
      if(!file || typeof createImageBitmap !== "function" || file.size < 1.5*1024*1024){ resolve(file); return; }
      createImageBitmap(file).then(function(bmp){
        var scale = Math.min(1, 1600 / Math.max(bmp.width, bmp.height));
        var c = document.createElement("canvas");
        c.width = Math.round(bmp.width*scale); c.height = Math.round(bmp.height*scale);
        c.getContext("2d").drawImage(bmp, 0, 0, c.width, c.height);
        if(bmp.close) bmp.close();
        c.toBlob(function(b){ resolve(b && b.size ? b : file); }, "image/jpeg", 0.85);
      }).catch(function(){ resolve(file); });
    });
  }

  /* 알약 위치 찾기용 작은 사진 (768px) */
  function small(file){
    return new Promise(function(resolve){
      if(!file || typeof createImageBitmap !== "function"){ resolve(null); return; }
      createImageBitmap(file).then(function(bmp){
        var scale = Math.min(1, 768 / Math.max(bmp.width, bmp.height));
        var c = document.createElement("canvas");
        c.width = Math.round(bmp.width*scale); c.height = Math.round(bmp.height*scale);
        c.getContext("2d").drawImage(bmp, 0, 0, c.width, c.height);
        if(bmp.close) bmp.close();
        c.toBlob(function(b){ resolve(b && b.size ? b : null); }, "image/jpeg", 0.8);
      }).catch(function(){ resolve(null); });
    });
  }

  /* 원본 해상도에서 알약 주변만 잘라냄 (사진 속 알약이 작을 때 각인이 크게 보이도록).
     위치를 못 찾았거나 이미 알약이 크게 찍힌 사진이면 기존처럼 전체 사진 */
  function cropToPill(file, box){
    if(!file || !box || typeof createImageBitmap !== "function") return shrink(file);
    return createImageBitmap(file).then(function(bmp){
      var W = bmp.width, H = bmp.height;
      var bw = (box[2] - box[0]) * W, bh = (box[3] - box[1]) * H;
      var cx = (box[0] + box[2]) / 2 * W, cy = (box[1] + box[3]) / 2 * H;
      /* 알약이 사진에 넓게 퍼져 있으면(여러 알 등) 잘라도 이득이 적고 가장자리가 잘릴 수 있어 전체 사진 */
      if(bw > W * 0.4 || bh > H * 0.4){ if(bmp.close) bmp.close(); return shrink(file); }
      /* 위치가 대략적이라 넉넉하게 (2.5배, 최소 짧은 변의 30%) */
      var minSide = Math.min(W, H) * 0.3;
      var w = Math.min(W, Math.max(bw * 2.5, minSide)), h = Math.min(H, Math.max(bh * 2.5, minSide));
      if(w * h > W * H * 0.5){ if(bmp.close) bmp.close(); return shrink(file); }
      var x = Math.min(Math.max(0, cx - w / 2), W - w), y = Math.min(Math.max(0, cy - h / 2), H - h);
      var sc = Math.min(1, 1600 / Math.max(w, h));
      var c = document.createElement("canvas");
      c.width = Math.round(w * sc); c.height = Math.round(h * sc);
      c.getContext("2d").drawImage(bmp, x, y, w, h, 0, 0, c.width, c.height);
      if(bmp.close) bmp.close();
      return new Promise(function(resolve){
        c.toBlob(function(b){ resolve(b && b.size ? b : file); }, "image/jpeg", 0.92);
      });
    }).catch(function(){ return shrink(file); });
  }

  /* 1) 작은 사진으로 알약 위치 찾기 → 2) 원본에서 그 부분만 잘라 판독용으로 보냄 (실패하면 전체 사진) */
  function preparePhotos(){
    return Promise.all([small(files.front), small(files.back)]).then(function(sm){
      if(!sm[0] && !sm[1]) return null;
      var fd = new FormData();
      if(sm[0]) fd.append("front", sm[0], "front.jpg");
      if(sm[1]) fd.append("back", sm[1], "back.jpg");
      return fetch("/pill/locate", { method:"POST", body:fd, credentials:"same-origin" })
        .then(function(r){ return r.json(); }).catch(function(){ return null; });
    }).catch(function(){ return null; }).then(function(loc){
      var boxes = (loc && loc.ok && loc.boxes) || {};
      return Promise.all([cropToPill(files.front, boxes.front), cropToPill(files.back, boxes.back)]);
    });
  }

  /* 찍은 사진을 앞면/뒷면 칸에 넣고 미리보기 */
  function setFile(side, f){
    files[side] = f || null;
    var box = modal.querySelector('.pill-shot[data-side="' + side + '"]');
    if(!box) return;
    var old = box.querySelector("img"); if(old) old.remove();
    if(f){
      var im = document.createElement("img");
      im.src = URL.createObjectURL(f);
      box.appendChild(im);
    }
  }

  /* (예비) 휴대폰 카메라 앱 / 파일 선택 */
  Array.prototype.forEach.call(modal.querySelectorAll(".pill-shot input"), function(inp){
    inp.addEventListener("click", function(e){ e.stopPropagation(); });
    inp.addEventListener("change", function(){
      if(window.camPending) window.camPending.clear();
      setFile(inp.getAttribute("data-side"), inp.files && inp.files[0]);
    });
  });

  /* 휴대폰 기본 카메라 앱으로 촬영. 열기 직전 표시를 남겨 화면이 새로 열려도 팝업을 복원 */
  function openPicker(side){
    var inp = modal.querySelector('.pill-shot[data-side="' + side + '"] input');
    if(!inp) return;
    if(!IS_PC && window.camPending) window.camPending.set("pill", { mode: surveyMode ? "survey" : "home", side: side });
    inp.click();
  }

  /* PC(터치 없는 기기): 카메라 대신 '사진 불러오기' (파일 선택 + 끌어다 놓기). 모바일은 그대로 */
  /* PC/모바일 판단: 메인화면과 동일하게 User-Agent 기준 (Android·iPhone·iPad·iPod·케어내비 앱 = 모바일) */
  var PILL_UA = navigator.userAgent || "";
  var IS_PC = !(/Android|iPhone|iPad|iPod/i.test(PILL_UA) || PILL_UA.indexOf("CareNaviApp") !== -1);
  if(IS_PC){
    document.getElementById("pillSub").textContent = "알약의 앞·뒷면 사진을 불러오면 식약처 낱알식별 정보에서 비슷한 약을 찾아드립니다.";
    document.getElementById("pillTipText").textContent = "알약 각인(글자)이 선명하게 보이는 사진을 불러와 주세요. 한 알도, 여러 알(최대 5알)도 됩니다. 사진은 저장되지 않습니다.";
    var PC_LABEL = { front: ["🖼️ 앞면 사진 불러오기", "클릭 또는 끌어다 놓기"], back: ["🖼️ 뒷면 사진 불러오기", "선택 · 클릭 또는 끌어다 놓기"] };
    Array.prototype.forEach.call(modal.querySelectorAll(".pill-shot"), function(box){
      var side = box.getAttribute("data-side");
      var inp = box.querySelector("input"); if(inp) inp.removeAttribute("capture");
      var gal = box.querySelector(".pill-gal"); if(gal) gal.style.display = "none";
      box.querySelector(".ps-t").textContent = PC_LABEL[side][0];
      box.querySelector(".ps-s").textContent = PC_LABEL[side][1];
      box.addEventListener("dragover", function(e){ e.preventDefault(); box.classList.add("drag"); });
      box.addEventListener("dragleave", function(){ box.classList.remove("drag"); });
      box.addEventListener("drop", function(e){
        e.preventDefault(); box.classList.remove("drag");
        var f = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0];
        if(f && (f.type || "").indexOf("image/") === 0) setFile(side, f);
      });
    });
  }

  Array.prototype.forEach.call(modal.querySelectorAll(".pill-shot"), function(box){
    box.addEventListener("click", function(){ openPicker(box.getAttribute("data-side")); });
    box.addEventListener("keydown", function(e){ if(e.key === "Enter" || e.key === " "){ e.preventDefault(); openPicker(box.getAttribute("data-side")); } });
  });

  /* 모바일: 우측 하단 액자 버튼 → 갤러리에서 사진 선택 (칸 클릭=카메라와 분리) */
  Array.prototype.forEach.call(modal.querySelectorAll(".pill-gal"), function(btn){
    btn.addEventListener("click", function(e){
      e.stopPropagation();
      var inp = modal.querySelector('.pill-gal-input[data-side="' + btn.getAttribute("data-side") + '"]');
      if(inp) inp.click();
    });
    btn.addEventListener("keydown", function(e){ e.stopPropagation(); });
  });

  function showMsg(t){ msg.textContent = t || ""; msg.style.display = t ? "block" : "none"; }

  /* 확인 중 로딩창 (사례검색과 같은 방식) */
  var LOAD_MSGS = [
    ["AI가 알약을 분석 중입니다", "사진 속 알약의 모양과 색을 확인하고 있습니다."],
    ["각인을 읽고 있습니다", "알약에 새겨진 글자를 확인하고 있습니다."],
    ["식약처 정보와 비교 중입니다", "등록된 알약 정보와 대조하고 있습니다."],
    ["결과를 정리하고 있습니다", "비슷한 순서로 후보를 정리하고 있습니다."]
  ];
  var loadBox = document.getElementById("pillLoading");
  var loadTimer = null;
  function setLoad(i){
    document.getElementById("pillLoadTitle").textContent = LOAD_MSGS[i][0];
    document.getElementById("pillLoadSub").textContent = LOAD_MSGS[i][1];
    Array.prototype.forEach.call(loadBox.querySelectorAll(".pill-step"), function(st, k){ st.classList.toggle("on", k <= i); });
  }
  function startLoading(){
    var i = 0; setLoad(0); loadBox.classList.add("show");
    clearInterval(loadTimer);
    loadTimer = setInterval(function(){ if(i < LOAD_MSGS.length - 1){ i++; setLoad(i); } else { clearInterval(loadTimer); } }, 3500);
  }
  function stopLoading(){ clearInterval(loadTimer); loadBox.classList.remove("show"); }

  function esc(s){ var d=document.createElement("div"); d.textContent = (s==null?"":s); return d.innerHTML; }

  /* 후보 카드 목록 */
  function renderCards(box, cands){
    box.innerHTML = "";
    (cands || []).forEach(function(c){
      var card = document.createElement("div");
      card.className = "pill-card";
      var prints = [c.print_front, c.print_back].filter(function(x){ return x; }).join(" / ");
      card.innerHTML =
        (c.image ? '<img src="' + esc(c.image) + '" alt="" loading="lazy">' : '') +
        '<div class="pill-info">' +
          '<div class="pill-name">' + (c.conf ? '<span class="pill-conf ' + esc(c.conf) + '">' + esc(c.conf_label) + '</span>' : '') + (c.dementia ? '<span class="pill-badge">치매약</span>' : '') + esc(c.name) + '</div>' +
          '<div class="pill-meta">' + (c.care && c.care.kind && !c.dementia ? '<span class="pill-kind">' + esc(c.care.kind) + '</span>' : '') + esc(c.company) + ' · ' + esc(c.etc_otc) + (c.cls ? ' · ' + esc(c.cls) : '') + '</div>' +
          '<div class="pill-meta">각인 ' + esc(prints || "-") + ' · ' + esc(c.color) + ' · ' + esc(c.shape) + '</div>' +
          '<div class="pill-actions">' +
            '<a class="pill-link" href="' + esc(c.detail_url) + '" target="_blank" rel="noopener noreferrer">상세정보(효능·용법) ↗</a>' +
          '</div>' +
        '</div>';
      if(surveyMode && c.dementia){
        var b = document.createElement("button");
        b.type = "button"; b.className = "pill-yes"; b.textContent = "치매약 복용 '예' 선택";
        b.addEventListener("click", function(){
          var r = document.querySelector('input[name="dementia"][value="y"]');
          window.closePill();
          if(r){ r.checked = true; r.dispatchEvent(new Event("change", {bubbles:true})); }
        });
        card.querySelector(".pill-actions").appendChild(b);
      }
      box.appendChild(card);
    });
  }

  /* ===== 돌봄 요약: 확인된 약 종류 → 검토해 볼 돌봄 → 사례검색으로 연결 =====
     - '거의 확실' 후보가 있으면 자동 선택, 후보가 모두 같은 종류면 고르지 않아도 됨
     - 후보끼리 종류가 다를 때만 '이 약이 맞아요' 버튼으로 고름 */
  var careState = [], careBoxRef = null;
  var SIGNAL_TEXT = {
    "낙상 주의": "낙상 위험이 있음",
    "어지럼 주의": "일어설 때 어지럼으로 넘어질 위험이 있음",
    "야간 화장실 낙상 주의": "밤에 화장실을 자주 가 낙상 위험이 있음",
    "식사·영양 관리": "식사와 영양 관리가 필요함",
    "넘어짐 시 출혈 주의": "넘어지면 출혈 위험이 커 낙상 예방이 필요함",
    "인지 지원": "치매로 인지 지원이 필요함"
  };
  function uniqList(a){ var o = []; a.forEach(function(x){ if(x && o.indexOf(x) === -1) o.push(x); }); return o; }
  function careOf(st){
    var c = st.cands;
    if(!c.length) return { status:"none" };
    if(st.sel !== null && c[st.sel]) return { status:"sel", care:c[st.sel].care };
    var kinds = uniqList(c.map(function(x){ return x.care && x.care.kind; }));
    if(kinds.length === 1) return { status:"same", care:c[0].care };
    return { status:"pick" };
  }
  function setupChoice(gi, glist, cands){
    var st = careState[gi];
    st.cands = cands; st.sel = null;
    cands.forEach(function(c, i){ if(c.conf === "high") st.sel = i; });
    var old = glist.parentNode && glist.parentNode.querySelector(".pill-pick-help");
    if(old) old.remove();
    var kinds = uniqList(cands.map(function(x){ return x.care && x.care.kind; }));
    if(kinds.length < 2) return;   /* 후보가 모두 같은 종류: 고를 필요 없음 */
    var help = document.createElement("div");
    help.className = "pill-pick-help";
    help.textContent = "후보마다 약 종류가 달라요. 실물과 같은 약을 골라 주세요.";
    glist.parentNode.insertBefore(help, glist);
    var cards = glist.querySelectorAll(".pill-card");
    function paint(){
      Array.prototype.forEach.call(cards, function(card, i){
        card.classList.toggle("picked", st.sel === i);
        var b = card.querySelector(".pill-pick");
        if(b) b.textContent = (st.sel === i) ? "✓ 선택됨" : "이 약이 맞아요";
      });
    }
    Array.prototype.forEach.call(cards, function(card, i){
      var b = document.createElement("button");
      b.type = "button"; b.className = "pill-pick";
      b.addEventListener("click", function(){
        st.sel = (st.sel === i) ? null : i;
        paint();
        renderCare(careBoxRef);
      });
      card.querySelector(".pill-actions").appendChild(b);
    });
    paint();
  }
  function renderCare(box){
    if(!box) return;
    var kinds = [], sigMap = {}, pending = 0;
    careState.forEach(function(st){
      var r = careOf(st);
      if(r.status === "pick"){ pending++; return; }
      if(r.status === "none") return;
      kinds.push(r.care.kind);
      (r.care.signals || []).forEach(function(sg){
        sigMap[sg] = sigMap[sg] || [];
        if(sigMap[sg].indexOf(r.care.kind) === -1) sigMap[sg].push(r.care.kind);
      });
    });
    var ukinds = uniqList(kinds), sigs = Object.keys(sigMap);
    if(!ukinds.length && !pending){ box.style.display = "none"; return; }
    box.style.display = "";
    var h = '<div class="pill-care-t">💊 확인된 약 ' + kinds.length + '개</div>' +
      '<div class="pill-care-kinds">' + (ukinds.length ? esc(ukinds.join(" · ")) : "-") +
      (pending ? ' <span style="color:#92400e">(' + pending + '개는 아직 선택 안 됨)</span>' : '') + '</div>';
    if(sigs.length){
      h += '<div class="pill-care-sub">⚠️ 검토해 볼 돌봄</div><ul class="pill-care-sig">' +
        sigs.map(function(sg){ return '<li>' + esc(sg) + ' (' + esc(sigMap[sg].join(", ")) + ')</li>'; }).join("") + '</ul>';
    }
    h += '<button type="button" class="pill-care-go"' + (ukinds.length ? '' : ' disabled') + '>이 내용으로 돌봄 서비스 찾기</button>' +
      '<div class="pill-care-note">약 종류로 본 참고 사항이며 의학적 판단이 아닙니다. 약 이름은 넘기지 않고 종류만 사례검색에 입력됩니다.</div>';
    box.innerHTML = h;
    var go = box.querySelector(".pill-care-go");
    if(go) go.addEventListener("click", function(){
      var q = ukinds.join("·") + " 복용 중." + sigs.map(function(sg){ return " " + (SIGNAL_TEXT[sg] || sg) + "."; }).join("");
      location.href = "/desc?query=" + encodeURIComponent(q);
    });
  }

  /* 알약 1개 묶음: (여러 알이면 'N번 알약') → AI가 읽은 정보(수정 가능) → 안내 → 후보 */
  function renderGroup(g, multi, onCands){
    var f = g.features || {};
    var impParts = String(f.imprint || "").split("/").map(function(x){ return x.trim(); }).filter(function(x){ return x; });
    var el = document.createElement("div");
    el.className = "pill-group";
    el.innerHTML =
      (multi ? '<div class="pill-group-title">' + g.no + '번 알약</div>' : '') +
      '<div class="pill-feat"' + (multi ? ' style="margin-top:8px"' : '') + '>' +
        '<div class="pill-feat-title">AI가 사진에서 읽은 정보</div>' +
        (multi ? '<div style="height:6px"></div>' : '<div class="pill-feat-help">사진 속 알약과 글자가 다르면 직접 고친 뒤 아래 버튼을 눌러주세요.</div>') +
        '<div class="pill-imp2">' +
          '<label>앞면 글자<input type="text" class="g-impF" value="' + esc(impParts[0] || "") + '"></label>' +
          '<label>뒷면 글자<input type="text" class="g-impB" placeholder="(없으면 비움)" value="' + esc(impParts.slice(1).join(" ")) + '"></label>' +
        '</div>' +
        '<div class="pill-feat-row">' +
          '<select class="g-color">' + opts(COLORS, "색 전체", f.color) + '</select>' +
          '<select class="g-shape">' + opts(SHAPES, "모양 전체", f.shape) + '</select>' +
          '<select class="g-form">' + opts(FORMS, "제형 전체", f.form) + '</select>' +
        '</div>' +
        '<button type="button" class="pill-re">다시 검색</button>' +
      '</div>' +
      '<div class="pill-msg g-msg" style="display:none"></div>' +
      '<div class="pill-list g-list"></div>';
    enhanceColor(el.querySelector(".g-color"));
    enhanceShape(el.querySelector(".g-shape"));
    enhanceForm(el.querySelector(".g-form"));
    var gmsg = el.querySelector(".g-msg"), glist = el.querySelector(".g-list");
    function setGMsg(t){ gmsg.textContent = t || ""; gmsg.style.display = t ? "block" : "none"; }
    setGMsg(g.message);
    renderCards(glist, g.candidates);
    if(onCands) onCands(glist, g.candidates || []);
    el.querySelector(".pill-re").addEventListener("click", function(){
      setGMsg(""); glist.innerHTML = "";
      if(!joinImp(el.querySelector(".g-impF").value, el.querySelector(".g-impB").value)){
        setGMsg("각인(알약에 새겨진 글자)을 입력해 주세요.");
        markImpEmpty(el.querySelector(".g-impF"));
        return;
      }
      fetch("/pill/search", {
        method:"POST", credentials:"same-origin",
        headers:{ "Content-Type":"application/json" },
        body: JSON.stringify({ imprint: joinImp(el.querySelector(".g-impF").value, el.querySelector(".g-impB").value), color: el.querySelector(".g-color").value, shape: el.querySelector(".g-shape").value, form: el.querySelector(".g-form").value })
      }).then(function(r){ return r.json(); }).then(function(d){
        if(!d || !d.ok){ setGMsg((d && d.message) || "오류가 발생했습니다."); return; }
        renderCards(glist, d.candidates);
        if(onCands) onCands(glist, d.candidates || []);
        setGMsg(d.message || "");
      }).catch(function(){ setGMsg("연결 오류가 발생했습니다."); });
    });
    return el;
  }

  function handle(data){
    if(!data || !data.ok){ showMsg((data && data.message) || "오류가 발생했습니다."); return; }
    list.innerHTML = "";
    var groups = data.groups || [];
    if(groups.length > 1){
      var note = document.createElement("div");
      note.className = "pill-feat-help";
      note.style.margin = "0 0 8px";
      note.textContent = "사진 속 알약 " + groups.length + "개를 찾았습니다. 앞면과 뒷면은 놓인 자리로 짝을 맞췄습니다. 글자가 다르면 해당 알약의 정보를 고친 뒤 다시 검색해 주세요.";
      list.appendChild(note);
    }
    careState = [];
    var careBox = careBoxRef = document.createElement("div");
    careBox.className = "pill-care";
    groups.forEach(function(g, gi){
      careState[gi] = { cands: [], sel: null };
      list.appendChild(renderGroup(g, groups.length > 1, function(glist, cands){
        setupChoice(gi, glist, cands);
        renderCare(careBox);
      }));
    });
    list.appendChild(careBox);
    renderCare(careBox);
    showMsg(data.message || "");
    scrollToResult();
  }

  /* 모바일: 결과가 나오면 결과 위치로 자동 스크롤 (인식 정보 → 후보 목록 순) */
  function scrollToResult(){
    if(!window.matchMedia("(max-width:767px)").matches) return;
    var body = modal.querySelector(".pill-body");
    var target = (msg.style.display === "block") ? msg : list;
    if(!body || !target) return;
    setTimeout(function(){
      var top = target.getBoundingClientRect().top - body.getBoundingClientRect().top + body.scrollTop - 8;
      body.scrollTo({ top: Math.max(0, top), behavior: "smooth" });
    }, 60);
  }

  goBtn.addEventListener("click", function(){
    if(!files.front && !files.back){ showMsg("알약 사진을 먼저 찍어주세요."); return; }
    goBtn.disabled = true; goBtn.textContent = "검색 중...";
    showMsg(""); list.innerHTML = "";
    startLoading();
    preparePhotos().then(function(arr){
      var fd = new FormData();
      if(arr[0]) fd.append("front", arr[0], "front.jpg");
      if(arr[1]) fd.append("back", arr[1], "back.jpg");
      return fetch("/pill/identify", { method:"POST", body:fd, credentials:"same-origin" });
    }).then(function(r){ return r.json(); }).then(handle)
      .catch(function(){ showMsg("연결 오류가 발생했습니다. 잠시 후 다시 시도해 주세요."); })
      .finally(function(){ stopLoading(); goBtn.disabled = false; goBtn.textContent = "검색"; });
  });

  /* survey=true 이면 치매약 후보에 '예 선택' 버튼 표시 (사전조사 화면) */
  window.openPill = function(survey, restored){
    surveyMode = !!survey;
    if(!restored){
      try{ if(navigator.sendBeacon){ navigator.sendBeacon("/pv/pill"); } else { fetch("/pv/pill", {method:"POST"}); } }catch(e){}
    }
    files = { front:null, back:null };
    Array.prototype.forEach.call(modal.querySelectorAll(".pill-shot"), function(b){
      var im = b.querySelector("img"); if(im) im.remove();
      Array.prototype.forEach.call(b.querySelectorAll("input"), function(inp){ inp.value = ""; });
    });
    setManual(false);
    document.getElementById("pmImpF").value = "";
    document.getElementById("pmImpB").value = "";
    modal.classList.add("show");
    document.body.style.overflow = "hidden";
    /* 휴대폰 뒤로가기를 누르면 이전 화면(로그인)이 아니라 팝업만 닫히도록 기록 하나 추가 */
    if(!historyPushed){
      try{
        /* 화면이 새로 열려 복원된 경우 이미 기록이 있으면 재사용 */
        if(!(history.state && history.state.pillModal)) history.pushState({ pillModal: true }, "");
        historyPushed = true;
      }catch(e){}
    }
  };
  var historyPushed = false;
  function hidePill(){
    if(window.camPending) window.camPending.clear();
    modal.classList.remove("show");
    document.body.style.overflow = "";
  }
  window.closePill = function(){
    hidePill();
    /* X·바깥 클릭으로 닫으면 추가한 기록도 정리 */
    if(historyPushed){ historyPushed = false; try{ history.back(); }catch(e){} }
  };
  /* 뒤로가기 → 팝업 닫기 (메인화면 유지) */
  window.addEventListener("popstate", function(){
    if(historyPushed){ historyPushed = false; hidePill(); }
  });
  modal.addEventListener("click", function(e){ if(e.target === modal) window.closePill(); });

  /* 카메라 앱을 쓰는 동안 휴대폰이 화면을 새로 열었으면 팝업을 다시 열고 '다시 촬영' 안내 */
  var back = window.camPending && window.camPending.take("pill");
  if(back){
    window.openPill(back.extra && back.extra.mode === "survey", true);
    window.camPending.notice(function(){ openPicker((back.extra && back.extra.side) || "front"); });
  }
})();
</script>
"""
PILL_HTML = CAM_RETURN_HTML + PILL_HTML  # 카메라 앱 복귀 처리 포함

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
  background:#e8ecf4;
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
  color:#94a3b8;
  text-decoration:none;
  font-weight:500;
  opacity:0.8;
}

.home-admin-hidden:hover{
  color:#64748b;
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
  background:#93c5fd;
  border:none;
  border-radius:50%;
  color:#1e40af;
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
  cursor:pointer;
  display:flex;
  align-items:center;
  justify-content:space-between;
  gap:8px;
}
.notice-title-text{
  flex:1;
  min-width:0;
}
.notice-pin-badge{
  display:inline-block;
  font-size:10px;
  font-weight:800;
  color:#b91c1c;
  background:#fee2e2;
  border-radius:5px;
  padding:2px 6px;
  margin-right:6px;
  vertical-align:middle;
  line-height:1.3;
}
.notice-item.pinned{
  background:#fffbeb;
  margin:0 -20px;
  padding-left:20px;
  padding-right:20px;
}
.notice-item-title::after{
  content:'▾';
  font-size:12px;
  color:#9ca3af;
  flex-shrink:0;
  transition:transform 0.15s;
}
.notice-item.open .notice-item-title::after{
  transform:rotate(180deg);
}
.notice-item-date{
  font-size:11px;
  color:#9ca3af;
  margin-bottom:6px;
}
.notice-item-content{
  display:none;
  font-size:13px;
  color:#4b5563;
  line-height:1.65;
  word-break:keep-all;
  margin-top:8px;
}
.notice-item.open .notice-item-content{
  display:block;
}
/* 본문 한 줄씩 — 하이픈 줄은 마커+텍스트 분리해 wrap 시 글자 아래로 정확히 정렬 */
.notice-line:empty{
  height:0.5em;
}
.notice-line.bullet{
  display:flex;
  gap:5px;
}
.notice-line.bullet .b-mark{
  flex-shrink:0;
  font-weight:800;
  color:#111827;
}
.notice-line.bullet .b-text{
  flex:1;
  min-width:0;
}
/* 공지 페이지네이션 */
.notice-pagination{
  display:none;
  justify-content:center;
  align-items:center;
  flex-wrap:wrap;
  gap:6px;
  padding:12px 20px 14px;
  border-top:1px solid #f3f4f6;
}
.notice-page-btn{
  min-width:30px;
  height:30px;
  padding:0 8px;
  border:1px solid #e5e7eb;
  background:#fff;
  border-radius:8px;
  font-size:13px;
  font-weight:700;
  color:#6b7280;
  cursor:pointer;
}
.notice-page-btn.active{
  background:#2563eb;
  border-color:#2563eb;
  color:#fff;
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
  word-break:keep-all;
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
  background:#93c5fd;
  color:#1e40af;
  font-size:11px;
  font-weight:900;
  vertical-align:middle;
  line-height:1;
}

/* PC: 가이드 투어 팝업 더 크게 */
@media (min-width:601px){
  .tour-popup{
    width:480px;
    max-width:none;
    padding:30px 32px 22px;
    border-radius:18px;
  }
  .tour-popup-title{ font-size:21px; margin-bottom:10px; }
  .tour-popup-text{ font-size:16px; line-height:1.6; margin-bottom:20px; }
  .tour-btn{ font-size:14.5px; padding:10px 18px; border-radius:10px; }
  .tour-q-icon{ width:20px; height:20px; font-size:12px; }
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
  border-left:8px solid #3b82f6;
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

/* 알약 확인 카드 아이콘 (다른 카드의 26px 아이콘과 크기 맞춤) */
.pill-home-ico{
  display:block;
  width:26px;
  margin-left:auto;
  margin-right:auto;
  font-size:22px;
  line-height:26px;
  height:26px;
  margin-bottom:4px;
}
@media (max-width:480px){
  .pill-home-ico{ font-size:17px; line-height:20px; height:20px; width:20px; margin-bottom:2px; }
  .bottom-row{ gap:8px !important; }
  .bottom-row .bottom-card div{ font-size:12px; line-height:1.25; word-break:keep-all; }
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

.copyright .visitor-box{
  width:100%;
  justify-content:flex-end;
  margin-top:10px;
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




/* 메인 메뉴 카드: 솟은 버튼 + 누르면 들어감 (디자인 전용) */
.main-menu-card, .sub-card, .bottom-card { box-shadow:0 2px 5px rgba(15,23,42,0.08); transition:transform .12s ease; }

/* 길게눌러(상세메뉴)·뒤로가기 후 호버가 끼어 간격·띠지색이 틀어지는 것 방지
   — 브라우저 hover 감지(@media hover)에 의존하지 않고, 모든 기기에서 hover를 평상시와 동일하게 고정 */
.main-menu-card, .sub-card, .bottom-card{
  -webkit-touch-callout:none;
  -webkit-user-select:none;
  user-select:none;
}
.card:hover, .main-menu-card:hover, .sub-card:hover, .bottom-card:hover{
  transform:none !important;
  box-shadow:0 2px 5px rgba(15,23,42,0.08) !important;
}
.main-menu-card:hover, .sub-card:hover, .bottom-card:hover{ background:#fff !important; }
.main-menu-card:hover{ border-left-color:#3b82f6 !important; }
.sub-card:hover{ border-left-color:#fb7185 !important; }
/* 누름 효과: 다른 버튼과 통일(살짝 작아짐). 호버 규칙보다 뒤에 둬서 탭 시 우선 적용 */
.main-menu-card:active, .sub-card:active, .bottom-card:active{ transform:translateY(2px) scale(0.97) !important; box-shadow:0 1px 2px rgba(15,23,42,0.05) !important; }
html.tap-reset .main-menu-card, html.tap-reset .sub-card, html.tap-reset .bottom-card{ transform:none !important; }

/* === 버튼 누름 효과 B (디자인 전용) === */
button, input[type="submit"], input[type="button"], a.card, .btn, .home-btn, .home-button, .reset-btn, .home-help-btn, .home-notice-btn, .tip-btn, #fabMain, .fab-item, [class*="-btn"], [class*="-button"] { transition:transform .12s ease, box-shadow .12s ease; }
button:active, input[type="submit"]:active, input[type="button"]:active, .btn:active, .home-btn:active, .home-button:active, .reset-btn:active, .home-help-btn:active, .home-notice-btn:active, .tip-btn:active, #fabMain:active, .fab-item:active, [class*="-btn"]:active, [class*="-button"]:active { transform:scale(0.92) !important; }
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
<h1>리부트-G <span>케어내비</span></h1>
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

<div>사업 안내</div>

</a>

<a href="#" class="bottom-card" onclick="if(window.openPill){openPill(false);} return false;">

<span class="pill-home-ico"><svg viewBox="0 0 24 24" style="width:100%;height:100%;display:block" aria-hidden="true"><g transform="rotate(-45 12 12)"><path d="M7 7h5v10H7a5 5 0 0 1 0-10z" fill="#3b82f6"/><path d="M12 7h5a5 5 0 0 1 0 10h-5z" fill="#fb923c"/><rect x="2" y="7" width="20" height="10" rx="5" fill="none" stroke="rgba(15,23,42,0.18)" stroke-width="1"/><path d="M4.8 10.6a2.4 2.4 0 0 1 2.2-1.6" stroke="#ffffff" stroke-width="1" stroke-linecap="round" fill="none" opacity=".8"/></g></svg></span>

<div>복용약 검색</div>

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
        {% if survey_on %}
        <div id="fabItem_survey" class="fab-item">
          <div class="fab-item-btn fab-item-btn-survey">
            <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" fill="white" viewBox="0 0 24 24">
              <path d="M19 3h-4.18C14.4 1.84 13.3 1 12 1s-2.4.84-2.82 2H5c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h14c1.1 0 2-.9 2-2V5c0-1.1-.9-2-2-2zm-7 0c.55 0 1 .45 1 1s-.45 1-1 1-1-.45-1-1 .45-1 1-1zm-2 14l-4-4 1.41-1.41L10 14.17l6.59-6.59L18 9l-8 8z"/>
            </svg>
          </div>
          <span class="fab-item-label">설문조사</span>
        </div>
        {% endif %}
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
  </div>

  <div class="copyright">
    <div class="copyright-line"></div>
    <div class="copyright-main">
      ©국민건강보험공단 광주전라제주지역본부
    </div>
    <div class="copyright-sub">
      통합돌봄부<span class="tf-label">(TF)</span> &amp; 연구반 <span class="brand">돌봄곳간</span>
    </div>
    <div class="visitor-box">
      <div>총 {{total}}</div>
      <div>오늘 {{today}}</div>
    </div>
    <div style="text-align:right;padding:8px 0 0;">
      <a href="/privacy" style="font-size:11px;color:#9ca3af;text-decoration:underline;">개인정보 처리방침</a>
    </div>
  </div>

</div>

<style>

/* === 버튼 누름 효과 B (디자인 전용) === */
button, input[type="submit"], input[type="button"], a.card, .btn, .home-btn, .home-button, .reset-btn, .home-help-btn, .home-notice-btn, .tip-btn, #fabMain, .fab-item, [class*="-btn"], [class*="-button"] { transition:transform .12s ease, box-shadow .12s ease; }
button:active, input[type="submit"]:active, input[type="button"]:active, .btn:active, .home-btn:active, .home-button:active, .reset-btn:active, .home-help-btn:active, .home-notice-btn:active, .tip-btn:active, #fabMain:active, .fab-item:active, [class*="-btn"]:active, [class*="-button"]:active { transform:scale(0.92) !important; }
</style>


<!-- ===== 단일 의견보내기 버튼 (PC/아이폰/앱) ===== -->




<!-- ===== Modal ===== -->

<!-- ===== 앱 설치 안내 모달 ===== -->
<div id="apkInstallModal" onclick="closeApkInstallModalByBg(event)">
  <div class="apk-install-box">

    <div class="apk-install-icon">📱</div>

    <div class="apk-install-title">케어내비 앱 설치 안내</div>

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

/* 설문조사(임시기능) — 파란색이 아닌 주황색으로 눈에 띄게 */
.fab-item-btn-survey{
  background:linear-gradient(135deg,#fb923c,#f97316) !important;
  box-shadow:0 4px 12px rgba(249,115,22,0.45) !important;
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
  top:-3px;
  right:-3px;
  width:15px;
  height:15px;
  background:#ef4444;
  border-radius:50%;
  border:2.5px solid #fff;
  box-shadow:0 1px 3px rgba(0,0,0,0.25);
  z-index:2;
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


/* === 버튼 누름 효과 B (디자인 전용) === */
button, input[type="submit"], input[type="button"], a.card, .btn, .home-btn, .home-button, .reset-btn, .home-help-btn, .home-notice-btn, .tip-btn, #fabMain, .fab-item, [class*="-btn"], [class*="-button"] { transition:transform .12s ease, box-shadow .12s ease; }
button:active, input[type="submit"]:active, input[type="button"]:active, .btn:active, .home-btn:active, .home-button:active, .reset-btn:active, .home-help-btn:active, .home-notice-btn:active, .tip-btn:active, #fabMain:active, .fab-item:active, [class*="-btn"]:active, [class*="-button"]:active { transform:scale(0.92) !important; }
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
  var fabItemSurvey = document.getElementById("fabItem_survey");
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
  var activeItems = [fabItemNotice, fabItemRep, fabItemSurvey];
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
  if(fabItemSurvey){
    fabItemSurvey.addEventListener("click", function(e){
      e.stopPropagation();
      closeFab();
      location.href = "/satisfaction";
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
        <div class="notice-item{% if n.is_pinned %} pinned{% endif %}">
          <div class="notice-item-date">{{ n.created_date }}</div>
          <div class="notice-item-title"><span class="notice-title-text">{% if n.is_pinned %}<span class="notice-pin-badge">필독</span>{% endif %}{{ n.title }}</span></div>
          <div class="notice-item-content">
            {% for line in n.content_lines %}{% set t = line.lstrip() %}{% if t[:1] == '-' %}<div class="notice-line bullet"><span class="b-mark">-</span><span class="b-text">{{ t[1:].lstrip() }}</span></div>{% else %}<div class="notice-line">{{ line }}</div>{% endif %}{% endfor %}
          </div>
        </div>
        {% endfor %}
      {% else %}
        <div class="notice-empty">등록된 공지사항이 없습니다.</div>
      {% endif %}
    </div>
    <div class="notice-pagination" id="noticePagination"></div>
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
  <div class="tour-popup-title">케어내비를 처음 방문해주셨네요 👋</div>
  <div class="tour-popup-text">사용법은 우측 상단 <span style="white-space:nowrap;"><span class="tour-q-icon">?</span> 버튼을</span> 눌러보세요.</div>
  <div class="tour-popup-buttons">
    <button type="button" class="tour-btn tour-btn-primary" onclick="openGuideFromTour()">설명서 보기</button>
    <button type="button" class="tour-btn tour-btn-dismiss" onclick="dismissTourForever()">다시 보지 않기</button>
  </div>
</div>

<script>
/* ===== 공지사항 ===== */
/* ===== 공지 아코디언 + 페이지네이션 ===== */
var NoticePager = (function(){
  var PER_PAGE = 5;
  var inited = false, items = [], pager = null, body = null, pages = 1, current = 1;
  function collapseAll(){ items.forEach(function(it){ it.classList.remove('open'); }); }
  function renderButtons(){
    if(!pager) return;
    if(pages <= 1){ pager.style.display = 'none'; return; }
    pager.style.display = 'flex';
    pager.innerHTML = '';
    for(var p = 1; p <= pages; p++){
      (function(p){
        var b = document.createElement('button');
        b.type = 'button';
        b.className = 'notice-page-btn' + (p === current ? ' active' : '');
        b.textContent = p;
        b.onclick = function(){ collapseAll(); showPage(p); };
        pager.appendChild(b);
      })(p);
    }
  }
  function showPage(p){
    current = p;
    items.forEach(function(it, i){
      it.style.display = (Math.floor(i / PER_PAGE) + 1 === p) ? '' : 'none';
    });
    renderButtons();
    if(body) body.scrollTop = 0;
  }
  function init(){
    if(inited) return;
    body = document.querySelector('#noticeModal .notice-body');
    pager = document.getElementById('noticePagination');
    items = body ? Array.prototype.slice.call(body.querySelectorAll('.notice-item')) : [];
    pages = Math.max(1, Math.ceil(items.length / PER_PAGE));
    // 제목 클릭 시 본문 펼치기/접기
    items.forEach(function(it){
      var t = it.querySelector('.notice-item-title');
      if(t){ t.addEventListener('click', function(){ it.classList.toggle('open'); }); }
    });
    inited = true;
  }
  function open(){ init(); collapseAll(); showPage(1); }
  return { open: open };
})();

function openNotice(){
  if(window.__careNaviMarkNoticeSeen) window.__careNaviMarkNoticeSeen();
  NoticePager.open();
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
  try{ if(navigator.sendBeacon){ navigator.sendBeacon('/pv/guide'); } else { fetch('/pv/guide'); } }catch(e){}
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

/* 뒤로가기(bfcache) 복귀 시 끼어있는 누름 상태 초기화 */
window.addEventListener('pageshow', function(e){
  if(e.persisted){
    document.documentElement.classList.add('tap-reset');
    requestAnimationFrame(function(){
      requestAnimationFrame(function(){ document.documentElement.classList.remove('tap-reset'); });
    });
  }
});

</script>


{{ pill_html|default('')|safe }}
</body>
</html>
"""
@app.route("/home")
@login_required
def home():
    total, today = update_visitors()

    # 홈 하단 방문자수도 관리자 페이지와 동일하게 일자별 방문자수 기준으로 표시
    try:
        if os.getenv("RENDER") is not None:
            visit_res = requests.get(
                f"{SUPABASE_URL}/rest/v1/visit_daily_counts?select=visit_date,count",
                headers=SUPABASE_HEADERS, timeout=5
            )
            visit_rows = visit_res.json() if visit_res.ok else []
            total = sum(int(row.get("count", 0) or 0) for row in visit_rows)
            today_kst = datetime.datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d")
            today = next(
                (int(row.get("count", 0) or 0) for row in visit_rows if str(row.get("visit_date", "")) == today_kst),
                0
            )
    except Exception:
        pass

    notices = []
    try:
        if os.getenv("RENDER") is not None:
            res = requests.get(
                f"{SUPABASE_URL}/rest/v1/notices?select=*&is_active=eq.true&order=is_pinned.desc.nullslast,pinned_at.desc.nullslast,created_at.desc&limit=100",
                headers=SUPABASE_HEADERS, timeout=5
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
    return render_template_string(HOME_HTML, style=BASE_STYLE, total=total, today=today, notices=notices, latest_notice_key=latest_notice_key, survey_on=_survey_is_on())

STATS_HTML = """
<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>관리자 페이지</title>
<style>
body{
  margin:0;
  background:#e8ecf4;
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
  margin-left:auto;
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
.maint-btn{
  background:#fee2e2 !important;
  border:1px solid #fecaca !important;
  color:#dc2626 !important;
}
.maint-btn:hover{
  background:#fecaca !important;
  color:#b91c1c !important;
}
.card{
  background:#ffffff;
  border-radius:16px;
  padding:18px;
  margin-bottom:16px;
  box-shadow:0 10px 26px rgba(15,23,42,0.10);
}
.summary-row{
  display:flex;
  gap:12px;
  flex-wrap:nowrap;
}
.summary-box{
  flex:1;
  min-width:0;
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
    gap:4px !important;
    flex-wrap:nowrap !important;
    justify-content:space-between !important;
    overflow-x:auto !important;
    white-space:nowrap !important;
    margin-bottom:14px !important;
    padding-bottom:8px !important;
  }

  .top-right-menu{
    gap:4px !important;
    flex-wrap:nowrap !important;
    flex-shrink:0 !important;
  }

  .home-button{
    height:34px !important;
    padding:0 10px !important;
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
    height:32px !important;
    padding:0 8px !important;
    font-size:12.5px !important;
  }
  .top-bar,
  .top-right-menu{
    gap:3px !important;
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

/* 막대 그래프 (외부 라이브러리 없이 CSS) */
.chart{
  display:flex;
  align-items:flex-end;
  gap:6px;
  padding:22px 4px 0;
  overflow-x:auto;
  -webkit-overflow-scrolling:touch;
}
.chart-col{
  flex:1 0 26px;
  min-width:26px;
  display:flex;
  flex-direction:column;
  align-items:center;
}
.chart-bar{
  width:62%;
  max-width:32px;
  min-height:4px;
  background:linear-gradient(180deg,#60a5fa,#2563eb);
  border-radius:6px 6px 0 0;
  position:relative;
}
.chart-bar.pv{
  background:linear-gradient(180deg,#34d399,#059669);
}
.chart-bar.page{
  background:linear-gradient(180deg,#818cf8,#4f46e5);
}
.chart.pages .chart-col{
  flex:1 0 56px;
  min-width:56px;
}
.chart.pages .chart-xlabel{
  white-space:normal;
  text-align:center;
  line-height:1.2;
}
.chart-count{
  position:absolute;
  top:-16px;
  left:50%;
  transform:translateX(-50%);
  font-size:10px;
  font-weight:700;
  color:#374151;
  white-space:nowrap;
}
.chart-xlabel{
  margin-top:6px;
  font-size:10px;
  color:#9ca3af;
  white-space:nowrap;
}

/* 접속 환경 도넛 그래프 */
.env-wrap{
  display:flex;
  align-items:center;
  gap:24px;
  flex-wrap:wrap;
  padding:10px 4px 4px;
}
.env-donut{
  width:170px;
  height:170px;
  border-radius:50%;
  position:relative;
  flex:0 0 auto;
  box-shadow:inset 0 0 0 1px rgba(15,23,42,0.05);
}
.env-donut::after{
  content:"";
  position:absolute;
  inset:34px;
  background:#ffffff;
  border-radius:50%;
  box-shadow:0 0 0 1px #e5e7eb;
}
.env-center{
  position:absolute;
  inset:0;
  display:flex;
  flex-direction:column;
  align-items:center;
  justify-content:center;
  z-index:1;
  pointer-events:none;
}
.env-total-label{
  font-size:11px;
  color:#9ca3af;
  margin-bottom:3px;
}
.env-total-value{
  font-size:22px;
  font-weight:900;
  color:#111827;
}
.env-legend{
  flex:1;
  min-width:220px;
}
.env-row{
  display:grid;
  grid-template-columns:14px 1fr auto auto;
  gap:8px;
  align-items:center;
  padding:7px 0;
  border-bottom:1px solid #f1f5f9;
  font-size:13px;
}
.env-row:last-child{ border-bottom:none; }
.env-dot{
  width:10px;
  height:10px;
  border-radius:50%;
}
.env-name{ color:#374151; font-weight:700; }
.env-count{ color:#6b7280; text-align:right; }
.env-percent{ color:#111827; font-weight:800; text-align:right; }

@media (max-width:480px){
  .env-wrap{
    justify-content:center;
    gap:16px;
  }
  .env-donut{
    width:150px;
    height:150px;
  }
  .env-donut::after{
    inset:30px;
  }
}


/* === 버튼 누름 효과 B (디자인 전용) === */
button, input[type="submit"], input[type="button"], a.card, .btn, .home-btn, .home-button, .reset-btn, .home-help-btn, .home-notice-btn, .tip-btn, #fabMain, .fab-item, [class*="-btn"], [class*="-button"] { transition:transform .12s ease, box-shadow .12s ease; }
button:active, input[type="submit"]:active, input[type="button"]:active, .btn:active, .home-btn:active, .home-button:active, .reset-btn:active, .home-help-btn:active, .home-notice-btn:active, .tip-btn:active, #fabMain:active, .fab-item:active, [class*="-btn"]:active, [class*="-button"]:active { transform:scale(0.92) !important; }
</style>
</head>
<body>
<div class="container">

  <div class="top-bar">
    <a href="/home" class="home-button">홈으로</a>

    <div class="top-right-menu">
      <a href="/stats/satisfaction" class="home-button">설문</a>
      <a href="/board/admin" class="home-button">의견</a>
      <a href="/notice/admin" class="home-button">공지</a>
      <a href="/stats/export/xlsx/케어내비_통계.xlsx" class="home-button">엑셀</a>
      <a href="/admin/maintenance" class="home-button maint-btn">점검모드</a>
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
    <h2>방문 추세 <span class="small">(최근 {{ chart_visits|length }}일)</span></h2>
    <div class="chart">
      {% if chart_visits %}
        {% for r in chart_visits %}
        <div class="chart-col">
          <div class="chart-bar" style="height:{% if chart_visits_max %}{{ [ (r.count * 130 // chart_visits_max), 4 ]|max }}{% else %}4{% endif %}px;"><span class="chart-count">{{ r.count }}</span></div>
          <div class="chart-xlabel">{{ r.date[5:] }}</div>
        </div>
        {% endfor %}
      {% else %}
        <div class="small">데이터가 없습니다.</div>
      {% endif %}
    </div>
  </div>

  <div class="card">
    <h2>페이지별 조회수</h2>
    <div class="chart pages">
      {% if top_pages %}
        {% for r in top_pages %}
        <div class="chart-col">
          <div class="chart-bar page" style="height:{% if top_pages_max %}{{ [ (r.count * 130 // top_pages_max), 4 ]|max }}{% else %}4{% endif %}px;"><span class="chart-count">{{ r.count }}</span></div>
          <div class="chart-xlabel">{{ r.page }}</div>
        </div>
        {% endfor %}
      {% else %}
        <div class="small">아직 페이지뷰 데이터가 없습니다. (Supabase에 page_view_logs 테이블 생성 후 집계됩니다)</div>
      {% endif %}
    </div>
  </div>

  <div class="card">
    <h2>접속 환경 <span class="small">(총 방문자수 기준)</span></h2>
    <div class="env-wrap">
      <div class="env-donut" style="background:{{ env_chart_style }};">
        <div class="env-center">
          <div class="env-total-label">총 방문</div>
          <div class="env-total-value">{{ env_total }}</div>
        </div>
      </div>
      <div class="env-legend">
        {% if env_total > 0 %}
          {% for r in env_stats %}
          <div class="env-row">
            <span class="env-dot" style="background:{{ r.color }};"></span>
            <span class="env-name">{{ r.label }}</span>
            <span class="env-count">{{ r.count }}</span>
            <span class="env-percent">{{ r.percent }}%</span>
          </div>
          {% endfor %}
        {% else %}
          <div class="small">아직 접속 환경 데이터가 없습니다. (Supabase에 env_stats 테이블 생성 후 집계됩니다)</div>
        {% endif %}
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
    <h2>지역 클릭 내역</h2>
    <div>
    <table>
      <thead>
        <tr>
          <th>일시</th>
          <th>시도</th>
          <th>시군구</th>
          <th>검색구분</th>
        </tr>
      </thead>
      <tbody id="regionTableBody">
        {% for row in daily_regions %}
        <tr>
          <td>{{ row["datetime"] }}</td>
          <td>{{ row["sido"] }}</td>
          <td>{{ row["sigungu"] }}</td>
          <td>{{ row["search_type"] }}</td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
    </div>
    <div id="regionPager" class="pager"></div>
  </div>

  <div class="card">
    <h2>AI 토큰 사용량 <span class="small">(GPT-4.1-mini)</span></h2>
    <table style="width:100%; border-collapse:collapse; font-size:14px;">
      <thead>
        <tr style="color:#6b7280;">
          <th style="text-align:left; padding:8px 6px; border-bottom:1px solid #e5e7eb;"></th>
          <th style="text-align:right; padding:8px 6px; border-bottom:1px solid #e5e7eb;">입력 토큰</th>
          <th style="text-align:right; padding:8px 6px; border-bottom:1px solid #e5e7eb;">출력 토큰</th>
          <th style="text-align:right; padding:8px 6px; border-bottom:1px solid #e5e7eb;">사용 요금</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td style="padding:10px 6px;">총 누적</td>
          <td style="text-align:right; padding:10px 6px;">{{ "{:,}".format(tok_total_in) }}</td>
          <td style="text-align:right; padding:10px 6px;">{{ "{:,}".format(tok_total_out) }}</td>
          <td style="text-align:right; padding:10px 6px; color:#2563eb; font-weight:700;">₩{{ "{:,}".format(tok_total_krw) }}</td>
        </tr>
        <tr>
          <td style="padding:10px 6px; border-top:1px solid #f1f5f9;">오늘</td>
          <td style="text-align:right; padding:10px 6px; border-top:1px solid #f1f5f9;">{{ "{:,}".format(tok_today_in) }}</td>
          <td style="text-align:right; padding:10px 6px; border-top:1px solid #f1f5f9;">{{ "{:,}".format(tok_today_out) }}</td>
          <td style="text-align:right; padding:10px 6px; border-top:1px solid #f1f5f9; color:#2563eb; font-weight:700;">₩{{ "{:,}".format(tok_today_krw) }}</td>
        </tr>
      </tbody>
    </table>
    <div class="small" style="margin-top:8px; color:#9ca3af;">단가 입력 ${{ price_in }} / 출력 ${{ price_out }} (1M토큰당) · 환율 ₩{{ "{:,}".format(usd_krw) }}/$ 기준 · 근사치</div>
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
# =========================
# 페이지뷰/차트 집계 헬퍼 (관리자 통계용)
# =========================
def _kst_date_str(s):
    try:
        x = str(s).replace("Z", "+00:00")
        dt = datetime.datetime.fromisoformat(x)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.timezone.utc)
        return dt.astimezone(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d")
    except Exception:
        return str(s)[:10]

def _kst_datetime_str(s):
    """UTC created_at → KST 'YYYY-MM-DD HH:MM:SS' 문자열."""
    try:
        x = str(s).replace("Z", "+00:00")
        dt = datetime.datetime.fromisoformat(x)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.timezone.utc)
        return dt.astimezone(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return str(s)[:19].replace("T", " ")

app.jinja_env.filters['kst'] = _kst_datetime_str

import re as _re_pii
_PII_PATTERNS = [
    r'[\w.+-]+@[\w-]+\.[\w.-]+',              # 이메일
    r'(?<!\d)(?:19|20)\d{2}[-./년\s]+(?:0?[1-9]|1[0-2])[-./월\s]+(?:0?[1-9]|[12]\d|3[01])일?(?!\d)',  # 생년월일(구분자 포함)
    r'(?<!\d)(?:19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])(?!\d)',  # 생년월일(8자리)
    r'(?<!\d)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])(?!\d)',  # 생년월일(6자리)
    r'\d{6}\s*-\s*\d{7}',                     # 주민등록번호
    r'01[016789][-\s.]?\d{3,4}[-\s.]?\d{4}',  # 휴대폰
    r'\d{2,3}[-\s.]\d{3,4}[-\s.]\d{4}',       # 일반전화
]
def _contains_pii(text):
    """자유입력에 식별정보(주민번호·전화·이메일) 패턴이 있으면 True 반환.
    탐지 시 GPT로 전송하지 않고 차단. (이름은 패턴이 없어 탐지 못 함 → 경고문이 보완)"""
    if not text:
        return False
    t = str(text)
    return any(_re_pii.search(p, t) for p in _PII_PATTERNS)

def _friendly_page(path):
    return _PV_TRACK.get(path)

def _compute_pv_stats():
    """페이지뷰 통계 (화이트리스트 6개만 집계). 테이블 없거나 오류면 0/빈값."""
    # ⚠️ PostgREST 기본 행수 상한(1000)이 있어, 테이블이 1000행을 넘으면
    #    단일 요청은 일부만 돌려줘 집계가 틀어진다. id 기준 Range 페이지네이션으로
    #    전체 행을 나눠 받아 정확히 집계한다. (정렬은 개수 집계용이라 무관)
    rows = []
    try:
        _step = 1000
        _offset = 0
        while True:
            _res = requests.get(
                f"{SUPABASE_URL}/rest/v1/page_view_logs?select=created_at,path&order=id.asc",
                headers={
                    **SUPABASE_HEADERS,
                    "Range-Unit": "items",
                    "Range": f"{_offset}-{_offset + _step - 1}",
                },
                timeout=8
            )
            if not _res.ok:
                break
            _batch = _res.json()
            if not isinstance(_batch, list) or not _batch:
                break
            rows.extend(_batch)
            if len(_batch) < _step:      # 마지막 페이지
                break
            _offset += _step
            if _offset > 500000:         # 안전장치 (무한루프 방지)
                break
    except Exception:
        rows = []

    today_kst = datetime.datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d")
    daily_map = defaultdict(int)
    page_map = defaultdict(int)
    pv_today = 0
    pv_total = 0
    for r in rows:
        name = _friendly_page(str(r.get("path", "") or ""))
        if name is None:        # 허용목록 밖(과거 데이터 등) → 무시
            continue
        d = _kst_date_str(r.get("created_at", ""))
        daily_map[d] += 1
        page_map[name] += 1
        pv_total += 1
        if d == today_kst:
            pv_today += 1

    daily_pv = [{"date": d, "count": daily_map[d]} for d in sorted(daily_map.keys(), reverse=True)]
    top_pages = sorted(
        [{"page": p, "count": c} for p, c in page_map.items()],
        key=lambda x: x["count"], reverse=True
    )[:10]
    return pv_total, pv_today, daily_pv, top_pages

def _chart_data(daily_list, n=14):
    """일자별 {date,count} desc 리스트 → 최근 n일 asc + 최댓값."""
    asc = sorted(daily_list, key=lambda r: r["date"])[-n:]
    mx = max([r["count"] for r in asc], default=0)
    return asc, mx



def _compute_env_stats():
    """접속 환경 통계. User-Agent 원문 없이 env_stats의 집계값만 사용."""
    env_meta = [
        {"env": "PC", "label": "PC", "color": "#2563eb"},
        {"env": "Android", "label": "모바일(안드로이드)", "color": "#059669"},
        {"env": "iOS", "label": "모바일(iOS)", "color": "#7c3aed"},
        {"env": "Other", "label": "기타", "color": "#f59e0b"},
    ]
    counts = {m["env"]: 0 for m in env_meta}

    try:
        res = requests.get(
            f"{SUPABASE_URL}/rest/v1/env_stats?select=env,count",
            headers=SUPABASE_HEADERS,
            timeout=8
        )
        rows = res.json() if res.ok else []
        if not isinstance(rows, list):
            rows = []
        for row in rows:
            env = str(row.get("env", "") or "")
            cnt = int(row.get("count", 0) or 0)
            if env in counts:
                counts[env] += cnt
            else:
                counts["Other"] += cnt
    except Exception:
        pass

    total = sum(counts.values())
    stats = []
    start = 0.0
    segments = []

    for meta in env_meta:
        count = counts.get(meta["env"], 0)
        percent = round((count / total * 100), 1) if total else 0
        end = start + (count / total * 360) if total else start
        if total and count > 0:
            segments.append(f'{meta["color"]} {start:.2f}deg {end:.2f}deg')
        stats.append({
            "env": meta["env"],
            "label": meta["label"],
            "color": meta["color"],
            "count": count,
            "percent": percent,
        })
        start = end

    chart_style = "conic-gradient(" + ", ".join(segments) + ")" if segments else "#e5e7eb"
    return stats, total, chart_style

@app.route("/stats")
def stats():

    if os.getenv("RENDER") is None:
        total_count = 100
        today_count = 5

        daily_visits = [
            {"date": "2026-06-03", "count": 12},
            {"date": "2026-06-04", "count": 18},
            {"date": "2026-06-05", "count": 5}
        ]

        daily_regions = [
            {"datetime": "2026-06-04 14:32:10", "sido": "전남광주통합특별시", "sigungu": "북구", "search_type": "조건기반"},
            {"datetime": "2026-06-04 11:05:47", "sido": "전남광주통합특별시", "sigungu": "나주시", "search_type": "사례기반"},
            {"datetime": "2026-06-05 09:18:22", "sido": "전남광주통합특별시", "sigungu": "서구", "search_type": "조건기반"}
        ]

        pv_total, pv_today = 173, 41
        daily_pv = [
            {"date": "2026-06-03", "count": 58},
            {"date": "2026-06-04", "count": 74},
            {"date": "2026-06-05", "count": 41}
        ]
        top_pages = [
            {"page": "기관검색", "count": 64},
            {"page": "사례검색", "count": 52},
            {"page": "메인", "count": 41},
            {"page": "공지사항", "count": 16},
        ]
        env_stats = [
            {"env": "PC", "label": "PC", "color": "#2563eb", "count": 46, "percent": 46.0},
            {"env": "Android", "label": "모바일(안드로이드)", "color": "#059669", "count": 38, "percent": 38.0},
            {"env": "iOS", "label": "모바일(iOS)", "color": "#7c3aed", "count": 14, "percent": 14.0},
            {"env": "Other", "label": "기타", "color": "#f59e0b", "count": 2, "percent": 2.0},
        ]
        env_total = 100
        env_chart_style = "conic-gradient(#2563eb 0deg 165.60deg, #059669 165.60deg 302.40deg, #7c3aed 302.40deg 352.80deg, #f59e0b 352.80deg 360.00deg)"
    else:
        stats_res = requests.get(
            f"{SUPABASE_URL}/rest/v1/visit_stats?id=eq.1&select=*",
            headers=SUPABASE_HEADERS, timeout=5
        )
        stats_rows = stats_res.json() if stats_res.ok else []
        stats_row = stats_rows[0] if stats_rows else {}

        total_count = int(stats_row.get("total_count", 0))
        today_count = int(stats_row.get("today_count", 0))

        visit_res = requests.get(
            f"{SUPABASE_URL}/rest/v1/visit_daily_counts?select=visit_date,count&order=visit_date.desc",
            headers=SUPABASE_HEADERS, timeout=5
        )
        visit_rows = visit_res.json() if visit_res.ok else []

        daily_visits = []
        for row in visit_rows:
            date_str = str(row.get("visit_date", ""))
            if date_str:
                daily_visits.append({
                    "date": date_str,
                    "count": int(row.get("count", 0) or 0)
                })

        region_rows = fetch_all_rows(
            "region_logs?select=created_at,sido,sigungu,search_type&order=created_at.desc"
        )

        # 클릭별 상세 내역 — KST 일시 표시. region_rows는 created_at desc 정렬이라 최신순.
        daily_regions = []
        for row in region_rows:
            created_at = str(row.get("created_at", ""))
            dt_str = _kst_datetime_str(created_at) if created_at else ""
            sido = str(row.get("sido", "") or "")
            sigungu = str(row.get("sigungu", "") or "")
            raw_search_type = str(row.get("search_type", "") or "").strip()

            if raw_search_type == "combo":
                search_type = "조건기반"
            elif raw_search_type == "desc":
                search_type = "사례기반"
            else:
                search_type = raw_search_type or "-"

            daily_regions.append({
                "datetime": dt_str,
                "sido": sido,
                "sigungu": sigungu,
                "search_type": search_type
            })

        pv_total, pv_today, daily_pv, top_pages = _compute_pv_stats()
        env_stats, env_total, env_chart_style = _compute_env_stats()

    # 총 방문자수/오늘 방문자수는 일자별 방문자수 기준으로 표시
    total_count = sum(row.get("count", 0) for row in daily_visits)
    today_kst = datetime.datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d")
    today_count = next((row.get("count", 0) for row in daily_visits if row.get("date") == today_kst), 0)

    # 접속 환경도 요약 통계의 총 방문자수를 기준으로 표시
    # 환경별 집계에서 빠진 방문은 별도 항목을 만들지 않고 기타에 합산
    if os.getenv("RENDER") is not None:
        missing_env_count = total_count - env_total
        if missing_env_count > 0:
            for env_row in env_stats:
                if env_row["env"] == "Other":
                    env_row["count"] += missing_env_count
                    break
        env_total = total_count
        start_angle = 0.0
        segments = []
        for env_row in env_stats:
            env_count = env_row["count"]
            env_row["percent"] = round(env_count / env_total * 100, 1) if env_total else 0
            if env_total and env_count > 0:
                end_angle = start_angle + env_count / env_total * 360
                segments.append(
                    f'{env_row["color"]} {start_angle:.2f}deg {end_angle:.2f}deg'
                )
                start_angle = end_angle
        env_chart_style = ("conic-gradient(" + ", ".join(segments) + ")") if segments else "#e5e7eb"

    chart_visits, chart_visits_max = _chart_data(daily_visits, 10)
    chart_pv, chart_pv_max = _chart_data(daily_pv)
    top_pages_max = max([r["count"] for r in top_pages], default=0)

    # AI 토큰 사용량 집계 (token_usage) — 격리: 실패해도 통계 페이지엔 영향 없음
    tok_total_in = tok_total_out = tok_today_in = tok_today_out = 0
    try:
        today_kst = datetime.datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d")
        if os.getenv("RENDER") is not None:
            _tr = requests.get(
                f"{SUPABASE_URL}/rest/v1/token_usage?select=usage_date,input_tokens,output_tokens",
                headers=SUPABASE_HEADERS, timeout=8
            )
            _trows = _tr.json() if _tr.ok else []
        else:
            _trows = [
                {"usage_date": today_kst, "input_tokens": 12000, "output_tokens": 3000},
                {"usage_date": "2026-06-05", "input_tokens": 50000, "output_tokens": 9000},
            ]
        for _row in _trows:
            _i = int(_row.get("input_tokens", 0) or 0)
            _o = int(_row.get("output_tokens", 0) or 0)
            tok_total_in += _i
            tok_total_out += _o
            if str(_row.get("usage_date", "")) == today_kst:
                tok_today_in += _i
                tok_today_out += _o
    except Exception as e:
        app.logger.exception(e)

    def _tok_krw(inp, outp):
        usd = inp / 1_000_000 * GPT_PRICE_INPUT_USD + outp / 1_000_000 * GPT_PRICE_OUTPUT_USD
        return int(round(usd * USD_TO_KRW))
    tok_total_krw = _tok_krw(tok_total_in, tok_total_out)
    tok_today_krw = _tok_krw(tok_today_in, tok_today_out)

    return render_template_string(
        STATS_HTML,
        total_count=total_count,
        today_count=today_count,
        daily_visits=daily_visits,
        daily_regions=daily_regions,
        pv_total=pv_total,
        pv_today=pv_today,
        daily_pv=daily_pv,
        top_pages=top_pages,
        top_pages_max=top_pages_max,
        chart_visits=chart_visits,
        chart_visits_max=chart_visits_max,
        chart_pv=chart_pv,
        chart_pv_max=chart_pv_max,
        tok_total_in=tok_total_in,
        tok_total_out=tok_total_out,
        tok_total_krw=tok_total_krw,
        tok_today_in=tok_today_in,
        tok_today_out=tok_today_out,
        tok_today_krw=tok_today_krw,
        price_in=GPT_PRICE_INPUT_USD,
        price_out=GPT_PRICE_OUTPUT_USD,
        usd_krw=USD_TO_KRW,
        env_stats=env_stats,
        env_total=env_total,
        env_chart_style=env_chart_style
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
            f"{SUPABASE_URL}/rest/v1/visit_daily_counts?select=visit_date,count&order=visit_date.desc",
            headers=SUPABASE_HEADERS, timeout=5
        )
        visit_rows = visit_res.json() if visit_res.ok else []

        daily_visits = []
        for row in visit_rows:
            date_str = str(row.get("visit_date", ""))
            if date_str:
                daily_visits.append({
                    "날짜": date_str,
                    "방문자수": int(row.get("count", 0) or 0)
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
            {"날짜": "2026-04-18", "시도": "전남광주통합특별시", "시군구": "북구", "검색구분": "조건기반", "클릭수": 3},
            {"날짜": "2026-04-18", "시도": "전남광주통합특별시", "시군구": "나주시", "검색구분": "사례기반", "클릭수": 2},
            {"날짜": "2026-04-19", "시도": "전남광주통합특별시", "시군구": "서구", "검색구분": "조건기반", "클릭수": 1}
        ]
    else:
        region_rows = fetch_all_rows(
            "region_logs?select=created_at,sido,sigungu,search_type&order=created_at.desc"
        )

        daily_region_map = defaultdict(int)
        for row in region_rows:
            created_at = str(row.get("created_at", ""))
            date_str = _kst_date_str(created_at) if created_at else ""
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

@app.route("/stats/export/all")
@app.route("/stats/export/xlsx/<path:fname>")
def export_stats_all(fname=None):
    """방문/페이지뷰/지역 통계를 시트별로 묶어 하나의 엑셀로 일괄 다운로드."""
    if os.getenv("RENDER") is None:
        total_count, today_count = 100, 5
        daily_visits = [
            {"날짜": "2026-06-04", "방문자수": 18},
            {"날짜": "2026-06-05", "방문자수": 5},
        ]
        daily_regions = [
            {"날짜": "2026-06-04", "시도": "전남광주통합특별시", "시군구": "북구", "검색구분": "조건기반", "클릭수": 3},
        ]
        pv_total, pv_today = 173, 41
        daily_pv = [{"date": "2026-06-05", "count": 41}]
        top_pages = [{"page": "기관검색", "count": 64}, {"page": "사례검색", "count": 52}]
    else:
        stats_res = requests.get(
            f"{SUPABASE_URL}/rest/v1/visit_stats?id=eq.1&select=*",
            headers=SUPABASE_HEADERS, timeout=5
        )
        stats_rows = stats_res.json() if stats_res.ok else []
        stats_row = stats_rows[0] if stats_rows else {}
        total_count = int(stats_row.get("total_count", 0))
        today_count = int(stats_row.get("today_count", 0))

        visit_res = requests.get(
            f"{SUPABASE_URL}/rest/v1/visit_daily_counts?select=visit_date,count&order=visit_date.desc",
            headers=SUPABASE_HEADERS, timeout=5
        )
        visit_rows = visit_res.json() if visit_res.ok else []
        daily_visits = [
            {"날짜": str(row.get("visit_date", "")), "방문자수": int(row.get("count", 0) or 0)}
            for row in visit_rows if row.get("visit_date")
        ]

        region_rows = fetch_all_rows(
            "region_logs?select=created_at,sido,sigungu,search_type&order=created_at.desc"
        )
        drm = defaultdict(int)
        for row in region_rows:
            ca = str(row.get("created_at", ""))
            ds = _kst_date_str(ca) if ca else ""
            sido = str(row.get("sido", "") or "")
            sigungu = str(row.get("sigungu", "") or "")
            rst = str(row.get("search_type", "") or "").strip()
            st = "조건기반" if rst == "combo" else "사례기반" if rst == "desc" else (rst or "-")
            drm[(ds, sido, sigungu, st)] += 1
        daily_regions = [
            {"날짜": k[0], "시도": k[1], "시군구": k[2], "검색구분": k[3], "클릭수": drm[k]}
            for k in sorted(drm.keys(), reverse=True)
        ]

        pv_total, pv_today, daily_pv, top_pages = _compute_pv_stats()

    summary_df = pd.DataFrame([
        {"항목": "총 방문자수", "값": total_count},
        {"항목": "오늘 방문자수", "값": today_count},
        {"항목": "총 페이지뷰", "값": pv_total},
        {"항목": "오늘 페이지뷰", "값": pv_today},
    ])
    visits_df = pd.DataFrame(daily_visits) if daily_visits else pd.DataFrame(columns=["날짜", "방문자수"])
    pv_df = pd.DataFrame(
        [{"날짜": r["date"], "페이지뷰": r["count"]} for r in daily_pv]
    ) if daily_pv else pd.DataFrame(columns=["날짜", "페이지뷰"])
    pages_df = pd.DataFrame(
        [{"페이지": r["page"], "조회수": r["count"]} for r in top_pages]
    ) if top_pages else pd.DataFrame(columns=["페이지", "조회수"])
    regions_df = pd.DataFrame(daily_regions) if daily_regions else pd.DataFrame(columns=["날짜", "시도", "시군구", "검색구분", "클릭수"])

    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        summary_df.to_excel(writer, index=False, sheet_name="요약")
        visits_df.to_excel(writer, index=False, sheet_name="일자별방문자수")
        regions_df.to_excel(writer, index=False, sheet_name="일자별지역클릭수")
        pv_df.to_excel(writer, index=False, sheet_name="일자별페이지뷰")
        pages_df.to_excel(writer, index=False, sheet_name="페이지별조회수")
    output.seek(0)

    # 파일명을 헤더에 넣지 않고(attachment만), URL 마지막 경로(케어내비_통계.xlsx)를
    # 파일명으로 쓰게 함 → PC 브라우저·모바일 브라우저·웹앱(WebView) 모두 동일하게 한글 파일명.
    resp = Response(
        output.read(),
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    resp.headers["Content-Disposition"] = "attachment"
    return resp

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
  background:#e8ecf4;
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
  box-shadow:0 10px 26px rgba(15,23,42,0.10);
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

/* === 버튼 누름 효과 B (디자인 전용) === */
button, input[type="submit"], input[type="button"], a.card, .btn, .home-btn, .home-button, .reset-btn, .home-help-btn, .home-notice-btn, .tip-btn, #fabMain, .fab-item, [class*="-btn"], [class*="-button"] { transition:transform .12s ease, box-shadow .12s ease; }
button:active, input[type="submit"]:active, input[type="button"]:active, .btn:active, .home-btn:active, .home-button:active, .reset-btn:active, .home-help-btn:active, .home-notice-btn:active, .tip-btn:active, #fabMain:active, .fab-item:active, [class*="-btn"]:active, [class*="-button"]:active { transform:scale(0.92) !important; }
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
  background:#e8ecf4;
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
  box-shadow:0 10px 26px rgba(15,23,42,0.10);
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

/* === 버튼 누름 효과 B (디자인 전용) === */
button, input[type="submit"], input[type="button"], a.card, .btn, .home-btn, .home-button, .reset-btn, .home-help-btn, .home-notice-btn, .tip-btn, #fabMain, .fab-item, [class*="-btn"], [class*="-button"] { transition:transform .12s ease, box-shadow .12s ease; }
button:active, input[type="submit"]:active, input[type="button"]:active, .btn:active, .home-btn:active, .home-button:active, .reset-btn:active, .home-help-btn:active, .home-notice-btn:active, .tip-btn:active, #fabMain:active, .fab-item:active, [class*="-btn"]:active, [class*="-button"]:active { transform:scale(0.92) !important; }
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
          {{ post["created_at"] | kst }}
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
  background:#e8ecf4;
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
  box-shadow:0 10px 26px rgba(15,23,42,0.10);
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

/* === 버튼 누름 효과 B (디자인 전용) === */
button, input[type="submit"], input[type="button"], a.card, .btn, .home-btn, .home-button, .reset-btn, .home-help-btn, .home-notice-btn, .tip-btn, #fabMain, .fab-item, [class*="-btn"], [class*="-button"] { transition:transform .12s ease, box-shadow .12s ease; }
button:active, input[type="submit"]:active, input[type="button"]:active, .btn:active, .home-btn:active, .home-button:active, .reset-btn:active, .home-help-btn:active, .home-notice-btn:active, .tip-btn:active, #fabMain:active, .fab-item:active, [class*="-btn"]:active, [class*="-button"]:active { transform:scale(0.92) !important; }
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

      <button type="submit">의견보내기</button>
      <div style="text-align:center;margin-top:14px;">
        <a href="/board/mine" style="font-size:12px;color:#9ca3af;text-decoration:underline;margin-right:12px;">내가 보낸 의견</a>
        <a href="/privacy" style="font-size:12px;color:#9ca3af;text-decoration:underline;">개인정보 처리방침</a>
      </div>
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
<title>의견 전송 완료</title>
<style>
*{ box-sizing:border-box; }
body{
  margin:0;
  min-height:100vh;
  min-height:100dvh;
  background:#e8ecf4;
  font-family:'Pretendard',sans-serif;
  color:#111827;
  display:flex;
  align-items:center;
  justify-content:center;
  padding:24px 16px;
}
.card{
  width:100%;
  max-width:420px;
  background:#fff;
  border-radius:22px;
  padding:36px 24px 26px;
  text-align:center;
  box-shadow:0 16px 38px rgba(15,23,42,0.12);
}
.check{
  width:64px;
  height:64px;
  margin:0 auto 18px;
  border-radius:50%;
  background:#eff6ff;
  display:flex;
  align-items:center;
  justify-content:center;
}
.check svg{ width:32px; height:32px; }
.title{
  font-size:21px;
  font-weight:800;
  letter-spacing:-0.4px;
  margin:0 0 8px;
}
.sub{
  font-size:14px;
  color:#6b7280;
  line-height:1.6;
  margin:0;
  word-break:keep-all;
}
.notice{
  margin:22px 0 0;
  padding:14px 16px;
  border-radius:14px;
  background:#f8fafc;
  border:1px solid #e5e7eb;
  font-size:13px;
  color:#4b5563;
  line-height:1.6;
  text-align:left;
  word-break:keep-all;
}
.notice b{ color:#111827; }
.btns{
  display:flex;
  flex-direction:column;
  gap:8px;
  margin-top:22px;
}
.btn{
  display:flex;
  align-items:center;
  justify-content:center;
  height:48px;
  border-radius:12px;
  font-size:15px;
  font-weight:700;
  text-decoration:none;
}
.btn-primary{
  background:linear-gradient(135deg,#3b82f6,#2563eb);
  color:#fff;
  box-shadow:0 6px 16px rgba(37,99,235,0.25);
}
.btn-secondary{
  background:#fff;
  border:1px solid #e5e7eb;
  color:#6b7280;
}

/* === 버튼 누름 효과 B (디자인 전용) === */
button, input[type="submit"], input[type="button"], a.card, .btn, .home-btn, .home-button, .reset-btn, .home-help-btn, .home-notice-btn, .tip-btn, #fabMain, .fab-item, [class*="-btn"], [class*="-button"] { transition:transform .12s ease, box-shadow .12s ease; }
button:active, input[type="submit"]:active, input[type="button"]:active, .btn:active, .home-btn:active, .home-button:active, .reset-btn:active, .home-help-btn:active, .home-notice-btn:active, .tip-btn:active, #fabMain:active, .fab-item:active, [class*="-btn"]:active, [class*="-button"]:active { transform:scale(0.96) !important; }
</style>
</head>
<body>
  <div class="card">
    <div class="check">
      <svg viewBox="0 0 24 24" fill="none" stroke="#2563eb" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg>
    </div>
    <h1 class="title">의견을 보냈습니다</h1>
    <p class="sub">보내주신 내용은 관리자만 확인합니다.<br>소중한 의견 감사합니다.</p>

    {% if can_delete %}
    <div class="notice">
      브라우저를 닫기 전까지 <b>내가 보낸 의견</b>에서 삭제할 수 있습니다.
    </div>
    {% endif %}

    <div class="btns">
      <a href="/home" class="btn btn-primary">홈으로</a>
      {% if can_delete %}
      <a href="/board/mine" class="btn btn-secondary">내가 보낸 의견</a>
      {% endif %}
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
  background:#e8ecf4;
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
.card{
  background:#fff;
  border-radius:18px;
  padding:22px;
  box-shadow:0 10px 26px rgba(15,23,42,0.10);
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


/* === 버튼 누름 효과 B (디자인 전용) === */
button, input[type="submit"], input[type="button"], a.card, .btn, .home-btn, .home-button, .reset-btn, .home-help-btn, .home-notice-btn, .tip-btn, #fabMain, .fab-item, [class*="-btn"], [class*="-button"] { transition:transform .12s ease, box-shadow .12s ease; }
button:active, input[type="submit"]:active, input[type="button"]:active, .btn:active, .home-btn:active, .home-button:active, .reset-btn:active, .home-help-btn:active, .home-notice-btn:active, .tip-btn:active, #fabMain:active, .fab-item:active, [class*="-btn"]:active, [class*="-button"]:active { transform:scale(0.92) !important; }
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
      {{ post["created_at"] | kst }}
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
  background:#e8ecf4;
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
.card{
  background:#fff;
  border-radius:16px;
  padding:18px;
  margin-bottom:14px;
  box-shadow:0 10px 26px rgba(15,23,42,0.10);
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

/* === 버튼 누름 효과 B (디자인 전용) === */
button, input[type="submit"], input[type="button"], a.card, .btn, .home-btn, .home-button, .reset-btn, .home-help-btn, .home-notice-btn, .tip-btn, #fabMain, .fab-item, [class*="-btn"], [class*="-button"] { transition:transform .12s ease, box-shadow .12s ease; }
button:active, input[type="submit"]:active, input[type="button"]:active, .btn:active, .home-btn:active, .home-button:active, .reset-btn:active, .home-help-btn:active, .home-notice-btn:active, .tip-btn:active, #fabMain:active, .fab-item:active, [class*="-btn"]:active, [class*="-button"]:active { transform:scale(0.92) !important; }
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
        {{ post["created_at"] | kst }}
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


PRIVACY_HTML = """
<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>개인정보 처리방침</title>
<style>
  body{font-family:-apple-system,BlinkMacSystemFont,'Malgun Gothic',sans-serif;background:#f1f5f9;color:#1f2937;margin:0;padding:20px;line-height:1.55;}
  .wrap{max-width:760px;margin:0 auto;background:#fff;border-radius:16px;padding:24px 20px;box-shadow:0 2px 12px rgba(0,0,0,0.05);}
  h1{font-size:22px;margin:0 0 6px;}
  .updated{color:#94a3b8;font-size:13px;margin-bottom:18px;}
  h2{font-size:16px;margin:20px 0 6px;color:#111827;}
  p{font-size:14px;color:#374151;margin:6px 0;}
  li{font-size:14px;color:#374151;margin:3px 0;}
  ul{padding-left:18px;margin:6px 0;}
  .notice{background:#fff7ed;border:1px solid #fed7aa;border-radius:12px;padding:10px 12px;font-size:13px;color:#9a3412;margin:10px 0;}
  a.back{display:inline-block;margin-top:24px;padding:10px 18px;background:#2563eb;color:#fff;border-radius:10px;text-decoration:none;font-size:14px;}
  .table-scroll{width:100%;overflow-x:auto;-webkit-overflow-scrolling:touch;margin:8px 0;}
  table{width:100%;min-width:720px;border-collapse:collapse;margin:0;font-size:12px;}
  th,td{border:1px solid #e5e7eb;padding:7px 8px;text-align:left;vertical-align:top;word-break:keep-all;}
  th{background:#f8fafc;}
  @media (max-width:480px){
    body{padding:12px;}
    .wrap{padding:20px 14px;}
    .table-scroll{margin:8px 0 10px 0;padding-bottom:4px;}
    table{font-size:11.5px;min-width:760px;}
  }
</style>
</head>
<body>
<div class="wrap">
  <h1>개인정보 처리방침</h1>
  <div class="updated">시행일: 2026년 10월 20일</div>

  <p>케어내비(이하 "서비스")는 「개인정보 보호법」을 준수하며, 이용자의 개인정보를 다음과 같이 처리합니다.</p>

  <div class="notice">
    본 서비스는 업무 참고용 서비스입니다. 이름, 주민등록번호, 연락처, 상세주소, 진단서·처방전 원본 등 직접 식별 가능한 개인정보나 민감정보는 입력 또는 업로드하지 않도록 주의해 주세요.
  </div>

  <h2>1. 처리하는 개인정보 항목 및 목적</h2>
  <div class="table-scroll">
  <table>
    <tr><th>기능</th><th>처리 항목</th><th>이용 목적</th><th>보유기간</th></tr>
    <tr><td>의견보내기</td><td>작성자, 회신연락처, 제목·문의내용</td><td>오류제보·의견 접수 및 회신</td><td>접수일로부터 1년</td></tr>
    <tr><td>사례별 AI 추천</td><td>이용자가 입력한 사례 내용</td><td>통합돌봄 서비스 추천 결과 생성</td><td>서버 DB에 저장하지 않음. 처리 과정에서 일시 이용</td></tr>
    <tr><td>이미지 OCR</td><td>이용자가 업로드한 이미지 및 이미지에서 추출된 텍스트</td><td>사진 속 사례 내용 추출</td><td>서버 DB에 저장하지 않음. 처리 과정에서 일시 이용</td></tr>
    <tr><td>알약 확인</td><td>이용자가 촬영한 알약 사진 및 사진에서 인식된 각인·색·모양 정보</td><td>알약 특징 인식 및 식약처 낱알식별 정보와 대조</td><td>서버 DB에 저장하지 않음. 처리 과정에서 일시 이용</td></tr>
    <tr><td>조사서식 작성·PDF 발송</td><td>이용자가 입력한 조사 내용, 수신 이메일 주소, 생성된 PDF</td><td>조사서식 PDF 생성 및 이메일 발송</td><td>서버 DB에 저장하지 않음. 메일 발송 과정에서 일시 이용</td></tr>
  </table>
  </div>

  <h2>2. 통계 정보</h2>
  <p>서비스는 운영 통계를 위해 아래 정보를 처리합니다. IP, 검색어, User-Agent 원문은 저장하지 않으며 특정 개인을 식별하지 않는 형태로 집계합니다.</p>
  <ul>
    <li>방문자수, 페이지별 조회수, 지역별 클릭수, AI 토큰 사용량</li>
    <li>접속환경 분류값: PC, Android, iOS, 기타</li>
  </ul>

  <h2>3. 처리위탁 및 국외 처리</h2>
  <p>서비스 운영을 위해 아래 외부 서비스를 이용하며, 일부 정보는 국외에서 처리될 수 있습니다.</p>
  <div class="table-scroll">
  <table>
    <tr>
      <th>수탁자</th>
      <th>처리 국가</th>
      <th>처리 항목</th>
      <th>처리 목적</th>
      <th>보유기간</th>
    </tr>
    <tr>
      <td>Supabase</td>
      <td>일본 등 서비스 제공 리전</td>
      <td>의견보내기 작성자, 제목, 내용, 회신연락처, 운영 통계</td>
      <td>의견 접수 관리 및 운영 통계 저장</td>
      <td>의견보내기 자료는 접수일로부터 1년, 운영 통계는 개인을 식별할 수 없는 형태로 보관</td>
    </tr>
    <tr>
      <td>OpenAI</td>
      <td>미국 등</td>
      <td>사용자가 입력한 사례 내용, OCR 이미지, 알약 사진</td>
      <td>AI 추천 결과 생성, 이미지 텍스트 추출 및 알약 특징 인식</td>
      <td>OpenAI API 정책 및 계약 조건에 따름</td>
    </tr>
    <tr>
      <td>Google/Gmail SMTP</td>
      <td>미국 등</td>
      <td>수신 이메일 주소, 생성된 PDF 첨부파일</td>
      <td>조사서식 PDF 이메일 발송</td>
      <td>메일 발송 처리 과정에서 이용되며, 발송 메일함 또는 수신자 메일함에 보관될 수 있음</td>
    </tr>
  </table>
  </div>

  <h2>4. 보유 및 이용기간</h2>
  <ul>
    <li>의견보내기 접수 내용 및 회신연락처: 접수일로부터 1년</li>
    <li>AI 추천 입력 내용, OCR 이미지, 알약 사진, 조사서식 PDF: 서버 DB에 저장하지 않고 요청 처리 과정에서만 일시 이용</li>
    <li>운영 통계: 개인을 식별할 수 없는 집계 정보로 보관</li>
  </ul>

  <h2>5. 파기 방법</h2>
  <p>보유기간이 지난 개인정보는 복구할 수 없도록 삭제합니다. 전자파일은 재생할 수 없는 방법으로 삭제합니다.</p>

  <h2>6. 정보주체의 권리</h2>
  <p>이용자는 본인의 개인정보에 대한 열람, 정정, 삭제, 처리정지를 요청할 수 있습니다. 아래 담당부서로 요청할 수 있습니다.</p>
  <p>의견보내기로 등록한 글은 작성한 브라우저를 닫기 전까지 '내가 보낸 의견' 화면에서 직접 삭제할 수 있으며, 삭제 즉시 영구 삭제됩니다.</p>

  <h2>7. 안전성 확보조치</h2>
  <ul>
    <li>관리자 페이지 접근 제한</li>
    <li>운영 로그 최소화 및 검색어·토큰·추천 결과 로그 미저장</li>
    <li>IP 및 User-Agent 원문 미저장</li>
    <li>외부 API 키 및 비밀번호의 환경변수 관리</li>
  </ul>

  <h2>8. 자동화된 추천에 관한 안내</h2>
  <p>AI 추천 결과는 업무 참고용이며, 최종 판단과 안내는 담당자가 관련 지침과 현장 상황을 확인하여 결정해야 합니다.</p>

  <h2>9. 개인정보 보호 담당부서</h2>
  <p>국민건강보험공단 광주전라제주지역본부 통합돌봄부<span style="font-size:12px;">(TF)</span></p>

  <a class="back" href="javascript:history.back()">돌아가기</a>
</div>
</body>
</html>
"""

@app.route("/privacy")
def privacy():
    return render_template_string(PRIVACY_HTML)

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

        saved = False
        if title and content and org_type:
            if os.getenv("RENDER") is not None:
                try:
                    res = requests.post(
                        f"{SUPABASE_URL}/rest/v1/board_posts",
                        headers={**SUPABASE_HEADERS, "Prefer": "return=representation"},
                        json={
                            "writer": writer,
                            "title": title,
                            "content": content,
                            "org_type": org_type,
                            "reply_contact": reply_contact
                        },
                        timeout=5
                    )
                    rows = res.json() if res.ok else []
                    if rows and rows[0].get("id") is not None:
                        # 이 브라우저 세션에서 작성한 글만 본인이 삭제할 수 있도록 id를 세션에 기록
                        mine = [int(i) for i in session.get("my_board_ids", [])]
                        session["my_board_ids"] = (mine + [int(rows[0]["id"])])[-20:]
                        saved = True
                except Exception as e:
                    app.logger.exception(e)

        return render_template_string(BOARD_SUCCESS_HTML, can_delete=saved)

    return render_template_string(BOARD_WRITE_HTML)

@app.route("/board/view/<int:post_id>")
def board_view(post_id):
    return redirect(url_for("board"))

@app.route("/board/admin")
def board_admin():
    cleanup_old_board_posts()

    posts = []

    if os.getenv("RENDER") is not None:
        res = requests.get(
            f"{SUPABASE_URL}/rest/v1/board_posts?select=*&is_deleted=eq.false&order=created_at.desc",
            headers=SUPABASE_HEADERS, timeout=5
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
            headers=SUPABASE_HEADERS, timeout=5
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
            },
            timeout=5
        )

    return redirect(url_for("board_admin"))

# =========================
# 내가 보낸 의견 (작성자 본인 삭제)
# - 같은 브라우저 세션에서 작성한 글만 목록에 보이고 삭제 가능
# - 삭제 시 DB에서 즉시 영구 삭제 (회신연락처 포함)
# =========================
@app.route("/board/mine")
def board_mine():
    ids = [int(i) for i in session.get("my_board_ids", [])]
    posts = []
    if ids and os.getenv("RENDER") is not None:
        try:
            res = requests.get(
                f"{SUPABASE_URL}/rest/v1/board_posts?select=id,title,content,created_at"
                f"&id=in.({','.join(map(str, ids))})&is_deleted=eq.false&order=created_at.desc",
                headers=SUPABASE_HEADERS, timeout=5
            )
            posts = res.json() if res.ok else []
        except Exception as e:
            app.logger.exception(e)
            posts = []
        # 이미 지워진 글(관리자 삭제·1년 자동삭제)은 세션에서도 정리
        alive = {int(p["id"]) for p in posts}
        session["my_board_ids"] = [i for i in ids if i in alive]
    return render_template_string(
        BOARD_MINE_HTML, posts=posts, msg=request.args.get("msg", ""),
        deleted=(request.args.get("deleted") == "1")
    )

@app.route("/board/mine/delete/<int:post_id>", methods=["POST"])
def board_mine_delete(post_id):
    mine = [int(i) for i in session.get("my_board_ids", [])]
    if post_id not in mine:
        return redirect(url_for("board_mine", msg="삭제할 수 없는 글입니다."))
    if os.getenv("RENDER") is not None:
        try:
            res = requests.delete(
                f"{SUPABASE_URL}/rest/v1/board_posts?id=eq.{post_id}",
                headers=SUPABASE_HEADERS, timeout=5
            )
            if not res.ok:
                return redirect(url_for("board_mine", msg="삭제 중 오류가 발생했습니다."))
        except Exception as e:
            app.logger.exception(e)
            return redirect(url_for("board_mine", msg="삭제 중 오류가 발생했습니다."))
    session["my_board_ids"] = [i for i in mine if i != post_id]
    return redirect(url_for("board_mine", msg="의견이 삭제되었습니다.", deleted=1))

BOARD_MINE_HTML = """
<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>내가 보낸 의견</title>
<style>
*{ box-sizing:border-box; }
body{
  margin:0;
  min-height:100vh;
  min-height:100dvh;
  background:#e8ecf4;
  font-family:'Pretendard',sans-serif;
  color:#111827;
  display:flex;
  align-items:center;
  justify-content:center;
  padding:24px 16px;
}
.card{
  width:100%;
  max-width:420px;
  background:#fff;
  border-radius:22px;
  padding:36px 24px 26px;
  text-align:center;
  box-shadow:0 16px 38px rgba(15,23,42,0.12);
}
.icon{
  width:64px;
  height:64px;
  margin:0 auto 18px;
  border-radius:50%;
  background:#eff6ff;
  display:flex;
  align-items:center;
  justify-content:center;
}
.icon.gray{ background:#f3f4f6; }
.icon svg{ width:30px; height:30px; }
.title{
  font-size:21px;
  font-weight:800;
  letter-spacing:-0.4px;
  margin:0 0 8px;
}
.sub{
  font-size:14px;
  color:#6b7280;
  line-height:1.6;
  margin:0;
  word-break:keep-all;
}
.msg{
  margin:18px 0 0;
  padding:12px 14px;
  border-radius:12px;
  font-size:13px;
  font-weight:700;
  line-height:1.5;
  word-break:keep-all;
}
.msg.ok{ background:#eff6ff; color:#1d4ed8; }
.msg.err{ background:#fef2f2; color:#b91c1c; }
.list{
  margin:22px 0 0;
  display:flex;
  flex-direction:column;
  gap:10px;
  text-align:left;
}
.post{
  padding:14px 16px;
  border-radius:14px;
  background:#f8fafc;
  border:1px solid #e5e7eb;
}
.post-head{
  display:flex;
  justify-content:space-between;
  align-items:flex-start;
  gap:10px;
}
.post-title{
  font-size:15px;
  font-weight:800;
  line-height:1.4;
  word-break:keep-all;
  overflow-wrap:anywhere;
}
.post-meta{ font-size:12px; color:#9ca3af; margin-top:3px; }
.post-content{
  margin-top:8px;
  font-size:13px;
  color:#4b5563;
  line-height:1.6;
  white-space:pre-wrap;
  word-break:keep-all;
  overflow-wrap:anywhere;
  display:-webkit-box;
  -webkit-line-clamp:3;
  -webkit-box-orient:vertical;
  overflow:hidden;
}
.post form{ margin:0; flex:none; }
.del-btn{
  height:30px;
  padding:0 12px;
  border:none;
  border-radius:999px;
  background:#fee2e2;
  color:#b91c1c;
  font-size:12.5px;
  font-weight:800;
  font-family:inherit;
  cursor:pointer;
}
.btns{
  display:flex;
  flex-direction:column;
  gap:8px;
  margin-top:22px;
}
.btn{
  display:flex;
  align-items:center;
  justify-content:center;
  height:48px;
  border-radius:12px;
  font-size:15px;
  font-weight:700;
  text-decoration:none;
}
.btn-primary{
  background:linear-gradient(135deg,#3b82f6,#2563eb);
  color:#fff;
  box-shadow:0 6px 16px rgba(37,99,235,0.25);
}
.btn-secondary{
  background:#fff;
  border:1px solid #e5e7eb;
  color:#6b7280;
}

/* === 버튼 누름 효과 B (디자인 전용) === */
button, input[type="submit"], input[type="button"], a.card, .btn, .home-btn, .home-button, .reset-btn, .home-help-btn, .home-notice-btn, .tip-btn, #fabMain, .fab-item, [class*="-btn"], [class*="-button"] { transition:transform .12s ease, box-shadow .12s ease; }
button:active, input[type="submit"]:active, input[type="button"]:active, .btn:active, .home-btn:active, .home-button:active, .reset-btn:active, .home-help-btn:active, .home-notice-btn:active, .tip-btn:active, #fabMain:active, .fab-item:active, [class*="-btn"]:active, [class*="-button"]:active { transform:scale(0.96) !important; }
</style>
</head>
<body>
  <div class="card">
    {% if deleted and not posts %}
      <div class="icon">
        <svg viewBox="0 0 24 24" fill="none" stroke="#2563eb" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg>
      </div>
      <h1 class="title">의견을 삭제했습니다</h1>
      <p class="sub">보내신 의견이 완전히 삭제되었습니다.<br>삭제된 내용은 복구할 수 없습니다.</p>
    {% elif posts %}
      <div class="icon">
        <svg viewBox="0 0 24 24" fill="none" stroke="#2563eb" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 5h16v11H8l-4 4z"/><path d="M8 9.5h8M8 12.5h5"/></svg>
      </div>
      <h1 class="title">내가 보낸 의견</h1>
      <p class="sub">이 브라우저에서 보낸 의견만 표시됩니다.<br>삭제하면 바로 영구 삭제됩니다.</p>
      {% if msg %}<div class="msg {{ 'ok' if deleted else 'err' }}">{{ msg }}</div>{% endif %}
      <div class="list">
        {% for p in posts %}
        <div class="post">
          <div class="post-head">
            <div>
              <div class="post-title">{{ p["title"] }}</div>
              <div class="post-meta">{{ p["created_at"] | kst }}</div>
            </div>
            <form method="post" action="/board/mine/delete/{{ p['id'] }}" onsubmit="return confirm('이 의견을 삭제할까요?\n삭제하면 복구할 수 없습니다.');">
              <button type="submit" class="del-btn">삭제</button>
            </form>
          </div>
          <div class="post-content">{{ p["content"] }}</div>
        </div>
        {% endfor %}
      </div>
    {% else %}
      <div class="icon gray">
        <svg viewBox="0 0 24 24" fill="none" stroke="#9ca3af" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 5h16v11H8l-4 4z"/></svg>
      </div>
      <h1 class="title">삭제할 의견이 없습니다</h1>
      <p class="sub">이 브라우저에서 보낸 의견만 삭제할 수 있습니다.<br>브라우저를 닫았거나 다른 기기에서 보낸 의견은 표시되지 않습니다.</p>
      {% if msg %}<div class="msg err">{{ msg }}</div>{% endif %}
    {% endif %}

    <div class="btns">
      <a href="/home" class="btn btn-primary">홈으로</a>
      <a href="/board/write" class="btn btn-secondary">의견보내기</a>
    </div>
  </div>
</body>
</html>
"""

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
body{ margin:0; background:#e8ecf4; font-family:'Pretendard',sans-serif; color:#111827; }
.container{ max-width:640px; margin:0 auto; padding:24px 16px 40px 16px; }
.top-bar{ display:flex; justify-content:space-between; align-items:center; margin-bottom:16px; gap:10px; }
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
.btn-edit{ background:#dbeafe; color:#1e40af; }
.btn-save{ background:#2563eb; color:#fff; }
.btn-cancel{ background:#f3f4f6; color:#6b7280; }
.btn-pin{ background:#fee2e2; color:#b91c1c; }
.btn-unpin{ background:#f3f4f6; color:#6b7280; }
.btn-top{ background:#fef3c7; color:#92400e; }
.pin-badge{ display:inline-block; font-size:11px; font-weight:800; color:#b91c1c; background:#fee2e2; border-radius:6px; padding:2px 8px; margin-bottom:6px; }
.card.pinned{ border:1.5px solid #fecaca; background:#fffbeb; }
.write-card label.pin-check, .edit-area label.pin-check{ display:flex; align-items:center; gap:8px; margin-top:12px; font-size:13px; font-weight:700; }
.write-card label.pin-check input, .edit-area label.pin-check input{ width:auto; margin:0; flex:none; }
.edit-area{ margin-top:10px; }
.edit-area label{ display:block; margin-top:10px; font-size:13px; font-weight:700; }
.edit-area input,.edit-area textarea{ width:100%; box-sizing:border-box; margin-top:5px; border:1px solid #d1d5db; border-radius:10px; padding:10px 12px; font-size:14px; font-family:inherit; }
.edit-area textarea{ min-height:100px; resize:vertical; line-height:1.6; }
.write-card{ background:#fff; border-radius:16px; padding:22px; box-shadow:0 10px 26px rgba(15,23,42,0.10); margin-bottom:20px; }
.write-card h3{ margin:0 0 14px 0; font-size:16px; font-weight:800; }
.write-card label{ display:block; margin-top:10px; font-size:13px; font-weight:700; }
.write-card input,.write-card textarea{ width:100%; box-sizing:border-box; margin-top:5px; border:1px solid #d1d5db; border-radius:10px; padding:10px 12px; font-size:14px; font-family:inherit; }
.write-card textarea{ min-height:100px; resize:vertical; line-height:1.6; }
.write-card button{ margin-top:14px; width:100%; height:42px; border:none; border-radius:10px; background:#2563eb; color:#fff; font-size:14px; font-weight:700; cursor:pointer; }
.empty{ background:#fff; border-radius:16px; padding:22px; color:#9ca3af; text-align:center; font-size:13px; }

/* === 버튼 누름 효과 B (디자인 전용) === */
button, input[type="submit"], input[type="button"], a.card, .btn, .home-btn, .home-button, .reset-btn, .home-help-btn, .home-notice-btn, .tip-btn, #fabMain, .fab-item, [class*="-btn"], [class*="-button"] { transition:transform .12s ease, box-shadow .12s ease; }
button:active, input[type="submit"]:active, input[type="button"]:active, .btn:active, .home-btn:active, .home-button:active, .reset-btn:active, .home-help-btn:active, .home-notice-btn:active, .tip-btn:active, #fabMain:active, .fab-item:active, [class*="-btn"]:active, [class*="-button"]:active { transform:scale(0.92) !important; }
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
      <label class="pin-check"><input type="checkbox" name="is_pinned" value="1"> 필독 공지로 등록 (항상 맨 위 고정)</label>
      <button type="submit">등록하기</button>
    </form>
  </div>
  {% if notices %}
    {% for n in notices %}
    <div class="card{% if n.is_pinned %} pinned{% endif %}">
      <div class="meta">{{ n.created_datetime }}</div>

      <div class="view-area" id="view-{{ n.id }}">
        {% if n.is_pinned %}<div class="pin-badge">필독</div>{% endif %}
        <div class="title">{{ n.title }}</div>
        <div class="content">{{ n.content }}</div>
        <div class="btn-row">
          {% if n.is_pinned %}
          <form method="post" action="/notice/admin/bump/{{ n.id }}">
            <button type="submit" class="btn-sm btn-top">↑ 맨 위로</button>
          </form>
          <form method="post" action="/notice/admin/pin/{{ n.id }}">
            <button type="submit" class="btn-sm btn-unpin">고정해제</button>
          </form>
          {% else %}
          <form method="post" action="/notice/admin/pin/{{ n.id }}">
            <button type="submit" class="btn-sm btn-pin">필독 고정</button>
          </form>
          {% endif %}
          <button type="button" class="btn-sm btn-edit" onclick="toggleEdit({{ n.id }})">수정</button>
          <form method="post" action="/notice/admin/delete/{{ n.id }}" onsubmit="return confirm('삭제할까요?');">
            <button type="submit" class="btn-sm btn-del">삭제</button>
          </form>
        </div>
      </div>

      <form class="edit-area" id="edit-{{ n.id }}" method="post" action="/notice/admin/edit/{{ n.id }}" style="display:none;">
        <label>제목</label>
        <input type="text" name="title" value="{{ n.title }}" required>
        <label>내용</label>
        <textarea name="content" required>{{ n.content }}</textarea>
        <label class="pin-check"><input type="checkbox" name="is_pinned" value="1" {% if n.is_pinned %}checked{% endif %}> 필독 공지 (항상 맨 위 고정)</label>
        <div class="btn-row">
          <button type="submit" class="btn-sm btn-save">저장</button>
          <button type="button" class="btn-sm btn-cancel" onclick="toggleEdit({{ n.id }})">취소</button>
        </div>
      </form>
    </div>
    {% endfor %}
  {% else %}
    <div class="empty">등록된 공지가 없습니다.</div>
  {% endif %}
</div>
<script>
function toggleEdit(id){
  var v = document.getElementById('view-' + id);
  var e = document.getElementById('edit-' + id);
  if(!v || !e) return;
  var editing = (e.style.display === 'block');
  v.style.display = editing ? 'block' : 'none';
  e.style.display = editing ? 'none' : 'block';
}
</script>
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
            f"{SUPABASE_URL}/rest/v1/notices?select=*&order=is_pinned.desc.nullslast,pinned_at.desc.nullslast,created_at.desc",
            headers=SUPABASE_HEADERS, timeout=5
        )
        if res.ok:
            notices = res.json()
    else:
        notices = [{"id":1,"title":"테스트 공지","content":"로컬 테스트","created_at":"2026-06-04T00:00:00","is_active":True,"is_pinned":False}]
    notices = clean_notices_for_template(notices)
    return render_template_string(NOTICE_ADMIN_HTML, notices=notices)

@app.route("/notice/admin/write", methods=["POST"])
def notice_admin_write():
    if not session.get("is_admin"):
        return redirect(url_for("admin_login"))
    title = (request.form.get("title","") or "").strip()
    content = (request.form.get("content","") or "").strip()
    is_pinned = (request.form.get("is_pinned") == "1")
    if title and content and os.getenv("RENDER") is not None:
        try:
            now = datetime.datetime.now(ZoneInfo("Asia/Seoul")).isoformat()
            new_notice = {"title": title, "content": content, "is_active": True, "is_pinned": is_pinned, "created_at": now}
            if is_pinned:
                new_notice["pinned_at"] = now
            res = requests.post(
                f"{SUPABASE_URL}/rest/v1/notices",
                headers=SUPABASE_HEADERS,
                json=new_notice, timeout=5
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
            headers=SUPABASE_HEADERS, timeout=5
        )
        if res.ok and res.json():
            current = res.json()[0].get("is_active", True)
            requests.patch(
                f"{SUPABASE_URL}/rest/v1/notices?id=eq.{notice_id}",
                headers=SUPABASE_HEADERS,
                json={"is_active": not current},
                timeout=5
            )
    return redirect(url_for("notice_admin"))

@app.route("/notice/admin/pin/<int:notice_id>", methods=["POST"])
def notice_admin_pin(notice_id):
    if not session.get("is_admin"):
        return redirect(url_for("admin_login"))
    if os.getenv("RENDER") is not None:
        res = requests.get(
            f"{SUPABASE_URL}/rest/v1/notices?id=eq.{notice_id}&select=is_pinned",
            headers=SUPABASE_HEADERS, timeout=5
        )
        if res.ok and res.json():
            current = res.json()[0].get("is_pinned", False)
            new_pinned = not current
            payload = {"is_pinned": new_pinned}
            if new_pinned:
                payload["pinned_at"] = datetime.datetime.now(ZoneInfo("Asia/Seoul")).isoformat()
            requests.patch(
                f"{SUPABASE_URL}/rest/v1/notices?id=eq.{notice_id}",
                headers=SUPABASE_HEADERS,
                json=payload, timeout=5
            )
    return redirect(url_for("notice_admin"))

@app.route("/notice/admin/bump/<int:notice_id>", methods=["POST"])
def notice_admin_bump(notice_id):
    if not session.get("is_admin"):
        return redirect(url_for("admin_login"))
    if os.getenv("RENDER") is not None:
        now = datetime.datetime.now(ZoneInfo("Asia/Seoul")).isoformat()
        requests.patch(
            f"{SUPABASE_URL}/rest/v1/notices?id=eq.{notice_id}",
            headers=SUPABASE_HEADERS,
            json={"is_pinned": True, "pinned_at": now},
            timeout=5
        )
    return redirect(url_for("notice_admin"))

@app.route("/notice/admin/delete/<int:notice_id>", methods=["POST"])
def notice_admin_delete(notice_id):
    if not session.get("is_admin"):
        return redirect(url_for("admin_login"))
    if os.getenv("RENDER") is not None:
        requests.delete(
            f"{SUPABASE_URL}/rest/v1/notices?id=eq.{notice_id}",
            headers=SUPABASE_HEADERS, timeout=5
        )
    return redirect(url_for("notice_admin"))


@app.route("/notice/admin/edit/<int:notice_id>", methods=["POST"])
def notice_admin_edit(notice_id):
    if not session.get("is_admin"):
        return redirect(url_for("admin_login"))
    title = (request.form.get("title","") or "").strip()
    content = (request.form.get("content","") or "").strip()
    is_pinned = (request.form.get("is_pinned") == "1")
    if title and content and os.getenv("RENDER") is not None:
        try:
            res = requests.patch(
                f"{SUPABASE_URL}/rest/v1/notices?id=eq.{notice_id}",
                headers=SUPABASE_HEADERS,
                json={"title": title, "content": content, "is_pinned": is_pinned},
                timeout=5
            )
            if not res.ok:
                app.logger.error("notice edit failed: %s %s", res.status_code, res.text)
        except Exception as e:
            app.logger.exception(e)
    return redirect(url_for("notice_admin"))


@app.route("/guide")
def guide():
    return redirect("/static/guide.pdf")

@app.route("/pv/guide", methods=["GET", "POST"])
def pv_guide():
    # 사용설명서 모달(openGuide)에서 호출 → 페이지뷰로 적재
    if os.getenv("RENDER") is not None and (session.get("logged_in") or session.get("is_admin")):
        try:
            _pv_threading.Thread(target=_pv_insert, args=("/manual",), daemon=True).start()
        except Exception:
            pass
    return ("", 204)

@app.route("/pv/dbo", methods=["GET", "POST"])
def pv_dbo():
    # 돌봄온 이미지 팝업(openDbo)을 열 때마다 호출 → 어떤 자원이든 1회로 적재 ("돌봄온")
    if os.getenv("RENDER") is not None and (session.get("logged_in") or session.get("is_admin")):
        try:
            _pv_threading.Thread(target=_pv_insert, args=("/dolbomon",), daemon=True).start()
        except Exception:
            pass
    return ("", 204)

@app.route("/pv/pill", methods=["GET", "POST"])
def pv_pill():
    # 알약 확인 팝업(openPill)을 열 때 호출 → 페이지뷰로 적재 ("알약확인")
    if os.getenv("RENDER") is not None and (session.get("logged_in") or session.get("is_admin")):
        try:
            _pv_threading.Thread(target=_pv_insert, args=("/pill",), daemon=True).start()
        except Exception:
            pass
    return ("", 204)
_GWANGJU_GU_RE = re.compile(r"^(광주)?(동구|서구|남구|북구|광산구)")


def to_map_search_address(addr: str) -> str:
    """지도(구글맵) 검색용 주소 변환.
    2026-07-01 전남광주통합특별시 출범 직후라 구글/카카오맵이 아직 새 행정구역명을
    인식하지 못해, 지도 검색을 보낼 때만 옛 행정구역명(광주광역시/전라남도)으로
    바꿔서 보낸다. 화면에 표시되는 기관주소 텍스트 자체는 건드리지 않는다."""
    addr = str(addr or "").strip()
    prefix = "전남광주통합특별시"

    if not addr.startswith(prefix):
        return addr

    rest = addr[len(prefix):].strip()
    old_sido = "광주광역시" if _GWANGJU_GU_RE.match(rest) else "전라남도"

    return f"{old_sido} {rest}".strip()


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
        "기관주소_지도용": to_map_search_address(r.get("기관주소", "")),
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

    middle_category_options = []
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
                .str.contains(program_kw, case=False, na=False, regex=False)
            ]

        if org_kw and "서비스제공기관명" in filtered.columns:
            filtered = filtered[
                filtered["서비스제공기관명"]
                .fillna("")
                .astype(str)
                .str.contains(org_kw, case=False, na=False, regex=False)
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

        # 각 지역/관리주체 안의 자원 목록을 프로그램명 기준 가나다 오름차순 정렬
        for manager_groups in results.values():
            for items in manager_groups.values():
                items.sort(key=lambda item: item["label"])

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

        # 검색 로그 적재 — 일자별 지역 클릭수 집계용 (IP 미수집, 지역/검색구분만)
        if os.getenv("RENDER"):
            _pv_threading.Thread(
                target=_region_log_insert,
                args=(sido, sigungu, "combo"),
                daemon=True
            ).start()

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
body{ background:#e8ecf4; font-family:'Pretendard',sans-serif; color:#111827; font-size:13px; }
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
.form-card{ background:#fff; border-radius:16px; padding:28px 24px; box-shadow:0 10px 26px rgba(15,23,42,0.10); overflow-x:auto; }
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
.result-card{ margin-top:18px; background:#fff; border-radius:16px; padding:22px 20px; box-shadow:0 10px 26px rgba(15,23,42,0.10); }
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

/* === 버튼 누름 효과 B (디자인 전용) === */
button, input[type="submit"], input[type="button"], a.card, .btn, .home-btn, .home-button, .reset-btn, .home-help-btn, .home-notice-btn, .tip-btn, #fabMain, .fab-item, [class*="-btn"], [class*="-button"] { transition:transform .12s ease, box-shadow .12s ease; }
button:active, input[type="submit"]:active, input[type="button"]:active, .btn:active, .home-btn:active, .home-button:active, .reset-btn:active, .home-help-btn:active, .home-notice-btn:active, .tip-btn:active, #fabMain:active, .fab-item:active, [class*="-btn"]:active, [class*="-button"]:active { transform:scale(0.92) !important; }
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
      <div style="display:flex;align-items:center;gap:6px;">
      {% if dolbomon_items %}
      <button type="button" onclick="openDboPicker()" style="height:28px;padding:0 11px;border-radius:999px;border:none;background:#93c5fd;color:#1e40af;font-size:13px;font-weight:700;letter-spacing:0.2px;cursor:pointer;display:inline-flex;align-items:center;flex-shrink:0;box-shadow:0 2px 6px rgba(37,99,235,0.3);white-space:nowrap;" aria-label="통합돌봄ON">통합돌봄ON</button>
      {% endif %}
      <button type="button" onclick="openComboInfo()" style="width:28px;height:28px;border-radius:50%;border:none;background:#93c5fd;color:#1e40af;font-size:15px;font-weight:900;cursor:pointer;display:inline-flex;align-items:center;justify-content:center;box-shadow:0 2px 6px rgba(37,99,235,0.3);flex-shrink:0;margin-right:4px;" aria-label="안내">!</button>
      </div>
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

      const addr = (d["기관주소_지도용"] || d["기관주소"] || "").trim();
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

{% if dolbomon_items %}
<!-- ===== 통합돌봄ON 선택창 (분류 선택 또는 이름 검색 → 돌봄온 팝업) ===== -->
<div id="dboPicker" class="dbo-picker">
  <div class="dbo-box">
    <div class="dbo-head">
      <div style="flex:1;min-width:0;">
        <div class="dbo-title">통합돌봄ON</div>
        <div class="dbo-sub">서비스 분류를 선택하거나 공단자원 이름으로 검색하세요.</div>
      </div>
      <button type="button" class="dbo-close" onclick="closeDboPicker()" aria-label="닫기">×</button>
    </div>
    <div class="dbo-pick-body">
      <input type="text" id="dboPickSearch" class="dbo-search-input" placeholder="공단자원 이름 검색 (예: 가족휴가제)" autocomplete="off">
      <div id="dboCatArea">
        <div class="dbo-pick-label">대분류</div>
        <div class="dbo-chips" id="dboMainChips"></div>
        <div class="dbo-pick-label" id="dboMidLabel" style="display:none;">중분류</div>
        <div class="dbo-chips" id="dboMidChips"></div>
      </div>
      <div class="dbo-pick-label" id="dboListLabel" style="display:none;">자원</div>
      <div id="dboPickList"></div>
    </div>
    <div class="dbo-foot">자료 출처: <a href="https://care1234.my.canva.site/2026v1" target="_blank" rel="noopener noreferrer">통합돌봄ON ↗</a></div>
  </div>
</div>

{{ dbo_viewer|safe }}

<script>
(function(){
  var ITEMS = {{ dolbomon_items|tojson }};
  var picker = document.getElementById("dboPicker");
  var searchInput = document.getElementById("dboPickSearch");
  var catArea = document.getElementById("dboCatArea");
  var mainBox = document.getElementById("dboMainChips");
  var midBox = document.getElementById("dboMidChips");
  var midLabel = document.getElementById("dboMidLabel");
  var listLabel = document.getElementById("dboListLabel");
  var listBox = document.getElementById("dboPickList");
  if(!picker || !ITEMS || !ITEMS.length) return;

  /* ── 검색 로직: 사례검색 연관검색어와 동일 ── */
  function norm(s){
    return Array.from(String(s || "")).filter(function(c){ return c.trim(); }).join("").toLowerCase();
  }
  function baseName(s){
    return String(s || "").split("(")[0].split("（")[0];
  }
  ITEMS.forEach(function(it){
    it._keys = [norm(baseName(it.name))].concat((it.keywords || []).map(norm))
      .filter(function(k){ return k.length >= 2; });
  });

  function uniq(arr){
    var out = [];
    arr.forEach(function(v){ if(v && out.indexOf(v) === -1) out.push(v); });
    return out;
  }
  function chip(label, onClick){
    var c = document.createElement("div");
    c.className = "dbo-chip";
    c.setAttribute("role", "button");
    c.textContent = label;
    c.addEventListener("click", function(){
      Array.prototype.forEach.call(c.parentNode.children, function(x){ x.classList.remove("active"); });
      c.classList.add("active");
      onClick();
    });
    return c;
  }
  function renderItems(items, label){
    listBox.innerHTML = "";
    listLabel.textContent = label;
    listLabel.style.display = "";
    if(!items.length){
      listBox.innerHTML = '<div class="dbo-empty" style="padding:20px 10px;">검색 결과가 없습니다.</div>';
      return;
    }
    items.forEach(function(it){
      var d = document.createElement("div");
      d.className = "dbo-item";
      d.setAttribute("role", "button");
      d.textContent = "🔍 " + it.name;
      d.addEventListener("click", function(){ if(window.openDbo) window.openDbo(it); });
      listBox.appendChild(d);
    });
  }

  function showMids(main){
    midBox.innerHTML = "";
    listBox.innerHTML = "";
    listLabel.style.display = "none";
    uniq(ITEMS.filter(function(it){ return it.main === main; }).map(function(it){ return it.middle; }))
      .forEach(function(mid){
        midBox.appendChild(chip(mid, function(){
          renderItems(ITEMS.filter(function(it){ return it.main === main && it.middle === mid; }), "자원");
        }));
      });
    midLabel.style.display = "";
  }

  function resetCategories(){
    mainBox.innerHTML = "";
    midBox.innerHTML = "";
    listBox.innerHTML = "";
    midLabel.style.display = "none";
    listLabel.style.display = "none";
    uniq(ITEMS.map(function(it){ return it.main; }))
      .forEach(function(main){ mainBox.appendChild(chip(main, function(){ showMids(main); })); });
  }

  /* 검색어 2~20자: 부분 일치. 검색 중에는 분류 선택 영역을 숨김 */
  function onSearch(){
    var q = norm(searchInput.value);
    if(q.length < 2){
      catArea.style.display = "";
      resetCategories();
      return;
    }
    catArea.style.display = "none";
    var hits = q.length > 20 ? [] : ITEMS.filter(function(it){
      return it._keys.some(function(k){ return k.indexOf(q) !== -1 || q.indexOf(k) !== -1; });
    });
    renderItems(hits, "검색 결과");
  }
  searchInput.addEventListener("input", onSearch);

  window.openDboPicker = function(){
    searchInput.value = "";
    catArea.style.display = "";
    resetCategories();
    picker.classList.add("show");
    if(window.dboSyncScroll) window.dboSyncScroll();
  };
  window.closeDboPicker = function(){
    picker.classList.remove("show");
    if(window.dboSyncScroll) window.dboSyncScroll();
  };
  picker.addEventListener("click", function(e){ if(e.target === picker) window.closeDboPicker(); });
  document.addEventListener("keydown", function(e){
    if(e.key !== "Escape" || !picker.classList.contains("show")) return;
    var viewer = document.getElementById("dboModal");
    if(viewer && viewer.classList.contains("show")) return;  /* 이미지 팝업이 열려 있으면 그것만 닫힘 */
    window.closeDboPicker();
  });
})();
</script>
{% endif %}

</body>
</html>
"""

@app.route("/ocr", methods=["POST"])
def ocr():
    # 개인정보가 포함된 이미지가 외부 OCR 처리로 넘어가지 않도록 사용자 확인을 서버에서도 검사
    if request.form.get("ocr_privacy_confirmed") != "yes":
        return jsonify({"error": "개인정보 업로드 주의사항 확인이 필요합니다."}), 400

    file = request.files.get("image")
    if not file:
        return {"text": ""}

    if not (file.mimetype or "").startswith("image/"):
        return jsonify({"error": "이미지 파일만 업로드할 수 있습니다."}), 400

    import base64
    from openai import OpenAI
    client = OpenAI()

    img_bytes = file.read()
    if len(img_bytes) > 8 * 1024 * 1024:
        return jsonify({"error": "이미지 용량은 8MB 이하만 업로드할 수 있습니다."}), 400

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

        # 토큰 사용량은 관리자 통계용 DB에만 누적하고 Render 로그에는 남기지 않음

        add_token_usage(input_tokens, output_tokens)

        return {
            "text": text,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": total_tokens
        }

    except Exception:
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

def apply_common_decline_filter(service_results, declined_keys=None):
    """AI 1회 판별값(명시적으로 거부한 서비스)을 추천 결과에 적용 (추가 AI 호출 없음)."""
    declined_keys = declined_keys or set()
    return [item for item in service_results if (
        str(item.get("대분류", "")).strip(),
        str(item.get("중분류", "")).strip(),
        str(item.get("서비스내용", "")).strip()
    ) not in declined_keys]

@app.route("/desc", methods=["GET","POST"])
def desc():
    query = (request.values.get("query", "") or "").strip()

    results = {}
    cond_display = None
    count = 0
    service_results = []
    declined_keys = set()
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
        # 개인정보(전화·주민번호·이메일) 탐지 시 GPT로 전송하지 않고 차단 + 팝업
        if _contains_pii(query):
            return render_template_string(
                DESC_HTML,
                style=BASE_STYLE,
                query=query,
                results=results,
                cond_display=cond_display,
                count=0,
                service_results=[],
                warning_msg="",
                selected_sido=selected_sido,
                selected_sigungu=selected_sigungu,
                sido_options=SIDO_OPTIONS,
                sigungu_options=SIGUNGU_MAP.get(selected_sido, []),
                pii_block=True
            )

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
                service_results = apply_common_decline_filter(
                    service_results,
                    set(tuple(k) for k in cached.get("declined_keys", [])),
                )
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
                    sido_options=SIDO_OPTIONS,
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

        if any(k in q_norm for k in ["요실금팬티"]):
            extra_aliases += ["복지용구", "요실금팬티", "구입"]
        elif any(k in q_norm for k in ["요실금", "패드"]) and "기저귀" not in q_norm:
            extra_aliases += ["복지용구", "요실금팬티", "구입"]

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

        # ---- 주거/구강/의사소통/응급/단기보호/치매조호 관련 ----
        if any(k in q_norm for k in ["주거", "주택", "거주환경", "주거환경", "집수리", "노후", "곰팡이", "해충", "악취", "쓰레기"]):
            extra_aliases += ["주거복지", "주거공간개선", "주거환경개선", "방역소독", "주거안전지원", "기타"]

        if any(k in q_norm for k in ["보일러", "에어컨", "냉방", "난방", "냉난방", "단열", "창호", "설비교체", "에너지효율", "에너지효율화"]):
            extra_aliases += ["주거복지", "주거공간개선", "기타", "집수리", "설비개선", "에너지효율화"]

        if any(k in q_norm for k in ["가스레인지", "가스렌지", "가스불", "화기", "불관리", "가스차단", "화재위험"]):
            extra_aliases += ["주거복지", "주거공간개선", "주거안전지원", "화재예방", "가스안전"]

        if "치매" in q_norm and (
            any(k in q_norm for k in ["가스레인지", "가스렌지", "가스불", "화기", "불관리", "가스차단", "화재위험", "불을켜놓", "가스잠그"])
            or ("냄비" in q_norm and any(k in q_norm for k in ["태우", "태움", "태웠", "태워", "탄다", "태운"]))
            or ("불" in q_norm and any(k in q_norm for k in ["깜빡", "잊어버", "잊고"]))
        ):
            extra_aliases += ["일상생활돌봄", "스마트돌봄", "기타", "안부확인", "응급안전", "화재감지기", "가스타이머차단기", "안전확인"]

        if any(k in q_norm for k in ["구강", "구강건조", "입마름", "입이마름", "칫솔질", "양치", "잇몸", "잇몸출혈", "치아출혈", "구내염"]):
            extra_aliases += ["구강관리", "구강위생", "칫솔질", "구강건강", "방문구강관리", "건강관리"]

        if any(k in q_norm for k in ["언어장애", "말을못", "말못", "소리를내지못", "의사소통", "고개를끄덕", "고개끄덕", "몸짓으로"]):
            extra_aliases += ["일상생활돌봄", "의사소통지원", "의사표현지원", "언어지원", "대화지원"]

        if any(k in q_norm for k in ["응급서비스", "응급안전", "응급안전안심", "응급호출", "응급벨", "위급상황", "응급상황", "안전확인필요"]):
            extra_aliases += ["일상생활돌봄", "스마트돌봄", "안부확인", "응급안전안심서비스", "응급호출", "안전확인", "기타"]

        if any(k in q_norm for k in ["단기보호", "임시보호", "잠시맡", "며칠맡", "일시보호", "가족부재", "보호자부재", "돌볼가족없", "맡아줄사람없"]):
            extra_aliases += ["요양", "단기보호", "보호", "일시보호", "가족부재", "돌봄공백"]

        if "치매" in q_norm and any(k in q_norm for k in ["기저귀", "조호물품", "소변실수", "배뇨실수"]):
            extra_aliases += ["건강관리예방", "치매전문관리", "조호물품제공", "치매조호물품", "기저귀지원"]

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
                sido_options=SIDO_OPTIONS,
                sigungu_options=SIGUNGU_OPTIONS
            )

        client = OpenAI(api_key=api_key)

        prompt = f"""
너는 통합돌봄 서비스 추천 전문가다.

[돌봄 사례 판단]
입력에 '돌봄 연결 단서'가 하나라도 있으면 추천을 진행한다.
(어르신·환자 같은 대상자 명칭이 적혀 있지 않아도 된다)
돌봄 연결 단서:
- 질환·건강상태·후유증·통증·투병 등 건강 단서
- 식사·이동·위생·주거·안전·정서 영역의 어려움이나 도움 필요
- 스마트폰·앱·디지털기기 등 IoT·스마트돌봄으로 연결되는 단서
단, "잘 한다/잘 탄다" 같은 능력·긍정 표현 자체는 단서로 보지 않는다.
(디지털기기 활용은 예외 — IoT 적합 신호로 본다)
명시적으로 적혀 있지 않아도 위 단서로부터 잠재적 돌봄 욕구를 합리적으로 추론하여 관련 서비스를 제시한다.
돌봄 연결 단서가 전혀 없는 입력이나 정치·연예·스포츠·날씨·잡담·정보나열은 {{"results": []}} 로 반환한다.

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
   - "집으로 와주길 원함", "누가 와주는", "방문해주는", "집으로 오는", "와서 ~해주는" 등 사람이 가정을 방문하여 돌봄을 제공하는 표현 → 방문요양·방문목욕·방문보건·방문진료 등 방문형 서비스를 우선 추천한다. 이때 함께 언급된 욕구(예: 건강관리)에 맞는 방문형을 선택한다.
     · 매우 중요: 이런 "사람이 방문하는" 표현을 주거복지(주거공간개선·주거안전지원·방역소독)로 해석하지 않는다. 주거복지는 문턱·손잡이·집수리·곰팡이·악취처럼 물리적 주거환경 문제가 직접 언급된 경우에만 검토한다.
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
   - "요실금팬티"가 직접 언급된 경우만 복지용구 구입(요실금팬티)을 검토한다
   - "요실금", "패드"는 기저귀와 구분하여 판단하고, 기저귀가 함께 언급되면 요실금팬티로 대체하지 않는다
   - "치매 + 소변실수/기저귀/조호물품" 맥락이면 건강관리예방-치매전문관리-조호물품제공을 우선 검토한다
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
   - 집이 지저분함, 악취, 곰팡이, 해충, 쓰레기, 노후주택 등 주거환경 문제 → 주거복지-주거공간개선-방역소독 또는 기타를 우선 검토한다
   - 보일러 교체, 에어컨 설치, 냉난방, 단열, 집수리, 주거 설비 교체 → 주거복지-주거공간개선-기타를 우선 검토한다
   - 화재·가스 안전 문제 판단 기준:
     · 가스레인지, 화기관리, 불을 켜놓음, 가스차단, 화재위험 등 화재·가스 안전 문제 → 주거복지-주거공간개선-주거안전지원(문턱제거, 안전손잡이 설치 등)을 우선 검토한다 (가스타이머차단기 등 설치도 이 서비스 범위에 포함된다)
     · 치매·인지저하로 인해 가스불을 켜놓고 잊어버리거나 냄비를 태우는 등 인지 문제가 원인인 경우, 안부·안전 상태를 확인해줄 "일상생활돌봄-스마트돌봄-안부확인"도 함께 추천한다
   - 구강건조, 칫솔질 시 출혈, 잇몸출혈, 양치 어려움 → 구강관리 관련 서비스를 우선 검토한다
   - 언어장애, 말을 하지 못함, 고개 끄덕임·몸짓으로만 의사표현 → 일상생활돌봄-의사소통지원 우선 검토
   - 응급서비스, 응급호출, 위급상황 대응, 응급안전안심서비스 필요 → 일상생활돌봄-스마트돌봄-안부확인 또는 같은 중분류의 기타 우선 검토
   - 치매 또는 돌봄 필요 대상자가 있으나 가족·보호자 부재로 일시적으로 맡아줄 곳이 필요함 → 단기보호 우선 검토
   - 몸 씻기, 비누칠, 샤워, 신체청결을 혼자 깨끗하게 수행하지 못하거나 부분도움이 필요함 → 방문목욕 또는 목욕지원 관련 서비스를 우선 검토한다
   - "무릎통증", "통증", "거동불편", "움직이기 어려움" → 재활, 기능회복, 방문보건, 이동지원 계열 고려 (단, 약 복용 언급만으로는 이 규칙 적용 금지 — 신체 불편이 명확히 언급된 경우에만 적용)
   - "요통", "허리가 자주 아픔", "허리 통증", "허리 불편" → 통증관리, 재활, 기능회복, 방문보건 계열을 우선 검토한다
   - "외로움", "말벗 필요", "혼자 지냄", "고립", "독거", "가족 왕래 없음", "보호자 부재" → 정서지원, 안부확인, 돌봄연계를 우선 검토한다
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
   - "잘 못 씹음", "씹기 어려움", "씹지 못함", "저작곤란", "삼키기 어려움", "연하곤란", "틀니가 안 맞음", "치아가 없어 못 먹음" 등 씹기·삼킴 문제 → "잘 못 먹음"과 동일하게 식사지원, 반찬지원(죽·갈아먹는 형태 포함), 영양지원 계열을 반드시 추천 대상으로 검토한다
   - 스마트폰·앱·디지털기기 언급 → IoT, 스마트돌봄, 응급안전안심서비스, AI 돌봄기기 검토
   - 입력에 "치매", "인지저하", "기억력 저하", "배회", "인지기능", "알츠하이머" 등이 직접 언급되지 않으면 치매 관련 서비스는 추천하지 않는다
   - 방문구강관리(대분류 건강관리예방) 추천 기준 (매우 중요):
     · 입력에 "구강", "양치", "칫솔질", "잇몸", "치아", "입냄새", "구취", "입마름", "구강건조", "구내염", "입안", "치주" 등 구강·치아 관련 단서가 직접 언급된 경우에만 방문구강관리를 추천한다
     · 위 구강·치아 단서가 전혀 없으면 방문구강관리는 추천하지 않는다. 특히 "뇌출혈", "거동 불편", "외출 곤란", "치과 방문 어려움" 같은 일반 질환·이동제약 표현만 있는 경우 절대 추천하지 않는다
     · 방문구강관리 서비스의 검색어/설명에 "거동 불편", "치과 방문 어려움"이 포함되어 있더라도 그것은 매칭 근거가 아니다. 사용자 입력에 실제 구강·치아 문제가 있을 때만 연결한다
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

[명시적 서비스 거부 판별 — 기존 AI 호출에서 함께 수행]
- 반드시 아래 '사용자 원문'만을 기준으로 서비스 거부/불필요를 판단한다. 검색어 보강 표현은 거부 여부 판단에 사용하지 않는다.
- '방문목욕을 원하지 않음', '식사도움을 희망하지 않음', '이용할 생각이 없음'처럼 명시적으로 거부한 서비스만 제외한다.
- '혼자 목욕하지 못함', '식사를 못함'은 수행능력 부족이지 서비스 거부가 아니다.
- '예전에는 원하지 않았지만 지금은 필요함'은 현재 거부가 아니다.
- 거부한 서비스와 독립적인 다른 서비스는 제외하지 않는다. 방문목욕 거부만으로 목욕의자·안전손잡이를 제외하지 않는다.
- 'declined_indices'는 아래 서비스 목록에서 명시적으로 거부한 서비스의 index만 담는다. 같은 중분류 전체를 명시적으로 거부했다면 그 중분류에 속하는 index를 모두 담는다. 애매하면 넣지 않는다.
- 'results'에는 declined_indices의 서비스를 추천하지 않는다.

설명문, 코드블록, 마크다운 없이 JSON만 출력한다.

출력 형식:
{{
  "declined_indices": [],
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

사용자 원문 (거부 판별은 이 원문만 사용):
{query}

검색용 보강 문장 (서비스 추천에만 참고):
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
                    # 토큰 수는 관리자 통계용 DB에만 저장하고 Render 로그에는 출력하지 않음
                    add_token_usage(res.usage.input_tokens, res.usage.output_tokens)
                except Exception:
                    pass

            text = res.output_text
            try:
                parsed = json.loads(text)
            except:
                match = re.search(r'\{.*\}', text, re.DOTALL)
                if match:
                    parsed = json.loads(match.group())
                else:
                    parsed = {"results": []}

            # 기존 AI 응답에 포함된 거부 서비스 인덱스만 재사용 (추가 AI 호출 없음).
            declined_indices = set()
            for value in parsed.get("declined_indices", []):
                try:
                    index = int(value)
                    if 0 <= index < len(service_df):
                        declined_indices.add(index)
                except (ValueError, TypeError):
                    pass
            declined_keys = set()
            for index in declined_indices:
                row = service_df.iloc[index]
                declined_keys.add((str(row.get("대분류", "")).strip(),
                                   str(row.get("중분류", "")).strip(),
                                   str(row.get("서비스내용", "")).strip()))

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
            for item in final_results:
                if infer_direct_need_from_query(query, item):
                    item["direct_need"] = True

            # 선택이유에서 실제 존재하지 않는 복지용구 품목명 제거
            INVALID_WELFARE_TERMS = ["욕실안전", "보행보조", "배변보조", "이동보조", "욕창예방", "위생지원"]
            for item in final_results:
                reason = str(item.get("선택이유", ""))
                for term in INVALID_WELFARE_TERMS:
                    reason = reason.replace(term + ", ", "").replace(", " + term, "").replace(term, "")
                item["선택이유"] = reason

            # 방문구강관리 하드 가드: 입력에 구강·치아 단서가 없으면 강제 제거 (GPT 오추천 차단)
            ORAL_CLUES = ["구강", "입안", "입속", "칫솔질", "양치", "잇몸", "치아", "치주",
                          "입냄새", "구취", "백태", "구내염", "입마름", "구강건조", "틀니"]
            _q_oral = query.replace(" ", "")
            if not any(c in _q_oral for c in ORAL_CLUES):
                final_results = [it for it in final_results
                                 if "구강" not in str(it.get("중분류", ""))]

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

            # 검색 로그 적재 — 일자별 지역 클릭수 집계용 (IP 미수집, 지역/검색구분만)
            if os.getenv("RENDER"):
                _pv_threading.Thread(
                    target=_region_log_insert,
                    args=(selected_sido, selected_sigungu, "desc"),
                    daemon=True
                ).start()

            # ======================
            # [후처리] 난청/청각 문제 → 의사소통지원 강제 포함
            # ======================
            q_norm_hearing = query.replace(" ", "").lower()
            has_hearing_comm_need = any(k in q_norm_hearing for k in [
                "난청", "청각장애", "귀가어두움", "귀가어두워",
                "소리를못알아듣", "소리를알아듣지못",
                "말소리를못알아듣", "말소리를알아듣지못",
                "듣지못함", "잘못들음", "잘안들림", "소리가안들림",
                "대화어려움", "의사소통어려움"
            ])

            if has_hearing_comm_need:
                existing_keys = set(
                    (str(item.get("대분류", "")).strip(),
                     str(item.get("중분류", "")).strip(),
                     str(item.get("서비스내용", "")).strip())
                    for item in final_results
                )

                for _, srow in service_df.iterrows():
                    s_main = str(srow.get("대분류", "")).strip()
                    s_mid  = str(srow.get("중분류", "")).strip()
                    s_sub  = str(srow.get("서비스내용", "")).strip()

                    if s_main == "일상생활돌봄" and s_mid == "의사소통지원":
                        if (s_main, s_mid, s_sub) not in existing_keys:
                            final_results.append({
                                "대분류": s_main,
                                "중분류": s_mid,
                                "서비스내용": s_sub,
                                "선택이유": "난청으로 소리를 알아듣기 어려워 의사소통지원 서비스 검토가 필요함",
                                "direct_need": any(w in q_norm_hearing for w in ["필요함", "필요하다", "필요로함", "원함", "희망함"]),
                                "_ai_picked": False
                            })
                            existing_keys.add((s_main, s_mid, s_sub))

            # ======================
            # [후처리] 몸씻기/비누칠/부분도움 → 방문요양-신체활동지원 강제 포함 및 정서지원 오탐 제거
            # ======================
            q_norm_bodycare = query.replace(" ", "")
            has_bodycare_need = (
                any(k in q_norm_bodycare for k in ["몸씻", "씻", "비누칠", "비누질", "샤워", "신체청결"])
                and any(k in q_norm_bodycare for k in ["도움", "부분도움", "필요", "못함", "수행하지못", "어려움"])
            )

            if has_bodycare_need:
                final_results = [
                    item for item in final_results
                    if not (
                        str(item.get("대분류", "")).strip() == "요양"
                        and str(item.get("중분류", "")).strip() == "방문요양"
                        and str(item.get("서비스내용", "")).strip() == "정서지원"
                    )
                ]

                existing_keys = set(
                    (str(item.get("대분류", "")).strip(),
                     str(item.get("중분류", "")).strip(),
                     str(item.get("서비스내용", "")).strip())
                    for item in final_results
                )

                for _, srow in service_df.iterrows():
                    s_main = str(srow.get("대분류", "")).strip()
                    s_mid  = str(srow.get("중분류", "")).strip()
                    s_sub  = str(srow.get("서비스내용", "")).strip()

                    if s_main == "요양" and s_mid == "방문요양" and s_sub == "신체활동지원":
                        if (s_main, s_mid, s_sub) not in existing_keys:
                            final_results.append({
                                "대분류": s_main,
                                "중분류": s_mid,
                                "서비스내용": s_sub,
                                "선택이유": "혼자서는 몸 씻기와 비누칠을 깨끗하게 수행하기 어려워 신체활동지원 검토가 필요함",
                                "direct_need": True,
                                "_ai_picked": False
                            })
                            existing_keys.add((s_main, s_mid, s_sub))

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
                "몸씻", "몸씻기", "씻을때", "씻을때도움", "몸을씻",
                "비누칠", "비누질", "등씻기", "머리감기", "샤워",
                "부분도움", "깨끗하게수행하지못", "신체청결", "청결유지어려움",
            ]
            # 목욕 자립 표현 (이런 표현이 있으면 방문목욕 강제 추가 안 함)
            bath_independent_keywords = [
                "혼자목욕가능", "혼자씻기가능", "혼자씻을수있", "스스로목욕가능",
                "목욕혼자가능", "씻기혼자가능", "혼자목욕함", "혼자씻음",
                "목욕스스로가능", "목욕독립적", "목욕도혼자가능",
            ]
            has_bath_keyword = any(k in q_norm_bath_pre for k in bath_need_keywords)
            if any(k in q_norm_bath_pre for k in ["몸씻", "씻을때", "비누칠", "비누질", "샤워", "신체청결"]) and any(k in q_norm_bath_pre for k in ["도움", "부분도움", "못함", "어려움", "필요"]):
                has_bath_keyword = True
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
                    "씻기도움희망", "씻기도움원함", "씻기필요", "씻을때도움필요",
                    "몸씻기필요", "비누칠도움", "부분도움필요", "신체청결필요",
                    "목욕서비스희망", "목욕서비스원함",
                ]
                is_bath_direct = (
                    any(p in q_norm_bath_pre for p in bath_direct_patterns)
                    or any(w in q_norm_bath_pre for w in ["필요함", "필요하다", "도움이필요", "도움필요", "원함", "희망함"])
                )

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

            # 직접 욕구 재보정 — 후처리로 추가된 항목까지 포함
            for item in final_results:
                if infer_direct_need_from_query(query, item):
                    item["direct_need"] = True

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
            # [후처리] 치매+기저귀/조호물품 맥락에서는 요실금팬티 복지용구 오탐 제거
            # ======================
            if "치매" in q_norm_welfare and any(k in q_norm_welfare for k in ["기저귀", "조호물품", "소변실수", "배뇨실수"]):
                final_results = [
                    item for item in final_results
                    if not (
                        str(item.get("대분류", "")).strip() == "요양" and
                        str(item.get("중분류", "")).strip() == "복지용구" and
                        "요실금팬티" in str(item.get("서비스내용", ""))
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

            # ======================
            # [후처리] 화기·가스 안전 맥락에서는 방역소독 오탐 제거
            # - 화기관리/가스불/가스차단/화재위험은 주거안전지원으로 봄
            # - 해충·악취·곰팡이·쓰레기 등 주거위생 문제가 함께 있을 때만 방역소독 허용
            # ======================
            q_norm_fire = query.replace(" ", "")

            fire_safety_keywords = [
                "가스레인지", "가스렌지", "가스불", "화기", "불관리",
                "가스차단", "화재위험", "불을켜놓", "불을안끄", "불끄는걸잊"
            ]

            hygiene_keywords = [
                "방역", "소독", "해충", "벌레", "바퀴", "악취",
                "곰팡이", "쓰레기", "집이지저분", "청소", "위생"
            ]

            has_fire_safety = any(k in q_norm_fire for k in fire_safety_keywords)
            has_hygiene_issue = any(k in q_norm_fire for k in hygiene_keywords)

            if has_fire_safety and not has_hygiene_issue:
                final_results = [
                    item for item in final_results
                    if not (
                        "방역" in str(item.get("서비스내용", "")).strip()
                        or "소독" in str(item.get("서비스내용", "")).strip()
                        or "방역" in str(item.get("중분류", "")).strip()
                        or "소독" in str(item.get("중분류", "")).strip()
                    )
                ]

            if "기관" in q_norm_medical and not has_real_medical:
                final_results = [
                    item for item in final_results
                    if not (
                        str(item.get("중분류", "")).strip() in ("방문진료", "방문간호")
                    )
                ]

            # 수기 추천/보정 이후 마지막에 같은 AI 판별 결과만 적용한다.
            # 새로운 AI 호출이나 추가 추론은 수행하지 않는다.
            final_results = [item for item in final_results if (
                str(item.get("대분류", "")).strip(),
                str(item.get("중분류", "")).strip(),
                str(item.get("서비스내용", "")).strip()
            ) not in declined_keys]
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
            service_results = filtered_results
            # _ai_picked는 정렬용 내부 플래그이므로 결과에서 제거
            for item in service_results:
                item.pop("_ai_picked", None)


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

        # AI가 판별한 명시적 거부 서비스를 최종 결과에 적용한다.
        service_results = apply_common_decline_filter(service_results, declined_keys)
        count = len(service_results)
        DESC_CACHE[cache_key] = {
            "results": service_results,
            "warning": warning_msg,
            "time": time.time(),
            "declined_keys": [list(k) for k in declined_keys],
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
        sido_options=SIDO_OPTIONS,
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
  margin-top:28px;
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
  position:relative;
  top:24px;
  right:10px;
  z-index:10000;
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
    height:30px !important;
    padding:0 10px !important;
    font-size:11.5px !important;
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
  background:#e8ecf4;
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
  box-shadow:0 10px 26px rgba(15,23,42,0.10);
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
    color:transparent;
  }
  .textarea-wrap{
    position:relative;
  }
  .mobile-query-placeholder{
    position:absolute;
    left:14px;
    top:14px;
    display:grid;
    grid-template-columns:max-content 1fr;
    grid-auto-rows:auto;
    column-gap:0;
    color:#6b7280;
    font-size:15px;
    line-height:1.7;
    pointer-events:none;
    white-space:nowrap;
  }
  .mobile-query-placeholder .ph-empty{
    visibility:hidden;
  }
  #queryInput:not(:placeholder-shown) + .mobile-query-placeholder{
    display:none;
  }
}
@media (min-width:769px){
  .mobile-query-placeholder{
    display:none;
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
  position:relative;
  margin:30px 0 0 0;
  padding:26px 18px 16px;
  border-radius:12px;
  background:#fff1f2;
  border:1px solid #fb7185;
  color:#9f1239;
  font-size:14px;
  font-weight:700;
  line-height:1.65;
  text-align:left;
}

.privacy-warning .siren-icon{
  position:absolute;
  top:-18px;
  left:50%;
  transform:translateX(-50%);
  width:40px;
  height:40px;
  flex:none;
  margin:0;
  background:#fff;
  border:1px solid #fb7185;
  border-radius:50%;
  display:flex;
  align-items:center;
  justify-content:center;
  box-shadow:0 1px 4px rgba(159,18,57,0.12);
}

.privacy-warning .siren-svg{
  width:22px;
  height:23px;
}

.privacy-warning-text{
  display:block;
  width:100%;
  text-align:left;
  word-break:keep-all;
  overflow-wrap:break-word;
}

.privacy-warning-text p{
  margin:0;
  padding-left:0;
  text-indent:0;
}

.privacy-warning-text .pw-sub{
  display:inline;
}

@media (max-width:480px){
  .privacy-warning-text .pw-sub{
    display:block;
    margin-top:6px;
  }
}

@media (min-width:481px){
  .privacy-warning{
    padding:28px 28px 18px;
  }
}

@media (max-width:480px){
  .privacy-warning{
    margin:28px 0 0 0;
    padding:24px 14px 14px;
    font-size:13px;
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
  cursor:pointer;
  flex-shrink:0;
  user-select:none;
  border:none;
  padding:0;
  margin:0;
  line-height:1;
  font-family:inherit;
  -webkit-appearance:none;
  appearance:none;
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
  z-index:10010;
  align-items:center;
  justify-content:center;
  padding:18px;
  overscroll-behavior:contain;
  touch-action:none;
}

body.privacy-modal-open{
  overflow:hidden !important;
  position:fixed !important;
  width:100% !important;
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

.privacy-agree-note{
  margin:14px 0 0 0;
  font-size:12.5px;
  color:#4b5563;
  line-height:1.6;
  text-align:center;
  word-break:keep-all;
}

.privacy-btns{
  display:flex;
  gap:10px;
}

.privacy-btns button{
  flex:1;
  width:auto;
}

.privacy-disagree{
  height:48px;
  border:1px solid #d1d5db;
  border-radius:14px;
  background:#ffffff;
  color:#6b7280;
  font-size:15px;
  font-weight:700;
  cursor:pointer;
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
    top:auto;
    right:auto;
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

/* ===== 공단자원 연관검색어 (팝업 스타일은 DBO_VIEWER_HTML 에 있음) ===== */
.dbo-suggest{ display:none; margin-top:8px; background:#eef4ff; border:1px solid #c7d7ff; border-radius:12px; padding:10px 12px 12px; }
.dbo-suggest.show{ display:block; animation:dboSuggestIn .15s ease; }
@keyframes dboSuggestIn{ from{ opacity:0; transform:translateY(-4px); } to{ opacity:1; transform:none; } }
.dbo-suggest-label{ font-size:12.5px; font-weight:700; color:#1e3a8a; margin-bottom:8px; }
#dboSuggestList{ display:flex; flex-wrap:wrap; gap:6px; }
.dbo-suggest-item{ display:inline-flex; align-items:center; padding:7px 12px; border-radius:999px; background:#fff; border:1px solid #93c5fd; font-size:13px; font-weight:700; color:#1d4ed8; cursor:pointer; line-height:1.3; word-break:keep-all; transition:background .12s, color .12s; }
.dbo-suggest-item:hover{ background:#2563eb; border-color:#2563eb; color:#fff; }
@media (max-width:480px){
  .dbo-suggest-label{ font-size:12px; }
  .dbo-suggest-item{ font-size:12.5px; padding:6px 10px; }
}

/* === 버튼 누름 효과 B (디자인 전용) === */
button, input[type="submit"], input[type="button"], a.card, .btn, .home-btn, .home-button, .reset-btn, .home-help-btn, .home-notice-btn, .tip-btn, #fabMain, .fab-item, [class*="-btn"], [class*="-button"] { transition:transform .12s ease, box-shadow .12s ease; }
button:active, input[type="submit"]:active, input[type="button"]:active, .btn:active, .home-btn:active, .home-button:active, .reset-btn:active, .home-help-btn:active, .home-notice-btn:active, .tip-btn:active, #fabMain:active, .fab-item:active, [class*="-btn"]:active, [class*="-button"]:active { transform:scale(0.92) !important; }
</style>
</head>

<body>

<!-- ===== 개인정보 입력 주의 팝업 ===== -->
<div id="privacyModal" onwheel="event.preventDefault()" ontouchmove="event.preventDefault()">
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

    <div class="privacy-agree-note">
      위 주의사항을 확인했으며, 개인정보·민감정보를 입력하지 않고 이용하는 데 동의합니다.
    </div>

    <label class="privacy-check">
      <input type="checkbox" id="hidePrivacyToday">
      오늘 하루 보지 않기
    </label>

    <div class="privacy-btns">
      <button type="button" class="privacy-confirm" onclick="closePrivacyModal()">
        동의하고 시작
      </button>
      <button type="button" class="privacy-disagree" onclick="declinePrivacyModal()">
        동의 안 함
      </button>
    </div>

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
        {% for s in sido_options %}
        <option value="{{s}}" {% if s==selected_sido %}selected{% endif %}>{{s}}</option>
        {% endfor %}
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
<div class="mobile-query-placeholder" aria-hidden="true">
  <span>예)&nbsp;</span><span>식사도움이 필요한</span>
  <span class="ph-empty">예)&nbsp;</span><span>어르신에게 맞는 서비스</span>
</div>

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

{{ cam_return|default('')|safe }}
<input type="file" id="imgInput" accept="image/*" capture="environment" style="display:none;">

<button type="button" onclick="openImage()" id="imgBtn">
  <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" fill="white" viewBox="0 0 24 24">
    <path d="M20 5h-3.2l-1.6-2H8.8L7.2 5H4c-1.1 0-2 .9-2 2v12c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V7c0-1.1-.9-2-2-2zm-8 13c-2.8 0-5-2.2-5-5s2.2-5 5-5 5 2.2 5 5-2.2 5-5 5zm0-8.2c-1.8 0-3.2 1.4-3.2 3.2s1.4 3.2 3.2 3.2 3.2-1.4 3.2-3.2-1.4-3.2-3.2-3.2z"/>
  </svg>
</button>
</div>

<div class="dbo-suggest" id="dboSuggest">
  <div class="dbo-suggest-label">💡 이런 공단자원을 찾으시나요?</div>
  <div id="dboSuggestList"></div>
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

{% macro render_group_card(group) %}
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
{% endmacro %}

{% set direct_groups = grouped_service_results|default([])|selectattr('direct_need')|list %}
{% set normal_groups = grouped_service_results|default([])|rejectattr('direct_need')|list %}

{% if service_results %}
<div class="result" id="resultArea">

{% if count > 0 %}
<h3>{{count}}건의 추천 서비스</h3>
{% endif %}

{% if direct_groups %}
<div class="direct-need-box">
  <div style="display:flex;align-items:center;gap:7px;margin-bottom:16px;">
    <div class="direct-need-title" style="margin-bottom:0;">
      <svg style="width:17px;height:17px;flex-shrink:0;vertical-align:-3px;" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
        <polygon points="12,2 15.09,8.26 22,9.27 17,14.14 18.18,21.02 12,17.77 5.82,21.02 7,14.14 2,9.27 8.91,8.26" fill="#EF9F27"/>
      </svg>
      <span>주요욕구</span>
    </div>
    <div class="direct-need-tooltip-wrap">
      <button type="button" class="direct-need-tooltip-icon" aria-label="안내" onclick="var e=event;e.stopPropagation();var b=this.parentElement.querySelector('.direct-need-tooltip-box');if(!b)return;var vis=(b.style.display==='block');document.querySelectorAll('.direct-need-tooltip-box').forEach(function(x){x.style.display='none';});b.style.display=vis?'none':'block';">?</button>
      <div class="direct-need-tooltip-box">대상자·보호자의 희망욕구와 조사자 판단 필요 서비스가 모두 포함되었습니다.</div>
    </div>
  </div>
  {% for group in direct_groups %}
  {{ render_group_card(group) }}
  {% endfor %}
</div>
{% endif %}


{% for group in normal_groups %}
{{ render_group_card(group) }}
{% endfor %}

{% if service_results %}
<div style="margin-top:18px;padding:12px 14px;background:#f8fafc;border:1px solid #e5e7eb;border-radius:12px;font-size:12.5px;line-height:1.6;color:#64748b;text-align:center;">
  본 추천 결과는 AI 기반 참고 자료이며, 최종 판단과 책임은 담당자의 전문적 판단에 따릅니다.
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

// 사례검색 음성 입력: 중간 인식 결과는 화면에만 표시하고, 종료 후 한 번만 검색한다.
let voiceSession = 0;
let voiceFinalText = "";
let voiceInterimText = "";
let voiceResultSegments = [];
let voiceStartValue = "";
let voiceSubmitted = false;
let voiceStopping = false;
let voiceNativeActive = false;
let voiceFallbackUsed = false;
let voiceError = "";

// 인식 엔진이 같은 구절을 누적 결과와 중간 결과에 반복해서 넣어도 한 번만 표시한다.
// 공백을 제외한 겹침을 비교하되, 실제 인식된 글자의 순서와 내용은 유지한다.
function mergeVoiceSegments(base, addition){
  base = String(base || "").trim();
  addition = String(addition || "").trim();
  if(!base) return addition;
  if(!addition) return base;
  const compactBase = base.replace(/\\s+/g, "");
  const compactNext = addition.replace(/\\s+/g, "");
  if(!compactNext) return base;
  if(compactNext === compactBase) return addition;
  if(compactNext.startsWith(compactBase)) return addition;
  if(compactBase.startsWith(compactNext)) return base;

  // 이전 문장의 끝과 새 결과의 시작이 겹치는 가장 긴 구절을 찾는다.
  const limit = Math.min(compactBase.length, compactNext.length);
  let overlap = 0;
  for(let n = limit; n >= 2; n--){
    if(compactBase.slice(-n) === compactNext.slice(0, n)){
      overlap = n;
      break;
    }
  }
  if(!overlap) return base + " " + addition;
  let consumed = 0;
  let offset = 0;
  while(offset < addition.length && consumed < overlap){
    if(!/\\s/.test(addition[offset])) consumed++;
    offset++;
  }
  const rest = addition.slice(offset);
  if(!rest.trim()) return base;
  return base + (/^\\s/.test(rest) ? "" : " ") + rest.trimEnd();
}

function getVoiceTranscript(){
  return mergeVoiceSegments(voiceFinalText, voiceInterimText).trim();
}

function showVoiceText(text){
  if(!queryInput) return;
  queryInput.value = String(text || "").slice(0, 2000);
  queryInput.dispatchEvent(new Event("input", {bubbles:true}));
  queryInput.scrollTop = queryInput.scrollHeight;
}

function beginVoiceInput(){
  voiceSession++;
  voiceFinalText = "";
  voiceInterimText = "";
  voiceResultSegments = [];
  voiceStartValue = queryInput ? queryInput.value : "";
  voiceSubmitted = false;
  voiceStopping = false;
  voiceNativeActive = false;
  voiceFallbackUsed = false;
  voiceError = "";
  isRecording = true;
  setVoiceButtonRecording(true);
  playBeep("start");
  const overlay = document.getElementById("voiceOverlay");
  if(overlay) overlay.style.display = "block";
}

function submitVoiceText(transcript){
  // 인식 결과가 여러 번 전달되거나 종료 콜백이 중복되어도 검색은 한 번만 실행한다.
  if(voiceSubmitted) return;
  const text = String(transcript || "").trim();
  if(!text){
    finishVoiceUI();
    return;
  }
  voiceSubmitted = true;
  showVoiceText(text);
  finishVoiceUI();
  document.getElementById("descAction").value = "search";
  // 기존 form submit 리스너(개인정보 확인 및 로딩 표시)를 그대로 통과한다.
  if(searchForm.requestSubmit){
    searchForm.requestSubmit();
  }else{
    if(window.__hasPII && window.__hasPII(queryInput.value)){
      if(typeof openPiiModal === "function") openPiiModal();
      return;
    }
    if(loading) loading.style.display = "flex";
    startLoadingMessages();
    searchForm.submit();
  }
}

function completeVoiceInput(){
  if(voiceSubmitted) return;
  const text = getVoiceTranscript();
  voiceNativeActive = false;
  recognition = null;
  if(text){
    submitVoiceText(text);
  }else{
    finishVoiceUI();
  }
}

function startNativeVoiceInput(){
  if(!window.AndroidVoice || !window.AndroidVoice.startVoiceSearch) return false;
  voiceFallbackUsed = true;
  voiceNativeActive = true;
  recognition = null;
  voiceError = "";
  try{
    window.AndroidVoice.startVoiceSearch();
    return true;
  }catch(e){
    voiceNativeActive = false;
    finishVoiceUI();
    return false;
  }
}

// 기존 안드로이드 브리지와 호환. 결과를 받은 순간에는 검색하지 않는다.
window.__careNaviVoiceResult = function(text){
  if(!voiceNativeActive || voiceSubmitted) return;
  voiceFinalText = String(text || "");
  voiceInterimText = "";
  showVoiceText(voiceFinalText);
};

// 네이티브 쪽에서 중간 결과를 전달하는 버전도 사용할 수 있도록 콜백을 제공한다.
window.__careNaviVoicePartial = function(text){
  if(!voiceNativeActive || voiceSubmitted) return;
  voiceInterimText = String(text || "");
  showVoiceText(getVoiceTranscript());
};
window.__careNaviVoiceInterim = window.__careNaviVoicePartial;

window.__careNaviVoiceEnd = function(){
  if(!voiceNativeActive || voiceSubmitted) return;
  completeVoiceInput();
};

function startVoiceInput(event){
  if(event) event.preventDefault();

  // 두 번째 누름은 인식을 종료하고 지금까지 입력된 문장으로 검색한다.
  if(isRecording){
    if(voiceStopping) return;
    voiceStopping = true;
    if(voiceNativeActive){
      if(window.AndroidVoice && window.AndroidVoice.stopVoiceSearch){
        window.AndroidVoice.stopVoiceSearch();
      }
      // 네이티브 종료 콜백에서 최종 결과를 받아 검색한다.
    }else if(recognition){
      recognition.stop();
    }
    return;
  }

  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  const hasNativeVoice = navigator.userAgent.indexOf("CareNaviApp") !== -1 &&
    window.AndroidVoice && window.AndroidVoice.startVoiceSearch;

  if(!SpeechRecognition && !hasNativeVoice){
    alert("이 브라우저는 음성인식을 지원하지 않습니다.");
    return;
  }

  beginVoiceInput();

  // 실시간 중간 결과를 지원하는 브라우저 음성인식을 우선 사용한다.
  // 앱 WebView에서 지원하지 않으면 기존 AndroidVoice 연결로 돌아간다.
  if(!SpeechRecognition){
    startNativeVoiceInput();
    return;
  }

  const currentSession = voiceSession;
  const currentRecognition = new SpeechRecognition();
  recognition = currentRecognition;
  currentRecognition.lang = "ko-KR";
  currentRecognition.interimResults = true;
  currentRecognition.continuous = true;

  currentRecognition.onresult = function(e){
    if(currentSession !== voiceSession || recognition !== currentRecognition || voiceSubmitted) return;
    // e.results는 누적 목록이다. 매 이벤트마다 더하지 않고 각 인덱스를 교체한다.
    // 브라우저가 중간 결과를 수정하거나 최종 결과로 바꾸더라도 중복되지 않는다.
    voiceResultSegments.length = e.results.length;
    for(let i = 0; i < e.results.length; i++){
      const result = e.results[i];
      voiceResultSegments[i] = {
        text: result && result[0] ? String(result[0].transcript || "") : "",
        isFinal: !!(result && result.isFinal)
      };
    }
    let finalText = "";
    let interimText = "";
    for(const segment of voiceResultSegments){
      if(!segment || !segment.text) continue;
      if(segment.isFinal){
        finalText = mergeVoiceSegments(finalText, segment.text);
      }else{
        interimText = mergeVoiceSegments(interimText, segment.text);
      }
    }
    voiceFinalText = finalText;
    voiceInterimText = interimText;
    showVoiceText(getVoiceTranscript());
  };

  currentRecognition.onerror = function(e){
    if(currentSession !== voiceSession || recognition !== currentRecognition) return;
    voiceError = e.error || "unknown";
  };

  currentRecognition.onend = function(){
    if(currentSession !== voiceSession || recognition !== currentRecognition || voiceSubmitted) return;
    // WebView에서 음성 서비스가 동작하지 않는 경우에만 기존 앱 브리지를 사용한다.
    if(!voiceStopping && !voiceFinalText && !voiceInterimText &&
       voiceError !== "no-speech" && voiceError !== "aborted" &&
       hasNativeVoice && !voiceFallbackUsed){
      startNativeVoiceInput();
      return;
    }
    completeVoiceInput();
  };

  try{
    currentRecognition.start();
  }catch(e){
    recognition = null;
    if(!hasNativeVoice || !startNativeVoiceInput()) finishVoiceUI();
  }
}

/* 사진 인식: 휴대폰 기본 카메라 앱으로 촬영.
   열기 직전 표시를 남겨 두어, 카메라 앱 사용 중 화면이 새로 열리면 안내 (CAM_RETURN_HTML) */
function openImage(){
  if(window.camPending) window.camPending.set("desc");
  document.getElementById("imgInput").click();
}

/* 카메라 원본 사진이 클 때 모바일/서버 메모리 부담을 줄이기 위해 OCR 전송본만 축소·압축 */
async function prepareOcrImage(file){
  const COMPRESS_MIN_BYTES = 1.5 * 1024 * 1024;
  const OCR_IMAGE_WIDTH = 1600;
  const OCR_JPEG_QUALITY = 0.80;

  if(!file || file.size <= COMPRESS_MIN_BYTES || typeof createImageBitmap !== "function"){
    return file;
  }

  let bitmap = null;
  try{
    bitmap = await createImageBitmap(file, {
      resizeWidth: OCR_IMAGE_WIDTH,
      resizeQuality: "high"
    });

    const canvas = document.createElement("canvas");
    canvas.width = bitmap.width;
    canvas.height = bitmap.height;

    const ctx = canvas.getContext("2d", {alpha:false});
    if(!ctx){
      if(bitmap.close) bitmap.close();
      return file;
    }

    ctx.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
    if(bitmap.close) bitmap.close();
    bitmap = null;

    const blob = await new Promise(function(resolve){
      canvas.toBlob(resolve, "image/jpeg", OCR_JPEG_QUALITY);
    });

    canvas.width = 1;
    canvas.height = 1;

    return (blob && blob.size > 0) ? blob : file;
  }catch(e){
    if(bitmap && bitmap.close) bitmap.close();
    return file;
  }
}

document.getElementById("imgInput").addEventListener("change", function(){
  const file = this.files[0];
  this.value = "";
  if(window.camPending) window.camPending.clear();
  if(file) handleOcrFile(file);
});

/* 카메라 앱을 쓰는 동안 휴대폰이 화면을 새로 열었으면 '다시 촬영' 안내 */
(function(){
  if(!window.camPending) return;
  if(window.camPending.take("desc")){
    setTimeout(function(){ window.camPending.notice(openImage); }, 300);
  }
})();

async function handleOcrFile(file){
  if(!file) return;

  const uploadImage = await prepareOcrImage(file);

  const formData = new FormData();
  formData.append("image", uploadImage, (uploadImage === file && file.name) ? file.name : "camera_ocr.jpg");
  formData.append("ocr_privacy_confirmed", "yes");

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
}

if(searchForm){
  searchForm.addEventListener("submit", function(e){
    var qv = (document.getElementById("queryInput") || {}).value || "";
    if(window.__hasPII && window.__hasPII(qv)){
      if(e && e.preventDefault){ e.preventDefault(); }
      if(typeof openPiiModal === "function"){ openPiiModal(); }
      return false;
    }
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

let privacyScrollY = 0;

function lockPrivacyScroll(){
  privacyScrollY = window.scrollY || document.documentElement.scrollTop || 0;
  document.body.style.top = "-" + privacyScrollY + "px";
  document.body.classList.add("privacy-modal-open");
}

function unlockPrivacyScroll(){
  document.body.classList.remove("privacy-modal-open");
  document.body.style.top = "";
  window.scrollTo(0, privacyScrollY || 0);
}

function showPrivacyModal(){
  const modal = document.getElementById("privacyModal");
  if(!modal) return;
  modal.style.display = "flex";
  lockPrivacyScroll();
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
  unlockPrivacyScroll();
}

function closePrivacyModalByBg(e){
  // 박스 바깥(어두운 배경) 클릭 시에만 닫기
  if(e.target && e.target.id === "privacyModal"){
    closePrivacyModal();
  }
}

function declinePrivacyModal(){
  // 미동의: 사례별 AI 추천을 이용하지 않고 메인페이지로 이동
  try{ sessionStorage.removeItem("desc_privacy_shown"); }catch(e){}
  unlockPrivacyScroll();
  window.location.href = "/home";
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

  showPrivacyModal();
});

</script>

<!-- ===== 돌봄온 팝업 (공단자원 연관검색어 클릭 시) ===== -->
{{ dbo_viewer|safe }}

<script>
(function(){
  var ITEMS = {{ dolbomon_items|default([])|tojson }};
  var input = document.getElementById("queryInput");
  var box = document.getElementById("dboSuggest");
  var list = document.getElementById("dboSuggestList");
  if(!ITEMS || !ITEMS.length || !input || !box || !list || !window.openDbo) return;

  /* 공백 제거 + 소문자 (띄어쓰기 무시 매칭) */
  function norm(s){
    return Array.from(String(s || "")).filter(function(c){ return c.trim(); }).join("").toLowerCase();
  }
  /* 표시명의 괄호 부분은 비교에서 제외 — 예: "가족휴가제(단기보호)" → "가족휴가제" */
  function baseName(s){
    return String(s || "").split("(")[0].split("（")[0];
  }
  ITEMS.forEach(function(it){
    it._keys = [norm(baseName(it.name))].concat((it.keywords || []).map(norm))
      .filter(function(k){ return k.length >= 2; });
  });

  /* 연관검색어: 입력이 짧을 때(공백 제외 2~20자)만 부분 일치로 표시
     - 20자 초과(사례 작성 중)면 표시하지 않음. 기준을 바꾸려면 아래 숫자 20만 수정 */
  function renderSuggest(){
    var q = norm(input.value);
    list.innerHTML = "";
    if(q.length < 2 || q.length > 20){ box.classList.remove("show"); return; }
    var hits = ITEMS.filter(function(it){
      return it._keys.some(function(k){ return k.indexOf(q) !== -1 || q.indexOf(k) !== -1; });
    }).slice(0, 8);
    if(!hits.length){ box.classList.remove("show"); return; }
    hits.forEach(function(it){
      var d = document.createElement("div");
      d.className = "dbo-suggest-item";
      d.setAttribute("role", "button");
      d.tabIndex = 0;
      d.textContent = it.name;
      d.addEventListener("click", function(){ window.openDbo(it); });
      d.addEventListener("keydown", function(e){ if(e.key === "Enter"){ e.preventDefault(); window.openDbo(it); } });
      list.appendChild(d);
    });
    box.classList.add("show");
  }
  input.addEventListener("input", renderSuggest);
  renderSuggest();
})();
</script>

  <div class="tip-notice">
    <p>※ 입력한 사례와 유사한 <b class="highlight">통합돌봄 서비스를 최대 30가지</b> 추천합니다.(최대 2,000자)</p>
    <p>※ <b class="highlight">AI 기반 추천 서비스</b>로, 같은 사례라도 추천 결과가 달라질 수 있습니다.</p>
    <p>※ <b class="highlight">지역 설정 시</b> 해당 지역 자원의 서비스 분류를, 미설정 시 전체 분류를 추천합니다.</p>

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

      <div class="privacy-warning-text">
        <p class="pw-main">성명·주민번호·연락처·주소 등 개인정보는 입력하지 마시고 사진 촬영 시 개인정보를 가려주세요. <span class="pw-sub">입력·업로드의 책임은 사용자에게 있습니다.</span></p>
      </div>
    </div>

<!-- ===== 개인정보 입력 차단 팝업 ===== -->
<div id="piiModal" style="display:none;position:fixed;inset:0;background:rgba(15,23,42,0.5);z-index:100000;align-items:center;justify-content:center;padding:24px;" onclick="if(event.target===this)closePiiModal()">
  <div style="width:100%;max-width:360px;background:#fff;border-radius:18px;padding:26px 22px;text-align:center;box-shadow:0 20px 50px rgba(15,23,42,0.25);">
    <div style="font-size:38px;line-height:1;margin-bottom:12px;">🔒</div>
    <div style="font-size:18px;font-weight:800;color:#111827;margin-bottom:10px;">개인정보가 감지되었습니다</div>
    <div style="font-size:14px;color:#4b5563;line-height:1.65;">전화번호 · 주민등록번호 · 이메일 등<br>개인정보가 포함되어 <b>검색이 차단</b>되었습니다.<br>해당 정보를 지우고 다시 검색해 주세요.</div>
    <div id="piiDetectedPart" style="display:none;margin-top:12px;padding:10px;background:#f3f4f6;border-radius:8px;font-size:13px;color:#374151;overflow-wrap:anywhere;"></div>
    <button type="button" onclick="closePiiModal()" style="margin-top:20px;width:100%;padding:13px;background:#2563eb;color:#fff;border:none;border-radius:12px;font-size:15px;font-weight:700;cursor:pointer;">확인</button>
  </div>
</div>

<script>
(function(){
  var PII = [
    /[\\w.+-]+@[\\w-]+\\.[\\w.-]+/,
    /(?:^|[^\\d])(?:19|20)\\d{2}[-./년\\s]+(?:0?[1-9]|1[0-2])[-./월\\s]+(?:0?[1-9]|[12]\\d|3[01])일?(?!\\d)/,
    /(?:^|[^\\d])(?:19|20)\\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\\d|3[01])(?!\\d)/,
    /(?:^|[^\\d])\\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\\d|3[01])(?!\\d)/,
    /\\d{6}\\s*-\\s*\\d{7}/,
    /01[016789][-\\s.]?\\d{3,4}[-\\s.]?\\d{4}/,
    /\\d{2,3}[-\\s.]\\d{3,4}[-\\s.]\\d{4}/
  ];
  var piiTypes = ["이메일", "생년월일", "생년월일", "생년월일", "주민등록번호", "휴대전화번호", "전화번호"];
  window.__hasPII = function(t){
    if(!t) return false;
    for(var i=0;i<PII.length;i++){ if(PII[i].test(t)) return true; }
    return false;
  };
  window.__showPiiDetectedPart = function(t){
    var el = document.getElementById("piiDetectedPart");
    if(!el) return;
    var matches = [];
    for(var i=0;i<PII.length;i++){
      var match = PII[i].exec(t || "");
      if(match){
        var value = match[0].trim();
        // 탐지된 원문은 팝업에 다시 노출하지 않고 유형과 마스킹된 값만 표시
        var masked = value.length <= 4 ? "****" : value.slice(0,2) + "***" + value.slice(-2);
        matches.push(piiTypes[i] + " (" + masked + ")");
      }
    }
    el.textContent = matches.length ? "차단된 부분: " + matches.join(", ") : "";
    el.style.display = matches.length ? "block" : "none";
  };
  window.openPiiModal = function(){
    var q = document.querySelector('textarea[name="query"], input[name="query"]');
    if(window.__showPiiDetectedPart) window.__showPiiDetectedPart(q ? q.value : "");
    var m = document.getElementById("piiModal");
    if(m){ m.style.display = "flex"; }
  };
  window.closePiiModal = function(){
    var m = document.getElementById("piiModal");
    if(m){ m.style.display = "none"; }
  };
})();
{% if pii_block|default(false) %}
window.addEventListener("DOMContentLoaded", function(){ if(window.openPiiModal) window.openPiiModal(); });
{% endif %}
</script>

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
            "못씹", "씹기힘들", "씹지못", "저작곤란", "연하곤란", "삼키기힘들", "틀니", "이가없",
            "영양부족", "영양불량", "체중감소", "기운없음"
        ],
        "aliases": [
            "영양지원", "식사지원", "반찬지원", "방문형지원", "건강관리"
        ]
    },

    "emotional_support": {
        "keywords": [
            "외로움", "외롭", "고립", "말벗", "우울", "혼자지냄",
            "혼자있음", "고독", "불안", "적적함", "심심함",
            "독거", "독거중", "혼자거주", "혼자삶", "혼자생활",
            "왕래하는가족없", "가족왕래없", "가족없음", "보호자없음",
            "가족부재", "연락하는사람없", "찾아오는사람없"
        ],
        "aliases": [
            "정서지원", "안부확인", "말벗", "돌봄연계", "사회적고립", "고독사예방"
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

    "oral_care": {
        "keywords": [
            "구강", "구강건조", "입마름", "입이마름", "칫솔질",
            "양치", "잇몸", "잇몸출혈", "출혈", "피가남",
            "치아출혈", "구내염", "입안통증", "구강관리",
            "입안", "입안관리", "입안위생", "입속", "입속관리", "입속위생",
            "입안이지저분", "입속이지저분", "입안청결", "입속청결",
            "입냄새", "구취", "혀", "백태"
        ],
        "aliases": [
            "구강관리", "구강위생", "칫솔질", "구강건강", "방문구강관리", "건강관리"
        ]
    },

    "housing_environment": {
        "keywords": [
            "집이지저분", "집이더러", "쓰레기", "악취", "냄새", "곰팡이",
            "해충", "벌레", "바퀴벌레", "쥐", "방역", "소독",
            "집노후", "노후주택", "주거환경", "주거공간", "환경개선"
        ],
        "aliases": [
            "주거복지", "주거공간개선", "방역소독", "주거환경개선", "환경개선"
        ]
    },

    "housing_facility": {
        "keywords": [
            "보일러", "보일러교체", "에어컨", "에어컨설치", "냉방",
            "난방", "난방비", "냉난방", "단열", "창호", "수리",
            "집수리", "설비교체", "전기시설", "수도시설", "가스시설",
            "에너지효율", "에너지효율화"
        ],
        "aliases": [
            "주거복지", "주거공간개선", "기타", "집수리", "설비개선", "에너지효율화"
        ]
    },

    "housing_fire_safety": {
        "keywords": [
            "가스레인지", "가스렌지", "가스불", "화기", "불관리",
            "불을켜놓", "가스잠그", "가스차단", "화재위험",
            "인덕션", "전기레인지", "안전점검"
        ],
        "aliases": [
            "주거복지", "주거공간개선", "주거안전지원", "화재예방", "가스안전"
        ]
    },

    "communication_support": {
        "keywords": [
            "언어장애", "말을못", "말못", "소리를내지못",
            "의사소통어려움", "의사소통불가", "고개를끄덕",
            "고개끄덕", "표정으로", "몸짓으로", "수어", "대화어려움",
            "난청", "청각장애", "귀가어두움", "귀가어두워",
            "소리를못알아듣", "소리를알아듣지못",
            "말소리를못알아듣", "말소리를알아듣지못",
            "듣지못함", "잘못들음", "잘안들림", "소리가안들림"
        ],
        "aliases": [
            "일상생활돌봄", "의사소통지원", "의사표현지원", "언어지원", "대화지원"
        ]
    },

    "emergency_safety": {
        "keywords": [
            "응급서비스", "응급서비스필요", "응급안전", "응급안전안심",
            "응급안전안심서비스", "응급호출", "응급벨", "위급상황",
            "쓰러졌을때", "119연계", "응급상황", "안전확인필요"
        ],
        "aliases": [
            "일상생활돌봄", "스마트돌봄", "안부확인", "응급안전안심서비스",
            "응급호출", "안전확인", "기타"
        ]
    },

    "short_term_care": {
        "keywords": [
            "단기보호", "임시보호", "잠시맡", "며칠맡", "일시보호",
            "가족부재", "보호자부재", "돌볼가족없", "맡아줄사람없",
            "가족이없어돌봄", "치매가족부재", "보호자가없어"
        ],
        "aliases": [
            "요양", "단기보호", "보호", "일시보호", "가족부재", "돌봄공백"
        ]
    },

    "dementia_care_supplies": {
        "keywords": [
            "치매기저귀", "치매로소변실수", "치매로배뇨실수",
            "기저귀", "기저귀지원", "기저귀사용량", "조호물품",
            "소변실수잦아기저귀", "치매소변실수"
        ],
        "aliases": [
            "건강관리예방", "치매전문관리", "조호물품제공", "치매조호물품", "기저귀지원"
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
            "요실금", "배뇨장애", "배뇨관리", "위생지원", "방문보건"
        ])
        if "기저귀" not in q_norm:
            aliases.extend(["요실금팬티", "복지용구"])

    if "변" in q_norm and ("실수" in q_norm or "지리" in q_norm or "지림" in q_norm):
        aliases.extend(["배변관리", "위생지원", "복지용구", "방문보건"])

    if "혼자" in q_norm or "외롭" in q_norm or "고립" in q_norm or "말벗" in q_norm or "독거" in q_norm or "가족왕래없" in q_norm or "가족부재" in q_norm or "보호자없" in q_norm:
        aliases.extend(["정서지원", "안부확인", "돌봄연계", "사회적고립", "고독사예방"])

    if "밥" in q_norm or "식사" in q_norm or "반찬" in q_norm or "도시락" in q_norm:
        aliases.extend(["식사지원", "반찬지원", "영양지원"])

    if "낙상" in q_norm or "넘어" in q_norm or "휘청" in q_norm:
        aliases.extend(["낙상예방", "안전지원", "이동지원", "복지용구"])

    if "약" in q_norm or "병원" in q_norm or "복약" in q_norm:
        aliases.extend(["복약관리", "병원동행", "방문보건", "건강관리"])

    if "배고프" in q_norm or "배고파" in q_norm or "허기" in q_norm or "허기지" in q_norm or "굶" in q_norm or "못먹" in q_norm or "식욕없" in q_norm or "못씹" in q_norm or "씹기" in q_norm or "씹지" in q_norm or "씹는" in q_norm or "저작" in q_norm or "연하" in q_norm or "삼키" in q_norm or "삼킬" in q_norm or "틀니" in q_norm or "이가없" in q_norm or "치아" in q_norm:
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

    if any(k in q_norm for k in ["주거", "주택", "거주환경", "주거환경", "집수리", "노후", "곰팡이", "해충", "악취", "쓰레기"]):
        aliases.extend(["주거복지", "주거공간개선", "주거환경개선", "방역소독", "주거안전지원", "기타"])

    if any(k in q_norm for k in ["보일러", "에어컨", "냉방", "난방", "냉난방", "단열", "창호", "설비교체", "에너지효율", "에너지효율화"]):
        aliases.extend(["주거복지", "주거공간개선", "기타", "집수리", "설비개선", "에너지효율화"])

    if any(k in q_norm for k in ["가스레인지", "가스렌지", "가스불", "화기", "불관리", "가스차단", "화재위험"]):
        aliases.extend(["주거복지", "주거공간개선", "주거안전지원", "화재예방", "가스안전"])

    if "치매" in q_norm and (
        any(k in q_norm for k in ["가스레인지", "가스렌지", "가스불", "화기", "불관리", "가스차단", "화재위험", "불을켜놓", "가스잠그"])
        or ("냄비" in q_norm and any(k in q_norm for k in ["태우", "태움", "태웠", "태워", "탄다", "태운"]))
        or ("불" in q_norm and any(k in q_norm for k in ["깜빡", "잊어버", "잊고"]))
    ):
        aliases.extend(["일상생활돌봄", "스마트돌봄", "기타", "안부확인", "응급안전", "화재감지기", "가스타이머차단기", "안전확인"])

    if any(k in q_norm for k in ["구강", "구강건조", "입마름", "입이마름", "칫솔질", "양치", "잇몸", "잇몸출혈", "치아출혈", "구내염"]):
        aliases.extend(["구강관리", "구강위생", "칫솔질", "구강건강", "방문구강관리", "건강관리"])

    if any(k in q_norm for k in ["언어장애", "말을못", "말못", "소리를내지못", "의사소통", "고개를끄덕", "고개끄덕", "몸짓으로"]):
        aliases.extend(["일상생활돌봄", "의사소통지원", "의사표현지원", "언어지원", "대화지원"])

    if any(k in q_norm for k in ["응급서비스", "응급안전", "응급안전안심", "응급호출", "응급벨", "위급상황", "응급상황", "안전확인필요"]):
        aliases.extend(["일상생활돌봄", "스마트돌봄", "안부확인", "응급안전안심서비스", "응급호출", "안전확인", "기타"])

    if any(k in q_norm for k in ["단기보호", "임시보호", "잠시맡", "며칠맡", "일시보호", "가족부재", "보호자부재", "돌볼가족없", "맡아줄사람없"]):
        aliases.extend(["요양", "단기보호", "보호", "일시보호", "가족부재", "돌봄공백"])

    if "치매" in q_norm and any(k in q_norm for k in ["기저귀", "조호물품", "소변실수", "배뇨실수"]):
        aliases.extend(["건강관리예방", "치매전문관리", "조호물품제공", "치매조호물품", "기저귀지원"])

    if any(k in q_norm for k in ["몸씻", "씻을때", "비누칠", "비누질", "샤워", "신체청결"]) and any(k in q_norm for k in ["도움", "부분도움", "못함", "어려움", "필요"]):
        aliases.extend(["요양", "방문목욕", "목욕지원", "신체청결"])

    return list(dict.fromkeys(aliases))


def infer_direct_need_from_query(query, item):
    q = str(query or "").replace(" ", "")
    need_words = ["필요함", "필요하다", "필요로함", "필요로한다", "원함", "희망함", "받고싶", "도움이필요", "도움필요"]
    if not any(w in q for w in need_words):
        return False

    mid = str(item.get("중분류", "")).strip()

    if mid == "방문목욕" and any(k in q for k in ["목욕", "씻", "샤워", "비누칠", "비누질", "신체청결", "몸씻", "부분도움"]):
        return True

    if mid == "주거공간개선" and any(k in q for k in ["주거", "집", "보일러", "에어컨", "방역", "소독", "가스", "화기", "노후", "곰팡이", "해충", "악취"]):
        return True

    if mid == "의사소통지원" and any(k in q for k in ["의사소통", "언어장애", "말을못", "말못", "고개", "몸짓", "난청", "청각장애", "소리를알아듣지못", "소리를못알아듣", "듣지못함", "잘안들림"]):
        return True

    if mid == "스마트돌봄" and any(k in q for k in ["응급", "안부", "안전확인"]):
        return True

    if mid == "단기보호" and any(k in q for k in ["단기보호", "임시보호", "잠시맡", "며칠맡", "가족부재", "보호자부재", "맡아줄사람없"]):
        return True

    if mid == "치매전문관리" and any(k in q for k in ["기저귀", "조호물품", "소변실수", "배뇨실수"]):
        return True

    if "구강" in mid and any(k in q for k in ["구강", "입안", "입속", "칫솔질", "양치", "잇몸", "치아", "입냄새", "구취", "백태"]):
        return True

    return False

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

    # 케어내비 관련 기본 키워드
    care_keywords = [
        "어르신", "노인", "고령", "돌봄", "통합돌봄", "복지", "복지용구",
        "장기요양", "요양", "건강", "질환", "통증", "병원", "의료", "간호",
        "간병", "치매", "약", "복약", "식사", "영양", "반찬", "목욕", "위생",
        "청소", "세탁", "이동", "거동", "보행", "낙상", "배뇨", "배변",
        "욕창", "상처", "감염", "튜브", "비위관", "콧줄", "도뇨", "소변줄",
        "외로움", "고립", "말벗", "독거", "보호자", "가족", "주거", "안전",
        "방문", "재활", "장애", "지원", "서비스", "구강", "칫솔질", "양치",
        "언어장애", "의사소통", "응급", "단기보호", "기저귀", "조호물품",
        "보일러", "에어컨", "가스레인지", "화기"
    ]

    # 의미상 돌봄/생활불편/정서지원으로 볼 수 있는 표현
    meaning_keywords = [
        "잘어울리지못", "어울리지못", "대인관계", "관계어려움",
        "혼자지냄", "혼자있음", "혼자생활", "외출안", "밖에안나감",
        "고립", "고독", "우울", "불안", "외롭", "말상대", "말벗",
        "난청", "청각장애", "귀가어두움", "귀가어두워",
        "소리를못알아듣", "소리를알아듣지못", "말소리를못알아듣", "말소리를알아듣지못",
        "듣지못함", "잘못들음", "잘안들림", "소리가안들림", "의사소통어려움", "대화어려움",
        "입안", "입속", "입안관리", "입속관리", "구강관리",
        "도구필요", "보조도구", "보조기구", "지팡이필요",
        "보행기필요", "휠체어필요",

        "밥못", "식사못", "반찬못", "끼니", "먹기힘들", "챙겨먹기힘들",
        "배고프", "배고파", "배가고프", "배가고파", "허기", "허기짐", "허기지", "굶", "굶고", "못먹", "못먹음",
        "못씹", "씹기힘들", "씹지못", "씹는것", "저작", "연하곤란", "삼키기힘들", "삼키기어렵", "틀니", "이가없", "치아",
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

        "못함", "하지못함", "수행하지못함", "알아듣지못함",
        "듣지못함", "말하지못함", "소리내지못함",
        "도움필요", "부분도움", "전적인도움", "혼자못함",
        "구강건조", "입마름", "칫솔질", "잇몸출혈",
        "독거", "왕래하는가족없", "가족왕래없", "보호자없음",
        "응급서비스", "응급호출", "위급상황",
        "보일러교체", "에어컨설치", "가스레인지", "화기관리",
        "단기보호", "임시보호", "기저귀", "조호물품",
    ]


    if any(k in q_norm for k in ["못함", "하지못함", "도움필요", "부분도움"]) and any(
        c in q_norm for c in ["식사", "목욕", "씻", "이동", "청소", "세탁", "소변", "배변", "의사소통", "듣", "말", "구강", "칫솔질"]
    ):
        return False

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
        found_sigungu=found_sigungu,
        sido_options=SIDO_OPTIONS
    )


def extract_region_from_query(query: str):
    q = str(query or "").strip()
    q = q.replace(" ", "")

    found_sido = ""
    found_sigungu = ""

    sido_alias_map = {
        "전남광주통합특별시": "전남광주통합특별시",
        "전라남도": "전남광주통합특별시",
        "전남": "전남광주통합특별시",
        "광주광역시": "전남광주통합특별시",
        "광주": "전남광주통합특별시",
        "전라북도": "전라북도",
        "전북": "전라북도",
        "제주특별자치도": "제주특별자치도",
        "제주도": "제주특별자치도",
        "제주": "제주특별자치도"
    }

    sigungu_alias_map = {
        "목포시": ("전남광주통합특별시", "목포시"),
        "목포": ("전남광주통합특별시", "목포시"),
        "여수시": ("전남광주통합특별시", "여수시"),
        "여수": ("전남광주통합특별시", "여수시"),
        "순천시": ("전남광주통합특별시", "순천시"),
        "순천": ("전남광주통합특별시", "순천시"),
        "나주시": ("전남광주통합특별시", "나주시"),
        "나주": ("전남광주통합특별시", "나주시"),
        "광양시": ("전남광주통합특별시", "광양시"),
        "광양": ("전남광주통합특별시", "광양시"),
        "담양군": ("전남광주통합특별시", "담양군"),
        "담양": ("전남광주통합특별시", "담양군"),
        "곡성군": ("전남광주통합특별시", "곡성군"),
        "곡성": ("전남광주통합특별시", "곡성군"),
        "구례군": ("전남광주통합특별시", "구례군"),
        "구례": ("전남광주통합특별시", "구례군"),
        "고흥군": ("전남광주통합특별시", "고흥군"),
        "고흥": ("전남광주통합특별시", "고흥군"),
        "보성군": ("전남광주통합특별시", "보성군"),
        "보성": ("전남광주통합특별시", "보성군"),
        "화순군": ("전남광주통합특별시", "화순군"),
        "화순": ("전남광주통합특별시", "화순군"),
        "장흥군": ("전남광주통합특별시", "장흥군"),
        "장흥": ("전남광주통합특별시", "장흥군"),
        "강진군": ("전남광주통합특별시", "강진군"),
        "강진": ("전남광주통합특별시", "강진군"),
        "해남군": ("전남광주통합특별시", "해남군"),
        "해남": ("전남광주통합특별시", "해남군"),
        "영암군": ("전남광주통합특별시", "영암군"),
        "영암": ("전남광주통합특별시", "영암군"),
        "무안군": ("전남광주통합특별시", "무안군"),
        "무안": ("전남광주통합특별시", "무안군"),
        "함평군": ("전남광주통합특별시", "함평군"),
        "함평": ("전남광주통합특별시", "함평군"),
        "영광군": ("전남광주통합특별시", "영광군"),
        "영광": ("전남광주통합특별시", "영광군"),
        "장성군": ("전남광주통합특별시", "장성군"),
        "장성": ("전남광주통합특별시", "장성군"),
        "완도군": ("전남광주통합특별시", "완도군"),
        "완도": ("전남광주통합특별시", "완도군"),
        "진도군": ("전남광주통합특별시", "진도군"),
        "진도": ("전남광주통합특별시", "진도군"),
        "신안군": ("전남광주통합특별시", "신안군"),
        "신안": ("전남광주통합특별시", "신안군"),

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

        "동구": ("전남광주통합특별시", "동구"),
        "서구": ("전남광주통합특별시", "서구"),
        "남구": ("전남광주통합특별시", "남구"),
        "북구": ("전남광주통합특별시", "북구"),
        "광산구": ("전남광주통합특별시", "광산구"),
        "광산": ("전남광주통합특별시", "광산구"),
        "광주동구": ("전남광주통합특별시", "동구"),
        "광주서구": ("전남광주통합특별시", "서구"),
        "광주남구": ("전남광주통합특별시", "남구"),
        "광주북구": ("전남광주통합특별시", "북구"),
        "광주광역시동구": ("전남광주통합특별시", "동구"),
        "광주광역시서구": ("전남광주통합특별시", "서구"),
        "광주광역시남구": ("전남광주통합특별시", "남구"),
        "광주광역시북구": ("전남광주통합특별시", "북구"),

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
    ["의자나 소파에서 걸터앉은 상태에서 무릎을 짚고 일어설 수 있습니까?",
     "도움 없이 혼자서 수행 가능", "보조도구(지팡이 등)를 잡고 수행 가능", "타인이 도와줘야 수행 가능"],
    ["집안에서 6걸음을 이동할 수 있습니까?",
     "도움 없이 혼자서 수행 가능", "보조도구(지팡이 등)를 잡고 수행 가능", "타인이 도와줘야 수행 가능"],
    ["등을 제외한 몸 전체를 씻을 수 있습니까?",
     "도움 없이 혼자서 수행 가능", "필요 도구를 준비해 주면 수행 가능", "타인이 도와줘야 수행 가능"],
    ["상의를 입고 단추를 잠글 수 있습니까?",
     "도움 없이 혼자서 수행 가능", "상의를 준비해 주면 수행 가능", "타인이 도와줘야 수행 가능"],
    ["하의를 입고 지퍼를 올릴 수 있습니까?",
     "도움 없이 혼자서 수행 가능", "하의를 준비해 주면 수행 가능", "타인이 도와줘야 수행 가능"],
    ["소변실수를 하지 않고 화장실에 갈 수 있습니까?",
     "요실금 없음", "주 1회 정도 실금함", "주 2회 이상 실금함"],
    ["화장실에서 변기에 앉아 용변을 볼 수 있습니까?",
     "도움 없이 혼자서 수행 가능", "보조도구(지팡이 등)를 잡고 수행 가능", "타인이 도와줘야 수행 가능"]
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
body{ background:#e8ecf4; font-family:'Pretendard',sans-serif; color:#111827; font-size:13px; }
.page-wrap{ max-width:860px; margin:0 auto; padding:20px 16px 60px 16px; min-width:0; word-break:keep-all; }

/* ── 상단 바 ── */
.top-bar{ display:flex; justify-content:space-between; align-items:center; margin-bottom:14px; gap:10px; flex-wrap:wrap; padding:6px 0; }
.home-btn{ display:inline-flex; align-items:center; justify-content:center; gap:5px; height:34px; padding:0 15px; border-radius:8px; background:#ffffff; border:1px solid #e5e7eb; color:#6b7280; text-decoration:none; font-size:13px; font-weight:600; box-shadow:0 2px 6px rgba(15,23,42,0.08); transition:all .15s; }
.home-btn:hover{ background:#f3f4f6; color:#374151; }
.btn-group{ display:flex; gap:10px; }
.reset-btn{ display:inline-flex; align-items:center; justify-content:center; gap:5px; height:34px; padding:0 15px; border-radius:8px; background:#ffffff; border:1px solid #e5e7eb; color:#6b7280; font-size:13px; font-weight:600; cursor:pointer; box-shadow:0 2px 6px rgba(15,23,42,0.08); transition:all .15s; }
.reset-btn:hover{ background:#f3f4f6; color:#374151; }

/* ── 폼 카드 ── */
.form-card{ background:#fff; border-radius:16px; padding:28px 24px; box-shadow:0 10px 26px rgba(15,23,42,0.10); overflow-x:auto; }
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

/* === 버튼 누름 효과 B (디자인 전용) === */
button, input[type="submit"], input[type="button"], a.card, .btn, .home-btn, .home-button, .reset-btn, .home-help-btn, .home-notice-btn, .tip-btn, #fabMain, .fab-item, [class*="-btn"], [class*="-button"] { transition:transform .12s ease, box-shadow .12s ease; }
button:active, input[type="submit"]:active, input[type="button"]:active, .btn:active, .home-btn:active, .home-button:active, .reset-btn:active, .home-help-btn:active, .home-notice-btn:active, .tip-btn:active, #fabMain:active, .fab-item:active, [class*="-btn"]:active, [class*="-button"]:active { transform:scale(0.92) !important; }
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
          <b class="question-title">{{i+1}}) {{q[0]}}</b>
          <div class="options">
            <label><input type="radio" name="q{{i}}" value="0"> {{q[1]}} (0점)</label>
            <label><input type="radio" name="q{{i}}" value="1"> {{q[2]}} (1점)</label>
            <label><input type="radio" name="q{{i}}" value="2"> {{q[3]}} (2점)</label>
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
<style>{{style}}
/* === 버튼 누름 효과 B (디자인 전용) === */
button, input[type="submit"], input[type="button"], a.card, .btn, .home-btn, .home-button, .reset-btn, .home-help-btn, .home-notice-btn, .tip-btn, #fabMain, .fab-item, [class*="-btn"], [class*="-button"] { transition:transform .12s ease, box-shadow .12s ease; }
button:active, input[type="submit"]:active, input[type="button"]:active, .btn:active, .home-btn:active, .home-button:active, .reset-btn:active, .home-help-btn:active, .home-notice-btn:active, .tip-btn:active, #fabMain:active, .fab-item:active, [class*="-btn"]:active, [class*="-button"]:active { transform:scale(0.92) !important; }
</style>

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
  box-shadow:0 10px 26px rgba(15,23,42,0.10);
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

/* === 버튼 누름 효과 B (디자인 전용) === */
button, input[type="submit"], input[type="button"], a.card, .btn, .home-btn, .home-button, .reset-btn, .home-help-btn, .home-notice-btn, .tip-btn, #fabMain, .fab-item, [class*="-btn"], [class*="-button"] { transition:transform .12s ease, box-shadow .12s ease; }
button:active, input[type="submit"]:active, input[type="button"]:active, .btn:active, .home-btn:active, .home-button:active, .reset-btn:active, .home-help-btn:active, .home-notice-btn:active, .tip-btn:active, #fabMain:active, .fab-item:active, [class*="-btn"]:active, [class*="-button"]:active { transform:scale(0.92) !important; }
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
body{ background:#e8ecf4; font-family:'Pretendard',sans-serif; color:#111827; font-size:13px; }
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
.form-card{ background:#fff; border-radius:0 16px 16px 16px; padding:28px 24px; box-shadow:0 10px 26px rgba(15,23,42,0.10); overflow-x:auto; }
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
.paren-sm,.paren-sm label,.paren-sm span{ font-size:10.5px !important; }
.opt-group{ display:inline-flex; align-items:center; flex-wrap:wrap; vertical-align:middle; max-width:100%; gap:0 3px; }
.opt-group > label{ display:inline-flex; align-items:center; line-height:1.4; }
.sub-paren{ font-size:10.5px; color:#374151; }
.sub-paren label{ font-size:10.5px !important; }
.sub-paren input[type=checkbox]{ width:12px !important; height:12px !important; flex-shrink:0; }
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
  .radio-group input[type=radio],.radio-group input[type=checkbox],.check-group input[type=radio],.check-group input[type=checkbox]{ width:14px !important; height:14px !important; }
  .wrap-below .sub-paren{ display:block; margin-top:2px; }
  .paren-sm,.paren-sm label,.paren-sm span{ font-size:9px !important; }
  .sub-paren{ font-size:9px; }
  .sub-paren label{ font-size:9px !important; }
  .sub-paren input[type=checkbox]{ width:11px !important; height:11px !important; }
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
  .adl-table thead tr th:nth-child(2),.adl-table thead tr th:nth-child(3),.adl-table thead tr th:nth-child(4),.adl-table thead tr th:nth-child(6),.adl-table thead tr th:nth-child(7),.adl-table thead tr th:nth-child(8){ width:32px; word-break:break-all; }
  .adl-table tbody tr td:nth-child(5){ text-align:left; }
  .th-internet-pc{ display:none !important; }
  .th-internet-mo{ display:block !important; font-size:10px; }
  span.th-internet-mo{ display:inline !important; }
  .th-internet{ font-size:10px !important; }
  .th-internet-mo input[type=checkbox]{ margin:0 !important; padding:0 !important; vertical-align:middle !important; }
  .bottom-action-bar{
    display:flex !important;
    justify-content:space-between !important;
    align-items:center !important;
    flex-wrap:nowrap !important;
    gap:5px !important;
    margin-top:20px !important;
  }
  .bottom-action-bar > .home-btn{
    flex:0 0 auto !important;
    margin-right:auto !important;
  }
  .bottom-action-bar > .btn-group,
  .bottom-action-bar > div{
    margin-left:auto !important;
    display:flex !important;
    gap:5px !important;
    flex-wrap:nowrap !important;
    align-items:center !important;
    justify-content:flex-end !important;
  }
  .relay-service-reason{
  flex-basis:auto !important;
  display:inline !important;
  margin-top:0 !important;
}
.relay-service-input{
  flex-basis:100% !important;
  width:100% !important;
  max-width:100% !important;
  display:block !important;
  margin-top:2px !important;
}
  .adl-table td span{
    font-size:9px !important;
  }

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


/* === 버튼 누름 효과 B (디자인 전용) === */
button, input[type="submit"], input[type="button"], a.card, .btn, .home-btn, .home-button, .reset-btn, .home-help-btn, .home-notice-btn, .tip-btn, #fabMain, .fab-item, [class*="-btn"], [class*="-button"] { transition:transform .12s ease, box-shadow .12s ease; }
button:active, input[type="submit"]:active, input[type="button"]:active, .btn:active, .home-btn:active, .home-button:active, .reset-btn:active, .home-help-btn:active, .home-notice-btn:active, .tip-btn:active, #fabMain:active, .fab-item:active, [class*="-btn"]:active, [class*="-button"]:active { transform:scale(0.92) !important; }

/* 치매 관련 약물 사진 보기: 기존 디자인과 격리 */
/* 사전조사: 제목 표시줄의 버튼을 세로 중앙·오른쪽 정렬 */
#panel-care #gt-dementia .section-header{display:flex;align-items:center;gap:6px;min-height:34px;padding-top:4px;padding-bottom:4px}
#panel-care #gt-dementia .dementia-med-open{display:inline-flex;align-items:center;justify-content:center;margin:0 0 0 auto;padding:0 9px;height:25px;font-size:11px;line-height:1;white-space:nowrap;flex:0 0 auto;box-shadow:none}
/* 모바일: 화면 오른쪽의 고정 점수 배너가 차지하는 영역을 비워 둠 */
@media (max-width:600px){ #panel-care #gt-dementia .section-header{padding-right:106px;gap:4px}#panel-care #gt-dementia .dementia-med-open{height:24px;padding:0 7px;font-size:10px}}
@media (max-width:380px){ #panel-care #gt-dementia .section-header{flex-wrap:wrap}}

.dementia-med-open{margin-top:12px;border:1px solid #a5b4fc;background:#fff;color:#3730a3;border-radius:9px;padding:9px 14px;font-size:12.5px;font-weight:700;cursor:pointer;box-shadow:0 2px 7px rgba(75,110,220,.09)}
.dementia-med-open:hover{background:#eef2ff}
.dementia-med-overlay{display:none;position:fixed;inset:0;z-index:12000;background:rgba(17,24,39,.60);padding:18px;overflow-y:auto;align-items:center;justify-content:center}
.dementia-med-overlay.dementia-med-show{display:flex}
.dementia-med-dialog{background:#fff;width:100%;max-width:650px;max-height:calc(100dvh - 36px);overflow-y:auto;padding:22px;border-radius:17px;box-shadow:0 16px 45px rgba(0,0,0,.2)}
.dementia-med-heading{display:flex;align-items:center;justify-content:space-between;gap:10px}
.dementia-med-heading h3{margin:0;color:#2d3a6e;font-size:19px}
.dementia-med-x{border:0;background:#f1f5f9;color:#475569;border-radius:8px;font-size:24px;line-height:1;width:34px;height:34px;cursor:pointer}
.dementia-med-caption{color:#64748b;line-height:1.65;margin:12px 0;font-size:12px;word-break:keep-all;overflow-wrap:break-word}
.dementia-med-note{display:flex;align-items:flex-start;gap:4px}
.dementia-med-note-mark{flex:none}
.dementia-med-note > span:last-child{min-width:0;word-break:keep-all;overflow-wrap:break-word}
/* 모바일에서만 문장 사이 줄바꿈, 기존 ※ 들여쓰기 유지 */
.dementia-med-mobile-break{display:none}
@media(max-width:600px){.dementia-med-mobile-break{display:initial}}
.dementia-med-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px;margin:16px 0}
.dementia-med-item{border:1px solid #e2e8f0;border-radius:12px;padding:12px;text-align:center;min-width:0}
.dementia-med-item b{display:block;font-size:13px;margin-bottom:8px;color:#334155}
.dementia-med-item img{display:block;width:100%;height:155px;object-fit:contain;background:#fff}
.dementia-med-item img[hidden]{display:none}
.dementia-med-missing{display:block;padding:45px 5px;background:#f8fafc;color:#94a3b8;font-size:12px}
.dementia-med-missing[hidden]{display:none}
.dementia-med-close{border:0;background:#5b7ee5;border-radius:10px;color:white;font-size:14px;font-weight:700;width:100%;padding:12px;cursor:pointer}
@media(max-width:520px){.dementia-med-dialog{padding:16px}.dementia-med-grid{grid-template-columns:1fr}.dementia-med-item img{height:180px}}
@media print{.dementia-med-open,.dementia-med-overlay{display:none !important}}
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
        <div class="section-header"><span>&#9632; 치매 관련 약 복용 여부</span><button type="button" class="dementia-med-open" onclick="openDementiaMedGuide()" aria-haspopup="dialog">&#128138; 치매약물</button></div>
        <div class="dementia-box">
          <b style="font-size:13.5px;display:block;margin-bottom:10px;">치매 관련 약을 복용 중이십니까?</b>
          <div class="dementia-options">
            <label><input type="radio" name="dementia" value="y"> 예</label>
            <label><input type="radio" name="dementia" value="n"> 아니오</label>
          </div>
          <div style="margin-top:12px;padding-top:10px;border-top:1px dashed #c7d2fe;text-align:center;font-size:12.5px;color:#4b5563;">
            약 이름을 모르시나요?
            <a href="#" onclick="if(window.openPill){openPill(true);} return false;" style="margin-left:4px;font-weight:800;color:#4338ca;text-decoration:none;white-space:nowrap;">📷 알약 사진으로 확인</a>
          </div>
        </div>
        </div>

        <div id="gt-adl" class="section-header">&#9632; 일상생활 수행능력(ADL) 조사</div>
        <div id="adlSection">
          {% for i,q in questions %}
          <div class="question-box">
            <b class="question-title">{{i+1}}) {{q[0]}}</b>
            <div class="options">
              <label><input type="radio" name="q{{i}}" value="0"> {{q[1]}} (0점)</label>
              <label><input type="radio" name="q{{i}}" value="1"> {{q[2]}} (1점)</label>
              <label><input type="radio" name="q{{i}}" value="2"> {{q[3]}} (2점)</label>
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
          <label><input type="radio" name="s_care" value="없음"> 없음</label>
          <label><input type="radio" name="s_care" value="배우자"> 배우자</label>
          <label><input type="radio" name="s_care" value="자녀"> 자녀(며느리·사위 포함)</label>
          <label><input type="radio" name="s_care" value="손자녀"> 손자녀</label>
          <label><input type="radio" name="s_care" value="친인척"> 친인척</label>
          <label><input type="radio" name="s_care" value="친구이웃"> 친구·이웃</label>
          <label><input type="radio" name="s_care" value="사적간병인"> 사적 간병인</label>
          <label><input type="radio" name="s_care" value="공적서비스"> 공적서비스 돌봄제공자(요양보호사 등)</label>
          <label><input type="radio" name="s_care" value="형제자매"> 형제·자매</label>
          <label><input type="radio" name="s_care" value="자원봉사자"> 자원봉사자</label>
          <span style="display:inline-flex;align-items:center;"><label><input type="radio" name="s_care" value="기타"> 기타</label>(<input type="text" class="etc-input" style="width:45px">)</span>
        </div></td></tr>
        <tr><th>가구<br>형태</th><td colspan="7"><div class="radio-group">
          <label><input type="radio" name="s_hh" value="독거"> 독거</label>
          <span class="opt-group"><label><input type="radio" name="s_hh" value="비독거"> 비독거</label><span class="sub-paren"><span style="white-space:nowrap;">(<label><input type="checkbox" name="s_hh_sub" value="부부"> 부부</label></span> <label><input type="checkbox" name="s_hh_sub" value="노부모"> 노부모</label> <label><input type="checkbox" name="s_hh_sub" value="자녀"> 자녀</label> <label><input type="checkbox" name="s_hh_sub" value="조손"> 조손</label> <label><input type="checkbox" name="s_hh_sub" value="형제자매"> 형제자매</label> <label><input type="checkbox" name="s_hh_sub" value="장애인가구"> 장애인가구</label> <label><input type="checkbox" name="s_hh_sub" value="다문화가구"> 다문화가구</label> <label><input type="checkbox" name="s_hh_sub" value="친척지인"> 친척·지인</label> <span style="white-space:nowrap;"><label><input type="checkbox" name="s_hh_sub" value="기타"> 기타</label>(<input type="text" class="etc-input" style="width:55px">))</span></span></span>
        </div></td></tr>
        <tr><th>사회보장<br>수급권</th><td colspan="7"><div class="check-group" style="flex-direction:column;align-items:flex-start;gap:6px;">
          <div style="display:flex;flex-wrap:wrap;gap:4px 10px;align-items:center;">
            <span class="opt-group"><label><input type="checkbox" name="s_wf2" value="국민기초"> 국민기초생활보장제도</label><span class="sub-paren"><span style="white-space:nowrap;">(<label><input type="checkbox" name="s_wf_sub" value="생계급여"> 생계급여</label></span> <label><input type="checkbox" name="s_wf_sub" value="의료급여"> 의료급여</label> <span style="white-space:nowrap;"><label><input type="checkbox" name="s_wf_sub" value="주거급여"> 주거급여</label>)</span></span></span>
            <label><input type="checkbox" name="s_wf" value="차상위"> 차상위</label>
            <label><input type="checkbox" name="s_wf" value="일반보훈"> 일반(보훈)</label>
            <label><input type="checkbox" name="s_wf2" value="기초연금"> 기초연금</label>
            <label><input type="checkbox" name="s_wf2" value="일반가구"> 일반가구</label>
          </div>
        </div></td></tr>
        <tr><th>대상자<br>유형</th><td colspan="7"><div class="check-group" style="flex-direction:column;align-items:flex-start;gap:6px;">
          <div style="display:flex;flex-wrap:wrap;gap:4px 10px;align-items:center;">
            <span class="opt-group wrap-below"><label><input type="checkbox" name="s_tt" value="장기요양재가"> 장기요양 재가급여자</label><span class="sub-paren"><span style="white-space:nowrap;">(<label><input type="checkbox" name="s_tg" value="1등급"> 1등급</label></span> <label><input type="checkbox" name="s_tg" value="2등급"> 2등급</label> <label><input type="checkbox" name="s_tg" value="3등급"> 3등급</label> <label><input type="checkbox" name="s_tg" value="4등급"> 4등급</label> <label><input type="checkbox" name="s_tg" value="5등급"> 5등급</label> <span style="white-space:nowrap;"><label><input type="checkbox" name="s_tg" value="인지등급"> 인지등급</label>)</span></span></span>
          </div>
          <div style="display:flex;flex-wrap:wrap;gap:4px 10px;align-items:center;">
            <label><input type="checkbox" name="s_tt" value="장기요양등급외"> 장기요양 등급외(A, B)</label>
            <label><input type="checkbox" name="s_tt" value="기각각하"> 기각·각하</label>
            <label><input type="checkbox" name="s_tt" value="등급판정신청중"> 장기요양 등급판정 신청 중</label>
          </div>
          <div style="display:flex;flex-wrap:wrap;gap:4px 10px;align-items:center;">
            <span class="opt-group"><label><input type="checkbox" name="s_tt" value="노인맞춤돌봄"> 노인맞춤돌봄서비스</label><span class="sub-paren"><span style="white-space:nowrap;">(<label><input type="checkbox" name="s_tc" value="일반돌봄군"> 일반돌봄군</label></span> <span style="white-space:nowrap;"><label><input type="checkbox" name="s_tc" value="중점돌봄군"> 중점돌봄군</label>)</span></span></span>
            <span class="opt-group"><label><input type="checkbox" name="s_tt" value="퇴원예정자"> 퇴원(예정)자</label><span class="sub-paren"><span style="white-space:nowrap;">(<label><input type="checkbox" name="s_td" value="의료기관연계"> 의료기관 연계</label></span> <span style="white-space:nowrap;"><label><input type="checkbox" name="s_td" value="지역사회발굴"> 지역사회 발굴</label>)</span></span></span>
          </div>
          <div style="display:flex;flex-wrap:wrap;gap:4px 10px;align-items:center;">
            <span class="opt-group"><label><input type="checkbox" name="s_tt" value="장애등록"> 장애등록·정도</label><span class="sub-paren"><span style="white-space:nowrap;">(<label><input type="checkbox" name="s_tdi" value="심한장애"> 심한 장애</label></span> <span style="white-space:nowrap;"><label><input type="checkbox" name="s_tdi" value="심하지않은장애"> 심하지 않은 장애</label>)</span></span></span>
            <span style="display:inline-flex;align-items:center;"><label><input type="checkbox" name="s_tt" value="기타"> 기타</label>(<input type="text" class="etc-input" style="width:90px">)</span>
            <label><input type="checkbox" name="s_tt" value="해당없음"> 해당 없음</label>
          </div>
        </div></td></tr>
        <tr><th>현재 이용중인<br>서비스</th><td colspan="7"><div class="check-group" style="flex-wrap:wrap;gap:4px 8px;">
          <label><input type="radio" name="s_cs" value="없음"> 없음</label>
          <span class="opt-group"><label><input type="radio" name="s_cs" value="있음"> 있음</label><span class="sub-paren"><span style="white-space:nowrap;">(<label><input type="checkbox" name="s_csd" value="노인맞춤돌봄"> 노인맞춤돌봄서비스</label></span> <label><input type="checkbox" name="s_csd" value="치매안심센터"> 치매안심센터</label> <label><input type="checkbox" name="s_csd" value="급식도시락반찬"> 급식 및 도시락 반찬</label> <label><input type="checkbox" name="s_csd" value="활동보조"> 활동보조</label> <label><input type="checkbox" name="s_csd" value="말벗"> 말벗</label> <label><input type="checkbox" name="s_csd" value="보건소사업"> 보건소사업</label> <label><input type="checkbox" name="s_csd" value="주거개선사업"> 주거개선사업</label> <label><input type="checkbox" name="s_csd" value="건강운동교실"> 건강운동교실</label> <label><input type="checkbox" name="s_csd" value="목욕이미용"> 목욕·이미용</label> <label><input type="checkbox" name="s_csd" value="이동지원"> 이동지원</label> <label><input type="checkbox" name="s_csd" value="노인일자리사업"> 노인일자리 사업</label> <label><input type="checkbox" name="s_csd" value="무료진료연계"> 무료진료연계</label> <label><input type="checkbox" name="s_csd" value="가사간병방문도움"> 가사간병방문도움</label> <label><input type="checkbox" name="s_csd" value="여가문화교육"> 여가, 문화, 교육</label> <span style="white-space:nowrap;"><label><input type="checkbox" name="s_csd" value="기타"> 기타</label>(<input type="text" class="etc-input" style="width:60px">))</span></span></span>
        </div></td></tr>
      </table>

      <div class="section-header">&#9632; 주거환경상태<br><span style="font-weight:400;font-size:11px;">(현장조사 시 조사자가 확인 / 병원조사인 경우 생략 가능)</span></div>
      <table class="form-table">
        <tr><th>생활방식</th><td colspan="5"><div class="radio-group">
          <label><input type="checkbox" name="s_ls" value="단독보행"> 단독보행</label>
          <label><input type="checkbox" name="s_ls_sub" value="클러치사용"> 클러치사용</label>
          <label><input type="checkbox" name="s_ls_sub" value="좌식생활"> 좌식생활</label>
          <label><input type="checkbox" name="s_ls_sub" value="휠체어사용"> 휠체어사용</label>
          <label><input type="checkbox" name="s_ls" value="와상생활"> 와상생활</label>
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
          <span style="display:inline-flex;align-items:center;"><label><input type="radio" name="s_ht" value="기타"> 기타</label>(<input type="text" class="etc-input">)</span>
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
          <span style="display:inline-flex;align-items:center;"><label><input type="radio" name="s_heat" value="기타"> 기타</label>(<input type="text" class="etc-input" style="width:120px">)</span>
        </div></td></tr>
        <tr><th>화장실<br>형태</th><td colspan="5"><div class="radio-group">
          <label><input type="radio" name="s_tlt" value="공용"> 공용</label>
          <label><input type="radio" name="s_tlt" value="전용"> 전용</label>
          <span style="color:#cbd5e1;">|</span>
          <label><input type="radio" name="s_tlt2" value="수세식"> 수세식</label>
          <label><input type="radio" name="s_tlt2" value="재래식"> 재래식</label>
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
      </table>
      </div><!-- /gt-section-wrap -->

      <div class="section-header">&#9632; 일상생활기능</div>
      <table class="adl-table">
        <thead><tr>
          <th style="width:30%">구분</th><th>완전자립</th><th>부분도움</th><th>완전도움</th>
          <th style="width:30%">구분</th><th>완전자립</th><th>부분도움</th><th>완전도움</th>
        </tr></thead>
        <tbody>
          <tr>
            <td>옷 입기<br><span style="font-size:11px;color:#6b7280;">(옷 꺼내기, 단추·지퍼·벨트 채우기)</span></td>
            <td><input type="radio" name="s_adl_dress" value="완전자립"></td><td><input type="radio" name="s_adl_dress" value="부분도움"></td><td><input type="radio" name="s_adl_dress" value="완전도움"></td>
            <td>누웠다 일어나 방 밖으로 나가기</td>
            <td><input type="radio" name="s_adl_move" value="완전자립"></td><td><input type="radio" name="s_adl_move" value="부분도움"></td><td><input type="radio" name="s_adl_move" value="완전도움"></td>
          </tr>
          <tr>
            <td>세수, 양치질, 머리감기</td>
            <td><input type="radio" name="s_adl_wash" value="완전자립"></td><td><input type="radio" name="s_adl_wash" value="부분도움"></td><td><input type="radio" name="s_adl_wash" value="완전도움"></td>
            <td>화장실 출입과 대소변 후 닦고 옷 입기</td>
            <td><input type="radio" name="s_adl_toilet" value="완전자립"></td><td><input type="radio" name="s_adl_toilet" value="부분도움"></td><td><input type="radio" name="s_adl_toilet" value="완전도움"></td>
          </tr>
          <tr>
            <td>목욕 또는 샤워하기<br><span style="font-size:11px;color:#6b7280;">(욕조 드나들기, 때밀기, 샤워)</span></td>
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

      <div class="section-header">&#9632; 도구적 일상생활기능</div>
      <table class="adl-table">
        <thead><tr>
          <th style="width:30%">구분</th><th>완전자립</th><th>부분도움</th><th>완전도움</th>
          <th style="width:30%">구분</th><th>완전자립</th><th>부분도움</th><th>완전도움</th>
        </tr></thead>
        <tbody>
          <tr>
            <td>몸단장<br><span style="font-size:11px;color:#6b7280;">(빗질, 화장, 면도 등)</span></td>
            <td><input type="radio" name="s_iadl_groom" value="완전자립"></td><td><input type="radio" name="s_iadl_groom" value="부분도움"></td><td><input type="radio" name="s_iadl_groom" value="완전도움"></td>
            <td>금전 관리<br><span style="font-size:11px;color:#6b7280;">(용돈, 통장관리, 재산관리)</span></td>
            <td><input type="radio" name="s_iadl_money" value="완전자립"></td><td><input type="radio" name="s_iadl_money" value="부분도움"></td><td><input type="radio" name="s_iadl_money" value="완전도움"></td>
          </tr>
          <tr>
            <td>집안일<br><span style="font-size:11px;color:#6b7280;">(실내청소, 집안정돈 등)</span></td>
            <td><input type="radio" name="s_iadl_house" value="완전자립"></td><td><input type="radio" name="s_iadl_house" value="부분도움"></td><td><input type="radio" name="s_iadl_house" value="완전도움"></td>
            <td>근거리 외출하기<br><span style="font-size:11px;color:#6b7280;">(가까운 거리 걸어서)</span></td>
            <td><input type="radio" name="s_iadl_out" value="완전자립"></td><td><input type="radio" name="s_iadl_out" value="부분도움"></td><td><input type="radio" name="s_iadl_out" value="완전도움"></td>
          </tr>
          <tr>
            <td>식사준비<br><span style="font-size:11px;color:#6b7280;">(음식재료준비, 요리 등)</span></td>
            <td><input type="radio" name="s_iadl_cook" value="완전자립"></td><td><input type="radio" name="s_iadl_cook" value="부분도움"></td><td><input type="radio" name="s_iadl_cook" value="완전도움"></td>
            <td>물건 구매 결정, 돈 지불, 거스름돈 받기</td>
            <td><input type="radio" name="s_iadl_buy" value="완전자립"></td><td><input type="radio" name="s_iadl_buy" value="부분도움"></td><td><input type="radio" name="s_iadl_buy" value="완전도움"></td>
          </tr>
          <tr>
            <td>빨래<br><span style="font-size:11px;color:#6b7280;">(세탁후 널어말리기 포함)</span></td>
            <td><input type="radio" name="s_iadl_laundry" value="완전자립"></td><td><input type="radio" name="s_iadl_laundry" value="부분도움"></td><td><input type="radio" name="s_iadl_laundry" value="완전도움"></td>
            <td>전화 걸고 받기</td>
            <td><input type="radio" name="s_iadl_phone" value="완전자립"></td><td><input type="radio" name="s_iadl_phone" value="부분도움"></td><td><input type="radio" name="s_iadl_phone" value="완전도움"></td>
          </tr>
          <tr>
            <td>제시간에 정해진 양의 약 챙겨 먹기</td>
            <td><input type="radio" name="s_iadl_med" value="완전자립"></td><td><input type="radio" name="s_iadl_med" value="부분도움"></td><td><input type="radio" name="s_iadl_med" value="완전도움"></td>
            <td>교통수단 이용하기<br><span style="font-size:11px;color:#6b7280;">(대중교통, 개인 차)</span></td>
            <td><input type="radio" name="s_iadl_transit" value="완전자립"></td><td><input type="radio" name="s_iadl_transit" value="부분도움"></td><td><input type="radio" name="s_iadl_transit" value="완전도움"></td>
          </tr>
        </tbody>
      </table>

      <div class="section-header">&#9632; 식사기능</div>
      <table class="form-table">
        <tr><td>1) 하루에 몇 끼니를 챙겨드십니까? (간식 제외)</td><td><div class="radio-group">
          <label><input type="radio" name="s_meal_count" value="1끼"> &#9312; 1끼</label>
          <label><input type="radio" name="s_meal_count" value="2끼"> &#9313; 2끼</label>
          <label><input type="radio" name="s_meal_count" value="3끼"> &#9314; 3끼</label>
        </div></td></tr>
        <tr><td>2) 음식 씹는 기능</td><td><div class="radio-group">
          <label><input type="radio" name="s_chew" value="씹기어렵다"> &#9312; 씹기 어렵다</label>
          <label><input type="radio" name="s_chew" value="부드러운음식"> &#9313; 부드러운 음식을 잘 씹는다</label>
          <label><input type="radio" name="s_chew" value="어떤음식이든"> &#9314; 어떤 음식이든지 잘 씹는다</label>
        </div></td></tr>
        <tr><td>3) 음식을 삼키는 기능 <span style="font-weight:400;font-size:11px;color:#6b7280;">(연하곤란, 사례들림 등)</span></td><td><div class="radio-group">
          <label><input type="radio" name="s_swallow" value="삼키기어렵다"> &#9312; 삼키기 어렵다</label>
          <label><input type="radio" name="s_swallow" value="부드러운음식"> &#9313; 부드러운 음식을 잘 삼킨다</label>
          <label><input type="radio" name="s_swallow" value="어떤음식이든"> &#9314; 어떤 음식이든지 잘 삼킨다</label>
        </div></td></tr>
      </table>

      <div class="section-header">&#9632; 인지심리기능</div>
      <table class="form-table">
        <tr><td>1) 단기 기억력</td><td><div class="radio-group">
          <label><input type="radio" name="s_mem" value="정상"> &#9312; 정상</label>
          <label><input type="radio" name="s_mem" value="이상있음"> &#9313; 이상 있음</label>
          <label><input type="radio" name="s_mem" value="확인불가"> &#9314; 확인 불가</label>
        </div></td></tr>
        <tr><td>2) 일상생활 시에 관한 의사결정을 할 수 있는 인식 기술</td><td><div class="radio-group" style="flex-direction:column;align-items:flex-start;gap:6px;">
          <label><input type="radio" name="s_decision" value="합리적"> &#9312; 스스로 일관성 있고 합리적인 의사결정을 함</label>
          <label><input type="radio" name="s_decision" value="새로운상황"> &#9313; 새로운 상황에서만 의사결정의 어려움이 있음</label>
          <label><input type="radio" name="s_decision" value="다소손상"> &#9314; 인식기술이 다소 손상됨</label>
          <label><input type="radio" name="s_decision" value="심하게손상"> &#9315; 인식기술이 심하게 손상됨</label>
        </div></td></tr>
        <tr><td colspan="2">3) 우울정도</td></tr>
        <tr><td style="padding-left:18px;">(1) 2주 이상 거의 매일 하루 종일 슬프거나, 공허하거나 우울하게 지낸 적이 있습니까?</td><td><div class="radio-group"><label><input type="radio" name="s_dep1" value="예"> &#9312; 예</label><label><input type="radio" name="s_dep1" value="아니오"> &#9313; 아니오</label></div></td></tr>
        <tr><td style="padding-left:18px;">(2) 2주 이상 거의 매일 하루 종일 일이나 취미 혹은 평소에 좋아하는 것들 대부분 흥미를 잃어버린 적이 있습니까?</td><td><div class="radio-group"><label><input type="radio" name="s_dep2" value="예"> &#9312; 예</label><label><input type="radio" name="s_dep2" value="아니오"> &#9313; 아니오</label></div></td></tr>
      </table>

      <div class="section-header">&#9632; 병의원 이용</div>
      <table class="form-table">
        <tr><td>1) 정기적으로 방문하는 병원이 있습니까?</td><td><div class="radio-group"><label><input type="radio" name="s_hosp1" value="예"> &#9312; 예</label><label><input type="radio" name="s_hosp1" value="아니오"> &#9313; 아니오</label></div></td></tr>
        <tr><td>2) (최근 1년) 아프면 병원에 가지 못하고 참았던 적이 있습니까?</td><td><div class="radio-group"><label><input type="radio" name="s_hosp2" value="예" onchange="toggleHosp2sub()"> &#9312; 예(2-1번으로)</label><label><input type="radio" name="s_hosp2" value="아니오" onchange="toggleHosp2sub()"> &#9313; 아니오(3번으로)</label></div></td></tr>
        <tr id="s_hosp2_sub"><td style="padding-left:20px;">2-1) 병원에 가지 못한 이유</td><td><div class="check-group">
          <label><input type="checkbox" name="s_hr" value="경제적어려움"> &#9312; 경제적 어려움</label>
          <label><input type="checkbox" name="s_hr" value="거동불편"> &#9313; 거동이 불편해서</label>
          <label><input type="checkbox" name="s_hr" value="의료정보부족"> &#9314; 의료정보 부족</label>
          <label><input type="checkbox" name="s_hr" value="병원예약어려움"> &#9315; 병원 예약이 어려워서</label>
          <label><input type="checkbox" name="s_hr" value="증상가벼움"> &#9316; 증상이 가벼워서</label>
          <span style="display:inline-flex;align-items:center;"><label><input type="checkbox" name="s_hr" value="기타"> &#9317; 기타</label>(<input type="text" class="etc-input">)</span>
        </div></td></tr>
        <tr><td>3) 다른 사람이 병원에서 약을 처방받아준 적이 있습니까?</td><td><div class="radio-group"><label><input type="radio" name="s_prx" value="예"> &#9312; 예</label><label><input type="radio" name="s_prx" value="아니오"> &#9313; 아니오</label></div></td></tr>
        <tr><td>4) 기타 통증 및 불편 사항</td><td><div class="radio-group"><label><input type="radio" name="s_pain" value="없음"> &#9312; 없음</label><label><input type="radio" name="s_pain" value="다소있음"> &#9313; 다소 있음</label><label><input type="radio" name="s_pain" value="매우심함"> &#9314; 매우 심함</label></div></td></tr>
        <tr><td>5) 병명 및 복용 중인 약 <span style="font-weight:400;font-size:11px;color:#6b7280;">(지자체 조사인 경우 생략 가능)</span></td><td>병명: <input type="text" name="s_disease" class="etc-input" style="width:180px"><span class="th-internet-mo"><br></span><span class="th-internet-pc">&nbsp;</span>복용약: <input type="text" name="s_meds" class="etc-input" style="width:180px"></td></tr>
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
      <textarea class="form-textarea" name="s_opinion" style="min-height:80px;" placeholder="지자체 자체조사를 수행한 담당자가 대상자(보호자)의 현재 생활현황 및 필요로 하는 서비스 내용, 조사결과 대상자에게 제공되어야 할 서비스 내용(조사자 판단)을 종합적으로 기입함"></textarea>
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
          <label><input type="radio" name="r_care" value="없음"> 없음</label>
          <label><input type="radio" name="r_care" value="배우자"> 배우자</label>
          <label><input type="radio" name="r_care" value="자녀"> 자녀(며느리·사위 포함)</label>
          <label><input type="radio" name="r_care" value="손자녀"> 손자녀</label>
          <label><input type="radio" name="r_care" value="친인척"> 친인척</label>
          <label><input type="radio" name="r_care" value="친구이웃"> 친구·이웃</label>
          <label><input type="radio" name="r_care" value="사적간병인"> 사적 간병인</label>
          <label><input type="radio" name="r_care" value="공적서비스"> 공적서비스 돌봄제공자(요양보호사 등)</label>
          <label><input type="radio" name="r_care" value="형제자매"> 형제·자매</label>
          <label><input type="radio" name="r_care" value="자원봉사자"> 자원봉사자</label>
          <span style="display:inline-flex;align-items:center;"><label><input type="radio" name="r_care" value="기타"> 기타</label>(<input type="text" class="etc-input" style="width:45px">)</span>
        </div></td></tr>
        <tr><th>가구<br>형태</th><td colspan="7"><div class="radio-group">
          <label><input type="radio" name="r_hh" value="독거"> 독거</label>
          <span class="opt-group"><label><input type="radio" name="r_hh" value="비독거"> 비독거</label><span class="sub-paren"><span style="white-space:nowrap;">(<label><input type="checkbox" name="r_hh_sub" value="부부"> 부부</label></span> <label><input type="checkbox" name="r_hh_sub" value="노부모"> 노부모</label> <label><input type="checkbox" name="r_hh_sub" value="자녀"> 자녀</label> <label><input type="checkbox" name="r_hh_sub" value="조손"> 조손</label> <label><input type="checkbox" name="r_hh_sub" value="형제자매"> 형제자매</label> <label><input type="checkbox" name="r_hh_sub" value="장애인가구"> 장애인가구</label> <label><input type="checkbox" name="r_hh_sub" value="다문화가구"> 다문화가구</label> <label><input type="checkbox" name="r_hh_sub" value="친척지인"> 친척·지인</label> <span style="white-space:nowrap;"><label><input type="checkbox" name="r_hh_sub" value="기타"> 기타</label>(<input type="text" class="etc-input" style="width:55px">))</span></span></span>
        </div></td></tr>
        <tr><th>사회보장<br>수급권</th><td colspan="7">
          <div class="check-group" style="flex-direction:column;align-items:flex-start;gap:6px;margin-bottom:6px;">
            <div style="display:flex;flex-wrap:wrap;gap:4px 10px;align-items:center;">
              <span class="opt-group"><label><input type="checkbox" name="r_wf2" value="국민기초"> 국민기초생활보장제도</label><span class="sub-paren"><span style="white-space:nowrap;">(<label><input type="checkbox" name="r_wf_sub" value="생계급여"> 생계급여</label></span> <label><input type="checkbox" name="r_wf_sub" value="의료급여"> 의료급여</label> <span style="white-space:nowrap;"><label><input type="checkbox" name="r_wf_sub" value="주거급여"> 주거급여</label>)</span></span></span>
              <label><input type="checkbox" name="r_wf" value="차상위"> 차상위</label>
              <label><input type="checkbox" name="r_wf" value="일반보훈"> 일반(보훈)</label>
              <label><input type="checkbox" name="r_wf2" value="기초연금"> 기초연금</label>
              <label><input type="checkbox" name="r_wf2" value="일반가구"> 일반가구</label>
            </div>
          </div>
          <table style="border-collapse:collapse;width:100%;table-layout:fixed;">
            <tr><th style="border:1px solid #d1d5db;padding:5px 8px;background:#f8fafc;font-weight:600;text-align:center;white-space:nowrap;width:6.5em;">주수입원</th><td style="border:1px solid #d1d5db;padding:5px 8px;"><div class="check-group"><label><input type="checkbox" name="r_inc" value="공적연금"> 공적연금</label><label><input type="checkbox" name="r_inc" value="사적지원"> 사적지원(가족지원)</label><label><input type="checkbox" name="r_inc" value="근로수입"> 근로수입</label><span style="display:inline-flex;align-items:center;"><label><input type="checkbox" name="r_inc" value="기타"> 기타</label>(<input type="text" class="etc-input" style="width:50px">)</span></div></td></tr>
            <tr><th style="border:1px solid #d1d5db;padding:5px 8px;background:#f8fafc;font-weight:600;text-align:center;white-space:nowrap;width:6.5em;">본인부담<br>가능여부</th><td style="border:1px solid #d1d5db;padding:5px 8px;"><div class="check-group"><label><input type="radio" name="r_copay" value="부담가능"> 부담가능</label><label><input type="radio" name="r_copay" value="일부부담가능"> 일부 부담가능</label><label><input type="radio" name="r_copay" value="부담어려움"> 부담어려움</label></div></td></tr>
          </table>
        </td></tr>
        <tr><th>대상자<br>유형</th><td colspan="7"><div class="check-group" style="flex-direction:column;align-items:flex-start;gap:6px;">
          <div style="display:flex;flex-wrap:wrap;gap:4px 10px;align-items:center;">
            <label><input type="radio" name="r_tt" value="해당없음"> 해당없음</label>
            <span class="opt-group wrap-below"><label><input type="checkbox" name="r_tt" value="장기요양재가"> 장기요양 재가급여자</label><span class="sub-paren"><span style="white-space:nowrap;">(<label><input type="checkbox" name="r_tg" value="1등급"> 1등급</label></span> <label><input type="checkbox" name="r_tg" value="2등급"> 2등급</label> <label><input type="checkbox" name="r_tg" value="3등급"> 3등급</label> <label><input type="checkbox" name="r_tg" value="4등급"> 4등급</label> <label><input type="checkbox" name="r_tg" value="5등급"> 5등급</label> <span style="white-space:nowrap;"><label><input type="checkbox" name="r_tg" value="인지등급"> 인지등급</label>)</span></span></span>
          </div>
          <div style="display:flex;flex-wrap:wrap;gap:4px 10px;align-items:center;">
            <label><input type="checkbox" name="r_tt" value="장기요양등급외"> 장기요양 등급외(A, B)</label>
            <label><input type="checkbox" name="r_tt" value="기각각하"> 기각·각하</label>
            <label><input type="checkbox" name="r_tt" value="등급판정신청중"> 장기요양 등급판정 신청 중</label>
          </div>
          <div style="display:flex;flex-wrap:wrap;gap:4px 10px;align-items:center;">
            <span class="opt-group"><label><input type="checkbox" name="r_tt" value="노인맞춤돌봄"> 노인맞춤돌봄서비스</label><span class="sub-paren"><span style="white-space:nowrap;">(<label><input type="checkbox" name="r_tc" value="일반돌봄군"> 일반돌봄군</label></span> <span style="white-space:nowrap;"><label><input type="checkbox" name="r_tc" value="중점돌봄군"> 중점돌봄군</label>)</span></span></span>
            <span class="opt-group"><label><input type="checkbox" name="r_tt" value="퇴원예정자"> 퇴원(예정)자</label><span class="sub-paren"><span style="white-space:nowrap;">(<label><input type="checkbox" name="r_td" value="의료기관연계"> 의료기관 연계</label></span> <span style="white-space:nowrap;"><label><input type="checkbox" name="r_td" value="지역사회발굴"> 지역사회 발굴</label>)</span></span></span>
          </div>
          <div style="display:flex;flex-wrap:wrap;gap:4px 10px;align-items:center;">
            <span class="opt-group"><label><input type="checkbox" name="r_tt" value="활동지원신청"> 활동지원 신청여부</label><span class="sub-paren"><span style="white-space:nowrap;">(<label><input type="checkbox" name="r_act" value="미신청"> 미신청</label></span> <label><input type="checkbox" name="r_act" value="신청"> 신청</label> <label><input type="checkbox" name="r_act" value="수급자"> 수급자</label> <span style="white-space:nowrap;"><label><input type="checkbox" name="r_act" value="등급외"> 등급외</label>)</span></span></span>
            <span class="paren-sm" style="color:#6b7280;">* 6세 이상 65세 미만 장애인만 해당</span>
          </div>
          <div style="display:flex;flex-wrap:wrap;gap:4px 10px;align-items:center;">
            <span class="opt-group"><label><input type="checkbox" name="r_tt" value="장애등록"> 장애등록·정도</label><span class="sub-paren"><span style="white-space:nowrap;">(<label><input type="checkbox" name="r_tdi" value="심한장애"> 심한 장애</label></span> <span style="white-space:nowrap;"><label><input type="checkbox" name="r_tdi" value="심하지않은장애"> 심하지 않은 장애</label>)</span></span></span>
            <span class="opt-group wrap-below"><label><input type="checkbox" name="r_tt" value="장애유형"> 장애유형</label><span class="sub-paren"><span style="white-space:nowrap;">(<label><input type="checkbox" name="r_dtype" value="지체"> 지체</label></span> <label><input type="checkbox" name="r_dtype" value="뇌병변"> 뇌병변</label> <label><input type="checkbox" name="r_dtype" value="시각"> 시각</label> <label><input type="checkbox" name="r_dtype" value="청각"> 청각</label> <label><input type="checkbox" name="r_dtype" value="언어"> 언어</label> <label><input type="checkbox" name="r_dtype" value="지적"> 지적</label> <label><input type="checkbox" name="r_dtype" value="자폐성"> 자폐성</label> <label><input type="checkbox" name="r_dtype" value="정신"> 정신</label> <label><input type="checkbox" name="r_dtype" value="신장"> 신장</label> <label><input type="checkbox" name="r_dtype" value="심장"> 심장</label> <label><input type="checkbox" name="r_dtype" value="호흡기"> 호흡기</label> <label><input type="checkbox" name="r_dtype" value="간"> 간</label> <label><input type="checkbox" name="r_dtype" value="안면"> 안면</label> <label><input type="checkbox" name="r_dtype" value="장루요루"> 장루·요루</label> <span style="white-space:nowrap;"><label><input type="checkbox" name="r_dtype" value="뇌전증"> 뇌전증</label>)</span></span></span>
            <span class="paren-sm" style="color:#6b7280;">* 중복시 모두 체크</span>
          </div>
          <div style="display:flex;flex-wrap:wrap;gap:4px 10px;align-items:center;">
            <span style="display:inline-flex;align-items:center;"><label><input type="checkbox" name="r_tt" value="기타"> 기타</label>(<input type="text" class="etc-input" style="width:90px">)</span>
          </div>
        </div></td></tr>
        <tr><th>현재 이용중인<br>서비스</th><td colspan="7"><div class="check-group" style="flex-direction:column;align-items:flex-start;gap:6px;">
          <div style="display:flex;flex-wrap:wrap;gap:4px 8px;align-items:center;">
            <label><input type="radio" name="r_sv" value="없음"> 없음</label>
            <span class="relay-service-reason" style="color:#6b7280;">— 필요서비스 미이용 사유 (사유확인):</span>
            <input type="text" name="r_sv_confirm" class="etc-input relay-service-input" style="width:150px">
          </div>
          <div style="display:flex;flex-wrap:wrap;gap:4px 8px;align-items:center;">
            <span class="opt-group"><label><input type="radio" name="r_sv" value="있음"> 있음</label><span class="sub-paren"><span style="white-space:nowrap;">(<label><input type="checkbox" name="r_svd" value="노인맞춤돌봄"> 노인맞춤돌봄서비스</label></span> <label><input type="checkbox" name="r_svd" value="치매안심센터"> 치매안심센터</label> <label><input type="checkbox" name="r_svd" value="급식도시락반찬"> 급식 및 도시락 반찬</label> <label><input type="checkbox" name="r_svd" value="활동보조"> 활동보조</label> <label><input type="checkbox" name="r_svd" value="말벗"> 말벗</label> <label><input type="checkbox" name="r_svd" value="보건소사업"> 보건소사업</label> <label><input type="checkbox" name="r_svd" value="주거개선사업"> 주거개선사업</label> <label><input type="checkbox" name="r_svd" value="건강운동교실"> 건강운동교실</label> <label><input type="checkbox" name="r_svd" value="목욕이미용"> 목욕·이미용</label> <label><input type="checkbox" name="r_svd" value="이동지원"> 이동지원</label> <label><input type="checkbox" name="r_svd" value="노인일자리사업"> 노인일자리 사업</label> <label><input type="checkbox" name="r_svd" value="무료진료연계"> 무료진료연계</label> <label><input type="checkbox" name="r_svd" value="가사간병방문도움"> 가사간병방문도움</label> <label><input type="checkbox" name="r_svd" value="여가문화교육"> 여가, 문화, 교육</label> <span style="white-space:nowrap;"><label><input type="checkbox" name="r_svd" value="기타"> 기타</label>(<input type="text" class="etc-input" style="width:60px">))</span></span></span>
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
      <div class="top-bar bottom-action-bar">
        <a href="/home" class="home-btn">&#8962; 홈으로</a>
        <div class="btn-group">
          <button type="button" class="print-btn" onclick="openEmailPopup()">&#9993; 메일 보내기</button>
          <button type="button" class="print-btn" onclick="doPrint()">&#128196; 출력 / PDF 저장</button>
          <button type="button" class="reset-btn" onclick="resetForm()">&#8635; 다시 입력</button>
        </div>
      </div>
    </div><!-- /panel-relay -->

  </div><!-- /form-card -->


<!-- 치매약 사진 참고 팝업: 기존 조사 데이터/채점 로직과 별개 -->
<div id="dementiaMedModal" class="dementia-med-overlay" role="dialog" aria-modal="true" aria-labelledby="dementiaMedTitle" aria-hidden="true" onclick="if(event.target===this) closeDementiaMedGuide()">
  <div class="dementia-med-dialog">
    <div class="dementia-med-heading">
      <h3 id="dementiaMedTitle">치매 관련 약물 사진</h3>
      <button type="button" class="dementia-med-x" onclick="closeDementiaMedGuide()" aria-label="닫기">&times;</button>
    </div>
    <div class="dementia-med-grid">
      <div class="dementia-med-item"><b>도네페질 (Donepezil)</b><img src="/static/donepezil.jpg" alt="도네페질 약물 참고 사진" onerror="this.hidden=true;this.nextElementSibling.hidden=false"><span class="dementia-med-missing" hidden>사진을 추가하면 여기에 표시됩니다.</span></div>
      <div class="dementia-med-item"><b>갈란타민 (Galantamine)</b><img src="/static/galantamine.jpg" alt="갈란타민 약물 참고 사진" onerror="this.hidden=true;this.nextElementSibling.hidden=false"><span class="dementia-med-missing" hidden>사진을 추가하면 여기에 표시됩니다.</span></div>
      <div class="dementia-med-item"><b>리바스티그민 (Rivastigmine)</b><img src="/static/rivastigmine.jpg" alt="리바스티그민 약물 참고 사진" onerror="this.hidden=true;this.nextElementSibling.hidden=false"><span class="dementia-med-missing" hidden>사진을 추가하면 여기에 표시됩니다.</span></div>
      <div class="dementia-med-item"><b>메만틴 (Memantine)</b><img src="/static/memantine.jpg" alt="메만틴 약물 참고 사진" onerror="this.hidden=true;this.nextElementSibling.hidden=false"><span class="dementia-med-missing" hidden>사진을 추가하면 여기에 표시됩니다.</span></div>
    </div>
    <p class="dementia-med-caption dementia-med-note"><span class="dementia-med-note-mark">※</span><span>약의 모양은 제조사와 용량에 따라 다를 수 있습니다.</p>
    <button type="button" class="dementia-med-close" onclick="closeDementiaMedGuide()">닫기</button>
  </div>
</div>

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

/* 복약 참고 사진 전용: 설문 선택/채점/저장과 무관 */
function openDementiaMedGuide(){
  var modal=document.getElementById('dementiaMedModal');
  if(!modal) return;
  modal.classList.add('dementia-med-show');
  modal.setAttribute('aria-hidden','false');
  document.body.dataset.dementiaMedPrevOverflow=document.body.style.overflow;
  document.body.style.overflow='hidden';
  var btn=modal.querySelector('.dementia-med-x');if(btn)btn.focus();
}
function closeDementiaMedGuide(){
  var modal=document.getElementById('dementiaMedModal');
  if(!modal)return;
  modal.classList.remove('dementia-med-show');
  modal.setAttribute('aria-hidden','true');
  document.body.style.overflow=document.body.dataset.dementiaMedPrevOverflow||'';
  var btn=document.querySelector('.dementia-med-open');if(btn)btn.focus();
}
document.addEventListener('keydown',function(ev){if(ev.key==='Escape'&&document.getElementById('dementiaMedModal')?.classList.contains('dementia-med-show'))closeDementiaMedGuide()});

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

function toggleHosp2sub(){
  var sub = document.getElementById('s_hosp2_sub');
  if(!sub) return;
  var sel = document.querySelector('input[name="s_hosp2"]:checked');
  var enable = sel && sel.value === '예';
  sub.querySelectorAll('input').forEach(function(el){ el.disabled = !enable; });
  sub.style.opacity = enable ? '1' : '0.45';
  if(!enable){
    sub.querySelectorAll('input[type=checkbox]').forEach(function(el){ el.checked = false; });
    sub.querySelectorAll('input[type=text]').forEach(function(el){ el.value = ''; });
  }
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

/* ── 자체조사/연계조사 괄호 하위항목 자동 연동 ── */
function getOptGroupParentInput(group){
  if(!group) return null;
  for(var i=0; i<group.children.length; i++){
    var child = group.children[i];
    if(child.tagName && child.tagName.toLowerCase() === 'label'){
      var input = child.querySelector('input[type=radio], input[type=checkbox]');
      if(input) return input;
    }
  }
  return null;
}

function clearChildrenInGroup(group){
  if(!group) return;
  group.querySelectorAll('.sub-paren input[type=checkbox], .sub-paren input[type=radio]').forEach(function(child){
    child.checked = false;
  });
}

function clearInactiveRadioChildren(panel, radioName){
  if(!panel || !radioName) return;
  panel.querySelectorAll('.opt-group').forEach(function(group){
    var parent = getOptGroupParentInput(group);
    if(parent && parent.type === 'radio' && parent.name === radioName && !parent.checked){
      clearChildrenInGroup(group);
    }
  });
}

function handleSurveyParentChildSync(target){
  var panel = target.closest('#panel-self, #panel-relay');
  if(!panel) return;

  if(target.matches('input[name="s_tt"], input[name="r_tt"]')){
    var isNone = (target.value === '해당없음' || target.value === '해당 없음');
    if(target.checked && isNone){
      panel.querySelectorAll('input[name="' + target.name + '"]').forEach(function(el){
        if(el !== target) el.checked = false;
      });
      panel.querySelectorAll('.opt-group').forEach(function(group){
        var parent = getOptGroupParentInput(group);
        if(parent && parent.name === target.name) clearChildrenInGroup(group);
      });
    }else if(target.checked && !isNone){
      panel.querySelectorAll('input[name="' + target.name + '"]').forEach(function(el){
        if(el.value === '해당없음' || el.value === '해당 없음') el.checked = false;
      });
    }
  }

  var subParen = target.closest('.sub-paren');
  if(subParen && (target.type === 'checkbox' || target.type === 'radio')){
    var group = target.closest('.opt-group');
    var parent = getOptGroupParentInput(group);
    if(parent && target.checked){
      parent.checked = true;
      if(parent.type === 'radio') clearInactiveRadioChildren(panel, parent.name);
    }
    return;
  }

  if(target.matches('input[type=radio], input[type=checkbox]')){
    var parentGroup = target.closest('.opt-group');
    var parentInput = getOptGroupParentInput(parentGroup);

    if(parentInput === target && target.type === 'checkbox' && !target.checked){
      clearChildrenInGroup(parentGroup);
    }

    if(target.type === 'radio'){
      clearInactiveRadioChildren(panel, target.name);
    }
  }
}

document.addEventListener('change', function(e){
  if(e.target.closest('#panel-self, #panel-relay')){
    handleSurveyParentChildSync(e.target);
  }
});

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
  toggleHosp2sub();
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
toggleHosp2sub();

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


// 직접욕구 툴팁 — 인라인 onclick으로 처리(iOS 사파리 탭 지원). 바깥 클릭 시 닫기만 유지
document.addEventListener('click', function(){
  document.querySelectorAll('.direct-need-tooltip-box').forEach(function(b){ b.style.display='none'; });
});

// 가이드 투어 제거: 자동 실행하지 않음
</script>
{{ pill_html|default('')|safe }}
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

        body = MIMEText("통합돌봄 지자체 조사 서식 PDF를 첨부합니다.\n\n※ 본 메일은 케어내비 시스템에서 자동 발송되었습니다.", "plain", "utf-8")
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

# =========================================================
# 설문조사 (/satisfaction)
# - 공개: /satisfaction, /satisfaction/submit (로그인 없이 접근, QR용)
# - 관리자: /stats/satisfaction, /stats/satisfaction/export  (/stats 하위라 관리자 로그인 자동 적용)
# - 저장: Supabase survey_responses (연락처는 동의한 경우에만 저장, 응답과 같은 행에 연결)
# =========================================================
SAT_ORGS = ["공단", "지자체"]
SAT_REGIONS = ["전남광주통합특별시", "전북특별자치도", "제주특별자치도"]
SAT_SCALE = ["매우 그렇다", "그렇다", "보통이다", "그렇지 않다", "전혀 그렇지 않다"]
SAT_QUESTIONS = [
    {"key": "q1", "title": "케어내비를 얼마나 자주 이용하십니까?",
     "options": ["거의 매일", "주 1~2회", "월 1~2회", "처음 이용"]},
    {"key": "q2", "title": "케어내비가 필요한 복지서비스를 찾는 데 도움이 되었습니까?", "options": SAT_SCALE},
    {"key": "q3", "title": "케어내비 사용으로 업무 시간이 단축되었다고 생각하십니까?", "options": SAT_SCALE},
    {"key": "q4", "title": "기존 방식과 비교해 서비스 검색이 편리해졌습니까?", "options": SAT_SCALE},
]
SAT_Q5_TITLE = "기타 하고 싶은 말씀이 있다면 자유롭게 적어 주세요."

SATISFACTION_HTML = """
<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>케어내비 설문조사</title>
<style>
*{ box-sizing:border-box; }
body{ margin:0; background:#e8ecf4; font-family:'Pretendard',-apple-system,'Malgun Gothic',sans-serif; color:#111827; padding:16px; }
.wrap{ max-width:560px; margin:0 auto; }
.card{ background:#fff; border-radius:18px; padding:22px 20px; margin-bottom:14px; box-shadow:0 8px 24px rgba(0,0,0,.06); }
h1{ font-size:20px; margin:0 0 6px; font-weight:800; }
.sub{ font-size:13px; color:#6b7280; line-height:1.6; word-break:keep-all; }
.sec-title{ font-size:13px; font-weight:800; color:#4b6edc; margin-bottom:12px; }
.q-title{ font-size:15px; font-weight:800; line-height:1.5; margin-bottom:12px; word-break:keep-all; }
.opt{ display:flex; align-items:center; gap:10px; padding:12px 14px; border:1.5px solid #e5e7eb; border-radius:12px; margin-bottom:8px; font-size:14px; cursor:pointer; }
.opt input{ width:18px; height:18px; margin:0; accent-color:#4b6edc; }
.opt.sel{ border-color:#4b6edc; background:#eef2ff; font-weight:700; }
.field-label{ font-size:14px; font-weight:800; margin:16px 0 8px; }
.field-label:first-of-type{ margin-top:0; }
.notice{ font-size:12px; color:#6b7280; background:#f3f4f6; border-radius:10px; padding:10px 12px; line-height:1.6; margin-bottom:10px; word-break:keep-all; }
.consent{ display:flex; align-items:flex-start; gap:10px; font-size:13px; line-height:1.5; margin-bottom:10px; cursor:pointer; }
.consent input{ width:18px; height:18px; margin:1px 0 0; accent-color:#4b6edc; flex:none; }
input[type=tel], textarea{ width:100%; border:1.5px solid #e5e7eb; border-radius:12px; padding:12px 14px; font-size:15px; font-family:inherit; }
input[type=tel]:disabled{ background:#f3f4f6; }
textarea{ min-height:110px; resize:vertical; }
.submit{ width:100%; border:0; border-radius:14px; background:#4b6edc; color:#fff; font-size:16px; font-weight:800; padding:15px; cursor:pointer; }
.submit:disabled{ opacity:.6; }
.err{ color:#dc2626; font-size:13px; margin:0 0 10px; display:none; text-align:center; }
.done{ text-align:center; padding:40px 20px; display:none; }
.done .big{ font-size:44px; margin-bottom:10px; }
.done a{ display:inline-block; margin-top:18px; color:#4b6edc; font-weight:800; text-decoration:none; }
</style>
</head>
<body>
<div class="wrap">
  <div id="formArea">
    <div class="card">
      <h1>케어내비 설문조사</h1>
      <div class="sub">더 나은 서비스를 위한 설문입니다. 약 1분이 소요됩니다.</div>
    </div>

    <div class="card">
      <div class="sec-title">기본 정보</div>
      <div class="field-label">1. 소속 기관</div>
      {% for o in orgs %}
      <label class="opt"><input type="radio" name="org" value="{{ o }}"> {{ o }}</label>
      {% endfor %}
      <div class="field-label">2. 근무 지역</div>
      {% for r in regions %}
      <label class="opt"><input type="radio" name="region" value="{{ r }}"> {{ r }}</label>
      {% endfor %}
      <div class="field-label">3. 연락처 (경품 지급용)</div>
      <div class="notice">연락처는 경품 지급 목적으로만 수집하며, 설문 성과분석 데이터와 분리하여 관리합니다.</div>
      <label class="consent"><input type="checkbox" id="consent"> <span>경품 지급을 위한 연락처 수집·이용에 동의합니다. (선택)</span></label>
      <input type="tel" id="contact" placeholder="010-0000-0000" inputmode="numeric" maxlength="13" disabled>
    </div>

    {% for q in questions %}
    <div class="card">
      <div class="q-title">{{ loop.index }}. {{ q.title }}</div>
      {% for o in q.options %}
      <label class="opt"><input type="radio" name="{{ q.key }}" value="{{ o }}"> {{ o }}</label>
      {% endfor %}
    </div>
    {% endfor %}

    <div class="card">
      <div class="q-title">5. {{ q5_title }} (선택)</div>
      <textarea id="q5" maxlength="1000" placeholder="자유롭게 작성해 주세요."></textarea>
    </div>

    <div class="err" id="err"></div>
    <button class="submit" id="submitBtn" type="button">제출하기</button>
  </div>

  <div class="card done" id="doneArea">
    <div class="big">🙏</div>
    <h1>참여해 주셔서 감사합니다</h1>
    <div class="sub">소중한 의견은 서비스 개선에 활용하겠습니다.</div>
    <a href="/home">메인화면으로 이동</a>
  </div>
</div>

<script>
(function(){
  document.querySelectorAll('.opt input').forEach(function(inp){
    inp.addEventListener('change', function(){
      document.querySelectorAll('input[name="'+inp.name+'"]').forEach(function(x){
        x.closest('.opt').classList.toggle('sel', x.checked);
      });
    });
  });

  var consent = document.getElementById('consent');
  var contact = document.getElementById('contact');
  consent.addEventListener('change', function(){
    contact.disabled = !consent.checked;
    if(!consent.checked) contact.value = '';
    else contact.focus();
  });
  contact.addEventListener('input', function(){
    var d = contact.value.replace(/[^0-9]/g,'').slice(0,11), o = d;
    if(d.length > 7) o = d.slice(0,3)+'-'+d.slice(3,7)+'-'+d.slice(7);
    else if(d.length > 3) o = d.slice(0,3)+'-'+d.slice(3);
    contact.value = o;
  });

  function val(name){
    var el = document.querySelector('input[name="'+name+'"]:checked');
    return el ? el.value : '';
  }
  function showErr(msg){
    var e = document.getElementById('err');
    e.textContent = msg; e.style.display = 'block';
    e.scrollIntoView({behavior:'smooth', block:'center'});
  }

  document.getElementById('submitBtn').addEventListener('click', function(){
    var data = {
      org: val('org'), region: val('region'),
      consent: consent.checked, contact: contact.value.trim(),
      q1: val('q1'), q2: val('q2'), q3: val('q3'), q4: val('q4'),
      q5: document.getElementById('q5').value.trim()
    };
    if(!data.org) return showErr('소속 기관을 선택해 주세요.');
    if(!data.region) return showErr('근무 지역을 선택해 주세요.');
    if(data.consent && data.contact.replace(/[^0-9]/g,'').length < 10) return showErr('연락처를 정확히 입력해 주세요.');
    for(var i=1;i<=4;i++){ if(!data['q'+i]) return showErr(i+'번 문항을 선택해 주세요.'); }

    var btn = this; btn.disabled = true; btn.textContent = '제출 중...';
    fetch('/satisfaction/submit', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(data)})
      .then(function(r){ return r.json(); })
      .then(function(j){
        if(j.success){
          document.getElementById('formArea').style.display = 'none';
          document.getElementById('doneArea').style.display = 'block';
          window.scrollTo(0,0);
        } else {
          btn.disabled = false; btn.textContent = '제출하기';
          showErr(j.message || '제출에 실패했습니다. 다시 시도해 주세요.');
        }
      })
      .catch(function(){
        btn.disabled = false; btn.textContent = '제출하기';
        showErr('네트워크 오류가 발생했습니다. 다시 시도해 주세요.');
      });
  });
})();
</script>
</body>
</html>
"""

@app.route("/satisfaction")
def satisfaction():
    return render_template_string(
        SATISFACTION_HTML,
        orgs=SAT_ORGS, regions=SAT_REGIONS,
        questions=SAT_QUESTIONS, q5_title=SAT_Q5_TITLE
    )

@app.route("/satisfaction/submit", methods=["POST"])
def satisfaction_submit():
    d = request.get_json(silent=True) or {}
    org = str(d.get("org", "")).strip()
    region = str(d.get("region", "")).strip()
    if org not in SAT_ORGS or region not in SAT_REGIONS:
        return jsonify({"success": False, "message": "소속 기관/근무 지역을 확인해 주세요."})

    row = {"org": org, "region": region}
    for q in SAT_QUESTIONS:
        v = str(d.get(q["key"], "")).strip()
        if v not in q["options"]:
            return jsonify({"success": False, "message": "모든 문항에 응답해 주세요."})
        row[q["key"]] = v
    row["q5"] = str(d.get("q5", "")).strip()[:1000]

    consent = bool(d.get("consent"))
    contact = ""
    if consent:
        digits = re.sub(r"\D", "", str(d.get("contact", "")))
        if not re.fullmatch(r"01\d{8,9}", digits):
            return jsonify({"success": False, "message": "연락처를 정확히 입력해 주세요."})
        contact = digits[:3] + "-" + digits[3:-4] + "-" + digits[-4:]
    row["consent"] = consent
    row["contact"] = contact if consent else None

    if os.getenv("RENDER") is None:
        return jsonify({"success": True})   # 로컬 테스트: 저장 생략
    try:
        res = requests.post(
            f"{SUPABASE_URL}/rest/v1/survey_responses",
            headers=SUPABASE_HEADERS, json=row, timeout=8
        )
        if not res.ok:
            return jsonify({"success": False, "message": "저장 중 오류가 발생했습니다. 잠시 후 다시 시도해 주세요."})
    except Exception:
        return jsonify({"success": False, "message": "저장 중 오류가 발생했습니다. 잠시 후 다시 시도해 주세요."})
    return jsonify({"success": True})


def _sat_load(org="", region=""):
    q = "survey_responses?select=*&order=id.desc"
    rows = fetch_all_rows(q)
    out = []
    for r in rows:
        if org and r.get("org") != org:
            continue
        if region and r.get("region") != region:
            continue
        r["created_kst"] = _kst_datetime_str(r.get("created_at", ""))
        out.append(r)
    # 화면/엑셀에 보이는 번호는 DB id가 아닌 순번 (가장 오래된 응답 = 1번) → 리셋 후에도 1번부터 시작
    n = len(out)
    for i, r in enumerate(out):
        r["no"] = n - i
    return out

def _sat_stats(rows):
    total = len(rows)
    result = []
    for q in SAT_QUESTIONS:
        items = []
        for opt in q["options"]:
            c = sum(1 for r in rows if r.get(q["key"]) == opt)
            items.append({"label": opt, "count": c, "pct": round(c * 100 / total, 1) if total else 0})
        result.append({"title": q["title"], "items": items})
    return result

SATISFACTION_ADMIN_HTML = """
<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>설문조사 통계</title>
<style>
*{ box-sizing:border-box; }
body{ margin:0; background:#e8ecf4; font-family:'Pretendard',-apple-system,'Malgun Gothic',sans-serif; color:#111827; padding:16px; }
.container{ max-width:980px; margin:0 auto; }
.top-bar{ display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:8px; margin-bottom:14px; }
.top-right{ display:flex; gap:8px; flex-wrap:wrap; }
.btn{ display:inline-block; border:0; background:#4b6edc; color:#fff; font-size:13px; font-weight:700; padding:9px 14px; border-radius:10px; text-decoration:none; cursor:pointer; font-family:inherit; }
.btn.gray{ background:#6b7280; }
.btn.light{ background:#e0e7ff; color:#3730a3; }
.card{ background:#fff; border-radius:16px; padding:18px; margin-bottom:14px; box-shadow:0 6px 18px rgba(0,0,0,.06); }
h2{ font-size:16px; margin:0 0 12px; }
.sum{ display:flex; gap:10px; flex-wrap:wrap; }
.sum div{ flex:1; min-width:110px; background:#f3f4f6; border-radius:12px; padding:12px; text-align:center; }
.sum b{ display:block; font-size:22px; margin-top:4px; }
.sum span{ font-size:12px; color:#6b7280; }
.filter{ display:flex; gap:8px; flex-wrap:wrap; align-items:center; }
select{ padding:8px 10px; border:1px solid #d1d5db; border-radius:8px; font-size:13px; font-family:inherit; }
.q-title{ font-size:14px; font-weight:800; margin-bottom:10px; }
.bar-row{ display:grid; grid-template-columns:110px 1fr 80px; gap:8px; align-items:center; font-size:13px; margin-bottom:6px; }
.bar-bg{ background:#eef2ff; border-radius:6px; height:16px; overflow:hidden; }
.bar-fill{ background:#4b6edc; height:100%; }
.bar-num{ text-align:right; color:#374151; }
.tbl-wrap{ overflow-x:auto; }
table{ width:100%; border-collapse:collapse; font-size:13px; min-width:640px; }
th,td{ padding:8px 6px; border-bottom:1px solid #f1f5f9; text-align:left; vertical-align:top; }
th{ background:#f9fafb; font-weight:800; }
tr.row{ cursor:pointer; }
tr.row:hover{ background:#f8faff; }
.ellipsis{ max-width:220px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.actions{ display:flex; gap:8px; flex-wrap:wrap; margin-bottom:10px; }
.modal{ display:none; position:fixed; inset:0; background:rgba(0,0,0,.55); z-index:1000; align-items:center; justify-content:center; padding:16px; }
.modal.open{ display:flex; }
.modal-box{ background:#fff; border-radius:16px; width:100%; max-width:520px; max-height:90vh; overflow:auto; padding:20px; }
.modal-head{ display:flex; justify-content:space-between; align-items:center; margin-bottom:12px; font-weight:800; }
.m-sec{ margin-bottom:12px; }
.m-q{ font-size:12px; color:#6b7280; margin-bottom:3px; }
.m-a{ font-size:14px; font-weight:700; white-space:pre-wrap; word-break:break-all; }
.modal-nav{ display:flex; justify-content:space-between; margin-top:14px; gap:8px; }
.empty{ text-align:center; color:#9ca3af; padding:24px 0; font-size:14px; }
.ctrl-row{ display:flex; justify-content:space-between; align-items:center; gap:10px; flex-wrap:wrap; }
.ctrl-label{ font-size:14px; font-weight:700; display:flex; align-items:center; gap:8px; }
.ctrl-state{ font-size:12px; font-weight:800; padding:3px 9px; border-radius:999px; }
.ctrl-state.on{ background:#dcfce7; color:#166534; }
.ctrl-state.off{ background:#fee2e2; color:#991b1b; }
.ctrl-btns{ display:flex; gap:6px; }
.btn.danger{ background:#dc2626; }
.sw{ position:relative; width:48px; height:28px; border:0; border-radius:999px; background:#cbd5e1; cursor:pointer; padding:0; transition:background .2s; flex:none; }
.sw::after{ content:''; position:absolute; top:3px; left:3px; width:22px; height:22px; border-radius:50%; background:#fff; box-shadow:0 1px 3px rgba(0,0,0,.3); transition:transform .2s; }
.sw.on{ background:#22c55e; }
.sw.on::after{ transform:translateX(20px); }
.ctrl-hint{ font-size:12px; color:#6b7280; margin-top:8px; line-height:1.5; }
.pager{ display:flex; justify-content:center; align-items:center; gap:4px; margin-top:12px; flex-wrap:wrap; }
.pager button{ min-width:34px; height:34px; border:1px solid #d1d5db; background:#fff; border-radius:8px; font-size:13px; font-weight:700; cursor:pointer; font-family:inherit; color:#374151; padding:0 8px; }
.pager button.cur{ background:#4b6edc; border-color:#4b6edc; color:#fff; }
.pager button:disabled{ opacity:.4; cursor:default; }
@media (max-width:520px){ .bar-row{ grid-template-columns:90px 1fr 64px; } }
</style>
</head>
<body>
<div class="container">
  <div class="top-bar">
    <a href="/stats" class="btn gray">통계로</a>
    <div class="top-right">
      <a href="/stats/satisfaction/export?org={{ f_org }}&region={{ f_region }}" class="btn">엑셀 다운로드</a>
    </div>
  </div>

  <div class="card">
    <h2>설문 관리</h2>
    <div class="ctrl-row">
      <div class="ctrl-label">메인화면 노출
        <button type="button" id="surveySwitch" class="sw {{ 'on' if survey_on else '' }}" role="switch" aria-checked="{{ 'true' if survey_on else 'false' }}" onclick="surveyToggle(!this.classList.contains('on'))"></button>
        <span class="ctrl-state {{ 'on' if survey_on else 'off' }}" id="surveyState">{{ 'ON' if survey_on else 'OFF' }}</span>
      </div>
      <div class="ctrl-btns">
        <button type="button" class="btn danger" onclick="surveyReset()">리셋</button>
      </div>
    </div>
    <div class="ctrl-hint">OFF 하면 메인화면 + 메뉴에서 설문조사 버튼이 사라집니다. 리셋은 모든 응답을 영구 삭제합니다.</div>
  </div>

  <div class="card">
    <h2>설문조사 요약</h2>
    <div class="sum">
      <div><span>총 응답</span><b>{{ total }}</b></div>
      {% for k, v in org_counts %}<div><span>{{ k }}</span><b>{{ v }}</b></div>{% endfor %}
      <div><span>연락처 제공</span><b>{{ contact_cnt }}</b></div>
    </div>
    <div class="sum" style="margin-top:10px;">
      {% for k, v in region_counts %}<div><span>{{ k }}</span><b>{{ v }}</b></div>{% endfor %}
    </div>
  </div>

  <div class="card">
    <form class="filter" method="get">
      <span style="font-size:13px;font-weight:700;">필터</span>
      <select name="org" onchange="this.form.submit()">
        <option value="">소속 전체</option>
        {% for o in orgs %}<option value="{{ o }}" {% if o == f_org %}selected{% endif %}>{{ o }}</option>{% endfor %}
      </select>
      <select name="region" onchange="this.form.submit()">
        <option value="">지역 전체</option>
        {% for r in regions %}<option value="{{ r }}" {% if r == f_region %}selected{% endif %}>{{ r }}</option>{% endfor %}
      </select>
    </form>
  </div>

  {% for s in stats %}
  <div class="card">
    <div class="q-title">{{ loop.index }}. {{ s.title }}</div>
    {% for it in s['items'] %}
    <div class="bar-row">
      <div>{{ it.label }}</div>
      <div class="bar-bg"><div class="bar-fill" style="width:{{ it.pct }}%"></div></div>
      <div class="bar-num">{{ it.count }}명 ({{ it.pct }}%)</div>
    </div>
    {% endfor %}
  </div>
  {% endfor %}

  <div class="card">
    <h2>응답 목록</h2>
    <div class="actions">
      <button type="button" class="btn light" onclick="toggleAll(true)">전체 선택</button>
      <button type="button" class="btn light" onclick="toggleAll(false)">선택 해제</button>
      <button type="button" class="btn" onclick="openViewer()">선택 설문지 보기</button>
    </div>
    {% if rows %}
    <div class="tbl-wrap">
      <table>
        <thead><tr><th></th><th>번호</th><th>제출일시</th><th>소속</th><th>지역</th><th>연락처</th><th>기타 의견</th></tr></thead>
        <tbody id="respBody">
        {% for r in rows %}
        <tr class="row" onclick="openOne({{ loop.index0 }}, event)">
          <td><input type="checkbox" class="chk" data-idx="{{ loop.index0 }}" onclick="event.stopPropagation()"></td>
          <td>{{ r.no }}</td>
          <td>{{ r.created_kst }}</td>
          <td>{{ r.org }}</td>
          <td>{{ r.region }}</td>
          <td>{{ r.contact or '-' }}</td>
          <td><div class="ellipsis">{{ r.q5 or '-' }}</div></td>
        </tr>
        {% endfor %}
        </tbody>
      </table>
    </div>
    <div class="pager" id="pager"></div>
    {% else %}
    <div class="empty">아직 응답이 없습니다.</div>
    {% endif %}
  </div>
</div>

<div class="modal" id="viewer" onclick="if(event.target===this)closeViewer()">
  <div class="modal-box">
    <div class="modal-head"><span id="vCount"></span><button type="button" class="btn gray" onclick="closeViewer()">닫기</button></div>
    <div id="vBody"></div>
    <div class="modal-nav">
      <button type="button" class="btn light" onclick="step(-1)">이전</button>
      <button type="button" class="btn" onclick="step(1)">다음</button>
    </div>
  </div>
</div>

<script>
var ROWS = {{ rows|tojson }};
var QS = {{ qtitles|tojson }};
var list = [], pos = 0;

function checkedIdx(){
  return Array.prototype.map.call(document.querySelectorAll('.chk:checked'), function(c){ return parseInt(c.dataset.idx,10); });
}
function toggleAll(on){ document.querySelectorAll('.chk').forEach(function(c){ c.checked = on; }); }

function surveyToggle(on){
  var sw = document.getElementById('surveySwitch');
  if(sw){ sw.classList.toggle('on', on); sw.setAttribute('aria-checked', on ? 'true' : 'false'); }
  var st = document.getElementById('surveyState');
  if(st){ st.textContent = on ? 'ON' : 'OFF'; st.className = 'ctrl-state ' + (on ? 'on' : 'off'); }
  fetch('/stats/satisfaction/toggle', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({on:on})})
    .then(function(r){ return r.json(); })
    .then(function(j){ if(j.success) location.reload(); else alert(j.message || '변경에 실패했습니다.'); })
    .catch(function(){ alert('네트워크 오류가 발생했습니다.'); });
}
function surveyReset(){
  var pw = prompt('설문 응답을 모두 삭제합니다. (복구 불가)\\n비밀번호를 입력하세요.');
  if(pw === null) return;
  fetch('/stats/satisfaction/reset', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({password:pw})})
    .then(function(r){ return r.json(); })
    .then(function(j){
      if(j.success){ alert('초기화되었습니다.'); location.reload(); }
      else alert(j.message || '초기화에 실패했습니다.');
    })
    .catch(function(){ alert('네트워크 오류가 발생했습니다.'); });
}

/* 응답 목록 페이지네이션 (10개씩) */
var PAGE_SIZE = 10, curPage = 1;
function goPage(p){
  var trs = document.querySelectorAll('#respBody tr.row');
  var pages = Math.max(1, Math.ceil(trs.length / PAGE_SIZE));
  curPage = Math.min(Math.max(1, p), pages);
  trs.forEach(function(tr, i){
    tr.style.display = (i >= (curPage-1)*PAGE_SIZE && i < curPage*PAGE_SIZE) ? '' : 'none';
  });
  var pg = document.getElementById('pager');
  if(!pg) return;
  if(pages <= 1){ pg.innerHTML = ''; return; }
  var h = '<button type="button" '+(curPage===1?'disabled':'')+' onclick="goPage('+(curPage-1)+')">이전</button>';
  var from = Math.max(1, curPage-2), to = Math.min(pages, from+4);
  from = Math.max(1, to-4);
  for(var i=from;i<=to;i++){
    h += '<button type="button" class="'+(i===curPage?'cur':'')+'" onclick="goPage('+i+')">'+i+'</button>';
  }
  h += '<button type="button" '+(curPage===pages?'disabled':'')+' onclick="goPage('+(curPage+1)+')">다음</button>';
  pg.innerHTML = h;
}
document.addEventListener('DOMContentLoaded', function(){ goPage(1); });

function esc(s){ var d = document.createElement('div'); d.textContent = (s==null?'':s); return d.innerHTML; }
function sec(q, a){ return '<div class="m-sec"><div class="m-q">'+esc(q)+'</div><div class="m-a">'+(a? esc(a) : '-')+'</div></div>'; }

function render(){
  var r = ROWS[list[pos]];
  document.getElementById('vCount').textContent = '설문지 #'+r.no+'  ('+(pos+1)+' / '+list.length+')';
  var h = sec('제출일시', r.created_kst) + sec('소속 기관', r.org) + sec('근무 지역', r.region)
        + sec('연락처', r.contact ? r.contact : (r.consent ? '-' : '미동의'));
  ['q1','q2','q3','q4'].forEach(function(k,i){ h += sec((i+1)+'. '+QS[i], r[k]); });
  h += sec('5. 기타 의견', r.q5);
  document.getElementById('vBody').innerHTML = h;
}
function openViewer(){
  list = checkedIdx();
  if(!list.length){ alert('보려는 설문지를 먼저 체크해 주세요.'); return; }
  pos = 0; render(); document.getElementById('viewer').classList.add('open');
}
function openOne(i, e){
  if(e && e.target.tagName === 'INPUT') return;
  list = [i]; pos = 0; render(); document.getElementById('viewer').classList.add('open');
}
function closeViewer(){ document.getElementById('viewer').classList.remove('open'); }
function step(d){ var n = pos + d; if(n < 0 || n >= list.length) return; pos = n; render(); }
document.addEventListener('keydown', function(e){
  if(!document.getElementById('viewer').classList.contains('open')) return;
  if(e.key === 'ArrowLeft') step(-1);
  else if(e.key === 'ArrowRight') step(1);
  else if(e.key === 'Escape') closeViewer();
});
</script>
</body>
</html>
"""

@app.route("/stats/satisfaction")
def satisfaction_admin():
    f_org = request.args.get("org", "").strip()
    f_region = request.args.get("region", "").strip()
    rows = _sat_load(f_org, f_region)
    return render_template_string(
        SATISFACTION_ADMIN_HTML,
        rows=rows, total=len(rows),
        stats=_sat_stats(rows),
        org_counts=[(o, sum(1 for r in rows if r.get("org") == o)) for o in SAT_ORGS],
        region_counts=[(g, sum(1 for r in rows if r.get("region") == g)) for g in SAT_REGIONS],
        contact_cnt=sum(1 for r in rows if r.get("contact")),
        orgs=SAT_ORGS, regions=SAT_REGIONS, f_org=f_org, f_region=f_region,
        qtitles=[q["title"] for q in SAT_QUESTIONS],
        survey_on=_survey_is_on(),
    )

SAT_RESET_PASSWORD = "02401234"

@app.route("/stats/satisfaction/toggle", methods=["POST"])
def satisfaction_toggle():
    d = request.get_json(silent=True) or {}
    _survey_set_on(bool(d.get("on")))
    return jsonify({"success": True})

@app.route("/stats/satisfaction/reset", methods=["POST"])
def satisfaction_reset():
    d = request.get_json(silent=True) or {}
    if str(d.get("password", "")).strip() != SAT_RESET_PASSWORD:
        return jsonify({"success": False, "message": "비밀번호가 올바르지 않습니다."})
    if os.getenv("RENDER") is None:
        return jsonify({"success": True})   # 로컬 테스트: 삭제 생략
    try:
        res = requests.delete(
            f"{SUPABASE_URL}/rest/v1/survey_responses?id=gt.0",
            headers={**SUPABASE_HEADERS, "Prefer": "return=minimal"}, timeout=15
        )
        if not res.ok:
            return jsonify({"success": False, "message": "삭제 중 오류가 발생했습니다."})
    except Exception:
        return jsonify({"success": False, "message": "삭제 중 오류가 발생했습니다."})
    return jsonify({"success": True})

@app.route("/stats/satisfaction/export")
def satisfaction_export():
    f_org = request.args.get("org", "").strip()
    f_region = request.args.get("region", "").strip()
    rows = _sat_load(f_org, f_region)
    ids = request.args.get("ids", "").strip()
    if ids:
        want = {i for i in ids.split(",") if i.strip().isdigit()}
        rows = [r for r in rows if str(r.get("id")) in want]
    rows = sorted(rows, key=lambda r: r.get("id", 0))

    cols = ["번호", "제출일시", "소속기관", "근무지역", "연락처 동의", "연락처"]
    cols += [f"{i+1}. {q['title']}" for i, q in enumerate(SAT_QUESTIONS)]
    cols += [f"5. {SAT_Q5_TITLE}"]
    data = []
    for r in rows:
        data.append([
            r.get("no"), r.get("created_kst"), r.get("org"), r.get("region"),
            "동의" if r.get("consent") else "미동의", r.get("contact") or "",
            r.get("q1"), r.get("q2"), r.get("q3"), r.get("q4"), r.get("q5") or "",
        ])
    df = pd.DataFrame(data, columns=cols)

    stat_rows = []
    total = len(rows)
    for i, q in enumerate(SAT_QUESTIONS):
        for opt in q["options"]:
            c = sum(1 for r in rows if r.get(q["key"]) == opt)
            stat_rows.append([f"{i+1}. {q['title']}", opt, c, round(c * 100 / total, 1) if total else 0])
    sdf = pd.DataFrame(stat_rows, columns=["문항", "응답", "인원", "비율(%)"])

    buf = BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        df.to_excel(w, sheet_name="응답(설문지별)", index=False)
        sdf.to_excel(w, sheet_name="문항별 통계", index=False)
        for ws in w.book.worksheets:
            for col in ws.columns:
                width = max(len(str(c.value)) if c.value is not None else 0 for c in col)
                ws.column_dimensions[col[0].column_letter].width = min(max(width * 1.6, 10), 50)
    buf.seek(0)
    return send_file(
        buf, as_attachment=True, download_name="케어내비_설문조사.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

@app.route("/app-version.json")
def app_version():
    return {
        "latestAppVersionCode": 8,
        "latestAppVersionName": "1.8",
        "apkUrl": "https://carenavi.kr/static/carenavi.apk",
        "message": "케어내비 새 버전이 있습니다. 업데이트해 주세요."
    }

if __name__ == "__main__":
    app.run()