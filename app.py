from flask import Flask, request, jsonify, render_template_string, Response, send_file, session, redirect
import functools
from html import escape as html_escape
import pandas as pd

from flask_compress import Compress

import os

import re

import time

import threading

import requests

try:

    from dotenv import load_dotenv

    load_dotenv()

except ImportError:

    pass

SUPABASE_URL = os.environ.get("SUPABASE_URL")

SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

import webbrowser

from urllib.parse import quote

import json

from datetime import date, datetime

from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")
def to_kst(value, naive_tz="UTC"):
    """Supabase 시각 문자열 → 한국시간. 오프셋 없는 값은 naive_tz 기준으로 해석한다."""
    if value is None or value == "":
        return None
    try:
        ts = pd.Timestamp(value)
    except Exception:
        return None
    if pd.isna(ts):
        return None
    if ts.tzinfo is None:
        ts = ts.tz_localize(naive_tz)
    return ts.tz_convert("Asia/Seoul")
def kst_iso(value):
    ts = to_kst(value)
    return ts.isoformat() if ts is not None else value
def kst_fmt_series(series, fmt="%Y-%m-%d", naive_tz="UTC"):
    def _f(v):
        ts = to_kst(v, naive_tz)
        return ts.strftime(fmt) if ts is not None else None
    return series.apply(_f)
from io import BytesIO





def update_visitors():
    """방문자수 집계. IP는 절대 수집하지 않고, 개별 방문 시각(타임스탬프)도 저장하지 않는다.
    같은 브라우저(세션) 안에서는 1시간에 1번만 카운트하고, 그 외엔 '날짜별 합계' 숫자만 +1 한다."""

    if not SUPABASE_URL or not SUPABASE_KEY:
        return {
            "total": 0,
            "today_count": 0
        }

    try:
        headers = {
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}",
            "Content-Type": "application/json",
            "Prefer": "return=representation"
        }

        url = f"{SUPABASE_URL}/rest/v1/visit_stats?id=eq.1"

        r = requests.get(url, headers=headers)

        if r.status_code >= 400:
            return {
                "total": 0,
                "today_count": 0
            }

        rows = r.json()

        if not rows or not isinstance(rows, list):
            return {
                "total": 0,
                "today_count": 0
            }

        row = rows[0]

        total = int(row.get("total_count", 0))
        today = str(row.get("today_date", datetime.now(KST).date()))
        today_count = int(row.get("today_count", 0))

        now_time = time.time()
        last_counted_at = session.get("last_visit_counted_at", 0)

        # 같은 브라우저(세션) 안에서 1시간 이내 재방문이면 카운트 증가 안 함
        if last_counted_at and now_time - float(last_counted_at) < 3600:
            if today != str(datetime.now(KST).date()) and feature_detail_on():
                today_count = 0
            return {
                "total": total,
                "today_count": today_count
            }

        now_day = str(datetime.now(KST).date())

        total += 1

        if today == now_day:
            today_count += 1
        else:
            today = now_day
            today_count = 1

        update_data = {
            "total_count": total,
            "today_date": today,
            "today_count": today_count,
            "updated_at": datetime.now(KST).isoformat()
        }

        requests.patch(
            url,
            headers=headers,
            json=update_data
        )

        # 일자별 방문자수 집계용 — 개별 시각/IP는 저장하지 않고, 오늘 날짜의 합계 숫자만 +1
        try:
            dc_select_url = f"{SUPABASE_URL}/rest/v1/visit_daily_counts?visit_date=eq.{now_day}&select=count"
            dc_res = requests.get(dc_select_url, headers=headers, timeout=5)
            dc_rows = dc_res.json() if dc_res.ok else []

            if dc_rows:
                cur = int(dc_rows[0].get("count", 0) or 0)
                requests.patch(
                    f"{SUPABASE_URL}/rest/v1/visit_daily_counts?visit_date=eq.{now_day}",
                    headers=headers,
                    json={"count": cur + 1},
                    timeout=5
                )
            else:
                requests.post(
                    f"{SUPABASE_URL}/rest/v1/visit_daily_counts",
                    headers=headers,
                    json={"visit_date": now_day, "count": 1},
                    timeout=5
                )
        except Exception:
            pass

        session["last_visit_counted_at"] = now_time

        return {
            "total": total,
            "today_count": today_count
        }

    except Exception as e:
        print("방문자 Supabase 처리 오류:", e)
        return {
            "total": 0,
            "today_count": 0
        }





def save_search_log(data):



    if not SUPABASE_URL or not SUPABASE_KEY:

        print("Supabase 환경변수 없음")

        return



    try:

        headers = {

            "apikey": SUPABASE_KEY,

            "Authorization": f"Bearer {SUPABASE_KEY}",

            "Content-Type": "application/json",

            "Prefer": "return=representation"

        }



        payload = {

            "province": data.get("province", ""),

            "city": data.get("city", ""),

            "categories": data.get("categories", []),

            "result_count": data.get("result_count", 0)

        }



        r = requests.post(

            f"{SUPABASE_URL}/rest/v1/search_logs",

            headers=headers,

            json=payload

        )



    except Exception as e:

        print("검색로그 Supabase 처리 오류:", e)





app = Flask(__name__)

app.secret_key = os.environ.get("SECRET_KEY", "safe-map-secret-key")

Compress(app)

# =========================
# 운영 로그 최소화
# - Render/Gunicorn/Flask 기본 요청 로그(접속 IP 포함)를 최대한 차단
# =========================
import logging
logging.getLogger('werkzeug').disabled = True
logging.getLogger('werkzeug').setLevel(logging.CRITICAL)
logging.getLogger('gunicorn.access').disabled = True
logging.getLogger('gunicorn.access').setLevel(logging.CRITICAL)
logging.getLogger('flask.app').setLevel(logging.ERROR)





app.json.ensure_ascii = False



KAKAO_KEY = os.environ.get("KAKAO_KEY")

KAKAO_JS_KEY = os.environ.get("KAKAO_JS_KEY", os.environ.get("KAKAO_KEY", ""))



@app.route("/search_place")

def search_place():



    query = request.args.get("q","")



    url = "https://dapi.kakao.com/v2/local/search/keyword.json"



    headers = {

        "Authorization": f"KakaoAK {KAKAO_KEY}"

    }



    params = {

        "query": query

    }



    r = requests.get(url, headers=headers, params=params)



    return jsonify(r.json())



app.config["JSON_AS_ASCII"] = False

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

FILE_PATH = "mapdata_geocoded.xlsx"

# 항목별 엑셀(공중화장실.xlsx 등)을 각각 읽어 합친다. mapdata 폴더 우선, 없으면 앱 루트.

DATA_DIR = os.path.join(BASE_DIR, "mapdata") if os.path.isdir(os.path.join(BASE_DIR, "mapdata")) else BASE_DIR

SPLIT_FILES = ["공중화장실.xlsx", "상습결빙지역.xlsx", "교통사고위험지역.xlsx", "주차장.xlsx", "자동심장충격기.xlsx"]

DATA_CACHE = None





TYPE_COLORS = {

    "상습결빙지역": "#06b6d4",

    "공중화장실": "#f59e0b",

    "교통사고위험지역": "#ef4444",   # 추가

    "공영주차장": "#8b5cf6",

    "민영주차장": "#8b5cf6",

    "자동심장충격기": "#16a34a"

}



DEFAULT_CENTER = [34.85, 126.90]

DEFAULT_ZOOM = 9





def safe_str(v):

    if pd.isna(v):

        return ""

    return str(v).strip()





def extract_town_from_address(address):

    addr = safe_str(address)

    if not addr:

        return "읍면동없음"



    # 읍/면/동/가/리 추출

    found = re.findall(r'([가-힣0-9]+(?:읍|면|동))', addr)

    if found:

        for token in reversed(found):

            if token.endswith(("읍", "면", "동")):

                return token



    return "읍면동없음"





def sample_desc(category, city, town, address):



    if category == "상습결빙지역":

        return f"{city} {town} 일대는 겨울철 노면 결빙 위험이 높은 구간입니다."



    if category == "공중화장실":

        return f"{city} {town} 인근 공중화장실 위치입니다."



    if category == "교통사고위험지역":

        return f"{city} {town} 일대는 교통사고 발생률이 높은 구간입니다."

    if category in ("공영주차장", "민영주차장"):

        return f"{city} {town} 인근 {category} 위치입니다."



    return f"{city} {town} 위치 정보입니다."



def sample_date(category):



    m = {

        "상습결빙지역": "2025-12-28",

        "공중화장실": "2025-01-01",

        "교통사고위험지역": "2025-01-01",   # 추가

        "공영주차장": "2025-01-01",

        "민영주차장": "2025-01-01"

    }



    return m.get(category, "2025-01-01")

 



def build_photo_url(row):



    category = safe_str(row["구분"])



    if category == "공중화장실":

        return "/photo/111"



    if category == "상습결빙지역":

        return "/photo/222"



    if category == "교통사고위험지역":

        return "/photo/333"



    return "/photo/111"



def load_df():



    global DATA_CACHE



    if DATA_CACHE is not None:

        return DATA_CACHE



    frames = []

    for _fn in SPLIT_FILES:

        _fp = os.path.join(DATA_DIR, _fn)

        if os.path.exists(_fp):

            frames.append(pd.read_excel(_fp))

    if frames:

        df = pd.concat(frames, ignore_index=True)

    elif os.path.exists(FILE_PATH):

        df = pd.read_excel(FILE_PATH)

    else:

        raise FileNotFoundError("지도 데이터 엑셀이 없습니다. (항목별 .xlsx 또는 mapdata_geocoded.xlsx)")

    

    required = ["순번", "구분", "시도", "시군구", "주소", "위도", "경도"]

    for col in required:

        if col not in df.columns:

            raise ValueError(f"엑셀에 '{col}' 열이 없습니다.")



    if "시도" not in df.columns:

        df["시도"] = ""



    if "읍면동" not in df.columns:

        df["읍면동"] = df["주소"].apply(extract_town_from_address)



    if "사고설명" not in df.columns:

        df["사고설명"] = ""



    if "날짜" not in df.columns:

        df["날짜"] = ""



    if "사진URL" not in df.columns:

        df["사진URL"] = ""



    # 항목별 추가 정보 열 (갱신 프로그램이 넣음, 예전 엑셀이면 빈 값)

    for _c in EXTRA_INFO_COLS:

        if _c not in df.columns:

            df[_c] = ""



    for col in ["구분", "시도", "시군구", "주소", "읍면동", "사고설명", "날짜", "사진URL"] + EXTRA_INFO_COLS:

        df[col] = df[col].apply(safe_str)

    df["구분"] = df["구분"].str.strip()



    df["위도"] = pd.to_numeric(df["위도"], errors="coerce")

    df["경도"] = pd.to_numeric(df["경도"], errors="coerce")



    # 좌표 없는 건 자동 제외

    df = df[df["위도"].notna() & df["경도"].notna()].copy()

    # 항목별 파일을 합치면 순번이 겹치므로 전체 다시 매김 (고유 id 보장)

    df = df.reset_index(drop=True)

    df["순번"] = range(1, len(df) + 1)

    DATA_CACHE = df

    return DATA_CACHE





# 항목별로 앱에 보내는 추가 정보 (팝업·내 주변 찾기 조건용)

EXTRA_INFO = {'공중화장실': ['개방시간', '비상벨', '장애인화장실', '화장실명', '자료수정일'], '공영주차장': ['요금', '요금상세', '운영평일', '운영토요일', '운영공휴일', '자료수정일'], '민영주차장': ['요금', '요금상세', '운영평일', '운영토요일', '운영공휴일', '자료수정일'], '자동심장충격기': ['설치장소', '사용시간', '일요일사용', '자료수정일'], '교통사고위험지역': ['사고건수', '보행자사고', '야간사고', '중상이상', '자료수정일'], '상습결빙지역': ['자료수정일']}

EXTRA_INFO_COLS = ['개방시간', '비상벨', '장애인화장실', '화장실명', '자료수정일', '요금', '요금상세', '운영평일', '운영토요일', '운영공휴일', '설치장소', '사용시간', '일요일사용', '사고건수', '보행자사고', '야간사고', '중상이상']





def row_to_dict(row):

    category = safe_str(row["구분"])

    province = safe_str(row["시도"])

    city = safe_str(row["시군구"])

    town = safe_str(row["읍면동"])

    address = safe_str(row["주소"])



    desc = safe_str(row.get("사고설명", ""))

    if not desc:

        desc = sample_desc(category, city, town, address)



    date_value = safe_str(row.get("날짜", ""))

    if not date_value:

        date_value = sample_date(category)



    d = {

        "시도": province,

        "순번": safe_str(row["순번"]),

        "구분": category,

        "시군구": city,

        "읍면동": town,

        "주소": address,

        "위도": float(row["위도"]),

        "경도": float(row["경도"]),

        "사고설명": desc,

        "날짜": date_value,

        "사진URL": build_photo_url(row),

        "마커색상": TYPE_COLORS.get(category, "#334155"),

    }

    if feature_detail_on():
        d["시설명"] = sr_place_name(row, category, address, town)

    # 항목별 추가 정보는 값이 있는 것만 보냄 (전송량 절약)

    for _c in (EXTRA_INFO.get(category, []) if feature_detail_on() else []):

        _v = re.sub(r"\.0$", "", safe_str(row.get(_c, "")))   # 엑셀이 3 → 3.0 으로 읽는 것 정리

        if _v and _v != "0":

            d[_c] = _v

    return d





# ===== 토글 ON: 목록·팝업 제목에 쓸 이름 =====
# 엑셀에 이름 열이 있으면 그 값, 없으면 주소로 만듦 (예: 선운중앙로 결빙 구간)
SR_NAME_COLS = ["화장실명", "시설명", "명칭", "이름", "주차장명", "설치기관명", "기관명", "지점명", "구간명", "장소명"]
SR_NAME_SUFFIX = {"상습결빙지역": "결빙 구간", "교통사고위험지역": "사고 위험 지점", "공영주차장": "공영주차장",
                  "민영주차장": "민영주차장", "자동심장충격기": "AED", "공중화장실": "공중화장실"}


def sr_place_name(row, category, address, town):
    for c in SR_NAME_COLS:
        v = re.sub(r"\.0$", "", safe_str(row.get(c, "")))
        if v and v != "0":
            return v
    place = ""
    for tok in address.replace("(", " ").replace(")", " ").replace(",", " ").split():
        if re.fullmatch(r"[가-힣][가-힣0-9]*(?:대로|로|길)", tok):
            place = tok                        # 첫 도로 이름 (선운중앙로67번길 등)
            break
    if not place and town and town != "읍면동없음":
        place = town
    suffix = SR_NAME_SUFFIX.get(category, category)
    return f"{place} {suffix}" if place else suffix


HTML = r"""

<!DOCTYPE html>

<html lang="ko">

<head>

<meta charset="UTF-8">

<meta name="viewport" content="width=device-width, initial-scale=1.0">

<title>장기요양 안전로드</title>



<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>

<link rel="stylesheet" href="https://unpkg.com/leaflet.markercluster@1.5.3/dist/MarkerCluster.css"/>

<link rel="stylesheet" href="https://unpkg.com/leaflet.markercluster@1.5.3/dist/MarkerCluster.Default.css"/>

<!-- 로드뷰용 카카오맵 SDK (JS키 사용) -->

<script type="text/javascript" src="//dapi.kakao.com/v2/maps/sdk.js?appkey={{kakao_js_key}}&libraries=services,roadview"></script>





{% raw %}<style>

/* ══ 리셋 ══ */

*{box-sizing:border-box;margin:0;padding:0;}

html,body{

  width:100%;height:100%;

  font-family:'Pretendard','Apple SD Gothic Neo','Malgun Gothic',sans-serif;

  font-size:14px;

  background:#f4f5f7;

  color:#1a202c;

  -webkit-font-smoothing:antialiased;

}



/* ══ 레이아웃 ══ */

.page{display:flex;flex-direction:row;width:100%;height:100vh;overflow:hidden;}



/* ══ 사이드바 - 소프트 그레이 + 인디고 ══ */

.sidebar{

  width:300px;min-width:300px;

  background:#f4f5f7;

  display:flex;flex-direction:column;

  overflow:hidden;

  border-right:1px solid #e5e7eb;

}

.sidebar-scroll{

  flex:1;overflow-y:auto;

  padding:12px;

  scrollbar-width:thin;

  scrollbar-color:#e5e7eb transparent;

}

.sidebar-scroll::-webkit-scrollbar{width:3px;}

.sidebar-scroll::-webkit-scrollbar-thumb{background:#e5e7eb;border-radius:3px;}



/* ══ 브랜드 헤더 ══ */

.brand{

  padding:14px 14px 12px;

  border-bottom:1px solid #f1f1f1;

  display:flex;align-items:center;gap:10px;

  background:#ffffff;

  flex-shrink:0;

}

.brand-accent{width:3px;height:36px;background:#3b82f6;border-radius:2px;flex-shrink:0;}

.brand-left{display:flex;flex-direction:column;gap:2px;flex:1;}

.brand-title{

  font-size:15px;font-weight:900;

  color:#1a202c;cursor:pointer;

  letter-spacing:-0.3px;

}

.brand-sub{font-size:10px;color:#9ca3af;}

.ci-logo{height:32px;object-fit:contain;flex-shrink:0;opacity:.95;}

@media(max-width:900px){.ci-logo{height:28px;}}



/* ══ 섹션 카드 ══ */

.s-card{

  background:#ffffff;

  border-radius:14px;

  padding:13px;

  margin-bottom:8px;

  box-shadow:0 1px 4px rgba(0,0,0,.07);

}

.s-card-label{

  font-size:14px;

  font-weight:900;

  color:#1a2f5a;

  letter-spacing:-0.2px;

  margin-bottom:12px;

  display:flex;

  align-items:center;

  justify-content:space-between;

  padding-bottom:8px;

  border-bottom:2.5px solid #93c5fd;

}

.s-card-label > span:first-child{

  display:flex;align-items:center;gap:6px;

}

.s-card-label > span:first-child::before{

  content:'';display:inline-block;

  width:3px;height:14px;

  background:#2563eb;border-radius:2px;flex-shrink:0;

}



/* ══ 폼 요소 ══ */

.form-label{

  font-size:11px;font-weight:600;

  color:#6b7280;

  margin:8px 0 4px;

  display:block;

}

.form-label:first-child{margin-top:0;}

.form-select{

  width:100%;height:38px;

  background:#f9fafb;

  border:1.5px solid #e5e7eb;

  border-radius:9px;

  color:#1f2937;

  font-size:13px;

  padding:0 10px;

  appearance:none;

  background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='11' height='11' viewBox='0 0 24 24' fill='none' stroke='%236b7280' stroke-width='2.5'%3E%3Cpolyline points='6 9 12 15 18 9'/%3E%3C/svg%3E");

  background-repeat:no-repeat;background-position:right 9px center;

  cursor:pointer;transition:border-color .15s;

}

.form-select:focus{outline:none;border-color:#3b82f6;box-shadow:0 0 0 2px rgba(59,130,246,.15);}



.town-multi-wrap{

  max-height:120px;overflow-y:auto;

  background:#f9fafb;border:1.5px solid #e5e7eb;

  border-radius:9px;padding:4px 6px;

}

.town-check-item{

  display:flex;align-items:center;gap:7px;

  padding:5px 5px;font-size:12px;color:#6b7280;

  cursor:pointer;border-radius:5px;transition:background .1s;

}

.town-check-item:hover{background:#f3f4f6;}

.town-check-item input{accent-color:#3b82f6;width:13px;height:13px;flex-shrink:0;}



/* ══ 카테고리 체크박스 ══ */

.check-grid{display:flex;flex-direction:column;gap:5px;}

.check-item{

  display:flex;align-items:center;gap:9px;

  padding:8px 10px;

  background:#f9fafb;border:1.5px solid #e5e7eb;

  border-radius:9px;font-size:13px;color:#374151;

  cursor:pointer;transition:border-color .15s,background .15s;

}

.check-item:has(input:checked){border-color:#3b82f6;background:#eff6ff;}

.dot{width:9px;height:9px;border-radius:50%;flex:0 0 9px;}



/* ══ 버튼 ══ */

.btn-main{

  width:100%;height:44px;

  background:linear-gradient(135deg,#2563eb,#3b82f6);

  color:#fff;border:none;border-radius:11px;

  font-size:15px;font-weight:800;

  cursor:pointer;margin-top:12px;

  display:flex;align-items:center;justify-content:center;

  box-shadow:0 4px 14px rgba(37,99,235,.35);

  transition:opacity .15s,transform .1s;

  letter-spacing:-0.2px;

}

.btn-main:hover{opacity:.92;}

.btn-main:active{transform:scale(.98);}



.btn-reset{

  height:26px;

  padding:0 12px;

  border:1.5px solid #d1d5db;

  border-radius:999px;

  background:#fff;

  color:#374151;

  font-size:11px;

  font-weight:400;

  cursor:pointer;

  box-shadow:0 1px 4px rgba(0,0,0,.08);

  transition:background .15s,color .15s;

}

.btn-reset:hover{

  background:#f3f4f6;

  color:#111827;

}



/* 2열 버튼 그리드 */

.btn-grid{display:grid;grid-template-columns:1fr 1fr;gap:6px;margin-bottom:0;}

.btn-grid .btn-action{height:40px;font-size:12px;}



.btn-action{

  width:100%;height:40px;

  border-radius:9px;border:1.5px solid #e5e7eb;

  background:#f9fafb;color:#374151;

  font-size:13px;font-weight:700;

  cursor:pointer;

  display:flex;align-items:center;justify-content:center;

  transition:border-color .15s,background .15s,color .15s;

}

.btn-action:hover{border-color:#bfdbfe;background:#eff6ff;color:#1d4ed8;}

.btn-action:active{transform:scale(.98);}

.btn-action.fab-on{background:#3b82f6;border-color:#3b82f6;color:#fff;}

#facilityFabMenu.fab-dim{position:relative;z-index:30;box-shadow:0 0 0 100vmax rgba(15,23,42,0.5);}



.btn-kakao{

  background:#FEE500;color:#191919;border:none;

}

.btn-kakao:hover{background:#f5dc00;color:#191919;}



.btn-green{

  background:#f9fafb;

  color:#374151;

  border:1.5px solid #e5e7eb;

}



/* ══ 방문자 ══ */

.visitor-row{display:grid;grid-template-columns:1fr 1fr;gap:6px;margin-bottom:8px;}

.visitor-box{

  background:#f9fafb;border-radius:10px;padding:10px;

  text-align:center;border:1px solid #e5e7eb;

}

.visitor-num{font-size:22px;font-weight:900;color:#374151;line-height:1;margin-bottom:3px;}

.visitor-lbl{font-size:10px;font-weight:600;color:#9ca3af;text-transform:uppercase;letter-spacing:.05em;}



/* ══ 푸터 ══ */

.sidebar-footer{

  padding:10px 14px;border-top:1px solid #f1f1f1;

  text-align:center;font-size:10px;color:#9ca3af;

  line-height:1.6;flex-shrink:0;background:#fff;

}



/* ══ 지도 영역 ══ */

.map-wrap{position:relative;flex:1;min-width:0;}

#map{width:100%;height:100vh;}



.top-badge{

  position:absolute;top:14px;right:14px;z-index:999;

  background:rgba(255,255,255,.96);border:1px solid #e5e7eb;

  border-radius:12px;padding:8px 12px;font-size:12px;

  box-shadow:0 4px 14px rgba(0,0,0,.10);

}

@media(max-width:900px){.top-badge{display:none!important;}}



.map-legend{

  position:absolute;top:20px;right:20px;

  background:rgba(255,255,255,.97);

  padding:10px 12px;border-radius:12px;

  box-shadow:0 4px 16px rgba(0,0,0,.12);

  font-size:12px;z-index:999;

}

.map-legend-item{display:flex;align-items:center;gap:7px;margin-bottom:5px;}

.map-legend-item:last-child{margin-bottom:0;}

.map-legend-dot{width:9px;height:9px;border-radius:50%;flex-shrink:0;}

@media(max-width:900px){.map-legend{display:none;}}



.loading{

  position:absolute;left:50%;top:50%;transform:translate(-50%,-50%);

  z-index:1000;background:rgba(15,23,42,.9);color:#fff;

  padding:12px 18px;border-radius:14px;font-size:13px;font-weight:600;display:none;

}



/* ══ 마커 / 위치 ══ */

.custom-marker{

  width:15px;height:15px;border-radius:50%;

  border:2.5px solid #fff;box-shadow:0 2px 6px rgba(0,0,0,.3);

}

.user-marker-wrap{position:relative;width:28px;height:28px;}
/* 내 위치로 버튼 (지도 오른쪽 아래, 결과 창이 올라오면 그 위로) */
.leaflet-control.sr-locate-wrap{border:none!important;background:none!important;box-shadow:none!important;margin-right:14px!important;transition:margin-bottom .18s ease;}
.sr-locate{width:46px;height:46px;border-radius:50%;background:#fff;border:1px solid #e5e7eb;box-shadow:0 3px 10px rgba(15,23,42,.18);display:flex;align-items:center;justify-content:center;cursor:pointer;padding:0;-webkit-tap-highlight-color:transparent;}
.sr-locate:active{transform:scale(.94);}
.sr-locate{color:#111827;}
.sr-locate.on,.sr-locate.busy{color:#2563eb;}
.sr-locate svg{width:24px;height:24px;stroke:currentColor;}
.sr-locate.on svg{stroke:#2563eb;}
.sr-locate.busy svg{animation:srLocSpin 1s linear infinite;stroke:#2563eb;}
@keyframes srLocSpin{to{transform:rotate(360deg)}}
.sr-locate-toast{position:absolute;right:0;bottom:56px;white-space:nowrap;background:rgba(17,24,39,.88);color:#fff;font-size:12.5px;padding:7px 11px;border-radius:10px;pointer-events:none;}

.user-marker-pulse{

  position:absolute;left:50%;top:50%;width:28px;height:28px;

  transform:translate(-50%,-50%);border-radius:50%;

  background:rgba(59,130,246,.22);animation:userPulse 1.8s ease-out infinite;

}

.user-marker-dot{

  position:absolute;left:50%;top:50%;width:13px;height:13px;

  transform:translate(-50%,-50%);border-radius:50%;

  background:#3b82f6;border:2.5px solid #fff;

  box-shadow:0 2px 6px rgba(0,0,0,.25);

}

@keyframes userPulse{

  0%{transform:translate(-50%,-50%) scale(.7);opacity:.9;}

  100%{transform:translate(-50%,-50%) scale(1.8);opacity:0;}

}



/* ══ locBtn ══ */

#locBtn{

  position:absolute;bottom:20px;right:20px;z-index:3500;

  width:44px;height:44px;border-radius:50%;border:none;

  background:#fff;

  display:flex;align-items:center;justify-content:center;

  box-shadow:0 4px 14px rgba(0,0,0,.18);cursor:pointer;transition:box-shadow .15s;

}

#locBtn:hover{box-shadow:0 6px 20px rgba(59,130,246,.25);}

@media(max-width:900px){#locBtn{display:none!important;}}



/* ══ Leaflet 팝업 ══ */

.leaflet-popup-content-wrapper{

  overflow:visible!important;border-radius:16px!important;

  box-shadow:0 8px 32px rgba(0,0,0,.15)!important;

}

.leaflet-popup-content{overflow:visible!important;margin:14px 16px!important;}

.popup-title{font-size:15px;font-weight:900;margin-bottom:5px;line-height:1.35;}

.popup-meta{font-size:12px;color:#64748b;line-height:1.5;margin-bottom:6px;}



/* ══ 모바일 지도 팝업 ══ */

.mobile-map-popup{position:fixed;inset:0;background:#fff;z-index:2000;display:none;flex-direction:column;}

.mobile-map-header{

  height:54px;display:flex;align-items:center;justify-content:space-between;

  padding:0 14px;border-bottom:1px solid #e5e7eb;background:#fff;flex-shrink:0;

}

.mobile-map-close{

  border:none;background:#3b82f6;color:#fff;

  padding:7px 14px;border-radius:8px;font-weight:700;font-size:13px;cursor:pointer;

}

.mobile-map{flex:1;}





/* ══ 모바일 결과 패널 ══ */

.mobile-result-panel{

  position:absolute;left:0;right:0;bottom:0;

  width:100%;height:180px;max-height:40%;

  background:#fff;

  border-top-left-radius:18px;border-top-right-radius:18px;

  box-shadow:0 -4px 20px rgba(0,0,0,.12);

  z-index:3000;display:none;flex-direction:column;

}

@media(max-width:900px){.mobile-result-panel{position:fixed;}}

.mobile-result-header{padding:10px 14px;font-weight:700;font-size:13px;border-bottom:1px solid #f1f5f9;display:flex;align-items:center;justify-content:space-between;gap:8px;}

.mobile-result-list{overflow:auto;flex:1;}

.mobile-result-item{padding:10px 14px;border-bottom:1px solid #f8fafc;font-size:13px;cursor:pointer;}

.mobile-result-item:hover{background:#f8fafc;}

.mobile-result-distance{font-size:12px;color:#3b82f6;font-weight:600;}



/* ══ mobileLocBtn ══ */

#mobileLocBtn{

  position:absolute;bottom:200px;right:12px;z-index:4500;

  width:48px;height:48px;border-radius:50%;border:none;

  background:linear-gradient(135deg,#3b82f6,#60a5fa);

  display:flex;align-items:center;justify-content:center;

  box-shadow:0 4px 16px rgba(59,130,246,.4);cursor:pointer;

}



/* ══ 알약 필터 바 ══ */

@media(max-width:900px){#pcPillBar{display:none!important;}}

.mobile-pill-bar{

  position:absolute;top:14px;left:50%;transform:translateX(-50%);

  right:auto;z-index:3500;

  display:flex;gap:7px;padding:0 8px;

  overflow-x:auto;-webkit-overflow-scrolling:touch;

  scrollbar-width:none;flex-wrap:nowrap;white-space:nowrap;

}

.mobile-pill-bar::-webkit-scrollbar{display:none;}

.mobile-pill{

  flex-shrink:0;height:28px;padding:0 10px;

  border-radius:999px;border:1.5px solid rgba(255,255,255,.85);

  background:rgba(255,255,255,.93);

  font-size:11px;font-weight:700;cursor:pointer;

  white-space:nowrap;display:flex;align-items:center;gap:4px;

  box-shadow:0 2px 8px rgba(0,0,0,.10);transition:all .15s;

  backdrop-filter:blur(8px);

}

.mobile-pill.active{color:#1a202c;border-width:2px;background:rgba(255,255,255,.98);}

.mobile-pill.active svg{opacity:1;}



/* ══ 나침반 버튼 ══ */

.map-compass-btn{

  position:absolute;bottom:72px;right:20px;z-index:1000;

  width:44px;height:44px;border-radius:50%;border:none;

  background:#fff;display:flex;align-items:center;justify-content:center;

  box-shadow:0 4px 14px rgba(0,0,0,.15);cursor:pointer;transition:transform .3s;

}



/* ══ 모바일 레이아웃 ══ */

@media(max-width:900px){

  .page{display:block;height:auto;min-height:100vh;}

  .sidebar{width:100%;min-width:0;box-shadow:none;}

  .map-wrap{display:block;position:static;width:100%;height:0;overflow:visible;}

  #map{display:none;}

  .mobile-map-popup .map-legend{

    display:none!important;

  }

}



/* ══ 기타 ══ */

.leaflet-control-attribution{display:none!important;}



/* ══ 모바일 지도 줌 컨트롤: 알약 메뉴 아래로 이동 ══ */

@media(max-width:900px){

  #mobileMapPopup .leaflet-top.leaflet-left{

    top:112px !important;

  }

  #mobileMapPopup .leaflet-control-zoom{

    margin-top:0 !important;

  }

}

.sexoffender-btn{width:100%;}

@keyframes floatChar{0%{transform:translateY(0);}50%{transform:translateY(-6px);}100%{transform:translateY(0);}}

.char{width:80px;animation:floatChar 2.2s ease-in-out infinite;}

.loading-dots::after{content:"";animation:dots 1.4s steps(3,end) infinite;}

@keyframes dots{0%{content:"";}33%{content:".";}66%{content:"..";}100%{content:"...";}}</style>{% endraw %}

{% if detail_on %}
<link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/variable/pretendardvariable-dynamic-subset.min.css">
{% raw %}<style id="sr-theme">
/* ===== 안전로드 새 디자인 (밝은 카드형) — 관리자 스위치 ON 일 때만 ===== */
:root{
  --sr-blue:#2563eb; --sr-blue-600:#1d4ed8; --sr-blue-50:#eff6ff; --sr-blue-100:#dbeafe;
  --sr-ink:#111827; --sr-text:#374151; --sr-sub:#6b7280; --sr-line:#eceef3; --sr-bg:#f6f7fb;
  --sr-shadow:0 1px 2px rgba(17,24,39,.04),0 8px 24px rgba(17,24,39,.06);
}
html,body{font-family:'Pretendard Variable','Pretendard','Apple SD Gothic Neo','Malgun Gothic',sans-serif;background:var(--sr-bg);color:var(--sr-ink);letter-spacing:-0.01em;}
.sidebar{background:var(--sr-bg);border-right:1px solid var(--sr-line);}
.sidebar-scroll{padding:16px;}

/* 상단 브랜드 */
.brand{background:#fff;border-bottom:1px solid var(--sr-line);padding:16px 18px;}
.brand-accent{display:none;}
.brand-title{font-size:18px;color:var(--sr-blue);letter-spacing:-0.4px;}
.brand-sub{font-size:11px;color:var(--sr-sub);}

/* 첫 문구: 파란 카드 */
.sr-hero{position:relative;overflow:hidden;background:linear-gradient(135deg,#2563eb,#3b82f6);border-radius:22px;padding:24px 20px 28px;margin-bottom:12px;box-shadow:0 4px 14px rgba(37,99,235,.25);}
.sr-hero-chip{display:inline-block;padding:4px 10px;border-radius:999px;background:rgba(255,255,255,.18);color:#fff;font-size:11.5px;font-weight:700;margin-bottom:12px;}
.sr-hero-t{position:relative;font-size:21px;font-weight:900;line-height:1.4;letter-spacing:-0.6px;color:#fff;word-break:keep-all;padding-right:24px;}
.sr-hero-s{position:relative;font-size:13px;color:#dbeafe;margin-top:8px;}
.sr-hero-deco{position:absolute;right:-10px;bottom:-14px;width:92px;height:92px;opacity:.16;}
.sr-hero-t,.sr-hero-s{padding-right:60px!important;}
.sr-hero-s{line-height:1.5;}

/* 카드 */
.s-card{background:#fff;border:1px solid var(--sr-line);border-radius:18px;padding:16px;margin-bottom:12px;box-shadow:var(--sr-shadow);}
.s-card-label{border-bottom:none;padding-bottom:0;margin-bottom:12px;font-size:15px;font-weight:900;color:var(--sr-ink);}
.s-card-label > span:first-child::before{display:none;}

/* 빠른 찾기 타일 */
.sr-tiles{display:grid;grid-template-columns:1fr 1fr;gap:10px;}
.sr-tile{display:flex;flex-direction:column;align-items:flex-start;gap:6px;padding:14px;border-radius:18px;border:none;background:#f6f7fb;text-align:left;cursor:pointer;font-family:inherit;transition:filter .15s,transform .1s;}
.sr-tile:hover{filter:brightness(.97);}
.sr-tiles .sr-tile:nth-child(1){background:#eef2ff;}
.sr-tiles .sr-tile:nth-child(2){background:#fff4e8;}
.sr-tiles .sr-tile:nth-child(3){background:#eaf2ff;}
.sr-tiles .sr-tile:nth-child(4){background:#f1f2f6;}
.sr-tiles .sr-ico{background:#fff!important;box-shadow:0 2px 6px rgba(17,24,39,.06);}
.sr-tile:active{transform:scale(.98);}
.sr-ico{width:40px;height:40px;border-radius:12px;display:flex;align-items:center;justify-content:center;margin-bottom:2px;}
.sr-t{font-size:15px;font-weight:800;color:var(--sr-ink);}
.sr-s{font-size:12px;color:var(--sr-sub);}

/* 입력 */
.form-label{font-size:12px;color:var(--sr-sub);font-weight:700;margin:12px 0 6px;}
.form-select{height:44px;border-radius:12px;border:1px solid #e5e7eb;background-color:#f9fafb;font-size:14px;color:var(--sr-ink);}
.form-select:focus{border-color:var(--sr-blue);box-shadow:0 0 0 3px rgba(37,99,235,.15);}
.town-multi-wrap{border:1px solid #e5e7eb;border-radius:12px;}
.check-item{border:1px solid #e5e7eb;border-radius:12px;padding:10px 12px;font-size:13.5px;}
.check-item:has(input:checked){border-color:var(--sr-blue);background:var(--sr-blue-50);}
.btn-reset{border:1px solid #e5e7eb;box-shadow:none;color:var(--sr-sub);}

/* 버튼 */
.btn-main{height:50px;border-radius:14px;background:linear-gradient(135deg,#2563eb,#3b82f6);box-shadow:0 4px 14px rgba(37,99,235,.3);font-size:15px;font-weight:900;}
.btn-main:hover{background:var(--sr-blue-600);opacity:1;}
.btn-action{height:46px;border-radius:14px;border:1px solid var(--sr-line);background:#fff;color:var(--sr-text);font-weight:700;}
.btn-action:hover{background:#f9fafb;border-color:#dfe3ea;color:var(--sr-ink);}

/* 방문자 */
.visitor-box{background:#f9fafb;border:none;border-radius:14px;}
.visitor-num{color:var(--sr-ink);font-weight:900;}
.visitor-lbl{font-size:11px;color:var(--sr-sub);letter-spacing:0;}
.sidebar-footer{background:transparent;border-top:none;color:#9ca3af;}

/* 지도 공통 */
.leaflet-bar{border:none!important;border-radius:12px!important;overflow:hidden;box-shadow:var(--sr-shadow)!important;}
.leaflet-bar a{width:38px!important;height:38px!important;line-height:38px!important;color:var(--sr-text)!important;border-bottom:1px solid var(--sr-line)!important;}
.leaflet-bar a:last-child{border-bottom:none!important;}
.mobile-pill{height:34px;padding:0 13px;border:1px solid var(--sr-line)!important;background:#fff;box-shadow:0 2px 10px rgba(17,24,39,.08);font-size:12.5px;}
.mobile-pill.active{background:var(--sr-ink)!important;color:#fff!important;border-color:var(--sr-ink)!important;}
.leaflet-popup-content-wrapper{border-radius:20px!important;box-shadow:0 14px 40px rgba(17,24,39,.18)!important;}
.popup-title{font-size:17px;font-weight:900;color:var(--sr-ink);}
.popup-meta{font-size:13px;color:#4b5563;}

/* 모바일 지도: 지도를 화면 전체로, 뒤로 버튼은 떠 있는 버튼 */
.mobile-map-header{position:absolute;top:12px;left:12px;z-index:4600;height:auto;padding:0;border:none;background:transparent;}
.mobile-map-header > span,.mobile-map-header > div{display:none;}
.mobile-map-close{height:44px;padding:0 16px 0 12px;border-radius:14px;background:#fff;color:var(--sr-ink);font-size:14px;font-weight:800;box-shadow:0 6px 18px rgba(17,24,39,.16);}
.mobile-map-close::before{content:"‹";font-size:22px;line-height:0;margin-right:6px;position:relative;top:2px;}
#mobilePillBar{top:66px!important;}
#mobileMapPopup .leaflet-top.leaflet-left{top:116px!important;}
.mobile-result-panel{border-top-left-radius:24px;border-top-right-radius:24px;box-shadow:0 -10px 30px rgba(17,24,39,.14);}
.mobile-result-panel::before{content:"";display:block;flex-shrink:0;width:40px;height:4px;border-radius:4px;background:#d1d5db;margin:10px auto 0;}
.mobile-result-header{font-size:16px;font-weight:900;padding:10px 18px 12px;border-bottom:1px solid #f3f4f6;}
.mobile-result-item{padding:13px 18px;border-bottom:1px solid #f3f4f6;}
.mobile-result-distance{display:inline-block;margin-top:3px;background:var(--sr-blue-50);color:var(--sr-blue-600);border-radius:8px;padding:2px 8px;font-weight:800;}
#mobileLocBtn{background:var(--sr-blue);box-shadow:0 8px 20px rgba(37,99,235,.35);}

/* PC: 왼쪽 메뉴를 넓혀 타일 글자가 줄바꿈되지 않게 */
@media (min-width:901px){
  .sidebar{width:360px;min-width:360px;}
  .sr-hero-t{font-size:20px;}
  .sr-tile{padding:13px;}
  .sr-t{font-size:14.5px;white-space:nowrap;}
  .sr-s{font-size:11.5px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:100%;}
}
.sr-t{white-space:nowrap;}

/* 내 주변 찾기 창: 어두운 머리 → 밝게 */
#facilityFabMenu > div{border-radius:22px!important;}
#facilityFabMenu > div > div:first-child,#routePopup > div > div:first-child,#addrSearchPopup > div > div:first-child{position:relative;background:#fff!important;border-bottom:none!important;padding:22px 20px 4px 74px!important;min-height:46px;}
#facilityFabMenu > div > div:first-child::before,#routePopup > div > div:first-child::before,#addrSearchPopup > div > div:first-child::before{content:"";position:absolute;left:20px;top:20px;width:42px;height:42px;border-radius:13px;background-color:#eff6ff;background-position:center;background-repeat:no-repeat;background-size:22px;}
#facilityFabMenu > div > div:first-child::before{background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%232563eb' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Ccircle cx='12' cy='12' r='7'/%3E%3Ccircle cx='12' cy='12' r='2.5'/%3E%3Cpath d='M12 2v3M12 19v3M2 12h3M19 12h3'/%3E%3C/svg%3E");}
#routePopup > div > div:first-child::before{background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%232563eb' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Ccircle cx='6' cy='19' r='2.5'/%3E%3Ccircle cx='18' cy='5' r='2.5'/%3E%3Cpath d='M8.5 19H16a3.5 3.5 0 0 0 0-7H8a3.5 3.5 0 0 1 0-7h7.5'/%3E%3C/svg%3E");}
#addrSearchPopup > div > div:first-child::before{background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%232563eb' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M12 21s-7-6.2-7-11.5a7 7 0 0 1 14 0C19 14.8 12 21 12 21z'/%3E%3Ccircle cx='12' cy='9.5' r='2.5'/%3E%3C/svg%3E");}
#facilityFabMenu > div > div:first-child > div:first-child,#routePopup > div > div:first-child > div:first-child,#addrSearchPopup > div > div:first-child > div:first-child{color:#111827!important;font-size:16.5px!important;letter-spacing:-0.3px;margin-bottom:3px!important;}
#facilityFabMenu > div > div:first-child > div:last-child,#routePopup > div > div:first-child > div:last-child,#addrSearchPopup > div > div:first-child > div:last-child{color:#6b7280!important;font-size:12.5px!important;}
#routePopup > div,#addrSearchPopup > div{border-radius:22px!important;}
#facilityFabMenu button{border-radius:14px!important;}
/* 결과 목록: 카드형 */
.mobile-result-list{padding:6px 10px 10px;}
.mobile-result-item{position:relative;padding:12px 84px 12px 56px!important;margin:4px 0;border:1px solid #eef0f4!important;border-radius:14px;background:#fff;font-size:12.5px;color:#6b7280;line-height:1.5;transition:background .15s,border-color .15s;}
.mobile-result-item:hover{background:#f8fafc;border-color:#dfe3ea!important;}
.mobile-result-item b{font-size:14px;color:#111827;font-weight:800;}
.mobile-result-item::before{content:"";position:absolute;left:12px;top:50%;width:32px;height:32px;margin-top:-16px;border-radius:10px;background:radial-gradient(circle,#2563eb 0 5px,#eff6ff 6px);}
.mobile-result-item[data-gubun="공중화장실"]::before{background:radial-gradient(circle,#f59e0b 0 5px,#fff7e6 6px);}
.mobile-result-item[data-gubun="공영주차장"]::before{background:radial-gradient(circle,#8b5cf6 0 5px,#f3eefe 6px);}
.mobile-result-item[data-gubun="민영주차장"]::before{background:radial-gradient(circle,#8b5cf6 0 5px,#f3eefe 6px);}
.mobile-result-item[data-gubun="자동심장충격기"]::before{background:radial-gradient(circle,#16a34a 0 5px,#e9f8ee 6px);}
.mobile-result-item[data-gubun="상습결빙지역"]::before{background:radial-gradient(circle,#06b6d4 0 5px,#e6f8fb 6px);}
.mobile-result-item[data-gubun="교통사고위험지역"]::before{background:radial-gradient(circle,#ef4444 0 5px,#fdecec 6px);}
.mobile-result-item .mobile-result-distance{position:absolute;right:12px;top:50%;transform:translateY(-50%);margin:0!important;}
.mobile-result-item .mobile-result-distance:empty{display:none;}
.mobile-result-header{border-bottom:none!important;}
html body .sr-hero-deco{right:16px!important;bottom:14px!important;width:60px!important;height:60px!important;opacity:.18!important;}
@media (max-width:600px){ html body .sr-hero-deco{right:14px!important;bottom:12px!important;width:50px!important;height:50px!important;} html body .sr-hero-s{padding-right:58px!important;} }
/* 모바일: 한 화면에 더 많이 */
@media (max-width:600px){
  .sr-hero{padding:18px 18px 18px!important;border-radius:20px!important;margin-bottom:10px!important;}
  .sr-hero-t{font-size:clamp(14px, calc((100vw - 74px) / 17.5), 18px)!important;line-height:1.42!important;padding-right:0!important;white-space:nowrap;}
  .sr-hero-s{font-size:12.5px!important;margin-top:6px!important;padding-right:0!important;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
  .sr-hero-deco{width:64px!important;height:64px!important;right:-8px!important;bottom:-10px!important;}
  .sr-tiles{gap:8px!important;}
  .sr-tile{padding:11px 12px!important;gap:3px!important;border-radius:16px!important;min-width:0;}
  .sr-ico{width:32px!important;height:32px!important;border-radius:10px!important;margin-bottom:3px!important;}
  .sr-ico svg{width:18px;height:18px;}
  .sr-t{font-size:14.5px!important;white-space:nowrap;}
  .sr-s{font-size:11.5px!important;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:100%;}
  html body #categoryBox{gap:6px!important;grid-template-columns:minmax(0,1fr) minmax(0,1fr)!important;}
  html body #categoryBox .check-item{flex-direction:row!important;align-items:center!important;gap:7px!important;min-height:0!important;padding:11px 8px 11px 9px!important;border-radius:14px!important;font-size:13px!important;letter-spacing:-0.4px;}
  html body #categoryBox .check-item .dot{width:22px!important;height:22px!important;flex:0 0 22px!important;border-radius:7px!important;}
  html body #categoryBox .check-item .dot::after{width:7px;height:7px;margin:-3.5px;}
  html body #categoryBox .check-item::after{display:none!important;}
  html body #categoryBox .check-item:has(input:checked){border-width:2px!important;padding:10px 7px 10px 8px!important;}
  html body #categoryBox .check-item:has(input:checked) > span:last-child{color:#1d4ed8;}
  html body #categoryBox .check-item > span:last-child{min-width:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
  html body #categoryBox .check-item > span:last-child span{display:none!important;}
}
/* 구분: 2x2 카드 */
#categoryBox{display:grid!important;grid-template-columns:1fr 1fr;gap:8px;}
#categoryBox .check-item{position:relative;display:flex!important;flex-direction:column;align-items:flex-start;gap:10px;min-height:88px;padding:14px!important;border:1.5px solid #e8ebf0!important;border-radius:16px!important;background:#fff;cursor:pointer;font-size:14px!important;font-weight:800;color:#111827;line-height:1.3;transition:border-color .15s,background .15s;}
#categoryBox .check-item:hover{border-color:#d5dae2!important;}
#categoryBox .check-item input{position:absolute;opacity:0;pointer-events:none;}
#categoryBox .check-item .dot{position:relative;width:34px!important;height:34px!important;border-radius:11px!important;margin:0!important;flex:0 0 34px!important;}
#categoryBox .check-item .dot::after{content:"";position:absolute;left:50%;top:50%;width:10px;height:10px;margin:-5px;border-radius:50%;background:#fff;}
#categoryBox .check-item > span:last-child span{display:block;font-weight:600;}
#categoryBox .check-item::after{content:"";position:absolute;right:12px;top:12px;width:20px;height:20px;border-radius:50%;border:1.5px solid #d1d5db;background:#fff;box-sizing:border-box;}
#categoryBox .check-item:has(input:checked){border-color:#2563eb!important;background:#f5f8ff!important;}
#categoryBox .check-item:has(input:checked)::after{border-color:#2563eb;background:#2563eb url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='white' stroke-width='3.2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M5 12.5l4.5 4.5L19 7.5'/%3E%3C/svg%3E") center/12px no-repeat;}
/* 로딩: 위치 찾기 */
#msgBox.sr-loading{width:300px;}
#msgBox.sr-loading #msgText{padding:30px 22px 28px!important;margin-bottom:0!important;}
.sr-ld{text-align:center;}
.sr-radar{position:relative;width:104px;height:104px;margin:0 auto 18px;}
.sr-radar i{position:absolute;inset:0;border-radius:50%;background:rgba(37,99,235,.22);animation:srPulse 2.1s cubic-bezier(.2,.6,.3,1) infinite;}
.sr-radar i:nth-child(2){animation-delay:.7s;}
.sr-radar i:nth-child(3){animation-delay:1.4s;}
.sr-radar b{position:absolute;left:50%;top:50%;width:46px;height:46px;margin:-23px 0 0 -23px;border-radius:50%;background:linear-gradient(135deg,#2563eb,#3b82f6);box-shadow:0 6px 16px rgba(37,99,235,.35);display:flex;align-items:center;justify-content:center;}
@keyframes srPulse{0%{transform:scale(.42);opacity:.95;}100%{transform:scale(1.15);opacity:0;}}
.sr-ld-t{font-size:16.5px;font-weight:900;color:#111827;letter-spacing:-0.3px;}
.sr-ld-s{font-size:12.5px;color:#6b7280;margin-top:6px;font-weight:500;}
/* 로딩: 데이터 불러오기 */
#loadingBox{white-space:nowrap;background:#fff!important;color:#111827!important;padding:14px 20px 14px 50px!important;border-radius:999px!important;box-shadow:0 12px 32px rgba(17,24,39,.18);font-size:13.5px!important;font-weight:800!important;}
#loadingBox::before{content:"";position:absolute;left:18px;top:50%;width:20px;height:20px;margin-top:-10px;border-radius:50%;border:3px solid #dbe5ff;border-top-color:#2563eb;animation:srSpin .8s linear infinite;box-sizing:border-box;}
@keyframes srSpin{to{transform:rotate(360deg);}}
.sr-trim{font-size:12px;font-weight:600;color:#9ca3af;margin-left:2px;}
.mobile-result-item.sr-rich{display:flex;align-items:center;gap:12px;padding:10px 12px!important;}
.mobile-result-item.sr-rich::before{display:none;}
.sr-rv{position:relative;flex-shrink:0;width:84px;height:62px;border-radius:10px;overflow:hidden;background:#eef1f5;}
.sr-rv-pano{position:absolute;left:0;top:0;width:336px;height:248px;transform:scale(.25);transform-origin:0 0;}
.sr-rv-msg{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;text-align:center;padding:4px;font-size:10px;line-height:1.3;color:#94a3b8;z-index:2;}
.sr-rv-cover{position:absolute;inset:0;z-index:3;}
.sr-rv-tag{position:absolute;left:4px;top:4px;z-index:3;width:10px;height:10px;border-radius:50%;border:2px solid #fff;box-shadow:0 1px 3px rgba(0,0,0,.25);}
.sr-txt{flex:1;min-width:0;}
.sr-txt b{display:block;}
.sr-nm{font-size:13px;font-weight:700;color:#334155;margin-top:1px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
.sr-upd{display:inline-flex;align-items:center;gap:3px;margin-left:6px;padding:2px 8px;border-radius:999px;background:#f1f5f9;color:#64748b;font-size:11px;font-weight:600;line-height:1.4;vertical-align:2px;white-space:nowrap;letter-spacing:-.2px;}
.sr-upd::before{content:"";width:5px;height:5px;border-radius:50%;background:#94a3b8;}
.sr-upd.old{background:#fff7ed;color:#c2410c;}
.sr-upd.old::before{background:#f59e0b;}
/* 로드뷰 속 시설 핀 (출장 도구함과 같은 모양) */
.rvpin{display:flex;flex-direction:column;align-items:center;pointer-events:none;filter:drop-shadow(0 2px 4px rgba(0,0,0,.45))}
.rvpin b{background:#e11d48;color:#fff;font-size:14px;font-weight:800;padding:6px 11px;border-radius:999px;white-space:nowrap;border:2px solid #fff}
.rvpin i{width:0;height:0;border-left:9px solid transparent;border-right:9px solid transparent;border-top:13px solid #e11d48;margin-top:-1px;animation:rvbob 1.1s ease-in-out infinite}
@keyframes rvbob{50%{transform:translateY(5px)}}
.rvpin.sm{filter:none}
.rvpin.sm i{border-left-width:19px;border-right-width:19px;border-top-width:30px;border-top-color:#ff1f4b;
  filter:drop-shadow(0 0 1.5px #fff) drop-shadow(0 0 1.5px #fff) drop-shadow(0 0 1.5px #fff) drop-shadow(0 2px 4px rgba(0,0,0,.7));
  animation:rvbob .9s ease-in-out infinite}
.sr-addr{font-size:12px;color:#6b7280;margin-top:2px;overflow:hidden;text-overflow:ellipsis;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;word-break:keep-all;}
.mobile-result-item.sr-rich .mobile-result-distance{position:static!important;transform:none!important;flex-shrink:0;align-self:center;}
@media (max-width:900px){
  .mobile-result-panel{height:350px!important;max-height:52%!important;}
}
@media (min-width:901px){
  .sr-hero{padding:22px 18px 24px!important;}
  .sr-hero-t{font-size:19px!important;padding-right:24px!important;}
  .sr-hero-s{font-size:11.5px!important;padding-right:52px!important;white-space:nowrap;}
  .sr-hero-deco{width:72px!important;height:72px!important;right:-8px!important;bottom:-10px!important;}
}
/* PC: 지도 왼쪽 아래에 떠 있는 패널 */
@media (min-width:901px){
  .mobile-result-panel{left:16px!important;right:auto!important;bottom:16px!important;width:360px!important;height:auto!important;max-height:min(62%,560px)!important;border-radius:22px!important;box-shadow:0 18px 44px rgba(17,24,39,.18)!important;overflow:hidden;}
  .mobile-result-panel::before{display:none!important;}
  .mobile-result-header{padding:16px 18px 6px!important;}
}
/* 알림 팝업: 다른 팝업과 같은 모양 */
#msgBox{padding:0!important;width:340px;min-width:0!important;max-width:92vw!important;border-radius:22px!important;overflow:hidden;box-shadow:0 20px 60px rgba(0,0,0,.25)!important;}
#msgText{padding:24px 22px 0;margin-bottom:18px!important;font-size:14.5px!important;}
#msgBtn{width:calc(100% - 44px);margin:0 22px 22px;height:46px;padding:0!important;border-radius:13px!important;background:linear-gradient(135deg,#2563eb,#3b82f6)!important;font-size:15px!important;font-weight:800!important;box-shadow:0 4px 14px rgba(37,99,235,.3);cursor:pointer;}
.sr-msg-head{display:none;position:relative;background:#fff;padding:22px 20px 4px 74px;min-height:46px;text-align:left;}
.sr-msg-head::before{content:"";position:absolute;left:20px;top:20px;width:42px;height:42px;border-radius:13px;background:#eff6ff url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%232563eb' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Ccircle cx='12' cy='12' r='9'/%3E%3Cpath d='M12 8h.01M11 12h1v5h1'/%3E%3C/svg%3E") center/22px no-repeat;}
.sr-msg-head.on{display:block;}
.sr-msg-head .t{font-size:16.5px;font-weight:900;color:#111827;margin-bottom:3px;letter-spacing:-0.3px;}
.sr-msg-head .s{font-size:12.5px;color:#6b7280;}
.sr-msg-head.on + #msgText{padding-top:14px;}
.sr-msg-head.on + #msgText{text-align:left;font-weight:500!important;color:#374151!important;}
</style>{% endraw %}
{% endif %}

</head>

<body>



<div class="page">

  <aside class="sidebar">



    <!-- 브랜드 헤더 -->

    <div class="brand">

      <div class="brand-accent"></div>

      <div class="brand-left">

        <div class="brand-title" onclick="goHome()">장기요양 안전로드</div>

        <div class="brand-sub">자료제공: 행정안전부(생활안전지도)</div>

      </div>

      <img src="/ci" class="ci-logo">

    </div>



    <div class="sidebar-scroll">



{% if detail_on %}
      <!-- 새 디자인: 첫 문구 -->
      <div class="sr-hero">
        <div class="sr-hero-t">출장 지역의 위험구간과 편의시설을<br>한눈에 확인합니다.</div>
        <div class="sr-hero-s">화장실, 주차장, AED, 결빙, 사고지역</div>
        <svg class="sr-hero-deco" width="120" height="120" viewBox="0 0 24 24" fill="none" stroke="#ffffff" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 3l7 3v5c0 4.5-3 8.3-7 10-4-1.7-7-5.5-7-10V6z"/><path d="M9 12l2 2 4-4"/></svg>
      </div>
      <!-- 새 디자인: 빠른 찾기 (순서는 기존과 같음) -->
      <div class="s-card">
        <div class="s-card-label"><span>빠른 찾기</span></div>
        <div class="sr-tiles">
          <button class="sr-tile" onclick="openRouteSearch()"><span class="sr-ico" style="background:#eef2ff;"><svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#4338ca" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="6" cy="18" r="2"/><circle cx="18" cy="6" r="2"/><path d="M6 16V9a4 4 0 0 1 4-4h6M18 8v7a4 4 0 0 1-4 4H8"/></svg></span><span class="sr-t">경로주변 찾기</span><span class="sr-s">출발지와 도착지 사이</span></button>
          <button class="sr-tile" onclick="openAddressSearch()"><span class="sr-ico" style="background:#fff7ed;"><svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#c2410c" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 21s-7-6.2-7-11a7 7 0 1 1 14 0c0 4.8-7 11-7 11z"/><circle cx="12" cy="10" r="2.5"/></svg></span><span class="sr-t">주소로 찾기</span><span class="sr-s">방문할 주소 주변</span></button>
          <button id="facilityFabBtn" class="sr-tile" onclick="toggleFacilityFab()"><span class="sr-ico" style="background:#eff6ff;"><svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#1d4ed8" stroke-width="2" stroke-linecap="round" aria-hidden="true"><circle cx="12" cy="12" r="7"/><circle cx="12" cy="12" r="2.5"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3"/></svg></span><span class="sr-t">내 주변 찾기</span><span class="sr-s">지금 위치 기준</span></button>
          <button class="sr-tile sexoffender-btn" onclick="openSexOffenderApp()"><span class="sr-ico" style="background:#f3f4f6;"><svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#374151" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 3l7 3v5c0 4.5-3 8.3-7 10-4-1.7-7-5.5-7-10V6z"/></svg></span><span class="sr-t">성범죄자 알림e</span><span class="sr-s">외부 서비스로 이동</span></button>
        </div>
        <button id="apkDownloadBtn" class="btn-action btn-green" style="display:none;margin-top:10px;" onclick="downloadApk()">안전로드 앱 다운로드 (Android)</button>
        {% raw %}<script>
        (function(){
          const params = new URLSearchParams(window.location.search);
          const fromApp = params.get("from_app") === "1";
          if(!fromApp && /Android/i.test(navigator.userAgent || "")){
            document.getElementById("apkDownloadBtn").style.display = "flex";
          }
        })();
        function downloadApk(){
          window.location.href="/download-apk";
        }
        </script>{% endraw %}
      </div>
{% endif %}
      <!-- 조회 조건 -->

      <div class="s-card">

        <div class="s-card-label">

          <span>{% if detail_on %}지역으로 조회{% else %}조회 조건{% endif %}</span>

          <button class="btn-reset" onclick="resetFilters()">초기화</button>

        </div>



        <label class="form-label">시도</label>

        <select id="province" class="form-select">

          <option value="">전체</option>

        </select>



        <label class="form-label">시군구</label>

        <select id="city" class="form-select">

          <option value="">전체</option>

        </select>



        <label class="form-label">읍면동 <span style="font-weight:400;color:#475569;font-size:10px;">(복수선택 가능)</span></label>

        <div class="town-multi-wrap" id="townMultiWrap">

          <div class="town-check-item" style="color:#475569;font-size:11px;">시군구를 먼저 선택하세요</div>

        </div>



        <label class="form-label">구분</label>

        <div class="check-grid" id="categoryBox"></div>



        <button class="btn-main" onclick="loadData()">조회</button>
        {% if detail_on %}
        <style>
        .sr-step{display:grid;grid-template-rows:0fr;opacity:0;transform:translateY(-6px);transition:grid-template-rows .3s ease,opacity .25s ease,transform .3s ease;}
        .sr-step > .sr-step-in{overflow:hidden;min-height:0;}
        .sr-step > .sr-step-in > label.form-label{display:block;margin-top:14px;}
        .sr-step.sr-show{grid-template-rows:1fr;opacity:1;transform:none;}
        .town-multi-wrap{display:grid!important;grid-template-columns:1fr 1fr;gap:6px;max-height:220px!important;padding:8px!important;background:#f6f7fb!important;border:1px solid #eceef3!important;border-radius:14px!important;}
        .town-multi-wrap > div.town-check-item{grid-column:1/-1;}
        .sr-tseg{display:flex;gap:4px;padding:4px;background:#f6f7fb;border:1px solid #eceef3;border-radius:14px;}
        .sr-tseg label{flex:1;min-width:0;}
        .sr-tseg input{position:absolute;opacity:0;pointer-events:none;}
        .sr-tseg span{display:flex;align-items:center;justify-content:center;gap:4px;height:40px;border-radius:10px;font-size:14px;font-weight:800;color:#6b7280;cursor:pointer;transition:background .15s,color .15s,box-shadow .15s;}
        .sr-tseg span em{font-style:normal;font-weight:600;font-size:12px;opacity:.8;}
        .sr-tseg input:checked + span{background:#fff;color:#2563eb;box-shadow:0 2px 8px rgba(17,24,39,.08);}
        .sr-sub .town-multi-wrap{margin-top:8px;}
        .sr-sel{position:relative;}
        .sr-sel-hit{position:absolute;inset:0;width:100%;border:none;background:transparent;cursor:pointer;padding:0;}
        .sr-sheet{position:fixed;inset:0;z-index:7000;background:rgba(15,23,42,.45);display:flex;align-items:flex-end;justify-content:center;opacity:0;pointer-events:none;transition:opacity .2s;}
        .sr-sheet.open{opacity:1;pointer-events:auto;}
        .sr-sheet-card{width:100%;max-width:480px;max-height:72vh;display:flex;flex-direction:column;background:#fff;border-radius:24px 24px 0 0;box-shadow:0 -10px 40px rgba(17,24,39,.2);transform:translateY(24px);transition:transform .25s ease;padding-bottom:env(safe-area-inset-bottom);}
        .sr-sheet.open .sr-sheet-card{transform:none;}
        .sr-sheet-card::before{content:"";display:block;width:40px;height:4px;border-radius:4px;background:#d1d5db;margin:10px auto 0;}
        .sr-sheet-head{display:flex;align-items:center;justify-content:space-between;padding:12px 20px 8px;}
        .sr-sheet-t{font-size:17px;font-weight:900;color:#111827;}
        .sr-sheet-x{width:34px;height:34px;border:none;border-radius:50%;background:#f3f4f6;color:#6b7280;font-size:14px;cursor:pointer;}
        .sr-sheet-list{overflow:auto;padding:4px 14px 18px;display:flex;flex-direction:column;gap:6px;}
        .sr-opt{display:flex;align-items:center;justify-content:space-between;width:100%;min-height:50px;padding:0 16px;border:1.5px solid #eef0f4;border-radius:14px;background:#fff;font-size:15px;font-weight:700;color:#111827;text-align:left;cursor:pointer;font-family:inherit;transition:background .12s,border-color .12s;}
        .sr-opt:hover{background:#f8fafc;}
        .sr-opt.on{border-color:#2563eb;background:#f5f8ff;color:#1d4ed8;}
        .sr-opt.on::after{content:"";width:22px;height:22px;border-radius:50%;background:#2563eb url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='white' stroke-width='3.2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M5 12.5l4.5 4.5L19 7.5'/%3E%3C/svg%3E") center/12px no-repeat;flex-shrink:0;}
        @media all{
          .sr-sheet{background:transparent;}
          .sr-sheet-card{position:fixed;max-width:none;border-radius:16px;border:1px solid #e5e7eb;box-shadow:0 16px 40px rgba(17,24,39,.16);transform:translateY(-6px);transition:transform .16s ease;}
          .sr-sheet.sr-up .sr-sheet-card{transform:translateY(6px);}
          .sr-sheet.open .sr-sheet-card{transform:none;}
          .sr-sheet-card::before,.sr-sheet-head{display:none;}
          .sr-sheet-list{padding:6px;gap:2px;}
          .sr-opt{min-height:40px;border:none;border-radius:10px;font-size:14px;padding:0 12px;}
          .sr-opt.on{background:#eff6ff;}
          .sr-opt.on::after{width:18px;height:18px;background-size:10px;}
        }
        .town-multi-wrap label.town-check-item{background:#fff;border:1px solid #e5e7eb;border-radius:10px;padding:8px 9px;font-size:12.5px;color:#374151;min-width:0;}
        .town-multi-wrap label.town-check-item span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
        .town-multi-wrap label.town-check-item:has(input:checked){border-color:#2563eb;background:#eff6ff;color:#1d4ed8;font-weight:700;}
        </style>
        <script>
        (function(){
          function wrapStep(ctrl){
            if(!ctrl) return null;
            var lbl = ctrl.previousElementSibling;
            var box = document.createElement("div"); box.className = "sr-step";
            var inner = document.createElement("div"); inner.className = "sr-step-in";
            box.appendChild(inner);
            ctrl.parentNode.insertBefore(box, lbl && lbl.tagName === "LABEL" ? lbl : ctrl);
            if(lbl && lbl.tagName === "LABEL") inner.appendChild(lbl);
            inner.appendChild(ctrl);
            return box;
          }
          var prov = document.getElementById("province");
          var city = document.getElementById("city");
          var cityStep = wrapStep(city);
          var townWrap = document.getElementById("townMultiWrap");
          var townStep = wrapStep(townWrap);
          // 읍면동: 전체 / 직접 선택
          var seg = document.createElement("div");
          seg.className = "sr-tseg";
          seg.innerHTML = '<label><input type="radio" name="sr_town_mode" value="all" checked><span>전체 <em id="srTownCnt"></em></span></label>' +
                          '<label><input type="radio" name="sr_town_mode" value="pick"><span>직접 선택</span></label>';
          var pickBox = document.createElement("div"); pickBox.className = "sr-step sr-sub";
          var pickIn = document.createElement("div"); pickIn.className = "sr-step-in";
          pickBox.appendChild(pickIn);
          townWrap.parentNode.insertBefore(seg, townWrap);
          townWrap.parentNode.insertBefore(pickBox, townWrap);
          pickIn.appendChild(townWrap);
          var lastCity = city ? city.value : "";
          function townMode(){ var r = seg.querySelector("input:checked"); return r ? r.value : "all"; }
          seg.addEventListener("change", function(){
            if(townMode() === "all") document.querySelectorAll(".town-check:checked").forEach(function(c){ c.checked = false; });
            sync();
          });
          function sync(){
            var p = prov && prov.value, c = city && city.value;
            if(c !== lastCity){ lastCity = c; seg.querySelector('input[value="all"]').checked = true; }
            if(document.querySelector(".town-check:checked") && townMode() === "all") seg.querySelector('input[value="pick"]').checked = true;
            var n = document.querySelectorAll(".town-check").length;
            var cnt = document.getElementById("srTownCnt"); if(cnt) cnt.textContent = n ? "(" + n + "곳)" : "";
            if(cityStep) cityStep.classList.toggle("sr-show", !!p);
            if(townStep) townStep.classList.toggle("sr-show", !!p && !!c);
            pickBox.classList.toggle("sr-show", townMode() === "pick");
          }
          // 시도·시군구: 둥근 선택 창
          var sheet = document.createElement("div");
          sheet.className = "sr-sheet";
          sheet.innerHTML = '<div class="sr-sheet-card"><div class="sr-sheet-head"><span class="sr-sheet-t"></span><button type="button" class="sr-sheet-x" aria-label="닫기">✕</button></div><div class="sr-sheet-list"></div></div>';
          document.body.appendChild(sheet);
          var curSel = null;
          function closeSheet(){ sheet.classList.remove("open"); document.body.style.overflow = ""; }
          function openSheet(sel, title){
            curSel = sel;
            sheet.querySelector(".sr-sheet-t").textContent = title;
            var list = sheet.querySelector(".sr-sheet-list");
            list.innerHTML = "";
            Array.prototype.forEach.call(sel.options, function(o){
              var b = document.createElement("button");
              b.type = "button";
              b.className = "sr-opt" + (o.value === sel.value ? " on" : "");
              b.textContent = o.textContent;
              b.onclick = function(){
                if(sel.value !== o.value){ sel.value = o.value; sel.dispatchEvent(new Event("change", {bubbles:true})); }
                closeSheet(); sync();
              };
              list.appendChild(b);
            });
            var card = sheet.querySelector(".sr-sheet-card");
            if(true){
              // 누른 칸 바로 아래에 펼치기 (아래 공간이 좁으면 위로)
              var r = sel.getBoundingClientRect();
              var below = window.innerHeight - r.bottom - 12, above = r.top - 12;
              var need = Math.min(420, sel.options.length * 42 + 14);
              var up = below < need && above > below;
              card.style.left = r.left + "px";
              card.style.width = Math.max(r.width, 220) + "px";
              card.style.maxHeight = Math.min(420, up ? above : below) + "px";
              card.style.top = up ? "" : (r.bottom + 6) + "px";
              card.style.bottom = up ? (window.innerHeight - r.top + 6) + "px" : "";
              sheet.classList.toggle("sr-up", up);
            } else {
              card.style.left = card.style.width = card.style.maxHeight = card.style.top = card.style.bottom = "";
              document.body.style.overflow = "hidden";
            }
            sheet.classList.add("open");
            var on = list.querySelector(".on"); if(on) list.scrollTop = Math.max(0, on.offsetTop - list.clientHeight / 2 + on.offsetHeight / 2);
          }
          window.addEventListener("scroll", function(e){ if(e.target && e.target.nodeType === 1 && sheet.contains(e.target)) return; if(sheet.classList.contains("open")) closeSheet(); }, true);
          window.addEventListener("resize", function(){ if(sheet.classList.contains("open")) closeSheet(); });
          sheet.addEventListener("click", function(e){ if(e.target === sheet || e.target.closest(".sr-sheet-x")) closeSheet(); });
          [[prov, "시도 선택"], [city, "시군구 선택"]].forEach(function(pair){
            var sel = pair[0]; if(!sel) return;
            var wrap = document.createElement("div"); wrap.className = "sr-sel";
            sel.parentNode.insertBefore(wrap, sel); wrap.appendChild(sel);
            var hit = document.createElement("button"); hit.type = "button"; hit.className = "sr-sel-hit"; hit.setAttribute("aria-label", pair[1]);
            hit.onclick = function(){ openSheet(sel, pair[1]); };
            wrap.appendChild(hit);
          });
          if(prov) prov.addEventListener("change", sync);
          if(city) city.addEventListener("change", sync);
          setInterval(sync, 400);
          sync();
        })();
        </script>
        {% endif %}

      </div>



{% if not detail_on %}
      <!-- 빠른 찾기 -->

      <div class="s-card">

        <div class="s-card-label"><span>빠른 찾기</span></div>

        <div class="btn-grid" style="margin-bottom:6px;">

          <button class="btn-action btn-kakao" onclick="openRouteSearch()">경로주변 찾기</button>

          <button class="btn-action btn-kakao" onclick="openAddressSearch()">주소로 찾기</button>

          <button id="facilityFabBtn" class="btn-action" onclick="toggleFacilityFab()">내 주변 찾기</button>

          <button class="btn-action sexoffender-btn" onclick="openSexOffenderApp()">성범죄자 알림e</button>

        </div>

        <button id="apkDownloadBtn" class="btn-action btn-green" style="display:none;" onclick="downloadApk()">안전로드 앱 다운로드 (Android)</button>

        {% raw %}<script>

        (function(){

  const params = new URLSearchParams(window.location.search);

  const fromApp = params.get("from_app") === "1";



  if(!fromApp && /Android/i.test(navigator.userAgent || "")){

    document.getElementById("apkDownloadBtn").style.display = "flex";

  }

})();

        function downloadApk(){

          window.location.href="/download-apk";

        }

        </script>{% endraw %}

      </div>



{% endif %}
      <!-- 방문자 수 -->

      <div class="s-card">

        <div class="s-card-label"><span>방문자 수</span></div>

        <div class="visitor-row">

          <div class="visitor-box">

            <div class="visitor-num">{{total_visit}}</div>

            <div class="visitor-lbl">총 방문자</div>

          </div>

          <div class="visitor-box">

            <div class="visitor-num">{{today_visit}}</div>

            <div class="visitor-lbl">오늘</div>

          </div>

        </div>

        <button class="btn-action" onclick="openAdminStats()">관리자</button>

      </div>



    </div><!-- /sidebar-scroll -->



    <div class="sidebar-footer">

      © 국민건강보험공단 광주전라제주지역본부 요양운영부

    </div>



  </aside>



  <main class="map-wrap">

  <div id="map"></div>



  <!-- 알약형 카테고리 필터 (PC+모바일 공통) -->

  <div class="mobile-pill-bar" id="pcPillBar">

    <button class="mobile-pill active" id="pc_pill_all"

      style="border-color:#475569;color:#1a202c;"

      onclick="pcPillFilter('전체')">

      <svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="#475569" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>

      전체

    </button>

    <button class="mobile-pill" id="pc_pill_ice"

      style="color:#1a202c;"

      onclick="pcPillFilter('상습결빙지역')">

      <svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="#06b6d4" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2v20M4.93 4.93l14.14 14.14M2 12h20M4.93 19.07l14.14-14.14"/><circle cx="12" cy="12" r="3"/></svg>

      상습결빙지역

    </button>

    <button class="mobile-pill" id="pc_pill_toilet"

      style="color:#1a202c;"

      onclick="pcPillFilter('공중화장실')">

      <svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="#f59e0b" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M9 2h6v2H9zM12 4v4M9 8H5a1 1 0 0 0-1 1v10a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1V9a1 1 0 0 0-1-1h-4"/><path d="M10 12v4M14 12v4"/></svg>

      공중화장실

    </button>

    <button class="mobile-pill" id="pc_pill_accident"

      style="color:#1a202c;"

      onclick="pcPillFilter('교통사고위험지역')">

      <svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="#ef4444" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>

      교통사고위험지역

    </button>

    <button class="mobile-pill" id="pc_pill_parking"

      style="color:#1a202c;"

      onclick="pcPillFilter('주차장')">

      <svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="#8b5cf6" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2"/><path d="M9 17V7h4a3 3 0 0 1 0 6H9"/></svg>

      주차장

    </button>

  </div>



  <div class="mobile-result-panel" id="mobileResultPanel">

    <div class="mobile-result-header">

      <span style="white-space:nowrap;">검색 결과 <span id="mobileResultCount">0</span>건</span><span id="ccbyBadge" style="display:none;align-items:center;gap:6px;font-weight:600;flex-shrink:0;"><span style="font-size:9px;color:#94a3b8;line-height:1.15;text-align:right;white-space:nowrap;">출처: 한국지능정보사회진흥원</span><img src="data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAJ8AAAA4CAIAAABsYL3hAAABMmlDQ1BJQ0MgUHJvZmlsZQAAeJx9kD9Lw0AYxn+Wgv8H0dEhYxelKuigLlUsOkmNYHVK0zQVmhiSlCK4+QX8EIKzowi6CjoIgpvgRxAH1/qkQdIlvsd797vnHu7ufaEwhqJYBs+Pw1q1YhzVj43RT0Y0BmHZUUB+yPXznnrfFv7x5cV404lsrV/KZqjHdaUpnnNTbifcSPki4V4cxOKrhEOztiW+FpfcIW4MsR2Eif9FvOF1unb2b6Yc//BA645ynm1OiQjoYHGOwT4rmqvaeXSJxT05YtqiiJpOKiKTUA5fSgtHTNK/9InLD9h86Pf795m29wi3azBxl2mldZiZhKfnTMt6GlihNZCKykKrBd83MF2H2Vfdc/LXyJzajEFtVc40XNXmSNnVf20WRcuUWWL1Fx+iTfmvd1mpAAAfVklEQVR42u18eVhUR7p3VZ3TezfdNNjsoLKDBEFE0Yj6JcQti4kTo9GYqDNmlvskT2L0jt9MojEYZ8y9jtcY7zzGbRyTODHmid4Yt0RRQFFAEJRNwyKrCnTTe/c5p+r7o6BtupFNTbzfk/pD6XPq1Km33rfe5fe+dSAhpLy8fM/uPdXV1QQQ8Ev739sIABAQAIICAxcvXjx12lRYWVn59ttvV1ReGx0VSTAgGAM4lMF+Jhp+mgZ73kb+V5BJCECQZZmmxia5RP7hxo3sgQMHrpSVvvPHVWNTx1ptNkAIpKN6UwYBIKD7NukRFAgBAIR4LwKE7osEAKF9idvP3h08L7oTCHve6HqJ29sIABD2zMz1DOk9jtvFXuPQ/yGAveYOeggioOefPngPIX3Ufa3uDt7XnAkhEEK3n913CZ2A90IRQID7I55k0hWjbyGEAACkUumttraNH2zctm0b29TUNEI3Ii4hzmq1OBwOhFAPMdB9hSEEva93D0dHvEskgAAADAi8u3LEfR3A3ZWCbovvLk0ecushw8RrXw1Gzr0H6a8/JQ0TAiFEEIlEIpYVQYQYhAAAGGOCCSdwnJPDWOhhM7z3S/siZ1AKob953mMAwnFcSGhYTGxs3fU6FkIIAbTbHRASnucRQoQQyk8X59y42y2zhBBCMICIZRiGZUUiEUIIdW8Q124mhBCO43me43meYAwRgj17HfaM78kl13WvP/qlauAHvUegHdxJ61EhBAIgEkukUinDMAaDwdCpt1isFouZEKBQyhVyuY9G7av1g4DY7XaHw0EIgRC5NpDrJR66ZvCTHD51ENntNowxYhALqVKDAELYvcUgdNc8roYQIAQCQDDGCCGZXCFixRjjLmNXXW29yWi2WS1mk8lms4klEqVSqVDI5QqFLiBAq/WVyxUYC3a7neM4hFC3DEHYWzED2Pul95oJvPcS9P+g9wg9JLtLLRGLxQqF0mQyXS66XFVZVXmtsrW51ck5eZ4HhLAilhWxOp0uPiEhJi4mPiHOz9/fZrM5HDYAkNsb+6BuwEn2w+xBUtetRwgAALBDstl0O8oVCrFYrO/orKwoulp2tfbH2uamFpPRzAscwYQQAiBAECKGkctlQUFB4SPD4xMSkpKTAoMCZTKZxWKh8tEnGQMK8iCFfUg93QwNlskUAIDCS4Unj50qKbpsMpn6HKS1ue1KSZlMIU8ck5A1Iyt9wniVysdkMgNA7iVSP7FPNgTuQggxFhhGpFAqDZ2dJ3Pz887m3bh+w2Qy99lfAABwvMPu0HcaKq5Vnj55JmJUxLjx46Y9MW3k6FFOh91us0GEhjPvQTNs8D2p7BJCfHw0BkPXl1/86/T3pw2dBnorLCwsMTHR39/fx8cHIWQ0GvV6fVVVVV1dnc1iLbpYVHG1YvKUSS8tWhAeHtHVpSeAQICG52gPac79OftwKNwVBEEqlYnF4sKCi19/+fW18mtOjoMQugwyhJBlWYZh6KYUBIHneYwxfZzjues116/XXC84fyFr1lNPzXxKpVabjMZHQcwhgAQQQohK5dPU2LR3197zuecxxiKRKDU15cUX50+aNCksLEwul6tUKoSQyWSy2WwtLS0lJSVfffVVXl6exWI5dfz7psamZb9ZnjT2MaPJSDD5WSnrFhHWPUy4Z19MlEqlgMnXXx76+uDXHR2d1EhTE6XT6aKjoxMSEgICArRarY+Pj91u7+zs7OjouHHjRkVFRUtLi8lkAgAghOrrGvZ+ureqovrlJQtHjx5tMhkxxvewHwPpVW93aOgKmQZ3GGMftbqluXXblm2ll0sBABEREStWrJg/f35kZKRrelarled5jUaj0WiCgoLGjRs3Z86cI0eObN26taKiovJa1Zb/2PLG22+kpqUaDPqHJYuDoq57ZVhw10Pvm7uYEJVKaTZb9u/954mjJxxOJ0KIinZGRsbs2bPT09OTkpJ8fX0hhKhH2RJCMMYOh6O6urqkpOT06dMnTpxob2+HEPI8n5tzrrmp6Te//c249HHGrq5+zPBgJPQ+lRvGWCaTm7qMez/dTVmblJS0fv36Z599FvWEQAihoqKiPXv2WK3WxYsXT58+nS50UFDQ66+/PmbMmHfffffMmTPNTc07//7pyj++EzEywmQanmZ6INhJt+1nxo0b19zSPO2J6RACQRA8JoQxVihVXV1d27duO3nsewFjKjvx8fErV65cs2bNM888M2rUKLlcjhDy8P0QQiKRKCgoKCUlJSsrKyEhwWq11tXVCYKAEOrs6LxWfjU4NCQyMtLhcPTjIg5lXYZj50SsiGVFn+/7/OTxk4SQhISEv/3tb3PmzHG50AihpqamVatWffbZZ6WlpTU1NY8//rhOp3OJUXh4+IQJE6qrq2trazs7Og16feq4FKlUxvNONKBvAYe8dwfsIJFICy8WGruMqM8tQIfABMvlcoEX9u7cc+5MHqQhEYTPPvvsnj17Vq1aNXr0aIwx6WneC0cbxlilUr3wwgs7dux49913dTod3Q1trbc+2bKttKRErdY8CG+CDDIc8pikQqm4Wl7+/akfBAGHhoauW7cuKyuLztw1QlNTU2VlJf27pqbm5s2brldACDHGcXFxH3744WOPPQYAuHjh0tkz52RSKYTILfwdkgK6L7fLlS9A93qzS6i/Pnjoh5OnEUKAEKlUumzZsu3bt0+YMMEl17CneYsIbVTrYoyDgoLWrFnz0UcfRUZGuhi88++7mhqbVCqVywW7T+/R9eBAI0BCsEQisZitJ4+f0nfqRSLRsmXLXnjhBRdc4LJzMTExTz75pEKhkEgkTz31VGJiovvg1FSNHz9+9erVGo2G47gfTv3Q3NwilUoJwT8LGj+AZoYQqnx8cn7I+efufXa7HUDAMMzy5cs3bNgQGBhIeTN45enywhiGSU5ODg8PLygoMBgMCKH2O+1mi3nc+PEiVkTBsuGYquEqN7lcUX6l7OAXBx0Ox7hx47Kzs/38/DwUAIRQLBZPmjQpJibmiSee+MMf/hAcHOxNPoRw9OjR5eXllZWVHR0doeEhCYkJDgc3xAgY3j9fxT2amfUeF0KAMVGpVE03Gw98fsBoMlHZfHbus3/+85/9/f0pa+/H35s7d25HR8eqVav0ej2EMO9s3pikMbOfnu10OoazZUkvf2RAr7LnLmEQAyGsqqgyGo0Mw7z44osjR4503/oQQpvNtm/fvtzcXLVaLZFICCHXrl3T6/XJycnLly/XarW0G32pUql87bXXjh8/bjaba6qvcxzPsgzHccP254frM3fnetg+H2YYBkL03f8cq6+tp3Zl/Pjx69evDw4OHjZre2PUZMmSJXV1dZs2bRIE7LA7jn17LDUt1d/fz2w2I8QMy28kQ1LphABGxHR1dV2vuQEACAgImD59OpVjdwIbGhr+8pe/1NfXezx+6tSp9PT0qVOn9kKnIRwzZkxsbGxxcfH1qpq21lZdQADHcS7JGwxjHgTc0Z3xQt7jYozlcsWNmhv5ufn0ikqleuuttxITE90pJ16tz6l496FqSiQSvf7665MnT8ZYQAjdqLlxIe88y4oYhunZgg/dOLEsq+/obGpsAgAkJyeHhoZ6+2JWq9XhcDAMQ4EahBD9mxBisVi8Fb5Wq01NTQUA3L7TfvvWbZZl3d2cnxCi8eRuNz8YhgUA5J7Lu33rNt1qM2fOnDlzprsP6VJH7s2Dwf30ofogLCzs5UUvq1Qq6nOdz7+g13dS7dcDaw8nJBi83WUYxmw2W60WAEBoaKhcLvfuTDkqCAJ2a4Ig0Me9+8vl8sDAQAAA5gWrxUo3A/zJWUvlie2VMoUQY6xQyDs7OstKr1AUacSIEa+++qqvr6/7xoUQOp3OhoaGlpYWkUik0+nCwsIkEonHItpstvr6+lu3bkkkkoCAgLCwMJFI5K6in5/7/FcHvzp58iQA4Eb19eqqmgkZE2w228O3TAACiBBjsVgcdgfdcx7zH957GYZRq9UAAAELVqt1SL7ng8QhXTgzdNfpEIpEooa6+tbmFjrd9PT0tLQ0l8jTHXnx4sU9e/YUFBRQf0Qul6ekpCxYsODJJ59kWZYq4XPnzu3Zs6ekpMRsNrMsq1Ao0tPTFy5cOHXqVFew4e/vP23atDNnznAcZ7XaaqpqJmZM7B+3GpBzg+xA8540Xqda+l7+hCuo87jSj8KnugcLGLrqMcDPoJs9fWYGMRjj6urqrq5uIC01NTUgIKBHWxII4TfffPOnP/2poqLCfbCysrKcnJw1a9YsWbJEKpXu37///fffr62tde9TWlqak5Ozdu3aefPmicViOmZGRoZarW5vbwcA1NXWWsxmlmWdTuewsMmhAdGCgOVyuVgstlpter3e4XC4VIt7+sRqtXqA4YQQijl7WyJCiNFoBAAwDJLKZB5B/IBA4/071XedRg+fmRBCPfi2tlt0/wUGBo4fP97diJaUlLz77ruUtf7+/pmZmTqdrrS0tLi4uKGhYfPmzRkZGU6nc926dXV1dQCA4ODgzMxMlUpVWFhYVlZWU1Pz0UcfpaamxsXFCYLAMExsbGx0dDTlbktzq6GrS6fTOZ3OB+CJkAGAaAELCoVCKpcBQ9ft27ftdrtSqfToPGLEiBUrVuTn558/f57iAYSQtLS0KVOmREREeA9OMygAAASRXC7FmAzRJX5giS8P7hIAAESI5zmruTtrGxgQ6KKBErZv375r165BCGUy2erVq5ctW6ZWq2tqalavXt3V1fXrX/86ICCAshZC6Ofnl52dPW/ePJlMVlxc/M477yiVyqVLlwYFBblUvVwuj4yMvHDhAgDAarHa7Q6EEAAEAkTAcFJAgxd/gefVvpoR/iPaWtrKr5a3t7f7+/u7FCn9NyQkZOPGjZ999tmlS5dc3F20aNEbb7xB96WH1jUYDNeuXQMAKH2UGj8t9b/uPzUyJDJ7eVXuQo0gdAqCxWqlV6QyiUqlcnVobW0tLCykg6amps6fP9/Pz48i75988gkhZOTIkY2NjXl5eXS0zMzM559/3sfHBwAwceLEvXv3yuXy4OBgd99VJBJpNBp6hed4u82GEOovHUkeSEQIIAQ8z2u12ujYqPKy8ob6hqKiori4uJ5iq15gNTWlHnbXg6/0qYaGhtLSUgBAVNTokJAQjnM+SH07ODJdASXysLsQIbvdYbF0c1epVFHeuLir13dnLqOiotRqtSuQjYiIoEBPY2OjuWfrx8XFyWQyGvAQQqKioige4j4zlmW1Wm03dwXeYrEgBAEBD3w5vPmLMWYYJjo2RiwW2+32gwcPUqU6YON5vs/wj+f5Q4cOdXR0AACiY6OVSoXACz9jhYJnjggCIPC8wHXrE4lEIhaLXXedTqfLlRCJRAzDuAeylG3ulEskElcfF7jhkXJACLlCEYwxz3G0kO9BIen9i7/T6RyTNCY+MR4AkJOTc/To0cHsM++sCaWrsLDw4MGDGOPAoMDklLEczwtYcN9nD5DTAw1FvHNEkBAilUplMin9bTab3REZlUollXbfok4mje7p7GlA7OPj49Jj7e3tHMfRPu4BlYdTSp1MAADLMFKpFGNyjwrhITNvwBEcDntAgC5rZpZUJjMajVu3br18+TLFI/tUxX0mxCjhLS0tmzZtamxsBABkTp0SGx9vt9mHZzXuOxXYXWnjgUQSjDErEsmVchcOR4tmaAsLC6NADACguLi4qqqKInMQwoMHD7733ntXrlzR6XTBwcGU/vz8/Pr6etqH5/ldu3ZlZ2dXVla6A+scxxkMhm7wiGXlCkX3ykLykLZsr2XA2O6wZ0zOSEtPpUS99957N27coAx2raDT6bTZbLRejBDimj/VWAihzs7ODRs2fPvttxjj6JioJ2dmAUJ4nrsfTP7+9y7bJ9oil8noFYvF4jK0hBC1Wj1z5szTp08LglBfX5+dnf3666+HhISUlpZu3ry5pqbm6NGjO3fu/NWvfpWbmwshLCsrW7du3auvvurn53f+/PnNmze3tLR89913O3bseOyxx6jZ4ziOhkMAAJGIlUql3b4oGEA/P5B9ABGy2W1KhWrxq6/cudVeXVV97NgxkUi0fv36pKQkqloghAqFIjo6mu5ajuNoaojqIYRQQ0PDhg0b/vGPf/A87+enfXnJy+Ejw01G4zBC9sH7XwNmr/vIEQkCFkvEPmo1fVNjY2NFRUV6erqrw4IFC86ePXv48GEAwIkTJy5evKjRaG7dumWz2SCEsbGxISEhL7zwwuHDh0+fPs3z/JdffvnDDz+oVKqWlhan08kwzJgxY3Q6nUv62tvbXcCIxlctl8vo8Y2Ho7L6aAxirFbLqNGjlq9YunXLtqabTd98801HR8fKlStpxh4AkJmZuXfvXmpfMMZRUVEuTl8ouLD5PzcfOXKEEKJSKRe+snDS45MtFhMhBEE0VAfigVW8EgA8svf0hIxMLuu40365qIRg7HA4QkJCsrKyKGIOIVSpVGPHju3q6mpsbOQ4zmazGQwGjLGvr+/SpUuzs7NDQkJ8fHySk5Pb29ubm5s5jrNarVT3+vv7//73v1+7di0tSqILdObMmX379jmdTgBA2vi0qdOnUlP9QBTvYEJ+OqDD4QgNCwsND2mor9d36m/evJmTk1NbWyuRSNRqtUajiYiICA8PDw8Pj4iIUCgURqPx0qVL27Zt27RpEw3WdQEjXlm6ZOacWXa7jef5Ic2zj8qW+9DYEonEO3tP8/YYEBAdG+0/wq+luRUAUFh4qba2Ni4uDveUzMXFxX388ccLFy7Mzc1tbm6GEIaGhk6ZMmXy5Mk04QMhHDt27I4dO86dO5efn9/W1saybHh4eGZmZkZGhlwud88U5ebmWq1W6jxHRkWKJWKb3dbP0jxIx8Qt50oIsVgtaePHazS+u3fsKistb2tr27lz57fffhsbG5uSkhIREUHrPg2GrpaW5rKysqtXrzY3N9NliYoe/crSJRMyMiwWM89zEA6tWr2PqrT7qI0kPdUgfWTv7XZ7cEjIyNGjW5pbIYSlpVdOnjwZHR3dncyCkBCi0Whmz56dlZVFAySWZSlC63KJCSFarXbu3Llz5syhfUQiUQ+8fveIWFlZ2ffff48xBgD6+fvFJsTSgOqnjxEhhIAQo9E4avSot1a/nfNDzpnvz9T+WNvW1tbW1nbu3DmxWOwqgHXXLqFhIZOmTHpqxlOh4WFms5FWfPZzFujhx/HdsY9nFoEQmtpzaDS+kyZPLCm6TM917dy1a8aMGbGxsa5yKvqwSCRywe7umXl3Mvrs0wPiC/v27aOON8Y4OeWxiJEjHQ7n4PD2gR2TIS8lBIAQk9nko/b51Uvz0iakFeQXVFdW36xvuHOn3b0sl2XZETr/8IjwqJioCZMmRMfEAAJMJiMA5AEkP4aGSPb98D1wZgAJIHa7fXxGesyJU1dKyiCEV8vLd+/evX79eppad0cn+rMc9+5DiylzcnIOHTpENZtKpcyclimVSru6DN0w73ARjQFrIj2PjLp+EgAAQBDabTan3REWFhb+crjZbG6+2dTc1GwymaxWKyBEJpcrlMrg4KCwiHAfHx8IodVq6an3g/3v0WEzfmgn3noWj+0d/narbLvd5qvxnf30rOvV1202OyBg165dMTExS5cudYdhB6M/vftQBVBVVZWdnX3z5s3uctGJ6ckpY2lMCSEkdz8CAfuJ1of3mQVvENF7zphgs9mIGFYsEkXHxsQlxsNudUdolTLGAs/zVqtVEHiPQxheYw54Nnzg0+X0OLRXOZLng25H/sFd7kIIIESuTYkJsVjMGY9PLikuPf7dCYRQR0fHhg0bdDrdM88841HJPaRGWdvU1LR27dqcnBzK2qDgoOeef04ikRgMeoZl3WAq2E8w56G7B8NnL6G4p/aHEAKACABOp5MmmwGE9PsChBBACE3tQQg96m/6+lQA7H3Fe+FgvyRA1zBeHaA3he58ZGnAJ5FK6eF5iBCAAAuCzWZTKiULXlnY3NRcXnaVYZi6urrVq1cLgjB37lwXn4a6YxBCP/7447p16w4dOuQ6ZzbvpXnxiXEGg0EikYpEYkwwegTOBrovOAHE3RZCCH6eL8IMYpERQjKpjGVYAACLEKqrq9uxfQehOBsgAIBp/2dafEK82WwKCg76ze9+/dFf/rOxoZFhmKqqqrfeequjo2Px4sUU+qdWs/997O5wFRYWrl279tixYz2f0gBPP/f0zNkzLRaLVCbraO84fvSYyWgWiViX9ewtpz3fTSGw77t9/Ox1i7h9v2OgB0HvrU76ukt6Bc900rDHrSGkrzF7dwbeuBwkkEAyjPl0JzjEIvHlomKNr5aFEOo7DYcPfYPdPvhwq7Vt9f/9d7lCoe/sjE9MXL5i2fb/+u/bt28zDFNfX79mzZqamprFixePGTPGFST0w2B669atW0ePHt22bVtJSQlVyBChmXNmLlqyCGOB5wW5XPHd/xw99OXXWMDgl3bfLXWcL5OWllZcXAQh6hY7CCGErS1tKpVybGoKx3N2my0yKiooJPDHGz8aDF0IIYvFkp+fn5+fb7VafXx8NBoNy7Lw3q2pqen48eMbN278+OOPGxsbKWslUslz8557bdlrEqnYYrH4+fkVnC/Yv3e/3WaHCALibWIHieHAvsxznw/2Y9T7pAP1uJJuaaI+skZw0LOF/c9hEI97eMq9TscEBQZ1V+/R4MUFNWCMv/n6cMTIkRmPT+rsbDebTZOnPO6r9f307zuvXrlKny8rK/vjH//4xRdfpKamTpgwIS4uTqvVqtVqlUrlcDj0er3JZKqtrS0qKiouLi4uLqaHSujgfv5+CxYvmPP0bAELJpNJq9XerG/4bN9nXYYuCCHBxCvuI4MOA/t5dvARZd/hTM89jwiZDDSBYYS0gwl+SF/IWy8C2D4pgxB2tHfs/nS3Vusbnxjf3tGu13fGJyasXL3ywOcHcs90Y4cYY8q5AwcOBAYGymQyhUJBz94bjUaHw9He3n779m33iA1BmJCUuGDRSxMmTrDYrDar1ddX22U07t65p7qy+mFCOWRIPUeNGpWRkUErFGiZ45UrV27cuJGcnDxx4sQrV64UFRVRWG3s2LEpKSm1tbVnz5591JQzey/RhRDW19Vv3/bJG2+9GRkdqdfr9Z2dAYEBv/u3340dm3zi2Mnqqmqb1UbdYJPJ5J4Gdm+uTDiEIDwiPHPa1CdnPBkYFNhlMvGc01ertZgte3bszs89/2Ax5PuBJGkV95YtWwgher0eIaTRaOrr6998802pVLpmzRqDwbB06dKSkpLQ0NAPP/wwPT195cqVZ8+e/amAxkGnv9LS0oqKivqcFoTwzu32muqayKjI8JERvJOzWC0iERsbF5eSlhIUEgQA4DnearMS3F9xudZPGxk1OmtW1uJXF2dOnyqRSkwmIwFE6+en79B/+t+fnjp+6tFZFGpBk5KSlixZcvr06b/+9a+nTp0SiUSzZ882Go379+/38fGZP38+xvj48eOLFi168803jxw5smnTJqfTCR+NQI5OIygoiO0/koEQ1lRf37zpb68tfzU9Y4JYKrGYzQ6HQ6lUzpo9a8qUxxtvNlZX1dysbzAaTVarxWqx2Ww2CIFEIlaqVH5+fsGhITGx0REjR/pqfQEgRmOXIAhSmUwuk9dU1ezf88+LBZceKXl3oS6EkNraWlpuERISMnfu3JaWFovFsnv37lmzZs2fP7+qquqll15qaWnZsmWLyWR61DYuGPCLRpTBdbV1W/7jv2bNmfHs88/56fytVqvVZrFaLVKpNDYhLi4xnnNyHMcJAu90OC0WK4JQKpNKpFKJRCISiWiW22QyChhLxBIftdrpcH535LuDBw42NzffT8Lg4TWEEMdxL7/88rhx4wAAcXFxVVVVx44dAwDU1dVt375906ZNH3zwgUwm++CDD4qLiyF8FMGN/jSz+0632WzXrlZUV1ezDAoMDNJofFmWdTidVouFczppvY5IxEplMrXaR+mjkkiliEFYEOx2u9VqEQQslctVSiUkoOxK2ef7Pj/89eHOzs5HcFHolBITE+fNm9fa2lpWVkZNb1hYmNPpvHjxIs/z169fj4uLGz9+fF5e3vr16ykhj5pxGUAze+xgjHFZaXl1ZU1KWkrm9MykpDFaPz+xWiwIvN3uEASe4zDFYF1RIMOwcoVCLBLzPN9lNF4tLc87m3vhfIG+Uw9+umTnMCE9lmUPHz68evVqAEB0dPS//vWvFStW7N27t7a21mw25+XlLVy4sKCggJYF9lNM8uhqZm800eFwFOQXlF4uGTlqVMKY+KTkxwIDAjRajVyuoN+aYxiEMaEfmrPbbHfu3Om40155rbK8rLyutt6gN3TzFZBHlrUu8Q8LC0tNTeV5Pi0tTafT6fV6WiEEempgf5YDnA+eux48ttscVRVVVRVVp459r1Aq/Ef4BQcFK31UCqVCJpM5HE6LxWy1WG61tt26ddtsthgNRkzunrp5lPnabbEYxmKxzJgxIzk5mVaNEUK2bt3a2tpKO0gkEnrK7Wc6wPkQuOumqLuRMBrptrW2XS275hJn6nB6FXwj8GjvV3cJLisry87Olkql9ChGR0dHQUFBYWGh69RXfn7++++/T+vlHl2ifvvb3/Z/1rh/9dWNv6I+KvRdH6saMIn0S3sYZiU1NZX1PvA0VDG/VzDTV5XCL+2nUz8cx7GjRo1y/+ThL+3/GwbHx8f/P3JZDC4wR5sQAAAAAElFTkSuQmCC" alt="CC BY 저작자표시" title="저작자표시(CC BY) · 출처: 한국지능정보사회진흥원" style="height:18px;width:auto;display:block;flex-shrink:0;"></span>

    </div>

    <div class="mobile-result-list" id="mobileResultList"></div>

  </div>



  </main>



  <button id="locBtn"><svg xmlns="http://www.w3.org/2000/svg" width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#2563eb" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3"/><circle cx="12" cy="12" r="7" stroke-dasharray="2 2"/></svg></button>

  <div class="top-badge">모바일 / PC 지원</div>

  <div class="map-legend">

  

    <div class="map-legend-item">

      <span class="map-legend-dot" style="background:#06b6d4"></span>

      상습결빙지역

    </div>



    <div class="map-legend-item">

      <span class="map-legend-dot" style="background:#f59e0b"></span>

      공중화장실

    </div>



    <div class="map-legend-item">

      <span class="map-legend-dot" style="background:#ef4444"></span>

      교통사고위험지역

    </div>

    <div class="map-legend-item">

      <span class="map-legend-dot" style="background:#8b5cf6"></span>

      주차장

    </div>



    <div class="map-legend-item">

      <span class="map-legend-dot" style="background:#2563eb"></span>

      내 위치

    </div>

  </div>



  <div class="loading" id="loadingBox">데이터를 불러오는 중입니다...</div>

</div>

<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>

<script src="https://unpkg.com/leaflet.markercluster@1.5.3/dist/leaflet.markercluster.js"></script>



<script>window.FEATURE_DETAIL = {{ 'true' if detail_on else 'false' }};</script>

{% raw %}<script>

let ALL_DATA_CACHE = null;





const CATEGORY_COLORS = {

  "상습결빙지역": "#06b6d4",

  "공중화장실": "#f59e0b",

  "교통사고위험지역": "#ef4444",

  "주차장": "#8b5cf6",

  "자동심장충격기": "#16a34a"

};



const CATEGORY_LIST = [

  "상습결빙지역",

  "공중화장실",

  "교통사고위험지역",

  "주차장"

];



// "주차장" = 공영주차장 + 민영주차장 묶음 (화면엔 1개, 데이터/마커는 두 구분값)

const CATEGORY_GROUP = { "주차장": ["공영주차장", "민영주차장"], "위험지역": ["상습결빙지역", "교통사고위험지역"] };

function expandCats(cats){

  const out = [];

  cats.forEach(function(c){ var g = CATEGORY_GROUP[c]; if(g){ g.forEach(function(x){ out.push(x); }); } else { out.push(c); } });

  return out;

}

function catMatch(gubun, cat){

  var g = CATEGORY_GROUP[cat];

  return g ? (g.indexOf(gubun) >= 0) : (gubun === cat);

}



// 목록용: 주차장이면 "주차장 + 공영/민영 배지" 로, 그 외는 구분 그대로

function gubunLabel(g){

  if(g === "공영주차장" || g === "민영주차장"){

    var t = g.substring(0,2);

    var c = (t === "공영") ? "#2563eb" : "#db2777";

    return '주차장<sup style="background:' + c + ';color:#fff;font-size:9px;font-weight:700;padding:1px 5px;border-radius:8px;margin-left:4px;vertical-align:super;white-space:nowrap;'+'">' + t + '</sup>';

  }

  return g;

}





const map = L.map("map", { zoomControl:true }).setView([34.85, 126.90], 9);

/* 내 위치로 버튼: 누르면 지금 위치로 이동하고 초록 원·점으로 표시 (토글 ON일 때, 모든 안전로드 지도) */
function srAddLocateBtn(m){
  if(!window.FEATURE_DETAIL || !m || m._srLocate) return;
  const me = L.layerGroup().addTo(m);
  const Ctl = L.Control.extend({
    options: {position: "bottomright"},
    onAdd: function(){
      const wrap = L.DomUtil.create("div", "leaflet-control sr-locate-wrap");
      wrap.innerHTML = '<button type="button" class="sr-locate" title="내 위치로" aria-label="내 위치로">'
        + '<svg viewBox="0 0 24 24" fill="none" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="7"/><circle cx="12" cy="12" r="2.2" fill="currentColor"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3"/></svg></button>';
      L.DomEvent.disableClickPropagation(wrap);
      L.DomEvent.disableScrollPropagation(wrap);
      const btn = wrap.querySelector("button");
      function toast(msg){
        let t = wrap.querySelector(".sr-locate-toast");
        if(!t){ t = document.createElement("div"); t.className = "sr-locate-toast"; wrap.appendChild(t); }
        t.textContent = msg;
        clearTimeout(t._h); t._h = setTimeout(function(){ t.remove(); }, 2600);
      }
      btn.addEventListener("click", function(){
        if(!navigator.geolocation){ toast("이 기기에서는 위치를 쓸 수 없어요"); return; }
        if(btn.classList.contains("busy")) return;
        btn.classList.add("busy");
        navigator.geolocation.getCurrentPosition(function(pos){
          btn.classList.remove("busy"); btn.classList.add("on");
          const lat = pos.coords.latitude, lng = pos.coords.longitude;
          const acc = Math.max(30, Math.min(pos.coords.accuracy || 80, 300));
          me.clearLayers();
          L.circle([lat, lng], {radius: acc, color: "#22c55e", fillColor: "#22c55e", fillOpacity: .18, weight: 1.5}).addTo(me);
          L.marker([lat, lng], {icon: buildUserIcon(), zIndexOffset: 1000, interactive: false}).addTo(me);
          m.setView([lat, lng], Math.max(m.getZoom(), 16), {animate: false});
          if(m._srLift) m.panBy([0, m._srLift / 2], {animate: false});   // 결과 창에 가리지 않게 보이는 부분 가운데로
        }, function(err){
          btn.classList.remove("busy");
          toast(err && err.code === 1 ? "위치 권한을 허용해 주세요" : "위치를 찾지 못했어요. 다시 눌러 주세요");
        }, {enableHighAccuracy: true, timeout: 10000, maximumAge: 15000});
      });
      return wrap;
    }
  });
  const ctl = new Ctl().addTo(m);
  m._srLocate = ctl;
  // 아래 결과 창이 지도를 덮으면 버튼을 그 위로 올림
  const el = ctl.getContainer();
  setInterval(function(){
    try{
      const panel = document.getElementById("mobileResultPanel");
      let lift = 0;
      if(panel && getComputedStyle(panel).display !== "none" && el.offsetParent){
        const pr = panel.getBoundingClientRect(), br = el.getBoundingClientRect(), mr = m.getContainer().getBoundingClientRect();
        const horiz = pr.left < br.right && pr.right > br.left;
        if(horiz && pr.top < mr.bottom && pr.bottom > pr.top) lift = Math.max(0, mr.bottom - pr.top);
      }
      m._srLift = lift;
      const want = (lift ? lift + 12 : 18) + "px";
      if(el.style.marginBottom !== want) el.style.marginBottom = want;
    }catch(e){}
  }, 300);
}
srAddLocateBtn(map);



setTimeout(()=>{

  map.invalidateSize();

},500);



let userLat = null;

let userLng = null;

function showMsg(text){
  const _lx = document.getElementById("msgBox"); if(_lx) _lx.classList.remove("sr-loading");



  const modal = document.getElementById("msgModal");

  const txt = document.getElementById("msgText");

  const btn = document.getElementById("msgBtn");



  if(!modal || !txt) return;



  txt.innerText = text;



  if(btn){

    btn.style.display = "inline-block";

  }



  modal.style.display = "flex";



}



function showLoadingLocation(){
  if(window.FEATURE_DETAIL){
    loadingStartTime = Date.now();
    const _m = document.getElementById("msgModal"), _t = document.getElementById("msgText"), _b = document.getElementById("msgBtn"), _x = document.getElementById("msgBox");
    if(!_m || !_t) return;
    _t.innerHTML = '<div class="sr-ld"><div class="sr-radar"><i></i><i></i><i></i><b><svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 21s-7-6.2-7-11.5a7 7 0 0 1 14 0C19 14.8 12 21 12 21z"/><circle cx="12" cy="9.5" r="2.5"/></svg></b></div><div class="sr-ld-t">' + (window.srLoadMode === "search" ? "위치를 찾고 있어요" : "내 위치를 찾고 있어요") + '</div><div class="sr-ld-s">' + (window.srLoadMode === "search" ? "입력한 곳을 지도에서 찾는 중이에요" : "처음에는 몇 초 걸릴 수 있어요") + '</div></div>';
    if(_b) _b.style.display = "none";
    if(_x) _x.classList.add("sr-loading");
    _m.style.display = "flex";
    return;
  }



  loadingStartTime = Date.now();



  const modal = document.getElementById("msgModal");

  const txt = document.getElementById("msgText");

  const btn = document.getElementById("msgBtn");



  if(!modal || !txt) return;



  txt.innerHTML = `

  <div style="

  display:flex;

  align-items:center;

  justify-content:center;

  gap:18px;

  ">



  <img src="/char_left" class="char">



  <div style="

  font-size:16px;

  font-weight:700;

  padding:10px 14px;

  white-space:nowrap;

  ">

  📍 위치 확인 중<span class="loading-dots"></span>

  </div>



  <img src="/char_right" class="char">



  </div>

<div style="

margin-top:10px;

font-size:13px;

color:#64748b;

">

※ 최초 검색 시 위치 정보를 찾는데 시간이 조금 걸릴 수 있습니다.

</div>

  `;



  if(btn){

    btn.style.display = "none";

  }



  modal.style.display = "flex";

}



function preloadLocation(){

  if(!navigator.geolocation){

    return;

  }



navigator.geolocation.getCurrentPosition(



  function(pos){



    userLat = pos.coords.latitude;

    userLng = pos.coords.longitude;

    console.log("사전 위치:", userLat, userLng, "정확도:", pos.coords.accuracy);

    drawUserLocation(userLat, userLng);



  },



  function(err){

    console.log("위치 사전 요청 실패", err);

  },



  {

    enableHighAccuracy:true,

    timeout:10000,

    maximumAge:0

  }



);}





L.tileLayer(

  "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",

  {

    maxZoom: 19,

    attribution: "&copy; OpenStreetMap"

  }

).addTo(map);



let markerGroup = L.markerClusterGroup({

  showCoverageOnHover:false,

  spiderfyOnMaxZoom:true,

  disableClusteringAtZoom:15,

  chunkedLoading:true

});



let routeLine = null;

map.addLayer(markerGroup);



function clearRoute(){



  if(routeLine){

    map.removeLayer(routeLine);

    routeLine = null;

  }



  if(window.mobileRouteLine && window.mobileLeafletMap){

    window.mobileLeafletMap.removeLayer(window.mobileRouteLine);

    window.mobileRouteLine = null;

  }



}



function setLoading(show){

  document.getElementById("loadingBox").style.display = show ? "block" : "none";

}



function calcDistance(lat1, lng1, lat2, lng2){



  const R = 6371000;



  const dLat = (lat2-lat1) * Math.PI/180;

  const dLng = (lng2-lng1) * Math.PI/180;



  const a =

    Math.sin(dLat/2)*Math.sin(dLat/2) +

    Math.cos(lat1*Math.PI/180) *

    Math.cos(lat2*Math.PI/180) *

    Math.sin(dLng/2)*Math.sin(dLng/2);



  const c = 2*Math.atan2(Math.sqrt(a),Math.sqrt(1-a));



  return R*c;



}





function srNotice(title, sub, body){
  const h = document.getElementById("srMsgHead");
  showMsg(body);
  if(h){
    document.getElementById("srMsgTitle").textContent = title;
    document.getElementById("srMsgSub").textContent = sub || "";
    h.classList.add("on");
  }
}
function fmtDist(d){
  if(!window.FEATURE_DETAIL) return d + " m";
  if(d >= 1000) return (d / 1000).toFixed(d >= 10000 ? 0 : 1) + " km";
  return d + " m";
}
/* 결과 카드: 작은 로드뷰 + 주소 + 거리 (토글 ON) */
const SR_TYPE_COLOR = {"공중화장실":"#f59e0b","공영주차장":"#8b5cf6","민영주차장":"#8b5cf6","자동심장충격기":"#16a34a","상습결빙지역":"#06b6d4","교통사고위험지역":"#ef4444"};
let srRvSeq = 0, srRvObserver = null, srLocAsked = false;
function srEnhanceList(){
  if(!window.FEATURE_DETAIL) return;
  const list = document.getElementById("mobileResultList");
  if(!list) return;
  const items = list.querySelectorAll(".mobile-result-item:not(.sr-rich)");
  if(!items.length) return;
  window.srHasDist = false;
  if(srRvObserver) srRvObserver.disconnect();
  srRvObserver = ("IntersectionObserver" in window) ? new IntersectionObserver(function(ents){
    ents.forEach(function(en){
      const box = en.target;
      if(en.isIntersecting && box.dataset.loaded !== "1"){
        box.dataset.loaded = "1";
        initRoadview(box.dataset.pano, +box.dataset.lat, +box.dataset.lng, box.dataset.gubun);
      } else if(!en.isIntersecting && box.dataset.loaded === "1"){
        // 화면 밖 로드뷰는 내려서 폰 메모리·그래픽 부담 줄이기
        box.dataset.loaded = "0";
        const pano = document.getElementById(box.dataset.pano);
        if(pano) pano.innerHTML = "";
        const msg = document.getElementById(box.dataset.pano + "_msg");
        if(msg){ msg.style.display = ""; msg.textContent = "로드뷰"; }
      }
    });
  }, {root: list, rootMargin: "160px 0px"}) : null;
  items.forEach(function(el){
    if(!el.dataset.lat) return;
    const b = el.querySelector("b");
    const label = b ? b.innerHTML : "";
    const old = el.querySelector(".mobile-result-distance");
    const dist = old ? old.textContent.trim() : "";
    const addr = el.dataset.addr || "";
    const id = "srrv_" + (++srRvSeq);
    const area = el.innerHTML.split("<br>")[1] || "";
    const nm = el.dataset.name || "";
    el.classList.add("sr-rich");
    el.innerHTML =
      `<div class="sr-rv" id="${id}_box" data-pano="${id}" data-lat="${el.dataset.lat}" data-lng="${el.dataset.lng}" data-gubun="${escapeHtml(el.dataset.gubun || "")}">` +
        `<div class="sr-rv-pano" id="${id}"></div><div class="sr-rv-msg" id="${id}_msg">로드뷰</div><span class="sr-rv-tag" style="background:${SR_TYPE_COLOR[el.dataset.gubun] || "#2563eb"};"></span><div class="sr-rv-cover"></div>` +
      `</div>` +
      `<div class="sr-txt"><b>${nm ? escapeHtml(nm) : label}</b><div class="sr-addr">${addr ? escapeHtml(addr) : area}</div></div>` +
      `<span class="mobile-result-distance">${dist}</span>`;
    const box = document.getElementById(id + "_box");
    if(srRvObserver) srRvObserver.observe(box);
  });
  srFillDistances();
}
const SR_LIST_MAX = 30;
function srTrimList(){
  const list = document.getElementById("mobileResultList");
  if(!list) return;
  const els = list.querySelectorAll(".mobile-result-item.sr-rich");
  const total = Math.max(els.length, window.srCutFrom || 0);
  if(total > SR_LIST_MAX){
    for(let i = SR_LIST_MAX; i < els.length; i++) els[i].remove();
  }
  const cnt = document.getElementById("mobileResultCount");
  const host = cnt && cnt.parentNode;
  if(!host) return;
  if(window.srCutFrom && total > SR_LIST_MAX) cnt.textContent = total;
  let note = host.querySelector(".sr-trim");
  if(total > SR_LIST_MAX){
    if(!note){ note = document.createElement("small"); note.className = "sr-trim"; host.appendChild(note); }
    const r = window.srRef;
    const base = r ? (r.kind === "route" ? "출발지 기준 " : "주소 기준 ") : (window.srHasDist ? "내 위치 기준 " : "");
    note.textContent = " · 목록은 " + base + SR_LIST_MAX + "곳";
  } else if(note && total) { note.remove(); }
}
function srApplyDistances(lat, lng){
  window.srHasDist = true;
  const list = document.getElementById("mobileResultList");
  if(!list) return;
  const els = Array.prototype.slice.call(list.querySelectorAll(".mobile-result-item.sr-rich"));
  els.forEach(function(el){
    const d = Math.round(calcDistance(lat, lng, +el.dataset.lat, +el.dataset.lng));
    el.dataset.dm = d;
    const sp = el.querySelector(".mobile-result-distance");
    if(sp) sp.textContent = fmtDist(d);
  });
  // 가까운 순으로 다시 정렬
  els.sort(function(x, y){ return (+x.dataset.dm) - (+y.dataset.dm); });
  let sorted = true;
  for(let i = 0; i < els.length; i++){ if(list.children[i] !== els[i]){ sorted = false; break; } }
  if(sorted){ srTrimList(); return; }
  const frag = document.createDocumentFragment();
  els.forEach(function(el){ frag.appendChild(el); });
  list.appendChild(frag);
  list.scrollTop = 0;
  srTrimList();
}
function srFillDistances(){
  if(window.srRef){ srApplyDistances(window.srRef.lat, window.srRef.lng); return; }
  if(typeof userLat !== "undefined" && userLat && userLng){ srApplyDistances(userLat, userLng); return; }
  if(window.srMyLat){ srApplyDistances(window.srMyLat, window.srMyLng); return; }
  if(srLocAsked) return;
  if(!navigator.geolocation){ srTrimList(); return; }
  srLocAsked = true;
  navigator.geolocation.getCurrentPosition(function(pos){
    srLocAsked = false;
    window.srMyLat = pos.coords.latitude; window.srMyLng = pos.coords.longitude;
    srApplyDistances(window.srMyLat, window.srMyLng);
  }, function(){ srLocAsked = false; srTrimList(); }, {enableHighAccuracy:false, timeout:8000, maximumAge:300000});
}
document.addEventListener("DOMContentLoaded", function(){
  if(!window.FEATURE_DETAIL) return;
  const list = document.getElementById("mobileResultList");
  if(!list) return;
  let t = null;
  new MutationObserver(function(){ clearTimeout(t); t = setTimeout(srEnhanceList, 30); }).observe(list, {childList:true});
});
function srCatOk(item, which){
  if(!window.FEATURE_DETAIL) return true;
  const box = document.getElementById("srPcat_" + which);
  if(!box) return true;
  const on = Array.from(box.querySelectorAll("input:checked")).map(i => i.value);
  if(!on.length) return true;
  const g = item.구분;
  return on.some(v => v === g || (v === "주차장" && (g === "공영주차장" || g === "민영주차장")));
}
function closeMsg(){
  const _lx2 = document.getElementById("msgBox"); if(_lx2) _lx2.classList.remove("sr-loading");
  const _h = document.getElementById("srMsgHead");
  if(_h) _h.classList.remove("on");

  const modal = document.getElementById("msgModal");

  if(modal){

    modal.style.display = "none";

  }

}



function showMobileResults(items, userLat, userLng){

  


  const panel = document.getElementById("mobileResultPanel");

  const list = document.getElementById("mobileResultList");



  if(!panel || !list) return;



  panel.style.display = "flex";

  list.innerHTML = "";



  items.forEach(item => {

    let distText = "";



    if(userLat !== null && userLng !== null){

      const dist = Math.round(

        calcDistance(userLat, userLng, item.위도, item.경도)

      );

      distText = `<span class="mobile-result-distance">${fmtDist(dist)}</span>`;

    }



    const el = document.createElement("div");

    el.className = "mobile-result-item";

    el.dataset.gubun = item.구분; el.dataset.lat = item.위도; el.dataset.lng = item.경도; el.dataset.addr = item.주소 || ""; el.dataset.name = item.시설명 || item.화장실명 || "";

    el.innerHTML = `

      <b>${gubunLabel(item.구분)}</b><br>

      ${item.시군구} ${item.읍면동}<br>

      ${distText}

    `;



    el.onclick = function(){



  if(isMobile() && window.mobileLeafletMap){



    window.mobileLeafletMap.flyTo(

      [item.위도,item.경도],

      16,

      {

        duration:1.2,

        easeLinearity:0.25

      }

    );



    window.mobileLeafletMap.once("moveend", function(){

      // 팝업이 화면 중앙에 오도록 지도 오른쪽으로 이동
      if(window.mobileMarkerGroup){
        var __found = false;
        window.mobileMarkerGroup.eachLayer(function(layer){
          if(layer.itemData && layer.itemData.순번 === item.순번){
            __found = true;
            window._skipPopupAutoPan = true;
            layer.openPopup();
          }
        });
        if(!__found){
          // 위치찾기 등으로 결과 마커가 지워진 경우 다시 만들어 팝업 표시
          var __mk = L.marker([item.위도,item.경도],{icon: buildMarkerIcon(item.마커색상)});
          __mk.itemData = item;
          __mk.bindPopup(buildPopupHtml(item),{maxWidth: isMobile() ? 310 : 650, autoPan: false});
          window.mobileMarkerGroup.addLayer(__mk);
          window._skipPopupAutoPan = true;
          setTimeout(function(){ __mk.openPopup(); }, 0);
        }
      }



    });



  }



};



    list.appendChild(el);

  });



  document.getElementById("mobileResultCount").textContent = items.length;

}



function createCategoryChecks(){

  const box = document.getElementById("categoryBox");

  box.innerHTML = "";

  CATEGORY_LIST.forEach(cat => {

    const color = CATEGORY_COLORS[cat] || "#334155";

    const item = document.createElement("label");

    item.className = "check-item";

    item.innerHTML = `

      <input type="checkbox" class="category-check" value="${cat}">

      <span class="dot" style="background:${color}"></span>

      <span>${cat === "주차장" ? '주차장<span style="font-size:11px;color:#9ca3af;">(공영/민영)</span>' : cat}</span>

    `;

    box.appendChild(item);

  });

}



function fillProvinces(provinces){



  const select = document.getElementById("province");



  select.innerHTML = '<option value="">전체</option>';



  provinces.forEach(p=>{



    const op = document.createElement("option");



    op.value = p;



    op.textContent = p;



    select.appendChild(op);



  });



}



function fillCities(cities){

  const select = document.getElementById("city");

  const current = select.value;

  select.innerHTML = '<option value="">전체</option>';

  cities.forEach(city => {

    const op = document.createElement("option");

    op.value = city;

    op.textContent = city;

    select.appendChild(op);

  });

  if(cities.includes(current)) select.value = current;

}



function fillTowns(towns){

  const wrap = document.getElementById("townMultiWrap");

  if(!wrap) return;

  wrap.innerHTML = "";

  if(!towns || towns.length === 0){

    wrap.innerHTML = '<div class="town-check-item" style="color:#94a3b8;font-size:12px;">읍면동 없음</div>';

    return;

  }

  towns.forEach(town => {

    const lbl = document.createElement("label");

    lbl.className = "town-check-item";

    lbl.innerHTML = `<input type="checkbox" class="town-check" value="${escapeHtml(town)}"><span>${escapeHtml(town)}</span>`;

    wrap.appendChild(lbl);

  });

}



function getSelectedTowns(){

  return Array.from(document.querySelectorAll(".town-check:checked")).map(el => el.value);

}



function getCheckedCategories(){

  return Array.from(document.querySelectorAll(".category-check:checked")).map(el => el.value);

}



function buildMarkerIcon(color){

  return L.divIcon({

    className: "",

    html: `<div class="custom-marker" style="background:${color};"></div>`,

    iconSize: [18, 18],

    iconAnchor: [9, 9],

    popupAnchor: [0, -8]

  });

}



// 7번: 팝업 HTML 빌더 (모바일은 티맵 포함, PC는 카카오+네이버만)

function buildPopupHtml(item){

  if(!window._popupItems) window._popupItems = {};

  window._popupItems[item.순번] = item;

  const addr = encodeURIComponent(item.주소);

  const tmapBtn = isMobile() ? `

  <a href="tmap://search?name=${addr}" target="_blank"

  style="display:flex;align-items:center;justify-content:center;height:36px;background:#4b8fe2;color:#fff;font-weight:700;border-radius:8px;text-decoration:none;font-size:13px;">

  티맵

  </a>` : "";

  const gridCols = isMobile() ? "1fr 1fr 1fr" : "1fr 1fr";

  const sid = escapeHtml(item.순번);

  const rvId = "rv_" + sid;

  // PC는 더 넓은 팝업, 모바일은 기본

  const rvHeight = isMobile() ? "220px" : "340px";

  const popupWidth = isMobile() ? 290 : 600;

  return `

  <div class="popup-wrap" style="width:${popupWidth}px;">



  <!-- 로드뷰 컨테이너 -->

  <div id="${rvId}" style="width:100%;height:${rvHeight};border-radius:10px;border:1px solid #e5e7eb;margin-bottom:8px;background:#f1f5f9;overflow:hidden;position:relative;">

    <div style="position:absolute;inset:0;display:flex;align-items:center;justify-content:center;font-size:12px;color:#94a3b8;" id="${rvId}_msg">로드뷰 불러오는 중...</div>

  </div>



  <div class="popup-title">${(window.FEATURE_DETAIL && (item.시설명 || item.화장실명)) ? escapeHtml(item.시설명 || item.화장실명) + srUpdChip(item.자료수정일) : gubunLabel(item.구분)}</div>

  <div class="popup-meta">

  주소: ${escapeHtml(item.주소)}

  </div>

  ${facilityInfoHtml(item)}



  <!-- 별점 UI: 평가하기 버튼 -->

  <div id="rating_wrap_${sid}" style="margin-top:8px;display:flex;align-items:center;gap:8px;flex-wrap:wrap;">

    <button onclick="openRatingModal('${sid}')" style="

      height:30px;padding:0 12px;border:1px solid #f59e0b;border-radius:8px;

      background:#fffbeb;font-size:12px;cursor:pointer;font-weight:700;color:#b45309;">

      ★ 평가하기

    </button>

    <span id="avg_${sid}" style="font-size:12px;color:#f59e0b;font-weight:700;"></span>

  </div>



  <!-- 코멘트 + 공유 (한 줄) -->

  <div style="margin-top:6px;display:grid;grid-template-columns:1fr 1fr;gap:6px;">

    <button onclick="openComments('${sid}')" style="height:34px;border:1px solid #e2e8f0;border-radius:8px;background:#f8fafc;font-size:13px;cursor:pointer;font-weight:600;color:#374151;">💬 코멘트</button>

    <button onclick="shareSpot('${sid}')" style="height:34px;border:1px solid #e2e8f0;border-radius:8px;background:#f8fafc;font-size:13px;cursor:pointer;font-weight:600;color:#374151;">🔗 공유</button>

  </div>



  <div style="margin-top:8px;display:grid;grid-template-columns:${gridCols};gap:6px;">

  <a href="https://map.naver.com/v5/search/${addr}" target="_blank"

  style="display:flex;align-items:center;justify-content:center;height:36px;background:#03C75A;color:#fff;font-weight:700;border-radius:8px;text-decoration:none;font-size:13px;">

  네이버

  </a>

  <a href="https://map.kakao.com/link/search/${addr}" target="_blank"

  style="display:flex;align-items:center;justify-content:center;height:36px;background:#FEE500;color:#191919;font-weight:700;border-radius:8px;text-decoration:none;font-size:13px;">

  카카오

  </a>

  ${tmapBtn}

  </div>

  </div>`;

}



async function shareSpot(sid){
  const item = (window._popupItems || {})[sid];
  if(!item) return;
  const name = (window.FEATURE_DETAIL && (item.시설명 || item.화장실명)) || item.구분 || "위치";
  const addr = item.주소 || ((item.시군구||"") + " " + (item.읍면동||""));
  const mapUrl = "https://map.kakao.com/link/map/" + encodeURIComponent(name) + "," + item.위도 + "," + item.경도;
  const shareText = name + "\n" + addr + "\n" + mapUrl;
  const canNativeShare = navigator.share && navigator.maxTouchPoints > 0;
  if(canNativeShare){
    try {
      await navigator.share({ title: "안전로드 - " + name, text: name + "\n" + addr, url: mapUrl });
      return;
    } catch(e){
      if(e && e.name === "AbortError") return;
    }
  }
  copyShareText(shareText);
}

function copyShareText(text){
  if(navigator.clipboard && navigator.clipboard.writeText){
    navigator.clipboard.writeText(text).then(function(){ showMsg("공유 링크가 복사되었습니다."); }).catch(function(){ legacyCopyText(text); });
  } else {
    legacyCopyText(text);
  }
}

function legacyCopyText(text){
  try {
    var ta = document.createElement("textarea");
    ta.value = text;
    ta.style.position = "fixed";
    ta.style.top = "-9999px";
    document.body.appendChild(ta);
    ta.select();
    document.execCommand("copy");
    document.body.removeChild(ta);
    showMsg("공유 링크가 복사되었습니다.");
  } catch(e){ showMsg(text); }
}



/* 로드뷰 속 시설 핀 (출장 도구함 화장실과 같은 방식). 건물에 붙어 같이 움직이고, 카메라는 핀 쪽으로.
   작은 로드뷰(목록)는 화살표만, 팝업은 이름표 + 사진 찍힌 곳에서 거리 */
const SR_PIN_LABEL = {"공중화장실":"화장실","공영주차장":"주차장","민영주차장":"주차장","자동심장충격기":"AED","상습결빙지역":"결빙 구간","교통사고위험지역":"사고 위험"};
function srRvPin(rv, lat, lng, gubun, small){
  const pos = new kakao.maps.LatLng(lat, lng);
  const pin = document.createElement("div");
  pin.className = small ? "rvpin sm" : "rvpin";
  pin.innerHTML = "<i></i>";
  const ov = new kakao.maps.CustomOverlay({position:pos, content:pin, xAnchor:.5, yAnchor:1});
  // 카메라를 핀 쪽으로: 방향(pan)은 사진 찍은 곳 → 시설 방위각으로 직접 계산 (가장 확실),
  // 위아래(tilt)만 카카오 계산값을 조금 씀. 카카오가 사진을 띄운 직후 시야를 덮어쓰는 경우가 있어 몇 번 더 맞춤
  function aim(){
    try{
      const p = rv.getPosition();
      if(!p) return;
      const R = Math.PI / 180, f1 = p.getLat() * R, f2 = lat * R, dl = (lng - p.getLng()) * R;
      const y = Math.sin(dl) * Math.cos(f2), x = Math.cos(f1) * Math.sin(f2) - Math.sin(f1) * Math.cos(f2) * Math.cos(dl);
      const pan = ((Math.atan2(y, x) * 180 / Math.PI) + 360) % 360;
      let tilt = 0;
      try{
        const vp = rv.getProjection().viewpointFromCoords(ov.getPosition(), ov.getAltitude());
        if(vp && isFinite(vp.tilt)) tilt = Math.max(-25, Math.min(10, vp.tilt));
      }catch(e){}
      rv.setViewpoint({pan: pan, tilt: tilt, zoom: 0});
    }catch(e){}
  }
  let done = false;
  kakao.maps.event.addListener(rv, "init", function(){
    try{
      const p = rv.getPosition();
      if(p && !small){
        const d = Math.round(calcDistance(p.getLat(), p.getLng(), lat, lng));
        pin.innerHTML = `<b>${SR_PIN_LABEL[gubun] || "여기"}${d >= 10 ? " · " + (d < 1000 ? d + "m" : (d / 1000).toFixed(1) + "km") : ""}</b><i></i>`;
      }
      ov.setMap(rv);
    }catch(e){}
    if(done) return;
    done = true;
    aim();
    setTimeout(aim, 250);
    setTimeout(aim, 800);
  });
}

// 로드뷰 초기화 함수 (팝업 열릴 때 호출)

function initRoadview(containerId, lat, lng, category){

  const msg = document.getElementById(containerId + "_msg");



  function doInit(){

    const container = document.getElementById(containerId);

    if(!container) return;

    try{

      const rvClient = new kakao.maps.RoadviewClient();

      const roadview = new kakao.maps.Roadview(container);

      const position = new kakao.maps.LatLng(lat, lng);

      const small = containerId.indexOf("srrv_") === 0;

      const radii = (window.FEATURE_DETAIL && !small) ? [100, 200] : [100];

      (function tryR(rs){ rvClient.getNearestPanoId(position, rs[0], function(panoId){

        if(panoId === null && rs.length > 1) return tryR(rs.slice(1));

        if(panoId === null){

          if(msg) msg.textContent = (containerId.indexOf("srrv_") === 0) ? "로드뷰 없음" : "📷 이 위치는 로드뷰가 없습니다.";

        } else {

          if(msg) msg.style.display = "none";

          if(window.FEATURE_DETAIL){ srRvPin(roadview, lat, lng, category, small); roadview.setPanoId(panoId, position); return; }

          roadview.setPanoId(panoId, position);

          // 공중화장실/주차장: 로드뷰 위치 → 시설 좌표 방향으로 카메라 회전

          if(true){   // 모든 시설: 로드뷰 카메라가 해당 시설 방향을 바라보도록 회전

            kakao.maps.event.addListener(roadview, 'init', function(){

              try{

                const rvPos = roadview.getPosition();

                if(!rvPos) return;

                const rvLat = rvPos.getLat();

                const rvLng = rvPos.getLng();

                // 방위각(bearing) 계산: 북=0, 시계방향 (카카오 pan 규격과 동일)

                const toRad = Math.PI / 180;

                const phi1 = rvLat * toRad;

                const phi2 = lat * toRad;

                const dLng = (lng - rvLng) * toRad;

                const y = Math.sin(dLng) * Math.cos(phi2);

                const x = Math.cos(phi1) * Math.sin(phi2) - Math.sin(phi1) * Math.cos(phi2) * Math.cos(dLng);

                const pan = ((Math.atan2(y, x) * 180 / Math.PI) + 360) % 360;

                roadview.setViewpoint({ pan: pan, tilt: 0, zoom: 0 });

              }catch(err){

                // 실패 시 기본 시야각 유지

              }

            });

          } else {

            // 그 외 카테고리: 초기 시야각 정북

            roadview.setViewpoint({

              pan: 0,

              tilt: 0,

              zoom: 0

            });

          }

        }

      }); })(radii);

    }catch(e){

      if(msg) msg.textContent = "📷 로드뷰를 불러올 수 없습니다.";

    }

  }



  // kakao SDK 로드 대기

  if(window.kakao && window.kakao.maps && window.kakao.maps.RoadviewClient){

    doInit();

  } else {

    let tries = 0;

    const timer = setInterval(function(){

      tries++;

      if(window.kakao && window.kakao.maps && window.kakao.maps.RoadviewClient){

        clearInterval(timer);

        doInit();

      } else if(tries > 20){

        clearInterval(timer);

        if(msg) msg.textContent = "📷 카카오 SDK 로드 실패";

      }

    }, 300);

  }

}



function buildUserIcon(){

  return L.divIcon({

    className:"",

    html:`

      <div class="user-marker-wrap">

        <div class="user-marker-pulse"></div>

        <div class="user-marker-dot"></div>

      </div>

    `,

    iconSize:[28,28],

    iconAnchor:[14,14]

  });

}



function drawUserLocation(lat,lng){



  // 기존 위치 마커 제거

  if(window.userCircle){

    map.removeLayer(window.userCircle);

  }



  if(window.userMarker){

    map.removeLayer(window.userMarker);

  }



  // 내 위치 원 (크게)

  window.userCircle = L.circle(

    [lat,lng],

    {

      radius:180,        // ⭐ 크기 (미터)

      color:"#22c55e",

      fillColor:"#22c55e",

      fillOpacity:0.25,

      weight:2

    }

  ).addTo(map);



  // 내 위치 점

  window.userMarker = L.marker(

    [lat,lng],

    { icon: buildUserIcon(), zIndexOffset: 1000 }

  ).addTo(map);



}









function escapeHtml(text){

  if(text === null || text === undefined) return "";

  return String(text)

    .replaceAll("&", "&amp;")

    .replaceAll("<", "&lt;")

    .replaceAll(">", "&gt;")

    .replaceAll('"', "&quot;")

    .replaceAll("'", "&#039;");

}



async function loadMeta(){

  const res = await fetch("/meta");

  const data = await res.json();

  fillProvinces(data.provinces || []);

  fillCities([]);   // 초기엔 비움

  fillTowns([]);    // 초기엔 비움



  // 10번: 저장된 값 복원

  const savedProvince = sessionStorage.getItem("sel_province") || "";

  const savedCity = sessionStorage.getItem("sel_city") || "";



  if(savedProvince){

    document.getElementById("province").value = savedProvince;

    const r2 = await fetch("/cities?province=" + encodeURIComponent(savedProvince));

    const d2 = await r2.json();

    fillCities(d2.cities || []);

    if(savedCity){

      document.getElementById("city").value = savedCity;

      const r3 = await fetch(`/towns?province=${encodeURIComponent(savedProvince)}&city=${encodeURIComponent(savedCity)}`);

      const d3 = await r3.json();

      fillTowns(d3.towns || []);

    }

  }

}



async function updateCities(){

  const province = document.getElementById("province").value;

  if(!province){

    fillCities([]);

    fillTowns([]);

    return;

  }

  const res = await fetch("/cities?province=" + encodeURIComponent(province));

  const data = await res.json();

  fillCities(data.cities || []);

  fillTowns([]);  // 시도 바뀌면 읍면동 초기화

}



async function updateTowns(){

  const province = document.getElementById("province").value;

  const city = document.getElementById("city").value;

  if(!city){

    fillTowns([]);

    return;

  }

  const res = await fetch(`/towns?province=${encodeURIComponent(province)}&city=${encodeURIComponent(city)}`);

  const data = await res.json();

  fillTowns(data.towns || []);

}



async function loadAllMarkers(){



  if(!ALL_DATA_CACHE){

  const res = await fetch("/data/all");

  const result = await res.json();

  ALL_DATA_CACHE = result.data || [];

}



const data = ALL_DATA_CACHE;



  markerGroup.clearLayers();



  const bounds = [];



  // 내 위치가 있으면 먼저 표시

  if(userLat !== null && userLng !== null){

    drawUserLocation(userLat, userLng);

  }



  data.forEach(item=>{



    const icon = buildMarkerIcon(item.마커색상);



    const marker = L.marker([item.위도,item.경도],{icon});

    marker.itemData = item;

    const popupHtml = buildPopupHtml(item);



    marker.bindPopup(popupHtml,{maxWidth: isMobile() ? 310 : 650});



    markerGroup.addLayer(marker);



    bounds.push([item.위도,item.경도]);



  });



  if(bounds.length>0){

    map.setView([34.85,126.90],9);

}



}



async function loadData(){



  clearRoute();



  if(isMobile()){

    openMobileMap();

  }



  setLoading(true);



map.once("moveend", () => {

  setLoading(false);

});



    markerGroup.clearLayers();



  const province = document.getElementById("province").value;

  const city = document.getElementById("city").value;

  const towns = getSelectedTowns();

  const categories = getCheckedCategories();



  // 10번: 선택값 세션에 저장

  sessionStorage.setItem("sel_province", province);

  sessionStorage.setItem("sel_city", city);

  sessionStorage.setItem("sel_town", "");



  const params = new URLSearchParams();

  if(province) params.append("province", province);

  if(city) params.append("city", city);

  towns.forEach(t => params.append("town", t));

  expandCats(categories).forEach(cat => params.append("category", cat));



  try{



    const res = await fetch("/data?" + params.toString());

    const result = await res.json();

    const data = result.data;

    const total = result.total;



    // 5000개 초과 시 서버 부하 방지 팝업
    if(result.too_many){
      setLoading(false);
      if(window.FEATURE_DETAIL && document.getElementById("srMsgHead")){
        srNotice("검색 결과가 너무 많아요", `${total.toLocaleString()}건이 조회됐어요 (5,000건까지 표시 가능)`, "시도 → 시군구 → 읍면동 순서로 범위를 좁히거나\n구분을 골라서 다시 조회해 주세요.");
      } else {
      showMsg(`🚨 검색 결과가 너무 많습니다 (${total.toLocaleString()}건)\n\n시도 → 시군구 → 읍면동으로 범위를 좁히거나 위험지역 구분을 선택해 주세요.`);
      }
      return;
    }



fetch("/log_search", {

  method:"POST",

  headers:{

    "Content-Type":"application/json"

  },

  body:JSON.stringify({

    province:province,

    city:city,

    categories:categories,

    result_count:total

  })

});



    const bounds = [];



    data.forEach(item => {



  

    const icon = buildMarkerIcon(item.마커색상);

    const marker = L.marker([item.위도, item.경도], { icon });

    marker.itemData = item;

    const popupHtml = buildPopupHtml(item);



      marker.bindPopup(popupHtml, { maxWidth: isMobile() ? 310 : 650 });

      markerGroup.addLayer(marker);

bounds.push([item.위도, item.경도]);



});





  if(bounds.length > 0){

    // 2번: 내 위치가 있으면 bounds에 포함해서 함께 보이도록

    const allBounds = [...bounds];

    if(userLat !== null && userLng !== null){

      allBounds.push([userLat, userLng]);

      drawUserLocation(userLat, userLng);

    }

    map.fitBounds(allBounds, { padding:[40,40] });

    map.once("moveend", closeMsg);

  }else{

    map.setView([34.85, 126.90], 9);

    showMsg("조건에 맞는 데이터가 없습니다.");

  }





if(isMobile()){

  syncToMobileMap(data);

}



// 조회 결과 목록 표시 (최대 10개)

// 결과가 5000개 미만일 때만 목록 표시

// 조회 결과 목록 표시 (5000개 미만일 때만)

// 조회 결과 목록 표시 (5000개 미만일 때만)

if(!isMobile()){

  if(total < 5000){

    showResultList(data, userLat, userLng);

  }else{

    const panel = document.getElementById("mobileResultPanel");

    if(panel){

      panel.style.display = "none";

    }

  }

}  }catch(e){

    showMsg("데이터를 불러오는 중 오류가 발생했습니다.");

    console.error(e);





  }finally{

  }

}



function resetFilters(){



  // 시도 초기화

  document.getElementById("province").value = "";



  // 시군구 초기화 (옵션 목록도 전체만 남기기)

  const cityEl = document.getElementById("city");

  cityEl.innerHTML = '<option value="">전체</option>';

  cityEl.value = "";



  // 읍면동 목록 초기화

  const townWrap = document.getElementById("townMultiWrap");

  if(townWrap){

    townWrap.innerHTML = '<div class="town-check-item" style="color:#475569;font-size:11px;">시군구를 먼저 선택하세요</div>';

  }



  // 읍면동 체크박스 해제

  document.querySelectorAll(".town-check")

  .forEach(el => el.checked = false);



  // 구분 체크 해제

  document.querySelectorAll(".category-check")

  .forEach(el => el.checked = false);



  // sessionStorage도 함께 초기화

  sessionStorage.removeItem("sel_province");

  sessionStorage.removeItem("sel_city");

  sessionStorage.removeItem("sel_town");





  // PC 지도 마커 삭제

  if(markerGroup){

    markerGroup.clearLayers();

  }



  // 모바일 지도 마커 삭제

  if(window.mobileMarkerGroup){

    window.mobileMarkerGroup.clearLayers();

  }



  // 지도 위치 초기화

  map.setView([34.85,126.90],9);



  // ⭐ 경로선 삭제

  if(routeLine){

    map.removeLayer(routeLine);

    routeLine = null;

  }



  // 모바일 결과 패널 닫기

  const result = document.getElementById("mobileResultPanel");

  if(result){

    result.style.display = "none";

  }



  // 초기화 후 재조회는 사용자가 직접 조회 버튼을 눌러야 함 (자동 전체 조회 제거)



}



window.addEventListener("load", function(){

  setTimeout(()=>{

    map.invalidateSize();

  },1000);

});



window.addEventListener("DOMContentLoaded", function(){

  // (입장 시 IME 예열 제거 — 이제 버튼 클릭 시 제스처 안에서 바로 focus하므로 불필요)

  preloadLocation();



  createCategoryChecks();



  loadMeta().then(()=>{

    // 시군구 선택 시 읍면동 갱신 + sessionStorage 즉시 저장 (조회는 버튼으로)

    document.getElementById("city").addEventListener("change", async function(){

      await updateTowns();

      sessionStorage.setItem("sel_city", document.getElementById("city").value);

    });

    // 시도 선택 시 시군구 갱신 + sessionStorage 즉시 저장

    document.getElementById("province").addEventListener("change", async function(){

      await updateCities();

      sessionStorage.setItem("sel_province", document.getElementById("province").value);

      // 시도 바뀌면 시군구 초기화

      sessionStorage.setItem("sel_city", "");

    });

    // 자동 loadAllMarkers 제거 — 조회 버튼을 눌러야만 데이터 로드

  });



  const destInput = document.getElementById("destInput");



if(destInput){

  destInput.addEventListener(

  "input",

  debounce(function(){

    searchPlaceSuggestions(this.value, "destInput");

  }, 400)

);

}



const startInput = document.getElementById("startInput");



if(startInput){

  startInput.addEventListener(

  "input",

  debounce(function(){

    searchPlaceSuggestions(this.value, "startInput");

  }, 400)

);

}





});



function goHome(){



  window.location.href = "/";



}



function openAdminStats(){



  const modal = document.getElementById("adminPwModal");

  const input = document.getElementById("adminPwInput");

  const msg = document.getElementById("adminPwMsg");



  if(!modal || !input){

    return;

  }



  input.value = "";

  msg.textContent = "";

  modal.style.display = "flex";



  activateIme("adminPwInput");



}

function closeAdminPwModal(){



  const modal = document.getElementById("adminPwModal");



  if(modal){

    modal.style.display = "none";

  }



}



function submitAdminPw(){



  const input = document.getElementById("adminPwInput");

  const msg = document.getElementById("adminPwMsg");



  if(!input){

    return;

  }



  fetch("/api/admin/login", {
    method:"POST",
    headers:{"Content-Type":"application/json"},
    body: JSON.stringify({password: input.value})
  }).then(function(r){ return r.json(); }).then(function(d){
    if(d && d.ok){ window.location.href = "/stats"; return; }
    if(msg){ msg.textContent = "암호가 틀렸습니다."; }
    input.focus();
  }).catch(function(){
    if(msg){ msg.textContent = "확인 중 오류가 발생했습니다."; }
  });



}



function isMobile(){

  if(/Android|iPhone|iPad|iPod|Mobile/i.test(navigator.userAgent)) return true;

  return window.innerWidth < 900;

}



function openSexOffenderApp(){



  const ua = navigator.userAgent || "";

  const isAndroid = /Android/i.test(ua);

  const isIOS = /iPhone|iPad|iPod/i.test(ua);



  const pcUrl = "https://www.sexoffender.go.kr";

  const playStoreUrl = "https://play.google.com/store/apps/details?id=com.mogef_android1.app";

  const appStoreUrl = "https://apps.apple.com/kr/app/%EC%84%B1%EB%B2%94%EC%A3%84%EC%9E%90-%EC%95%8C%EB%A6%BCe/id896534884";



  if(!isAndroid && !isIOS){

    window.open(pcUrl, "_blank");

    return;

  }



  if(isAndroid){



    const intentUrl =

      "intent://#Intent;"

      + "scheme=sexoffender;"

      + "package=com.mogef_android1.app;"

      + "S.browser_fallback_url=" + encodeURIComponent(playStoreUrl) + ";"

      + "end";



    window.location.href = intentUrl;

    return;

  }



  if(isIOS){

    window.location.href = appStoreUrl;

    return;

  }

}



function openMobileMap(){





  if(!isMobile()) return;



  const popup = document.getElementById("mobileMapPopup");

  popup.style.display = "flex";



  // 뒤로가기 시 홈(조건 선택 화면)으로 돌아오도록 히스토리 상태 push

  if(!window._mobileMapHist){

    window._mobileMapHist = true;

    history.pushState({mobileMap:true}, "", location.href);

  }



  const mapDiv = document.getElementById("mobileMap");



  if(!window.mobileLeafletMap){



    



    window.mobileLeafletMap = L.map(mapDiv, {zoomControl: false}).setView([34.85, 126.90], 9);



    // 줌 컨트롤을 알약 메뉴 아래(왼쪽)에 배치

    L.control.zoom({position: 'topleft'}).addTo(window.mobileLeafletMap);
    srAddLocateBtn(window.mobileLeafletMap);



    L.tileLayer(

      "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",

      { maxZoom: 19 }

    ).addTo(window.mobileLeafletMap);



    window.mobileMarkerGroup = L.markerClusterGroup({

      showCoverageOnHover:false,

      spiderfyOnMaxZoom:true,

      disableClusteringAtZoom:15,

      chunkedLoading:true

    });



    window.mobileLeafletMap.addLayer(window.mobileMarkerGroup);
    // 내 위치(초록 원·점)는 시설 마커와 같이 묶이지 않게 따로 그림. 마커를 지울 때 같이 지움
    window.mobileUserGroup = L.layerGroup().addTo(window.mobileLeafletMap);
    (function(g){ const cl = g.clearLayers.bind(g);
      g.clearLayers = function(){ window.mobileUserGroup.clearLayers(); return cl(); }; })(window.mobileMarkerGroup);



    // 5번: 모바일 팝업 열릴 때 별점 + 로드뷰 로드

    window.mobileLeafletMap.on("popupopen", onPopupOpen);

    window.mobileLeafletMap.on("popupclose", onPopupClose);

  }



  setTimeout(()=>{

    window.mobileLeafletMap.invalidateSize();

  }, 200);

}



function closeMobileMap(){



  document.getElementById("mobileMapPopup").style.display = "none";



  const result = document.getElementById("mobileResultPanel");



  if(result){

    result.style.display = "none";

  }



}


window.safeBack = function(){

  const mobileMap = document.getElementById("mobileMapPopup");

  const result = document.getElementById("mobileResultPanel");

  const routePopup = document.getElementById("routePopup");

  const addrPopup = document.getElementById("addressPopup");

  const msgModal = document.getElementById("msgModal");



  function isOpen(el){

    if(!el) return false;

    const style = window.getComputedStyle(el);

    return style.display !== "none" && style.visibility !== "hidden";

  }



  if(isOpen(msgModal)){

    msgModal.style.display = "none";

    return "handled";

  }



  if(isOpen(routePopup)){

    routePopup.style.display = "none";

    return "handled";

  }



  if(isOpen(addrPopup)){

    addrPopup.style.display = "none";

    return "handled";

  }



  if(isOpen(mobileMap)){

    mobileMap.style.display = "none";

    if(result) result.style.display = "none";

    return "handled";

  }



  return "exit";

};




function syncToMobileMap(items, userLat=null, userLng=null, radiusMeter=null){



  if(!isMobile()) return;



  if(userLat && userLng){



    items.sort((a,b)=>{



      const da = calcDistance(userLat,userLng,a.위도,a.경도);

      const db = calcDistance(userLat,userLng,b.위도,b.경도);



      return da-db;



    });



  }









  openMobileMap();



  window.mobileMarkerGroup.clearLayers();





  const bounds = [];



  if(userLat !== null && userLng !== null){



  const userCircle = L.circle(

    [userLat, userLng],

    {

      radius: 160,

      color:"#22c55e",

      fillColor:"#22c55e",

      fillOpacity:0.28,

      weight:3

    }

  );



  const userMarker = L.marker(

    [userLat, userLng],

    { icon: buildUserIcon(), zIndexOffset: 1000 }

  );



  window.mobileUserGroup.addLayer(userCircle);

  window.mobileUserGroup.addLayer(userMarker);



  bounds.push([userLat, userLng]);



  if(radiusMeter){

    const circle = L.circle(

      [userLat, userLng],

      {

        radius: radiusMeter,

        color:"#2563eb",

        fillColor:"#2563eb",

        fillOpacity:0.08

      }

    );

    window.mobileUserGroup.addLayer(circle);

  }

}



items.forEach(item=>{



  const icon = buildMarkerIcon(item.마커색상);



  const marker = L.marker([item.위도,item.경도],{icon});

  marker.itemData = item;



  const popupHtml = buildPopupHtml(item);



  marker.bindPopup(popupHtml,{maxWidth: isMobile() ? 310 : 650, autoPan: false});



  window.mobileMarkerGroup.addLayer(marker);



  bounds.push([item.위도,item.경도]);



});





  setTimeout(()=>{

    window.mobileLeafletMap.invalidateSize();



    if(bounds.length > 0){

      window.mobileLeafletMap.fitBounds(bounds, { padding:[40,40] });

    }else{

      window.mobileLeafletMap.flyTo(

  [34.85,126.90],

  9,

  {

    duration:1.2,

    easeLinearity:0.25

  }

);

    }



  }, 250);





// 🔵 여기 추가

showMobileResults(items,userLat,userLng);

}



async function findNearestToilet(){



  clearRoute();   // ⭐ 추가



  showLoadingLocation();   // 추가



  if(!navigator.geolocation){

    showMsg("GPS를 지원하지 않는 기기입니다.");

    return;

  }



  navigator.geolocation.getCurrentPosition(



    pos=>{



      const lat = pos.coords.latitude;

      const lng = pos.coords.longitude;



      userLat = lat;

      userLng = lng;



      runNearestSearch(lat,lng,"공중화장실");



    },



    err=>{

      closeMsg();

      showMsg("위치를 가져올 수 없습니다.");

    },



    {

      enableHighAccuracy:true,

      timeout:10000,

      maximumAge:0

    }



  );



}







async function findNearestFacility(targetType){
  closeFacilityFab();
  clearRoute();
  showLoadingLocation();
  if(!navigator.geolocation){ showMsg("GPS를 지원하지 않는 기기입니다."); return; }
  navigator.geolocation.getCurrentPosition(
    pos=>{
      const lat = pos.coords.latitude;
      const lng = pos.coords.longitude;
      userLat = lat; userLng = lng;
      runNearestSearch(lat,lng,targetType);
    },
    err=>{ closeMsg(); showMsg("위치를 가져올 수 없습니다."); },
    { enableHighAccuracy:true, timeout:10000, maximumAge:0 }
  );
}

function toggleFacilityFab(){
  const m = document.getElementById("facilityFabMenu");
  if(!m) return;
  const open = (m.style.display !== "flex");
  m.style.display = open ? "flex" : "none";
  document.body.style.overflow = open ? "hidden" : "";
}

function closeFacilityFab(){
  const m = document.getElementById("facilityFabMenu");
  if(m) m.style.display = "none";
  document.body.style.overflow = "";
}



async function findNearestDanger(){



  clearRoute();   // ⭐ 추가



  showLoadingLocation();



  if(!navigator.geolocation){

    showMsg("GPS를 지원하지 않는 기기입니다.");

    return;

  }



  navigator.geolocation.getCurrentPosition(



    pos=>{



      const lat = pos.coords.latitude;

      const lng = pos.coords.longitude;



      userLat = lat;

      userLng = lng;



      runNearestSearch(lat,lng,"상습결빙지역");



    },



    err=>{

      closeMsg();

      showMsg("위치를 가져올 수 없습니다.");

    },



    {

      enableHighAccuracy:true,

      timeout:10000,

      maximumAge:0

    }



  );



}



async function runNearestSearch(lat,lng,targetType){



  if(!ALL_DATA_CACHE){

  const res = await fetch("/data/all");

  const result = await res.json();

  ALL_DATA_CACHE = result.data || [];

}



const data = ALL_DATA_CACHE;



  const radius = 5000;



  const filtered = [];



  data.forEach(item=>{

    

    console.log(item.구분,targetType);



    if(!catMatch(item.구분, targetType)) return;
    if(!facilityFilterPass(item, targetType)) return;



    const dist = map.distance(

      [lat,lng],

      [item.위도,item.경도]

    );



    if(dist <= radius){



      item._dist = dist;



      filtered.push(item);



    }



  });



  filtered.sort((a,b)=>a._dist-b._dist);

  filtered.splice(10);



  if(filtered.length === 0){

    closeMsg();   // ⭐ 추가

    if(facilityFilterActive(targetType)){
      showMsg("조건에 맞는 곳이 주변 5km 안에 없습니다.\n(정보가 없는 곳은 조건 검색에서 빠집니다)");
    } else {
      showMsg("주변에 데이터가 없습니다.");
    }



    return;



  }



if(isMobile()){

  syncToMobileMap(filtered,lat,lng,5000);

  closeMsg();   // ⭐ 이거 추가

  return;

}



const bounds = [];



bounds.push([lat,lng]);



filtered.forEach(item=>{

  bounds.push([item.위도,item.경도]);

});



map.fitBounds(bounds,{

  padding:[60,60]

});



map.once("moveend", closeMsg);



// ⭐ moveend 안 생길 경우 대비

setTimeout(closeMsg, 800);



markerGroup.clearLayers();



drawUserLocation(lat, lng);

L.circle(

  [lat,lng],

  {

    radius: radius,

    color:"#2563eb",

    fillColor:"#2563eb",

    fillOpacity:0.08

  }

).addTo(markerGroup);



filtered.forEach(item=>{



  const icon = buildMarkerIcon(item.마커색상);



const marker = L.marker(

  [item.위도,item.경도],

  {icon}

);

marker.itemData = item;



const popupHtml = buildPopupHtml(item);



marker.bindPopup(popupHtml,{maxWidth: isMobile() ? 310 : 650, autoPan: false});



markerGroup.addLayer(marker);





});



showResultList(filtered,lat,lng);



}







async function findRadius(km){



  if(userLat && userLng){

    runRadius(userLat,userLng,km);

    return;

  }



  if(!navigator.geolocation){

    showMsg("GPS를 지원하지 않는 기기입니다.");

    return;

  }



  navigator.geolocation.getCurrentPosition(



    pos=>{



      closeMsg();

      userLat = pos.coords.latitude;

      userLng = pos.coords.longitude;



      runRadius(userLat,userLng,km);



    },



    err=>{

     closeMsg();   // ⭐ 추가



      showMsg("위치를 가져올 수 없습니다.");

    },



    {

      enableHighAccuracy:true,

      timeout:10000,

      maximumAge:0

    }



  );



}





/* CC BY (주차장 출처) 배지: 결과 목록이 전부 주차장일 때만 표시 */
function updateCcbyBadge(){
  var el = document.getElementById('ccbyBadge');
  if(!el) return;
  var nodes = document.querySelectorAll('#mobileResultList .mobile-result-item');
  var hasVisible = false, allParking = true;
  nodes.forEach(function(n){
    if(n.style.display === 'none') return;
    hasVisible = true;
    if(!catMatch(n.dataset.gubun || '', '주차장')) allParking = false;
  });
  el.style.display = (hasVisible && allParking) ? 'flex' : 'none';
}
(function(){
  function setup(){
    var list = document.getElementById('mobileResultList');
    if(!list){ setTimeout(setup, 300); return; }
    try{
      var obs = new MutationObserver(function(){ updateCcbyBadge(); });
      obs.observe(list, {childList:true, subtree:true, attributes:true, attributeFilter:['style']});
    }catch(e){}
    updateCcbyBadge();
  }
  if(document.readyState === 'loading'){
    document.addEventListener('DOMContentLoaded', setup);
  } else { setup(); }
}());

function showResultList(items, userLat, userLng){



  const panel = document.getElementById("mobileResultPanel");

  const list = document.getElementById("mobileResultList");



  panel.style.display = "flex";

  list.innerHTML = "";



  items.forEach(item=>{



    let distText = "";



    if(userLat && userLng){

      const dist = Math.round(

        calcDistance(userLat,userLng,item.위도,item.경도)

      );

      distText = fmtDist(dist);

    }



    const el = document.createElement("div");



    el.className = "mobile-result-item";

    el.dataset.gubun = item.구분; el.dataset.lat = item.위도; el.dataset.lng = item.경도; el.dataset.addr = item.주소 || ""; el.dataset.name = item.시설명 || item.화장실명 || "";



    el.innerHTML = `

      <b>${gubunLabel(item.구분)}</b><br>

      ${item.시군구} ${item.읍면동}<br>

      <span class="mobile-result-distance">${distText}</span>

    `;

    el.onclick = function(){



  map.flyTo([item.위도,item.경도],16);



  map.once("moveend", function(){

    map.panBy([0, -150], {animate: false});

    markerGroup.eachLayer(function(layer){



      if(layer.itemData && layer.itemData.순번 === item.순번){

        layer.openPopup();

      }



    });



  });



  if(isMobile() && window.mobileLeafletMap){



    window.mobileLeafletMap.flyTo(

      [item.위도,item.경도],

      16,

      {

        duration:1.2,

        easeLinearity:0.25

      }

    );



    window.mobileLeafletMap.once("moveend", function(){

      // 팝업이 화면 중앙에 오도록 지도 오른쪽으로 이동
      if(window.mobileMarkerGroup){



        window.mobileMarkerGroup.eachLayer(function(layer){



          if(layer.itemData && layer.itemData.순번 === item.순번){

            window._skipPopupAutoPan = true;

            layer.openPopup();

          }



        });



      }



    });



  }



};





    list.appendChild(el);



  });



  document.getElementById("mobileResultCount").textContent = items.length;



}



async function runRadius(lat,lng,km){



  if(!ALL_DATA_CACHE){

  const res = await fetch("/data/all");

  const result = await res.json();

  ALL_DATA_CACHE = result.data || [];

}



const data = ALL_DATA_CACHE;



  markerGroup.clearLayers();



  const radiusMeter = km * 1000;



  drawUserLocation(lat,lng);



  L.circle(

    [lat,lng],

    {

      radius: radiusMeter,

      color:"#2563eb",

      fillColor:"#2563eb",

      fillOpacity:0.08

    }

  ).addTo(markerGroup);



  const filtered = [];



  data.forEach(item=>{



    const dist = map.distance(

      [lat,lng],

      [item.위도,item.경도]

    );



    if(dist <= radiusMeter){

      filtered.push(item);

    }



  });



  if(filtered.length === 0){

    showMsg(`${km}km 안에 위험지역이 없습니다.`);

    return;

  }



  if(isMobile()){

    syncToMobileMap(filtered,lat,lng,radiusMeter);

  }



}



window.addEventListener("DOMContentLoaded", function(){



  const locBtn = document.getElementById("locBtn");



  if(locBtn){

    locBtn.onclick = function(){



      if(!navigator.geolocation){

        showMsg("GPS를 지원하지 않는 기기입니다.");

        return;

      }



navigator.geolocation.getCurrentPosition(



pos=>{



const lat = pos.coords.latitude;

const lng = pos.coords.longitude;



userLat = lat;

userLng = lng;



console.log("내 위치 버튼:", lat, lng, "정확도:", pos.coords.accuracy);



markerGroup.clearLayers();



map.flyTo([lat, lng], 17);



// ⭐ 내 위치 표시

drawUserLocation(lat,lng);



if(isMobile() && window.mobileLeafletMap){

  window.mobileLeafletMap.flyTo(

  [lat,lng],

  17,

  {

    duration:1.2,

    easeLinearity:0.25

  }

);

}



if(window.mobileMarkerGroup){

  // 결과 마커(itemData 있는 것)는 유지하고, 이전 '내 위치' 표시만 제거
  var __rm = [];
  window.mobileMarkerGroup.eachLayer(function(l){ if(!l.itemData) __rm.push(l); });
  __rm.forEach(function(l){ window.mobileMarkerGroup.removeLayer(l); });
  if(window.mobileUserGroup) window.mobileUserGroup.clearLayers();



  const userCircle = L.circle(

    [lat, lng],

    {

      radius:180,

      color:"#22c55e",

      fillColor:"#22c55e",

      fillOpacity:0.28,

      weight:3

    }

  );



  const userMarker = L.marker(

    [lat, lng],

    { icon: buildUserIcon(), zIndexOffset: 1000 }

  );



  window.mobileUserGroup.addLayer(userCircle);

  window.mobileUserGroup.addLayer(userMarker);

}

},



err=>{

  showMsg("위치를 가져올 수 없습니다.");

},



{

  enableHighAccuracy:true,

  timeout:10000,

  maximumAge:0

}



);



    };

  }



});

window.addEventListener("popstate", function(){

window._mobileMapHist = false;

clearRoute();   // ⭐ 추가



const popup = document.getElementById("mobileMapPopup");

const result = document.getElementById("mobileResultPanel");



if(result){

  result.style.display = "none";

}



if(popup){

  popup.style.display = "none";

}



});





window.addEventListener("DOMContentLoaded", function(){



const mobileBtn = document.getElementById("mobileLocBtn");



if(mobileBtn){



mobileBtn.onclick = function(){



if(!navigator.geolocation){

  alert("GPS를 지원하지 않습니다.");

  return;

}



navigator.geolocation.getCurrentPosition(



pos=>{

const lat = pos.coords.latitude;

const lng = pos.coords.longitude;



userLat = lat;

userLng = lng;



console.log("모바일 위치 버튼:", lat, lng, "정확도:", pos.coords.accuracy);



if(isMobile() && window.mobileLeafletMap){



  window.mobileLeafletMap.flyTo(

  [lat,lng],

  17,

  {

    duration:1.2,

    easeLinearity:0.25

  }

);



  if(window.mobileMarkerGroup){

  window.mobileMarkerGroup.clearLayers();



  const userCircle = L.circle(

    [lat, lng],

    {

      radius: 160,

      color:"#22c55e",

      fillColor:"#22c55e",

      fillOpacity:0.28,

      weight:3

    }

  );



  const userMarker = L.marker(

    [lat, lng],

    { icon: buildUserIcon(), zIndexOffset: 1000 }

  );



  window.mobileUserGroup.addLayer(userCircle);

  window.mobileUserGroup.addLayer(userMarker);

}



}},



err=>{

  closeMsg();

  showMsg("위치를 가져올 수 없습니다.");

},



{

  enableHighAccuracy:true,

  timeout:10000,

  maximumAge:0

}



);

};



}



});



let loadingStartTime = 0;




function activateIme(inputId){
  var inp = document.getElementById(inputId);
  if(!inp) return;
  // 방금 보여진 요소의 레이아웃을 확정시킨 뒤(안드로이드 크롬/웨일 대비),
  // 사용자 탭 제스처 안에서 곧바로 focus → 웨일/크롬/삼성/사파리 모두 자판이 뜬다.
  void inp.offsetHeight;
  inp.focus({ preventScroll: true });
}
// 자판이 뜨면 경로/주소 팝업 카드를 자판 위로 올리고, 자판 끄면 다시 중앙
(function(){
  if(!window.visualViewport) return;
  var vv = window.visualViewport;
  function adjustPopupForKeyboard(){
    var kb = window.innerHeight - vv.height - vv.offsetTop;
    var shift = (kb > 80) ? -Math.round(kb/2) : 0;
    ["routePopup","addrSearchPopup"].concat(window.FEATURE_DETAIL ? ["adminPwModal"] : []).forEach(function(id){
      var p = document.getElementById(id);
      if(!p || getComputedStyle(p).display === "none") return;
      var card = p.firstElementChild;
      if(card){ card.style.transition = "transform .2s ease"; card.style.transform = "translateY(" + shift + "px)"; }
    });
  }
  vv.addEventListener("resize", adjustPopupForKeyboard);
  vv.addEventListener("scroll", adjustPopupForKeyboard);
})();



function openRouteSearch(){

  var popup = document.getElementById("routePopup");

  popup.style.display = "flex";

  document.getElementById("startInput").value = "";

  document.getElementById("destInput").value = "";

  activateIme("startInput");

}


function closeRoutePopup(){

  document.getElementById("routePopup").style.display="none";



  const box = document.getElementById("destSuggestBox");

  if(box){

    box.style.display = "none";

    box.innerHTML = "";

  }

}





document.addEventListener("click", function(e){



  const input = document.getElementById("destInput");

  const box = document.getElementById("destSuggestBox");



  if(!input || !box){

    return;

  }





  if(e.target !== input && !box.contains(e.target)){

    box.style.display = "none";

  }



});





async function searchPlaceSuggestions(query, inputId){



  const box = document.getElementById("destSuggestBox");



  if(!box){

    return;

  }



  query = query.trim();



  if(query.length < 3){

    box.style.display = "none";

    box.innerHTML = "";

    return;

  }



  try{



    const res = await fetch("/search_place?q=" + encodeURIComponent(query));

    const data = await res.json();



    box.innerHTML = "";



    if(!data.documents || data.documents.length === 0){

      box.innerHTML = `

        <div style="padding:12px;font-size:13px;color:#64748b;">

          검색 결과가 없습니다.

        </div>

      `;

      box.style.display = "block";

      return;

    }



    data.documents.slice(0,5).forEach(place=>{



      const item = document.createElement("div");



      item.style.padding="10px 12px";

      item.style.borderBottom="1px solid #f1f5f9";

      item.style.cursor="pointer";

      item.style.fontSize="13px";

      item.style.lineHeight="1.45";



      // 3번: 도로명주소(신주소)와 지번주소(구주소) 모두 표시

      const roadAddr = place.road_address_name || "";

const jibunAddr = place.address_name || "";



const addrLineHtml = roadAddr

  ? `<div style="margin-top:3px;color:#64748b;font-size:11px;font-weight:600;">

       ${escapeHtml(roadAddr)}

     </div>

     <div style="margin-top:1px;color:#94a3b8;font-size:10.5px;">

       ${escapeHtml(jibunAddr)}

     </div>`

  : `<div style="margin-top:3px;color:#64748b;font-size:11px;">

       ${escapeHtml(jibunAddr)}

     </div>`;



item.innerHTML = `

  <div style="font-size:14px;font-weight:900;color:#0f172a;margin-bottom:2px;">

    ${escapeHtml(place.place_name || "")}

  </div>

  ${addrLineHtml}

`;



      item.onclick=function(){

        const input=document.getElementById(inputId);

        if(input){

          input.value=place.place_name || "";

          // 4번: 좌표를 data 속성에 저장해서 정확한 위치 사용

          input.dataset.lat = place.y || "";

          input.dataset.lng = place.x || "";

          input.dataset.addr = jibunAddr;

        }

        box.style.display="none";

        box.innerHTML="";

      };



      box.appendChild(item);



    });



    box.style.display="block";



  }catch(err){



    console.error("자동완성 검색 오류:",err);

    box.style.display="none";

    box.innerHTML="";



  }



}



async function geocodeAddress(query, inputId){



  query = query.trim();



  if(!query){

    return null;

  }



  // 4번: 자동완성으로 선택한 경우 저장된 좌표를 우선 사용 (다른 지역 혼동 방지)

  if(inputId){

    const el = document.getElementById(inputId);

    if(el && el.dataset.lat && el.dataset.lng && el.value === query){

      return {

        lat: parseFloat(el.dataset.lat),

        lng: parseFloat(el.dataset.lng)

      };

    }

  }



  const res = await fetch("/search_place?q=" + encodeURIComponent(query));

  const data = await res.json();



  if(data.documents && data.documents.length > 0){

    return {

      lat: parseFloat(data.documents[0].y),

      lng: parseFloat(data.documents[0].x)

    };

  }



  return null;



}





function distancePointToLine(px,py,x1,y1,x2,y2){



  const A = px-x1;

  const B = py-y1;

  const C = x2-x1;

  const D = y2-y1;



  const dot = A*C + B*D;

  const len = C*C + D*D;



  let param = -1;



  if(len!==0){

    param = dot/len;

  }



  let xx,yy;



  if(param<0){

    xx=x1;

    yy=y1;

  }else if(param>1){

    xx=x2;

    yy=y2;

  }else{

    xx=x1 + param*C;

    yy=y1 + param*D;

  }



  return calcDistance(px,py,xx,yy);



}





async function getRoadRoute(startLat,startLng,endLat,endLng){



  const url =

  "https://router.project-osrm.org/route/v1/driving/"

  + startLng + "," + startLat + ";"

  + endLng + "," + endLat

  + "?overview=full&geometries=geojson";



  const res = await fetch(url);

  const data = await res.json();



  if(!data.routes || data.routes.length === 0){

    return null;

  }



  return data.routes[0].geometry.coordinates;



}



function distancePointToRoute(lat, lng, routeLatLngs){



  let minDist = Infinity;



  for(let i = 0; i < routeLatLngs.length - 1; i++){



    const p1 = routeLatLngs[i];

    const p2 = routeLatLngs[i + 1];



    const dist = distancePointToLine(

      lng, lat,

      p1[1], p1[0],

      p2[1], p2[0]

    );



    if(dist < minDist){

      minDist = dist;

    }



  }



  return minDist;

}



async function runRouteSearch(){

  showLoadingLocation();   // ⭐ 추가



  closeRoutePopup();   // ⭐ 여기 추가





  clearRoute();



  if(isMobile()){

    openMobileMap();

    await new Promise(r => setTimeout(r,300));

  }



  const start = document.getElementById("startInput").value.trim();

  const dest = document.getElementById("destInput").value.trim();



  if(!dest){

    showMsg("도착지를 입력하세요.");

    return;

  }



  let startLat = userLat;

  let startLng = userLng;



  if(start){

    const startGeo = await geocodeAddress(start, "startInput");



    if(!startGeo){

      showMsg("출발지를 찾을 수 없습니다.");

      return;

    }



    startLat = startGeo.lat;

    startLng = startGeo.lng;

  }else{

    if(userLat === null || userLng === null){

      showMsg("출발지를 입력하거나 내 위치를 먼저 확인해주세요.");

      return;

    }

  }



  const endGeo = await geocodeAddress(dest, "destInput");



  if(!endGeo){

    showMsg("도착지를 찾을 수 없습니다.");

    return;

  }



  const endLat = endGeo.lat;

  const endLng = endGeo.lng;
  if(window.FEATURE_DETAIL) window.srRef = {lat: startLat, lng: startLng, kind: "route"};

  const road = await getRoadRoute(startLat,startLng,endLat,endLng);



let routeLatLngs = [];



if(road){

  routeLatLngs = road.map(c => [c[1], c[0]]);

}else{

  routeLatLngs = [

    [startLat, startLng],

    [endLat, endLng]

  ];

}



 if(!ALL_DATA_CACHE){

  const res = await fetch("/data/all");

  const result = await res.json();

  ALL_DATA_CACHE = result.data || [];

}



const data = ALL_DATA_CACHE;



const radius = 50;



const filtered = [];



data.forEach(item=>{



  const dist = distancePointToRoute(

    item.위도,

    item.경도,

    routeLatLngs

  );

  

  if(dist <= radius && srCatOk(item, "route")){

    filtered.push(item);

  }



});



  markerGroup.clearLayers();



  filtered.forEach(item=>{

    const icon = buildMarkerIcon(item.마커색상);

    const marker = L.marker([item.위도, item.경도], {icon});

    marker.itemData = item;

    const popupHtml = buildPopupHtml(item);

    marker.bindPopup(popupHtml,{maxWidth: isMobile() ? 310 : 650, autoPan: false});

    markerGroup.addLayer(marker);

  });



  if(routeLine){

    map.removeLayer(routeLine);

  }



routeLine = L.polyline(

  routeLatLngs,

  {color:"#2563eb", weight:5}

).addTo(map);



if(isMobile() && window.mobileLeafletMap){



  if(window.mobileRouteLine){

    window.mobileLeafletMap.removeLayer(window.mobileRouteLine);

  }



  window.mobileRouteLine = L.polyline(

    routeLatLngs,

    {color:"#2563eb", weight:5}

  ).addTo(window.mobileLeafletMap);



}



  map.fitBounds(

    [

      [startLat, startLng],

      [endLat, endLng]

    ],

    {padding:[60,60]}

  );



  // map.once("moveend", closeMsg);

  // setTimeout(closeMsg,800);



  const toiletCount = filtered.filter(x=>x.구분==="공중화장실").length;

  const iceCount = filtered.filter(x=>x.구분==="상습결빙지역").length;

  const accidentCount = filtered.filter(x=>x.구분==="교통사고위험지역").length;

  const parkingCount = filtered.filter(x=>x.구분==="공영주차장"||x.구분==="민영주차장").length;



  showMsg(

      `경로 주변 시설\n\n공중화장실 ${toiletCount}개\n상습결빙지역 ${iceCount}개\n교통사고위험지역 ${accidentCount}개\n주차장 ${parkingCount}개`

  );



  showResultList(filtered, (window.FEATURE_DETAIL || userLat === null) ? startLat : userLat, (window.FEATURE_DETAIL || userLng === null) ? startLng : userLng);



  if(isMobile()){

  syncToMobileMap(filtered, (window.FEATURE_DETAIL || userLat === null) ? startLat : userLat, (window.FEATURE_DETAIL || userLng === null) ? startLng : userLng);

}











  if(isMobile()){

  document.getElementById("mobileResultPanel").style.display="flex";

}





}





// 9번: 주소로 근처 위험지역 검색

function openAddressSearch(){

  document.getElementById("addrSearchPopup").style.display="flex";

  document.getElementById("addrSearchInput").value="";

  document.getElementById("addrSuggestBox").style.display="none";

  document.getElementById("addrSuggestBox").innerHTML="";

  activateIme("addrSearchInput");

}



function closeAddressSearch(){

  document.getElementById("addrSearchPopup").style.display="none";

}



window.addEventListener("DOMContentLoaded", function(){

  const addrInput = document.getElementById("addrSearchInput");

  if(addrInput){

    addrInput.addEventListener("input", debounce(function(){

      searchAddrSuggestions(this.value);

    }, 400));

  }

});



async function searchAddrSuggestions(query){

  const box = document.getElementById("addrSuggestBox");

  if(!box) return;

  query = query.trim();

  if(query.length < 2){ box.style.display="none"; box.innerHTML=""; return; }

  try{

    const res = await fetch("/search_place?q=" + encodeURIComponent(query));

    const data = await res.json();

    box.innerHTML="";

    if(!data.documents || data.documents.length===0){

      box.innerHTML='<div style="padding:10px;font-size:13px;color:#94a3b8;">결과 없음</div>';

      box.style.display="block"; return;

    }

    data.documents.slice(0,5).forEach(place=>{

      const d = document.createElement("div");

      d.style.cssText="padding:9px 12px;border-bottom:1px solid #f1f5f9;cursor:pointer;font-size:13px;";

      

      const roadA = place.road_address_name || "";

const jibunA = place.address_name || "";



const addrLineHtml = roadA

  ? `<div style="margin-top:3px;color:#64748b;font-size:11px;font-weight:600;">

       ${escapeHtml(roadA)}

     </div>

     <div style="margin-top:1px;color:#94a3b8;font-size:10.5px;">

       ${escapeHtml(jibunA)}

     </div>`

  : `<div style="margin-top:3px;color:#64748b;font-size:11px;">

       ${escapeHtml(jibunA)}

     </div>`;



d.innerHTML = `

  <div style="font-size:14px;font-weight:900;color:#0f172a;margin-bottom:2px;">

    ${escapeHtml(place.place_name || "")}

  </div>

  ${addrLineHtml}

`;



      d.onclick=function(){

        const inp=document.getElementById("addrSearchInput");

        inp.value=place.place_name||"";

        inp.dataset.lat=place.y||"";

        inp.dataset.lng=place.x||"";

        box.style.display="none"; box.innerHTML="";

      };

      box.appendChild(d);

    });

    box.style.display="block";

  }catch(e){ box.style.display="none"; }

}



async function runAddressSearch(){

  const inp = document.getElementById("addrSearchInput");

  const query = inp.value.trim();

  if(!query){ showMsg("주소를 입력하세요."); return; }



  closeAddressSearch();

  showLoadingLocation();



  let lat, lng;

  if(inp.dataset.lat && inp.dataset.lng){

    lat = parseFloat(inp.dataset.lat);

    lng = parseFloat(inp.dataset.lng);

  } else {

    const geo = await geocodeAddress(query);

    if(!geo){ showMsg("주소를 찾을 수 없습니다."); return; }

    lat = geo.lat; lng = geo.lng;

  }



  if(!ALL_DATA_CACHE){

    const res = await fetch("/data/all");

    const result = await res.json();

    ALL_DATA_CACHE = result.data || [];

  }

  const data = ALL_DATA_CACHE;

  const radius = 5000;

  if(window.FEATURE_DETAIL) window.srRef = {lat: lat, lng: lng, kind: "addr"};
  const filtered = data.filter(item => {

    return calcDistance(lat, lng, item.위도, item.경도) <= radius && srCatOk(item, "addr");

  }).sort((a,b) =>

    calcDistance(lat,lng,a.위도,a.경도) - calcDistance(lat,lng,b.위도,b.경도)

  );



  if(filtered.length===0){

    closeMsg(); showMsg("5km 이내에 위험지역이 없습니다."); return;

  }



  if(isMobile()){

    syncToMobileMap(filtered, lat, lng, radius);

    closeMsg(); return;

  }



  markerGroup.clearLayers();

  // 주소 기준점 마커 (파란 원)

  L.circle([lat,lng],{radius:radius,color:"#2563eb",fillColor:"#2563eb",fillOpacity:0.07}).addTo(markerGroup);

  L.marker([lat,lng],{icon:L.divIcon({className:"",html:'<div style="width:18px;height:18px;border-radius:50%;background:#2563eb;border:3px solid #fff;box-shadow:0 2px 8px rgba(0,0,0,.3);"></div>',iconSize:[18,18],iconAnchor:[9,9]})}).addTo(markerGroup);



  const bounds = [[lat,lng]];

  filtered.forEach(item=>{

    const icon = buildMarkerIcon(item.마커색상);

    const marker = L.marker([item.위도,item.경도],{icon});

    marker.itemData = item;

    marker.bindPopup(buildPopupHtml(item),{maxWidth: isMobile() ? 310 : 650});

    markerGroup.addLayer(marker);

    bounds.push([item.위도,item.경도]);

  });

  map.fitBounds(bounds,{padding:[50,50]});

  map.once("moveend", closeMsg);

  setTimeout(closeMsg,800);

  showResultList(filtered, lat, lng);

}



// 1번 알약 필터 JS 끝

let mobilePillActive = "전체";

const PILL_COLORS = {

  "상습결빙지역": "#06b6d4",

  "공중화장실": "#f59e0b",

  "교통사고위험지역": "#ef4444",

  "주차장": "#8b5cf6",

  "전체": "#475569"

};

const PILL_IDS = {

  "전체": "pill_all",

  "상습결빙지역": "pill_ice",

  "공중화장실": "pill_toilet",

  "교통사고위험지역": "pill_accident",

  "주차장": "pill_parking"

};



function mobilePillFilter(cat){

  mobilePillActive = cat;

  // 알약 활성화 스타일

  Object.keys(PILL_IDS).forEach(k => {

    const el = document.getElementById(PILL_IDS[k]);

    if(!el) return;

    if(k === cat){

      el.classList.add("active");

      el.style.background = "rgba(255,255,255,.98)";

      el.style.borderColor = PILL_COLORS[k];

      el.style.borderWidth = "2px";

      el.style.color = "#1a202c";

    } else {

      el.classList.remove("active");

      el.style.background = "rgba(255,255,255,.93)";

      el.style.borderColor = "rgba(255,255,255,.85)";

      el.style.borderWidth = "1.5px";

      el.style.color = "#1a202c";

    }

  });



  // 마커 필터링

  if(window.mobileMarkerGroup && window.mobileLeafletMap){

    window.mobileMarkerGroup.eachLayer(function(layer){

      if(!layer.itemData) return;

      if(cat === "전체"){

        if(layer._icon) layer._icon.style.display="";

      } else {

        if(catMatch(layer.itemData.구분, cat)){

          layer._icon && (layer._icon.style.display="");

        } else {

          layer._icon && (layer._icon.style.display="none");

        }

      }

    });

  }



  // 2번: 결과 목록도 필터링

  const list = document.getElementById("mobileResultList");

  if(!list) return;

  const items = list.querySelectorAll(".mobile-result-item");

  items.forEach(el => {

    if(cat === "전체"){

      el.style.display = "";

    } else {

      if(catMatch(el.dataset.gubun || "", cat)){

        el.style.display = "";

      } else {

        el.style.display = "none";

      }

    }

  });



  // 결과 건수 업데이트

  const visible = cat === "전체"

    ? items.length

    : [...items].filter(el => el.style.display !== "none").length;

  const countEl = document.getElementById("mobileResultCount");

  if(countEl) countEl.textContent = visible;

}



// PC 알약 필터

const PC_PILL_COLORS = {

  "상습결빙지역": "#06b6d4",

  "공중화장실": "#f59e0b",

  "교통사고위험지역": "#ef4444",

  "주차장": "#8b5cf6",

  "전체": "#475569"

};

let pcPillActive = "전체";



function pcPillFilter(cat){

  pcPillActive = cat;

  ["전체","상습결빙지역","공중화장실","교통사고위험지역","주차장"].forEach(k=>{

    const id = "pc_pill_" + (k==="전체"?"all":k==="상습결빙지역"?"ice":k==="공중화장실"?"toilet":k==="교통사고위험지역"?"accident":"parking");

    const el = document.getElementById(id);

    if(!el) return;

    if(k===cat){

      el.classList.add("active");

      el.style.background = "rgba(255,255,255,.98)";

      el.style.borderColor = PC_PILL_COLORS[k];

      el.style.borderWidth = "2px";

      el.style.color = "#1a202c";

    } else {

      el.classList.remove("active");

      el.style.background = "rgba(255,255,255,.93)";

      el.style.borderColor = "rgba(255,255,255,.85)";

      el.style.borderWidth = "1.5px";

      el.style.color = "#1a202c";

    }

  });

  // PC 마커 필터링

  markerGroup.eachLayer(function(layer){

    if(!layer.itemData) return;

    if(cat==="전체"){

      if(layer._icon) layer._icon.style.display="";

    } else {

      if(layer._icon) layer._icon.style.display = catMatch(layer.itemData.구분, cat) ? "" : "none";

    }

  });

  // 결과 목록 필터 + 건수 업데이트

  const list = document.getElementById("mobileResultList");

  if(!list) return;

  const items = list.querySelectorAll(".mobile-result-item");

  items.forEach(el=>{

    const b = el.querySelector("b");

    el.style.display = (cat==="전체" || catMatch(el.dataset.gubun || "", cat)) ? "" : "none";

  });

  const visible = cat==="전체"

    ? items.length

    : [...items].filter(el => el.style.display !== "none").length;

  const countEl = document.getElementById("mobileResultCount");

  if(countEl) countEl.textContent = visible;

}



// ===== 5번: 별점 + 코멘트 =====



// 팝업 열릴 때 별점 + 로드뷰 자동 초기화, 검색결과 패널 숨김

function onPopupOpen(e){

  var __mlb=document.getElementById('mobileLocBtn'); if(__mlb) __mlb.style.display='none';

  const popup = e.popup;

  const marker = popup._source;

  const item = marker && marker.itemData;

  if(!item) return;

  const sid = String(item.순번);

  loadRating(sid);

  // 로드뷰: 약간 딜레이 후 DOM 안정되면 초기화

  setTimeout(()=> initRoadview("rv_" + sid, item.위도, item.경도, item.구분), 200);

  // 검색결과 패널 숨기기

  const panel = document.getElementById("mobileResultPanel");

  if(panel && panel.style.display !== "none"){

    panel._wasVisible = true;

    panel.style.display = "none";

  }

  // 모바일: 팝업이 실제로 화면 어디에 떴는지 측정해 정확히 중앙으로 panBy 보정
  if(isMobile()){

    // 팝업 DOM이 그려진 뒤 위치를 측정해야 하므로 약간의 딜레이를 둔다
    setTimeout(function(){

      const targetMap = (popup && popup._map) || window.mobileLeafletMap;
      if(!targetMap) return;

      const popupEl = popup.getElement ? popup.getElement() : null;
      if(!popupEl) return;

      const popupRect = popupEl.getBoundingClientRect();
      const mapEl = targetMap.getContainer();
      const mapRect = mapEl.getBoundingClientRect();

      // 팝업 높이가 0이면 아직 렌더링 전 — 한 번 더 시도
      if(popupRect.height < 10){
        setTimeout(function(){
          const r2 = popupEl.getBoundingClientRect();
          const m2 = mapEl.getBoundingClientRect();
          if(r2.height < 10) return;
          const popupCenterY = (r2.top + r2.bottom) / 2 - m2.top;
          const mapCenterY = m2.height / 2;
          const offsetY = popupCenterY - mapCenterY;
          if(Math.abs(offsetY) > 5){
            targetMap.panBy([0, offsetY], {animate: true, duration: 0.35});
          }
        }, 200);
        return;
      }

      // 팝업의 세로 중심이 지도 컨테이너의 세로 중심에 오도록 지도 패닝
      const popupCenterY = (popupRect.top + popupRect.bottom) / 2 - mapRect.top;
      const mapCenterY = mapRect.height / 2;
      const offsetY = popupCenterY - mapCenterY;

      if(Math.abs(offsetY) > 5){
        targetMap.panBy([0, offsetY], {animate: true, duration: 0.35});
      }

    }, 150);

  }

  window._skipPopupAutoPan = false;

}



function onPopupClose(e){

  var __mlb=document.getElementById('mobileLocBtn'); if(__mlb) __mlb.style.display='flex';

  // 팝업 닫히면 결과 패널 복원

  const panel = document.getElementById("mobileResultPanel");

  if(panel && panel._wasVisible){

    panel.style.display = "flex";

    panel._wasVisible = false;

  }

}



map.on("popupopen", onPopupOpen);

map.on("popupclose", onPopupClose);



// 별점 렌더 함수

function renderStars(sid, myScore, avgScore, count){

  const avg = document.getElementById("avg_"+sid);

  if(avg && count>0) avg.textContent = `${avgScore.toFixed(1)}점 (${count}명)`;

  else if(avg) avg.textContent = "아직 평가없음";

}



async function loadRating(sid){

  try{

    const res = await fetch("/api/rating?"+spotQuery(sid));

    const d = await res.json();

    const myScore = parseInt(localStorage.getItem(spotKey(sid))||"0");

    renderStars(sid, myScore, d.avg||0, d.count||0);

  }catch(e){}

}



// 별점 모달

let _ratingModalSid = null;

let _ratingSelected = 0;



function openRatingModal(sid){

  _ratingModalSid = sid;

  _ratingSelected = parseInt(localStorage.getItem(spotKey(sid))||"0");

  renderRatingStars(_ratingSelected);

  document.getElementById("ratingModal").style.display = "flex";

}



function closeRatingModal(){

  document.getElementById("ratingModal").style.display = "none";

  _ratingModalSid = null;

  _ratingSelected = 0;

}



function selectRatingStar(n){

  _ratingSelected = n;

  renderRatingStars(n);

}



function renderRatingStars(n){

  const row = document.getElementById("ratingStarRow");

  if(!row) return;

  row.querySelectorAll("span").forEach(s=>{

    const sn = parseInt(s.dataset.n);

    s.textContent = sn <= n ? "★" : "☆";

    s.style.color = sn <= n ? "#f59e0b" : "#cbd5e1";

  });

}



async function submitRating(){

  if(!_ratingModalSid){ closeRatingModal(); return; }

  if(_ratingSelected < 1){ alert("별점을 선택해주세요."); return; }

  const sid = _ratingModalSid;

  const score = _ratingSelected;

  closeRatingModal();

  try{

    const res = await fetch("/api/rating", {

      method:"POST",

      headers:{"Content-Type":"application/json"},

      body: JSON.stringify(Object.assign(spotBody(sid), {score: score}))

    });

    const d = await res.json();

    if(d.ok){

      localStorage.setItem(spotKey(sid), score);

      await loadRating(sid);

    } else {

      alert("별점 저장에 실패했습니다. 잠시 후 다시 시도해주세요.");

    }

  }catch(e){

    alert("네트워크 오류로 별점 저장에 실패했습니다.");

  }

}



// 코멘트 모달

function openComments(sid){

  const modal = document.getElementById("commentModal");

  if(!modal) return;

  modal.dataset.sid = sid;

  modal.style.display = "flex";

  loadComments(sid);

}



function closeComments(){

  const modal = document.getElementById("commentModal");

  if(modal) modal.style.display = "none";

}



async function loadComments(sid){

  const list = document.getElementById("commentList");

  if(!list) return;

  list.innerHTML = '<div style="color:#94a3b8;font-size:13px;padding:10px;">불러오는 중...</div>';

  try{

    const res = await fetch("/api/comments?"+spotQuery(sid));

    const d = await res.json();

    if(!d.comments || d.comments.length===0){

      list.innerHTML='<div style="color:#94a3b8;font-size:13px;padding:10px;">아직 코멘트가 없습니다.</div>';

      return;

    }

    list.innerHTML = d.comments.map(c=>`

      <div style="padding:10px 0;border-bottom:1px solid #f1f5f9;">

        <div style="font-size:13px;color:#1e293b;">${escapeHtml(c.content)}</div>

        <div style="font-size:11px;color:#94a3b8;margin-top:3px;">${c.created_at ? c.created_at.slice(0,16).replace("T"," ") : ""}</div>

      </div>

    `).join("");

  }catch(e){

    list.innerHTML='<div style="color:#ef4444;font-size:13px;padding:10px;">로드 실패</div>';

  }

}



async function submitComment(){

  const modal = document.getElementById("commentModal");

  const input = document.getElementById("commentInput");

  if(!modal||!input) return;

  const sid = modal.dataset.sid;

  const content = input.value.trim();

  if(!content){ alert("내용을 입력하세요."); return; }

  try{

    const res = await fetch("/api/comments", {
      method:"POST",
      headers:{"Content-Type":"application/json"},
      body: JSON.stringify(Object.assign(spotBody(sid), {content: content}))
    });
    const d = await res.json().catch(function(){ return {}; });
    if(!d.ok){ alert("저장 실패"); return; }
    input.value = "";

    loadComments(sid);

  }catch(e){ alert("저장 실패"); }

}



// ===== 11번: 지도 회전 (CSS transform 방식, 플러그인 불필요) =====

let mapRotation = 0;



function resetMapBearing(){

  mapRotation = 0;

  applyMapRotation();

}



function resetMobileMapBearing(){

  mapRotation = 0;

  applyMapRotation();

}



function applyMapRotation(){

  // PC 지도

  const mapPane = document.querySelector("#map .leaflet-map-pane");

  if(mapPane) mapPane.style.transform = `rotate(${mapRotation}deg)`;

  const mapEl = document.getElementById("map");

  if(mapEl) mapEl.style.transform = `rotate(0deg)`; // 외부는 고정



  // 나침반 버튼 반대 회전 표시

  const btn = document.getElementById("compassBtn");

  if(btn) btn.style.transform = `rotate(${-mapRotation}deg)`;

  const mBtn = document.getElementById("mobileCompassBtn");

  if(mBtn) mBtn.style.transform = `rotate(${-mapRotation}deg)`;



  // 모바일 지도

  const mMapPane = document.querySelector("#mobileMap .leaflet-map-pane");

  if(mMapPane) mMapPane.style.transform = `rotate(${mapRotation}deg)`;

}



// 두 손가락 회전 제스처 (모바일 전용)

(function setupRotateGesture(){

  // 모바일이 아니면 등록하지 않음

  if(!('ontouchstart' in window) && !navigator.maxTouchPoints) return;



  let startAngle = null;

  let startRotation = 0;



  function getAngle(t1, t2){

    return Math.atan2(t2.clientY - t1.clientY, t2.clientX - t1.clientX) * 180 / Math.PI;

  }



  function onTouchStart(e){

    if(e.touches.length === 2){

      startAngle = getAngle(e.touches[0], e.touches[1]);

      startRotation = mapRotation;

    }

  }



  function onTouchMove(e){

    if(e.touches.length === 2 && startAngle !== null){

      const angle = getAngle(e.touches[0], e.touches[1]);

      mapRotation = startRotation + (angle - startAngle);

      applyMapRotation();

    }

  }



  function onTouchEnd(e){

    if(e.touches.length < 2) startAngle = null;

  }



  ["map","mobileMap"].forEach(id => {

    const el = document.getElementById(id);

    if(!el) return;

    el.addEventListener("touchstart", onTouchStart, {passive:true});

    el.addEventListener("touchmove",  onTouchMove,  {passive:true});

    el.addEventListener("touchend",   onTouchEnd,   {passive:true});

  });

})();



/* ===== 시설 추가 정보 (화장실·주차장·AED·교통사고) ===== */
function timeRangeOpen(s){
  // "09:00~18:00" · "0900-1800" · "09:00∼18:00" · "9시~18시" 등이 지금 열려 있는지: true / false / null(판단 불가)
  if(!s) return null;
  const t = String(s).replace(/\s/g, "").replace(/[∼～〜–—]/g, "~");
  if(/상시|24시간|연중무휴|0?0:?00[~\-]24:?00/.test(t)) return true;
  let m = t.match(/(\d{1,2}):?(\d{2})[~\-](\d{1,2}):?(\d{2})/);
  if(!m){
    const k = t.match(/(\d{1,2})시(?:(\d{1,2})분)?[~\-](\d{1,2})시(?:(\d{1,2})분)?/);
    if(!k) return null;
    m = [k[0], k[1], k[2] || "0", k[3], k[4] || "0"];
  }
  const a = (+m[1]) * 60 + (+m[2]);
  let b = (+m[3]) * 60 + (+m[4]);
  if(a > 24 * 60 || b > 24 * 60) return null;
  if(b === 23 * 60 + 59) b = 24 * 60;            // 23:59 = 하루 끝까지
  const d = new Date();
  const n = d.getHours() * 60 + d.getMinutes();
  if(a === b) return null;                         // 00:00~00:00 등은 24시간인지 미운영인지 알 수 없음
  return a < b ? (n >= a && n < b) : (n >= a || n < b);   // 자정 넘는 시간대
}
// 예전 이름 호환
function toiletOpenState(s){ return timeRangeOpen(s); }

function openBadge(st){
  if(st === true) return '<span style="background:#dcfce7;color:#166534;border-radius:6px;padding:1px 6px;font-weight:700;margin-left:4px;">지금 이용 가능</span>';
  if(st === false) return '<span style="background:#fee2e2;color:#991b1b;border-radius:6px;padding:1px 6px;font-weight:700;margin-left:4px;">지금 이용 불가</span>';
  return "";
}

/* 주차장: 오늘 요일에 맞는 운영시간 (일요일=공휴일 시간 사용, 법정공휴일은 구분 못 함) */
function parkingTodayRange(item){
  const day = new Date().getDay();   // 0=일
  if(day === 0) return item.운영공휴일 || "";   // 일요일은 공휴일 시간
  if(day === 6) return item.운영토요일 || "";
  return item.운영평일 || "";
}

/* AED: 오늘 사용시간 (사용시간 = 월~일 7칸, 일요일사용 = 1~5주 Y/N) */
function aedTodayRange(item){
  const parts = String(item.사용시간 || "").split(",");
  if(parts.length < 7) return "";
  const day = new Date().getDay();
  const idx = day === 0 ? 6 : day - 1;
  return parts[idx] || "";
}
function aedOpenNow(item){
  const day = new Date().getDay();
  if(day === 0 && item.일요일사용){
    const w = Math.ceil(new Date().getDate() / 7);   // 몇째 일요일
    const flag = String(item.일요일사용).charAt(w - 1);
    if(flag === "N") return false;
  }
  return timeRangeOpen(aedTodayRange(item));
}

/* 화장실 자료 마지막 수정 연월. 2년 넘으면 주황색 (현장 확인 필요) */
function srUpdChip(u){
  if(!u || !/^\d{4}-\d{2}/.test(u)) return "";
  const y = +u.slice(0,4), m = +u.slice(5,7), now = new Date();
  const old = (now.getFullYear() - y) * 12 + (now.getMonth() + 1 - m) >= 24;
  return `<span class="sr-upd${old ? " old" : ""}" title="이 정보를 관리기관이 마지막으로 고친(기준으로 삼은) 때">${y}.${String(m).padStart(2,"0")} 자료</span>`;
}

function infoLine(html){
  return `<div class="popup-meta" style="margin-top:2px;">${html}</div>`;
}

function facilityInfoHtml(item){
  if(!window.FEATURE_DETAIL) return "";   // 관리자 페이지에서 OFF 이면 예전 팝업 그대로
  const g = item.구분;
  if(g === "공중화장실"){
    const hr = String(item.개방시간 || "").trim();
    const HR = {"상시": "상시 개방 (24시간)", "정시": "정해진 시간에 개방", "불규칙": "개방 시간 불규칙", "미개방": "개방 안 함"};
    const extra = [];
    if(item.비상벨 === "Y") extra.push("🔔 비상벨 있음");
    if(item.장애인화장실 === "Y") extra.push("♿ 장애인 화장실 있음");
    return infoLine(`개방: ${hr ? escapeHtml(HR[hr] || hr) : "정보 없음"}${hr === "미개방" ? openBadge(false) : openBadge(timeRangeOpen(hr))}${extra.length ? "<br>" + extra.join(" · ") : ""}`);
  }
  if(g === "공영주차장" || g === "민영주차장"){
    if(!item.요금 && !item.운영평일 && !item.운영토요일 && !item.운영공휴일) return "";
    const fee = item.요금 ? escapeHtml(item.요금) + ((item.요금상세 && /[1-9]/.test(String(item.요금상세).replace(/[0-9]+분/g, ""))) ? ` (${escapeHtml(item.요금상세)})` : "") : "요금 정보 없음";
    const today = parkingTodayRange(item);
    const rows = [];
    if(item.운영평일) rows.push("평일 " + escapeHtml(item.운영평일));
    if(item.운영토요일) rows.push("토 " + escapeHtml(item.운영토요일));
    if(item.운영공휴일) rows.push("일·공휴일 " + escapeHtml(item.운영공휴일));
    return infoLine(`요금: ${fee}<br>운영: ${rows.length ? rows.join(" · ") : "정보 없음"}${openBadge(parkOpenNow(item))}`);
  }
  if(g === "자동심장충격기"){
    if(!item.설치장소 && !item.사용시간) return "";
    const place = item.설치장소 ? "설치 위치: " + escapeHtml(item.설치장소) : "";
    const today = aedTodayRange(item);
    const use = item.사용시간 ? `오늘 사용시간: ${today ? escapeHtml(today) : "정보 없음"}${openBadge(aedOpenNow(item))}` : "";
    return infoLine([place, use].filter(Boolean).join("<br>"));
  }
  if(g === "교통사고위험지역"){
    const n = +item.사고건수 || 0;
    if(!n) return "";
    const pill = (t, bg, fg) => `<span style="display:inline-flex;align-items:center;height:22px;padding:0 9px;margin:2px 4px 2px 0;border-radius:999px;background:${bg};color:${fg};font-size:12px;font-weight:800;white-space:nowrap;">${t}</span>`;
    const pills = [pill(`사고 ${n}건`, "#f1f5f9", "#334155")];
    pills.push(+item.중상이상 ? pill(`중상 이상 ${+item.중상이상}`, "#fee2e2", "#b91c1c") : pill("경상", "#ecfdf5", "#047857"));
    if(+item.보행자사고) pills.push(pill(`보행자 ${+item.보행자사고}`, "#fff7ed", "#c2410c"));
    if(+item.야간사고) pills.push(pill(`야간 ${+item.야간사고}`, "#eef2ff", "#4338ca"));
    return `<div class="popup-meta" style="margin-top:4px;display:flex;flex-wrap:wrap;">${pills.join("")}</div>`;
  }
  return "";
}

/* 내 주변 찾기 조건 */
function fchk(id){
  const el = document.getElementById(id);
  return !!(el && el.checked);
}

function fval(name){
  const el = document.querySelector('input[name="' + name + '"]:checked');
  return el ? el.value : "";
}
function isAllDay(r){
  const t = String(r || "").replace(/\s/g, "");
  return /^0?0:?00[~\-](24:?00|23:?59)$/.test(t);
}
/* 주차장: 오늘 운영 여부 (00:00~00:00 은 그날 운영 안 함) */
function parkOpenNow(item){
  const r = String(parkingTodayRange(item) || "").replace(/\s/g, "");
  if(/^0?0:?00[~\-]0?0:?00$/.test(r)) return false;
  return timeRangeOpen(r);
}
function aedAllDay(item){
  const parts = String(item.사용시간 || "").split(",");
  return parts.length >= 7 && parts.slice(0, 7).every(isAllDay);
}
function facilityFilterActive(targetType){
  if(!window.FEATURE_DETAIL) return false;
  if(targetType === "공중화장실") return !!fval("fab_toilet_open");
  if(targetType === "주차장") return !!(fval("fab_park_fee") || fval("fab_park_open"));
  if(targetType === "자동심장충격기") return !!fval("fab_aed_use");
  if(targetType === "위험지역") return !!(fval("fab_risk_kind") || fchk("fabAccWalk") || fchk("fabAccNight") || fchk("fabAccSevere"));
  return false;
}
function facilityFilterPass(item, targetType){
  if(!window.FEATURE_DETAIL) return true;
  const g = item.구분;
  if(targetType === "공중화장실"){
    const v = fval("fab_toilet_open");
    if(v && String(item.개방시간 || "").indexOf(v) < 0) return false;
  }
  if(targetType === "주차장"){
    const fee = fval("fab_park_fee"), op = fval("fab_park_open");
    if(fee && item.요금 !== fee) return false;
    if(op === "now" && parkOpenNow(item) !== true) return false;
    if(op === "24" && !isAllDay(parkingTodayRange(item))) return false;
  }
  if(targetType === "자동심장충격기"){
    const u = fval("fab_aed_use");
    if(u === "now" && aedOpenNow(item) !== true) return false;
    if(u === "24" && !aedAllDay(item)) return false;
  }
  if(targetType === "위험지역"){
    const k = fval("fab_risk_kind");
    const acc = fchk("fabAccWalk") || fchk("fabAccNight") || fchk("fabAccSevere");
    if(k && g !== k) return false;
    if(acc){
      if(g !== "교통사고위험지역") return false;
      if(fchk("fabAccWalk") && !(+item.보행자사고 > 0)) return false;
      if(fchk("fabAccNight") && !(+item.야간사고 > 0)) return false;
      if(fchk("fabAccSevere") && !(+item.중상이상 > 0)) return false;
    }
  }
  return true;
}
// 예전 이름 호환
function toiletFilterPass(item){ return facilityFilterPass(item, "공중화장실"); }

/* ===== 별점·코멘트 장소 식별 (구분 + 좌표) ===== */
function spotQuery(sid){
  const it = (window._popupItems || {})[sid];
  let q = "spot_id=" + encodeURIComponent(sid);
  if(it) q += "&gubun=" + encodeURIComponent(it.구분) + "&lat=" + it.위도 + "&lng=" + it.경도;
  return q;
}
function spotBody(sid){
  const it = (window._popupItems || {})[sid];
  return it ? {spot_id: sid, gubun: it.구분, lat: it.위도, lng: it.경도} : {spot_id: sid};
}
function spotKey(sid){
  // 내가 준 별점 기억용 (순번이 바뀌어도 유지되도록 좌표 기준)
  const it = (window._popupItems || {})[sid];
  return it ? "rating_" + it.구분 + "_" + Number(it.위도).toFixed(4) + "_" + Number(it.경도).toFixed(4) : "rating_" + sid;
}

function debounce(fn, delay){



  let timer;



  return function(...args){



    clearTimeout(timer);



    timer = setTimeout(()=>{

      fn.apply(this, args);

    }, delay);



  };



}



// 관리자 페이지에서 이동 시 해당 지점 로드뷰 팝업 자동 열기

window.addEventListener("load", function(){

  const params = new URLSearchParams(window.location.search);

  const gotoSpot = params.get("goto_spot");

  const gotoLat = parseFloat(params.get("lat"));

  const gotoLng = parseFloat(params.get("lng"));

  if(gotoSpot && !isNaN(gotoLat) && !isNaN(gotoLng)){

    // 데이터 로드 완료 후 이동하는 함수

    async function doGotoSpot(){

      if(!ALL_DATA_CACHE){

        const res = await fetch("/data/all");

        const result = await res.json();

        ALL_DATA_CACHE = result.data || [];

      }

      // 순번은 엑셀 갱신 때 바뀌므로 좌표로 가장 가까운 장소(30m 이내)를 찾음
      let found = null, best = 30;
      const gotoGubun = params.get("gubun") || "";
      ALL_DATA_CACHE.forEach(d => {
        if(gotoGubun && d.구분 !== gotoGubun) return;   // 같은 좌표에 여러 시설이 있을 때 구분으로 가림
        const dist = map.distance([gotoLat, gotoLng], [d.위도, d.경도]);
        if(dist <= best){ best = dist; found = d; }
      });

      if(!found){

        alert("해당 지점을 데이터에서 찾을 수 없습니다. (지점번호: " + gotoSpot + ")");

        return;

      }

      const targetLat = found.위도;

      const targetLng = found.경도;



      // 클러스터 그룹에서 해당 마커를 찾아 팝업을 여는 함수
      // markerClusterGroup은 eachLayer가 클러스터 객체를 포함하므로
      // getAllChildMarkers로 실제 마커를 직접 탐색한다

      function openMarkerPopup(mGroup){

        let targetMarker = null;

        mGroup.eachLayer(function(layer){

          // 클러스터면 자식 마커 탐색
          if(layer.getAllChildMarkers){

            layer.getAllChildMarkers().forEach(function(child){

              if(child.itemData && String(child.itemData.순번) === String(found.순번)){

                targetMarker = child;

              }

            });

          }

          // 일반 마커인 경우
          if(layer.itemData && String(layer.itemData.순번) === String(found.순번)){

            targetMarker = layer;

          }

        });

        if(targetMarker){

          // zoomToShowLayer: 클러스터가 펼쳐지면서 팝업 오픈
          mGroup.zoomToShowLayer(targetMarker, function(){

            targetMarker.openPopup();

          });

        }

      }



      if(isMobile()){

        openMobileMap();

        // 모바일 지도에 전체 마커가 없으면 먼저 로드

        const needsLoad = !window.mobileMarkerGroup ||

          window.mobileMarkerGroup.getLayers().length === 0;

        async function doMobileGoto(){

          if(needsLoad){

            // 전체 데이터를 모바일 마커 그룹에 로드

            ALL_DATA_CACHE.forEach(item=>{

              const icon = buildMarkerIcon(item.마커색상);

              const marker = L.marker([item.위도, item.경도], {icon});

              marker.itemData = item;

              marker.bindPopup(buildPopupHtml(item), {maxWidth: isMobile() ? 310 : 650});

              window.mobileMarkerGroup.addLayer(marker);

            });

          }

          setTimeout(()=>{

            if(isMobile() && window.mobileLeafletMap){

              window.mobileLeafletMap.flyTo([targetLat, targetLng], 17);

              window.mobileLeafletMap.once("moveend", function(){

                if(window.mobileMarkerGroup) openMarkerPopup(window.mobileMarkerGroup);

              });

            }

          }, 400);

        }

        setTimeout(doMobileGoto, 600);

      } else {

        // PC: markerGroup에 마커가 없으면 전체 마커를 먼저 추가

        if(markerGroup.getLayers().length === 0){

          ALL_DATA_CACHE.forEach(item=>{

            const icon = buildMarkerIcon(item.마커색상);

            const marker = L.marker([item.위도, item.경도], {icon});

            marker.itemData = item;

            marker.bindPopup(buildPopupHtml(item), {maxWidth: 650});

            markerGroup.addLayer(marker);

          });

        }

        map.flyTo([targetLat, targetLng], 17);

        map.once("moveend", function(){

          openMarkerPopup(markerGroup);

        });

      }

    }



    // loadAllMarkers 완료 후 실행되도록 충분히 기다림

    setTimeout(doGotoSpot, 2000);

  }

});



</script>{% endraw %}







<div class="mobile-map-popup" id="mobileMapPopup">



  <div class="mobile-map-header">

  <button class="mobile-map-close" onclick="goHome()">

  홈으로

  </button>

  <span style="font-size:15px;font-weight:700;">지도 보기</span>

  <div style="width:70px;"></div>

</div>



  <div id="mobileMap" class="mobile-map"></div>

  <button id="mobileLocBtn"><svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#ffffff" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3"/><circle cx="12" cy="12" r="7" stroke-dasharray="2 2"/></svg></button>



  <!-- 알약형 카테고리 필터 -->

  <div class="mobile-pill-bar" id="mobilePillBar" style="top:62px;left:8px;right:8px;transform:none;justify-content:flex-start;gap:5px;">

    <button class="mobile-pill active" id="pill_all"

      style="border-color:#475569;color:#1a202c;"

      onclick="mobilePillFilter('전체')">

      <svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="#475569" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>

      전체

    </button>

    <button class="mobile-pill" id="pill_ice"

      style="color:#1a202c;"

      onclick="mobilePillFilter('상습결빙지역')">

      <svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="#06b6d4" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2v20M4.93 4.93l14.14 14.14M2 12h20M4.93 19.07l14.14-14.14"/><circle cx="12" cy="12" r="3"/></svg>

      상습결빙지역

    </button>

    <button class="mobile-pill" id="pill_toilet"

      style="color:#1a202c;"

      onclick="mobilePillFilter('공중화장실')">

      <svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="#f59e0b" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M9 2h6v2H9zM12 4v4M9 8H5a1 1 0 0 0-1 1v10a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1V9a1 1 0 0 0-1-1h-4"/><path d="M10 12v4M14 12v4"/></svg>

      공중화장실

    </button>

    <button class="mobile-pill" id="pill_accident"

      style="color:#1a202c;"

      onclick="mobilePillFilter('교통사고위험지역')">

      <svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="#ef4444" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>

      교통사고위험지역

    </button>

    <button class="mobile-pill" id="pill_parking"

      style="color:#1a202c;"

      onclick="mobilePillFilter('주차장')">

      <svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="#8b5cf6" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2"/><path d="M9 17V7h4a3 3 0 0 1 0 6H9"/></svg>

      주차장

    </button>

  </div>



  <div class="map-legend">





    <div class="map-legend-item">

      <span class="map-legend-dot" style="background:#06b6d4"></span>

      상습결빙지역

    </div>



    <div class="map-legend-item">

      <span class="map-legend-dot" style="background:#f59e0b"></span>

      공중화장실

    </div>



<div class="map-legend-item">

  <span class="map-legend-dot" style="background:#ef4444"></span>

  교통사고위험지역

</div>

<div class="map-legend-item">

  <span class="map-legend-dot" style="background:#8b5cf6"></span>

  주차장

</div>



<div class="map-legend-item">

  <span class="map-legend-dot" style="background:#2563eb"></span>

  내 위치

</div>





  </div>



</div>







<div id="msgModal" style="

position:fixed;

inset:0;

background:rgba(0,0,0,0.45);

display:none;

align-items:center;

justify-content:center;

z-index:5000;

">



<div id="msgBox" style="

background:#ffffff;

padding:24px 22px;

border-radius:18px;

min-width:320px;

max-width:90vw;

text-align:center;

box-shadow:0 18px 40px rgba(0,0,0,0.18);

">



{% if detail_on %}<div class="sr-msg-head" id="srMsgHead"><div class="t" id="srMsgTitle"></div><div class="s" id="srMsgSub"></div></div>{% endif %}
<div id="msgText" style="

font-size:15px;

margin-bottom:18px;

line-height:1.6;

white-space:pre-line;

color:#0f172a;

font-weight:600;

word-break:keep-all;

"></div>



<button id="msgBtn" onclick="closeMsg()" style="

background:#2563eb;

border:none;

color:white;

padding:8px 16px;

border-radius:8px;

font-weight:700;

cursor:pointer;

">

확인

</button>



</div>

</div>



<div id="facilityFabMenu" onclick="if(event.target===this) closeFacilityFab();" style="
position:fixed;inset:0;background:rgba(0,0,0,.5);
display:none;align-items:center;justify-content:center;z-index:6000;
backdrop-filter:blur(4px);">
<div style="background:#fff;border-radius:18px;width:340px;max-width:94vw;overflow:hidden;box-shadow:0 20px 60px rgba(0,0,0,.25);">
  <div style="background:#0f172a;padding:18px 20px 14px;">
    <div style="font-size:15px;font-weight:900;color:#f8fafc;margin-bottom:2px;">내 주변에서 찾기</div>
    <div style="font-size:12px;color:#64748b;">찾을 시설을 선택하세요</div>
  </div>
  <div style="padding:16px 20px 18px;">
{% if detail_on %}
    <style>
      .fgrid{display:grid;grid-template-columns:1fr 1fr;column-gap:8px;row-gap:0;}
      .fbtn{position:relative;display:flex;align-items:center;justify-content:center;gap:6px;height:50px;margin-bottom:8px;border:1.5px solid #e2e8f0;border-radius:14px;background:#fff;font-size:13px;font-weight:800;color:#374151;cursor:pointer;font-family:inherit;padding:0 22px 0 10px;line-height:1.2;transition:background .15s,border-color .15s,color .15s;}
      .fbtn .fdot{width:9px;height:9px;border-radius:50%;background:var(--fc);flex-shrink:0;}
      .fbtn .fchev{position:absolute;right:9px;color:#94a3b8;transition:transform .25s;}
      .fbtn.on{border-color:var(--fc);background:color-mix(in srgb,var(--fc) 9%,#fff);color:#111827;}
      .fbtn.on .fchev{transform:rotate(180deg);color:var(--fc);}
      .fpanel{grid-column:1/-1;display:grid;grid-template-rows:0fr;transition:grid-template-rows .28s ease;}
      .fpanel.open{grid-template-rows:1fr;}
      .fpanel-in{overflow:hidden;min-height:0;}
      .fpanel-box{margin-bottom:8px;padding:12px;border-radius:14px;background:#f6f7fb;border:1px solid #eceef3;}
      .fpanel-t{font-size:12.5px;font-weight:800;color:#111827;margin-bottom:8px;}
      .fpanel-t span{font-weight:600;color:#94a3b8;}
      .fgroup{display:none;flex-wrap:wrap;gap:6px;}
      .fgroup.on{display:flex;}
      .fchip input{position:absolute;opacity:0;pointer-events:none;}
      .fchip span{display:inline-flex;align-items:center;height:32px;padding:0 12px;white-space:nowrap;border:1.5px solid #e2e8f0;border-radius:999px;background:#fff;font-size:12.5px;font-weight:700;color:#475569;cursor:pointer;user-select:none;transition:background .15s,border-color .15s,color .15s;}
      .fchip input:checked + span{color:#fff;}
      .fchip input:checked + span:before{content:"✓";margin-right:4px;font-weight:900;}
      .fc-toilet input:checked + span{background:#f59e0b;border-color:#f59e0b;}
      .fc-park input:checked + span{background:#8b5cf6;border-color:#8b5cf6;}
      .fc-aed input:checked + span{background:#16a34a;border-color:#16a34a;}
      .fc-acc input:checked + span{background:#ef4444;border-color:#ef4444;}
      .fgroup{flex-direction:column;gap:10px;}
      .frow-t{font-size:11.5px;font-weight:700;color:#64748b;margin-bottom:5px;}
      .frow-t span{font-weight:500;color:#94a3b8;}
      .fseg{display:flex;gap:3px;padding:3px;background:#fff;border:1px solid #e2e8f0;border-radius:11px;}
      .fseg label{flex:1;min-width:0;}
      .fseg input{position:absolute;opacity:0;pointer-events:none;}
      .fseg span{display:flex;align-items:center;justify-content:center;height:32px;padding:0 4px;border-radius:8px;font-size:12.5px;font-weight:700;color:#64748b;white-space:nowrap;cursor:pointer;user-select:none;transition:background .15s,color .15s;}
      .fseg input:checked + span{background:var(--fc);color:#fff;}
      .fchips{display:flex;flex-wrap:wrap;gap:6px;}
      .fgo{width:100%;height:44px;margin-top:12px;border:none;border-radius:12px!important;background:linear-gradient(135deg,#2563eb,#3b82f6);color:#fff;font-size:14px;font-weight:800;cursor:pointer;font-family:inherit;box-shadow:0 4px 14px rgba(37,99,235,.3);}
    </style>
    <div class="fgrid" id="fGrid">
      <button type="button" class="fbtn" data-t="공중화장실" data-g="toilet" style="--fc:#f59e0b;" onclick="fabPick(this)"><span class="fdot"></span><span class="flabel">화장실</span><svg class="fchev" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M6 9l6 6 6-6"/></svg></button>
      <button type="button" class="fbtn" data-t="주차장" data-g="park" style="--fc:#8b5cf6;" onclick="fabPick(this)"><span class="fdot"></span><span class="flabel">주차장</span><svg class="fchev" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M6 9l6 6 6-6"/></svg></button>
      <button type="button" class="fbtn" data-t="위험지역" data-g="acc" style="--fc:#ef4444;" onclick="fabPick(this)"><span class="fdot"></span><span class="flabel">위험지역</span><svg class="fchev" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M6 9l6 6 6-6"/></svg></button>
      <button type="button" class="fbtn" data-t="자동심장충격기" data-g="aed" style="--fc:#16a34a;" onclick="fabPick(this)"><span class="fdot"></span><span class="flabel">자동심장충격기(AED)</span><svg class="fchev" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M6 9l6 6 6-6"/></svg></button>
      <div class="fpanel" id="fPanel"><div class="fpanel-in"><div class="fpanel-box">
        <div class="fpanel-t">조건 <span>(안 골라도 돼요)</span></div>
        <div class="fgroup" data-g="toilet">
          <div class="frow"><div class="frow-t">개방</div><div class="fseg" style="--fc:#f59e0b;"><label><input type="radio" name="fab_toilet_open" value="" checked><span>전체</span></label><label><input type="radio" name="fab_toilet_open" value="상시"><span>상시 개방</span></label><label><input type="radio" name="fab_toilet_open" value="정시"><span>정시 개방</span></label></div></div>
        </div>
        <div class="fgroup" data-g="park">
          <div class="frow"><div class="frow-t">요금</div><div class="fseg" style="--fc:#8b5cf6;"><label><input type="radio" name="fab_park_fee" value="" checked><span>전체</span></label><label><input type="radio" name="fab_park_fee" value="무료"><span>무료</span></label><label><input type="radio" name="fab_park_fee" value="유료"><span>유료</span></label><label><input type="radio" name="fab_park_fee" value="혼합"><span>혼합</span></label></div></div>
          <div class="frow"><div class="frow-t">운영</div><div class="fseg" style="--fc:#8b5cf6;"><label><input type="radio" name="fab_park_open" value="" checked><span>전체</span></label><label><input type="radio" name="fab_park_open" value="now"><span>지금 운영 중</span></label><label><input type="radio" name="fab_park_open" value="24"><span>24시간</span></label></div></div>
        </div>
        <div class="fgroup" data-g="acc">
          <div class="frow"><div class="frow-t">종류</div><div class="fseg" style="--fc:#ef4444;"><label><input type="radio" name="fab_risk_kind" value="" checked><span>전체</span></label><label><input type="radio" name="fab_risk_kind" value="상습결빙지역"><span>결빙</span></label><label><input type="radio" name="fab_risk_kind" value="교통사고위험지역"><span>교통사고</span></label></div></div>
          <div class="frow" id="fAccRow"><div class="frow-t">교통사고 유형 <span>(여러 개 가능)</span></div><div class="fchips"><label class="fchip fc-acc"><input type="checkbox" id="fabAccWalk"><span>보행자</span></label><label class="fchip fc-acc"><input type="checkbox" id="fabAccNight"><span>야간</span></label><label class="fchip fc-acc"><input type="checkbox" id="fabAccSevere"><span>중상 이상</span></label></div></div>
        </div>
        <div class="fgroup" data-g="aed">
          <div class="frow"><div class="frow-t">사용</div><div class="fseg" style="--fc:#16a34a;"><label><input type="radio" name="fab_aed_use" value="" checked><span>전체</span></label><label><input type="radio" name="fab_aed_use" value="now"><span>지금 사용 가능</span></label><label><input type="radio" name="fab_aed_use" value="24"><span>24시간</span></label></div></div>
        </div>
        <button type="button" class="fgo" onclick="fabGo()">확인</button>
      </div></div></div>
    </div>
    <script>
    (function(){
      var cur = null;
      function grid(){ return document.getElementById("fGrid"); }
      function panel(){ return document.getElementById("fPanel"); }
      function place(btn){
        var btns = Array.prototype.slice.call(grid().querySelectorAll(".fbtn"));
        var idx = btns.indexOf(btn);
        var after = btns[idx < 2 ? 1 : 3];
        after.parentNode.insertBefore(panel(), after.nextSibling);
      }
      function show(btn){
        grid().querySelectorAll(".fbtn").forEach(function(b){ b.classList.toggle("on", b === btn); });
        panel().querySelectorAll(".fgroup").forEach(function(g){ g.classList.toggle("on", g.dataset.g === btn.dataset.g); });
        place(btn);
        void panel().offsetHeight;
        panel().classList.add("open");
        cur = btn;
      }
      function collapse(){
        panel().classList.remove("open");
        grid().querySelectorAll(".fbtn").forEach(function(b){ b.classList.remove("on"); });
        cur = null;
      }
      window.fabPick = function(btn){
        if(cur === btn){ collapse(); return; }
        var sameRow = cur && (Array.prototype.indexOf.call(grid().querySelectorAll(".fbtn"), cur) < 2) === (Array.prototype.indexOf.call(grid().querySelectorAll(".fbtn"), btn) < 2);
        if(cur && !sameRow){ panel().classList.remove("open"); setTimeout(function(){ show(btn); }, 260); }
        else show(btn);
      };
      document.querySelectorAll("#fAccRow input").forEach(function(c){
        c.addEventListener("change", function(){
          if(c.checked){ var r = document.querySelector('input[name="fab_risk_kind"][value="교통사고위험지역"]'); if(r) r.checked = true; }
        });
      });
      document.querySelectorAll('input[name="fab_risk_kind"]').forEach(function(r){
        r.addEventListener("change", function(){
          if(r.checked && r.value === "상습결빙지역") document.querySelectorAll("#fAccRow input").forEach(function(c){ c.checked = false; });
        });
      });
      window.fabGo = function(){ if(cur) findNearestFacility(cur.dataset.t); };
      var _close = window.closeFacilityFab;
      window.closeFacilityFab = function(){ _close.apply(this, arguments); collapse(); };
    })();
    </script>
    {% else %}
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:8px;">
      <button onclick="findNearestFacility('공중화장실')" style="display:flex;align-items:center;justify-content:center;gap:5px;height:48px;border:1.5px solid #e2e8f0;border-radius:10px;background:#fff;font-size:13px;font-weight:700;color:#374151;cursor:pointer;"><span style="width:9px;height:9px;border-radius:50%;background:#f59e0b;flex-shrink:0;"></span>화장실</button>
      <button onclick="findNearestFacility('주차장')" style="display:flex;align-items:center;justify-content:center;gap:5px;height:48px;border:1.5px solid #e2e8f0;border-radius:10px;background:#fff;font-size:13px;font-weight:700;color:#374151;cursor:pointer;"><span style="width:9px;height:9px;border-radius:50%;background:#8b5cf6;flex-shrink:0;"></span>주차장</button>
      <button onclick="findNearestFacility('위험지역')" style="display:flex;align-items:center;justify-content:center;gap:5px;height:48px;border:1.5px solid #e2e8f0;border-radius:10px;background:#fff;font-size:13px;font-weight:700;color:#374151;cursor:pointer;"><span style="width:9px;height:9px;border-radius:50%;background:#ef4444;flex-shrink:0;"></span>위험지역</button>
      <button onclick="findNearestFacility('자동심장충격기')" style="display:flex;align-items:center;justify-content:center;gap:5px;height:48px;border:1.5px solid #e2e8f0;border-radius:10px;background:#fff;font-size:12px;font-weight:700;color:#374151;cursor:pointer;line-height:1.2;text-align:center;padding:0 6px;"><span style="width:9px;height:9px;border-radius:50%;background:#16a34a;flex-shrink:0;"></span>자동심장충격기(AED)</button>
    </div>
    {% endif %}
    <button onclick="closeFacilityFab()" style="width:100%;height:42px;border:1.5px solid #e2e8f0;border-radius:10px;background:#fff;font-weight:700;font-size:14px;cursor:pointer;color:#475569;">취소</button>
  </div>
</div>
</div>



{% if detail_on %}
<script>
(function(){
  function srRefit(){
    var mobile = isMobile();
    var m = mobile ? window.mobileLeafletMap : (typeof map !== "undefined" ? map : null);
    var grp = mobile ? window.mobileMarkerGroup : (typeof markerGroup !== "undefined" ? markerGroup : null);
    if(!m || !grp) return;
    var b = L.latLngBounds([]);
    grp.eachLayer(function(l){ if(l.getLatLng && !(l instanceof L.CircleMarker)) b.extend(l.getLatLng()); });
    var line = mobile ? window.mobileRouteLine : (typeof routeLine !== "undefined" ? routeLine : null);
    if(line && m.hasLayer(line)) b.extend(line.getBounds());
    if(!b.isValid()) return;
    var panel = document.getElementById("mobileResultPanel");
    var shown = panel && panel.style.display !== "none" && panel.offsetHeight > 0;
    var opt = mobile
      ? {paddingTopLeft: [28, 140], paddingBottomRight: [28, (shown ? panel.offsetHeight : 0) + 24], maxZoom: 16}
      : {paddingTopLeft: [shown ? 400 : 60, 80], paddingBottomRight: [60, 60], maxZoom: 16};
    m.fitBounds(b, opt);
  }
  window.srRefit = srRefit;
  function wrap(name, mode, refit){
    var f = window[name];
    if(typeof f !== "function") return;
    window[name] = function(){
      window.srRef = null;
      window.srCutFrom = null;
      window.srLoadMode = mode;
      var r = f.apply(this, arguments);
      Promise.resolve(r).then(function(){ if(refit) setTimeout(srRefit, 450); }, function(){});
      return r;
    };
  }
  wrap("runAddressSearch", "search", true);
  wrap("runRouteSearch", "search", true);
  ["findNearestFacility", "findNearestToilet", "findNearestDanger", "loadData"].forEach(function(n){ wrap(n, "me", false); });
})();
</script>
{% endif %}
{% if detail_on %}
<style>
.sr-pcat{margin:2px 0 12px;}
.sr-pcat-t{font-size:12px;font-weight:700;color:#6b7280;margin-bottom:6px;}
.sr-pcat-row{display:grid;grid-template-columns:1fr 1fr;gap:6px;}
.sr-pcat label{position:relative;display:flex;align-items:center;gap:7px;height:38px;padding:0 10px;border:1.5px solid #e5e7eb;border-radius:11px;background:#fff;font-size:13px;font-weight:700;color:#9ca3af;cursor:pointer;user-select:none;transition:border-color .15s,background .15s,color .15s;}
.sr-pcat label input{position:absolute;opacity:0;pointer-events:none;}
.sr-pcat label i{width:9px;height:9px;border-radius:50%;flex-shrink:0;opacity:.35;}
.sr-pcat label:has(input:checked){border-color:#bfd2fb;background:#f5f8ff;color:#111827;}
.sr-pcat label:has(input:checked) i{opacity:1;}
</style>
<script>
(function(){
  var CATS = [["상습결빙지역","결빙","#06b6d4"],["공중화장실","화장실","#f59e0b"],["교통사고위험지역","교통사고","#ef4444"],["주차장","주차장","#8b5cf6"]];
  function addChips(popupId, which){
    var pop = document.getElementById(popupId); if(!pop) return;
    var body = pop.firstElementChild && pop.firstElementChild.children[1]; if(!body) return;
    var btnRow = body.lastElementChild;
    var box = document.createElement("div");
    box.className = "sr-pcat"; box.id = "srPcat_" + which;
    box.innerHTML = '<div class="sr-pcat-t">찾을 구분</div><div class="sr-pcat-row">' +
      CATS.map(function(c){ return '<label><input type="checkbox" value="' + c[0] + '" checked><i style="background:' + c[2] + '"></i>' + c[1] + '</label>'; }).join('') + '</div>';
    body.insertBefore(box, btnRow);
  }
  function init(){
    addChips("routePopup", "route");
    addChips("addrSearchPopup", "addr");
    var sub = document.querySelector("#addrSearchPopup > div > div:first-child > div:last-child");
    if(sub) sub.textContent = "주소 5km 안을 지도에, 가까운 30곳을 목록에 보여줘요";
  }
  if(document.readyState === "loading") document.addEventListener("DOMContentLoaded", init); else init();

  /* 뒤로가기: 열린 팝업만 닫기 (사이트를 떠나지 않게) */
  function shown(id){ var e = document.getElementById(id); return !!(e && getComputedStyle(e).display !== "none"); }
  var LAYERS = [
    {open: function(){ return !!document.querySelector(".sr-sheet.open"); }, close: function(){ var e = document.querySelector(".sr-sheet.open"); if(e) e.click(); }},
    {open: function(){ return shown("facilityFabMenu"); }, close: function(){ closeFacilityFab(); }},
    {open: function(){ return shown("routePopup"); },      close: function(){ closeRoutePopup(); }},
    {open: function(){ return shown("addrSearchPopup"); }, close: function(){ closeAddressSearch(); }},
    {open: function(){ return shown("adminPwModal"); },    close: function(){ closeAdminPwModal(); }},
    {open: function(){ return shown("msgModal"); },        close: function(){ closeMsg(); }},
    {open: function(){ return shown("mobileMapPopup"); },  close: function(){ closeMobileMap(); }}
  ];
  function anyOpen(){ return LAYERS.some(function(l){ try{ return l.open(); }catch(e){ return false; } }); }
  var guard = false, skip = false, closing = false;
  function ensureGuard(){
    if(guard) return;
    try{ history.pushState({srGuard: 1}, ""); guard = true; }catch(e){}
  }
  function afterClose(){
    if(closing) return;
    setTimeout(function(){
      if(guard && !anyOpen()){ guard = false; skip = true; history.back(); }
    }, 60);
  }
  window.addEventListener("popstate", function(){
    if(skip){ skip = false; return; }
    guard = false;
    for(var i = 0; i < LAYERS.length; i++){
      var l = LAYERS[i], isOpen = false;
      try{ isOpen = l.open(); }catch(e){}
      if(isOpen){ closing = true; try{ l.close(); }catch(e){} closing = false; break; }
    }
    if(anyOpen()) ensureGuard();
  });
  function wrapOpen(name){
    var f = window[name]; if(typeof f !== "function") return;
    window[name] = function(){ var r = f.apply(this, arguments); setTimeout(function(){ if(anyOpen()) ensureGuard(); }, 0); return r; };
  }
  function wrapClose(name){
    var f = window[name]; if(typeof f !== "function") return;
    window[name] = function(){ var r = f.apply(this, arguments); afterClose(); return r; };
  }
  ["openRouteSearch", "openAddressSearch", "toggleFacilityFab", "openAdminStats", "openMobileMap", "showMsg", "showLoadingLocation"].forEach(wrapOpen);
  ["closeRoutePopup", "closeAddressSearch", "closeFacilityFab", "closeAdminPwModal", "closeMobileMap", "closeMsg"].forEach(wrapClose);
  document.addEventListener("click", function(e){
    if(e.target.closest && e.target.closest(".sr-sel-hit")) setTimeout(function(){ if(anyOpen()) ensureGuard(); }, 0);
  }, true);

  /* 모바일: 결과 목록은 지도가 열려 있을 때만 (검색이 늦게 끝나도 첫 화면에 목록이 남지 않게) */
  function fixPanel(){
    if(!isMobile()) return;
    var panel = document.getElementById("mobileResultPanel");
    if(panel && panel.style.display !== "none" && !shown("mobileMapPopup")) panel.style.display = "none";
  }
  function watchPanel(){
    var panel = document.getElementById("mobileResultPanel");
    if(!panel) return;
    new MutationObserver(function(){ setTimeout(fixPanel, 0); }).observe(panel, {attributes: true, attributeFilter: ["style"]});
    var mm = document.getElementById("mobileMapPopup");
    if(mm) new MutationObserver(function(){ setTimeout(fixPanel, 0); }).observe(mm, {attributes: true, attributeFilter: ["style"]});
  }
  if(document.readyState === "loading") document.addEventListener("DOMContentLoaded", watchPanel); else watchPanel();
  /* '홈으로'는 페이지를 다시 불러오지 않고 지도만 닫기 (뒤로가기 기록이 쌓여 예전 화면이 나오는 것 방지) */
  var _goHome = window.goHome;
  if(typeof _goHome === "function"){
    window.goHome = function(){
      if(isMobile() && shown("mobileMapPopup")){ closeMobileMap(); window.scrollTo(0, 0); return; }
      return _goHome.apply(this, arguments);
    };
  }
  /* 뒤로가기로 예전 화면이 캐시에서 돌아온 경우 열린 창 정리 */
  window.addEventListener("pageshow", function(e){
    if(!e.persisted) return;
    LAYERS.slice().reverse().forEach(function(l){ try{ if(l.open()) l.close(); }catch(err){} });
    fixPanel();
  });
})();
</script>
{% endif %}
<div id="routePopup" style="

position:fixed;inset:0;

background:rgba(0,0,0,.5);

display:none;align-items:center;justify-content:center;z-index:6000;

backdrop-filter:blur(4px);">

<div style="

background:#fff;border-radius:18px;width:360px;max-width:94vw;

overflow:hidden;box-shadow:0 20px 60px rgba(0,0,0,.25);">

  <div style="background:#0f172a;padding:18px 20px 14px;">

    <div style="font-size:15px;font-weight:900;color:#f8fafc;margin-bottom:2px;">경로 설정</div>

    <div style="font-size:12px;color:#64748b;">출발지와 도착지를 입력하세요</div>

  </div>

  <div style="padding:18px 20px;">

    <input id="startInput"

      placeholder="출발지 (예: 광주전라제주지역본부)"

      style="width:100%;height:42px;padding:0 12px;border:1.5px solid #e2e8f0;border-radius:10px;font-size:13px;margin-bottom:8px;outline:none;transition:border-color .15s;"

      onfocus="this.style.borderColor='#3b82f6'" onblur="this.style.borderColor='#e2e8f0'">

    <input id="destInput"

      placeholder="도착지 (예: 전라남도청)"

      style="width:100%;height:42px;padding:0 12px;border:1.5px solid #e2e8f0;border-radius:10px;font-size:13px;margin-bottom:10px;outline:none;transition:border-color .15s;"

      onfocus="this.style.borderColor='#3b82f6'" onblur="this.style.borderColor='#e2e8f0'">

    <div id="destSuggestBox" style="

      display:none;width:100%;max-height:180px;overflow-y:auto;

      border:1.5px solid #e2e8f0;border-radius:10px;background:#fff;

      margin-bottom:12px;box-shadow:0 4px 14px rgba(0,0,0,.08);"></div>

    <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;">

      <button onclick="closeRoutePopup()" style="

        height:42px;border:1.5px solid #e2e8f0;border-radius:10px;

        background:#fff;font-weight:700;font-size:14px;cursor:pointer;color:#475569;">취소</button>

      <button type="button" onclick="runRouteSearch()" style="

        height:42px;border:none;border-radius:10px;

        background:linear-gradient(135deg,#3b82f6,#2563eb);

        color:#fff;font-weight:800;font-size:14px;cursor:pointer;">조회</button>

    </div>

  </div>

</div>

</div>



<div id="adminPwModal" style="

display:none;

position:fixed;

inset:0;

background:rgba(15,23,42,0.45);

z-index:5000;

align-items:center;

justify-content:center;

padding:20px;

">

  <div style="

  width:100%;

  max-width:360px;

  background:#ffffff;

  border-radius:18px;

  padding:22px;

  box-shadow:0 18px 45px rgba(0,0,0,0.25);

  ">

    <div style="

    font-size:18px;

    font-weight:900;

    margin-bottom:8px;

    color:#111827;

    ">

    관리자 통계

    </div>



    <div style="

    font-size:13px;

    color:#64748b;

    margin-bottom:14px;

    ">

    관리자 암호를 입력하세요.

    </div>



    <input id="adminPwInput" type="password" onkeydown="if(event.key==='Enter'){submitAdminPw();}" style="

    width:100%;

    height:44px;

    border:1px solid #cbd5e1;

    border-radius:12px;

    padding:0 12px;

    font-size:16px;

    outline:none;

    ">



    <div id="adminPwMsg" style="

    min-height:20px;

    margin-top:8px;

    font-size:13px;

    color:#ef4444;

    "></div>



    <div style="

    display:grid;

    grid-template-columns:1fr 1fr;

    gap:10px;

    margin-top:14px;

    ">

      <button onclick="closeAdminPwModal()" style="

      height:42px;

      border:1px solid #cbd5e1;

      border-radius:12px;

      background:#ffffff;

      font-weight:800;

      cursor:pointer;

      ">

      취소

      </button>



      <button onclick="submitAdminPw()" style="

      height:42px;

      border:none;

      border-radius:12px;

      background:#2563eb;

      color:#ffffff;

      font-weight:800;

      cursor:pointer;

      ">

      확인

      </button>

    </div>

  </div>

</div>



<!-- 9번: 주소로 근처 위험지역 검색 팝업 -->

<div id="addrSearchPopup" style="

position:fixed;inset:0;background:rgba(0,0,0,.5);

display:none;align-items:center;justify-content:center;z-index:6000;

backdrop-filter:blur(4px);">

<div style="background:#fff;border-radius:18px;width:360px;max-width:94vw;overflow:hidden;box-shadow:0 20px 60px rgba(0,0,0,.25);">

  <div style="background:#0f172a;padding:18px 20px 14px;">

    <div style="font-size:15px;font-weight:900;color:#f8fafc;margin-bottom:2px;">주소로 찾기</div>

    <div style="font-size:12px;color:#64748b;">입력한 주소 5km 이내 위험지역을 표시합니다</div>

  </div>

  <div style="padding:18px 20px;">

    <input id="addrSearchInput"

      placeholder="주소 입력 (예: 광주시 서구 치평동)"

      style="width:100%;height:42px;padding:0 12px;border:1.5px solid #e2e8f0;border-radius:10px;font-size:13px;margin-bottom:8px;outline:none;transition:border-color .15s;"

      onfocus="this.style.borderColor='#3b82f6'" onblur="this.style.borderColor='#e2e8f0'">

    <div id="addrSuggestBox" style="

      display:none;width:100%;max-height:160px;overflow-y:auto;

      border:1.5px solid #e2e8f0;border-radius:10px;background:#fff;

      margin-bottom:10px;box-shadow:0 4px 14px rgba(0,0,0,.08);"></div>

    <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;">

      <button onclick="closeAddressSearch()" style="

        height:42px;border:1.5px solid #e2e8f0;border-radius:10px;

        background:#fff;font-weight:700;font-size:14px;cursor:pointer;color:#475569;">취소</button>

      <button type="button" onclick="runAddressSearch()" style="

        height:42px;border:none;border-radius:10px;

        background:linear-gradient(135deg,#3b82f6,#2563eb);

        color:#fff;font-weight:800;font-size:14px;cursor:pointer;">조회</button>

    </div>

  </div>

</div>

</div>



<!-- 5번: 코멘트 모달 -->

<div id="commentModal" style="

position:fixed;inset:0;background:rgba(0,0,0,.45);

display:none;align-items:center;justify-content:center;z-index:7000;">

<div style="background:white;border-radius:18px;padding:22px;width:360px;max-width:94vw;max-height:80vh;display:flex;flex-direction:column;">

  <div style="font-size:17px;font-weight:900;margin-bottom:14px;">💬 코멘트 게시판</div>

  <div id="commentList" style="flex:1;overflow-y:auto;max-height:260px;margin-bottom:14px;border:1px solid #f1f5f9;border-radius:10px;padding:8px 10px;"></div>

  <textarea id="commentInput" maxlength="500" placeholder="이 지점에 대한 의견을 남겨주세요..." style="

    width:100%;height:72px;border:1px solid #cbd5e1;border-radius:10px;

    padding:10px;font-size:13px;resize:none;margin-bottom:10px;

    font-family:inherit;"></textarea>

  <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;">

    <button onclick="closeComments()" style="height:42px;border:1px solid #cbd5e1;border-radius:10px;background:#fff;font-weight:700;cursor:pointer;">닫기</button>

    <button onclick="submitComment()" style="height:42px;border:none;border-radius:10px;background:#2563eb;color:#fff;font-weight:700;cursor:pointer;">등록</button>

  </div>

</div>

</div>



<!-- 별점 평가 모달 -->

<div id="ratingModal" style="

position:fixed;inset:0;background:rgba(0,0,0,.45);

display:none;align-items:center;justify-content:center;z-index:7500;">

<div style="background:white;border-radius:18px;padding:24px 22px;width:320px;max-width:94vw;text-align:center;">

  <div style="font-size:17px;font-weight:900;margin-bottom:6px;">이 지점 평가</div>

  <div style="font-size:13px;color:#64748b;margin-bottom:16px;">별점을 선택하고 등록을 눌러주세요.</div>

  <div id="ratingStarRow" style="font-size:28px;letter-spacing:2px;margin-bottom:18px;cursor:pointer;display:flex;justify-content:center;gap:2px;flex-wrap:nowrap;white-space:nowrap;">

    <span onclick="selectRatingStar(1)" data-n="1" style="display:inline-block;padding:2px;">☆</span>

    <span onclick="selectRatingStar(2)" data-n="2" style="display:inline-block;padding:2px;">☆</span>

    <span onclick="selectRatingStar(3)" data-n="3" style="display:inline-block;padding:2px;">☆</span>

    <span onclick="selectRatingStar(4)" data-n="4" style="display:inline-block;padding:2px;">☆</span>

    <span onclick="selectRatingStar(5)" data-n="5" style="display:inline-block;padding:2px;">☆</span>

  </div>

  <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;">

    <button onclick="closeRatingModal()" style="height:42px;border:1px solid #cbd5e1;border-radius:10px;background:#fff;font-weight:700;cursor:pointer;">취소</button>

    <button onclick="submitRating()" style="height:42px;border:none;border-radius:10px;background:#2563eb;color:#fff;font-weight:700;cursor:pointer;">등록</button>

  </div>

</div>

</div>



<!-- 개인정보 안내 팝업 -->

<div id="privacyNoticeModal" style="

position:fixed;inset:0;background:rgba(15,23,42,0.55);

display:none;align-items:center;justify-content:center;z-index:9999;

backdrop-filter:blur(3px);">

<div style="

background:#ffffff;border-radius:22px;

padding:36px 32px 28px;

width:min(460px,92vw);

box-shadow:0 20px 60px rgba(0,0,0,0.25);

text-align:center;

">

  <!-- 알림 아이콘 (SVG) -->

  <div style="margin-bottom:16px;display:flex;justify-content:center;">

    <svg xmlns='http://www.w3.org/2000/svg' width='52' height='52' viewBox='0 0 24 24' fill='none' stroke='#2563eb' stroke-width='1.8' stroke-linecap='round' stroke-linejoin='round'>

      <path d='M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9'/>

      <path d='M13.73 21a2 2 0 0 1-3.46 0'/>

    </svg>

  </div>

  <div style="font-size:clamp(16px,2.2vw,20px);font-weight:900;color:#1a202c;margin-bottom:14px;line-height:1.4;">

    장기요양 안전로드 안내

  </div>

  <div style="font-size:clamp(13px,1.5vw,15px);color:#374151;line-height:1.9;margin-bottom:26px;word-break:keep-all;">

    '장기요양 안전로드'는 내부직원 업무지원을 위해 제작되었으며,

    사용자의 위치 정보를 수집하지 않습니다.

  </div>

  <button onclick="closePrivacyNotice()" style="

    width:100%;height:clamp(44px,6vw,52px);border:none;border-radius:13px;

    background:linear-gradient(135deg,#2563eb,#3b82f6);

    color:#fff;font-size:clamp(14px,1.6vw,16px);font-weight:800;

    cursor:pointer;

    box-shadow:0 4px 14px rgba(37,99,235,.35);

  ">확인</button>

</div>

</div>

<script>

(function(){

  if(!sessionStorage.getItem("privacyNoticeSeen")){

    const modal = document.getElementById("privacyNoticeModal");

    if(modal){ modal.style.display = "flex"; document.body.style.overflow = "hidden"; }

  }

})();

function closePrivacyNotice(){

  sessionStorage.setItem("privacyNoticeSeen","1");

  const modal = document.getElementById("privacyNoticeModal");

  if(modal) modal.style.display = "none";

  document.body.style.overflow = "";

}

</script>



</body>

</html>

"""



@app.route("/char_left")

def char_left():

    return send_file("left.png", mimetype="image/png")



@app.route("/char_right")

def char_right():

    return send_file("right.png", mimetype="image/png")



@app.route("/ci")

def ci():

    return send_file("ci.png", mimetype="image/png")



@app.route("/photo/111")

def photo_toilet():

    return send_file("111.png", mimetype="image/png")



@app.route("/photo/222")

def photo_ice():

    return send_file("222.png", mimetype="image/png")



@app.route("/photo/333")

def photo_accident():

    return send_file("333.png", mimetype="image/png")



@app.route("/download-apk")

def download_apk():

    apk_path = os.path.join(BASE_DIR, "safeload.apk")

    if not os.path.exists(apk_path):

        return "APK 파일 없음 - safeload.apk를 app.py와 같은 폴더에 넣어주세요.", 404

    try:

        now_time = time.time()
        last_dl_at = session.get("last_download_counted_at", 0)
        is_range_request = bool(request.headers.get("Range"))

        if SUPABASE_URL and SUPABASE_KEY and not is_range_request and now_time - float(last_dl_at) > 10:

            requests.post(
                f"{SUPABASE_URL}/rest/v1/download_logs",
                headers={
                    "apikey": SUPABASE_KEY,
                    "Authorization": f"Bearer {SUPABASE_KEY}",
                    "Content-Type": "application/json"
                },
                json={"downloaded_at": datetime.now(KST).isoformat()}
            )

            session["last_download_counted_at"] = now_time

    except Exception as e:

        print("download_logs 기록 실패:", e)

    return send_file(apk_path, as_attachment=True, download_name="safeload.apk", mimetype="application/vnd.android.package-archive")



@app.route("/")

def index():



    visitor = update_visitors()



    return render_template_string(

        HTML,

        total_visit=visitor["total"],

        today_visit=visitor["today_count"],

        kakao_key=KAKAO_KEY or "",

        kakao_js_key=KAKAO_JS_KEY or "",

        detail_on=feature_detail_on()

    )





@app.route("/log_search", methods=["POST"])

def log_search():



    data = request.get_json() or {}



    save_search_log(data)



    return jsonify({"ok": True})





# ===== 5번: 별점 API =====

# ===== 별점·코멘트를 순번이 아니라 "구분 + 좌표"로 연결 =====
# 엑셀을 갱신하면 순번이 바뀌므로, 같은 구분 + 반경 약 15m 안이면 같은 장소로 본다.
SPOT_TOL_LAT = 0.00015   # 약 17m
SPOT_TOL_LNG = 0.00018   # 약 16m (위도 35도 기준)


def _spot_loc(src):
    gubun = safe_str(src.get("gubun", ""))
    try:
        lat = float(src.get("lat"))
        lng = float(src.get("lng"))
    except (TypeError, ValueError):
        return None
    if gubun not in TYPE_COLORS or not (32.5 <= lat <= 39.5 and 123.5 <= lng <= 132.5):
        return None
    return gubun, lat, lng


def spot_filter_qs(args, spot_id):
    """조회 조건: 좌표가 오면 좌표 범위로, 없으면 예전처럼 spot_id 로"""
    loc = _spot_loc(args)
    if not loc:
        return f"spot_id=eq.{quote(str(spot_id))}"
    g, lat, lng = loc
    return (f"spot_gubun=eq.{quote(g)}"
            f"&spot_lat=gte.{lat - SPOT_TOL_LAT:.7f}&spot_lat=lte.{lat + SPOT_TOL_LAT:.7f}"
            f"&spot_lng=gte.{lng - SPOT_TOL_LNG:.7f}&spot_lng=lte.{lng + SPOT_TOL_LNG:.7f}")


def spot_loc_fields(data):
    """저장할 때 함께 넣을 구분·좌표"""
    loc = _spot_loc(data)
    if not loc:
        return {}
    return {"spot_gubun": loc[0], "spot_lat": round(loc[1], 7), "spot_lng": round(loc[2], 7)}





@app.route("/api/rating", methods=["GET"])

def get_rating():

    spot_id = request.args.get("spot_id", "")

    if not spot_id or not SUPABASE_URL or not SUPABASE_KEY:

        return jsonify({"avg": 0, "count": 0})

    try:

        headers = {

            "apikey": SUPABASE_KEY,

            "Authorization": f"Bearer {SUPABASE_KEY}",

            "Content-Type": "application/json"

        }

        r = requests.get(

            f"{SUPABASE_URL}/rest/v1/spot_ratings?{spot_filter_qs(request.args, spot_id)}&select=score",

            headers=headers

        )

        rows = r.json()

        if not rows or not isinstance(rows, list) or len(rows) == 0:

            return jsonify({"avg": 0, "count": 0})

        scores = [int(row["score"]) for row in rows if "score" in row]

        avg = round(sum(scores) / len(scores), 1) if scores else 0

        return jsonify({"avg": avg, "count": len(scores)})

    except Exception as e:

        return jsonify({"avg": 0, "count": 0})





@app.route("/api/rating", methods=["POST"])

def post_rating():

    data = request.get_json() or {}

    spot_id = str(data.get("spot_id", "")).strip()
    try:
        score = int(data.get("score", 0))
    except (TypeError, ValueError):
        score = 0
    if not spot_id.isdigit() or score < 1 or score > 5 or not SUPABASE_URL or not SUPABASE_KEY:

        return jsonify({"ok": False})

    try:

        headers = {

            "apikey": SUPABASE_KEY,

            "Authorization": f"Bearer {SUPABASE_KEY}",

            "Content-Type": "application/json",

            "Prefer": "return=representation"

        }

        r = requests.post(

            f"{SUPABASE_URL}/rest/v1/spot_ratings",

            headers=headers,

            json={"spot_id": spot_id, "score": score, **spot_loc_fields(data)}

        )

        if r.status_code >= 400:

            print("별점 저장 실패:", r.status_code, r.text)

            return jsonify({"ok": False, "error": r.text})

        return jsonify({"ok": True})

    except Exception as e:

        return jsonify({"ok": False})





# ===== 5번: 코멘트 API =====

@app.route("/api/comments", methods=["GET"])

def get_comments():

    spot_id = request.args.get("spot_id", "")

    if not spot_id or not SUPABASE_URL or not SUPABASE_KEY:

        return jsonify({"comments": []})

    try:

        headers = {

            "apikey": SUPABASE_KEY,

            "Authorization": f"Bearer {SUPABASE_KEY}",

            "Content-Type": "application/json"

        }

        r = requests.get(

            f"{SUPABASE_URL}/rest/v1/spot_comments?{spot_filter_qs(request.args, spot_id)}&order=created_at.desc&limit=50",

            headers=headers

        )

        rows = r.json()
        if not isinstance(rows, list):
            return jsonify({"comments": []})
        for row in rows:
            row["created_at"] = kst_iso(row.get("created_at"))
        return jsonify({"comments": rows})
    except Exception as e:
        return jsonify({"comments": []})
@app.route("/api/comments", methods=["POST"])

def post_comment():

    data = request.get_json() or {}

    spot_id = str(data.get("spot_id", "")).strip()
    content = str(data.get("content", "")).strip()
    if not spot_id.isdigit() or not content or len(content) > 500 or not SUPABASE_URL or not SUPABASE_KEY:
        return jsonify({"ok": False})
    try:

        headers = {

            "apikey": SUPABASE_KEY,

            "Authorization": f"Bearer {SUPABASE_KEY}",

            "Content-Type": "application/json",

            "Prefer": "return=representation"

        }

        r = requests.post(
            f"{SUPABASE_URL}/rest/v1/spot_comments",
            headers=headers,
            json={"spot_id": spot_id, "content": content, **spot_loc_fields(data)}
        )
        return jsonify({"ok": r.status_code < 300})

    except Exception as e:

        return jsonify({"ok": False})





@app.route("/api/spot_location")

def spot_location():

    spot_id = request.args.get("spot_id", "")

    try:

        df = sr_df()

        row = df[df["순번"].astype(str) == str(spot_id)]

        if row.empty:

            return jsonify({"lat": None, "lng": None})

        r = row.iloc[0]

        return jsonify({"lat": float(r["위도"]), "lng": float(r["경도"])})

    except Exception as e:

        return jsonify({"lat": None, "lng": None})





# ===== 관리자 인증 (서버에서 확인) =====
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "qwer")
def admin_required(view):
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("safety_admin"):
            if request.path.startswith("/api/"):
                return jsonify({"ok": False, "error": "관리자 인증이 필요합니다."}), 401
            return redirect("/")
        return view(*args, **kwargs)
    return wrapped
# ===== 데이터 갱신 프로그램(exe) 내려받기 — 관리자만 =====
# 저장소에 아래 이름 중 하나로 올려두면 됨 (exe 안에 인증키가 있으니 저장소는 꼭 비공개로)
REFRESH_EXE_CANDIDATES = [
    os.path.join(BASE_DIR, "tools", "안전로드_데이터갱신.exe"),
    os.path.join(BASE_DIR, "안전로드_데이터갱신.exe"),
    os.path.join(BASE_DIR, "tools", "SafetyRoadRefresh.exe"),
    os.path.join(BASE_DIR, "SafetyRoadRefresh.exe"),
]


def refresh_exe_info():
    for fp in REFRESH_EXE_CANDIDATES:
        if os.path.isfile(fp):
            st = os.stat(fp)
            return {"ok": True, "size": f"{st.st_size / 1024 / 1024:.1f}MB",
                    "date": datetime.fromtimestamp(st.st_mtime, KST).strftime("%Y-%m-%d")}
    return {"ok": False}


@app.route("/admin/refresh_tool")
@admin_required
def download_refresh_tool():
    for fp in REFRESH_EXE_CANDIDATES:
        if os.path.isfile(fp):
            return send_file(fp, as_attachment=True, download_name="안전로드_데이터갱신.exe",
                             mimetype="application/octet-stream")
    return "갱신 프로그램 파일이 서버에 없습니다. 저장소에 안전로드_데이터갱신.exe 를 올려 주세요.", 404


# ===== 시설 상세정보 기능 ON/OFF (관리자 페이지 스위치) =====
# OFF: 예전 화면 그대로 / ON: 팝업 상세정보 + '내 주변 찾기' 조건
FEATURE_KEY = "feature_detail"
_FEATURE_CACHE = {"v": None, "t": 0.0}


def _sb_headers(extra=None):
    h = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}", "Content-Type": "application/json"}
    if extra:
        h.update(extra)
    return h


def _fetch_feature():
    """→ (값 True/False, 오류문구 또는 None)"""
    if not SUPABASE_URL or not SUPABASE_KEY:
        return False, "Supabase 환경변수 없음"
    r = requests.get(f"{SUPABASE_URL}/rest/v1/app_settings?key=eq.{FEATURE_KEY}&select=value",
                     headers=_sb_headers(), timeout=6)
    if r.status_code >= 400:
        return False, "app_settings 표가 없습니다 (SQL 먼저 실행)"
    rows = r.json()
    return bool(rows) and str(rows[0].get("value", "")).lower() == "on", None


def feature_detail_on():
    now = time.time()
    if _FEATURE_CACHE["v"] is not None and now - _FEATURE_CACHE["t"] < 30:
        return _FEATURE_CACHE["v"]
    v = _FEATURE_CACHE["v"] or False
    try:
        _v, _err = _fetch_feature()
        if not _err:
            v = _v
    except Exception:
        pass   # 조회 실패 시 직전 값 유지 (처음이면 OFF)
    _FEATURE_CACHE.update(v=v, t=now)
    return v


# ===== 토글 ON: 공중화장실을 엑셀 대신 출장 도구함 화장실 자료(행안부 전국 자료, 7일마다 자동 갱신)로 =====
# 안전로드는 광주·전남·전북·제주만 보여줌. 다른 항목(결빙·사고·주차장·AED)은 엑셀 그대로.
# 첫 이름으로 통일 (광주·전남은 2026.7.1 전남광주통합특별시로 통합. 옛 주소 표기도 같은 곳으로 봄)
SR_TOILET_REGIONS = {
    "전남광주": ("전남광주통합특별시", "전남광주특별시", "광주특별시", "광주광역시", "광주", "전라남도", "전남"),
    "전북": ("전북특별자치도", "전라북도", "전북"),
    "제주": ("제주특별자치도", "제주도", "제주"),
}
_SR_TOILET_DF = {"key": None, "df": None, "rows": None}
SR_GWANGJU_GU = {"동구", "서구", "남구", "북구", "광산구"}
# 안전로드 관할 시군구 (화장실 주소가 '서구독립로'처럼 붙어 쓰인 경우를 바로잡는 기준)
SR_HQ_SGG = {
    "전남광주통합특별시": ["광주동구", "광주서구", "광주남구", "광주북구", "광주광산구", "목포시", "여수시", "순천시", "나주시",
                    "광양시", "담양군", "곡성군", "구례군", "고흥군", "보성군", "화순군", "장흥군", "강진군", "해남군",
                    "영암군", "무안군", "함평군", "영광군", "장성군", "완도군", "진도군", "신안군"],
    "전북특별자치도": ["전주시", "군산시", "익산시", "정읍시", "남원시", "김제시", "완주군", "진안군", "무주군", "장수군",
                "임실군", "순창군", "고창군", "부안군"],
    "제주특별자치도": ["제주시", "서귀포시"],
}


def _sr_region(sido):
    for k, names in SR_TOILET_REGIONS.items():
        if sido in names:
            return k
    return None


def _sr_df_with_trip_toilets(base):
    rows = trip_load_toilets()
    if not rows:
        return base
    import numpy as np
    # 시도 이름 통일: 엑셀에 광주광역시·전라남도·전라북도 같은 옛 이름이 섞여 있어도 한 이름으로 (다른 항목도 같이)
    base = base.copy()
    base["시도"] = [SR_TOILET_REGIONS[_sr_region(v)][0] if _sr_region(v) else v for v in base["시도"]]
    # 시군구: 관할 목록 + 엑셀에 쓰인 '전주시 완산구' 같은 표기만 인정
    valid = {sd: set(v) for sd, v in SR_HQ_SGG.items()}
    for sd, ct in zip(base["시도"], base["시군구"]):
        if sd in valid and any(ct == h or ct.startswith(h + " ") for h in SR_HQ_SGG[sd]):
            valid[sd].add(ct)
    towns = {}
    for sd, ct, tw in zip(base["시도"], base["시군구"], base["읍면동"]):
        if tw and tw != "읍면동없음":
            towns.setdefault((sd, ct), set()).add(tw)
    old_t = base[base["구분"] == "공중화장실"]
    addr_town = {a: t for a, t in zip(old_t["주소"], old_t["읍면동"]) if a and t != "읍면동없음"}
    # 읍면동을 주소로 못 찾으면 같은 시군구의 가장 가까운 기존 지점 읍면동을 씀 (도로명주소 대비)
    ref = base[base["읍면동"] != "읍면동없음"]
    near = {k: (g["위도"].to_numpy(), g["경도"].to_numpy(), g["읍면동"].tolist())
            for k, g in ref.groupby(["시도", "시군구"])}

    near_sd = {}
    for (sd, ct), g in near.items():
        near_sd.setdefault(sd, []).append((ct, g))

    def city_of(k, sd, tok, lat, lng):
        ok = valid.get(sd, set())
        a = tok[1]
        if len(tok) > 2 and f"{a} {tok[2]}" in ok:
            return f"{a} {tok[2]}"
        if a in ok:
            return a
        if k == "전남광주" and "광주" + a in ok:
            return "광주" + a
        # 붙어 쓰인 주소: '서구독립로' → 광주서구, '여수시문수동111-3' → 여수시
        for v in sorted(ok, key=len, reverse=True):
            short = v[2:] if (k == "전남광주" and v.startswith("광주") and v[2:] in SR_GWANGJU_GU) else v
            if a.startswith(v) or a.startswith(short):
                return v
        # 그래도 모르면 같은 시도에서 가장 가까운 기존 지점의 시군구 (약 5km 안)
        best, bd = None, 0.05 ** 2
        for ct, g in near_sd.get(sd, []):
            d = (g[0] - lat) ** 2 + ((g[1] - lng) * 0.82) ** 2
            i = int(np.argmin(d))
            if d[i] < bd:
                best, bd = ct, d[i]
        return best

    def town_of(sd, ct, addr, lat, lng):
        t = addr_town.get(addr) or extract_town_from_address(addr)
        known = towns.get((sd, ct))
        if t != "읍면동없음":
            # '여수시문수동' 처럼 앞에 시군구가 붙은 경우 → '문수동'
            cands = [t] + [t[i + 1:] for i, ch in enumerate(t[:-1]) if ch in "시군구"]
            for c in cands:
                if known and c in known:
                    return c
            if not known and re.fullmatch(r"[가-힣]{1,6}\d*(읍|면|동|가)", t) and not re.search(r"[시군구]", t[:-1]):
                return t
        g = near.get((sd, ct))
        if not g:
            return "읍면동없음"
        d = (g[0] - lat) ** 2 + ((g[1] - lng) * 0.82) ** 2
        i = int(np.argmin(d))
        return g[2][i] if d[i] < 0.03 ** 2 else "읍면동없음"   # 약 3km 안

    recs = []
    for t in rows:
        _id, name, addr, lat, lng, op, bell, acc = t[:8]
        upd = t[8] if len(t) > 8 else ""
        tok = str(addr).split()
        if op == "미개방" or len(tok) < 2:
            continue
        k = _sr_region(tok[0])
        if not k:
            continue
        sd = SR_TOILET_REGIONS[k][0]
        ct = city_of(k, sd, tok, lat, lng)
        if not ct:
            continue                             # 시군구를 알 수 없는 곳은 뺌
        recs.append({"구분": "공중화장실", "시도": sd, "시군구": ct, "읍면동": town_of(sd, ct, addr, lat, lng),
                     "주소": " ".join(tok[1:]), "위도": float(lat), "경도": float(lng), "날짜": upd,
                     "개방시간": op, "비상벨": "Y" if bell else "N", "장애인화장실": "Y" if acc else "N",
                     "화장실명": name, "자료수정일": upd})
    if not recs:
        return base
    other = base[base["구분"] != "공중화장실"]
    new = pd.DataFrame(recs).reindex(columns=base.columns)
    for c in new.columns:
        if c not in ("위도", "경도"):
            new[c] = new[c].fillna("")
    start = int(base["순번"].max()) + 1      # 다른 항목 순번은 그대로 두고 화장실만 뒤에 붙임
    new["순번"] = range(start, start + len(new))
    return pd.concat([other, new], ignore_index=True)


_SR_LIVE_DF = {"key": None, "df": None}


def _sr_apply_live(df):
    """자동 갱신 자료가 있는 항목(결빙·사고·주차장·AED)은 엑셀 대신 그 자료로"""
    out = df.copy() if df is DATA_CACHE else df
    out["시도"] = [SR_TOILET_REGIONS[_sr_region(v)][0] if _sr_region(v) else v for v in out["시도"]]
    if "시설명" not in out.columns:
        out["시설명"] = ""
    for cat, live in list(_SR_LIVE["data"].items()):
        gubuns = ("공영주차장", "민영주차장") if cat == "주차장" else (cat,)
        old_n = int(out["구분"].isin(gubuns).sum())
        if old_n and len(live) < old_n * SR_LIVE_SHRINK_GUARD:
            _SR_LIVE["note"][cat] = f"엑셀 {old_n:,}건보다 너무 적어({len(live):,}건) 엑셀 사용"
            continue
        new = live.reindex(columns=out.columns)
        for c in new.columns:
            if c not in ("위도", "경도"):
                new[c] = new[c].fillna("")
        new["사고설명"], new["사진URL"] = "", ""
        start = int(pd.to_numeric(out["순번"], errors="coerce").max() or 0) + 1
        new["순번"] = range(start, start + len(new))
        out = pd.concat([out[~out["구분"].isin(gubuns)], new], ignore_index=True)
    return out


def sr_df():
    """안전로드 지도 자료. 토글 OFF = 엑셀 그대로 / ON = 화장실은 출장 도구함 자료, 나머지는 자동 갱신 자료로"""
    base = load_df()
    if not feature_detail_on():
        return base
    try:
        cnt = base["구분"].value_counts().to_dict()
        cnt["주차장"] = cnt.get("공영주차장", 0) + cnt.get("민영주차장", 0)
        sr_live_tick(cnt)
    except Exception as e:
        print("안전로드 자동 갱신 확인 실패:", e)
    try:
        rows = trip_load_toilets() or []
    except Exception:
        rows = []
    key = (id(base), id(rows), len(rows), _SR_LIVE["ver"])
    if _SR_LIVE_DF["key"] == key:
        return _SR_LIVE_DF["df"]
    _SR_LIVE_DF.update(key=None, df=None)      # 예전 결과를 먼저 버려 메모리에 두 벌 안 겹치게
    try:
        df = _sr_df_with_trip_toilets(base)
    except Exception as e:
        print("안전로드 화장실(출장 도구함 자료) 합치기 실패, 엑셀 사용:", e)
        df = base
    try:
        df = _sr_apply_live(df)
    except Exception as e:
        print("안전로드 자동 갱신 자료 합치기 실패, 엑셀 사용:", e)
    import gc
    gc.collect()
    _SR_LIVE_DF.update(key=key, df=df)
    return df


# =====================================================================
# 안전로드 자료 자동 갱신 (토글 ON) — 데이터 갱신 프로그램(exe)과 같은 API·같은 규칙을 서버에서 7일마다
#   상습결빙지역·교통사고위험지역: 생활안전지도(safemap) IF_0103 / IF_0093  (SAFEMAP_KEY)
#   주차장: 공공데이터포털 전국주차장 표준데이터                       (PARKING_KEY, 없으면 DATA_GO_KR_KEY)
#   자동심장충격기: 공공데이터포털 AED 정보                           (DATA_GO_KR_KEY)
#   시도·시군구·읍면동은 카카오 좌표→행정구역 (exe와 같은 정리 규칙). 조회 결과는 저장소에 보관해 다시 안 부름
#   받은 자료는 Supabase 저장소(버킷 safetyroad, 비공개)에 CSV로 보관 → 재시작·재배포해도 유지
#   실패하거나 건수가 기존 엑셀의 절반도 안 되면 엑셀 그대로 씀
# =====================================================================
import math
import csv
import io
from collections import Counter
SR_LIVE_CATS = ["상습결빙지역", "주차장", "자동심장충격기", "교통사고위험지역"]
SR_LIVE_SIDOS = ["전남광주통합특별시", "전북특별자치도", "제주특별자치도"]
SR_LIVE_REFRESH_SEC = 7 * 86400
SR_NIGHT_HOURS = (2, 5)        # 다시 받는 건 새벽 2시~5시(한국시간)에만 시작. 한 번도 못 받은 항목은 바로 받음
SR_LIVE_PAGE_SIZE = 1000
SR_LIVE_MAX_PAGES = 2000
SR_LIVE_SHRINK_GUARD = 0.5
# 카카오는 앱 검색과 같은 키를 쓰므로 갱신은 하루 API별 이만큼만 (넘으면 다음 날 이어서)
SR_LIVE_KAKAO_DAILY = int(os.environ.get("SR_KAKAO_DAILY", "30000"))
SR_SAFEMAP_URL = "http://safemap.go.kr/openapi2/{code}"
SR_PARKING_URL = "https://api.data.go.kr/openapi/tn_pubr_prkplce_info_api"
SR_AED_URL = "https://apis.data.go.kr/B552657/AEDInfoInqireService/getEgytAedManageInfoInqire"
SR_SIDO_ALIASES = {
    "전북특별자치도": ["전라북도", "전북"],
    "전남광주통합특별시": ["광주광역시", "전라남도", "광주", "전남"],
    "제주특별자치도": ["제주도", "제주"],
}
SR_ALIAS_TO_SIDO = {}
for _s, _al in SR_SIDO_ALIASES.items():
    SR_ALIAS_TO_SIDO[_s] = _s
    for _a in _al:
        SR_ALIAS_TO_SIDO[_a] = _s
SR_AED_Q0 = {s: [a for a in [s] + al if a.endswith(("시", "도")) and len(a) >= 3] for s, al in SR_SIDO_ALIASES.items()}
SR_SIDO_BBOX = {"전북특별자치도": (125.9, 35.25, 127.95, 36.18), "전남광주통합특별시": (124.9, 33.8, 127.95, 35.55),
                "제주특별자치도": (125.95, 32.95, 127.05, 34.1)}
SR_CTPRVN = {"29": "전남광주통합특별시", "46": "전남광주통합특별시", "45": "전북특별자치도", "52": "전북특별자치도",
             "50": "제주특별자치도"}
SR_ROAD_TYPES = {"시도", "국도", "고속국도", "구도", "광역시도", "일반국도", "군도", "고속도로", "도시계획도로", "특별광역시도",
                 "지방도", "국가지원지방도", "시군도", "농어촌도로"}
SR_LIVE_COLS = ["구분", "시도", "시군구", "읍면동", "주소", "위도", "경도", "시설명", "자료수정일"]
SR_LIVE_EXTRA = {"주차장": ["요금", "요금상세", "운영평일", "운영토요일", "운영공휴일"],
                 "자동심장충격기": ["설치장소", "사용시간", "일요일사용"],
                 "교통사고위험지역": ["사고건수", "보행자사고", "야간사고", "중상이상"]}
SR_LIVE_OBJ = {"상습결빙지역": "ice", "교통사고위험지역": "acc", "주차장": "parking", "자동심장충격기": "aed"}
_SR_LIVE = {"data": {}, "at": {}, "note": {}, "count": {}, "busy": False, "loaded": False, "ver": 0}
_SR_LIVE_LOCK = threading.Lock()
_SR_KAKAO_USE = {"date": "", "n": {}}
_SR_KAKAO_CACHE = {"d": None, "dirty": 0}


class _SrStop(Exception):
    pass


def _sr_s(v):
    return "" if v is None else str(v).strip()


def _sr_num(v):
    try:
        f = float(str(v).replace(",", "").strip())
        return None if math.isnan(f) else f
    except (TypeError, ValueError):
        return None


def _sr_int(v):
    try:
        return int(float(str(v).replace(",", "").strip()))
    except (TypeError, ValueError):
        return None


# ---- 저장소 ----
def _sr_store():
    if not SUPABASE_URL or not SUPABASE_KEY:
        return None, None
    return SUPABASE_URL.rstrip("/") + "/storage/v1", {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}


def _sr_store_put(name, data, ctype):
    base, h = _sr_store()
    if not base:
        return False
    requests.post(f"{base}/bucket", headers=h, json={"id": "safetyroad", "name": "safetyroad", "public": False}, timeout=15)
    r = requests.post(f"{base}/object/safetyroad/{name}", data=data, headers={**h, "x-upsert": "true", "Content-Type": ctype},
                      timeout=120)
    return r.ok


def _sr_store_get(name):
    """→ (bytes, 보관 시각) 또는 None"""
    base, h = _sr_store()
    if not base:
        return None
    try:
        r = requests.get(f"{base}/object/authenticated/safetyroad/{name}", headers=h, timeout=60)
        if not r.ok:
            return None
        try:
            from email.utils import parsedate_to_datetime
            at = parsedate_to_datetime(r.headers.get("Last-Modified", "")).timestamp()
        except Exception:
            at = time.time()
        return r.content, at
    except Exception:
        return None


# ---- 응답 해석 (exe parse_response 와 같은 방식: JSON/XML 모두, item 목록 자동 탐색) ----
def _sr_flat(d):
    return {str(k): ("" if v is None else str(v).strip()) for k, v in d.items() if not isinstance(v, (dict, list))}


def _sr_json_find(o, key):
    if isinstance(o, dict):
        for k, v in o.items():
            if str(k).lower() == key and not isinstance(v, (dict, list)):
                return v
        for v in o.values():
            r = _sr_json_find(v, key)
            if r is not None:
                return r
    elif isinstance(o, list):
        for v in o:
            r = _sr_json_find(v, key)
            if r is not None:
                return r
    return None


def _sr_json_items(data):
    best = []

    def walk(o):
        nonlocal best
        if isinstance(o, list):
            dicts = [x for x in o if isinstance(x, dict)]
            if dicts and len(dicts) == len(o) and len(o) > len(best):
                best = o
            for x in o:
                walk(x)
        elif isinstance(o, dict):
            for k, v in o.items():
                if str(k).lower() in ("item", "row") and isinstance(v, dict) and not best:
                    best = [v]
                walk(v)
    walk(data)
    return [_sr_flat(x) for x in best]


def _sr_parse(content):
    text = content.decode("utf-8", errors="replace").strip() if isinstance(content, bytes) else str(content).strip()
    if not text:
        return [], None, "빈 응답"
    if text[0] in "{[":
        try:
            data = json.loads(text)
        except ValueError as e:
            return [], None, f"JSON 해석 실패: {e}"
        items = _sr_json_items(data)
        total = _sr_int(_sr_json_find(data, "totalcount"))
        code = _sr_json_find(data, "resultcode")
        msg = _sr_json_find(data, "resultmsg") or _sr_json_find(data, "errmsg") or _sr_json_find(data, "message")
    else:
        import xml.etree.ElementTree as ET
        try:
            root = ET.fromstring(text.encode("utf-8"))
        except ET.ParseError:
            return [], None, "응답 해석 실패: " + text[:200]

        def xf(key):
            for el in root.iter():
                if el.tag.split("}")[-1].lower() == key and (el.text or "").strip():
                    return el.text.strip()
            return None
        items = [{c.tag.split("}")[-1]: (c.text or "").strip() for c in el} for el in root.iter()
                 if el.tag.split("}")[-1].lower() in ("item", "row") and len(list(el))]
        total = _sr_int(xf("totalcount"))
        code = xf("resultcode") or xf("returnreasoncode")
        msg = xf("resultmsg") or xf("returnauthmsg") or xf("errmsg")
    err = None
    if not items:
        if code is not None and str(code).strip().upper() not in {"OK", "SUCCESS", "0", "INFO-000", "200", "NORMAL_SERVICE", "00", "000"}:
            err = f"[{code}] {msg or ''}".strip()
        elif msg and re.search(r"(error|invalid|not registered|unauthor|인증|오류|실패)", str(msg), re.I):
            err = str(msg)
    return items, total, err


def _sr_http(url, params, headers=None, timeout=30, tries=3):
    last = None
    for i in range(tries):
        try:
            r = requests.get(url, params=params, headers=headers, timeout=timeout)
            if r.status_code >= 500:
                raise requests.HTTPError(f"HTTP {r.status_code}")
            return r
        except requests.RequestException as e:
            last = e
            time.sleep(1.5 * (i + 1))
    raise RuntimeError(f"접속 실패: {last}")


def _sr_paged(url, base, label):
    """exe _paged 와 같음: 서버가 한 번에 주는 최대 건수에 맞춰 페이지 크기를 줄이고, 같은 페이지가 반복되면 멈춤"""
    page, got, total, prev_first, size = 1, 0, None, None, SR_LIVE_PAGE_SIZE
    while page <= SR_LIVE_MAX_PAGES:
        r = _sr_http(url, {**base, "pageNo": page, "numOfRows": size})
        items, tot, err = _sr_parse(r.content)
        if page == 1 and tot and len(items) < size and len(items) < tot:
            size = len(items)
        if r.status_code >= 400 and not items:
            raise RuntimeError(f"{label}: HTTP {r.status_code} {err or r.text[:200]}")
        if err:
            raise RuntimeError(f"{label}: {err}")
        if tot is not None:
            total = tot
        if not items:
            return
        first = json.dumps(items[0], ensure_ascii=False, sort_keys=True)
        if first == prev_first:
            return
        prev_first = first
        got += len(items)
        if page % 5 == 0:
            import gc
            gc.collect()
        pages = math.ceil(total / size) if total else "?"
        _SR_LIVE["prog"] = f"{got:,}건 받음 · {page}/{pages}쪽"
        _sr_heartbeat()
        yield items
        if total is not None and got >= total:
            return
        page += 1


def _sr_keys(*names):
    return list(dict.fromkeys(os.environ.get(n) for n in names if os.environ.get(n)))


def _sr_paged_keys(cands, label, make):
    """키 후보를 차례로: 첫 페이지에서 오류가 나면 다음 키로 (받기 시작한 뒤의 오류는 그대로 알림)"""
    if not cands:
        raise RuntimeError(f"{label} 인증키 환경변수가 없습니다")
    for i, key in enumerate(cands):
        url, base = make(key)
        started = False
        try:
            for items in _sr_paged(url, base, label):
                started = True
                yield items
            return
        except RuntimeError:
            if started or i == len(cands) - 1:
                raise


# 키: 안전로드 전용(SR_…)이 있으면 그걸 먼저, 없으면 출장 도구함과 같은 키
def _sr_fetch(cat):
    if cat in ("상습결빙지역", "교통사고위험지역"):
        code = "IF_0103" if cat == "상습결빙지역" else "IF_0093"
        yield from _sr_paged_keys(_sr_keys("SR_SAFEMAP_KEY", "SAFEMAP_KEY"), code,
                                  lambda k: (SR_SAFEMAP_URL.format(code=code), {"serviceKey": k, "returnType": "json"}))
    elif cat == "주차장":
        yield from _sr_paged_keys(_sr_keys("PARKING_KEY", "SR_DATA_GO_KR_KEY", "DATA_GO_KR_KEY"), "전국주차장",
                                  lambda k: (SR_PARKING_URL, {"serviceKey": k, "type": "json"}))
    elif cat == "자동심장충격기":
        cands = _sr_keys("SR_DATA_GO_KR_KEY", "DATA_GO_KR_KEY")
        for sido in SR_LIVE_SIDOS:
            for q0 in SR_AED_Q0.get(sido, [sido]):
                yield from _sr_paged_keys(cands, f"AED {q0}", lambda k, q0=q0: (SR_AED_URL, {"serviceKey": k, "Q0": q0}))


# ---- 좌표 ----
def _sr_in_korea(lon, lat):
    return 124.0 <= lon <= 132.0 and 32.8 <= lat <= 39.0


def _sr_to_wgs84(x, y, crs=None):
    if x is None or y is None:
        return None
    if crs is None:
        if _sr_in_korea(x, y) or _sr_in_korea(y, x):
            crs = 4326
        elif 13000000 < x < 15000000 and 3500000 < y < 5000000:
            crs = 3857
    r = None
    if crs == 4326:
        r = (x, y) if _sr_in_korea(x, y) else ((y, x) if _sr_in_korea(y, x) else None)
    elif crs == 3857:
        lon = x / 6378137.0 * 180 / math.pi
        lat = (2 * math.atan(math.exp(y / 6378137.0)) - math.pi / 2) * 180 / math.pi
        r = (lon, lat)
    if r and _sr_in_korea(r[0], r[1]):
        return float(r[0]), float(r[1])
    return None


# ---- 카카오 (조회 결과는 저장소에 보관 → 같은 좌표는 다시 안 부름) ----
def _sr_kakao_cache():
    if _SR_KAKAO_CACHE["d"] is None:
        got = _sr_store_get("kakao_cache.json")
        try:
            _SR_KAKAO_CACHE["d"] = json.loads(got[0].decode("utf-8")) if got else {}
        except Exception:
            _SR_KAKAO_CACHE["d"] = {}
    return _SR_KAKAO_CACHE["d"]


def _sr_kakao_save():
    if _SR_KAKAO_CACHE["dirty"] and _SR_KAKAO_CACHE["d"] is not None:
        try:
            _sr_store_put("kakao_cache.json", json.dumps(_SR_KAKAO_CACHE["d"], ensure_ascii=False).encode("utf-8"),
                          "application/json")
            _SR_KAKAO_CACHE["dirty"] = 0
        except Exception:
            pass


def _sr_kakao_get(path, params):
    today = datetime.now(KST).strftime("%Y-%m-%d")
    if _SR_KAKAO_USE["date"] != today:
        _SR_KAKAO_USE.update(date=today, n={})
    if _SR_KAKAO_USE["n"].get(path, 0) >= SR_LIVE_KAKAO_DAILY:
        raise _SrStop(f"카카오 오늘 몫({SR_LIVE_KAKAO_DAILY:,}회) 다 씀 → 내일 이어서")
    if not KAKAO_KEY:
        raise _SrStop("KAKAO_KEY 환경변수가 없습니다")
    _SR_KAKAO_USE["n"][path] = _SR_KAKAO_USE["n"].get(path, 0) + 1
    r = _sr_http("https://dapi.kakao.com/v2/local" + path, params, headers={"Authorization": f"KakaoAK {KAKAO_KEY}"})
    if r.status_code in (401, 403, 429):
        raise _SrStop(f"카카오 {r.status_code}")
    if r.status_code >= 400:
        return None
    time.sleep(0.02)
    return r.json()


def _sr_kakao_cached(key, fn):
    c = _sr_kakao_cache()
    if key in c:
        return c[key] or None
    val = fn()
    c[key] = val or {}
    _SR_KAKAO_CACHE["dirty"] += 1
    if _SR_KAKAO_CACHE["dirty"] >= 300:
        _sr_kakao_save()
    return val or None


def _sr_kakao_region(lon, lat):
    def fn():
        d = _sr_kakao_get("/geo/coord2regioncode.json", {"x": lon, "y": lat}) or {}
        for doc in d.get("documents", []):
            if doc.get("region_type") == "B":
                return {"r1": doc.get("region_1depth_name", ""), "r2": doc.get("region_2depth_name", ""),
                        "r3": doc.get("region_3depth_name", "")}
        return None
    return _sr_kakao_cached(f"rc|{lon:.6f},{lat:.6f}", fn)


def _sr_address_of(lon, lat):
    def fn():
        d = _sr_kakao_get("/geo/coord2address.json", {"x": lon, "y": lat}) or {}
        docs = d.get("documents") or []
        if not docs:
            return None
        a = (docs[0].get("address") or {}).get("address_name") or (docs[0].get("road_address") or {}).get("address_name") or ""
        return {"addr": a} if a else None
    return (_sr_kakao_cached(f"c2a|{lon:.6f},{lat:.6f}", fn) or {}).get("addr", "")


def _sr_geocode(query):
    if not query:
        return None

    def fn():
        for path in ("/search/address.json", "/search/keyword.json"):
            d = _sr_kakao_get(path, {"query": query, "size": 1}) or {}
            docs = d.get("documents") or []
            if docs:
                return {"x": float(docs[0]["x"]), "y": float(docs[0]["y"])}
        return None
    return _sr_kakao_cached(f"geo|{query}", fn)


# ---- 행 만들기 (exe make_row / extra_fields 와 같은 규칙) ----
def _sr_sido_from_address(addr):
    tok = addr.split()[0] if addr and addr.split() else ""
    return SR_ALIAS_TO_SIDO.get(tok)


def _sr_strip_sido(addr):
    toks = (addr or "").split()
    if toks and toks[0] in SR_ALIAS_TO_SIDO:
        toks = toks[1:]
    return " ".join(toks)


def _sr_clean_addr(addr):
    a = re.sub(r"\([^)]*\)", " ", addr or "").split(",")[0]
    a = re.sub(r"(일대|번지)", " ", a)
    return re.sub(r"\s+", " ", a).strip()


def _sr_normalize_region(r1, r2):
    r1 = (r1 or "").strip()
    sido = SR_ALIAS_TO_SIDO.get(r1, r1)
    sgg = (r2 or "").strip()
    if sido == "전남광주통합특별시" and (r1.startswith("광주") or sgg in SR_GWANGJU_GU) and sgg and not sgg.startswith("광주"):
        sgg = "광주" + sgg
    return sido, (sgg or sido)


def _sr_iget(item, name):
    if name in item:
        return _sr_s(item.get(name))
    low = name.lower()
    for k, v in item.items():
        if k.lower() == low:
            return _sr_s(v)
    return ""


def _sr_hhmm(v):
    t = re.sub(r"[^0-9]", "", v or "")
    if not t or len(t) > 4:
        return ""
    t = t.zfill(4)
    h, mi = int(t[:2]), int(t[2:])
    return "" if h > 24 or mi > 59 else f"{h:02d}:{mi:02d}"


def _sr_range(a, b):
    a, b = _sr_hhmm(a), _sr_hhmm(b)
    return f"{a}~{b}" if a and b else ""


def _sr_extra(cat, item):
    out = {}
    if cat == "주차장":
        out["요금"] = _sr_iget(item, "parkingchrgeInfo") or _sr_iget(item, "요금정보")
        bt, bc = _sr_iget(item, "basicTime"), _sr_iget(item, "basicCharge")
        at, ac = _sr_iget(item, "addUnitTime"), _sr_iget(item, "addUnitCharge")
        detail = []
        if bt and bc:
            detail.append(f"기본 {bt}분 {_sr_int(bc):,}원" if _sr_int(bc) is not None else f"기본 {bt}분 {bc}원")
        if at and ac:
            detail.append(f"추가 {at}분당 {_sr_int(ac):,}원" if _sr_int(ac) is not None else f"추가 {at}분 {ac}원")
        out["요금상세"] = " · ".join(detail)
        out["운영평일"] = _sr_range(_sr_iget(item, "weekdayOperOpenHhmm"), _sr_iget(item, "weekdayOperColseHhmm"))
        out["운영토요일"] = _sr_range(_sr_iget(item, "satOperOperOpenHhmm"), _sr_iget(item, "satOperCloseHhmm"))
        out["운영공휴일"] = _sr_range(_sr_iget(item, "holidayOperOpenHhmm"), _sr_iget(item, "holidayCloseOpenHhmm"))
    elif cat == "자동심장충격기":
        org, place = _sr_iget(item, "org"), _sr_iget(item, "buildPlace")
        out["설치장소"] = " ".join(x for x in (org, place) if x)
        days = [_sr_range(_sr_iget(item, f"{d}SttTme"), _sr_iget(item, f"{d}EndTme"))
                for d in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")]
        out["사용시간"] = ",".join(days) if any(days) else ""
        weeks = [_sr_iget(item, f"sun{w}Yon").upper()[:1] for w in ("Frt", "Scd", "Thi", "Fur", "Fif")]
        out["일요일사용"] = "".join(w if w in ("Y", "N") else "-" for w in weeks) if any(weeks) else ""
    elif cat == "교통사고위험지역":
        sclas, wlkg, lclas = _sr_iget(item, "sclas"), _sr_iget(item, "wlkg"), _sr_iget(item, "lclas")
        hour, death = _sr_int(_sr_iget(item, "occu_tm")), _sr_int(_sr_iget(item, "death")) or 0
        out["사고건수"] = 1
        out["보행자사고"] = 1 if ("사람" in sclas or "보행" in sclas or wlkg not in ("", "0", "N", "n")) else 0
        out["야간사고"] = 1 if (hour is not None and (hour >= 18 or hour < 6)) else 0
        out["중상이상"] = 1 if (death > 0 or "사망" in lclas or "중상" in lclas) else 0
    return out


# API 응답에서 자료 기준일·수정일 찾기 (칸 이름이 API마다 달라 이름에 들어간 단어로 찾음)
SR_DATE_KEYS = ("referencedate", "stdr", "crtr", "lastupdt", "updt", "update", "mdfcn", "modif", "lastmod", "regist")


def _sr_find_date(item):
    for want in SR_DATE_KEYS:
        for k, v in item.items():
            if want in k.lower().replace("_", ""):
                m = re.search(r"((?:19|20)\d{2})[-./]?(\d{2})[-./]?(\d{2})", str(v))
                if m:
                    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    return ""


def _sr_make_row(cat, item, stats):
    road = jibun = area = kind = sido_code = roadtype = ""
    crs = None
    if cat == "상습결빙지역":
        lon, lat, crs, area = _sr_num(item.get("x")), _sr_num(item.get("y")), 3857, _sr_s(item.get("area_name"))
        roadtype = _sr_s(item.get("road_name"))
        if roadtype not in SR_ROAD_TYPES:
            roadtype = ""
    elif cat == "교통사고위험지역":
        lon, lat, crs, sido_code = _sr_num(item.get("x")), _sr_num(item.get("y")), 3857, _sr_s(item.get("ctprvn_cd"))
    elif cat == "주차장":
        road, jibun = _sr_s(item.get("rdnmadr")), _sr_s(item.get("lnmadr"))
        lon, lat, kind = _sr_num(item.get("longitude")), _sr_num(item.get("latitude")), _sr_s(item.get("prkplceSe"))
    else:
        road = _sr_s(item.get("buildAddress"))
        lon, lat = _sr_num(item.get("wgs84Lon")), _sr_num(item.get("wgs84Lat"))
    if jibun == road:
        jibun = ""
    addr = road or jibun
    coords = _sr_to_wgs84(lon, lat, crs)
    pre = _sr_sido_from_address(road) or _sr_sido_from_address(jibun) or _sr_sido_from_address(area)
    if not pre and sido_code:
        pre = SR_CTPRVN.get(sido_code[:2], "기타")
    if pre and pre not in SR_LIVE_SIDOS:
        stats["선택지역 외"] += 1
        return None
    if not pre:
        if coords and not any(SR_SIDO_BBOX[s][0] <= coords[0] <= SR_SIDO_BBOX[s][2] and
                              SR_SIDO_BBOX[s][1] <= coords[1] <= SR_SIDO_BBOX[s][3] for s in SR_LIVE_SIDOS):
            stats["선택지역 외"] += 1
            return None
        if not coords and not addr:
            stats["좌표·주소 없음"] += 1
            return None
    if not coords:
        hit = _sr_geocode(_sr_clean_addr(addr)) or (_sr_geocode(_sr_clean_addr(jibun)) if road and jibun else None)
        if not hit:
            stats["지오코딩 실패"] += 1
            return None
        coords = (hit["x"], hit["y"])
    lon, lat = coords
    reg = _sr_kakao_region(lon, lat)
    if not reg:
        stats["역지오코딩 실패"] += 1
        return None
    sido, sgg = _sr_normalize_region(reg["r1"], reg["r2"])
    if sido not in SR_LIVE_SIDOS:
        stats["선택지역 외"] += 1
        return None
    emd = re.sub(r"\d+가$", "", (reg.get("r3") or "").strip())
    if not emd:
        found = re.findall(r"([가-힣0-9]+(?:읍|면|동))", addr or "")
        emd = found[-1] if found else "읍면동없음"
    if not addr:
        addr = _sr_address_of(lon, lat)
    disp = _sr_strip_sido(addr)
    gubun = cat
    name = ""
    if cat == "주차장":
        gubun = "민영주차장" if "민영" in kind else "공영주차장"
        name = _sr_s(item.get("prkplceNm"))
    elif cat == "자동심장충격기":
        name = _sr_s(item.get("org"))
    elif cat == "상습결빙지역" and roadtype:
        disp = f"{disp} ({roadtype})" if disp else f"{sgg} {roadtype}"
    if not disp:
        disp = f"{sgg} {emd}".strip()
    row = {"구분": gubun, "시도": sido, "시군구": sgg, "읍면동": emd, "주소": disp,
           "위도": round(lat, 7), "경도": round(lon, 7), "시설명": name, "자료수정일": _sr_find_date(item)}
    row.update(_sr_extra(cat, item))
    return row


def _sr_collect(cat):
    stats, rows, seen = Counter(), [], {}
    for items in _sr_fetch(cat):
        for it in items:
            stats["수신"] += 1
            if cat == "교통사고위험지역":
                # 같은 지점 사고는 카카오 부르기 전에 미리 합침 (결과는 exe와 같고 호출 수만 줄어듦)
                c = _sr_to_wgs84(_sr_num(it.get("x")), _sr_num(it.get("y")), 3857)
                if c:
                    k = (round(c[1], 6), round(c[0], 6))
                    if k in seen:
                        if True:
                            ex = _sr_extra(cat, it)
                            for col in ("사고건수", "보행자사고", "야간사고", "중상이상"):
                                seen[k][col] += ex[col]
                            stats["같은 지점 사고 합침"] += 1
                        continue
            try:
                row = _sr_make_row(cat, it, stats)
            except _SrStop:
                raise
            except RuntimeError:
                stats["통신 오류"] += 1
                continue
            if cat == "교통사고위험지역":
                if row:
                    if c:
                        seen[k] = row
                    rows.append(row)
                continue
            if not row:
                continue
            key = (row["구분"], round(row["위도"], 6), round(row["경도"], 6), row["주소"])
            if key in seen:
                stats["중복"] += 1
                continue
            seen[key] = row
            rows.append(row)
    return rows, stats


def _sr_rows_to_csv(cat, rows):
    cols = SR_LIVE_COLS + SR_LIVE_EXTRA.get(cat, [])
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore")
    w.writeheader()
    for r in rows:
        w.writerow(r)
    return buf.getvalue().encode("utf-8")


def _sr_csv_to_df(data):
    df = pd.read_csv(io.BytesIO(data), dtype=str, keep_default_na=False)
    df["위도"] = pd.to_numeric(df["위도"], errors="coerce")
    df["경도"] = pd.to_numeric(df["경도"], errors="coerce")
    return df[df["위도"].notna() & df["경도"].notna()].reset_index(drop=True)


def _sr_live_load_store():
    """서버 시작 후 처음: 저장소에 보관된 마지막 자료를 읽음"""
    for cat, obj in SR_LIVE_OBJ.items():
        got = _sr_store_get(f"{obj}.csv")
        if not got:
            continue
        try:
            df = _sr_csv_to_df(got[0])
        except Exception:
            continue
        if len(df):
            _SR_LIVE["data"][cat], _SR_LIVE["at"][cat], _SR_LIVE["count"][cat] = df, got[1], len(df)
    _SR_LIVE["ver"] += 1


def _sr_live_refresh(due, old_counts):
    try:
        for cat in due:
            try:
                _SR_LIVE["note"][cat] = ""
                _SR_LIVE["cur"], _SR_LIVE["prog"] = cat, "시작"
                _sr_heartbeat(force=True)
                rows, stats = _sr_collect(cat)
                old = old_counts.get(cat, 0)
                if old and len(rows) < old * SR_LIVE_SHRINK_GUARD:
                    raise RuntimeError(f"받은 건수가 너무 적음 ({len(rows):,} / 기존 {old:,})")
                if not rows:
                    raise RuntimeError("받은 자료 없음")
                data = _sr_rows_to_csv(cat, rows)
                kept = "저장소 보관" if _sr_store_put(f"{SR_LIVE_OBJ[cat]}.csv", data, "text/csv") else "저장소 보관 실패"
                df = _sr_csv_to_df(data)
                _SR_LIVE["data"][cat], _SR_LIVE["at"][cat], _SR_LIVE["count"][cat] = df, time.time(), len(df)
                _SR_LIVE["note"][cat] = f"{len(df):,}건 · " + ", ".join(f"{k} {v:,}" for k, v in stats.items()) + f" · {kept}"
                _SR_LIVE["ver"] += 1
            except _SrStop as e:
                _SR_LIVE["note"][cat] = f"중단: {e}"
                break
            except Exception as e:
                _SR_LIVE["note"][cat] = f"갱신 실패: {e}"
                _SR_LIVE["at"][cat] = time.time() - SR_LIVE_REFRESH_SEC + 86400   # 실패하면 하루 뒤 다시
            finally:
                _sr_kakao_save()
    finally:
        _SR_LIVE["busy"] = False
        _SR_LIVE["cur"], _SR_LIVE["prog"] = "", ""
        try:
            _sr_store_put("refresh_lock.txt", b'{"t": 0}', "application/json")
        except Exception:
            pass


SR_LOCK_STALE = 20 * 60     # '받는 중' 표시가 20분 넘게 안 바뀌면 그 서버는 꺼진 걸로 봄 (재배포 등)


# 이번 배포 표시: 같은 배포의 서버끼리는 같은 값. 재배포하면 바뀜
SR_DEPLOY_ID = os.environ.get("RENDER_GIT_COMMIT", "") + "|" + str(int(os.path.getmtime(os.path.abspath(__file__))))


def _sr_lock_write(t):
    info = {"t": t, "deploy": SR_DEPLOY_ID, "cur": _SR_LIVE.get("cur", ""), "prog": _SR_LIVE.get("prog", ""),
            "kakao": sum(_SR_KAKAO_USE["n"].values()), "mem": _sr_mem_mb()}
    _sr_store_put("refresh_lock.txt", json.dumps(info, ensure_ascii=False).encode("utf-8"), "application/json")


def _sr_mem_mb():
    """이 서버 프로세스가 지금 쓰는 메모리(MB). Render Starter는 512MB가 한도"""
    try:
        with open("/proc/self/status") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) // 1024
    except Exception:
        pass
    return 0


def _sr_heartbeat(force=False):
    """받는 중인 서버가 1분마다 '아직 받는 중 + 어디까지 받았는지'를 저장소에 씀"""
    now = time.time()
    if _SR_LIVE["busy"] and (force or now - _SR_LIVE.get("beat", 0) > 60):
        _SR_LIVE["beat"] = now
        try:
            _sr_lock_write(now)
        except Exception:
            pass


def _sr_lock_info():
    """받는 중인 서버가 남긴 표시 → {"t": 마지막 소식 시각(끝났으면 0), "cur": 항목, "prog": 진행, "kakao": 카카오 횟수}"""
    got = _sr_store_get("refresh_lock.txt")
    if not got:
        return {"t": 0.0}
    try:
        d = json.loads(got[0].decode("utf-8"))
        return d if isinstance(d, dict) else {"t": float(d)}
    except ValueError:
        return {"t": 0.0}


def _sr_lock_time():
    """받는 중인 서버의 마지막 소식 시각. 이전 배포의 서버가 남긴 표시는 무시 (재배포하면 그 서버는 꺼졌으니 바로 다시 받음)"""
    info = _sr_lock_info()
    if info.get("deploy") != SR_DEPLOY_ID:
        return 0.0
    return float(info.get("t") or 0)


def _sr_live_reload_due(due, now):
    """다른 프로세스가 이미 새로 받아 저장소에 올렸으면 그걸 읽어옴 (10분에 한 번만 확인)"""
    if now - _SR_LIVE.get("checked", 0) < 600:
        return
    _SR_LIVE["checked"] = now
    for cat in due:
        got = _sr_store_get(f"{SR_LIVE_OBJ[cat]}.csv")
        if got and got[1] > _SR_LIVE["at"].get(cat, 0) and now - got[1] < SR_LIVE_REFRESH_SEC:
            try:
                df = _sr_csv_to_df(got[0])
            except Exception:
                continue
            if len(df):
                _SR_LIVE["data"][cat], _SR_LIVE["at"][cat], _SR_LIVE["count"][cat] = df, got[1], len(df)
                _SR_LIVE["ver"] += 1


def _sr_is_night():
    h = datetime.now(KST).hour
    return SR_NIGHT_HOURS[0] <= h < SR_NIGHT_HOURS[1]


def _sr_night_loop():
    """아무도 접속 안 하는 새벽에도 갱신이 시작되게 10분마다 확인 (토글 ON일 때만)"""
    time.sleep(300)
    while True:
        try:
            if _sr_is_night() and feature_detail_on():
                b = load_df()
                cnt = b["구분"].value_counts().to_dict()
                cnt["주차장"] = cnt.get("공영주차장", 0) + cnt.get("민영주차장", 0)
                sr_live_tick(cnt)
        except Exception as e:
            print("안전로드 새벽 갱신 확인 실패:", e)
        time.sleep(600)


if os.environ.get("SR_LIVE_AUTO", "1") != "0":
    threading.Thread(target=_sr_night_loop, daemon=True).start()


def sr_live_tick(excel_counts):
    """토글 ON 상태에서 지도 자료·관리자 페이지를 부를 때: 처음이면 저장소 자료를 읽고, 7일 지난 항목은 뒤에서 새로 받음"""
    if os.environ.get("SR_LIVE_AUTO", "1") == "0":
        return
    with _SR_LIVE_LOCK:
        now = time.time()
        if not _SR_LIVE["loaded"]:
            _SR_LIVE["loaded"] = True
            _SR_LIVE["checked"] = now
            _sr_live_load_store()
        if _SR_LIVE["busy"]:
            return
        due = [c for c in SR_LIVE_CATS if now - _SR_LIVE["at"].get(c, 0) > SR_LIVE_REFRESH_SEC]
        if due:
            _sr_live_reload_due(due, now)
            due = [c for c in SR_LIVE_CATS if now - _SR_LIVE["at"].get(c, 0) > SR_LIVE_REFRESH_SEC]
        if not _sr_is_night():
            due = [c for c in due if c not in _SR_LIVE["data"]]      # 낮에는 처음 받는 항목만
        if not due:
            return
        # 여러 서버 프로세스가 동시에 받지 않게 저장소에 '받는 중' 표시 (끝나면 지움, 6시간 지나면 무시)
        if now - _sr_lock_time() < SR_LOCK_STALE:
            return
        _SR_LIVE["busy"] = True
        _SR_LIVE["beat"] = now
        _SR_LIVE["cur"], _SR_LIVE["prog"] = due[0], "시작"
        _sr_lock_write(now)
        old = {c: (_SR_LIVE["count"].get(c) or excel_counts.get(c, 0)) for c in due}
        threading.Thread(target=_sr_live_refresh, args=(due, old), daemon=True).start()


def sr_live_status():
    now = time.time()
    if _SR_LIVE["busy"]:
        info = {"t": _SR_LIVE.get("beat", now), "cur": _SR_LIVE.get("cur", ""), "prog": _SR_LIVE.get("prog", ""),
                "kakao": sum(_SR_KAKAO_USE["n"].values()), "mem": _sr_mem_mb()}
    else:
        info = _sr_lock_info()
        if info.get("deploy") != SR_DEPLOY_ID:
            info = {"t": 0}
    running = now - float(info.get("t") or 0) < SR_LOCK_STALE
    out = []
    for cat in SR_LIVE_CATS:
        at = _SR_LIVE["at"].get(cat)
        has = cat in _SR_LIVE["data"] and now - (at or 0) < SR_LIVE_REFRESH_SEC
        note, busy = _SR_LIVE["note"].get(cat, ""), False
        if running and info.get("cur") == cat:
            ago = int((now - float(info["t"])) // 60)
            note = (f"{info.get('prog') or '시작'} · 카카오 {int(info.get('kakao') or 0):,}회"
                    f" · 메모리 {int(info.get('mem') or 0)}MB · {'방금' if ago < 1 else f'{ago}분 전'} 소식")
            busy = True
        elif running and not has and not note:
            note, busy = "차례 기다리는 중", True
        elif not running and cat in _SR_LIVE["data"] and not has and not note:
            note = f"새벽 {SR_NIGHT_HOURS[0]}~{SR_NIGHT_HOURS[1]}시에 새로 받음"
        out.append({"cat": cat, "count": _SR_LIVE["count"].get(cat, 0), "busy": busy,
                    "date": datetime.fromtimestamp(at, KST).strftime("%Y-%m-%d") if at and cat in _SR_LIVE["data"] else "",
                    "note": note})
    return out


@app.route("/api/admin/feature", methods=["GET"])
@admin_required
def admin_get_feature():
    try:
        v, err = _fetch_feature()
    except Exception as e:
        v, err = None, str(e)
    if err and _FEATURE_CACHE["v"] is None:
        return jsonify(ok=False, on=False, error=err)
    if err:
        v = _FEATURE_CACHE["v"]          # 잠깐 응답이 늦은 것: 직전 값 그대로 (화면에 OFF로 잘못 안 보이게)
    else:
        _FEATURE_CACHE.update(v=v, t=time.time())
    try:
        if v:
            _b = load_df()
            _cnt = _b["구분"].value_counts().to_dict()
            _cnt["주차장"] = _cnt.get("공영주차장", 0) + _cnt.get("민영주차장", 0)
            sr_live_tick(_cnt)
        live = sr_live_status()
        live.append({"cat": "서버 메모리", "count": 0, "date": "", "busy": False,
                     "note": "", "sub": f"지금 {_sr_mem_mb()}MB 사용 (한도 512MB)", "mem": True})
        _d = _SR_LIVE_DF["df"]
        _n = int((_d["구분"] == "공중화장실").sum()) if _d is not None else 0   # 안전로드에 실제로 나오는 건수 (4개 지역)
        live.insert(0, {"cat": "공중화장실", "count": _n, "date": trip_toilet_data_date() if _n else "",
                        "note": "", "sub": "출장 도구함 화장실 자료 중 광주·전남·전북·제주"})
    except Exception as e:
        live = [{"cat": "자동 갱신", "count": 0, "date": "", "note": f"상태 확인 실패: {e}"}]
    return jsonify(ok=True, on=v, live=live)


@app.route("/api/admin/feature", methods=["POST"])
@admin_required
def admin_set_feature():
    on = bool((request.get_json() or {}).get("on"))
    if not SUPABASE_URL or not SUPABASE_KEY:
        return jsonify(ok=False, error="Supabase 환경변수 없음")
    try:
        r = requests.post(f"{SUPABASE_URL}/rest/v1/app_settings",
                          headers=_sb_headers({"Prefer": "resolution=merge-duplicates,return=minimal"}),
                          json={"key": FEATURE_KEY, "value": "on" if on else "off"}, timeout=5)
        if r.status_code >= 400:
            return jsonify(ok=False, error="저장 실패 — app_settings 표가 있는지 확인 (" + str(r.status_code) + ")")
    except Exception as e:
        return jsonify(ok=False, error=str(e))
    _FEATURE_CACHE.update(v=on, t=time.time())
    return jsonify(ok=True, on=on)





@app.route("/api/admin/login", methods=["POST"])
def admin_login():
    data = request.get_json(silent=True) or {}
    if str(data.get("password", "")) == ADMIN_PASSWORD:
        session["safety_admin"] = True
        return jsonify({"ok": True})
    return jsonify({"ok": False}), 401
# ===== 관리자: 코멘트 전체 조회 =====
@app.route("/api/admin/comments", methods=["GET"])
@admin_required
def admin_get_comments():

    if not SUPABASE_URL or not SUPABASE_KEY:

        return jsonify({"comments": []})

    try:

        headers = {

            "apikey": SUPABASE_KEY,

            "Authorization": f"Bearer {SUPABASE_KEY}",

            "Content-Type": "application/json"

        }

        r = requests.get(

            f"{SUPABASE_URL}/rest/v1/spot_comments?order=created_at.desc&limit=1000",

            headers=headers

        )

        rows = r.json()
        if not isinstance(rows, list):
            return jsonify({"comments": []})
        for row in rows:
            row["created_at"] = kst_iso(row.get("created_at"))
        return jsonify({"comments": rows})
    except Exception as e:
        return jsonify({"comments": []})
# ===== 관리자: 코멘트 삭제 =====

@app.route("/api/admin/comments/<int:comment_id>", methods=["DELETE"])
@admin_required
def admin_delete_comment(comment_id):

    if not SUPABASE_URL or not SUPABASE_KEY:

        return jsonify({"ok": False})

    try:

        headers = {

            "apikey": SUPABASE_KEY,

            "Authorization": f"Bearer {SUPABASE_KEY}",

            "Content-Type": "application/json"

        }

        r = requests.delete(

            f"{SUPABASE_URL}/rest/v1/spot_comments?id=eq.{comment_id}",

            headers=headers

        )

        return jsonify({"ok": r.status_code < 300})

    except Exception as e:

        return jsonify({"ok": False})





# ===== 관리자: 별점 전체 조회 =====

@app.route("/api/admin/ratings", methods=["GET"])
@admin_required
def admin_get_ratings():

    if not SUPABASE_URL or not SUPABASE_KEY:

        return jsonify({"ratings": []})

    try:

        headers = {

            "apikey": SUPABASE_KEY,

            "Authorization": f"Bearer {SUPABASE_KEY}",

            "Content-Type": "application/json"

        }

        r = requests.get(

            f"{SUPABASE_URL}/rest/v1/spot_ratings?order=created_at.desc&limit=1000",

            headers=headers

        )

        rows = r.json()
        if not isinstance(rows, list):
            return jsonify({"ratings": []})
        for row in rows:
            row["created_at"] = kst_iso(row.get("created_at"))
        return jsonify({"ratings": rows})
    except Exception as e:

        return jsonify({"ratings": []})





# ===== 관리자: 별점 삭제 =====

@app.route("/api/admin/ratings/<int:rating_id>", methods=["DELETE"])
@admin_required
def admin_delete_rating(rating_id):

    if not SUPABASE_URL or not SUPABASE_KEY:

        return jsonify({"ok": False})

    try:

        headers = {

            "apikey": SUPABASE_KEY,

            "Authorization": f"Bearer {SUPABASE_KEY}",

            "Content-Type": "application/json"

        }

        r = requests.delete(

            f"{SUPABASE_URL}/rest/v1/spot_ratings?id=eq.{rating_id}",

            headers=headers

        )

        return jsonify({"ok": r.status_code < 300})

    except Exception as e:

        return jsonify({"ok": False})





@app.route("/stats")
@admin_required
def stats():

    try:
        if not SUPABASE_URL or not SUPABASE_KEY:
            return """
            <h2>조회 통계</h2>
            <p>Supabase 환경변수가 없습니다.</p>
            <p><a href="/">돌아가기</a></p>
            """

        headers = {
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}",
            "Content-Type": "application/json"
        }

        res = requests.get(
            f"{SUPABASE_URL}/rest/v1/search_logs?select=*&order=created_at.desc&limit=10000",
            headers=headers
        )

        if res.status_code >= 400:
            return f"""
            <h2>조회 통계 오류</h2>
            <p>Supabase 조회 실패</p>
            <pre>{res.status_code}</pre>
            <pre>{res.text}</pre>
            <p><a href="/">돌아가기</a></p>
            """

        logs = res.json()

        if not isinstance(logs, list) or len(logs) == 0:
            region_stats = pd.DataFrame(columns=["날짜", "시도", "시군구", "읍면동", "조회수"])
            category_stats = pd.DataFrame(columns=["날짜", "위험지역 구분", "체크 수"])
        else:
            df = pd.DataFrame(logs)

            if df.empty or "created_at" not in df.columns:
                region_stats = pd.DataFrame(columns=["날짜", "시도", "시군구", "읍면동", "조회수"])
                category_stats = pd.DataFrame(columns=["날짜", "위험지역 구분", "체크 수"])
            else:
                for col in ["province", "city", "town", "categories", "result_count"]:
                    if col not in df.columns:
                        df[col] = ""

                df["day"] = kst_fmt_series(df["created_at"])

                df["day"] = df["day"].fillna("날짜없음")

                region_stats = (
                    df.groupby(["day", "province", "city", "town"], dropna=False)
                    .size()
                    .reset_index(name="조회수")
                    .sort_values(["day", "조회수"], ascending=[False, False])
                )

                region_stats.columns = ["날짜", "시도", "시군구", "읍면동", "조회수"]

                category_rows = []

                for _, row in df.iterrows():
                    categories = row.get("categories", [])

                    if isinstance(categories, str):
                        try:
                            categories = json.loads(categories)
                        except Exception:
                            categories = [categories] if categories else []

                    if not categories:
                        category_rows.append({
                            "day": row.get("day", ""),
                            "category": "전체",
                            "search_count": 1
                        })
                    else:
                        for cat in categories:
                            category_rows.append({
                                "day": row.get("day", ""),
                                "category": cat,
                                "search_count": 1
                            })

                category_df = pd.DataFrame(category_rows)

                if category_df.empty:
                    category_stats = pd.DataFrame(
                        columns=["날짜", "위험지역 구분", "체크 수"]
                    )
                else:
                    category_stats = (
                        category_df.groupby(["day", "category"], dropna=False)["search_count"]
                        .sum()
                        .reset_index()
                        .sort_values(["day", "search_count"], ascending=[False, False])
                    )

                    category_stats.columns = ["날짜", "위험지역 구분", "체크 수"]

        # 날짜별 앱 다운로드 수
        try:
            dl_res = requests.get(
                f"{SUPABASE_URL}/rest/v1/download_logs?select=*&order=downloaded_at.desc&limit=10000",
                headers=headers
            )

            if dl_res.status_code >= 400:
                download_stats = pd.DataFrame(columns=["날짜", "다운로드 수"])
            else:
                dl_logs = dl_res.json()

                if not isinstance(dl_logs, list) or len(dl_logs) == 0:
                    download_stats = pd.DataFrame(columns=["날짜", "다운로드 수"])
                else:
                    dl_df = pd.DataFrame(dl_logs)

                    if "downloaded_at" not in dl_df.columns:
                        download_stats = pd.DataFrame(columns=["날짜", "다운로드 수"])
                    else:
                        dl_df["day"] = kst_fmt_series(dl_df["downloaded_at"], naive_tz="Asia/Seoul")

                        dl_df["day"] = dl_df["day"].fillna("날짜없음")

                        download_stats = (
                            dl_df.groupby("day", dropna=False)
                            .size()
                            .reset_index(name="다운로드 수")
                            .sort_values("day", ascending=False)
                        )

                        download_stats.columns = ["날짜", "다운로드 수"]

        except Exception as e:
            print("download_logs 조회 실패:", e)
            download_stats = pd.DataFrame(columns=["날짜", "다운로드 수"])

        # 총/오늘 방문자 수 (읽기 전용 조회, 카운트 증가 없음)
        try:
            vs_res = requests.get(
                f"{SUPABASE_URL}/rest/v1/visit_stats?id=eq.1",
                headers=headers
            )
            vs_rows = vs_res.json() if vs_res.status_code < 400 else []
            if isinstance(vs_rows, list) and vs_rows:
                total_visit_count = int(vs_rows[0].get("total_count", 0))
                today_visit_count = int(vs_rows[0].get("today_count", 0))
                if feature_detail_on() and str(vs_rows[0].get("today_date", "")) != str(datetime.now(KST).date()):
                    today_visit_count = 0
            else:
                total_visit_count = 0
                today_visit_count = 0
        except Exception as e:
            print("visit_stats 조회 실패:", e)
            total_visit_count = 0
            today_visit_count = 0

        # 일자별 방문자수 (visit_daily_counts — 개별 시각/IP 없이 날짜별 합계만 저장됨)
        try:
            vl_res = requests.get(
                f"{SUPABASE_URL}/rest/v1/visit_daily_counts?select=visit_date,count&order=visit_date.desc&limit=10000",
                headers=headers
            )
            if vl_res.status_code >= 400:
                visit_daily_df = pd.DataFrame(columns=["날짜", "방문수"])
            else:
                vl_logs = vl_res.json()
                if not isinstance(vl_logs, list) or len(vl_logs) == 0:
                    visit_daily_df = pd.DataFrame(columns=["날짜", "방문수"])
                else:
                    vldf = pd.DataFrame(vl_logs)
                    visit_daily_df = vldf.rename(columns={"visit_date": "날짜", "count": "방문수"})[["날짜", "방문수"]]
        except Exception as e:
            print("visit_daily_counts 조회 실패:", e)
            visit_daily_df = pd.DataFrame(columns=["날짜", "방문수"])

        def _daily_chart_json(df, value_cols, limit_days=10):
            if df is None or df.empty:
                return "[]"
            d = df[df["날짜"] != "날짜없음"].copy()
            d = d.sort_values("날짜").tail(limit_days)
            records = []
            for _, row in d.iterrows():
                rec = {"date": row["날짜"]}
                for col in value_cols:
                    rec[col] = row[col]
                records.append(rec)
            return json.dumps(records, ensure_ascii=False)

        visit_chart_data = _daily_chart_json(visit_daily_df, ["방문수"])

        return render_template_string("""
        <!DOCTYPE html>
        <html lang="ko">
        <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=5.0, user-scalable=yes">
        <title>조회 통계</title>
        <style>
        *{ touch-action: pan-x pan-y pinch-zoom; }
        body{
          font-family:Malgun Gothic, sans-serif;
          padding:24px;
          background:#f8fafc;
        }
        table{
          border-collapse:collapse;
          width:100%;
          background:white;
          margin-bottom:30px;
        }
        .table-wrap{
          overflow-x:auto;
          margin-bottom:12px;
          border:1px solid #ddd;
          border-radius:6px;
        }
        .table-wrap table{
          margin-bottom:0;
        }
        .table-wrap table tbody tr{
          display:none;
        }
        .table-wrap table tbody tr.pg-visible{
          display:table-row;
        }
        .pg-controls{
          display:flex;
          gap:6px;
          margin:0 0 26px;
          flex-wrap:nowrap;
          overflow-x:auto;
          -webkit-overflow-scrolling:touch;
          padding-bottom:6px;
        }
        @media (min-width:769px){
          .pg-controls{
            justify-content:center;
          }
        }
        @media (max-width:480px){
          body{
            padding:12px;
          }
          .pg-controls{
            gap:4px;
          }
          .pg-num{
            padding:5px 7px;
            font-size:12px;
          }
          .pg-nav{
            padding-left:4px;
            padding-right:4px;
            min-width:20px;
          }
        }
        .pg-num{
          flex:0 0 auto;
          padding:6px 12px;
          border:1px solid #cbd5e1;
          background:white;
          color:#334155;
          border-radius:6px;
          cursor:pointer;
          font-size:13px;
        }
        .pg-num.active{
          background:#2563eb;
          border-color:#2563eb;
          color:white;
          font-weight:700;
        }
        .pg-nav{
          font-weight:700;
          color:#2563eb;
          padding-left:6px;
          padding-right:6px;
          min-width:26px;
        }
        .pg-num:disabled{
          opacity:0.35;
          cursor:default;
        }
        th,td{
          border:1px solid #ddd;
          padding:8px;
          font-size:14px;
          text-align:left;
        }
        th{
          background:#e5e7eb;
        }
        .btn{
          display:inline-block;
          padding:10px 14px;
          background:#2563eb;
          color:white;
          text-decoration:none;
          border-radius:8px;
          margin-bottom:18px;
        }
        .btn-del{
          padding:4px 10px;
          background:#ef4444;
          color:white;
          border:none;
          border-radius:6px;
          cursor:pointer;
          font-size:13px;
          margin-right:4px;
        }
        .btn-goto{
          padding:4px 10px;
          background:#2563eb;
          color:white;
          border:none;
          border-radius:6px;
          cursor:pointer;
          font-size:13px;
        }
        pre{
          white-space:pre-wrap;
          background:#111827;
          color:#f9fafb;
          padding:12px;
          border-radius:8px;
        }
        .page-nav{
          display:flex;
          gap:6px;
          margin:18px 0 22px;
          flex-wrap:nowrap;
          overflow-x:auto;
          -webkit-overflow-scrolling:touch;
          padding-bottom:4px;
        }
        .page-btn{
          flex:1 1 0;
          min-width:0;
          padding:10px 4px;
          border:1px solid #cbd5e1;
          background:white;
          color:#334155;
          border-radius:8px;
          cursor:pointer;
          font-size:12px;
          font-weight:600;
          white-space:nowrap;
          overflow:hidden;
          text-overflow:ellipsis;
        }
        .page-btn.active{
          background:#2563eb;
          border-color:#2563eb;
          color:white;
        }
        .page-panel{
          display:none;
        }
        .page-panel.active{
          display:block;
        }
        .stat-cards{
          display:flex;
          gap:14px;
          margin-bottom:18px;
          flex-wrap:nowrap;
        }
        .stat-card{
          flex:1 1 0;
          min-width:0;
          background:white;
          border:1px solid #e2e8f0;
          border-radius:10px;
          padding:14px 16px;
          text-align:center;
        }
        .stat-card .num{
          font-size:24px;
          font-weight:800;
          color:#2563eb;
        }
        .stat-card .lbl{
          font-size:12.5px;
          color:#64748b;
          margin-top:2px;
        }
        @media (max-width:600px){
          .page-nav{
            flex-wrap:nowrap;
            gap:4px;
          }
          .page-btn{
            flex:1 1 0;
            min-width:0;
            padding:8px 2px;
            font-size:12px;
            white-space:nowrap;
            overflow:hidden;
            text-overflow:clip;
          }
          .stat-cards{
            gap:8px;
          }
          .stat-card{
            padding:10px 6px;
          }
          .stat-card .num{
            font-size:19px;
          }
          .stat-card .lbl{
            font-size:11px;
            white-space:nowrap;
          }
        }
        .chart-box{
          background:white;
          border:1px solid #e2e8f0;
          border-radius:10px;
          padding:16px;
          margin-bottom:22px;
        }
        .chart-box canvas{
          max-height:280px;
        }
        </style>
        <script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
        {% if detail_on %}
<link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/variable/pretendardvariable-dynamic-subset.min.css">
        {% raw %}<style id="sr-theme-admin">
        /* ===== 관리자 페이지 새 디자인 (스위치 ON 일 때만) ===== */
        body{font-family:'Pretendard Variable','Pretendard','Apple SD Gothic Neo','Malgun Gothic',sans-serif;background:#f6f7fb;color:#111827;letter-spacing:-0.01em;}
        h2{font-size:22px;font-weight:900;letter-spacing:-0.02em;margin:6px 0 14px;}
        h3{font-size:16px;font-weight:900;}
        .btn{padding:9px 16px;border-radius:12px;font-weight:700;font-size:14px;}
        .btn[href="/"]{background:#fff;color:#374151;border:1px solid #eceef3;}
        .page-btn{border:1px solid #eceef3;border-radius:12px;font-weight:700;color:#4b5563;}
        .page-btn.active{box-shadow:none;}
        .stat-card,.chart-box{border:1px solid #eceef3;border-radius:16px;box-shadow:0 1px 2px rgba(17,24,39,.04),0 8px 24px rgba(17,24,39,.05);}
        .stat-card .num{font-weight:900;}
        .table-wrap{border:1px solid #eceef3;border-radius:14px;background:#fff;}
        .table-wrap table,table[border]{border:0;border-collapse:collapse;}
        th,td{border:none;border-bottom:1px solid #f1f2f6;padding:10px 12px;font-size:13.5px;}
        th{background:#f9fafb;color:#4b5563;font-weight:700;}
        .pg-num{border:1px solid #eceef3;border-radius:8px;}
        .btn-del,.btn-goto{border-radius:8px;font-weight:700;}
        .btn-del{background:#fff;color:#dc2626;border:1px solid #fecaca;}
        .btn-goto{background:#eff6ff;color:#1d4ed8;border:1px solid #dbeafe;}
        .ft-card{border:1px solid #eceef3;border-radius:18px;}
        </style>{% endraw %}
        {% endif %}
        </head>
        <body>

        <h2>조회 통계</h2>

        <a class="btn" href="/">돌아가기</a>
        <a class="btn" href="/stats_excel">엑셀 다운로드</a>

        <div class="page-nav">
          <button class="page-btn active" data-page="0" onclick="goToPage(0)">방문자</button>
          <button class="page-btn" data-page="1" onclick="goToPage(1)">지역</button>
          <button class="page-btn" data-page="2" onclick="goToPage(2)">위험</button>
          <button class="page-btn" data-page="3" onclick="goToPage(3)">코멘트</button>
          <button class="page-btn" data-page="4" onclick="goToPage(4)">별점</button>
          <button class="page-btn" data-page="5" onclick="goToPage(5)">어플</button>
        </div>

        <div class="page-panel active" data-page="0">
          <h3>👥 방문자 통계</h3>
          <div class="stat-cards">
            <div class="stat-card">
              <div class="num">{{ total_visit_count }}</div>
              <div class="lbl">총 방문자</div>
            </div>
            <div class="stat-card">
              <div class="num">{{ today_visit_count }}</div>
              <div class="lbl">오늘 방문자</div>
            </div>
          </div>
          <div class="chart-box">
            <canvas id="visitChart"></canvas>
          </div>
          <h3>📅 일자별 방문자 수</h3>
          <div class="table-wrap">{{ visit_daily_table|safe }}</div>
          <div class="pg-controls" id="pg-visitDailyTable"></div>
        </div>

        <div class="page-panel" data-page="1">
          <h3>날짜별·지역별 조회 수</h3>
          <div class="table-wrap">{{ region_table|safe }}</div>
          <div class="pg-controls" id="pg-regionTable"></div>
        </div>

        <div class="page-panel" data-page="2">
          <h3>날짜별·위험지역 체크 수</h3>
          <div class="table-wrap">{{ category_table|safe }}</div>
          <div class="pg-controls" id="pg-categoryTable"></div>
        </div>

        <div class="page-panel" data-page="3">
          <h3>💬 코멘트 관리</h3>
          <div id="commentAdminArea">불러오는 중...</div>
        </div>

        <div class="page-panel" data-page="4">
          <h3>⭐ 별점 관리</h3>
          <div id="ratingAdminArea">불러오는 중...</div>
        </div>

        <div class="page-panel" data-page="5">
          <h3>📥 날짜별 앱 다운로드 수</h3>
          <div class="table-wrap">{{ download_table|safe }}</div>
          <div class="pg-controls" id="pg-downloadTable"></div>
        </div>

        <style>
        .ft-card{background:#fff;border-radius:14px;padding:14px 18px;margin:28px 0 16px;box-shadow:0 1px 4px rgba(0,0,0,.08);max-width:620px;}
        .ft-switch{position:relative;display:inline-block;width:56px;height:30px;vertical-align:middle;}
        .ft-switch input{opacity:0;width:0;height:0;}
        .ft-slider{position:absolute;inset:0;background:#cbd5e1;border-radius:30px;transition:.2s;cursor:pointer;}
        .ft-slider:before{content:"";position:absolute;width:24px;height:24px;left:3px;top:3px;background:#fff;border-radius:50%;transition:.2s;box-shadow:0 1px 3px rgba(0,0,0,.2);}
        .ft-switch input:checked + .ft-slider{background:#22c55e;}
        .ft-switch input:checked + .ft-slider:before{transform:translateX(26px);}
        .ft-state{display:inline-block;padding:2px 10px;border-radius:8px;font-weight:800;font-size:13px;}
        </style>
        {% if detail_on %}
        {# 데이터 갱신 프로그램(exe) 내려받기 카드는 뺌 — 토글 ON이면 서버가 7일마다 직접 받음 #}
        {% endif %}
        <div class="ft-card">
          <div style="display:flex;align-items:center;gap:12px;">
            <div style="font-size:16px;font-weight:800;">안전로드 Ver.2</div>
            <label class="ft-switch"><input type="checkbox" id="featureDetailToggle" onchange="setFeatureDetail(this.checked)"><span class="ft-slider"></span></label>
            <span id="featureDetailState" class="ft-state" style="background:#f1f5f9;color:#64748b;">확인 중</span>
          </div>
          <div id="srLiveStatus" style="margin-top:10px;font-size:12.5px;color:#475569;line-height:1.7;"></div>
        </div>

        <script>
        function goToPage(n){
          document.querySelectorAll('.page-btn').forEach(b=>{
            b.classList.toggle('active', b.dataset.page == n);
          });
          document.querySelectorAll('.page-panel').forEach(p=>{
            p.classList.toggle('active', p.dataset.page == n);
          });
          setTimeout(()=>{
            if(window._dailyCharts){
              Object.values(window._dailyCharts).forEach(c=>{ try{ c.resize(); }catch(e){} });
            }
          }, 0);
        }

        function paginateTable(tableId, pageSize){
          pageSize = pageSize || 10;
          const windowSize = window.innerWidth <= 480 ? 5 : 10;
          const table = document.getElementById(tableId);
          if(!table) return;
          const tbody = table.querySelector('tbody');
          if(!tbody) return;
          const rows = Array.from(tbody.querySelectorAll('tr'));
          const controls = document.getElementById('pg-' + tableId);
          const totalPages = Math.max(1, Math.ceil(rows.length / pageSize));
          let currentPage = 1;

          function makeBtn(label, page, disabled, extraClass){
            const b = document.createElement('button');
            b.textContent = label;
            b.className = 'pg-num' + (extraClass ? ' ' + extraClass : '');
            if(disabled){
              b.disabled = true;
            } else {
              b.onclick = ()=>{ currentPage = page; render(); };
            }
            return b;
          }

          function render(){
            rows.forEach((r,i)=>{
              r.classList.toggle('pg-visible', i >= (currentPage-1)*pageSize && i < currentPage*pageSize);
            });
            if(controls){
              controls.innerHTML = '';

              const windowStart = Math.floor((currentPage-1)/windowSize) * windowSize + 1;
              const windowEnd = Math.min(windowStart + windowSize - 1, totalPages);

              controls.appendChild(makeBtn('«', 1, currentPage===1, 'pg-nav'));
              controls.appendChild(makeBtn('‹', Math.max(1, windowStart-1), windowStart===1, 'pg-nav'));

              for(let p=windowStart; p<=windowEnd; p++){
                controls.appendChild(makeBtn(String(p), p, false, p===currentPage ? 'active' : ''));
              }

              controls.appendChild(makeBtn('›', Math.min(totalPages, windowEnd+1), windowEnd===totalPages, 'pg-nav'));
              controls.appendChild(makeBtn('»', totalPages, windowEnd===totalPages, 'pg-nav'));

              controls.scrollLeft = 0;
            }
          }
          render();
        }

        function _esc(s){
          return String(s == null ? '' : s).replace(/[&<>"']/g, function(ch){
            return ch === '&' ? '&amp;' : ch === '<' ? '&lt;' : ch === '>' ? '&gt;' : ch === '"' ? '&quot;' : '&#39;';
          });
        }
        function _sid(s){ return String(s == null ? '' : s).replace(/[^0-9]/g, ''); }
        async function loadAdminComments(){
          const res = await fetch('/api/admin/comments');
          const d = await res.json();
          const area = document.getElementById('commentAdminArea');
          if(!d.comments || d.comments.length===0){
            area.innerHTML='<p style="color:#94a3b8;">등록된 코멘트가 없습니다.</p>';
            return;
          }
          let html = '<div class="table-wrap"><table id="commentsTable"><thead><tr><th>ID</th><th>지점번호</th><th>내용</th><th>작성일시</th><th>삭제/이동</th></tr></thead><tbody>';
          d.comments.forEach(c=>{
            html += `<tr>
              <td>${_esc(c.id)}</td>
              <td>${_esc(c.spot_gubun || '')} ${_esc(c.spot_id)}</td>
              <td style="max-width:300px;word-break:break-all;">${_esc(c.content)}</td>
              <td>${c.created_at ? c.created_at.slice(0,16).replace('T',' ') : ''}</td>
              <td style="white-space:nowrap;">
                <button class="btn-del" onclick="deleteComment(${Number(c.id)}, this)">삭제</button>
                <button class="btn-goto" onclick="gotoSpot('${_sid(c.spot_id)}', ${Number(c.spot_lat) || 0}, ${Number(c.spot_lng) || 0}, '${_esc(c.spot_gubun || '')}')">이동</button>
              </td>
            </tr>`;
          });
          html += '</tbody></table></div><div class="pg-controls" id="pg-commentsTable"></div>';
          area.innerHTML = html;
          paginateTable('commentsTable', 10);
        }

        async function deleteComment(id, btn){
          if(!confirm('이 코멘트를 삭제하시겠습니까?')) return;
          btn.disabled = true;
          btn.textContent = '삭제중...';
          const res = await fetch('/api/admin/comments/' + id, {method:'DELETE'});
          const d = await res.json();
          if(d.ok){
            loadAdminComments();
          } else {
            btn.disabled = false;
            btn.textContent = '삭제';
            alert('삭제 실패');
          }
        }

        async function loadAdminRatings(){
          const res = await fetch('/api/admin/ratings');
          const d = await res.json();
          const area = document.getElementById('ratingAdminArea');
          if(!d.ratings || d.ratings.length===0){
            area.innerHTML='<p style="color:#94a3b8;">등록된 별점이 없습니다.</p>';
            return;
          }
          let html = '<div class="table-wrap"><table id="ratingsTable"><thead><tr><th>ID</th><th>지점번호</th><th>별점</th><th>작성일시</th><th>삭제/이동</th></tr></thead><tbody>';
          d.ratings.forEach(r=>{
            const stars = '★'.repeat(r.score||0) + '☆'.repeat(5-(r.score||0));
            html += `<tr>
              <td>${_esc(r.id)}</td>
              <td>${_esc(r.spot_gubun || '')} ${_esc(r.spot_id)}</td>
              <td style="color:#f59e0b;font-weight:700;letter-spacing:1px;">${stars} (${r.score}점)</td>
              <td>${r.created_at ? r.created_at.slice(0,16).replace('T',' ') : ''}</td>
              <td style="white-space:nowrap;">
                <button class="btn-del" onclick="deleteRating(${Number(r.id)}, this)">삭제</button>
                <button class="btn-goto" onclick="gotoSpot('${_sid(r.spot_id)}', ${Number(r.spot_lat) || 0}, ${Number(r.spot_lng) || 0}, '${_esc(r.spot_gubun || '')}')">이동</button>
              </td>
            </tr>`;
          });
          html += '</tbody></table></div><div class="pg-controls" id="pg-ratingsTable"></div>';
          area.innerHTML = html;
          paginateTable('ratingsTable', 10);
        }

        async function deleteRating(id, btn){
          if(!confirm('이 별점을 삭제하시겠습니까?')) return;
          btn.disabled = true;
          btn.textContent = '삭제중...';
          const res = await fetch('/api/admin/ratings/' + id, {method:'DELETE'});
          const d = await res.json();
          if(d.ok){
            loadAdminRatings();
          } else {
            btn.disabled = false;
            btn.textContent = '삭제';
            alert('삭제 실패');
          }
        }

        async function gotoSpot(spotId, lat, lng, gubun){
          if(lat && lng){   // 저장된 좌표가 있으면 그 위치로 바로 이동
            window.location.href = '/?goto_spot=' + encodeURIComponent(spotId) + '&lat=' + lat + '&lng=' + lng + '&gubun=' + encodeURIComponent(gubun || '');
            return;
          }
          try{
            const res = await fetch('/api/spot_location?spot_id=' + encodeURIComponent(spotId));
            const d = await res.json();
            if(d.lat && d.lng){
              window.location.href = '/?goto_spot=' + encodeURIComponent(spotId) + '&lat=' + d.lat + '&lng=' + d.lng;
            } else {
              alert('해당 지점의 좌표를 찾을 수 없습니다. (지점번호: ' + spotId + ')');
            }
          }catch(e){
            alert('이동 오류: ' + e.message);
          }
        }

        window._dailyCharts = {};

        function renderDailyChart(canvasId, labels, dataSets, chartType){
          const el = document.getElementById(canvasId);
          if(!el || typeof Chart === 'undefined') return;
          if(!labels.length){
            el.parentElement.innerHTML = '<p style="color:#94a3b8;">표시할 데이터가 없습니다.</p>';
            return;
          }
          // 모바일: 최근 7일만, 날짜는 "11/2"처럼 짧게, 글자 기울이지 않음
          const isMobileView = window.matchMedia('(max-width: 600px)').matches;
          let showLabels = labels;
          let showSets = dataSets;
          if(isMobileView){
            const n = Math.min(7, labels.length);
            showLabels = labels.slice(-n).map(function(d){
              const m = String(d).match(/^[0-9]{4}-([0-9]{2})-([0-9]{2})/);
              return m ? (parseInt(m[1], 10) + '/' + parseInt(m[2], 10)) : d;
            });
            showSets = dataSets.map(function(ds){
              return Object.assign({}, ds, { data: ds.data.slice(-n) });
            });
          }
          window._dailyCharts[canvasId] = new Chart(el, {
            type: chartType || 'bar',
            data: {
              labels: showLabels,
              datasets: showSets
            },
            options: {
              responsive: true,
              maintainAspectRatio: false,
              plugins: { legend: { display: dataSets.length > 1 } },
              scales: {
                y: { beginAtZero: true },
                x: { ticks: isMobileView ? { maxRotation: 0, minRotation: 0, autoSkip: false, font: { size: 11 } } : {} }
              }
            }
          });
        }

        function initCharts(){
          const visitData = {{ visit_chart_data|safe }};
          renderDailyChart(
            'visitChart',
            visitData.map(r => r.date),
            [{ label: '방문수', data: visitData.map(r => r['방문수']), backgroundColor: '#2563eb' }]
          );
        }

        paginateTable('visitDailyTable', 10);
        paginateTable('regionTable', 10);
        paginateTable('categoryTable', 10);
        paginateTable('downloadTable', 10);
        function showFeatureDetail(on, msg){
          const t = document.getElementById('featureDetailToggle');
          const st = document.getElementById('featureDetailState');
          if(t) t.checked = !!on;
          if(!st) return;
          if(msg){ st.textContent = msg; st.style.background = '#fee2e2'; st.style.color = '#991b1b'; return; }
          st.textContent = on ? 'ON' : 'OFF';
          st.style.background = on ? '#dcfce7' : '#f1f5f9';
          st.style.color = on ? '#166534' : '#64748b';
        }
        async function loadFeatureDetail(){
          try{
            const r = await fetch('/api/admin/feature');
            const d = await r.json();
            showFeatureDetail(d.on, d.ok ? '' : (d.error || '확인 실패'));
            const box = document.getElementById('srLiveStatus');
            if(box && d.live){
              const e = t => String(t == null ? '' : t).replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'})[c]);
              const badge = (t, bg, fg) => '<span style="flex:none;padding:3px 9px;border-radius:999px;font-size:12px;font-weight:800;background:' + bg + ';color:' + fg + ';white-space:nowrap;">' + t + '</span>';
              box.innerHTML = '<div style="font-weight:800;color:#334155;margin-bottom:6px;">자료 자동 갱신 <span style="font-weight:500;color:#94a3b8;">· ON일 때 7일마다 새벽 2~5시</span></div>' + d.live.map(x => {
                const n = String(x.note || '');
                let b, sub = x.sub || '';
                if(x.busy && n !== '차례 기다리는 중'){ b = badge('받는 중', '#dbeafe', '#1d4ed8'); sub = n; }
                else if(n === '차례 기다리는 중'){ b = badge('대기', '#f1f5f9', '#64748b'); }
                else if(/^(갱신 실패|중단)/.test(n)){ b = badge(n.indexOf('중단') === 0 ? '중단' : '실패', '#fee2e2', '#b91c1c'); sub = n.replace(/^(갱신 실패|중단): ?/, ''); }
                else if(x.mem){ b = badge(e(String(x.sub).replace(/^지금 | 사용.*$/g, '')), '#f1f5f9', '#475569'); sub = '한도 512MB · 넘으면 서버가 재시작됨'; }
                else if(x.date){ if(/^새벽/.test(n)) sub = n; b = badge(e(x.date.slice(5).replace('-', '.')) + ' · ' + Number(x.count || 0).toLocaleString() + '건', '#dcfce7', '#15803d'); }
                else { b = badge('엑셀 사용', '#f1f5f9', '#64748b'); sub = sub || n; }
                return '<div style="padding:7px 0;border-top:1px solid #f1f5f9;">'
                  + '<div style="display:flex;align-items:center;justify-content:space-between;gap:8px;"><span style="font-weight:700;color:#334155;">' + e(x.cat) + '</span>' + b + '</div>'
                  + (sub ? '<div style="font-size:11.5px;color:#94a3b8;margin-top:3px;word-break:keep-all;">' + e(sub) + '</div>' : '')
                  + '</div>';
              }).join('');
              clearTimeout(window._srLiveTimer); window._srLiveTimer = null;
              if(d.live.some(x => x.busy)){
                box.innerHTML += '<div style="font-size:11.5px;color:#94a3b8;margin-top:4px;">10초마다 저절로 새로 고침</div>';
                window._srLiveTimer = setTimeout(function(){ window._srLiveTimer = null; loadFeatureDetail(); }, 10000);
              } else {
                window._srLiveTimer = 1;   // 다 끝났으면 자동 새로 고침 멈춤
              }
            }
          }catch(e){ showFeatureDetail(false, '확인 실패'); }
          if(!window._srLiveTimer){ window._srLiveTimer = setTimeout(function(){ window._srLiveTimer = null; loadFeatureDetail(); }, 10000); }
        }
        async function setFeatureDetail(on){
          showFeatureDetail(on, '');
          try{
            const r = await fetch('/api/admin/feature', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({on: on})});
            const d = await r.json();
            if(!d.ok){ alert('저장 실패: ' + (d.error || '')); showFeatureDetail(!on, ''); return; }
            showFeatureDetail(d.on, '');
          }catch(e){ alert('저장 실패: ' + e.message); showFeatureDetail(!on, ''); }
        }
        loadFeatureDetail();
        loadAdminComments();
        loadAdminRatings();
        initCharts();
        </script>
        {% if detail_on %}
        {% raw %}
        <style id="sr-admin2">
        body{max-width:1000px;margin:0 auto;padding:22px 20px 40px;background:#f3f5f9;}
        h2{font-size:24px;margin:4px 0 14px;}
        .btn{display:inline-flex;align-items:center;height:38px;padding:0 16px;margin:0 6px 16px 0;border-radius:12px;background:#fff!important;color:#374151!important;border:1px solid #e6e9ef;font-size:13.5px;font-weight:700;box-shadow:0 1px 2px rgba(17,24,39,.04);}
        .btn[href="/stats_excel"]{background:linear-gradient(135deg,#2563eb,#3b82f6)!important;color:#fff!important;border-color:transparent;box-shadow:0 4px 14px rgba(37,99,235,.25);}
        .page-nav{gap:4px;padding:5px;margin:0 0 16px;background:#e9edf4;border-radius:16px;}
        .page-btn{border:none!important;background:transparent!important;color:#64748b!important;border-radius:12px!important;padding:10px 4px!important;font-size:13.5px!important;font-weight:800!important;}
        .page-btn.active{background:#fff!important;color:#1d4ed8!important;box-shadow:0 2px 8px rgba(17,24,39,.08)!important;}
        .page-panel.active{background:#fff;border-radius:22px;padding:22px;box-shadow:0 1px 2px rgba(17,24,39,.04),0 12px 32px rgba(17,24,39,.06);}
        .page-panel h3{font-size:16px;margin:4px 0 14px;}
        .page-panel h3 ~ h3{margin-top:26px;}
        .stat-cards{gap:10px!important;margin-bottom:16px;flex-wrap:wrap!important;}
        .stat-card{flex:1 1 140px!important;text-align:left!important;padding:16px!important;border:none!important;border-radius:16px!important;background:#f6f8fc!important;box-shadow:none!important;position:relative;}
        .stat-card .num{font-size:26px!important;color:#111827!important;letter-spacing:-0.02em;}
        .stat-card .lbl{font-size:12.5px!important;color:#6b7280!important;font-weight:600;margin-top:4px!important;}
        .stat-card .ico{width:34px;height:34px;border-radius:11px;display:flex;align-items:center;justify-content:center;margin-bottom:12px;}
        .stat-card .delta{position:absolute;right:14px;top:16px;font-size:11.5px;font-weight:800;padding:3px 8px;border-radius:999px;}
        .delta.up{background:#dcfce7;color:#15803d;} .delta.down{background:#fee2e2;color:#b91c1c;} .delta.same{background:#eef2f7;color:#64748b;}
        .chart-box{border:none!important;box-shadow:none!important;background:#fff;padding:0!important;margin-bottom:18px!important;}
        .sr-chart{position:relative;height:260px;}
        .sr-chart canvas{max-height:none!important;}
        .sr-grid2{display:grid;grid-template-columns:1.3fr 1fr;gap:14px;margin-bottom:18px;}
        .sr-sub{background:#f9fafc;border:1px solid #eef1f6;border-radius:18px;padding:16px;}
        .sr-sub-t{font-size:13.5px;font-weight:800;color:#111827;margin-bottom:10px;}
        .sr-sub-t span{font-weight:600;color:#9ca3af;font-size:12px;margin-left:4px;}
        .sr-g-cat{grid-template-columns:1fr 1.3fr;}
        .sr-rsum{grid-template-columns:1fr 1.4fr;align-items:stretch;}
        .sr-rcards{margin:0!important;display:grid!important;grid-template-columns:1fr 1fr;}
        .sr-rcards .stat-card{flex:none!important;}
        .sr-legend{display:flex;flex-direction:column;gap:8px;margin-top:12px;}
        .sr-legend div{display:flex;align-items:center;gap:8px;font-size:13px;color:#374151;font-weight:600;}
        .sr-legend i{width:10px;height:10px;border-radius:3px;flex-shrink:0;}
        .sr-legend b{margin-left:auto;color:#111827;}
        .sr-stars{display:flex;flex-direction:column;gap:7px;}
        .sr-stars div{display:flex;align-items:center;gap:8px;font-size:12.5px;color:#4b5563;font-weight:700;}
        .sr-stars .bar{flex:1;height:8px;border-radius:8px;background:#eef1f6;overflow:hidden;}
        .sr-stars .bar span{display:block;height:100%;border-radius:8px;background:linear-gradient(90deg,#f59e0b,#fbbf24);}
        .table-wrap{border:1px solid #eef1f6!important;border-radius:16px!important;}
        th{background:#f8fafc!important;font-size:12.5px!important;color:#6b7280!important;}
        td{font-size:13.5px!important;}
        tbody tr:hover td{background:#fafbff;}
        .pg-num{border:none!important;background:#f3f5f9!important;border-radius:10px!important;font-weight:700;}
        .pg-num.active{background:#2563eb!important;color:#fff!important;}
        .ft-card{max-width:none!important;border:none!important;border-radius:22px!important;padding:18px 22px!important;box-shadow:0 1px 2px rgba(17,24,39,.04),0 12px 32px rgba(17,24,39,.06)!important;}
        @media (max-width:700px){
          body{padding:14px 12px 30px;}
          .page-panel.active{padding:16px;border-radius:18px;}
          .sr-grid2,.sr-g-cat,.sr-rsum{grid-template-columns:1fr!important;}
          .sr-legend div{white-space:nowrap;}
          .table-wrap td{white-space:nowrap;}
          /* 숫자 카드는 한 줄에 나란히 */
          .stat-cards{display:grid!important;grid-auto-flow:column;grid-auto-columns:minmax(0,1fr);gap:6px!important;}
          .stat-card{padding:11px 8px 10px!important;border-radius:14px!important;text-align:center!important;min-width:0;}
          .stat-card .ico{display:none;}
          .stat-card .num{font-size:18px!important;line-height:1.2;white-space:nowrap;}
          .stat-card .num span{font-size:11px!important;}
          .stat-card .lbl{font-size:11px!important;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;margin-top:2px!important;}
          .stat-card .delta{position:static;display:inline-block;margin-top:5px;font-size:10px;padding:2px 6px;order:3;}
          .stat-card{display:flex!important;flex-direction:column;align-items:center;}
          .sr-chart{height:220px;}
          .page-btn{font-size:12.5px!important;}
        }
        </style>
        <script>
        (function(){
          if(typeof Chart === 'undefined') return;
          Chart.defaults.font.family = "'Pretendard Variable','Pretendard','Malgun Gothic',sans-serif";
          Chart.defaults.color = '#6b7280';
          const isMobile = window.matchMedia('(max-width:700px)').matches;
          const CAT_COLOR = {"상습결빙지역":"#06b6d4","공중화장실":"#f59e0b","교통사고위험지역":"#ef4444","주차장":"#8b5cf6","자동심장충격기":"#16a34a","전체":"#94a3b8"};
          const PALETTE = ['#2563eb','#3b82f6','#60a5fa','#93c5fd','#a5b4fc','#c4b5fd','#cbd5e1','#e2e8f0'];
          function rows(id){
            const t = document.getElementById(id); if(!t) return [];
            return Array.from(t.querySelectorAll('tbody tr')).map(tr => Array.from(tr.children).map(td => td.textContent.trim()));
          }
          function todayStr(){
            const d = new Date(Date.now() + (9*60 + new Date().getTimezoneOffset())*60000);
            return d.getFullYear() + '-' + String(d.getMonth()+1).padStart(2,'0') + '-' + String(d.getDate()).padStart(2,'0');
          }
          function shortDate(d){ const m = String(d).match(/^[0-9]{4}-([0-9]{2})-([0-9]{2})/); return m ? (parseInt(m[1],10) + '/' + parseInt(m[2],10)) : d; }
          function fmt(n){ return Number(n||0).toLocaleString('ko-KR'); }
          function ico(color, svg){ return '<div class="ico" style="background:' + color + '1a;"><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="' + color + '" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">' + svg + '</svg></div>'; }
          const I_USER = '<circle cx="12" cy="8" r="4"/><path d="M4 21c0-4 4-6 8-6s8 2 8 6"/>';
          const I_CAL = '<rect x="3" y="5" width="18" height="16" rx="3"/><path d="M3 10h18M8 3v4M16 3v4"/>';
          const I_TREND = '<path d="M3 17l6-6 4 4 8-8"/><path d="M15 7h6v6"/>';
          const I_SEARCH = '<circle cx="11" cy="11" r="7"/><path d="M21 21l-4.3-4.3"/>';
          const I_DL = '<path d="M12 3v12M7 10l5 5 5-5M4 21h16"/>';
          const I_STAR = '<path d="M12 3l2.8 5.7 6.2.9-4.5 4.4 1 6.2L12 17.3 6.5 20.2l1-6.2L3 9.6l6.2-.9z"/>';
          function card(color, icon, num, lbl, delta){
            return '<div class="stat-card">' + ico(color, icon) + (delta || '') + '<div class="num">' + num + '</div><div class="lbl">' + lbl + '</div></div>';
          }
          function deltaBadge(cur, prev){
            if(!prev) return '';
            const pct = Math.round((cur - prev) / prev * 100);
            const cls = pct > 0 ? 'up' : pct < 0 ? 'down' : 'same';
            return '<span class="delta ' + cls + '">' + (pct > 0 ? '▲ ' : pct < 0 ? '▼ ' : '') + Math.abs(pct) + '%</span>';
          }
          function gradient(ctx, color){
            const g = ctx.createLinearGradient(0, 0, 0, 260);
            g.addColorStop(0, color + '55'); g.addColorStop(1, color + '00');
            return g;
          }
          const baseScales = {
            x: { grid: { display: false }, border: { display: false }, ticks: { maxRotation: 0, autoSkip: true, font: { size: 11 } } },
            y: { beginAtZero: true, grid: { color: '#eef1f6' }, border: { display: false }, ticks: { precision: 0, font: { size: 11 } } }
          };
          const tip = { backgroundColor: '#111827', padding: 10, cornerRadius: 10, titleFont: { weight: '700' }, displayColors: false };
          function mountChart(beforeEl, html){
            const w = document.createElement('div'); w.innerHTML = html; const node = w.firstElementChild;
            beforeEl.parentNode.insertBefore(node, beforeEl); return node;
          }

          /* ── 방문자 ── */
          const vRows = rows('visitDailyTable').filter(r => /^[0-9]{4}-/.test(r[0])).map(r => [r[0], +r[1] || 0]).sort((a,b) => a[0] < b[0] ? -1 : 1);
          const vMap = {}; vRows.forEach(r => vMap[r[0]] = r[1]);
          const today = todayStr();
          const yd = new Date(Date.parse(today) - 86400000).toISOString().slice(0,10);
          const sum = (arr) => arr.reduce((a,b) => a + b, 0);
          const last7 = sum(vRows.slice(-7).map(r => r[1])), prev7 = sum(vRows.slice(-14, -7).map(r => r[1]));
          const sc = document.querySelector('.page-panel[data-page="0"] .stat-cards');
          if(sc){
            const nums = sc.querySelectorAll('.num');
            const total = nums[0] ? nums[0].textContent.trim() : '0', todayN = nums[1] ? nums[1].textContent.trim() : '0';
            sc.innerHTML = card('#2563eb', I_USER, fmt(total.replace(/,/g,'')), '총 방문자')
              + card('#16a34a', I_CAL, fmt(todayN.replace(/,/g,'')), '오늘 방문자', deltaBadge(+todayN.replace(/,/g,''), vMap[yd]))
              + card('#8b5cf6', I_TREND, fmt(last7), '최근 7일', deltaBadge(last7, prev7))
              + card('#f59e0b', I_CAL, fmt(vMap[yd] || 0), '어제 방문자');
          }
          const vc = document.getElementById('visitChart');
          if(vc && vRows.length){
            if(window._dailyCharts && window._dailyCharts.visitChart){ try{ window._dailyCharts.visitChart.destroy(); }catch(e){} }
            const box = vc.closest('.chart-box');
            box.innerHTML = '<div class="sr-sub"><div class="sr-sub-t">일자별 방문자 <span>최근 ' + (isMobile ? 7 : 14) + '일</span></div><div class="sr-chart"><canvas id="visitChart2"></canvas></div></div>';
            const data = vRows.slice(isMobile ? -7 : -14);
            const ctx = document.getElementById('visitChart2').getContext('2d');
            window._dailyCharts.visitChart = new Chart(ctx, {
              type: 'line',
              data: { labels: data.map(r => shortDate(r[0])), datasets: [{ label: '방문자', data: data.map(r => r[1]), borderColor: '#2563eb', backgroundColor: gradient(ctx, '#2563eb'), fill: true, tension: .38, borderWidth: 2.5, pointRadius: 3, pointHoverRadius: 6, pointBackgroundColor: '#fff', pointBorderColor: '#2563eb', pointBorderWidth: 2 }] },
              options: { responsive: true, maintainAspectRatio: false, interaction: { mode: 'index', intersect: false }, plugins: { legend: { display: false }, tooltip: tip }, scales: baseScales }
            });
          }

          /* ── 지역 ── */
          const rRows = rows('regionTable');
          const rp = document.querySelector('.page-panel[data-page="1"]');
          if(rp && rRows.length){
            const byPlace = {}, byDay = {};
            let totalQ = 0, todayQ = 0;
            rRows.forEach(r => {
              const n = +r[4] || 0; totalQ += n; if(r[0] === today) todayQ += n;
              const key = (r[2] && r[2] !== 'None' && r[2] !== 'nan') ? r[2] : (r[1] && r[1] !== 'None' && r[1] !== 'nan' ? r[1] + ' 전체' : '전체 지역');
              byPlace[key] = (byPlace[key] || 0) + n;
              byDay[r[0]] = (byDay[r[0]] || 0) + n;
            });
            const top = Object.entries(byPlace).sort((a,b) => b[1] - a[1]).slice(0, 8);
            const h3 = rp.querySelector('h3');
            const wrap = mountChart(h3, '<div><div class="stat-cards">' + card('#2563eb', I_SEARCH, fmt(totalQ), '전체 조회') + card('#16a34a', I_CAL, fmt(todayQ), '오늘 조회') + card('#8b5cf6', I_TREND, fmt(Object.keys(byPlace).length), '조회된 지역 수') + '</div>'
              + '<div class="sr-grid2"><div class="sr-sub"><div class="sr-sub-t">많이 조회한 지역 <span>상위 8곳</span></div><div class="sr-chart"><canvas id="srRegionTop"></canvas></div></div>'
              + '<div class="sr-sub"><div class="sr-sub-t">일자별 조회 <span>최근 7일</span></div><div class="sr-chart"><canvas id="srRegionDay"></canvas></div></div></div></div>');
            new Chart(document.getElementById('srRegionTop'), {
              type: 'bar',
              data: { labels: top.map(t => t[0]), datasets: [{ data: top.map(t => t[1]), backgroundColor: top.map((t,i) => PALETTE[Math.min(i, PALETTE.length-1)]), borderRadius: 8, borderSkipped: false, barThickness: 16 }] },
              options: { indexAxis: 'y', responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false }, tooltip: tip }, scales: { x: Object.assign({}, baseScales.y), y: { grid: { display: false }, border: { display: false }, ticks: { font: { size: 12, weight: '600' }, color: '#374151' } } } }
            });
            const days = Object.keys(byDay).filter(d => /^[0-9]{4}-/.test(d)).sort().slice(-7);
            new Chart(document.getElementById('srRegionDay'), {
              type: 'bar',
              data: { labels: days.map(shortDate), datasets: [{ data: days.map(d => byDay[d]), backgroundColor: days.map(d => d === today ? '#2563eb' : '#bfdbfe'), borderRadius: 8, borderSkipped: false, maxBarThickness: 26 }] },
              options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false }, tooltip: tip }, scales: baseScales }
            });
          }

          /* ── 위험지역 ── */
          const cRows = rows('categoryTable');
          const cp = document.querySelector('.page-panel[data-page="2"]');
          if(cp && cRows.length){
            const byCat = {}, byDayCat = {};
            cRows.forEach(r => {
              const n = +r[2] || 0; byCat[r[1]] = (byCat[r[1]] || 0) + n;
              (byDayCat[r[0]] = byDayCat[r[0]] || {})[r[1]] = n;
            });
            const cats = Object.entries(byCat).sort((a,b) => b[1] - a[1]);
            const tot = sum(cats.map(c => c[1]));
            const h3 = cp.querySelector('h3');
            mountChart(h3, '<div class="sr-grid2 sr-g-cat"><div class="sr-sub"><div class="sr-sub-t">구분별 비율 <span>전체 기간</span></div><div class="sr-chart" style="height:200px;"><canvas id="srCatPie"></canvas></div><div class="sr-legend">'
              + cats.map(c => '<div><i style="background:' + (CAT_COLOR[c[0]] || '#94a3b8') + '"></i>' + c[0] + '<b>' + fmt(c[1]) + ' <span style="color:#9ca3af;font-weight:600;">(' + Math.round(c[1]/tot*100) + '%)</span></b></div>').join('')
              + '</div></div><div class="sr-sub"><div class="sr-sub-t">일자별 구분 체크 <span>최근 7일</span></div><div class="sr-chart"><canvas id="srCatDay"></canvas></div></div></div>');
            new Chart(document.getElementById('srCatPie'), {
              type: 'doughnut',
              data: { labels: cats.map(c => c[0]), datasets: [{ data: cats.map(c => c[1]), backgroundColor: cats.map(c => CAT_COLOR[c[0]] || '#94a3b8'), borderWidth: 3, borderColor: '#f9fafc', hoverOffset: 6 }] },
              options: { responsive: true, maintainAspectRatio: false, cutout: '68%', plugins: { legend: { display: false }, tooltip: tip } }
            });
            const days = Object.keys(byDayCat).filter(d => /^[0-9]{4}-/.test(d)).sort().slice(-7);
            new Chart(document.getElementById('srCatDay'), {
              type: 'bar',
              data: { labels: days.map(shortDate), datasets: cats.map(c => ({ label: c[0], data: days.map(d => (byDayCat[d] || {})[c[0]] || 0), backgroundColor: CAT_COLOR[c[0]] || '#94a3b8', borderRadius: 4, borderSkipped: false, maxBarThickness: 26 })) },
              options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false }, tooltip: Object.assign({}, tip, { displayColors: true }) }, scales: { x: Object.assign({ stacked: true }, baseScales.x), y: Object.assign({ stacked: true }, baseScales.y) } }
            });
          }

          /* ── 다운로드 ── */
          const dRows = rows('downloadTable').filter(r => /^[0-9]{4}-/.test(r[0])).map(r => [r[0], +r[1] || 0]).sort((a,b) => a[0] < b[0] ? -1 : 1);
          const dp = document.querySelector('.page-panel[data-page="5"]');
          if(dp && dRows.length){
            const dTot = sum(dRows.map(r => r[1]));
            const dMap = {}; dRows.forEach(r => dMap[r[0]] = r[1]);
            const d7 = sum(dRows.slice(-7).map(r => r[1]));
            const h3 = dp.querySelector('h3');
            mountChart(h3, '<div><div class="stat-cards">' + card('#2563eb', I_DL, fmt(dTot), '전체 다운로드') + card('#16a34a', I_CAL, fmt(dMap[today] || 0), '오늘') + card('#8b5cf6', I_TREND, fmt(d7), '최근 7일') + '</div>'
              + '<div class="sr-sub" style="margin-bottom:18px;"><div class="sr-sub-t">일자별 다운로드 <span>최근 14일</span></div><div class="sr-chart"><canvas id="srDl"></canvas></div></div></div>');
            const data = dRows.slice(-14);
            new Chart(document.getElementById('srDl'), {
              type: 'bar',
              data: { labels: data.map(r => shortDate(r[0])), datasets: [{ data: data.map(r => r[1]), backgroundColor: data.map(r => r[0] === today ? '#2563eb' : '#bfdbfe'), borderRadius: 8, borderSkipped: false, maxBarThickness: 26 }] },
              options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false }, tooltip: tip }, scales: baseScales }
            });
          }

          /* ── 모바일: 표는 7줄씩 ── */
          if(isMobile && typeof paginateTable === 'function'){
            const _pg = paginateTable;
            window.paginateTable = paginateTable = function(id, size){ return _pg(id, 7); };
            ['visitDailyTable', 'regionTable', 'categoryTable', 'downloadTable', 'commentsTable', 'ratingsTable'].forEach(function(id){
              if(document.getElementById(id)) _pg(id, 7);
            });
          }

          /* ── 별점 요약 ── */
          function ratingSummary(){
            const area = document.getElementById('ratingAdminArea'); if(!area) return;
            const tb = document.getElementById('ratingsTable'); if(!tb || area.querySelector('.sr-rsum')) return;
            const scores = Array.from(tb.querySelectorAll('tbody tr')).map(tr => { const m = tr.textContent.match(/[(]([0-9])점[)]/); return m ? +m[1] : 0; }).filter(Boolean);
            if(!scores.length) return;
            const avg = (sum(scores) / scores.length).toFixed(1);
            const cnt = [5,4,3,2,1].map(k => scores.filter(x => x === k).length);
            const mx = Math.max.apply(null, cnt) || 1;
            const div = document.createElement('div');
            div.className = 'sr-grid2 sr-rsum';
            div.innerHTML = '<div class="stat-cards sr-rcards">' + card('#f59e0b', I_STAR, avg + '<span style="font-size:15px;color:#9ca3af;font-weight:700;"> / 5</span>', '평균 별점') + card('#2563eb', I_USER, fmt(scores.length), '전체 별점 수') + '</div>'
              + '<div class="sr-sub"><div class="sr-sub-t">점수 분포</div><div class="sr-stars">' + [5,4,3,2,1].map((k,i) => '<div>' + k + '점<div class="bar"><span style="width:' + Math.round(cnt[i]/mx*100) + '%"></span></div>' + cnt[i] + '</div>').join('') + '</div></div>';
            area.insertBefore(div, area.firstChild);
          }
          function commentSummary(){
            const area = document.getElementById('commentAdminArea'); if(!area) return;
            const tb = document.getElementById('commentsTable'); if(!tb || area.querySelector('.sr-csum')) return;
            const trs = Array.from(tb.querySelectorAll('tbody tr'));
            const todayN = trs.filter(tr => (tr.children[3] && tr.children[3].textContent.indexOf(today) === 0)).length;
            const div = document.createElement('div');
            div.className = 'stat-cards sr-csum';
            div.innerHTML = card('#2563eb', '<path d="M21 12a8 8 0 0 1-11.6 7.1L4 20l1.1-4.6A8 8 0 1 1 21 12z"/>', fmt(trs.length), '전체 코멘트') + card('#16a34a', I_CAL, fmt(todayN), '오늘 작성');
            area.insertBefore(div, area.firstChild);
          }
          ['ratingAdminArea', 'commentAdminArea'].forEach(function(id){
            const el = document.getElementById(id); if(!el) return;
            new MutationObserver(function(){ id === 'ratingAdminArea' ? ratingSummary() : commentSummary(); }).observe(el, { childList: true });
            id === 'ratingAdminArea' ? ratingSummary() : commentSummary();
          });
        })();
        </script>
        {% endraw %}
        {% endif %}
        </body>
        </html>
        """,
        region_table=region_stats.to_html(index=False, table_id="regionTable"),
        category_table=category_stats.to_html(index=False, table_id="categoryTable"),
        download_table=download_stats.to_html(index=False, table_id="downloadTable"),
        visit_daily_table=visit_daily_df.to_html(index=False, table_id="visitDailyTable"),
        total_visit_count=total_visit_count,
        today_visit_count=today_visit_count,
        visit_chart_data=visit_chart_data,
        detail_on=feature_detail_on(),
        refresh_exe=refresh_exe_info()
        )

    except Exception as e:
        return f"""
        <h2>조회 통계 오류</h2>
        <p>관리자페이지 처리 중 오류가 발생했습니다.</p>
        <pre>{str(e)}</pre>
        <p><a href="/">돌아가기</a></p>
        """


@app.route("/stats_excel")
@admin_required
def stats_excel():



    try:

        if not SUPABASE_URL or not SUPABASE_KEY:

            return "Supabase 환경변수가 없습니다.", 500



        headers = {

            "apikey": SUPABASE_KEY,

            "Authorization": f"Bearer {SUPABASE_KEY}",

            "Content-Type": "application/json"

        }



        res = requests.get(

            f"{SUPABASE_URL}/rest/v1/search_logs?select=*&order=created_at.desc&limit=10000",

            headers=headers

        )



        if res.status_code >= 400:

            return f"Supabase 조회 실패: {res.status_code} / {res.text}", 500



        logs = res.json()



        if not isinstance(logs, list) or len(logs) == 0:

            return "다운로드할 조회 기록이 없습니다.", 404



        df = pd.DataFrame(logs)



        for col in ["created_at", "province", "city", "town", "categories", "result_count"]:

            if col not in df.columns:

                df[col] = ""



        df["날짜"] = kst_fmt_series(df["created_at"])
        df["조회일시"] = kst_fmt_series(df["created_at"], "%Y-%m-%d %H:%M:%S")



        def category_text(v):

            if isinstance(v, list):

                return ", ".join([str(x) for x in v])

            if isinstance(v, str):

                try:

                    parsed = json.loads(v)

                    if isinstance(parsed, list):

                        return ", ".join([str(x) for x in parsed])

                except Exception:

                    return v

            return ""



        df["위험지역 구분"] = df["categories"].apply(category_text)



        raw_df = df[[

            "조회일시",

            "날짜",

            "province",

            "city",

            "town",

            "위험지역 구분",

            "result_count"

        ]].copy()



        raw_df.columns = [

            "조회일시",

            "날짜",

            "시도",

            "시군구",

            "읍면동",

            "위험지역 구분",

            "조회결과수"

        ]



        region_stats = (

            raw_df.groupby(["날짜", "시도", "시군구", "읍면동"], dropna=False)

            .size()

            .reset_index(name="조회수")

            .sort_values(["날짜", "조회수"], ascending=[False, False])

        )



        category_rows = []



        for _, row in df.iterrows():

            categories = row.get("categories", [])



            if isinstance(categories, str):

                try:

                    categories = json.loads(categories)

                except Exception:

                    categories = [categories] if categories else []



            if not categories:

                category_rows.append({

                    "날짜": row.get("날짜", ""),

                    "위험지역 구분": "전체",

                    "체크 수": 1

                })

            else:

                for cat in categories:

                    category_rows.append({

                        "날짜": row.get("날짜", ""),

                        "위험지역 구분": cat,

                        "체크 수": 1

                    })



        category_df = pd.DataFrame(category_rows)



        if category_df.empty:

            category_stats = pd.DataFrame(columns=["날짜", "위험지역 구분", "체크 수"])

        else:

            category_stats = (

                category_df.groupby(["날짜", "위험지역 구분"], dropna=False)["체크 수"]

                .sum()

                .reset_index()

                .sort_values(["날짜", "체크 수"], ascending=[False, False])

            )



        # 방문자 통계 (총/오늘 + 일자별) — 0.방문자 탭과 동일한 수치, 그래프 제외
        try:
            vs_res = requests.get(
                f"{SUPABASE_URL}/rest/v1/visit_stats?id=eq.1",
                headers=headers
            )
            vs_rows = vs_res.json() if vs_res.status_code < 400 else []
            if isinstance(vs_rows, list) and vs_rows:
                total_visit_count = int(vs_rows[0].get("total_count", 0))
                today_visit_count = int(vs_rows[0].get("today_count", 0))
                if feature_detail_on() and str(vs_rows[0].get("today_date", "")) != str(datetime.now(KST).date()):
                    today_visit_count = 0
            else:
                total_visit_count = 0
                today_visit_count = 0
        except Exception as e:
            print("visit_stats 조회 실패:", e)
            total_visit_count = 0
            today_visit_count = 0

        visit_summary_df = pd.DataFrame({
            "항목": ["총 방문자", "오늘 방문자"],
            "값": [total_visit_count, today_visit_count]
        })

        try:
            vl_res = requests.get(
                f"{SUPABASE_URL}/rest/v1/visit_daily_counts?select=visit_date,count&order=visit_date.desc&limit=10000",
                headers=headers
            )
            if vl_res.status_code >= 400:
                visit_daily_df = pd.DataFrame(columns=["날짜", "방문수"])
            else:
                vl_logs = vl_res.json()
                if not isinstance(vl_logs, list) or len(vl_logs) == 0:
                    visit_daily_df = pd.DataFrame(columns=["날짜", "방문수"])
                else:
                    vldf = pd.DataFrame(vl_logs)
                    visit_daily_df = vldf.rename(columns={"visit_date": "날짜", "count": "방문수"})[["날짜", "방문수"]]
        except Exception as e:
            print("visit_daily_counts 조회 실패:", e)
            visit_daily_df = pd.DataFrame(columns=["날짜", "방문수"])

        # 날짜별 앱 다운로드 수 — 5.다운 탭과 동일
        try:
            dl_res = requests.get(
                f"{SUPABASE_URL}/rest/v1/download_logs?select=*&order=downloaded_at.desc&limit=10000",
                headers=headers
            )
            if dl_res.status_code >= 400:
                download_stats = pd.DataFrame(columns=["날짜", "다운로드 수"])
            else:
                dl_logs = dl_res.json()
                if not isinstance(dl_logs, list) or len(dl_logs) == 0:
                    download_stats = pd.DataFrame(columns=["날짜", "다운로드 수"])
                else:
                    dl_df = pd.DataFrame(dl_logs)
                    if "downloaded_at" not in dl_df.columns:
                        download_stats = pd.DataFrame(columns=["날짜", "다운로드 수"])
                    else:
                        dl_df["day"] = kst_fmt_series(dl_df["downloaded_at"], naive_tz="Asia/Seoul")
                        dl_df["day"] = dl_df["day"].fillna("날짜없음")
                        download_stats = (
                            dl_df.groupby("day", dropna=False)
                            .size()
                            .reset_index(name="다운로드 수")
                            .sort_values("day", ascending=False)
                        )
                        download_stats.columns = ["날짜", "다운로드 수"]
        except Exception as e:
            print("download_logs 조회 실패:", e)
            download_stats = pd.DataFrame(columns=["날짜", "다운로드 수"])

        output = BytesIO()



        with pd.ExcelWriter(output, engine="openpyxl") as writer:

            visit_summary_df.to_excel(writer, index=False, sheet_name="방문자 통계", startrow=0)

            visit_daily_df.to_excel(writer, index=False, sheet_name="방문자 통계", startrow=5)

            writer.sheets["방문자 통계"].cell(row=5, column=1, value="일자별 방문자 수")

            raw_df.to_excel(writer, index=False, sheet_name="전체 조회기록")

            region_stats.to_excel(writer, index=False, sheet_name="지역별 통계")

            category_stats.to_excel(writer, index=False, sheet_name="구분별 통계")

            download_stats.to_excel(writer, index=False, sheet_name="다운로드 통계")



        output.seek(0)



        filename = "safety_map_stats_" + datetime.now(KST).strftime("%Y%m%d_%H%M%S") + ".xlsx"



        response = send_file(

            output,

            as_attachment=True,

            download_name=filename,

            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

        )



        response.headers["Cache-Control"] = "no-store"

        response.headers["Content-Disposition"] = f"attachment; filename={filename}"



        return response


    except Exception as e:

        return f"엑셀 생성 오류: {str(e)}", 500



@app.route("/meta")

def meta():

    df = sr_df()



    provinces = sorted(df["시도"].dropna().astype(str).unique().tolist())

    cities = sorted(df["시군구"].dropna().astype(str).unique().tolist())

    towns = sorted(df["읍면동"].dropna().astype(str).unique().tolist())



    return jsonify({

        "provinces": provinces,

        "cities": cities,

        "towns": towns

    })



@app.route("/cities")

def cities():



    province = safe_str(request.args.get("province",""))



    df = sr_df()



    if province:

        df = df[df["시도"] == province]



    cities = sorted(df["시군구"].dropna().astype(str).unique().tolist())



    return jsonify({"cities":cities})





@app.route("/towns")

def towns():



    province = safe_str(request.args.get("province",""))

    city = safe_str(request.args.get("city",""))



    df = sr_df()



    if province:

        df = df[df["시도"] == province]



    if city:

        df = df[df["시군구"] == city]



    towns = sorted(df["읍면동"].dropna().astype(str).unique().tolist())



    return jsonify({"towns": towns})







@app.route("/data")

def data():



    province = safe_str(request.args.get("province",""))

    city = safe_str(request.args.get("city",""))

    towns = request.args.getlist("town")

    categories = request.args.getlist("category")



    df = sr_df()



    if province:

        df = df[df["시도"] == province]



    if city:

        df = df[df["시군구"] == city]



    if towns:

        df = df[df["읍면동"].isin(towns)]



    if categories:

        df = df[df["구분"].isin(categories)]



    total_count = len(df)



    # 5000개 초과 시 서버 부하 방지: 데이터 전송 없이 경고 반환

    if total_count > 5000:

        return jsonify({

            "total": total_count,

            "too_many": True,

            "data": []

        })



    records = df.apply(row_to_dict, axis=1).tolist()



    return jsonify({

        "total": total_count,

        "too_many": False,

        "data": records

    })



_DATA_ALL_CACHE = {"key": None, "gz": None}
_DATA_ALL_LOCK = threading.Lock()


@app.route("/data/all")

def data_all():
    """지도 전체 자료. 4만여 건을 요청마다 새로 만들면 메모리가 크게 튀어서(서버 재시작 원인),
    자료가 바뀔 때 한 번만 만들어 압축해 두고 그대로 보냄"""
    import gzip
    df = sr_df()
    key = (id(df), bool(feature_detail_on()), len(df))
    with _DATA_ALL_LOCK:
        if _DATA_ALL_CACHE["key"] != key:
            _DATA_ALL_CACHE.update(key=None, gz=None)
            records = df.apply(row_to_dict, axis=1).tolist()
            raw = json.dumps({"total": len(records), "too_many": False, "data": records},
                             ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            del records
            gz = gzip.compress(raw, 6)
            del raw
            _DATA_ALL_CACHE.update(key=key, gz=gz)
        gz = _DATA_ALL_CACHE["gz"]
    if "gzip" in request.headers.get("Accept-Encoding", ""):
        resp = Response(gz, mimetype="application/json")
        resp.headers["Content-Encoding"] = "gzip"
    else:
        resp = Response(gzip.decompress(gz), mimetype="application/json")
    resp.headers["Vary"] = "Accept-Encoding"
    resp.headers["Cache-Control"] = "no-cache"
    return resp


@app.route("/sample-image")

def sample_image():

    category = safe_str(request.args.get("category", "위험지역"))
    city = safe_str(request.args.get("city", ""))
    town = safe_str(request.args.get("town", ""))
    color = TYPE_COLORS.get(category, "#334155")
    category, city, town = html_escape(category), html_escape(city), html_escape(town)



    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="800" height="450">

    <defs>

      <linearGradient id="g" x1="0" y1="0" x2="1" y2="1">

        <stop offset="0%" stop-color="{color}"/>

        <stop offset="100%" stop-color="#0f172a"/>

      </linearGradient>

    </defs>

    <rect width="800" height="450" fill="url(#g)"/>

    <rect x="30" y="30" width="740" height="390" rx="24" fill="rgba(255,255,255,0.12)" stroke="rgba(255,255,255,0.2)"/>

    <text x="50%" y="42%" text-anchor="middle" fill="white" font-size="42" font-family="Arial" font-weight="700">{category}</text>

    <text x="50%" y="54%" text-anchor="middle" fill="white" font-size="24" font-family="Arial">{city} {town}</text>

    <text x="50%" y="70%" text-anchor="middle" fill="white" font-size="18" font-family="Arial">샘플 이미지</text>

    </svg>"""

    return Response(svg, mimetype="image/svg+xml")







def open_preferred_browser(url):

    time.sleep(1.5)



    candidates = [

        r"C:\Program Files\Naver\Naver Whale\Application\whale.exe",

        r"C:\Program Files (x86)\Naver\Naver Whale\Application\whale.exe",

        r"C:\Program Files\Google\Chrome\Application\chrome.exe",

        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",

    ]



    for path in candidates:

        if os.path.exists(path):

            try:

                webbrowser.register("preferred_browser", None, webbrowser.BackgroundBrowser(path))

                webbrowser.get("preferred_browser").open(url)

                return

            except Exception:

                pass



    webbrowser.open(url)






# ================================================================
# ===============  매식비 관리 모듈 (/meal)  =====================
#   - 기존 지도앱 코드와 완전히 분리, /meal 하위 경로로만 동작
#   - 저장소: Supabase REST (meal_teams / meal_members / meal_entries)
#   - 로그인: 비밀번호 3333 (session['meal_authed'])
# ================================================================
import calendar as _meal_calendar
import functools as _meal_functools
from zoneinfo import ZoneInfo as _MealZoneInfo
from flask import redirect as _meal_redirect

MEAL_KST = _MealZoneInfo("Asia/Seoul")
MEAL_FIXED_AMOUNT = 9000
MEAL_MONTHLY_COUNT = 6
MEAL_MONTHLY_CAP = MEAL_FIXED_AMOUNT * MEAL_MONTHLY_COUNT
MEAL_PASSWORD = "7788"
MEAL_ADMIN_PASSWORD = "qwer"   # 백업/복원 관리자 화면 비밀번호
MEAL_BACKUP_SLOTS = 3          # 수동 저장 슬롯 개수 (1~3)
MEAL_AUTO_SLOT = 0             # 복원 직전 자동저장 슬롯
# 공휴일은 기존 meal_backups 테이블의 예약 슬롯에 별도 보관한다.
# 기존 사용자 백업 슬롯(0~3), 매식비 기록 및 안전로드 테이블에는 영향을 주지 않는다.
MEAL_HOLIDAY_MANUAL_SLOT = 9999
MEAL_HOLIDAY_YEAR_SLOT_BASE = 10000
MEAL_HOLIDAY_API_KEY = os.environ.get("MEAL_HOLIDAY_API_KEY", "").strip()
_MEAL_HOLIDAY_LOCK = threading.RLock()
_MEAL_HOLIDAY_RETRY_AFTER = {}


# ---------------------------------------------------------------- Supabase REST
def _meal_headers():
    return {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
    }


def _meal_get(path):
    if not SUPABASE_URL or not SUPABASE_KEY:
        return []
    try:
        r = requests.get(f"{SUPABASE_URL}/rest/v1/{path}",
                         headers=_meal_headers(), timeout=10)
        if r.status_code >= 400:
            print("meal get err:", r.status_code, r.text)
            return []
        return r.json()
    except Exception as e:
        print("meal get exc:", e)
        return []


def _meal_post(table, payload):
    h = _meal_headers()
    h["Prefer"] = "return=representation"
    return requests.post(f"{SUPABASE_URL}/rest/v1/{table}",
                         headers=h, json=payload, timeout=10)


def _meal_patch(table, filt, payload):
    h = _meal_headers()
    h["Prefer"] = "return=representation"
    return requests.patch(f"{SUPABASE_URL}/rest/v1/{table}?{filt}",
                          headers=h, json=payload, timeout=10)


def _meal_delete(table, filt):
    return requests.delete(f"{SUPABASE_URL}/rest/v1/{table}?{filt}",
                           headers=_meal_headers(), timeout=10)


# ---------------------------------------------------------------- 백업 / 복원
def meal_make_snapshot():
    """현재 매식비 데이터 전체(팀/팀원/입력내역)를 하나의 딕셔너리로 묶는다."""
    teams = _meal_get("meal_teams?select=*&order=sort_order.asc,id.asc")
    members = _meal_get("meal_members?select=*&order=id.asc")
    entries = _meal_get("meal_entries?select=*&order=id.asc")
    return {
        "version": 1,
        "saved_at": datetime.now(MEAL_KST).isoformat(),
        "teams": teams,
        "members": members,
        "entries": entries,
        "counts": {
            "teams": len(teams),
            "members": len(members),
            "entries": len(entries),
        },
    }


def _meal_chunks(lst, size):
    for i in range(0, len(lst), size):
        yield lst[i:i + size]


def meal_restore_snapshot(snap):
    """스냅샷으로 현재 데이터를 통째로 교체한다.
    id 충돌/시퀀스 문제를 피하려고, 새 id를 받아 옛 id -> 새 id로 다시 연결한다."""
    teams = snap.get("teams") or []
    members = snap.get("members") or []
    entries = snap.get("entries") or []

    # 1) 기존 데이터 삭제 (자식 -> 부모 순서로)
    _meal_delete("meal_entries", "id=gt.0")
    _meal_delete("meal_members", "id=gt.0")
    _meal_delete("meal_teams", "id=gt.0")

    # 2) 팀 복원 (옛 id -> 새 id)
    team_map = {}
    if teams:
        payload = [{"name": t.get("name", ""),
                    "sort_order": t.get("sort_order", 0)} for t in teams]
        resp = _meal_post("meal_teams", payload)
        if resp.status_code >= 400:
            raise RuntimeError("teams: " + resp.text)
        for old, new in zip(teams, resp.json()):
            team_map[old["id"]] = new["id"]

    # 3) 팀원 복원 (옛 id -> 새 id, team_id 재매핑)
    mem_map = {}
    if members:
        payload = [{"team_id": team_map.get(m.get("team_id")),
                    "name": m.get("name", ""),
                    "active": m.get("active", True)} for m in members]
        resp = _meal_post("meal_members", payload)
        if resp.status_code >= 400:
            raise RuntimeError("members: " + resp.text)
        for old, new in zip(members, resp.json()):
            mem_map[old["id"]] = new["id"]

    # 4) 입력내역 복원 (team_id / member_id 재매핑, 큰 데이터는 나눠 삽입)
    if entries:
        payload = [{"team_id": team_map.get(e.get("team_id")),
                    "member_id": mem_map.get(e.get("member_id")),
                    "d": e.get("d"),
                    "amount": e.get("amount", MEAL_FIXED_AMOUNT),
                    "restaurant": e.get("restaurant") or "",
                    "approver": e.get("approver") or "",
                    "created_at": e.get("created_at")} for e in entries]
        payload = [p for p in payload
                   if p["team_id"] and p["member_id"] and p["d"]]
        for chunk in _meal_chunks(payload, 400):
            resp = _meal_post("meal_entries", chunk)
            if resp.status_code >= 400:
                raise RuntimeError("entries: " + resp.text)


def meal_save_backup(slot, label, snap):
    """slot 자리에 백업을 저장(기존 것 있으면 교체)."""
    _meal_delete("meal_backups", f"slot=eq.{slot}")
    return _meal_post("meal_backups", {
        "slot": slot,
        "label": (label or "").strip()[:60],
        "created_at": datetime.now(MEAL_KST).isoformat(),
        "payload": snap,
    })


def meal_backup_list():
    rows = _meal_get("meal_backups?select=slot,label,created_at,payload&order=slot.asc")
    by_slot = {}
    for r in rows:
        c = (r.get("payload") or {}).get("counts") or {}
        by_slot[r["slot"]] = {
            "slot": r["slot"],
            "label": r.get("label") or "",
            "created_at": r.get("created_at") or "",
            "teams": c.get("teams", 0),
            "members": c.get("members", 0),
            "entries": c.get("entries", 0),
        }
    return by_slot


# ---------------------------------------------------------------- helpers
def meal_today_kst():
    return datetime.now(MEAL_KST).date()


def meal_parse_ym(ym):
    t = meal_today_kst()
    if ym:
        try:
            y, m = ym.split("-")
            y, m = int(y), int(m)
            if 1 <= m <= 12:
                return y, m
        except Exception:
            pass
    return t.year, t.month


def meal_ym_str(y, m):
    return f"{y:04d}-{m:02d}"


def meal_shift_month(y, m, delta):
    idx = y * 12 + (m - 1) + delta
    return idx // 12, idx % 12 + 1


def meal_status_of(count):
    if count == 0:
        return "none"
    if count >= MEAL_MONTHLY_COUNT:
        return "full"
    return "ok"


def meal_ensure_teams():
    """팀이 하나도 없으면 기본 5팀 시드(통합돌봄팀 맨 위)."""
    teams = _meal_get("meal_teams?select=*&order=sort_order.asc,id.asc")
    if teams:
        return teams
    seed = [
        {"name": "통합돌봄팀(TF)", "sort_order": 0},
        {"name": "요양운영1팀", "sort_order": 1},
        {"name": "요양운영2팀", "sort_order": 2},
        {"name": "요양운영3팀", "sort_order": 3},
        {"name": "요양운영4팀", "sort_order": 4},
    ]
    try:
        _meal_post("meal_teams", seed)
    except Exception as e:
        print("meal seed err:", e)
    return _meal_get("meal_teams?select=*&order=sort_order.asc,id.asc")


# ---------------------------------------------------------------- 공휴일 자동 동기화 + 관리자 추가
# 월별 화면/서버 입력 검사 모두 공유하는 저장 데이터: meal_backups 예약 슬롯.
# 공공데이터포털 키가 있으면 한국천문연구원 특일정보를 우선 사용하며,
# 키가 없는 경우 별도 인증키가 필요 없는 Nager.Date 공개 공휴일 API를 사용한다.
# 공개 API는 정부 공식 데이터가 아니므로 임시공휴일 등 업데이트 시차가 있을 수 있다.
def meal_holiday_read_slot(slot):
    rows = _meal_get(f"meal_backups?slot=eq.{slot}&select=slot,payload")
    if rows and isinstance(rows[0].get("payload"), dict):
        return rows[0]["payload"], True
    return {}, False


def meal_holiday_write_slot(slot, payload):
    """기존 백업 API용 테이블을 이용해 서버 재시작 후에도 휴일 데이터를 유지."""
    old, exists = meal_holiday_read_slot(slot)
    now = datetime.now(MEAL_KST).isoformat()
    label = "[시스템] 수동 공휴일" if slot == MEAL_HOLIDAY_MANUAL_SLOT else "[시스템] 공휴일 자동 캐시"
    if exists:
        resp = _meal_patch("meal_backups", f"slot=eq.{slot}",
                           {"payload": payload, "created_at": now})
    else:
        resp = _meal_post("meal_backups", {"slot": slot, "label": label,
                                           "created_at": now, "payload": payload})
    if not resp.ok:
        raise RuntimeError("공휴일 저장소 접근 실패: " + str(resp.status_code))
    return True


def meal_holiday_fetch_official(year):
    """한국천문연구원 특일 정보 제공 서비스: 공휴일 조회(getRestDeInfo)."""
    if not MEAL_HOLIDAY_API_KEY:
        raise RuntimeError("공공데이터 인증키가 설정되지 않았습니다.")
    url = "https://apis.data.go.kr/B090041/openapi/service/SpcdeInfoService/getRestDeInfo"
    res = requests.get(url, params={"serviceKey": MEAL_HOLIDAY_API_KEY,
                                    "solYear": str(year), "numOfRows": "200",
                                    "pageNo": "1", "_type": "json"}, timeout=9)
    res.raise_for_status()
    try:
        data = res.json()
        reply = data["response"]
        if str(reply["header"]["resultCode"]).strip() not in ("00", "0"):
            raise ValueError("공휴일 API 응답 오류")
        body = reply["body"]
        if int(body.get("totalCount", 0)) > 200:
            raise ValueError("공휴일 결과가 한 페이지를 초과했습니다.")
        items = (body.get("items") or {}).get("item", [])
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        raise RuntimeError("공공데이터 응답 형식 오류") from exc
    if isinstance(items, dict):
        items = [items]
    days = {}
    for item in items:
        if str(item.get("isHoliday", "Y")).upper() != "Y":
            continue
        raw = str(item.get("locdate", ""))
        try:
            d = datetime.strptime(raw, "%Y%m%d").date().isoformat()
        except ValueError:
            continue
        if d[:4] == str(year):
            name = str(item.get("dateName") or "공휴일").strip()[:60]
            days[d] = name or "공휴일"
    if not days:
        raise RuntimeError("공공데이터에서 해당 연도 공휴일을 받지 못했습니다.")
    return days, "한국천문연구원(공공데이터포털)"


def meal_holiday_fetch_public(year):
    """공공데이터 키가 없는 경우 사용할 수 있는 공개 연간 공휴일 데이터."""
    url = f"https://nagerholidays.com/api/v4/Holidays/KR/{year}"
    res = requests.get(url, timeout=9)
    res.raise_for_status()
    records = res.json()
    if not isinstance(records, list):
        raise RuntimeError("공휴일 조회 응답 형식이 올바르지 않습니다.")
    names_ko = {
        "New Year's Day": "신정", "Independence Movement Day": "삼일절",
        "Children's Day": "어린이날", "Memorial Day": "현충일",
        "Liberation Day": "광복절", "National Foundation Day": "개천절",
        "Hangul Day": "한글날", "Christmas Day": "성탄절",
        "Lunar New Year": "설날", "Seollal": "설날",
        "Chuseok": "추석", "Buddha's Birthday": "부처님오신날",
        "Substitute Holiday": "대체공휴일", "Election Day": "선거일",
    }
    days = {}
    for item in records:
        if not isinstance(item, dict):
            continue
        types = item.get("holidayTypes") or []
        if "Public" not in types or item.get("subdivisionCodes"):
            continue
        d = str(item.get("date") or "")
        try:
            if date.fromisoformat(d).year != year:
                continue
        except ValueError:
            continue
        name = str(item.get("name") or "공휴일").strip()
        days[d] = names_ko.get(name, name)[:60] or "공휴일"
    if not days:
        raise RuntimeError("공개 서비스에서 해당 연도 공휴일을 받지 못했습니다.")
    return days, "Nager.Date(공개 서비스, 정부 공식 데이터 아님)"


def meal_holiday_ensure_year(year, force=False):
    """최초 조회 후 DB 캐시 사용; 올해/내년은 KST 기준 하루 한 번 새로 조회."""
    year = int(year)
    if not 1900 <= year <= 2100:
        return {"days": {}, "checked_at": "", "error": "지원하지 않는 연도"}
    slot = MEAL_HOLIDAY_YEAR_SLOT_BASE + year
    with _MEAL_HOLIDAY_LOCK:
        payload, _ = meal_holiday_read_slot(slot)
        today = meal_today_kst().isoformat()
        checked = str(payload.get("checked_at") or "")[:10]
        attempted = str(payload.get("attempted_at") or "")[:10]
        # 지난 연도의 유효한 공휴일 기록은 재조회하지 않는다.
        if not force and ((checked == today) or
                          (year < meal_today_kst().year and payload.get("days") and checked)):
            return payload
        # 실패 시에도 날짜 화면을 열 때마다 외부 서비스를 연속 호출하지 않음.
        if not force and (attempted == today or
                          _MEAL_HOLIDAY_RETRY_AFTER.get(year, 0) > time.monotonic()):
            return payload
        try:
            if MEAL_HOLIDAY_API_KEY:
                days, source = meal_holiday_fetch_official(year)
            else:
                days, source = meal_holiday_fetch_public(year)
            next_payload = {"days": days, "checked_at": today,
                            "attempted_at": today, "source": source, "error": ""}
            meal_holiday_write_slot(slot, next_payload)
            _MEAL_HOLIDAY_RETRY_AFTER.pop(year, None)
            return next_payload
        except Exception as exc:
            print("meal holiday refresh error:", type(exc).__name__, str(exc)[:200])
            _MEAL_HOLIDAY_RETRY_AFTER[year] = time.monotonic() + 1200
            # 기존 정상 공휴일 목록은 지우지 않고, 수동 공휴일도 별도 슬롯에 남긴다.
            payload = dict(payload)
            payload["attempted_at"] = today
            payload["error"] = "자동 조회 실패: 이전 저장 데이터를 사용 중입니다."
            try:
                meal_holiday_write_slot(slot, payload)
            except Exception:
                pass
            return payload


def meal_holiday_manual_days():
    payload, _ = meal_holiday_read_slot(MEAL_HOLIDAY_MANUAL_SLOT)
    days = payload.get("days")
    return days if isinstance(days, dict) else {}


def meal_holiday_year_view(year, refresh=True):
    auto = meal_holiday_ensure_year(year) if refresh else meal_holiday_read_slot(MEAL_HOLIDAY_YEAR_SLOT_BASE + year)[0]
    days = dict(auto.get("days") or {})
    # 수동 등록이 자동 조회보다 우선한다. 삭제하면 자동 공휴일이 다시 보인다.
    days.update({d: name for d, name in meal_holiday_manual_days().items()
                 if d[:4] == f"{year:04d}"})
    return days, auto


def meal_holiday_name(d):
    """서버 측 입력/수정 검증에서도 동일한 공휴일 데이터를 조회한다."""
    days, _ = meal_holiday_year_view(date.fromisoformat(d).year)
    return days.get(d)


def meal_holiday_js_json(data):
    """관리자가 입력한 공휴일 이름이 script 태그를 종료하지 못하게 보호."""
    return (json.dumps(data, ensure_ascii=False)
            .replace("<", "\\u003c").replace(">", "\\u003e")
            .replace("&", "\\u0026"))


# ---------------------------------------------------------------- login guard
def meal_login_required(fn):
    @_meal_functools.wraps(fn)
    def _wrap(*a, **k):
        if not session.get("meal_authed"):
            if request.path.startswith("/meal/api/"):
                return jsonify(ok=False, error="로그인이 필요해요."), 401
            return _meal_redirect("/meal/login")
        return fn(*a, **k)
    return _wrap


def meal_admin_required(fn):
    @_meal_functools.wraps(fn)
    def _wrap(*a, **k):
        if not session.get("meal_admin_authed"):
            if request.path.startswith("/meal/api/"):
                return jsonify(ok=False, error="관리자 인증이 필요해요."), 401
            return _meal_redirect("/meal/admin/login")
        return fn(*a, **k)
    return _wrap


@app.route("/meal/api/admin/holiday/add", methods=["POST"])
@meal_admin_required
def meal_admin_holiday_add():
    data = request.get_json(silent=True) or {}
    d = str(data.get("date") or "").strip()
    name = str(data.get("name") or "").strip()
    try:
        selected = date.fromisoformat(d)
        if selected.isoformat() != d or not 1900 <= selected.year <= 2100:
            raise ValueError()
    except ValueError:
        return jsonify(ok=False, error="날짜를 올바르게 선택해 주세요."), 400
    if not name or len(name) > 60:
        return jsonify(ok=False, error="공휴일 이름을 1~60자로 입력해 주세요."), 400
    with _MEAL_HOLIDAY_LOCK:
        days = dict(meal_holiday_manual_days())
        days[d] = name
        try:
            meal_holiday_write_slot(MEAL_HOLIDAY_MANUAL_SLOT, {"days": days})
        except Exception:
            return jsonify(ok=False, error="공휴일을 저장하지 못했습니다. 저장소 설정을 확인해 주세요."), 500
    return jsonify(ok=True)


@app.route("/meal/api/admin/holiday/delete", methods=["POST"])
@meal_admin_required
def meal_admin_holiday_delete():
    data = request.get_json(silent=True) or {}
    d = str(data.get("date") or "").strip()
    with _MEAL_HOLIDAY_LOCK:
        days = dict(meal_holiday_manual_days())
        if d not in days:
            return jsonify(ok=False, error="수동으로 등록된 공휴일이 아닙니다."), 404
        days.pop(d)
        try:
            meal_holiday_write_slot(MEAL_HOLIDAY_MANUAL_SLOT, {"days": days})
        except Exception:
            return jsonify(ok=False, error="공휴일 삭제를 저장하지 못했습니다."), 500
    return jsonify(ok=True)


@app.route("/meal/api/admin/holiday/refresh", methods=["POST"])
@meal_admin_required
def meal_admin_holiday_refresh():
    today = meal_today_kst()
    results = {str(y): meal_holiday_ensure_year(y, force=True)
               for y in (today.year, today.year + 1)}
    errors = [f"{y}년: {p.get('error')}" for y, p in results.items() if p.get("error")]
    return jsonify(ok=not errors, errors=errors,
                   error=" / ".join(errors), years={y: len(p.get("days") or {})
                                                for y, p in results.items()})


# ---------------------------------------------------------------- routes
@app.route("/meal/login")
def meal_login_page():
    if session.get("meal_authed"):
        return _meal_redirect("/meal")
    return render_template_string(MEAL_LOGIN_HTML)


@app.route("/meal/api/login", methods=["POST"])
def meal_do_login():
    data = request.get_json(force=True)
    pw = (data.get("password") or "").strip()
    if pw == MEAL_PASSWORD:
        session["meal_authed"] = True
        return jsonify(ok=True)
    return jsonify(ok=False, error="비밀번호가 올바르지 않아요."), 401


@app.route("/meal/logout")
def meal_logout():
    session.pop("meal_authed", None)
    return _meal_redirect("/meal/login")


# ---------------------------------------------------------------- 관리자(백업)
@app.route("/meal/admin/login")
def meal_admin_login_page():
    if session.get("meal_admin_authed"):
        return _meal_redirect("/meal/admin")
    return render_template_string(MEAL_ADMIN_LOGIN_HTML)


@app.route("/meal/api/admin/login", methods=["POST"])
def meal_admin_do_login():
    data = request.get_json(force=True)
    pw = (data.get("password") or "").strip()
    if pw == MEAL_ADMIN_PASSWORD:
        session["meal_admin_authed"] = True
        return jsonify(ok=True)
    return jsonify(ok=False, error="비밀번호가 올바르지 않아요."), 401


@app.route("/meal/admin/logout")
def meal_admin_logout():
    session.pop("meal_admin_authed", None)
    return _meal_redirect("/meal/login")


@app.route("/meal/admin")
@meal_admin_required
def meal_admin_page():
    backups = meal_backup_list()
    now = meal_make_snapshot()["counts"]
    holiday_today = meal_today_kst()
    holiday_years = {y: meal_holiday_ensure_year(y)
                     for y in (holiday_today.year, holiday_today.year + 1)}
    manual_holidays = sorted(meal_holiday_manual_days().items())
    return render_template_string(
        MEAL_ADMIN_HTML,
        slots=list(range(1, MEAL_BACKUP_SLOTS + 1)),
        backups=backups,
        auto=backups.get(MEAL_AUTO_SLOT),
        auto_slot=MEAL_AUTO_SLOT,
        now=now,
        holiday_years=holiday_years, manual_holidays=manual_holidays,
        holiday_today=holiday_today,
    )


@app.route("/meal/api/admin/save", methods=["POST"])
@meal_admin_required
def meal_admin_save():
    data = request.get_json(force=True)
    try:
        slot = int(data.get("slot"))
    except Exception:
        return jsonify(ok=False, error="슬롯이 올바르지 않아요."), 400
    if not (1 <= slot <= MEAL_BACKUP_SLOTS):
        return jsonify(ok=False, error="슬롯이 올바르지 않아요."), 400
    label = data.get("label") or ""
    snap = meal_make_snapshot()
    resp = meal_save_backup(slot, label, snap)
    if resp.status_code >= 400:
        return jsonify(ok=False, error="저장 중 오류가 발생했어요."), 500
    return jsonify(ok=True, counts=snap["counts"])


@app.route("/meal/api/admin/load", methods=["POST"])
@meal_admin_required
def meal_admin_load():
    data = request.get_json(force=True)
    try:
        slot = int(data.get("slot"))
    except Exception:
        return jsonify(ok=False, error="슬롯이 올바르지 않아요."), 400
    rows = _meal_get(f"meal_backups?slot=eq.{slot}&select=payload")
    if not rows:
        return jsonify(ok=False, error="해당 슬롯에 백업이 없어요."), 404
    snap = rows[0].get("payload") or {}
    # 복원 전에 현재 상태를 자동저장본(slot 0)으로 보관 → 실수 복원 되돌리기용
    try:
        cur = meal_make_snapshot()
        meal_save_backup(MEAL_AUTO_SLOT, "복원 직전 자동저장", cur)
    except Exception as e:
        print("meal auto-backup err:", e)
    try:
        meal_restore_snapshot(snap)
    except Exception as e:
        print("meal restore err:", e)
        return jsonify(ok=False, error="복원 중 오류가 발생했어요."), 500
    return jsonify(ok=True)


@app.route("/meal/api/admin/delete", methods=["POST"])
@meal_admin_required
def meal_admin_delete():
    data = request.get_json(force=True)
    try:
        slot = int(data.get("slot"))
    except Exception:
        return jsonify(ok=False, error="슬롯이 올바르지 않아요."), 400
    _meal_delete("meal_backups", f"slot=eq.{slot}")
    return jsonify(ok=True)


@app.route("/meal/admin/download/<int:slot>")
@meal_admin_required
def meal_admin_download(slot):
    rows = _meal_get(f"meal_backups?slot=eq.{slot}&select=payload,created_at")
    if not rows:
        return _meal_redirect("/meal/admin")
    snap = rows[0].get("payload") or {}
    raw = json.dumps(snap, ensure_ascii=False, indent=2)
    stamp = (rows[0].get("created_at") or meal_today_kst().isoformat())[:10]
    fname = f"meal_backup_slot{slot}_{stamp}.json"
    return Response(
        raw, mimetype="application/json; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename={fname}"})


@app.route("/meal/api/admin/restore-file", methods=["POST"])
@meal_admin_required
def meal_admin_restore_file():
    data = request.get_json(force=True)
    snap = data.get("snapshot")
    if not isinstance(snap, dict) or "entries" not in snap:
        return jsonify(ok=False, error="백업 파일 형식이 올바르지 않아요."), 400
    try:
        cur = meal_make_snapshot()
        meal_save_backup(MEAL_AUTO_SLOT, "파일복원 직전 자동저장", cur)
    except Exception as e:
        print("meal auto-backup err:", e)
    try:
        meal_restore_snapshot(snap)
    except Exception as e:
        print("meal file restore err:", e)
        return jsonify(ok=False, error="복원 중 오류가 발생했어요."), 500
    return jsonify(ok=True)


@app.route("/meal")
@meal_login_required
def meal_home():
    # 해당 날짜에 첫 매식비 화면을 열 때 올해/내년 공휴일을 한 번씩 갱신.
    today = meal_today_kst()
    meal_holiday_ensure_year(today.year)
    meal_holiday_ensure_year(today.year + 1)
    teams = meal_ensure_teams()

    # 팀별 변경 알림용 현재 상태 지문.
    # 별도 DB 스키마를 건드리지 않고, 매식비 팀/팀원/입력내역만 기준으로 계산한다.
    import hashlib as _meal_hashlib
    all_members = _meal_get(
        "meal_members?select=id,team_id,name,active&order=id.asc")
    all_entries = _meal_get(
        "meal_entries?select=id,team_id,member_id,d,amount,restaurant,approver,created_at&order=id.asc")

    members_by_team = {}
    for m in all_members:
        members_by_team.setdefault(m.get("team_id"), []).append(m)

    entries_by_team = {}
    for e in all_entries:
        entries_by_team.setdefault(e.get("team_id"), []).append(e)

    for t in teams:
        tid = t.get("id")
        state = {
            "team": {
                "id": tid,
                "name": t.get("name") or "",
                "sort_order": t.get("sort_order"),
            },
            "members": members_by_team.get(tid, []),
            "entries": entries_by_team.get(tid, []),
        }
        raw = json.dumps(state, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":"), default=str)
        t["change_rev"] = _meal_hashlib.sha1(
            raw.encode("utf-8")).hexdigest()

    return render_template_string(MEAL_HOME_HTML, teams=teams,
                                  monthly_count=MEAL_MONTHLY_COUNT,
                                  cap=MEAL_MONTHLY_CAP, amount=MEAL_FIXED_AMOUNT)


@app.route("/meal/team/<int:team_id>")
@meal_login_required
def meal_team_page(team_id):
    ym = request.args.get("ym")
    year, month = meal_parse_ym(ym)

    trows = _meal_get(f"meal_teams?id=eq.{team_id}&select=*")
    if not trows:
        return _meal_redirect("/meal")
    team = trows[0]

    members_all = _meal_get(f"meal_members?team_id=eq.{team_id}&select=*&order=id.asc")
    members = [m for m in members_all if m.get("active", True) is not False]
    prefix = meal_ym_str(year, month)
    rows = _meal_get(
        f"meal_entries?team_id=eq.{team_id}&d=like.{prefix}*"
        f"&select=*&order=d.asc,id.asc")

    member_name = {m["id"]: m["name"] for m in members_all}

    by_date = {}
    for r in rows:
        by_date.setdefault(r["d"], []).append({
            "id": r["id"],
            "member_id": r["member_id"],
            "name": member_name.get(r["member_id"], "?"),
            "restaurant": r.get("restaurant") or "",
            "approver": r.get("approver") or "",
        })

    per_member_days = {m["id"]: [] for m in members}
    for r in rows:
        per_member_days.setdefault(r["member_id"], [])
        per_member_days[r["member_id"]].append(r["d"])

    # 삭제(비활성)된 팀원이라도 이번 달 기록이 있으면 집계에 그대로 표시
    entry_mids = {r["member_id"] for r in rows}
    active_ids = {m["id"] for m in members}
    summary_members = list(members) + [
        m for m in members_all
        if m["id"] not in active_ids and m["id"] in entry_mids]

    summaries = []
    team_total = 0
    full_people = 0
    for m in summary_members:
        cnt = len(per_member_days.get(m["id"], []))
        st = meal_status_of(cnt)
        if st == "full":
            full_people += 1
        team_total += cnt * MEAL_FIXED_AMOUNT
        summaries.append({"id": m["id"], "name": m["name"],
                          "count": cnt, "total": cnt * MEAL_FIXED_AMOUNT,
                          "status": st})

    rest_map = {}
    for r in rows:
        key = (r.get("restaurant") or "").strip() or "미지정"
        if key not in rest_map:
            rest_map[key] = {"name": key, "days": set(), "total": 0}
        rest_map[key]["days"].add(r["d"])
        rest_map[key]["total"] += r.get("amount") or MEAL_FIXED_AMOUNT
    rest_summaries = sorted(
        [{"name": v["name"], "count": len(v["days"]), "total": v["total"]}
         for v in rest_map.values()],
        key=lambda x: x["total"], reverse=True)

    holiday_days, holiday_status = meal_holiday_year_view(year)
    cal = _meal_calendar.Calendar(firstweekday=6)
    today = meal_today_kst()
    weeks = []
    for week in cal.monthdatescalendar(year, month):
        wk = []
        for dt in week:
            ds = dt.strftime("%Y-%m-%d")
            wk.append({
                "day": dt.day,
                "date_str": ds,
                "in_month": dt.month == month,
                "is_today": dt == today,
                "is_weekend": dt.weekday() >= 5,
                "holiday_name": holiday_days.get(ds, ""),
                "entries": by_date.get(ds, []),
            })
        weeks.append(wk)

    member_info = {}
    for m in summary_members:
        days = sorted(per_member_days.get(m["id"], []))
        member_info[m["id"]] = {"name": m["name"], "days": days,
                                "count": len(days), "active": m["id"] in active_ids}

    py, pm = meal_shift_month(year, month, -1)
    ny, nm = meal_shift_month(year, month, 1)

    # 이 팀이 지금까지(전체 기간) 사용한 식당 목록 → 식당 선택 콤보박스용
    rest_rows = _meal_get(
        f"meal_entries?team_id=eq.{team_id}&select=restaurant")
    seen, restaurant_list = set(), []
    for r in rest_rows:
        nm_r = (r.get("restaurant") or "").strip()
        if nm_r and nm_r not in seen:
            seen.add(nm_r)
            restaurant_list.append(nm_r)
    restaurant_list.sort()

    return render_template_string(
        MEAL_TEAM_HTML,
        team=team, members=members, weeks=weeks, summaries=summaries,
        rest_summaries=rest_summaries,
        year=year, month=month,
        prev_ym=meal_ym_str(py, pm), next_ym=meal_ym_str(ny, nm),
        team_total=team_total, full_people=full_people,
        amount=MEAL_FIXED_AMOUNT, monthly_count=MEAL_MONTHLY_COUNT,
        cap=MEAL_MONTHLY_CAP,
        member_info_json=json.dumps(member_info, ensure_ascii=False),
        restaurant_list=restaurant_list, holiday_days_json=meal_holiday_js_json(holiday_days),
        holiday_status=holiday_status,
        weekdays=["일", "월", "화", "수", "목", "금", "토"],
    )


def meal_entry_date_error(d):
    try:
        selected = date.fromisoformat(d)
        if selected.isoformat() != d:
            raise ValueError("Invalid date format")
    except (TypeError, ValueError):
        return "올바른 날짜를 선택해 주세요."
    if selected.weekday() >= 5:
        return "주말에는 매식비를 입력하거나 수정할 수 없습니다. 평일 날짜를 선택해 주세요."
    if selected > meal_today_kst():
        return "미래 날짜에는 매식비를 입력하거나 수정할 수 없습니다. 오늘 또는 지난 날짜를 선택해 주세요."
    holiday = meal_holiday_name(d)
    if holiday:
        return f"{holiday} 공휴일에는 매식비를 입력하거나 수정할 수 없습니다."
    return None


@app.route("/meal/api/entry", methods=["POST"])
@meal_login_required
def meal_add_entry():
    data = request.get_json(force=True)
    team_id = int(data.get("team_id", 0))
    member_ids = data.get("member_ids") or []
    d = (data.get("date") or "").strip()
    restaurant = (data.get("restaurant") or "").strip()
    approver = (data.get("approver") or "").strip()

    try:
        member_ids = [int(x) for x in member_ids]
    except Exception:
        member_ids = []

    if not (team_id and member_ids and d):
        return jsonify(ok=False, error="팀원과 날짜를 선택해 주세요."), 400
    date_error = meal_entry_date_error(d)
    if date_error:
        return jsonify(ok=False, error=date_error), 400
    if not restaurant:
        return jsonify(ok=False, error="식당명을 입력해 주세요."), 400
    if not approver:
        return jsonify(ok=False, error="결제자를 선택하거나 입력해 주세요."), 400

    members = _meal_get(f"meal_members?team_id=eq.{team_id}&select=id,name")
    name_of = {m["id"]: m["name"] for m in members}
    month_prefix = d[:7]
    now_iso = datetime.now(MEAL_KST).isoformat()

    added, skipped = [], []
    to_insert = []
    for mid in member_ids:
        ex = _meal_get(
            f"meal_entries?member_id=eq.{mid}&d=like.{month_prefix}*&select=d")
        used_days = {r["d"] for r in ex}
        nm = name_of.get(mid, str(mid))
        if d in used_days:
            skipped.append(f"{nm}(이미 입력)")
            continue
        if len(used_days) >= MEAL_MONTHLY_COUNT:
            skipped.append(f"{nm}(한도초과)")
            continue
        to_insert.append({
            "team_id": team_id, "member_id": mid, "d": d,
            "amount": MEAL_FIXED_AMOUNT, "restaurant": restaurant,
            "approver": approver, "created_at": now_iso,
        })
        added.append(nm)

    if to_insert:
        resp = _meal_post("meal_entries", to_insert)
        if resp.status_code >= 400:
            return jsonify(ok=False, error="저장 중 오류가 발생했어요."), 500

    if not added:
        return jsonify(ok=False,
                       error="추가된 인원이 없어요. " + ", ".join(skipped)), 400
    return jsonify(ok=True, added=added, skipped=skipped)


@app.route("/meal/api/entry/edit", methods=["POST"])
@meal_login_required
def meal_edit_entry():
    data = request.get_json(force=True)
    try:
        team_id = int(data.get("team_id", 0))
        selected_ids = [int(mid) for mid in (data.get("member_ids") or [])]
    except (ValueError, TypeError):
        return jsonify(ok=False, error="올바른 팀원 정보를 선택해 주세요."), 400
    d = str(data.get("date") or "").strip()
    restaurant = str(data.get("restaurant") or "").strip()
    approver = str(data.get("approver") or "").strip()
    if not team_id or not selected_ids or len(set(selected_ids)) != len(selected_ids):
        return jsonify(ok=False, error="팀원을 한 명 이상 선택해 주세요."), 400
    date_error = meal_entry_date_error(d)
    if date_error:
        return jsonify(ok=False, error=date_error), 400
    if not restaurant:
        return jsonify(ok=False, error="식당명을 입력해 주세요."), 400
    if not approver:
        return jsonify(ok=False, error="결제자를 선택하거나 입력해 주세요."), 400

    member_rows = _meal_get(f"meal_members?team_id=eq.{team_id}&select=id,name,active")
    members = {int(m["id"]): m for m in member_rows}
    month_rows = _meal_get(
        f"meal_entries?team_id=eq.{team_id}&d=like.{d[:7]}*&select=*")
    day_rows = [r for r in month_rows if r["d"] == d]
    if not day_rows:
        return jsonify(ok=False, error="수정할 기존 입력 내역이 없습니다. 화면을 새로고침해 주세요."), 409
    existing = {int(r["member_id"]): r for r in day_rows}
    if any(mid not in members or
           (members[mid].get("active", True) is False and mid not in existing)
           for mid in selected_ids):
        return jsonify(ok=False, error="이 팀의 등록된 팀원만 선택할 수 있습니다."), 400
    for mid in selected_ids:
        # 수정 중인 날짜는 월 한도 계산에서 제외하여 6회째 기록도 수정 가능.
        other_days = {r["d"] for r in month_rows
                      if int(r["member_id"]) == mid and r["d"] != d}
        if len(other_days) >= MEAL_MONTHLY_COUNT:
            return jsonify(ok=False,
                           error=f"{members[mid]['name']}님의 이번 달 입력 한도를 초과합니다."), 400

    ids_to_keep = [int(existing[mid]["id"]) for mid in selected_ids if mid in existing]
    new_ids = [mid for mid in selected_ids if mid not in existing]
    ids_to_remove = [int(r["id"]) for mid, r in existing.items()
                     if mid not in selected_ids]
    if ids_to_keep:
        kept = ",".join(str(i) for i in ids_to_keep)
        response = _meal_patch("meal_entries", f"team_id=eq.{team_id}&d=eq.{d}&id=in.({kept})",
                               {"restaurant": restaurant, "approver": approver})
        if not response.ok:
            return jsonify(ok=False, error="기존 내역 수정에 실패했습니다. 다시 시도해 주세요."), 500
    if new_ids:
        now_iso = datetime.now(MEAL_KST).isoformat()
        response = _meal_post("meal_entries", [
            {"team_id": team_id, "member_id": mid, "d": d,
             "amount": MEAL_FIXED_AMOUNT, "restaurant": restaurant,
             "approver": approver, "created_at": now_iso}
            for mid in new_ids])
        if not response.ok:
            return jsonify(ok=False, error="팀원 추가에 실패했습니다. 일부 내용이 수정되었을 수 있으니 화면을 새로고침해 주세요."), 500
    if ids_to_remove:
        removed = ",".join(str(i) for i in ids_to_remove)
        response = _meal_delete("meal_entries",
                                f"team_id=eq.{team_id}&d=eq.{d}&id=in.({removed})")
        if not response.ok:
            return jsonify(ok=False, error="선택 해제한 팀원 내역의 삭제에 실패했습니다. 화면을 새로고침해 주세요."), 500
    return jsonify(ok=True)


@app.route("/meal/api/entry/delete", methods=["POST"])
@meal_login_required
def meal_delete_entry():
    data = request.get_json(force=True)
    entry_id = int(data.get("entry_id", 0))
    _meal_delete("meal_entries", f"id=eq.{entry_id}")
    return jsonify(ok=True)


@app.route("/meal/api/entry/delete-many", methods=["POST"])
@meal_login_required
def meal_delete_entries():
    data = request.get_json(force=True)
    ids = data.get("entry_ids") or []
    try:
        ids = [int(x) for x in ids]
    except Exception:
        ids = []
    if ids:
        idlist = ",".join(str(i) for i in ids)
        _meal_delete("meal_entries", f"id=in.({idlist})")
    return jsonify(ok=True)


@app.route("/meal/api/member/add", methods=["POST"])
@meal_login_required
def meal_add_member():
    data = request.get_json(force=True)
    team_id = int(data.get("team_id", 0))
    name = (data.get("name") or "").strip()
    if not (team_id and name):
        return jsonify(ok=False, error="이름을 입력해 주세요."), 400
    resp = _meal_post("meal_members", {"team_id": team_id, "name": name})
    if resp.status_code >= 400:
        return jsonify(ok=False, error="추가 중 오류가 발생했어요."), 500
    return jsonify(ok=True)


@app.route("/meal/api/member/delete", methods=["POST"])
@meal_login_required
def meal_delete_member():
    data = request.get_json(force=True)
    member_id = int(data.get("member_id", 0))
    # 기존 입력 기록은 그대로 두고, 명단에서만 숨김 처리(소프트 삭제)
    _meal_patch("meal_members", f"id=eq.{member_id}", {"active": False})
    return jsonify(ok=True)


@app.route("/meal/api/member/delete-many", methods=["POST"])
@meal_login_required
def meal_delete_members():
    data = request.get_json(force=True)
    ids = data.get("member_ids") or []
    try:
        ids = [int(x) for x in ids]
    except Exception:
        ids = []
    if ids:
        idlist = ",".join(str(i) for i in ids)
        _meal_patch("meal_members", f"id=in.({idlist})", {"active": False})
    return jsonify(ok=True)


@app.route("/meal/api/team/rename", methods=["POST"])
@meal_login_required
def meal_rename_team():
    data = request.get_json(force=True)
    team_id = int(data.get("team_id", 0))
    name = (data.get("name") or "").strip()
    if not (team_id and name):
        return jsonify(ok=False, error="팀 이름을 입력해 주세요."), 400
    resp = _meal_patch("meal_teams", f"id=eq.{team_id}", {"name": name})
    if resp.status_code >= 400:
        return jsonify(ok=False, error="변경 중 오류가 발생했어요."), 500
    return jsonify(ok=True)


# ---------------------------------------------------------------- templates
MEAL_BASE_CSS = """
:root{
  --bg:#eef1f7; --bg2:#e6ebf5;
  --surface:#ffffff; --surface-2:#f7f9fd;
  --primary:#4f6ef0; --primary-d:#3f5bdc; --primary-dd:#2f47b8;
  --accent:#6366f1;
  --ink:#1b2436; --ink-soft:#3a455c; --muted:#7b8499; --line:#e6eaf2;
  --soft:#eef1fb; --soft-2:#f1f4fb;
  --ok:#10a37f; --ok-soft:#e6f6f0; --full:#e2555a; --full-soft:#fdeceec0;
  --strip:linear-gradient(180deg,#5b7bf5,#3f5bdc);
  --shadow-sm:0 1px 2px rgba(27,36,54,.05),0 2px 8px rgba(27,36,54,.05);
  --shadow-md:0 4px 14px rgba(27,36,54,.08),0 1px 3px rgba(27,36,54,.05);
  --shadow-lg:0 18px 50px rgba(27,36,54,.22);
  --r:16px;
}
*{box-sizing:border-box}
body{margin:0;color:var(--ink);
  background:
    radial-gradient(1200px 420px at 50% -120px,#f4f6fc 0%,rgba(244,246,252,0) 70%),
    linear-gradient(180deg,var(--bg) 0%,var(--bg2) 100%);
  background-attachment:fixed;min-height:100svh;
  font-family:-apple-system,BlinkMacSystemFont,"Apple SD Gothic Neo","Malgun Gothic","Noto Sans KR",sans-serif;
  -webkit-text-size-adjust:100%;-webkit-tap-highlight-color:transparent;
  letter-spacing:-.2px;}
a{color:inherit;text-decoration:none}
.wrap{max-width:760px;margin:0 auto;padding:18px 15px 80px;}
.topbar{display:flex;align-items:center;gap:10px;padding:4px 2px 18px;}
.topbar h1{font-size:21px;margin:0;font-weight:800;letter-spacing:-.6px;flex:1;}
.back{font-size:22px;line-height:1;color:var(--primary-d);padding:6px 10px;margin-left:-6px;
  background:rgba(255,255,255,.7);border-radius:11px;box-shadow:var(--shadow-sm);font-weight:700;}
.back:active{transform:scale(.94);}
.card{background:var(--surface);border:1px solid var(--line);border-radius:var(--r);
  box-shadow:var(--shadow-sm);padding:16px;margin-bottom:14px;
  position:relative;overflow:hidden;}
.card.strip{padding-left:19px;}
.card.strip::before{content:"";position:absolute;left:0;top:0;bottom:0;width:5px;
  background:var(--strip);}
.muted{color:var(--muted);font-size:13px;}
.btn{display:inline-flex;align-items:center;justify-content:center;gap:6px;border:none;
  background:linear-gradient(180deg,var(--primary),var(--primary-d));color:#fff;font-weight:700;
  border-radius:13px;padding:12px 16px;font-size:15px;cursor:pointer;letter-spacing:-.2px;
  box-shadow:0 3px 0 var(--primary-dd),0 6px 14px rgba(79,110,240,.30);
  transition:transform .06s,box-shadow .06s,filter .15s;}
.btn:active{transform:translateY(2px);box-shadow:0 1px 0 var(--primary-dd),0 3px 8px rgba(79,110,240,.25);filter:brightness(.97);}
.btn:disabled{background:#c4cad6;box-shadow:0 3px 0 #aab2c2;cursor:not-allowed;filter:none;}
.btn.ghost{background:var(--soft);color:var(--primary-dd);box-shadow:0 3px 0 #d3dcf6;}
.btn.ghost:active{box-shadow:0 1px 0 #d3dcf6;}
.del{background:var(--full-soft);color:var(--full);border:none;border-radius:9px;
  padding:6px 11px;font-size:13px;cursor:pointer;font-weight:700;transition:transform .06s;}
.del:active{transform:scale(.95);}
.pill{font-size:12px;font-weight:700;padding:3px 10px;border-radius:20px;
  background:var(--soft);color:var(--primary-dd);}

/* ── 로딩 오버레이 (클릭 반응 표시) ── */
.mloader{position:fixed;inset:0;z-index:300;display:none;align-items:center;justify-content:center;
  background:rgba(20,27,45,.40);backdrop-filter:blur(3px);-webkit-backdrop-filter:blur(3px);
  animation:mfade .15s ease;}
.mloader.on{display:flex;}
@keyframes mfade{from{opacity:0}to{opacity:1}}
.mloader-card{background:#fff;border-radius:18px;padding:22px 28px;display:flex;flex-direction:column;
  align-items:center;gap:13px;box-shadow:var(--shadow-lg);min-width:130px;}
.mloader-spin{width:36px;height:36px;border-radius:50%;
  border:3.5px solid var(--soft);border-top-color:var(--primary);animation:mspin .7s linear infinite;}
@keyframes mspin{to{transform:rotate(360deg)}}
.mloader-txt{font-size:13.5px;font-weight:700;color:var(--ink);letter-spacing:-.2px;}

/* ── 공통 앱 팝업 ── */
.mdialog-mask{position:fixed;inset:0;z-index:400;display:none;align-items:center;justify-content:center;
  background:rgba(20,27,45,.48);backdrop-filter:blur(4px);-webkit-backdrop-filter:blur(4px);padding:18px;}
.mdialog-mask.on{display:flex;animation:mfade .16s ease;}
.mdialog{width:min(92vw,420px);background:#fff;border-radius:22px;box-shadow:var(--shadow-lg);overflow:hidden;
  border:1px solid rgba(230,234,242,.95);animation:pop .18s cubic-bezier(.2,.8,.3,1);}
.mdialog-head{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:18px 18px 14px;
  background:linear-gradient(180deg,#f8faff 0%,#f2f5fd 100%);border-bottom:1px solid var(--line);}
.mdialog-title{font-size:17px;font-weight:900;color:var(--ink);letter-spacing:-.4px;}
.mdialog-close{width:34px;height:34px;border:none;border-radius:11px;background:#fff;color:var(--muted);font-size:20px;line-height:1;
  box-shadow:var(--shadow-sm);cursor:pointer;flex:0 0 auto;}
.mdialog-close:active{transform:scale(.94);}
.mdialog-body{padding:18px;font-size:14px;line-height:1.7;color:var(--ink-soft);white-space:pre-line;word-break:keep-all;}
.mdialog-input{width:100%;margin-top:2px;margin-bottom:16px;padding:12px 14px;
  background:#f7f9fd;color:var(--ink);border:1.5px solid #dfe5f0;border-radius:12px;
  font-size:14px;outline:none;box-sizing:border-box;}
.mdialog-input:focus{border-color:var(--primary);background:#fff;box-shadow:0 0 0 3px rgba(79,110,240,.13);}
.mdialog-actions{display:flex;justify-content:flex-end;gap:8px;padding:0 18px 18px;}
.mdialog-btn{min-width:96px;height:44px;border:none;border-radius:13px;font-size:14px;font-weight:800;cursor:pointer;}
.mdialog-btn.sub{background:var(--soft);color:var(--primary-dd);}
.mdialog-btn.main{background:linear-gradient(180deg,var(--primary),var(--primary-d));color:#fff;
  box-shadow:0 3px 0 var(--primary-dd),0 6px 14px rgba(79,110,240,.22);}
.mdialog-btn:active{transform:translateY(2px);}
"""

# 모든 매식비 화면에서 재사용하는 로딩 오버레이 (markup + 제어 스크립트)
MEAL_LOADER_HTML = """
<div class=mloader id=mloader><div class=mloader-card>
  <div class=mloader-spin></div><div class=mloader-txt id=mloaderTxt>처리 중…</div>
</div></div>
<script>
window.mealLoading=function(show,txt){
  var el=document.getElementById('mloader');if(!el)return;
  if(txt){var t=document.getElementById('mloaderTxt');if(t)t.textContent=txt;}
  el.classList.toggle('on',show!==false);
};
window.addEventListener('pageshow',function(){
  var el=document.getElementById('mloader');if(el)el.classList.remove('on');
});

window.mealDialog=function(opts){
  opts=opts||{};
  return new Promise(function(resolve){
    var mask=document.getElementById('mealDialogMask');
    var title=document.getElementById('mealDialogTitle');
    var body=document.getElementById('mealDialogBody');
    var input=document.getElementById('mealDialogInput');
    var cancelBtn=document.getElementById('mealDialogCancel');
    var okBtn=document.getElementById('mealDialogOk');
    var closeBtn=document.getElementById('mealDialogClose');
    if(!mask||!title||!body||!input||!cancelBtn||!okBtn||!closeBtn){resolve(opts.mode==='confirm'?false:(opts.mode==='prompt'?null:undefined));return;}
    title.textContent=opts.title||'알림';
    body.textContent=opts.message||'';
    okBtn.textContent=opts.okText||'확인';
    cancelBtn.textContent=opts.cancelText||'취소';
    cancelBtn.style.display=(opts.mode==='confirm'||opts.mode==='prompt')?'':'none';
    closeBtn.style.display=opts.hideClose?'none':'';
    input.style.display=opts.mode==='prompt'?'block':'none';
    input.value=opts.defaultValue||'';
    input.placeholder=opts.placeholder||'';
    var oldOverflow=document.body.style.overflow;
    mask.classList.add('on');
    document.body.style.overflow='hidden';
    function cleanup(val){
      mask.classList.remove('on');
      document.body.style.overflow=oldOverflow;
      okBtn.onclick=cancelBtn.onclick=closeBtn.onclick=null;
      mask.onclick=null;
      window.removeEventListener('keydown', onKey);
      resolve(val);
    }
    function onKey(e){
      if(!mask.classList.contains('on')) return;
      if(e.key==='Escape'){ e.preventDefault(); cleanup(opts.mode==='confirm'?false:(opts.mode==='prompt'?null:undefined)); }
      if(e.key==='Enter'){
        if(opts.mode==='prompt' && document.activeElement===input){ e.preventDefault(); cleanup(input.value); }
        else if(opts.mode!=='prompt'){ e.preventDefault(); cleanup(opts.mode==='confirm'?true:undefined); }
      }
    }
    okBtn.onclick=function(){ cleanup(opts.mode==='prompt'?input.value:(opts.mode==='confirm'?true:undefined)); };
    cancelBtn.onclick=function(){ cleanup(opts.mode==='confirm'?false:null); };
    closeBtn.onclick=function(){ cleanup(opts.mode==='confirm'?false:(opts.mode==='prompt'?null:undefined)); };
    mask.onclick=function(e){ if(e.target===mask) cleanup(opts.mode==='confirm'?false:(opts.mode==='prompt'?null:undefined)); };
    window.addEventListener('keydown', onKey);
    setTimeout(function(){ (opts.mode==='prompt'?input:okBtn).focus(); if(opts.mode==='prompt') input.select(); }, 0);
  });
};
window.mealAlert=function(message,title,okText){ return window.mealDialog({mode:'alert',title:title||'알림',message:String(message||''),okText:okText||'확인'}); };
window.mealConfirm=function(message,title,okText,cancelText){ return window.mealDialog({mode:'confirm',title:title||'확인',message:String(message||''),okText:okText||'확인',cancelText:cancelText||'취소'}); };
window.mealPrompt=function(message,defaultValue,title,placeholder){ return window.mealDialog({mode:'prompt',title:title||'입력',message:String(message||''),defaultValue:defaultValue||'',placeholder:placeholder||''}); };
</script>
<div class=mdialog-mask id=mealDialogMask><div class=mdialog role=dialog aria-modal=true aria-labelledby=mealDialogTitle>
  <div class=mdialog-head><div class=mdialog-title id=mealDialogTitle>알림</div><button type=button class=mdialog-close id=mealDialogClose aria-label=닫기>×</button></div>
  <div class=mdialog-body id=mealDialogBody></div>
  <div style="padding:0 18px"><input id=mealDialogInput class=mdialog-input style="display:none"></div>
  <div class=mdialog-actions><button type=button class="mdialog-btn sub" id=mealDialogCancel>취소</button><button type=button class="mdialog-btn main" id=mealDialogOk>확인</button></div>
</div></div>
"""

MEAL_LOGIN_HTML = """<!doctype html><html lang=ko><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>매식비 관리 · 로그인</title><style>""" + MEAL_BASE_CSS + """
.login-wrap{min-height:100svh;display:flex;align-items:center;justify-content:center;padding:20px;}
.login-card{background:var(--surface);border:1px solid var(--line);border-radius:22px;
  box-shadow:var(--shadow-lg);padding:34px 26px 26px;width:100%;max-width:362px;text-align:center;
  transform:translateY(-3vh);}
.login-logo{width:62px;height:62px;border-radius:18px;
  background:linear-gradient(135deg,#5b7bf5,#2f47b8);
  display:flex;align-items:center;justify-content:center;margin:0 auto 16px;
  color:#fff;font-size:28px;box-shadow:0 8px 20px rgba(79,110,240,.40);}
.login-card h1{font-size:21px;margin:0 0 5px;font-weight:800;letter-spacing:-.5px;}
.login-card p{font-size:13px;color:var(--muted);margin:0 0 22px;}
.login-card input{width:100%;font:inherit;font-size:19px;text-align:center;letter-spacing:7px;
  border:1.5px solid var(--line);border-radius:13px;padding:14px;margin-bottom:12px;background:var(--surface-2);
  transition:border-color .15s,box-shadow .15s;}
.login-card input:focus{outline:none;border-color:var(--primary);box-shadow:0 0 0 3px rgba(79,110,240,.18);background:#fff;}
.login-card .btn{width:100%;}
.login-err{color:var(--full);font-size:13px;font-weight:600;margin-bottom:10px;min-height:18px;}
.admin-link{margin-top:20px;font-size:12.5px;color:var(--muted);}
.admin-link a{color:var(--primary-d);font-weight:700;border-bottom:1px dashed rgba(79,110,240,.5);padding-bottom:1px;}
</style></head><body>
<div class=login-wrap>
  <div class=login-card>
    <div class=login-logo>&#127869;</div>
    <h1>매식비 관리</h1>
    <p>비밀번호를 입력해 주세요.</p>
    <div class=login-err id=err></div>
    <input id=pw type=password inputmode=numeric placeholder="****"
           onkeydown="if(event.key=='Enter')doLogin()" autofocus>
    <button class=btn onclick=doLogin()>로그인</button>
    <div class=admin-link><a href="/meal/admin/login">백업 · 복원 (관리자)</a></div>
  </div>
</div>
<script>
async function doLogin(){
  const pw = document.getElementById('pw').value;
  const r = await fetch('/meal/api/login',{method:'POST',
    headers:{'Content-Type':'application/json'},body:JSON.stringify({password:pw})});
  const res = await r.json();
  if(res.ok){location.href='/meal';}
  else{
    document.getElementById('err').textContent = res.error||'로그인 실패';
    document.getElementById('pw').value='';
    document.getElementById('pw').focus();
  }
}
</script>
</body></html>"""

MEAL_ADMIN_LOGIN_HTML = """<!doctype html><html lang=ko><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>매식비 · 백업 관리자</title><style>""" + MEAL_BASE_CSS + """
.login-wrap{min-height:100svh;display:flex;align-items:center;justify-content:center;padding:20px;}
.login-card{background:var(--surface);border:1px solid var(--line);border-radius:22px;
  box-shadow:var(--shadow-lg);padding:34px 26px 26px;width:100%;max-width:362px;text-align:center;
  transform:translateY(-3vh);}
.login-logo{width:62px;height:62px;border-radius:18px;
  background:linear-gradient(135deg,#2f3b57,#111a2e);
  display:flex;align-items:center;justify-content:center;margin:0 auto 16px;
  color:#fff;font-size:26px;box-shadow:0 8px 20px rgba(17,26,46,.35);}
.login-card h1{font-size:20px;margin:0 0 5px;font-weight:800;letter-spacing:-.5px;}
.login-card p{font-size:13px;color:var(--muted);margin:0 0 22px;}
.login-card input{width:100%;font:inherit;font-size:18px;text-align:center;letter-spacing:5px;
  border:1.5px solid var(--line);border-radius:13px;padding:14px;margin-bottom:12px;background:var(--surface-2);
  transition:border-color .15s,box-shadow .15s;}
.login-card input:focus{outline:none;border-color:var(--primary);box-shadow:0 0 0 3px rgba(79,110,240,.18);background:#fff;}
.login-card .btn{width:100%;}
.login-err{color:var(--full);font-size:13px;font-weight:600;margin-bottom:10px;min-height:18px;}
.admin-link{margin-top:20px;font-size:12.5px;color:var(--muted);}
.admin-link a{color:var(--primary-d);font-weight:700;}
</style></head><body>
<div class=login-wrap>
  <div class=login-card>
    <div class=login-logo>&#128274;</div>
    <h1>백업 · 복원</h1>
    <p>관리자 비밀번호를 입력해 주세요.</p>
    <div class=login-err id=err></div>
    <input id=pw type=password placeholder="비밀번호"
           onkeydown="if(event.key=='Enter')doLogin()" autofocus>
    <button class=btn onclick=doLogin()>들어가기</button>
    <div class=admin-link><a href="/meal/login">‹ 일반 로그인으로</a></div>
  </div>
</div>
<script>
async function doLogin(){
  const pw = document.getElementById('pw').value;
  const r = await fetch('/meal/api/admin/login',{method:'POST',
    headers:{'Content-Type':'application/json'},body:JSON.stringify({password:pw})});
  const res = await r.json();
  if(res.ok){location.href='/meal/admin';}
  else{
    document.getElementById('err').textContent = res.error||'로그인 실패';
    document.getElementById('pw').value='';
    document.getElementById('pw').focus();
  }
}
</script>
</body></html>"""

MEAL_HOME_HTML = """<!doctype html><html lang=ko><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>매식비 관리</title><style>""" + MEAL_BASE_CSS + """
.hero{position:relative;overflow:hidden;border-radius:18px;padding:14px 16px;margin:14px 0 20px;
  background:linear-gradient(135deg,#7e93f3 0%,#6478ea 100%);
  box-shadow:0 8px 22px rgba(100,120,234,.22);}
.hero::before{content:"";position:absolute;width:150px;height:150px;border-radius:50%;
  right:-46px;top:-60px;background:rgba(255,255,255,.14);}
.hero::after{content:"";position:absolute;width:100px;height:100px;border-radius:50%;
  right:26px;bottom:-54px;background:rgba(255,255,255,.09);}
.hero-row{position:relative;z-index:1;display:flex;align-items:center;gap:12px;}
.hero-logo{width:42px;height:42px;border-radius:13px;flex:0 0 auto;
  background:rgba(255,255,255,.22);display:flex;align-items:center;justify-content:center;font-size:22px;
  box-shadow:inset 0 0 0 1px rgba(255,255,255,.30);}
.hero-tt{flex:1;min-width:0;}
.hero-tt h1{margin:0;font-size:20px;font-weight:800;letter-spacing:-.5px;color:#fff;}
.hero .logout{background:rgba(255,255,255,.20);border:1px solid rgba(255,255,255,.32);color:#fff;
  box-shadow:none;flex:0 0 auto;}
.hero .logout:active{transform:scale(.95);background:rgba(255,255,255,.32);}

.lead-card{position:relative;overflow:hidden;background:var(--surface);border:1px solid var(--line);
  border-radius:var(--r);padding:13px 15px 13px 18px;box-shadow:var(--shadow-sm);margin-bottom:16px;}
.lead-card::before{content:"";position:absolute;left:0;top:0;bottom:0;width:5px;background:var(--strip);}
.lead{font-size:13.5px;color:var(--ink-soft);line-height:1.65;margin:0;word-break:keep-all;}
.lead .lead-word{display:inline-block;white-space:nowrap;}
.lead b{color:var(--primary-dd);font-weight:800;}

.sec-title{font-size:14px;font-weight:800;margin:20px 2px 12px;letter-spacing:-.3px;color:var(--ink-soft);
  display:flex;align-items:center;gap:7px;}
.sec-title .dot{width:7px;height:7px;border-radius:50%;background:var(--primary);
  box-shadow:0 0 0 3px rgba(79,110,240,.18);}

.team-grid{display:grid;grid-template-columns:1fr 1fr;gap:11px 10px;}
.team-btn{display:flex;flex-direction:column;align-items:center;justify-content:center;gap:7px;
  background:var(--surface);border:1px solid var(--line);border-radius:16px;padding:13px 12px;
  box-shadow:var(--shadow-sm);position:relative;overflow:hidden;text-align:center;
  transition:transform .14s ease,box-shadow .2s ease,border-color .2s ease;}
.team-btn .ava{width:40px;height:40px;border-radius:12px;flex:0 0 auto;display:flex;align-items:center;
  justify-content:center;font-size:20px;color:#fff;
  background:linear-gradient(135deg,#5b7bf5,#3f5bdc);box-shadow:0 5px 12px rgba(79,110,240,.30);}
.team-btn.tf .ava{background:linear-gradient(135deg,#ef8585,#dd6b6b);box-shadow:0 5px 12px rgba(221,107,107,.30);}
.team-btn .nm{font-size:15px;font-weight:800;letter-spacing:-.4px;color:var(--ink);word-break:keep-all;}
.team-btn .chev{display:none;}
.team-change-dot{position:absolute;top:10px;left:10px;width:10px;height:10px;border-radius:50%;
  background:#e2555a;border:2px solid #fff;box-shadow:0 1px 5px rgba(226,85,90,.45);display:none;z-index:2;}
/* 통합돌봄팀(TF) = 맨 아래 한 줄 전체폭, 가운데 정렬 카드 */
.team-btn.tf{grid-column:1 / -1;order:1;flex-direction:row;justify-content:center;gap:12px;
  padding:22px 16px;text-align:center;}
.team-btn.tf .nm{font-size:18px;}
@media (hover:hover) and (pointer:fine){
  .team-btn:hover{transform:translateY(-2px);box-shadow:var(--shadow-md);border-color:rgba(79,110,240,.35);}
}
.team-btn:active{transform:scale(.98);box-shadow:0 1px 4px rgba(27,36,54,.06);}
.logout{font-size:13px;color:var(--muted);background:rgba(255,255,255,.7);border:1px solid var(--line);
  border-radius:10px;padding:7px 13px;cursor:pointer;font-weight:600;box-shadow:var(--shadow-sm);}
.logout:active{transform:scale(.95);}
</style></head><body><div class=wrap>
<div class=hero>
  <div class=hero-row>
    <div class=hero-logo>&#127869;</div>
    <div class=hero-tt>
      <h1>매식비 관리</h1>
    </div>
    <button class=logout onclick="location.href='/meal/logout'">로그아웃</button>
  </div>
</div>
<div class=lead-card><p class=lead><span class=lead-word>팀을</span> <span class=lead-word>고른</span> <span class=lead-word>뒤</span> <span class=lead-word>달력에서</span> <b><span class=lead-word>날짜·팀원을</span></b> <span class=lead-word><b>선택</b>하고</span> <span class=lead-word>식당·결제자를</span> <span class=lead-word>입력하면</span> <span class=lead-word>1인</span> <span class=lead-word>{{ "{:,}".format(amount) }}원씩</span> <span class=lead-word>기록돼요.</span> <span class=lead-word>한</span> <span class=lead-word>사람당</span> <span class=lead-word>한</span> <span class=lead-word>달</span> <span class=lead-word><b>{{monthly_count}}회({{ "{:,}".format(cap) }}원)</b>까지만</span> <span class=lead-word>가능해요.</span></p></div>
<div class=sec-title><span class=dot></span>팀 선택</div>
<div class=team-grid>
{% for t in teams %}
  <a class="team-btn{% if '통합돌봄' in t.name %} tf{% endif %}" href="/meal/team/{{t.id}}"
     data-team-id="{{t.id}}" data-change-rev="{{t.change_rev}}"
     onclick="mealMarkTeamSeen(this);mealLoading(true,'불러오는 중…')">
    <span class=team-change-dot aria-hidden=true></span>
    <span class=ava>&#127869;</span>
    <span class=nm>{{t.name}}</span>
    <span class=chev>›</span>
  </a>
{% endfor %}
</div>
<script>
(function(){
  const keyPrefix='meal_team_seen_rev_';
  const cards=document.querySelectorAll('.team-btn[data-team-id]');

  cards.forEach(function(card){
    const key=keyPrefix+card.dataset.teamId;
    const current=card.dataset.changeRev||'';
    const dot=card.querySelector('.team-change-dot');
    try{
      const seen=localStorage.getItem(key);
      if(seen===null){
        // 기능을 처음 쓰는 기기에서는 현재 상태를 기준점으로 잡아 기존 데이터가 전부 새 알림으로 뜨지 않게 한다.
        localStorage.setItem(key,current);
      }else if(seen!==current && dot){
        dot.style.display='block';
      }
    }catch(e){}
  });

  window.mealMarkTeamSeen=function(card){
    if(!card)return;
    const key=keyPrefix+card.dataset.teamId;
    const current=card.dataset.changeRev||'';
    try{localStorage.setItem(key,current);}catch(e){}
    const dot=card.querySelector('.team-change-dot');
    if(dot)dot.style.display='none';
  };
})();
</script>
</div>""" + MEAL_LOADER_HTML + """</body></html>"""

MEAL_ADMIN_HTML = """<!doctype html><html lang=ko><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>매식비 · 백업 관리</title><style>""" + MEAL_BASE_CSS + """
.note-card{background:linear-gradient(180deg,#fff,var(--surface-2));border:1px solid var(--line);
  border-radius:var(--r);padding:15px 17px;box-shadow:var(--shadow-sm);margin-bottom:16px;
  font-size:13.5px;color:var(--ink-soft);line-height:1.65;word-break:keep-all;}
.note-card b{color:var(--primary-dd);}
.cur{display:flex;gap:8px;margin-top:11px;}
.cur .c{flex:1;background:#fff;border:1px solid var(--line);border-radius:11px;padding:9px 10px;text-align:center;}
.cur .c .n{font-size:18px;font-weight:800;}
.cur .c .l{font-size:11px;color:var(--muted);margin-top:1px;}
.sec-title{font-size:15px;font-weight:800;margin:22px 2px 11px;display:flex;align-items:center;gap:7px;}
.slot{background:var(--surface);border:1px solid var(--line);border-radius:15px;padding:14px 15px;
  margin-bottom:11px;box-shadow:var(--shadow-sm);position:relative;overflow:hidden;}
.slot.filled{padding-left:18px;}
.slot.filled::before{content:"";position:absolute;left:0;top:0;bottom:0;width:5px;background:var(--strip);}
.slot.empty{border-style:dashed;background:var(--surface-2);}
.slot .head{display:flex;align-items:center;gap:9px;margin-bottom:3px;}
.slot .sn{font-size:12px;font-weight:800;color:#fff;background:var(--primary-d);
  border-radius:8px;width:26px;height:22px;display:inline-flex;align-items:center;justify-content:center;flex:0 0 auto;}
.slot .lb{font-weight:800;font-size:15px;flex:1;min-width:0;letter-spacing:-.3px;
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
.slot .meta{font-size:12px;color:var(--muted);margin:1px 0 0 35px;}
.slot .meta .dot{margin:0 5px;opacity:.5;}
.slot .actions{display:flex;flex-wrap:wrap;gap:7px;margin-top:11px;}
.sbtn{border:none;border-radius:10px;padding:9px 13px;font-size:13px;font-weight:700;cursor:pointer;
  letter-spacing:-.2px;transition:transform .06s,filter .12s;}
.sbtn:active{transform:translateY(1px);}
.sbtn.save{background:linear-gradient(180deg,#8ba0f6,#7186ef);color:#fff;box-shadow:0 2px 0 #5b72e3;}
.sbtn.load{background:var(--ok-soft);color:var(--ok);}
.sbtn.dl{background:var(--soft);color:var(--primary-dd);}
.sbtn.rm{background:var(--full-soft);color:var(--full);}
.sbtn.full{flex:1;}
.auto-card{background:#fff7ed;border:1px solid #fed7aa;border-radius:15px;padding:14px 15px;margin-bottom:8px;
  box-shadow:var(--shadow-sm);}
.auto-card .ttl{font-weight:800;font-size:14px;color:#b45309;display:flex;align-items:center;gap:6px;}
.auto-card .meta{font-size:12px;color:#a16207;margin:3px 0 0;}
.auto-card .actions{display:flex;gap:7px;margin-top:11px;}
.auto-card .sbtn.load{background:#fff1e0;color:#b45309;}
.auto-card .sbtn.dl{background:#fff1e0;color:#b45309;}
.file-card{background:var(--surface);border:1px dashed var(--line);border-radius:15px;padding:15px;
  box-shadow:var(--shadow-sm);}
.file-card p{font-size:13px;color:var(--ink-soft);margin:0 0 11px;line-height:1.6;}
.file-row{display:flex;gap:8px;align-items:center;flex-wrap:wrap;}
.file-row input[type=file]{font-size:13px;flex:1;min-width:0;}
.logout{font-size:13px;color:var(--muted);background:rgba(255,255,255,.7);border:1px solid var(--line);
  border-radius:10px;padding:7px 13px;cursor:pointer;font-weight:600;box-shadow:var(--shadow-sm);}
 .holiday-admin{background:#fff;border:1px solid var(--line);border-radius:15px;padding:16px;margin-bottom:15px;}
 .holiday-admin p{font-size:12px;color:var(--muted);line-height:1.65;margin:7px 0;}
 .holiday-admin .holiday-form{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-top:12px;}
 .holiday-admin input{border:1px solid var(--line);border-radius:9px;padding:10px;max-width:100%;}
 .holiday-admin .holiday-form input[type=date]{width:175px;}
 .holiday-admin .holiday-form input[type=text]{flex:1;min-width:180px;}
 .holiday-admin .holiday-row{display:flex;align-items:center;gap:8px;padding:9px 2px;border-bottom:1px solid var(--line);font-size:13px;}
 .holiday-admin .holiday-row span{flex:1;}
 </style></head><body><div class=wrap>
<div class=topbar>
  <a class=back href="/meal/login">‹</a>
  <h1>백업 · 복원</h1>
  <button class=logout onclick="location.href='/meal/admin/logout'">나가기</button>
</div>

<div class=note-card>
  매식비 기록을 슬롯에 <b>통째로 저장(백업)</b>해 두고, 필요할 때 <b>그 시점으로 되돌릴(복원)</b> 수 있어요.
  슬롯은 최대 <b>{{ slots|length }}개</b>까지 쓸 수 있고, 각 백업은 JSON 파일로 <b>내려받아 보관</b>할 수도 있습니다.
  <span style="color:var(--full);font-weight:700">복원하면 현재 데이터가 그 백업으로 교체</span>되지만,
  복원 직전 상태는 자동으로 한 번 저장되니 안심하세요.
  <div class=cur>
    <div class=c><div class=n>{{now.teams}}</div><div class=l>팀</div></div>
    <div class=c><div class=n>{{now.members}}</div><div class=l>팀원</div></div>
    <div class=c><div class=n>{{now.entries}}</div><div class=l>입력내역</div></div>
  </div>
</div>

{% if auto %}
<div class=auto-card>
  <div class=ttl>&#9888;&#65039; 복원 직전 자동저장본</div>
  <div class=meta>{{auto.created_at[:16].replace('T',' ')}} · 팀 {{auto.teams}} · 팀원 {{auto.members}} · 내역 {{auto.entries}}</div>
  <div class=actions>
    <button class="sbtn load" onclick="admLoad({{auto_slot}},'복원 직전 자동저장본')">이 상태로 되돌리기</button>
    <a class="sbtn dl" href="/meal/admin/download/{{auto_slot}}">다운로드</a>
  </div>
</div>
{% endif %}

<div class=sec-title>&#128190; 저장 슬롯</div>
{% for s in slots %}
  {% set b = backups.get(s) %}
  {% if b %}
  <div class="slot filled">
    <div class=head>
      <span class=sn>{{s}}</span>
      <span class=lb>{{ b.label if b.label else '백업 ' ~ s }}</span>
    </div>
    <div class=meta>{{b.created_at[:16].replace('T',' ')}}<span class=dot>·</span>팀 {{b.teams}}<span class=dot>·</span>팀원 {{b.members}}<span class=dot>·</span>내역 {{b.entries}}</div>
    <div class=actions>
      <button class="sbtn save" onclick="admSave({{s}})">덮어쓰기</button>
      <button class="sbtn load" data-label="{{ b.label|e if b.label else '백업 ' ~ s }}" onclick="admLoad({{s}}, this.dataset.label)">복원</button>
      <a class="sbtn dl" href="/meal/admin/download/{{s}}">다운로드</a>
      <button class="sbtn rm" onclick="admDelete({{s}})">삭제</button>
    </div>
  </div>
  {% else %}
  <div class="slot empty">
    <div class=head>
      <span class=sn>{{s}}</span>
      <span class=lb style="color:var(--muted);font-weight:600">비어 있음</span>
    </div>
    <div class=actions>
      <button class="sbtn save full" onclick="admSave({{s}})">여기에 현재 데이터 저장</button>
    </div>
  </div>
  {% endif %}
{% endfor %}

<div class=sec-title>📅 공휴일 관리</div>
<div class=holiday-admin>
  <b>공휴일 자동 반영 (올해·내년)</b>
  <p>매식비 화면을 열면 저장된 정보를 사용하며 한국 시간 기준 하루 한 번 갱신합니다.
  관리자가 직접 추가한 날짜는 자동 갱신 후에도 유지됩니다.</p>
  <p>{% for y, info in holiday_years.items() %}
    {{y}}년: {{info.days|length if info.days else 0}}일 저장 ·
    {% if info.checked_at %}최근 정상 조회 {{info.checked_at}}{% else %}아직 정상 조회되지 않음{% endif %}
    {% if info.source %} · {{info.source}}{% endif %}
    {% if info.error %} · ⚠ {{info.error}}{% endif %}<br>
  {% endfor %}</p>
  <button type=button class="sbtn dl" onclick="admHolidayRefresh()">지금 공휴일 다시 조회</button>
  <p>인증키를 설정하면 한국천문연구원 데이터를 사용합니다. 인증키가 없으면 공개 공휴일 서비스를 사용하며, 새 임시공휴일은 제공처에 반영되기 전까지 자동으로 표시되지 않을 수 있습니다.</p>
  <div class=sec-title style="margin-top:16px">임시공휴일 수동 등록</div>
  <div class=holiday-form>
    <input type=date id=holidayDate aria-label="등록할 공휴일 날짜">
    <input type=text id=holidayName maxlength=60 placeholder="공휴일 이름 (예: 임시공휴일)" aria-label="공휴일 이름">
    <button class="sbtn save" onclick="admHolidayAdd()">등록</button>
  </div>
  {% if manual_holidays %}
    {% for d, name in manual_holidays %}
    <div class=holiday-row><span>{{d}} · {{name}}</span>
      <button class="sbtn rm" data-day="{{d}}" onclick="admHolidayDelete(this.dataset.day)">삭제</button></div>
    {% endfor %}
  {% else %}<p>관리자가 직접 등록한 공휴일이 없습니다.</p>{% endif %}
  <p>수동 등록을 삭제해도 같은 날이 자동 공휴일이라면 입력 불가는 유지됩니다.</p>
</div>

<div class=sec-title>&#128193; 파일에서 복원</div>
<div class=file-card>
  <p>내려받아 둔 백업 JSON 파일로도 복원할 수 있어요. (복원 전 현재 상태는 자동 저장됩니다.)</p>
  <div class=file-row>
    <input type=file id=restoreFile accept="application/json,.json">
    <button class="btn" onclick="admRestoreFile()">파일로 복원</button>
  </div>
</div>

</div>""" + MEAL_LOADER_HTML + """
<script>
async function admApi(url, body){
  const r = await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body||{})});
  return r.json();
}
async function admHolidayAdd(){
  const d=document.getElementById('holidayDate').value;
  const name=document.getElementById('holidayName').value.trim();
  if(!d||!name){await mealAlert('날짜와 공휴일 이름을 입력해 주세요.','입력 필요');return;}
  const result=await admApi('/meal/api/admin/holiday/add',{date:d,name:name});
  if(result.ok){location.reload();}else{await mealAlert(result.error||'공휴일을 등록하지 못했습니다.','등록 실패');}
}
async function admHolidayDelete(d){
  if(!await mealConfirm(d+'에 수동 등록한 공휴일을 삭제할까요?','공휴일 삭제'))return;
  const result=await admApi('/meal/api/admin/holiday/delete',{date:d});
  if(result.ok){location.reload();}else{await mealAlert(result.error||'삭제하지 못했습니다.','삭제 실패');}
}
async function admHolidayRefresh(){
  mealLoading(true,'공휴일 정보를 확인 중…');
  try{
    const result=await admApi('/meal/api/admin/holiday/refresh',{});
    if(!result.ok){await mealAlert(result.error||'일부 연도의 공휴일을 갱신하지 못했습니다.','갱신 실패');}
    location.reload();
  }catch(e){mealLoading(false);await mealAlert('공휴일 조회 중 네트워크 오류가 발생했습니다.','네트워크 오류');}
}
async function admSave(slot){
  const label = await mealPrompt('이 백업에 붙일 이름을 입력해 주세요.\\n비워 두면 기본 이름으로 저장됩니다.', '', '백업 이름', '예: 9월 말 정리본');
  if(label===null) return;
  mealLoading(true,'저장 중…');
  const res = await admApi('/meal/api/admin/save',{slot:slot,label:label});
  if(res.ok){ location.reload(); }
  else{ mealLoading(false); await mealAlert(res.error||'저장 실패','백업 저장 실패'); }
}
async function admLoad(slot,label){
  label = label || ('백업 '+slot);
  if(!await mealConfirm("'"+label+"' 백업으로 복원할까요?\\n\\n지금의 모든 매식비 데이터가 이 백업 시점으로 교체됩니다.\\n(복원 직전 상태는 자동저장본으로 보관돼요.)",'백업 복원')) return;
  mealLoading(true,'복원 중…');
  const res = await admApi('/meal/api/admin/load',{slot:slot});
  if(res.ok){ mealLoading(false); await mealAlert('복원이 완료됐어요.','복원 완료'); location.reload(); }
  else{ mealLoading(false); await mealAlert(res.error||'복원 실패','복원 실패'); }
}
async function admDelete(slot){
  if(!await mealConfirm('이 슬롯의 백업을 삭제할까요?','백업 삭제')) return;
  mealLoading(true,'삭제 중…');
  const res = await admApi('/meal/api/admin/delete',{slot:slot});
  if(res.ok){ location.reload(); }
  else{ mealLoading(false); await mealAlert(res.error||'삭제 실패','삭제 실패'); }
}
async function admRestoreFile(){
  const f = document.getElementById('restoreFile').files[0];
  if(!f){ await mealAlert('백업 파일을 선택해 주세요.','파일 선택'); return; }
  let snap;
  try{ snap = JSON.parse(await f.text()); }
  catch(e){ await mealAlert('JSON 파일을 읽을 수 없어요.','파일 읽기 실패'); return; }
  if(!snap || !snap.entries){ await mealAlert('매식비 백업 파일이 아닌 것 같아요.','형식 오류'); return; }
  const c = snap.counts || {};
  if(!await mealConfirm('이 파일로 복원할까요?\\n\\n팀 '+(c.teams||'?')+' · 팀원 '+(c.members||'?')+' · 내역 '+(c.entries||'?')+'\\n현재 데이터가 모두 교체됩니다.','파일 복원')) return;
  mealLoading(true,'복원 중…');
  const res = await admApi('/meal/api/admin/restore-file',{snapshot:snap});
  if(res.ok){ mealLoading(false); await mealAlert('복원이 완료됐어요.','복원 완료'); location.href='/meal'; }
  else{ mealLoading(false); await mealAlert(res.error||'복원 실패','복원 실패'); }
}
</script>
</body></html>"""

MEAL_TEAM_HTML = """<!doctype html><html lang=ko><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>{{team.name}} · 매식비</title><style>""" + MEAL_BASE_CSS + """
.monthbar{display:flex;align-items:center;justify-content:space-between;margin-bottom:14px;
  background:var(--surface);border:1px solid var(--line);border-radius:14px;padding:6px;box-shadow:var(--shadow-sm);}
.monthbar .m{font-size:17px;font-weight:800;letter-spacing:-.4px;}
.navb{font-size:18px;color:var(--primary-dd);background:var(--soft);border:none;border-radius:10px;
  padding:8px 16px;cursor:pointer;font-weight:700;transition:transform .06s,filter .12s;}
.navb:active{transform:scale(.92);filter:brightness(.96);}
.teamtotal{display:flex;gap:10px;margin-bottom:14px;}
.tot{flex:1;background:linear-gradient(180deg,#fff,var(--surface-2));border:1px solid var(--line);
  border-radius:14px;padding:13px 15px;box-shadow:var(--shadow-sm);}
.tot.hl{background:linear-gradient(135deg,var(--primary),var(--primary-dd));border-color:transparent;}
.tot.hl .lab,.tot.hl .val{color:#fff;}
.tot .lab{font-size:12px;color:var(--muted);font-weight:600;}
.tot .val{font-size:20px;font-weight:800;margin-top:3px;letter-spacing:-.5px;}
.cal{width:100%;border-collapse:separate;border-spacing:4px;table-layout:fixed;}
.cal th{font-size:11.5px;color:var(--muted);font-weight:700;padding:4px 0 7px;}
.cal th.sun{color:var(--full);} .cal th.sat{color:#3b6fe0;}
.cal td{vertical-align:top;height:74px;border:1px solid var(--line);padding:4px;cursor:pointer;
  background:var(--surface);transition:background .12s,transform .06s,box-shadow .12s;border-radius:10px;}
.cal td:active{background:var(--soft);transform:scale(.96);}
.cal td.has{box-shadow:inset 0 0 0 1.5px rgba(79,110,240,.25);}
.cal td.out{background:transparent;border-color:transparent;color:#c2c8d2;cursor:default;}
.cal td.weekend{background:#f0f2f6;border-color:#dfe3eb;cursor:not-allowed;}
.cal td.weekend:active{background:#e8ebf1;transform:none;}
.cal td.weekend .dn{color:#929aaa;}
.cal td.weekend .daylocked{display:none;}
.cal td.weekend.has .chip{opacity:.75;}
.cal td.holiday{background:#fff0f1;border-color:#f8ccd0;cursor:not-allowed;}
.cal td.holiday:active{background:#ffe8eb;transform:none;}
.cal td.holiday .dn{color:#ad3445;}
.cal td.holiday .holidayname{font-size:10px;color:#a52e41;font-weight:800;line-height:1.3;word-break:keep-all;}
.cal td.holiday.has .chip{opacity:.75;}
.cal td.today.holiday{background:#fff0f1;border-color:#f8ccd0;}
.holiday-note{font-size:12px;color:#7b8499;margin:2px 0 10px;line-height:1.55;}
.cal td .dn{font-size:12px;font-weight:700;color:var(--ink-soft);}
.cal td .cell{display:flex;flex-direction:column;align-items:flex-start;gap:5px;height:100%;}
.cal td.today{background:#fff7ed;border-color:#fcd29a;box-shadow:inset 0 0 0 1.5px rgba(245,158,11,.45);}
.cal td.today .dn{background:linear-gradient(135deg,#fbbf24,#f59e0b);color:#fff;border-radius:50%;
  width:21px;height:21px;display:inline-flex;align-items:center;justify-content:center;
  box-shadow:0 2px 6px rgba(245,158,11,.5);}
.chip{font-size:11px;line-height:1.25;background:linear-gradient(135deg,#5b7bf5,#3f5bdc);color:#fff;
  border-radius:7px;padding:3px 7px;margin:0;display:inline-flex;align-items:center;gap:2px;
  white-space:nowrap;font-weight:700;box-shadow:0 1px 3px rgba(79,110,240,.3);}
.sec-title{font-size:15px;font-weight:800;margin:22px 2px 11px;letter-spacing:-.3px;}
.sumrow{display:flex;flex-direction:column;gap:9px;padding:13px 4px;border-bottom:1px solid var(--line);}
.sumrow:last-child{border-bottom:none;}
.sumtop{display:flex;align-items:center;gap:10px;}
.sumrow .nm{font-weight:700;flex:1;min-width:0;letter-spacing:-.3px;
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
.bar{width:100%;height:10px;background:#eaeef6;border-radius:6px;overflow:hidden;}
.bar > i{display:block;height:100%;background:linear-gradient(90deg,#13b88f,var(--ok));
  border-radius:6px;transition:width .3s;}
.sumrow.full .bar > i{background:linear-gradient(90deg,#ef6a6f,var(--full));}
.cntpill{font-size:12px;font-weight:800;min-width:34px;text-align:right;}
.cntpill.full{color:var(--full);}
.amt{font-size:12px;color:var(--muted);text-align:right;font-weight:600;flex:0 0 auto;}
.badge{font-size:11px;font-weight:700;padding:2px 8px;border-radius:20px;}
.badge.full{background:var(--full-soft);color:var(--full);}
.badgeslot{flex:0 0 auto;width:42px;display:flex;justify-content:flex-end;}
.empty{color:var(--muted);font-size:13px;padding:14px 4px;}
.restrow{display:flex;align-items:center;gap:10px;padding:11px 4px;border-bottom:1px solid var(--line);}
.restrow:last-child{border-bottom:none;}
.restrow .rn{flex:1;font-weight:700;}
.restrow .rc{font-size:12px;color:var(--muted);min-width:44px;text-align:right;font-weight:600;}
.restrow .ra{font-size:13px;font-weight:700;min-width:84px;text-align:right;}
.acc-head{display:flex;align-items:center;justify-content:space-between;
  width:100%;background:var(--surface);border:1px solid var(--line);border-radius:14px;
  padding:14px 16px;cursor:pointer;font-size:15px;font-weight:800;
  box-shadow:var(--shadow-sm);}
.acc-head .ico{color:var(--primary);font-size:13px;transition:transform .2s;}
.acc-wrap.open .acc-head{border-radius:14px 14px 0 0;}
.acc-wrap.open .acc-head .ico{transform:rotate(180deg);}
.acc-body{display:none;background:var(--surface);border:1px solid var(--line);border-top:none;
  border-radius:0 0 14px 14px;padding:6px 15px 14px;box-shadow:var(--shadow-sm);}
.acc-wrap.open .acc-body{display:block;}
.memrow{display:flex;align-items:center;gap:8px;padding:10px 2px;border-bottom:1px solid var(--line);}
.memrow:last-child{border-bottom:none;}
.memrow .nm{flex:1;font-weight:600;}
.memrow .memchk{width:18px;height:18px;margin:0;flex:0 0 auto;accent-color:var(--primary);}
.memtools{display:flex;gap:8px;margin-bottom:8px;}
.selbtn,.selcancel{background:var(--soft);border:none;color:var(--primary-dd);font-size:13px;
  font-weight:600;padding:7px 12px;border-radius:9px;cursor:pointer;}
.seldel{background:var(--full-soft);border:none;color:var(--full);font-size:13px;font-weight:700;
  padding:7px 12px;border-radius:9px;cursor:pointer;}
.addmem{display:flex;gap:8px;margin-top:12px;align-items:stretch;}
.addmem input{flex:1 1 auto;min-width:0;}
.addmem .btn{flex:0 0 auto;white-space:nowrap;padding:11px 16px;}
input,select{font:inherit;border:1.5px solid var(--line);border-radius:11px;padding:12px;background:var(--surface-2);
  transition:border-color .15s,box-shadow .15s;color:var(--ink);}
input:focus,select:focus{outline:none;border-color:var(--primary);box-shadow:0 0 0 3px rgba(79,110,240,.16);background:#fff;}
select{appearance:none;-webkit-appearance:none;
  background-image:url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='12' height='8' viewBox='0 0 12 8'><path d='M1 1l5 5 5-5' stroke='%237b8499' stroke-width='2' fill='none' stroke-linecap='round'/></svg>");
  background-repeat:no-repeat;background-position:right 14px center;padding-right:36px;cursor:pointer;}
.editname{background:var(--soft);border:none;color:var(--primary-dd);font-size:13px;
  cursor:pointer;padding:7px 11px;border-radius:9px;font-weight:600;}
.editname:active{transform:scale(.95);}
.mask{position:fixed;inset:0;background:rgba(20,27,45,.5);display:none;backdrop-filter:blur(2px);
  -webkit-backdrop-filter:blur(2px);
  align-items:center;justify-content:center;z-index:50;padding:18px;overscroll-behavior:contain;}
.mask.on{display:flex;}
.modal{background:#fff;width:100%;max-width:440px;border-radius:22px;padding:22px 19px;
  max-height:88vh;overflow-y:auto;animation:pop .18s cubic-bezier(.2,.8,.3,1);box-shadow:var(--shadow-lg);}
@keyframes pop{from{transform:scale(.94) translateY(8px);opacity:0}to{transform:none;opacity:1}}
.modal h3{margin:0 0 4px;font-size:18px;font-weight:800;letter-spacing:-.4px;}
.daymodal-head{display:flex;align-items:flex-start;justify-content:space-between;gap:12px;margin-bottom:6px;}
.day-edit-btn{border:1px solid #d9e1f1;background:#f7f9fd;color:var(--primary-dd);
  border-radius:10px;padding:8px 13px;font-size:13px;font-weight:800;cursor:pointer;}
.editmode-label{margin:4px 0 0;font-size:12px;color:var(--primary-d);font-weight:800;}
.modal .hint{font-size:13px;color:var(--muted);margin:0 0 14px;}
.dayentries{margin:0 0 6px;}
.de{display:flex;align-items:flex-start;gap:8px;padding:10px 0;border-bottom:1px solid var(--line);}
.de .nm{font-weight:700;min-width:54px;}
.de .meta{flex:1;min-width:0;font-size:12px;color:var(--muted);line-height:1.4;
  white-space:normal;word-break:break-all;}
.de .am{color:var(--muted);font-size:13px;white-space:nowrap;}
.de .entrychk{width:18px;height:18px;margin:0;flex:0 0 auto;accent-color:var(--primary);margin-top:1px;}
.detools{display:flex;justify-content:flex-end;gap:8px;margin:8px 0 2px;}
.flabel{font-size:13px;font-weight:700;margin:14px 0 6px;display:block;color:var(--ink-soft);}
.memberchecks{display:flex;flex-direction:column;max-height:220px;overflow-y:auto;overflow-x:hidden;
  border:1.5px solid var(--line);border-radius:12px;background:var(--surface-2);}
.mcheck{width:100%;display:grid;grid-template-columns:22px 1fr auto auto;align-items:center;gap:10px;
  padding:12px;cursor:pointer;border-bottom:1px solid var(--line);}
.mcheck:last-child{border-bottom:none;}
.mcheck:active{background:var(--soft);}
.mcheck input{width:18px;height:18px;margin:0;accent-color:var(--primary);}
.mcheck .mname{min-width:0;font-weight:600;color:var(--ink);white-space:nowrap;
  overflow:hidden;text-overflow:ellipsis;}
.mcheck .mcount{font-size:12px;color:var(--muted);white-space:nowrap;}
.mcheck .mtag{font-size:11px;color:var(--full);font-weight:700;white-space:nowrap;}
.mcheck.disabled{opacity:.5;}
.addform input,.addform select{width:100%;}
.note{font-size:13px;border-radius:11px;padding:11px 13px;display:none;margin-top:10px;font-weight:600;}
.note.on{display:block;}
.note.warn{color:var(--full);background:var(--full-soft);}
.note.ok{color:#15663f;background:var(--ok-soft);}
.modalbtns{display:flex;gap:8px;margin-top:16px;}
.modalbtns .btn{flex:1;}
.cancelbtn{background:var(--soft);color:var(--primary-dd);box-shadow:0 3px 0 #d3dcf6;}
.cancelbtn:active{box-shadow:0 1px 0 #d3dcf6;}
</style></head><body><div class=wrap>

<div class=topbar>
  <a class=back href="/meal">‹</a>
  <h1 id=teamTitle>{{team.name}}</h1>
  <button class=editname onclick="renameTeam()">이름수정</button>
</div>

<div class=monthbar>
  <a class=navb href="/meal/team/{{team.id}}?ym={{prev_ym}}" onclick="mealLoading(true,'불러오는 중…')">‹</a>
  <span class=m>{{year}}년 {{month}}월</span>
  <a class=navb href="/meal/team/{{team.id}}?ym={{next_ym}}" onclick="mealLoading(true,'불러오는 중…')">›</a>
</div>

<div class=teamtotal>
  <div class="tot hl"><div class=lab>이번 달 총 사용</div><div class=val>{{ "{:,}".format(team_total) }}원</div></div>
  <div class=tot><div class=lab>한도 마감 인원</div><div class=val>{{full_people}}명</div></div>
</div>

<div class=holiday-note>회색 주말 · 연분홍 공휴일은 입력할 수 없습니다.{% if holiday_status.error %} ⚠ 공휴일 최신정보를 확인하지 못했습니다. {% if not holiday_status.days %}자동 공휴일 차단이 완전하지 않을 수 있습니다.{% else %}이전에 저장한 공휴일 정보만 표시 중입니다.{% endif %}{% endif %}</div>
<div class=card style="padding:8px">
<table class=cal>
  <tr>{% for w in weekdays %}<th class="{% if loop.index0==0 %}sun{% elif loop.index0==6 %}sat{% endif %}">{{w}}</th>{% endfor %}</tr>
  {% for week in weeks %}
  <tr>
    {% for c in week %}
      {% if c.in_month %}
      <td class="{% if c.is_today %}today {% endif %}{% if c.is_weekend %}weekend {% endif %}{% if c.holiday_name %}holiday {% endif %}{% if c.entries %}has{% endif %}" onclick="openDay('{{c.date_str}}')" {% if c.holiday_name %}title="{{c.holiday_name}}" aria-label="{{c.date_str}} {{c.holiday_name}}"{% elif c.is_weekend %}title="주말" aria-label="{{c.date_str}} 주말"{% endif %}>
        <div class=cell>
          <span class=dn>{{c.day}}</span>
          {% if c.holiday_name %}<span class=holidayname>{{c.holiday_name}}</span>{% endif %}
          {% if c.entries %}<span class=chip>{{c.entries|length}}명</span>{% endif %}
        </div>
      </td>
      {% else %}
      <td class=out><span class=dn>{{c.day}}</span></td>
      {% endif %}
    {% endfor %}
  </tr>
  {% endfor %}
</table>
</div>

<div class=sec-title>팀원별 집계 ({{month}}월)</div>
<div class="card strip">
{% if summaries %}
  {% for s in summaries %}
  <div class="sumrow {{s.status}}">
    <div class=sumtop>
      <span class=nm>{{s.name}}</span>
      <span class="cntpill {{s.status}}">{{s.count}}/{{monthly_count}}</span>
      <span class=amt>{{ "{:,}".format(s.total) }}원</span>
      <span class=badgeslot>{% if s.status=='full' %}<span class="badge full">마감</span>{% endif %}</span>
    </div>
    <span class=bar><i style="width:{{ (s.count*100//monthly_count) if s.count<monthly_count else 100 }}%"></i></span>
  </div>
  {% endfor %}
{% else %}
  <div class=empty>아직 등록된 팀원이 없어요. 아래 팀원 관리에서 추가해 주세요.</div>
{% endif %}
</div>

<div class=sec-title>식당별 집계 ({{month}}월)</div>
<div class="card strip">
{% if rest_summaries %}
  {% for r in rest_summaries %}
  <div class=restrow>
    <span class=rn>{{r.name}}</span>
    <span class=rc>{{r.count}}건</span>
    <span class=ra>{{ "{:,}".format(r.total) }}원</span>
  </div>
  {% endfor %}
{% else %}
  <div class=empty>아직 입력 내역이 없어요.</div>
{% endif %}
</div>

<div class=sec-title>팀원 관리</div>
<div class=acc-wrap id=memAcc>
  <div class=acc-head onclick="document.getElementById('memAcc').classList.toggle('open')">
    <span>팀원 {{members|length}}명</span>
    <span class=ico>▼</span>
  </div>
  <div class=acc-body>
    <div class=memtools>
      <button class=selbtn id=selToggle onclick="toggleSelMode()">선택 삭제</button>
      <button class=seldel id=selDelBtn onclick="delSelected()" style="display:none">선택한 0명 삭제</button>
      <button class=selcancel id=selCancelBtn onclick="toggleSelMode()" style="display:none">취소</button>
    </div>
    {% for m in members %}
    <div class=memrow>
      <input type=checkbox class=memchk value="{{m.id}}" data-name="{{m.name}}" onchange="updateSelCount()" style="display:none">
      <span class=nm>{{m.name}}</span>
      <button class="del rowdel" onclick="delMember({{m.id}},'{{m.name}}')">삭제</button>
    </div>
    {% endfor %}
    <div class=addmem>
      <input id=newMember placeholder="새 팀원 이름" onkeydown="if(event.key=='Enter')addMember()">
      <button class="btn" onclick="addMember()">추가</button>
    </div>
  </div>
</div>

<div class=mask id=mask>
  <div class=modal>
    <div class=daymodal-head>
      <div><h3 id=modalDate></h3><p class=editmode-label id=editModeLabel style="display:none">입력 내역 수정 중</p></div>
      <button type=button class=day-edit-btn id=dayEditBtn onclick="editDay()" style="display:none">수정</button>
    </div>
    <p class=hint id=dayModalHint>팀원을 고르고 식당·결제자를 입력하면 1인 {{ "{:,}".format(amount) }}원이 기록돼요.</p>
    <div class=dayentries id=dayEntries></div>
    <div class=addform>
      <label class=flabel>팀원 선택 (여러 명 가능)</label>
      <div class=memberchecks id=memberChecks></div>

      <label class=flabel>식당</label>
      <select id=restaurantSel onchange="onRestaurantChange()">
        <option value="">선택하세요</option>
        {% for rname in restaurant_list %}<option value="{{rname}}">{{rname}}</option>{% endfor %}
        <option value="__other__">그 외 (직접 입력)</option>
      </select>
      <input id=restaurantOther placeholder="식당명 직접 입력" style="display:none;margin-top:8px;" onkeydown="if(event.key=='Enter')saveEntry()">

      <label class=flabel>결제자</label>
      <select id=approverSel onchange="onApproverChange()">
        <option value="">선택 안 함</option>
        {% for m in members %}<option value="{{m.name}}">{{m.name}}</option>{% endfor %}
        <option value="__other__">그 외 (직접 입력)</option>
      </select>
      <input id=approverOther placeholder="결제자 이름" style="display:none;margin-top:8px;" onkeydown="if(event.key=='Enter')saveEntry()">

      <div class=note id=noteBox></div>
      <div class=modalbtns>
        <button class="btn" id=addBtn onclick="saveEntry()">추가하기</button>
        <button class="btn cancelbtn" onclick="closeDay()">취소</button>
      </div>
    </div>
  </div>
</div>

<script>
const TEAM_ID = {{team.id}};
const AMOUNT = {{amount}};
const MONTHLY_COUNT = {{monthly_count}};
const MONTHLY_CAP = {{cap}};
const HOLIDAY_DAYS = {{ holiday_days_json | safe }};
const MEMBER_INFO = {{ member_info_json | safe }};
const DAY_ENTRIES = {
{% for week in weeks %}{% for c in week %}{% if c.in_month and c.entries %}"{{c.date_str}}":[{% for e in c.entries %}{id:{{e.id}},mid:{{e.member_id}},name:"{{e.name}}",rest:"{{e.restaurant}}",appr:"{{e.approver}}"},{% endfor %}],{% endif %}{% endfor %}{% endfor %}
};
const HAS_MEMBERS = {{ 'true' if members or summaries else 'false' }};
let curDate = null;
let dayEditMode = false;

function fmt(n){return n.toLocaleString('ko-KR');}
async function api(url, body){
  const r = await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  return r.json();
}

async function openDay(ds){
  if(HOLIDAY_DAYS[ds]){
    await mealAlert(HOLIDAY_DAYS[ds]+' 공휴일에는 매식비를 입력하거나 수정할 수 없습니다.','공휴일 안내');return;
  }
  const dayOfWeek = new Date(ds+'T12:00:00').getDay();
  if(dayOfWeek===0 || dayOfWeek===6){
    await mealAlert('주말에는 매식비를 입력하거나 수정할 수 없습니다.\\n평일 날짜를 선택해 주세요.','주말 안내');return;
  }
  // 한국 시간 기준으로 자정을 지난 직후에도 미래 날짜 선택을 막는다.
  const todayKst = new Date(Date.now()+9*60*60*1000).toISOString().slice(0,10);
  if(ds>todayKst){await mealAlert('미래 날짜에는 매식비를 입력할 수 없습니다.\\n오늘 또는 지난 날짜를 선택해 주세요.','미래 날짜 안내');return;}
  if(!HAS_MEMBERS){await mealAlert('먼저 팀원을 추가해 주세요.','팀원 없음');return;}
  dayEditMode=false;
  curDate = ds;
  document.getElementById('modalDate').textContent = ds.replace(/-/g,'.');
  entrySelMode=false;
  updateDayEditUI();
  renderDayEntries();
  renderMemberChecks();
  document.getElementById('restaurantSel').value='';
  document.getElementById('restaurantOther').value='';
  document.getElementById('restaurantOther').style.display='none';
  document.getElementById('approverSel').value='';
  document.getElementById('approverOther').value='';
  document.getElementById('approverOther').style.display='none';
  document.getElementById('noteBox').className='note';
  document.getElementById('mask').classList.add('on');
  document.body.style.overflow='hidden';
}
function closeDay(){dayEditMode=false;document.getElementById('mask').classList.remove('on');document.body.style.overflow='';}
document.getElementById('mask').addEventListener('click',e=>{if(e.target.id==='mask')closeDay();});

function updateDayEditUI(){
  const hasEntries=(DAY_ENTRIES[curDate]||[]).length>0;
  const editBtn=document.getElementById('dayEditBtn');
  editBtn.style.display=hasEntries?'':'none';
  editBtn.textContent=dayEditMode?'수정 취소':'수정';
  document.getElementById('editModeLabel').style.display=dayEditMode?'':'none';
  document.getElementById('dayEntries').style.display=dayEditMode?'none':'';
  document.getElementById('addBtn').textContent=dayEditMode?'수정 저장':'추가하기';
  document.getElementById('dayModalHint').textContent=dayEditMode
    ? '기존 입력값을 불러왔습니다. 팀원·식당·결제자를 변경한 후 수정 저장을 눌러 주세요.'
    : '팀원을 고르고 식당·결제자를 입력하면 1인 '+fmt(AMOUNT)+'원이 기록돼요.';
}
function setDaySelect(id, value){
  const select=document.getElementById(id);
  const exists=Array.from(select.options).some(o=>o.value===value);
  select.value=exists?value:'__other__';
  const other=document.getElementById(id==='restaurantSel'?'restaurantOther':'approverOther');
  if(!exists)other.value=value;
  other.style.display=exists?'none':'block';
}
function editDay(){
  dayEditMode=!dayEditMode;
  entrySelMode=false;
  renderDayEntries();
  renderMemberChecks();
  if(dayEditMode){
    const first=(DAY_ENTRIES[curDate]||[])[0];
    if(first){setDaySelect('restaurantSel',first.rest||'');setDaySelect('approverSel',first.appr||'');}
  }else{
    document.getElementById('restaurantSel').value='';
    document.getElementById('approverSel').value='';
    document.getElementById('restaurantOther').value='';
    document.getElementById('approverOther').value='';
    document.getElementById('restaurantOther').style.display='none';
    document.getElementById('approverOther').style.display='none';
  }
  document.getElementById('noteBox').className='note';
  updateDayEditUI();
}

let entrySelMode=false;
function renderDayEntries(){
  const box = document.getElementById('dayEntries');
  const list = DAY_ENTRIES[curDate] || [];
  if(!list.length){entrySelMode=false;box.innerHTML='<div class=muted style="padding:4px 0 6px">이 날 입력 내역이 없어요.</div>';return;}
  const rows = list.map(e=>{
    let meta = [];
    if(e.rest) meta.push(e.rest);
    if(e.appr) meta.push('결제 '+e.appr);
    return `<div class=de>`+
      `<input type=checkbox class=entrychk value="${e.id}" onchange="updateEntrySelCount()" style="display:${entrySelMode?'block':'none'}">`+
      `<span class=nm>${e.name}</span>`+
      `<span class=meta>${meta.join(' · ')}</span>`+
      `<span class=am>${fmt(AMOUNT)}원</span>`+
      `<button class="del entrydel" onclick="delEntry(${e.id})" style="display:${entrySelMode?'none':''}">삭제</button></div>`;
  }).join('');
  let tools = '';
  if(list.length >= 2){
    tools = `<div class=detools>`+(entrySelMode
      ? `<button class=seldel id=entrySelDelBtn onclick="delSelectedEntries()">선택한 0건 삭제</button>`+
        `<button class=selcancel onclick="toggleEntrySelMode()">취소</button>`
      : `<button class=selbtn onclick="toggleEntrySelMode()">선택 삭제</button>`)+`</div>`;
  }
  box.innerHTML = rows + tools;
}
function toggleEntrySelMode(){entrySelMode=!entrySelMode;renderDayEntries();}
function updateEntrySelCount(){
  const n=document.querySelectorAll('#dayEntries .entrychk:checked').length;
  const b=document.getElementById('entrySelDelBtn');
  if(b)b.textContent='선택한 '+n+'건 삭제';
}
async function delSelectedEntries(){
  const checked=Array.from(document.querySelectorAll('#dayEntries .entrychk:checked'));
  if(!checked.length){await mealAlert('삭제할 항목을 선택해 주세요.','선택 필요');return;}
  if(!await mealConfirm(`선택한 ${checked.length}건을 삭제할까요?`,'입력 내역 삭제'))return;
  mealLoading(true,'삭제 중…');
  const ids=checked.map(c=>parseInt(c.value,10));
  const res=await api('/meal/api/entry/delete-many',{entry_ids:ids});
  if(res.ok)location.reload(); else {mealLoading(false);await mealAlert(res.error||'삭제 실패','삭제 실패');}
}

function renderMemberChecks(){
  const box = document.getElementById('memberChecks');
  let html='';
  for(const mid in MEMBER_INFO){
    const info = MEMBER_INFO[mid];
    const existing = info.days.includes(curDate);
    if(!info.active && (!dayEditMode || !existing)) continue;
    if(!dayEditMode && existing) continue; // 추가 모드에서는 기존 입력을 중복 표시하지 않음
    const full = info.count >= MONTHLY_COUNT && !existing;
    const tag = full ? '<span class=mtag>한도초과</span>' : '';
    html += `<label class="mcheck ${full?'disabled':''}">`+
      `<input type=checkbox value="${mid}" ${dayEditMode&&existing?'checked':''} ${full?'disabled':''}>`+
      `<span class=mname>${info.name}</span>`+
      `<span class=mcount>${info.count}/${MONTHLY_COUNT}</span>`+
      `${tag}</label>`;
  }
  if(!html) html='<div class=muted style="padding:14px;text-align:center;font-size:13px">이 날짜에 추가할 수 있는 팀원이 없어요.</div>';
  box.innerHTML = html;
}

function onApproverChange(){
  const sel = document.getElementById('approverSel');
  const other = document.getElementById('approverOther');
  if(sel.value==='__other__'){other.style.display='block';other.focus();}
  else{other.style.display='none';}
}
function onRestaurantChange(){
  const sel = document.getElementById('restaurantSel');
  const other = document.getElementById('restaurantOther');
  if(sel.value==='__other__'){other.style.display='block';other.focus();}
  else{other.style.display='none';}
}

async function saveEntry(){
  const checks = document.querySelectorAll('#memberChecks input:checked');
  const ids = Array.from(checks).map(c=>parseInt(c.value,10));
  const note = document.getElementById('noteBox');
  if(!ids.length){note.className='note warn on';note.textContent='팀원을 한 명 이상 선택해 주세요.';return;}
  let rest = document.getElementById('restaurantSel').value;
  if(rest==='__other__') rest = document.getElementById('restaurantOther').value.trim();
  if(!rest){note.className='note warn on';note.textContent='식당을 선택하거나 직접 입력해 주세요.';return;}
  let appr = document.getElementById('approverSel').value;
  if(appr==='__other__') appr = document.getElementById('approverOther').value.trim();
  if(!appr){note.className='note warn on';note.textContent='결제자를 선택하거나 직접 입력해 주세요.';return;}

  mealLoading(true,dayEditMode?'수정 중…':'저장 중…');
  const res = await api(dayEditMode?'/meal/api/entry/edit':'/meal/api/entry',
    {team_id:TEAM_ID,member_ids:ids,date:curDate,restaurant:rest,approver:appr});
  if(res.ok){
    if(res.skipped && res.skipped.length){
      mealLoading(false); await mealAlert('추가: '+res.added.join(', ')+'\\n제외: '+res.skipped.join(', '),'입력 결과');
    }
    location.reload();
  }else{
    mealLoading(false);
    note.className='note warn on';note.textContent=res.error||'저장에 실패했어요.';
  }
}
async function delEntry(id){
  if(!await mealConfirm('이 입력을 삭제할까요?','입력 삭제'))return;
  mealLoading(true,'삭제 중…');
  const res = await api('/meal/api/entry/delete',{entry_id:id});
  if(res.ok)location.reload(); else mealLoading(false);
}
async function addMember(){
  const inp = document.getElementById('newMember');
  const name = inp.value.trim();
  if(!name){inp.focus();return;}
  mealLoading(true,'추가 중…');
  const res = await api('/meal/api/member/add',{team_id:TEAM_ID,name:name});
  if(res.ok)location.reload(); else {mealLoading(false);await mealAlert(res.error||'추가 실패','팀원 추가 실패');}
}
async function delMember(id,name){
  if(!await mealConfirm(`'${name}' 팀원을 명단에서 삭제할까요?\n\n지금까지 입력한 식비 기록은 그대로 남고,\n팀원 선택 명단에서만 빠집니다.`,'팀원 삭제'))return;
  mealLoading(true,'삭제 중…');
  const res = await api('/meal/api/member/delete',{member_id:id});
  if(res.ok)location.reload(); else mealLoading(false);
}
let selMode=false;
function toggleSelMode(){
  selMode=!selMode;
  document.querySelectorAll('.memchk').forEach(c=>{c.style.display=selMode?'block':'none';if(!selMode)c.checked=false;});
  document.querySelectorAll('.rowdel').forEach(b=>{b.style.display=selMode?'none':'';});
  document.getElementById('selToggle').style.display=selMode?'none':'';
  document.getElementById('selDelBtn').style.display=selMode?'':'none';
  document.getElementById('selCancelBtn').style.display=selMode?'':'none';
  updateSelCount();
}
function updateSelCount(){
  const n=document.querySelectorAll('.memchk:checked').length;
  document.getElementById('selDelBtn').textContent='선택한 '+n+'명 삭제';
}
async function delSelected(){
  const checked=Array.from(document.querySelectorAll('.memchk:checked'));
  if(!checked.length){await mealAlert('삭제할 팀원을 선택해 주세요.','선택 필요');return;}
  const names=checked.map(c=>c.dataset.name).join(', ');
  if(!await mealConfirm(`선택한 ${checked.length}명(${names})을 명단에서 삭제할까요?\n\n입력한 식비 기록은 그대로 남고, 팀원 명단에서만 빠집니다.`,'팀원 삭제'))return;
  mealLoading(true,'삭제 중…');
  const ids=checked.map(c=>parseInt(c.value,10));
  const res=await api('/meal/api/member/delete-many',{member_ids:ids});
  if(res.ok)location.reload(); else {mealLoading(false);await mealAlert(res.error||'삭제 실패','삭제 실패');}
}
async function renameTeam(){
  const name = await mealPrompt('변경할 팀 이름을 입력해 주세요.', document.getElementById('teamTitle').textContent, '팀 이름 변경', '팀 이름');
  if(!name||!name.trim())return;
  mealLoading(true,'변경 중…');
  const res = await api('/meal/api/team/rename',{team_id:TEAM_ID,name:name.trim()});
  if(res.ok)location.reload(); else {mealLoading(false);await mealAlert(res.error||'변경 실패','변경 실패');}
}
</script>
""" + MEAL_LOADER_HTML + """
</div></body></html>"""
# ================================================================
# ===============  매식비 관리 모듈 끝  ==========================
# ================================================================


# ================================================================================
# ===============  출장 도구함 모듈 (/trip)  ======================================
#   - 안전로드 지도앱·매식비 코드와 완전히 분리, /trip 하위 경로로만 동작
#   - 도구: 1. 최적 동선  2. 집 미리보기  3. 내 근처 화장실  4. 복용약 찾기  5. 큰 글씨 대화  6. 통합판정 낱말카드(빈 화면)
#   - 이름·주민번호·전화번호는 받지 않고, 입력·사진·위치는 저장하지 않음 (DB 안 씀)
#   - 환경변수: KAKAO_KEY, KAKAO_JS_KEY(기존) / DATA_GO_KR_KEY, SAFEMAP_KEY, OPENAI_API_KEY(추가)
#   - 데이터 파일: trip_toilets.csv(전국 화장실, 없으면 공중화장실.xlsx), pills.csv(케어내비에서 복사)
#   - 주소 자동완성은 안전로드 /search_place 를 그대로 씀
#   - TRIP_DEMO=1 이면 키 없이 예시 화면
# ================================================================================
import math as _trip_math
import csv
import io
from concurrent.futures import ThreadPoolExecutor
from itertools import permutations
from flask import Blueprint, render_template
from jinja2 import ChoiceLoader as _TripChoiceLoader, DictLoader as _TripDictLoader
try:
    from openai import OpenAI
except ImportError:          # openai 패키지가 없어도 안전로드는 정상 동작 (복용약 사진 판독만 안 됨)
    OpenAI = None
_trip_log = logging.getLogger("trip")

# ---------- 출장 도구함: kakao ----------
TRIP_KAKAO_LOCAL = "https://dapi.kakao.com/v2/local"
TRIP_KAKAO_NAVI = "https://apis-navi.kakaomobility.com/v1/directions"
TRIP_HTTP_TIMEOUT = 6


def _trip_kakao_headers():
    return {"Authorization": f"KakaoAK {os.environ.get('KAKAO_KEY', '')}"}


def _trip_kakao_local(path, params):
    r = requests.get(f"{TRIP_KAKAO_LOCAL}{path}", headers=_trip_kakao_headers(), params=params, timeout=TRIP_HTTP_TIMEOUT)
    r.raise_for_status()
    return r.json().get("documents", [])


def _trip_addr_doc(doc, label=None):
    addr = doc.get("address") or {}
    road = doc.get("road_address") or {}
    b_code = addr.get("b_code", "")
    return {
        "label": label or road.get("building_name") or doc.get("address_name"),
        "road_address": road.get("address_name") or "",
        "jibun_address": addr.get("address_name") or doc.get("address_name", ""),
        "lat": float(doc["y"]), "lng": float(doc["x"]),
        "sigungu_cd": b_code[:5], "bjdong_cd": b_code[5:10],
        "plat_gb_cd": "1" if addr.get("mountain_yn") == "Y" else "0",
        "bun": (addr.get("main_address_no") or "0").zfill(4),
        "ji": (addr.get("sub_address_no") or "0").zfill(4),
        "dong": addr.get("region_3depth_name", ""),
    }


def trip_addr_search(query, limit=5):
    """도로명·지번이면 주소 검색, 단지명·건물명이면 장소 검색. 후보 목록."""
    docs = _trip_kakao_local("/search/address.json", {"query": query, "size": limit})
    if docs:
        return [_trip_addr_doc(d) for d in docs]
    out = []
    for p in _trip_kakao_local("/search/keyword.json", {"query": query, "size": limit}):
        a = _trip_kakao_local("/search/address.json", {"query": p.get("address_name", ""), "size": 1})
        if a:
            out.append(_trip_addr_doc(a[0], label=p.get("place_name")))
    return out


def trip_where(lat, lng):
    """좌표 → 주소 (내 위치 표시용). 도로명이 있으면 도로명, 없으면 지번"""
    docs = _trip_kakao_local("/geo/coord2address.json", {"x": lng, "y": lat})
    if not docs:
        return ""
    d = docs[0]
    full = ((d.get("road_address") or {}).get("address_name")
            or (d.get("address") or {}).get("address_name") or "")
    # 시·도는 빼서 짧게: '전남광주통합특별시 광산구 소촌로 1' → '광산구 소촌로 1'
    t = full.split(" ", 2)
    if len(t) >= 2 and t[1].endswith(("시", "군", "구")) and (t[0].endswith(("시", "도")) or len(t[0]) == 2):
        return full.split(" ", 1)[1]
    return full


def trip_addr_suggest(query, limit=5):
    """자동완성: 실제 있는 주소(도로명·지번)를 먼저, 그다음 건물·장소 이름. 안전로드 /search_place와 같은 모양으로 돌려줌"""
    out, seen = [], set()
    for d in _trip_kakao_local("/search/address.json", {"query": query, "size": limit}):
        road, addr = d.get("road_address") or {}, d.get("address") or {}
        item = {"place_name": road.get("building_name") or road.get("address_name") or d.get("address_name", ""),
                "road_address_name": road.get("address_name", ""),
                "address_name": addr.get("address_name") or d.get("address_name", ""),
                "x": d.get("x"), "y": d.get("y")}
        key = item["road_address_name"] or item["address_name"]
        if key not in seen:
            seen.add(key)
            out.append(item)
    if len(out) < limit:
        for p in _trip_kakao_local("/search/keyword.json", {"query": query, "size": limit}):
            key = p.get("road_address_name") or p.get("address_name", "")
            if key in seen:
                continue
            seen.add(key)
            out.append({k: p.get(k, "") for k in ("place_name", "road_address_name", "address_name", "x", "y")})
    return out[:limit]


class TripRouteFail(Exception):
    """카카오모빌리티가 길을 못 찾음. code 102: 출발지 주변 도로 없음, 103: 도착지 주변 도로 없음"""
    def __init__(self, code, msg):
        super().__init__(msg)
        self.code = code


def trip_directions(a, b, geometry=False):
    """a → b 자동차 경로. 실시간 교통 반영 추천 경로. 반환: 거리(m), 시간(초), 경로 좌표."""
    params = {"origin": f"{a['lng']},{a['lat']}", "destination": f"{b['lng']},{b['lat']}",
              "priority": "RECOMMEND", "summary": "false" if geometry else "true"}
    r = requests.get(TRIP_KAKAO_NAVI, headers=_trip_kakao_headers(), params=params, timeout=TRIP_HTTP_TIMEOUT)
    r.raise_for_status()
    route = (r.json().get("routes") or [{}])[0]
    code = route.get("result_code", -1)
    if code == 104:   # 출발지와 도착지가 5m 안: 같은 곳으로 보고 0분
        return {"distance": 0, "duration": 0, "path": [[a["lat"], a["lng"]], [b["lat"], b["lng"]]]}
    if code != 0:
        raise TripRouteFail(code, route.get("result_msg", "경로 없음"))
    s = route["summary"]
    path = []
    if geometry:
        for sec in route.get("sections", []):
            for road in sec.get("roads", []):
                v = road.get("vertexes", [])
                path += [[v[i + 1], v[i]] for i in range(0, len(v) - 1, 2)]
    return {"distance": s["distance"], "duration": s["duration"], "path": path}

# ---------- 출장 도구함: route_opt ----------
TRIP_MAX_STOPS = 6


def _trip_haversine(a, b):
    r = 6371000
    p1, p2 = _trip_math.radians(a["lat"]), _trip_math.radians(b["lat"])
    dp, dl = p2 - p1, _trip_math.radians(b["lng"] - a["lng"])
    h = _trip_math.sin(dp / 2) ** 2 + _trip_math.cos(p1) * _trip_math.cos(p2) * _trip_math.sin(dl / 2) ** 2
    return 2 * r * _trip_math.asin(_trip_math.sqrt(h))


def trip_estimate_leg(a, b, geometry=False):
    """키 없는 예시 모드용 추정: 직선거리 ×1.35, 평균 시속 35km. 실제 길찾기가 아님."""
    d = _trip_haversine(a, b) * 1.35
    return {"distance": int(d), "duration": int(d / (35000 / 3600)),
            "path": [[a["lat"], a["lng"]], [b["lat"], b["lng"]]] if geometry else []}


class TripPinConflict(Exception):
    pass


class TripLegFail(Exception):
    """a → b 구간 길찾기 실패"""
    def __init__(self, a, b, err):
        super().__init__(str(err))
        self.a, self.b, self.err = a, b, err


def _trip_route_fixed(pts, leg_fn):
    """사용자가 순서를 직접 바꾼 경우: 그 순서 그대로 구간만 계산"""
    with ThreadPoolExecutor(max_workers=8) as ex:
        legs = list(ex.map(lambda k: leg_fn(pts[k], pts[k + 1], True), range(len(pts) - 1)))
    return {
        "order": pts,
        "legs": [{"distance": l["distance"], "duration": l["duration"], "path": l["path"]} for l in legs],
        "total_duration": sum(l["duration"] for l in legs),
        "total_distance": sum(l["distance"] for l in legs),
        "saved_vs_worst": 0, "saved_vs_input": 0, "orders_checked": 1, "fixed": True,
    }


def trip_optimize(start, stops, end, leg_fn, keep_order=False, pins=None):
    """start/end: 지점 dict, stops: 경유지 목록. leg_fn(a, b, geometry) → {distance, duration, path}
    keep_order=True 이면 순서를 바꾸지 않고 넣은 순서대로 계산
    pins: 방문지별 고정 순서 [None | 1부터 시작하는 번째 | "last"] — 고정한 집은 그 번째에만 둠"""
    pts = [start] + stops + [end]
    if keep_order:
        return _trip_route_fixed(pts, leg_fn)
    n_s = len(stops)
    s_idx, e_idx = 0, n_s + 1
    pairs = {(s_idx, i) for i in range(1, n_s + 1)} | {(i, e_idx) for i in range(1, n_s + 1)} \
        | {(i, j) for i in range(1, n_s + 1) for j in range(1, n_s + 1) if i != j}
    if n_s == 0:
        pairs = {(s_idx, e_idx)}

    with ThreadPoolExecutor(max_workers=8) as ex:
        futs = {p: ex.submit(leg_fn, pts[p[0]], pts[p[1]], False) for p in pairs}
        mat = {}
        for p, f in futs.items():
            try:
                mat[p] = f.result()
            except Exception as e:   # 어느 구간이 안 되는지 알려주기 위해 두 지점을 붙여서 올림
                raise TripLegFail(pts[p[0]], pts[p[1]], e) from e

    def total(order):
        seq = [s_idx] + list(order) + [e_idx]
        return sum(mat[(seq[k], seq[k + 1])]["duration"] for k in range(len(seq) - 1))

    # 고정: {번째(0부터): 방문지 번호(1부터)}
    fixed = {}
    for i, p in enumerate(pins or [], start=1):
        if p == "last":
            fixed[n_s - 1] = i
        elif isinstance(p, int) and 1 <= p <= n_s:
            fixed[p - 1] = i
    orders = [o for o in permutations(range(1, n_s + 1))
              if all(o[pos] == i for pos, i in fixed.items())]
    if not orders:
        raise TripPinConflict("고정한 순서끼리 겹쳐요")
    scored = sorted((total(o), o) for o in orders)
    best_t, best = scored[0]
    worst_t = scored[-1][0]
    given_t = total(tuple(range(1, n_s + 1)))

    seq = [s_idx] + list(best) + [e_idx]
    with ThreadPoolExecutor(max_workers=8) as ex:
        legs = list(ex.map(lambda k: leg_fn(pts[seq[k]], pts[seq[k + 1]], True), range(len(seq) - 1)))

    return {
        "order": [pts[i] for i in seq],
        "legs": [{"distance": l["distance"], "duration": l["duration"], "path": l["path"]} for l in legs],
        "total_duration": best_t,
        "total_distance": sum(l["distance"] for l in legs),
        "saved_vs_worst": worst_t - best_t,
        "saved_vs_input": given_t - best_t,
        "orders_checked": len(orders),
    }

# ---------- 출장 도구함: house ----------
TRIP_BLD_TITLE_URL = "https://apis.data.go.kr/1613000/BldRgstHubService/getBrTitleInfo"
TRIP_WOOD = ("목조", "목구조", "흙")
TRIP_MASONRY = ("조적", "벽돌", "블록")


def _trip_int(v):
    try:
        return int(str(v).strip() or 0)
    except ValueError:
        return 0


def trip_building(loc):
    """표제부. 반환: dict / None(대장 없음). 조회 실패는 예외."""
    params = {"serviceKey": os.environ.get("DATA_GO_KR_KEY") or os.environ.get("MEAL_HOLIDAY_API_KEY", ""), "_type": "json", "numOfRows": 50,
              "sigunguCd": loc["sigungu_cd"], "bjdongCd": loc["bjdong_cd"], "platGbCd": loc["plat_gb_cd"],
              "bun": loc["bun"], "ji": loc["ji"]}
    r = requests.get(TRIP_BLD_TITLE_URL, params=params, timeout=6)
    r.raise_for_status()
    body = (r.json().get("response") or {}).get("body") or {}
    items = body.get("items") or {}
    rows = items.get("item") if isinstance(items, dict) else []
    rows = rows if isinstance(rows, list) else ([rows] if rows else [])
    if not rows:
        return None
    main = [x for x in rows if str(x.get("mainAtchGbCd", "0")) == "0"] or rows
    rep = max(main, key=lambda x: _trip_int(x.get("grndFlrCnt")))
    # 승강기: 동마다 따로 적혀 있어서 주건축물 중 가장 많이 적힌 값을 씀
    elev = max(_trip_int(x.get("rideUseElvtCnt")) + _trip_int(x.get("emgenUseElvtCnt")) for x in main)
    grnd = _trip_int(rep.get("grndFlrCnt"))
    if elev == 0 and grnd >= 6:
        elev = None   # 6층 이상은 승강기 설치 의무라 0은 '대장에 안 적힘'으로 봄
    apr = str(rep.get("useAprDay") or "").strip()
    year = int(apr[:4]) if apr[:4].isdigit() else None
    return {
        "name": rep.get("bldNm") or "",
        "purpose": rep.get("mainPurpsCdNm") or "",
        "structure": rep.get("strctCdNm") or rep.get("etcStrct") or "",
        "roof": rep.get("roofCdNm") or rep.get("etcRoof") or "",
        "year": year,
        "grnd": grnd,
        "ugrnd": _trip_int(rep.get("ugrndFlrCnt")),
        "elevators": elev,
        "households": _trip_int(rep.get("hhldCnt")) or _trip_int(rep.get("fmlyCnt")) or _trip_int(rep.get("hoCnt")),
        "dongs": len(main),
    }


TRIP_STRUCT_PLAIN = [("철근콘크리트", "콘크리트"), ("철골철근", "철골·콘크리트"), ("철골", "철골"), ("조적", "벽돌·블록"),
                ("벽돌", "벽돌"), ("블록", "블록"), ("목", "나무"), ("흙", "흙"), ("경량", "가벼운 철골·패널")]


def _trip_plain_struct(s):
    for k, v in TRIP_STRUCT_PLAIN:
        if k in s:
            return v
    return ""


def trip_house_rows(bld, floor, mountain, unknown="대장에 안 적힘"):
    """건축물대장 값을 있는 그대로 보여줄 표. [(항목, 값)]"""
    if not bld:
        return []
    rows = []
    rows.append(("주용도", bld.get("purpose") or unknown))
    s = bld.get("structure") or ""
    rows.append(("구조", (f"{s} ({_trip_plain_struct(s)})" if _trip_plain_struct(s) else s) if s else unknown))
    rows.append(("지붕", bld.get("roof") or unknown))
    if bld.get("year"):
        rows.append(("준공", f"{bld['year']}년 · {date.today().year - bld['year']}년 차"))
    else:
        rows.append(("준공", unknown))
    grnd, ugrnd = bld.get("grnd") or 0, bld.get("ugrnd") or 0
    rows.append(("층수", (f"지상 {grnd}층" if grnd else unknown) + (f" · 지하 {ugrnd}층" if ugrnd else "")))
    elev = bld.get("elevators")
    rows.append(("승강기", unknown if elev is None else (f"있음 · {elev}대" if elev else "없음")))
    hh, dongs = bld.get("households") or 0, bld.get("dongs") or 0
    if hh or dongs > 1:
        rows.append(("규모", " · ".join(x for x in (f"{hh}세대" if hh else "", f"{dongs}개 동" if dongs > 1 else "") if x)))
    if mountain:
        rows.append(("땅", "산 지번"))
    return rows


def trip_interpret(bld, floor, mountain, missing=False):
    """반환: notes=[(아이콘, 조심할 점, 짧은 설명)], checks=[가서 볼 것]"""
    facts, checks = [], []
    if missing:
        facts.append(("alert", "대장에 없는 집", "무허가·미등기일 수 있어요. 주거지원에서 빠졌는지 보세요"))
        checks += ["언제 지은 집인지, 증축한 곳이 있는지", "지붕 재질(슬레이트인지)"]
    if bld:
        age = (date.today().year - bld["year"]) if bld.get("year") else None
        if age is not None and age >= 30:
            facts.append(("clock", f"지은 지 {age}년", "단열·배관이 낡았을 수 있어요"))
            checks.append("겨울에 난방을 실제로 켜시는지")
        elif age is not None and age >= 20:
            facts.append(("clock", f"지은 지 {age}년", "욕실·배관 교체 시기예요"))
            checks.append("욕실 손잡이, 미끄럼 방지 매트")
        s = bld.get("structure") or ""
        if any(w in s for w in TRIP_WOOD):
            facts.append(("fire", "나무·흙집", "불에 약하고 겨울에 추워요"))
            checks.append("전열기구·화기 사용과 화재경보기")
        elif any(w in s for w in TRIP_MASONRY):
            facts.append(("brick", "벽돌·블록집", "춥고 곰팡이가 생기기 쉬워요"))
        if "슬레이트" in (bld.get("roof") or ""):
            facts.append(("roof", "슬레이트 지붕", "석면 가능성, 개량 지원 확인"))
        p = bld.get("purpose") or ""
        if "근린생활" in p:
            facts.append(("store", "상가용 건물", "상가 위 살림집·고시원일 수 있어요"))
        elif "숙박" in p:
            facts.append(("store", "숙박시설", "여관·모텔 장기투숙일 수 있어요"))
        elif p and not any(w in p for w in ("주택", "아파트", "공동", "업무")):
            facts.append(("store", "주거용 아닌 건물", f"{p}에 살고 계세요"))

        grnd, ugrnd, elev = bld.get("grnd") or 0, bld.get("ugrnd") or 0, bld.get("elevators")
        if elev == 0 and grnd >= 3:
            facts.append(("stairs", f"승강기 없는 {grnd}층 건물", "위층이면 매일 계단을 올라요"))
            checks.append("몇 층에 사시는지, 계단을 혼자 오르내리실 수 있는지")
        elif elev == 1 and grnd >= 6:
            facts.append(("lift", "승강기 1대뿐", "고장 나면 외출이 끊겨요"))
            checks.append("엘리베이터가 멈추면 어떻게 하시는지")
        elif elev is None and grnd >= 2:
            facts.append(("lift", "승강기 정보 없음", "현장에서 꼭 확인하세요"))
            checks.append("엘리베이터가 있는지, 몇 층에 사시는지")
        # 지하층 있는 5층 이하 주택(빌라·다가구) — 아파트 지하주차장은 제외
        if ugrnd and grnd <= 5 and any(w in p for w in ("주택", "공동")) and "아파트" not in p:
            facts.append(("drop", "지하층이 있는 건물", "반지하에 사시면 습기·침수 주의"))
            checks.append("반지하인지, 비 오면 물이 새거나 차는지")
    if mountain:
        facts.append(("hill", "산 지번", "집 앞이 언덕길일 수 있어요"))
        checks.append("집 밖 오르막을 혼자 다니실 수 있는지")
    for d in ("지금 몇 분이 같이 사시는지", "장보기·청소는 누가 하시는지"):
        if len(checks) < 3:
            checks.append(d)
    return facts, list(dict.fromkeys(checks))[:3]

# ---------- 출장 도구함: toilets ----------
TRIP_TOILET_RADIUS = 5000
TRIP_TOILET_LIMIT = 15
TRIP_OPEN_LABEL = {"상시": "상시 개방", "정시": "정해진 시간 개방", "불규칙": "개방 불규칙", "미개방": "개방 안 함"}
TRIP_TOILET_FILE = "trip_toilets.csv"
TRIP_TOILET_CSV_URL = "https://file.localdata.go.kr/file/download/public_restroom_info/info"
TRIP_TOILET_INFO_URL = "https://file.localdata.go.kr/file/public_restroom_info/info"
TRIP_TOILET_REFRESH_SEC = 7 * 86400
TRIP_TOILET_NEW_GEOCODE_MAX = 800

# 행: (관리번호, 이름, 주소, 위도, 경도, 개방시간, 비상벨, 장애인화장실, 그 화장실 자료 마지막 수정일)
_TRIP_TOILET_CACHE = {"key": None, "rows": [], "date": ""}
_TRIP_TOILET_LIVE = {"rows": None, "at": 0.0, "busy": False, "date": "", "note": "", "store_tried": False, "ok_at": 0.0}
_TRIP_TOILET_LOCK = threading.Lock()


def _trip_s(v):
    return "" if v is None or (isinstance(v, float) and _trip_math.isnan(v)) else str(v).strip()


def _trip_toilet_find(name):
    for p in (name, os.path.join("mapdata", name)):
        if os.path.exists(p):
            return p
    return None


def _trip_toilet_num(v):
    try:
        return int(float(_trip_s(v) or 0))
    except ValueError:
        return 0


def _trip_toilet_from_localdata(r):
    """LOCALDATA 공중화장실 한 행(dict) → 좌표 없는 행. 구분명 이동화장실은 위치가 바뀌어서 뺀다"""
    if _trip_s(r.get("구분명")) == "이동화장실":
        return None
    acc = any(_trip_toilet_num(r.get(c)) > 0 for c in ("남성용-장애인용대변기수", "남성용-장애인용소변기수", "여성용-장애인용대변기수"))
    return {"id": _trip_s(r.get("관리번호")), "name": _trip_s(r.get("화장실명")),
            "road": _trip_s(r.get("소재지도로명주소")), "jibun": _trip_s(r.get("소재지지번주소")),
            "open": _trip_s(r.get("개방시간")), "bell": _trip_s(r.get("비상벨설치여부")) == "Y", "acc": acc,
            "date": _trip_s(r.get("최종수정시점"))[:10]}


TRIP_TOILET_CSV_HEAD = ["관리번호", "화장실명", "주소", "위도", "경도", "개방시간", "비상벨", "장애인화장실", "데이터기준일자"]


def _trip_toilet_rows_from_csv(text):
    rows, date = [], ""
    for r in csv.DictReader(io.StringIO(text)):
        try:
            lat, lng = float(r["위도"]), float(r["경도"])
        except (KeyError, TypeError, ValueError):
            continue
        rows.append((_trip_s(r.get("관리번호")), _trip_s(r.get("화장실명")), _trip_s(r.get("주소")), lat, lng,
                     _trip_s(r.get("개방시간")), _trip_s(r.get("비상벨")) == "Y", _trip_s(r.get("장애인화장실")) == "Y",
                     _trip_s(r.get("데이터기준일자"))[:10]))
        date = max(date, _trip_s(r.get("데이터기준일자")))
    return rows, date


def _trip_toilet_rows_to_csv(rows, date):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(TRIP_TOILET_CSV_HEAD)
    for t in rows:
        w.writerow([t[0], t[1], t[2], round(t[3], 6), round(t[4], 6), t[5], "Y" if t[6] else "N",
                    "Y" if t[7] else "N", t[8] if len(t) > 8 else date])   # 화장실마다 마지막 수정일
    return buf.getvalue()


def _trip_toilet_load_national(path):
    return _trip_toilet_rows_from_csv(open(path, encoding="utf-8-sig").read())


# ---- 새로 받은 자료를 Supabase 저장소(버킷 trip, 비공개)에 보관 → 서버가 재시작돼도 마지막 자료·날짜 유지 ----
def _trip_toilet_store():
    url, key = os.environ.get("SUPABASE_URL", ""), os.environ.get("SUPABASE_KEY", "")
    if not url or not key:
        return None, None
    return url.rstrip("/") + "/storage/v1", {"apikey": key, "Authorization": f"Bearer {key}"}


# v2: 화장실마다 수정일을 따로 보관 (v1은 전부 같은 날짜로 덮어써서 버림)
def _trip_toilet_save_live(rows, date):
    base, h = _trip_toilet_store()
    if not base:
        return "저장소 없음"
    requests.post(f"{base}/bucket", headers=h, json={"id": "trip", "name": "trip", "public": False}, timeout=15)
    r = requests.post(f"{base}/object/trip/toilets_live_v2.csv", data=_trip_toilet_rows_to_csv(rows, date).encode("utf-8"),
                      headers={**h, "x-upsert": "true", "Content-Type": "text/csv"}, timeout=60)
    return "저장소 보관" if r.ok else f"저장소 보관 실패 {r.status_code}"


def _trip_toilet_load_store():
    """저장소에 보관된 마지막 자료 → (rows, date, 보관 시각). 없거나 실패하면 None"""
    base, h = _trip_toilet_store()
    if not base:
        return None
    try:
        r = requests.get(f"{base}/object/authenticated/trip/toilets_live_v2.csv", headers=h, timeout=30)
        if not r.ok:
            return None
        rows, date = _trip_toilet_rows_from_csv(r.content.decode("utf-8-sig"))
        try:
            from email.utils import parsedate_to_datetime
            at = parsedate_to_datetime(r.headers.get("Last-Modified", "")).timestamp()
        except Exception:
            at = time.time()
        return (rows, date, at) if rows else None
    except Exception:
        return None


def _trip_toilet_load_xlsx(path):
    df = pd.read_excel(path)
    if "구분" in df.columns:
        df = df[df["구분"].astype(str).str.strip() == "공중화장실"]
    df["위도"] = pd.to_numeric(df["위도"], errors="coerce")
    df["경도"] = pd.to_numeric(df["경도"], errors="coerce")
    df = df[df["위도"].notna() & df["경도"].notna()]
    name_col = next((c for c in ("화장실명", "시설명", "명칭") if c in df.columns), None)
    return [("", _trip_s(r.get(name_col)) if name_col else "", _trip_s(r.get("주소")), float(r["위도"]), float(r["경도"]),
             _trip_s(r.get("개방시간")), _trip_s(r.get("비상벨")) == "Y", _trip_s(r.get("장애인화장실")) == "Y", "")
            for r in df.to_dict("records")]


def _trip_toilet_base():
    """파일에서 읽은 기본 자료 (파일이 바뀌면 다시 읽음). national=전국 파일 여부"""
    path = _trip_toilet_find(os.environ.get("TRIP_TOILET_FILE", TRIP_TOILET_FILE))
    national = bool(path)
    if not path:
        path = _trip_toilet_find(os.environ.get("TOILET_FILE", "공중화장실.xlsx"))
    if not path:
        return [], False
    key = (path, os.path.getmtime(path))
    if _TRIP_TOILET_CACHE["key"] != key:
        if national:
            rows, date = _trip_toilet_load_national(path)
        else:
            rows, date = _trip_toilet_load_xlsx(path), ""
        _TRIP_TOILET_CACHE.update(key=key, rows=rows, date=date)
    return _TRIP_TOILET_CACHE["rows"], national


def _trip_toilet_geocode(road, jibun, name):
    key = os.environ.get("KAKAO_KEY", "")
    if not key:
        return None
    h = {"Authorization": f"KakaoAK {key}"}
    tries = []
    for a in (road, jibun):
        if a:
            tries.append(("address", a))
            if " " in a:
                tries.append(("address", a.split(" ", 1)[1]))     # 시·도 이름이 바뀐 경우 대비
    if name and (road or jibun):
        tries.append(("keyword", f"{(road or jibun).split(' ')[1] if ' ' in (road or jibun) else ''} {name}".strip()))
    for kind, q in tries:
        try:
            r = requests.get(f"https://dapi.kakao.com/v2/local/search/{kind}.json", headers=h,
                             params={"query": q, "size": 1}, timeout=6)
            docs = r.json().get("documents", []) if r.ok else []
        except Exception:
            docs = []
        if docs:
            return float(docs[0]["y"]), float(docs[0]["x"])
    return None


def _trip_toilet_refresh(old):
    """전국 파일을 다시 받아 기존 좌표를 이어 붙이고, 새 화장실만 카카오로 좌표를 붙인다"""
    try:
        s = requests.Session()
        s.headers["User-Agent"] = "Mozilla/5.0"
        try:
            s.get(TRIP_TOILET_INFO_URL, timeout=15)
        except Exception:
            pass
        r = s.get(TRIP_TOILET_CSV_URL, headers={"Referer": TRIP_TOILET_INFO_URL}, timeout=120)
        r.raise_for_status()
        raw = r.content
        text = None
        for enc in ("utf-8-sig", "cp949"):
            try:
                text = raw.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        if not text or "관리번호" not in text[:2000]:
            raise ValueError("전국 화장실 파일 형식이 아님")
        by_id = {t[0]: (t[3], t[4]) for t in old if t[0]}
        by_addr = {t[2]: (t[3], t[4]) for t in old if t[2]}
        rows, new, date = [], 0, ""
        for rec in csv.DictReader(io.StringIO(text)):
            t = _trip_toilet_from_localdata(rec)
            if not t or _trip_s(t["open"]) == "미개방":
                continue
            addr = t["road"] or t["jibun"]
            xy = by_id.get(t["id"]) or by_addr.get(addr)
            # 새로 생기거나 고쳐진 화장실만 좌표를 구함. PC에서 일부러 뺀 곳(위치 불확실)은 다시 넣지 않음.
            # 번지 없는 주소는 위치가 부정확해 뺌
            if (not xy and new < TRIP_TOILET_NEW_GEOCODE_MAX and t["date"] > _TRIP_TOILET_CACHE["date"]
                    and any(ch.isdigit() for ch in addr)):
                new += 1
                xy = _trip_toilet_geocode(t["road"], t["jibun"], t["name"])
            if not xy:
                continue
            rows.append((t["id"], t["name"], addr, xy[0], xy[1], t["open"], t["bell"], t["acc"], t["date"]))
            date = max(date, t["date"])
        if len(rows) < len(old) * 0.8:
            raise ValueError(f"받은 건수가 너무 적음 ({len(rows)} / 기존 {len(old)})")
        try:
            kept = _trip_toilet_save_live(rows, date)
        except Exception as e:
            kept = f"저장소 보관 실패 {e}"
        _TRIP_TOILET_LIVE.update(rows=rows, date=date, ok_at=time.time(), at=time.time(), note=f"갱신 {len(rows)}건, 새 좌표 {new}건, {kept}")
    except Exception as e:
        _TRIP_TOILET_LIVE.update(note=f"갱신 실패: {e}", at=time.time() - TRIP_TOILET_REFRESH_SEC + 86400)   # 실패하면 하루 뒤 다시
    finally:
        _TRIP_TOILET_LIVE["busy"] = False


def trip_load_toilets():
    base, national = _trip_toilet_base()
    if national:
        with _TRIP_TOILET_LOCK:
            if not _TRIP_TOILET_LIVE["store_tried"] and os.environ.get("TRIP_TOILET_AUTO", "1") != "0":
                _TRIP_TOILET_LIVE["store_tried"] = True
                got = _trip_toilet_load_store()
                if got and got[1] >= _TRIP_TOILET_CACHE["date"]:  # 새로 push한 파일이 더 최신이면 파일 우선
                    _TRIP_TOILET_LIVE.update(rows=got[0], date=got[1], at=got[2], ok_at=got[2])
            # push·재시작과 상관없이 '마지막으로 받은 때'(저장소 보관 시각)부터 7일. 한 번도 안 받았으면 바로 받음
            due = time.time() - _TRIP_TOILET_LIVE["at"] > TRIP_TOILET_REFRESH_SEC
            if due and not _TRIP_TOILET_LIVE["busy"] and os.environ.get("TRIP_TOILET_AUTO", "1") != "0":
                _TRIP_TOILET_LIVE["busy"] = True
                threading.Thread(target=_trip_toilet_refresh, args=(_TRIP_TOILET_LIVE["rows"] or base,), daemon=True).start()
    return _TRIP_TOILET_LIVE["rows"] if _TRIP_TOILET_LIVE["rows"] is not None else base


def trip_toilet_data_date():
    """화면에 보일 기준일: 행안부에서 마지막으로 받아 확인한 날 (바뀐 게 없어도 그날로). 아직 못 받았으면 파일의 자료 날짜"""
    if _TRIP_TOILET_LIVE["ok_at"]:
        from datetime import datetime, timedelta, timezone
        return datetime.fromtimestamp(_TRIP_TOILET_LIVE["ok_at"], timezone(timedelta(hours=9))).strftime("%Y-%m-%d")
    return _TRIP_TOILET_LIVE["date"] or _TRIP_TOILET_CACHE["date"]


def _trip_dist(lat1, lng1, lat2, lng2):
    r = 6371000
    p1, p2 = _trip_math.radians(lat1), _trip_math.radians(lat2)
    dp, dl = p2 - p1, _trip_math.radians(lng2 - lng1)
    h = _trip_math.sin(dp / 2) ** 2 + _trip_math.cos(p1) * _trip_math.cos(p2) * _trip_math.sin(dl / 2) ** 2
    return 2 * r * _trip_math.asin(_trip_math.sqrt(h))


def trip_nearest_toilets(lat, lng, rows, only_always=False, need_bell=False, need_accessible=False):
    dlat, dlng = TRIP_TOILET_RADIUS / 111000, TRIP_TOILET_RADIUS / (111000 * max(0.2, _trip_math.cos(_trip_math.radians(lat))))
    out = []
    for t in rows:
        if isinstance(t, dict):        # 예시 데이터
            t = ("", t["name"], t["address"], t["lat"], t["lng"], t["open"], t["bell"], t["accessible"], "")
        _, name, addr, tlat, tlng, op, bell, acc, upd = t
        if abs(tlat - lat) > dlat or abs(tlng - lng) > dlng:
            continue
        if op == "미개방" or (only_always and op != "상시") or (need_bell and not bell) or (need_accessible and not acc):
            continue
        d = _trip_dist(lat, lng, tlat, tlng)
        if d <= TRIP_TOILET_RADIUS:
            out.append({"name": name, "address": addr, "lat": tlat, "lng": tlng, "open": op, "bell": bell,
                        "accessible": acc, "distance": int(d), "open_label": TRIP_OPEN_LABEL.get(op, op or "정보 없음"),
                        "walk_min": max(1, round(d / 67)), "updated": upd[:7]})
    out.sort(key=lambda x: x["distance"])
    return out[:TRIP_TOILET_LIMIT]

# ---------- 출장 도구함: pills ----------
_trip_log = logging.getLogger(__name__)

TRIP_PILL_FILE = os.environ.get("PILL_FILE", "pills.csv")
_TRIP_PILL_CACHE = {"mtime": None, "rows": []}
TRIP_PILL_DEMENTIA_KW = ["도네페질", "리바스티그민", "갈란타민", "메만틴", "아리셉트", "엑셀론", "레미닐", "에빅사"]
TRIP_PILL_COLORS = ["하양", "노랑", "주황", "분홍", "빨강", "갈색", "연두", "초록", "청록", "파랑", "남색", "자주", "보라", "회색", "검정", "투명"]
TRIP_PILL_SHAPES = ["원형", "타원형", "장방형", "반원형", "삼각형", "사각형", "마름모형", "오각형", "육각형", "팔각형", "기타"]
TRIP_PILL_FORMS = ["정제", "경질캡슐", "연질캡슐"]


def _trip_pill_form_kind(form_name):
    """식약처 제형명(FORM_CODE_NAME) → 정제 / 경질캡슐 / 연질캡슐 (그 외는 빈 값)"""
    f = str(form_name or "")
    if "연질" in f:
        return "연질캡슐"
    if "캡슐" in f:
        return "경질캡슐"
    if "정" in f:
        return "정제"
    return ""


def _trip_pill_norm(s):
    """각인 비교용 정규화: 대문자, '분할선'·'마크' 등 설명어 제거, 글자·숫자만 남김"""
    s = str(s or "").upper()
    for w in ("분할선", "마크", "각인", "없음"):
        s = s.replace(w, "")
    return re.sub(r"[^0-9A-Z가-힣]", "", s)


def trip_load_pills():
    try:
        mtime = os.path.getmtime(TRIP_PILL_FILE)
    except OSError:
        return []
    if _TRIP_PILL_CACHE["mtime"] == mtime:
        return _TRIP_PILL_CACHE["rows"]
    try:
        pdf = pd.read_csv(TRIP_PILL_FILE, dtype=str).fillna("")
    except Exception as e:
        _trip_log.exception(e)
        return _TRIP_PILL_CACHE["rows"]
    rows = []
    for r in pdf.to_dict("records"):
        name = r.get("ITEM_NAME", "")
        prints = [p for p in (_trip_pill_norm(r.get("PRINT_FRONT")), _trip_pill_norm(r.get("PRINT_BACK"))) if p]
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
            "_kind": _trip_pill_form_kind(r.get("FORM_CODE_NAME", "")),
            "dementia": any(k in name for k in TRIP_PILL_DEMENTIA_KW),
        })
    _TRIP_PILL_CACHE["mtime"] = mtime
    _TRIP_PILL_CACHE["rows"] = rows
    return rows


# 사진에서 자주 헷갈리는 글자 → 같은 대표 글자로 바꿔 비교 (정확히 같은 글자보다는 낮게 인정)
_TRIP_PILL_CONFUSE = str.maketrans({"O": "0", "Q": "0", "I": "1", "L": "1", "B": "8",
                               "S": "5", "Z": "2", "T": "7", "G": "6"})


def _trip_pill_canon(s):
    return s.translate(_TRIP_PILL_CONFUSE)


def _trip_pill_imprint_score(photo_prints, pill_prints):
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
            cp, cd = _trip_pill_canon(p), _trip_pill_canon(d)
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
TRIP_PILL_CARE_MAP = {
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


def _trip_pill_care(cls, dementia=False):
    """약 1개의 쉬운 이름과 돌봄 신호. 치매약은 이름으로 판별(분류명이 '기타의 중추신경용약' 등으로 흩어져 있음)"""
    if dementia:
        return {"kind": "치매약", "signals": ["인지 지원"]}
    cls = str(cls or "").strip()
    for key, (kind, signals) in TRIP_PILL_CARE_MAP.items():
        if key in cls:
            return {"kind": kind, "signals": list(signals)}
    kind = re.sub(r"^\[\d+\]\s*", "", cls).replace("기타의 ", "").strip() or "기타 약"
    return {"kind": kind, "signals": []}


def trip_search_pills(imprints, color="", shape="", capsule=None, limit=3, form=""):
    """각인(필수) + 색·모양(보조)으로 후보를 점수순으로 반환
    form: 사용자가 고른 제형(정제/경질캡슐/연질캡슐). 고르면 해당 제형만, 빈 값이면 전체"""
    photo_prints = [p for p in (_trip_pill_norm(x) for x in (imprints or [])) if p]
    if not photo_prints:
        return []
    results = []
    for row in trip_load_pills():
        if form and row["_kind"] != form:
            continue
        s_imp = _trip_pill_imprint_score(photo_prints, row["_prints"])
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
        item["care"] = _trip_pill_care(row["cls"], row["dementia"])
        out.append(item)
    return out


TRIP_PILL_MAX = 10          # 한 번에 처리하는 최대 알약 수
TRIP_PILL_RECOMMEND = 5     # 권장 알약 수 (넘으면 안내)


def _trip_pill_features_from_images(images):
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
        f"사진마다 보이는 알약을 하나씩 모두 적어 (최대 {TRIP_PILL_MAX}개).\n"
        "알약 1개는 반드시 1개로만 적어. 한 알약의 글자가 분할선 등으로 나뉘어 있어도 별도 알약으로 나누지 말고, 같은 알약을 두 번 적지 마.\n"
        "알약마다 imprint(알약에 새겨지거나 인쇄된 글자·숫자를 보이는 그대로, 로고나 그림이면 빈 문자열, "
        "분할선으로 나뉜 글자는 이어서), color, shape, form, 그리고 사진 안에서 알약 중심의 위치 x, y"
        "(사진 너비·높이 대비 비율 0~1, 왼쪽 위가 0)를 적어.\n"
        f"color는 다음 중 하나: {', '.join(TRIP_PILL_COLORS)}\n"
        f"shape는 다음 중 하나: {', '.join(TRIP_PILL_SHAPES)}\n"
        "form은 '정제', '캡슐', '모름' 중 하나.\n"
        "photos 배열은 사진 순서대로 하나씩, 각 사진의 pills 배열에 알약을 넣어.\n"
        '형식: {"photos":[{"pills":[{"imprint":"","color":"","shape":"","form":"정제","x":0.5,"y":0.5}]}]}'
    )}]
    for _, mime, data in images:
        b64 = base64.b64encode(data).decode("utf-8")
        content.append({"type": "input_image", "image_url": f"data:{mime};base64,{b64}", "detail": "high"})

    res = client.responses.create(model=os.environ.get("OPENAI_MODEL", "gpt-4.1-mini"), input=[{"role": "user", "content": content}], temperature=0)
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
        for p in pills[:TRIP_PILL_MAX]:
            if not isinstance(p, dict):
                continue
            form = p.get("form", "모름")
            clean.append({
                "imprint": str(p.get("imprint", "") or "").strip(),
                "color": p.get("color") if p.get("color") in TRIP_PILL_COLORS else "",
                "shape": p.get("shape") if p.get("shape") in TRIP_PILL_SHAPES else "",
                "capsule": True if form == "캡슐" else (False if form == "정제" else None),
                "x": _num(p.get("x")),
                "y": _num(p.get("y")),
            })
        out[lb] = clean
    return out


def _trip_pill_norm_positions(pills):
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


def _trip_pill_pair_by_position(front, back):
    """같은 자리에서 뒤집었으므로 '배치상 같은 위치'끼리 앞·뒷면 짝을 맞춤.
    반환: [(앞면 index 또는 None, 뒷면 index 또는 None), ...]  앞면 순서 유지"""
    from itertools import permutations
    fp, bp = _trip_pill_norm_positions(front), _trip_pill_norm_positions(back)
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


def _trip_pill_group(no, imprints, color, shape, capsule=None):
    """알약 1개 결과 묶음 만들기"""
    # AI가 '정제'로 읽은 경우만 제형을 미리 채움 (캡슐은 경질/연질 구분이 어려워 '전체'로 둠)
    feats = {"imprint": " / ".join(imprints), "color": color, "shape": shape,
             "form": "정제" if capsule is False else ""}
    if not imprints:
        return {"no": no, "features": feats, "candidates": [],
                "message": "각인(글자)을 읽지 못했습니다. 이 알약은 글자가 보이도록 가까이 따로 찍거나, 위에 각인을 직접 입력해 주세요."}
    cands = trip_search_pills(imprints, color, shape, capsule)
    return {"no": no, "features": feats, "candidates": cands,
            "message": "" if cands else "일치하는 알약을 찾지 못했습니다. 인식된 각인을 직접 고쳐서 다시 찾아보세요."}


def _trip_pill_build_groups(front, back):
    """앞·뒷면을 배치 위치로 짝지어 알약마다 결과 묶음 만들기 (1알이면 기존과 동일)"""
    if not front and back:
        front, back = back, []
    groups = []
    for fi, bi in _trip_pill_pair_by_position(front, back):
        if fi is None:
            continue   # 뒷면에서만 보인 것(바닥 무늬 오인식 등)은 별도 알약으로 만들지 않음
        sides = ([front[fi]] if fi is not None else []) + ([back[bi]] if bi is not None else [])
        imprints = [s["imprint"] for s in sides if s["imprint"]]
        color = next((s["color"] for s in sides if s["color"]), "")
        shape = next((s["shape"] for s in sides if s["shape"]), "")
        capsule = next((s["capsule"] for s in sides if s["capsule"] is not None), None)
        groups.append(_trip_pill_group(len(groups) + 1, imprints, color, shape, capsule))
    return groups


# ---------- 출장 도구함: demo_data ----------
TRIP_DEMO_PLACES = {
    "지사": {"label": "출발지 (예시)", "road_address": "광주 광산구 (예시 좌표)", "lat": 35.1395, "lng": 126.7935},
    "라인2차": {"label": "소촌라인2차", "road_address": "광주 광산구 금봉로 18", "lat": 35.1420, "lng": 126.7980},
    "미소래": {"label": "소촌2차 국제미소래", "road_address": "광주 광산구 소촌로42번길 163", "lat": 35.1475, "lng": 126.8060},
    "라인1차": {"label": "소촌라인1차", "road_address": "광주 광산구 소촌동", "lat": 35.1455, "lng": 126.7955},
}

TRIP_DEMO_HOUSES = {
    "라인2차": {"loc": {**TRIP_DEMO_PLACES["라인2차"], "plat_gb_cd": "0"},
             "bld": {"name": "소촌라인2차", "purpose": "공동주택", "structure": None, "roof": None, "year": 1997,
                     "grnd": 10, "ugrnd": None, "elevators": None, "households": 436, "dongs": 7},
             "extra": [], "source": "아파트지인·리치고 단지정보"},
    "미소래": {"loc": {**TRIP_DEMO_PLACES["미소래"], "plat_gb_cd": "1"},
            "bld": {"name": "소촌2차 국제미소래", "purpose": "공동주택", "structure": None, "roof": None, "year": None,
                    "grnd": None, "ugrnd": None, "elevators": None, "households": 382, "dongs": 9},
            "extra": [], "source": "노잉애셋 단지정보"},
}

TRIP_DEMO_TOILETS = [
    {"name": "예시 공중화장실 A", "address": "예시 주소", "lat": 35.1402, "lng": 126.7948, "open": "상시", "bell": True, "accessible": True},
    {"name": "예시 공중화장실 B", "address": "예시 주소", "lat": 35.1431, "lng": 126.7901, "open": "정시", "bell": False, "accessible": True},
    {"name": "예시 공중화장실 C", "address": "예시 주소", "lat": 35.1465, "lng": 126.8012, "open": "상시", "bell": True, "accessible": False},
]


def trip_demo_place(q):
    for k, v in TRIP_DEMO_PLACES.items():
        if k in q:
            return dict(v)
    return None


def trip_demo_house(q):
    for k, v in TRIP_DEMO_HOUSES.items():
        if k in q:
            return v
    return None

# ---------- 출장 도구함: init ----------
try:
    from openai import OpenAI
except ImportError:
    OpenAI = None

trip_bp = Blueprint("trip", __name__, url_prefix="/trip")

TRIP_PII = [re.compile(r"\d{6}\s*-?\s*[1-4]\d{6}"), re.compile(r"01[016789]\s*-?\s*\d{3,4}\s*-?\s*\d{4}")]


def trip_demo():
    return os.environ.get("TRIP_DEMO") == "1" or not os.environ.get("KAKAO_KEY")


def trip_has_pii(*texts):
    return any(p.search(t or "") for p in TRIP_PII for t in texts)


@trip_bp.context_processor
def trip_inject():
    return {"demo": trip_demo(), "kakao_js_key": os.environ.get("KAKAO_JS_KEY") or os.environ.get("KAKAO_KEY", ""),
            "safemap_key": os.environ.get("SAFEMAP_KEY", ""),
            "safemap_wms": os.environ.get("SAFEMAP_WMS_URL", "https://www.safemap.go.kr/openapi2/IF_0087_WMS"),
            "crime_layers": trip_crime_layers()}


# 범죄주의구간 종류별 레이어. IF 번호가 바뀌면 SAFEMAP_IF_<키> 환경변수로 덮어쓰면 됨 (예: SAFEMAP_IF_RAPE=IF_0085)
TRIP_CRIME_LAYERS = [  # (키, 이름, 기본 IF 번호, 스타일)
    ("TOT", "전체", "IF_0087", "A2SM_CrmnlHspot_Tot_Tot"),
    ("RAPE", "성폭력", "IF_0085", "A2SM_CrmnlHspot_Tot_Rape"),
    ("BRGLR", "강도", "IF_0086", "A2SM_CrmnlHspot_Tot_Brglr"),
    ("VIOLN", "폭력", "IF_0083", "A2SM_CrmnlHspot_Tot_Violn"),
    ("THEFT", "절도", "IF_0084", "A2SM_CrmnlHspot_Tot_Theft"),
]


def trip_crime_layers():
    base = "https://www.safemap.go.kr/openapi2/"
    out = []
    for key, name, if_id, style in TRIP_CRIME_LAYERS:
        if_id = os.environ.get(f"SAFEMAP_IF_{key}", if_id)
        url = os.environ.get("SAFEMAP_WMS_URL") if key == "TOT" and os.environ.get("SAFEMAP_WMS_URL") else f"{base}{if_id}_WMS"
        out.append({"key": key, "name": name, "url": url,
                    "style": os.environ.get(f"SAFEMAP_STYLE_{key}", style)})
    return out


TRIP_SIDO_SHORT = ("서울", "부산", "대구", "인천", "광주", "대전", "울산", "세종", "경기", "강원",
              "충북", "충남", "전북", "전남", "경북", "경남", "제주")


@trip_bp.app_template_filter("short_addr")
def trip_short_addr(s):
    """화면용 주소: 맨 앞 시·도는 빼고 시·군·구부터. '전남광주통합특별시 신안군 …' → '신안군 …'"""
    s = (s or "").strip()
    t = s.split(" ", 2)
    if len(t) >= 2 and t[1].endswith(("시", "군", "구")) and (t[0].endswith(("시", "도")) or t[0] in TRIP_SIDO_SHORT):
        return s.split(" ", 1)[1]
    return s


@trip_bp.app_template_filter("trip_km")
def trip_km(m):
    return "-" if m is None else (f"{m}m" if m < 1000 else f"{m / 1000:.1f}km")


@trip_bp.get("/", endpoint="home")
def trip_home():
    return render_template("trip/home.html")


@trip_bp.get("/api/where", endpoint="api_where")
def trip_api_where():
    """좌표 → 주소 (현재 위치가 어디인지 보여주기용, 저장 안 함)"""
    try:
        lat, lng = float(request.args["lat"]), float(request.args["lng"])
    except (KeyError, ValueError):
        return jsonify(address="")
    if trip_demo():
        return jsonify(address="광주 광산구 (예시 위치)")
    try:
        return jsonify(address=trip_where(lat, lng))
    except Exception:
        return jsonify(address="")


@trip_bp.get("/api/suggest", endpoint="api_suggest")
def trip_api_suggest():
    """주소 자동완성 (동선·집 미리보기 공용). 주소로 쳐도 실제 주소가 뜨도록 주소 검색 → 장소 검색 순"""
    q = (request.args.get("q") or "").strip()
    if len(q) < 2 or trip_demo() or trip_has_pii(q):
        return jsonify(documents=[])
    try:
        return jsonify(documents=trip_addr_suggest(q))
    except Exception:
        return jsonify(documents=[])


# ---------- 1. 최적 동선 ----------
@trip_bp.get("/route", endpoint="route_page")
def trip_route_page():
    return render_template("trip/route.html", max_stops=TRIP_MAX_STOPS)


def _trip_picked(p):
    """자동완성에서 고른 곳이면 좌표를 그대로 씀 (다시 검색하지 않음)"""
    try:
        return {"label": str(p.get("label") or ""), "road_address": str(p.get("road_address") or ""),
                "lat": float(p["lat"]), "lng": float(p["lng"])}
    except (AttributeError, KeyError, TypeError, ValueError):
        return None


def _trip_resolve(q, gps=None, pick=None):
    if pick:
        return pick
    if gps:
        addr = ""
        if not trip_demo():
            try:
                addr = trip_where(gps[0], gps[1])
            except Exception:
                addr = ""
        return {"label": "현재 위치", "road_address": addr, "lat": gps[0], "lng": gps[1]}
    if trip_demo():
        return trip_demo_place(q)
    c = trip_addr_search(q, limit=1)
    return c[0] if c else None


@trip_bp.post("/api/route", endpoint="api_route")
def trip_api_route():
    d = request.get_json(silent=True) or {}
    start_q = (d.get("start") or "").strip()
    stops_q = [s.strip() for s in d.get("stops", []) if s and s.strip()][: TRIP_MAX_STOPS]
    back = bool(d.get("return_to_start", True))
    end_q = start_q if back else (d.get("end") or "").strip()
    gps = d.get("gps")
    if not (start_q or gps) or not stops_q or not (end_q or gps):
        return jsonify(ok=False, message="출발지와 방문지를 한 곳 이상 넣어주세요.")
    if trip_has_pii(start_q, end_q, *stops_q):
        return jsonify(ok=False, message="주민번호나 전화번호는 넣지 마세요. 주소만 입력하면 돼요.")
    picks = d.get("picks") or {}
    stop_picks = [_trip_picked(p) for p in (picks.get("stops") or [])] + [None] * len(stops_q)
    start_pick = _trip_picked(picks.get("start"))
    end_pick = start_pick if back else _trip_picked(picks.get("end"))
    queries = [("출발", start_q, gps, start_pick)] \
        + [(f"방문지 {i + 1}", q, None, stop_picks[i]) for i, q in enumerate(stops_q)] \
        + [("도착", end_q, gps if back else None, end_pick)]
    try:
        with ThreadPoolExecutor(max_workers=8) as ex:
            found = list(ex.map(lambda x: _trip_resolve(x[1], x[2], x[3]), queries))
    except Exception:
        return jsonify(ok=False, message="주소 검색에 실패했어요. 잠시 후 다시 시도하세요.")
    missing = [f"{name} '{q}'" for (name, q, _, _), f in zip(queries, found) if not f]
    if missing:
        return jsonify(ok=False, message=f"{', '.join(missing)}을(를) 찾지 못했어요. 도로명 주소나 단지명으로 다시 넣어주세요.")
    found = [dict(f) if f else f for f in found]
    for (name, q, _, _), f in zip(queries, found):
        f["input"], f["role"] = q, name
    # 순서 고정: 방문지와 같은 순서로 [None | 번째 | "last"]
    pins, used = [], set()
    for p in (d.get("pins") or [])[:len(stops_q)]:
        v = "last" if p == "last" else (int(p) if str(p).isdigit() and 1 <= int(p) <= len(stops_q) else None)
        if v == len(stops_q):
            v = "last"
        if v is not None and v in used:
            return jsonify(ok=False, message="같은 번째에 두 곳을 고정했어요. 하나를 풀어주세요.")
        if v is not None:
            used.add(v)
        pins.append(v)
    for f, p in zip(found[1:-1], pins + [None] * len(stops_q)):
        if p:
            f["pin"] = "마지막" if p == "last" else f"{p}번째"
    leg = trip_estimate_leg if trip_demo() else trip_directions
    try:
        res = trip_optimize(found[0], found[1:-1], found[-1], leg, keep_order=bool(d.get("keep_order")), pins=pins)
    except TripPinConflict:
        return jsonify(ok=False, message="고정한 순서끼리 겹쳐요. 고정을 다시 확인해 주세요.")
    except TripLegFail as e:
        nm = lambda p: p.get("label") or p.get("input") or p.get("role")
        code = getattr(e.err, "code", None)
        if code is None:   # 통신 오류 등 길 자체 문제가 아님
            return jsonify(ok=False, message="길찾기 서버 연결이 잠깐 안 돼요. 잠시 후 다시 눌러 주세요.")
        if code == 102:
            who = nm(e.a)
        elif code == 103:
            who = nm(e.b)
        else:
            who = f"{nm(e.a)} → {nm(e.b)}"
        return jsonify(ok=False, message=f"'{who}' 쪽은 차로 가는 길을 찾지 못했어요. "
                                         "섬·선착장·산길처럼 차도와 떨어진 곳이면 근처 도로 주소로 바꿔 넣어주세요.")
    except Exception:
        return jsonify(ok=False, message="길찾기에 실패했어요. 차로 갈 수 있는 주소인지 확인해 주세요.")
    res.update(ok=True, demo=trip_demo(), return_to_start=back)
    return jsonify(res)


# ---------- 2. 집 미리보기 ----------
@trip_bp.get("/house", endpoint="house_page")
def trip_house_page():
    return render_template("trip/house.html")


def _trip_floor(raw):
    raw = (raw or "").strip().replace("층", "")
    if not raw:
        return None
    if raw.startswith(("지하", "B", "b")):
        return -int(re.sub(r"\D", "", raw) or 1)
    return int(raw) if raw.lstrip("-").isdigit() else None


def _trip_house_card(loc, bld, floor, missing=False, extra=None, source=None):
    mountain = loc.get("plat_gb_cd") == "1"
    facts, checks = trip_interpret(bld, floor, mountain, missing)
    facts = (extra or []) + facts
    rows = trip_house_rows(bld, floor, mountain, unknown="실제 조회하면 표시" if trip_demo() else "대장에 안 적힘")
    return render_template("trip/house_card.html", loc=loc, bld=bld, floor=floor, facts=facts, rows=rows,
                           checks=checks, source=source, missing=missing)


@trip_bp.post("/house", endpoint="house_search")
def trip_house_search():
    q, floor_raw = request.form.get("q", "").strip(), request.form.get("floor", "")
    if not q:
        return render_template("trip/house.html", error="주소나 단지명을 넣어주세요.")
    if trip_has_pii(q, floor_raw):
        return render_template("trip/house.html", q=q, error="주민번호나 전화번호는 넣지 마세요. 주소만 입력하면 돼요.")
    floor = None   # 거주층은 받지 않음 (대장 값만으로 판단)
    if trip_demo():
        h = trip_demo_house(q)
        if not h:
            return render_template("trip/house.html", q=q, error="예시 모드에서는 라인2차, 미소래만 돼요.")
        return _trip_house_card(h["loc"], h["bld"], floor, extra=h["extra"], source=h["source"])
    picked_addr, picked_label = request.form.get("addr", "").strip(), request.form.get("label", "").strip()
    try:
        cands = trip_addr_search(picked_addr or q)
        if picked_addr and cands:
            cands = cands[:1]
            if picked_label:
                cands[0]["label"] = picked_label
    except Exception:
        return render_template("trip/house.html", q=q, error="주소 검색에 실패했어요. 잠시 후 다시 시도하세요.")
    if not cands:
        return render_template("trip/house.html", q=q, error="주소를 찾지 못했어요. 도로명 주소로 다시 넣어보세요.")
    pick = request.form.get("pick")
    if len(cands) > 1 and pick is None:
        return render_template("trip/house.html", q=q, floor=floor_raw, cands=cands)
    loc = cands[min(int(pick or 0), len(cands) - 1)]
    try:
        bld = trip_building(loc)
    except Exception:
        return _trip_house_card(loc, None, floor, source="건축물대장 조회 실패")
    return _trip_house_card(loc, bld, floor, missing=bld is None)


# ---------- 3. 내 근처 화장실 ----------
@trip_bp.get("/toilet", endpoint="toilet_page")
def trip_toilet_page():
    date = ""
    if not trip_demo():
        try:
            trip_load_toilets()
            date = trip_toilet_data_date()
        except Exception:
            date = ""
    return render_template("trip/toilet.html", toilet_date=date)


@trip_bp.get("/api/toilets", endpoint="api_toilets")
def trip_api_toilets():
    try:
        lat, lng = float(request.args["lat"]), float(request.args["lng"])
    except (KeyError, ValueError):
        return jsonify(ok=False, message="위치를 가져오지 못했어요.")
    rows = TRIP_DEMO_TOILETS if trip_demo() else trip_load_toilets()
    if not rows:
        return jsonify(ok=False, message="화장실 데이터(trip_toilets.csv)가 없어요. 관리자에게 알려주세요.")
    a = request.args
    found = trip_nearest_toilets(lat, lng, rows, a.get("always") == "1", a.get("bell") == "1", a.get("acc") == "1")
    # 차로 몇 분: 카카오모빌리티 실제 경로(실패하면 직선거리로 추정, '약' 표시)
    def car(t):
        if not trip_demo():
            try:
                leg = trip_directions({"lat": lat, "lng": lng}, {"lat": t["lat"], "lng": t["lng"]})
                return max(1, round(leg["duration"] / 60)), True
            except Exception:
                pass
        return max(1, round(t["distance"] * 1.4 / 400)), False
    if found:
        with ThreadPoolExecutor(max_workers=8) as ex:
            for t, (m, real) in zip(found, ex.map(car, found)):
                t["car_min"], t["car_real"] = m, real
    here = "광주 광산구 (예시 위치)" if trip_demo() else ""
    if not trip_demo():
        try:
            here = trip_where(lat, lng)
        except Exception:
            here = ""
    return jsonify(ok=True, items=found, demo=trip_demo(), here=here, date="" if trip_demo() else trip_toilet_data_date(),
                   message="" if found else "주변 5km 안에 조건에 맞는 화장실이 없어요.")


# ---------- 4. 복용약 찾기 ----------
@trip_bp.get("/pill", endpoint="pill_page")
def trip_pill_page():
    return render_template("trip/pill.html")


_TRIP_PILL_LAST = {}


def _trip_pill_throttle():
    """연속 호출 방지 (토큰 비용 보호): 같은 접속 5초 이내 재요청 차단 (케어내비와 같음)"""
    import time
    ip = request.headers.get("X-Forwarded-For", request.remote_addr or "").split(",")[0].strip()
    now = time.time()
    if now - _TRIP_PILL_LAST.get(ip, 0) < 5:
        return True
    _TRIP_PILL_LAST[ip] = now
    if len(_TRIP_PILL_LAST) > 2000:
        _TRIP_PILL_LAST.clear()
    return False


def _trip_pill_files(limit):
    images = []
    for key in ("front", "back"):
        f = request.files.get(key)
        if not f:
            continue
        if not (f.mimetype or "").startswith("image/"):
            return None, "이미지 파일만 올릴 수 있습니다."
        data = f.read()
        if len(data) > limit:
            return None, "이미지 용량은 8MB 이하만 가능합니다."
        images.append((key, f.mimetype, data))
    return images, ""


def _trip_pill_locate_boxes(images):
    """알약이 사진 어디에 있는지만 대략 찾음 (케어내비 코드 그대로, 저해상도)"""
    import base64
    import json
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


@trip_bp.post("/api/pill/locate", endpoint="api_pill_locate")
def trip_api_pill_locate():
    """알약 위치 찾기 (실패해도 됨: 휴대폰은 원래 사진 그대로 보냄)"""
    if not os.environ.get("OPENAI_API_KEY") or OpenAI is None:
        return jsonify(ok=False)
    images, err = _trip_pill_files(2 * 1024 * 1024)
    if not images:
        return jsonify(ok=False)
    try:
        boxes = _trip_pill_locate_boxes([(m, d) for _, m, d in images])
    except Exception:
        return jsonify(ok=False)
    return jsonify(ok=True, boxes={k: b for (k, _, _), b in zip(images, boxes)})


@trip_bp.post("/api/pill/identify", endpoint="api_pill_identify")
def trip_api_pill_identify():
    if not trip_load_pills():
        return jsonify(ok=False, message="알약 데이터(pills.csv)가 없습니다. 관리자에게 문의하세요.")
    if not os.environ.get("OPENAI_API_KEY") or OpenAI is None:
        return jsonify(ok=False, message="AI 설정이 되어 있지 않습니다. 관리자에게 문의하세요.")
    if _trip_pill_throttle():
        return jsonify(ok=False, message="요청이 너무 빠릅니다. 잠시 후 다시 시도해 주세요.")
    images, err = _trip_pill_files(8 * 1024 * 1024)
    if images is None:
        return jsonify(ok=False, message=err)
    if not images:
        return jsonify(ok=False, message="알약 사진을 찍어주세요.")
    try:
        feat = _trip_pill_features_from_images(images)
    except Exception:
        return jsonify(ok=False, message="사진 분석 중 오류가 발생했습니다. 다시 시도해 주세요.")
    front, back = feat.get("front", []), feat.get("back", [])
    if not front and not back:
        return jsonify(ok=True, groups=[], message="사진에서 알약을 찾지 못했습니다. 알약이 잘 보이도록 밝은 곳에서 다시 찍어주세요.")
    groups = _trip_pill_build_groups(front, back)
    count = len(front) or len(back)
    msg = ""
    if count > TRIP_PILL_RECOMMEND:
        msg = (f"알약이 {count}개로 많아 정확도가 떨어질 수 있습니다. "
               f"{TRIP_PILL_RECOMMEND}알 이하로 나눠 찍으면 더 정확합니다.")
    if front and back and len(front) != len(back):
        msg = (msg + " " if msg else "") + (f"앞면에서 {len(front)}개, 뒷면에서 {len(back)}개를 찾아 앞면 기준 {len(front)}개로 정리했습니다. "
                                            "알약끼리 떨어뜨리고 무늬 없는 바닥에서 찍으면 더 정확합니다.")
    return jsonify(ok=True, groups=groups, message=msg)


@trip_bp.post("/api/pill/search", endpoint="api_pill_search")
def trip_api_pill_search():
    d = request.get_json(silent=True) or {}
    imprints = [x.strip() for x in str(d.get("imprint", "")).split("/") if x.strip()]
    if not imprints:
        return jsonify(ok=True, candidates=[], message="각인(알약에 새겨진 글자)을 입력해 주세요.")
    if not trip_load_pills():
        return jsonify(ok=False, message="알약 데이터(pills.csv)가 없습니다. 관리자에게 문의하세요.")
    color = d.get("color") if d.get("color") in TRIP_PILL_COLORS else ""
    shape = d.get("shape") if d.get("shape") in TRIP_PILL_SHAPES else ""
    form = d.get("form") if d.get("form") in TRIP_PILL_FORMS else ""
    c = trip_search_pills(imprints, color, shape, form=form)
    return jsonify(ok=True, candidates=c, message="" if c else "일치하는 알약을 찾지 못했습니다.")


@trip_bp.get("/static/app.css", endpoint="css")
def trip_css():
    return Response(TRIP_CSS, mimetype="text/css")


TRIP_CSS = r'''@import url("https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/static/pretendard.min.css");
:root{
  --bg:#f4f2ec; --card:#fff; --ink:#1b1d1c; --sub:#5f625f; --muted:#9a9d98; --line:#e7e4dc;
  --route:#2f6fed; --route-bg:#e9f0fe;
  --house:#e0782f; --house-bg:#fdf0e5;
  --toilet:#13997a; --toilet-bg:#e4f5ef;
  --pill:#8b55d6; --pill-bg:#f1eafb;
  --warn:#9a5b06; --warn-bg:#fdf3dc; --bad:#b4332f; --bad-bg:#fcebea;
  --r:18px;
}
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
/* 한글 줄바꿈: 단어 중간에서 끊지 않고, 마지막 줄이 한 글자만 남지 않게 */
body{word-break:keep-all;overflow-wrap:break-word;line-break:strict}
.t,.nm,.hname,.wt .t{text-wrap:balance}
p,.d,.m,.hint,.note,.ad,.wt .d,.fact .m{text-wrap:pretty}
html,body{margin:0;background:var(--bg);color:var(--ink);
  font-family:Pretendard,"Apple SD Gothic Neo","Noto Sans CJK KR","Malgun Gothic",sans-serif;font-size:15px;line-height:1.55;letter-spacing:-0.01em}
a{color:inherit}
.wrap{max-width:480px;margin:0 auto;padding:18px 16px 40px;position:relative}
.ci{position:absolute;top:16px;right:16px;height:42px;max-width:84px;object-fit:contain;width:auto;z-index:5;pointer-events:none}
.bar{padding-right:96px}
.bar h1{white-space:nowrap}
.bar .tag{white-space:nowrap;flex:none}
.hello{padding-right:0}
.hello .date{padding-right:110px}
.hello h1{margin-top:22px}

/* 상단 */
.bar{display:flex;align-items:center;gap:10px;margin:2px 0 16px}
.bar a.back{width:38px;height:38px;border-radius:12px;background:var(--card);border:1px solid var(--line);display:flex;align-items:center;justify-content:center;text-decoration:none}
.bar h1{font-size:19px;margin:0;font-weight:700}
.bar .tag{margin-left:6px;font-size:12px;padding:3px 9px;border-radius:999px;background:var(--warn-bg);color:var(--warn);font-weight:600}

/* 홈 */
.hello{margin:6px 2px 18px}
.hello .date{font-size:13px;color:var(--muted);font-weight:600}
.hello h1{font-size:26px;line-height:1.3;margin:4px 0 0;font-weight:800;letter-spacing:-0.03em}
.tiles{display:grid;grid-template-columns:1fr 1fr;gap:12px}
.tile{position:relative;display:flex;flex-direction:column;justify-content:space-between;min-height:168px;padding:16px;border-radius:22px;
  text-decoration:none;color:var(--ink);background:var(--card);border:1px solid var(--line);overflow:hidden;transition:transform .15s}
.tile:active{transform:scale(.97)}
.tile .ico{width:48px;height:48px;border-radius:15px;display:flex;align-items:center;justify-content:center}
.tile .ico svg{width:26px;height:26px}
.tile .t{font-size:17px;font-weight:700;margin:14px 0 2px}
.tile .d{font-size:12.5px;color:var(--sub);line-height:1.45}
.tile .no{position:absolute;right:14px;top:12px;font-size:12px;font-weight:700;color:var(--muted)}
.tile.route .ico{background:var(--route-bg);color:var(--route)}
.tile.house .ico{background:var(--house-bg);color:var(--house)}
.tile.toilet .ico{background:var(--toilet-bg);color:var(--toilet)}
.tile.pill .ico{background:var(--pill-bg);color:var(--pill)}
.tile.wide{grid-column:span 2;min-height:auto;flex-direction:row;align-items:center;gap:14px}
.tile.wide .t{margin:0}
.note{font-size:12px;color:var(--muted);margin:18px 4px 0;line-height:1.6}

/* 공통 카드 */
.card{background:var(--card);border:1px solid var(--line);border-radius:var(--r);padding:16px 16px;margin-bottom:12px}
.hero{border-radius:var(--r);padding:16px;margin-bottom:12px;color:#fff}
.hero b{display:block;font-size:13px;opacity:.85;font-weight:600}
.hero .big{font-size:30px;font-weight:800;letter-spacing:-0.03em;line-height:1.2}
.hero .sm{font-size:13px;opacity:.9;margin-top:4px}
label.l{display:block;font-size:13px;color:var(--sub);font-weight:600;margin:12px 0 6px}
label.l:first-child{margin-top:0}
input[type=text],select{width:100%;height:48px;border:1px solid var(--line);border-radius:13px;padding:0 14px;font-size:16px;background:#fbfaf7;font-family:inherit;color:var(--ink)}
input[type=text]:focus,select:focus{outline:none;border-color:var(--ink);background:#fff}
.row{display:flex;gap:8px;align-items:center}
.row>input{flex:1}
.btn{display:inline-flex;align-items:center;justify-content:center;gap:6px;height:48px;padding:0 16px;border-radius:13px;border:1px solid var(--line);
  background:#fff;font-size:15px;font-weight:600;font-family:inherit;color:var(--ink);text-decoration:none;cursor:pointer;white-space:nowrap}
.btn.sm{height:38px;font-size:13px;padding:0 12px;border-radius:11px}
.btn.main{width:100%;margin-top:16px;border:none;color:#fff;font-size:16px;font-weight:700;height:54px;border-radius:15px}
.btn.ghost{border-style:dashed;color:var(--sub);width:100%;margin-top:8px}
.btn:disabled{opacity:.5}
.err{background:var(--bad-bg);color:var(--bad);border-radius:13px;padding:11px 13px;font-size:14px;margin-bottom:12px}
.hint{font-size:12.5px;color:var(--muted);margin:8px 2px 0}
.muted{color:var(--muted)}
.chips{display:flex;flex-wrap:wrap;gap:6px}
.chip{display:inline-flex;align-items:center;gap:4px;height:28px;padding:0 10px;border-radius:999px;background:#f2f0ea;color:var(--sub);font-size:12.5px;font-weight:600}
.toggle{display:flex;gap:6px;flex-wrap:wrap}
.toggle input{display:none}
.toggle label{height:36px;padding:0 13px;border-radius:999px;border:1px solid var(--line);display:inline-flex;align-items:center;font-size:13px;font-weight:600;color:var(--sub);background:#fff;cursor:pointer}
.toggle input:checked+label{background:var(--ink);color:#fff;border-color:var(--ink)}
.spin{width:18px;height:18px;border:2.5px solid rgba(255,255,255,.4);border-top-color:#fff;border-radius:50%;animation:sp .8s linear infinite}
@keyframes sp{to{transform:rotate(360deg)}}

/* 1. 동선 */
.t-route .btn.main{background:var(--route)} .t-route .hero{background:var(--route)}
.stop{display:flex;align-items:center;gap:8px;margin-bottom:8px}
.stop .n{width:28px;height:28px;flex:none;border-radius:50%;background:var(--route-bg);color:var(--route);font-weight:800;font-size:13px;display:flex;align-items:center;justify-content:center}
.stop .x{width:38px;height:48px;flex:none;border:none;background:none;color:var(--muted);font-size:20px;cursor:pointer}
.map .basemap{filter:grayscale(1) brightness(1.06) contrast(.85);opacity:.75}
.map .crimelayer{filter:saturate(2.2) contrast(1.35) drop-shadow(0 0 1px rgba(150,0,20,.45))}
.map{height:240px;border-radius:14px;overflow:hidden;background:#e9e7e0;border:1px solid var(--line)}
.tl{list-style:none;margin:0;padding:0}
.tl li{position:relative;display:flex;gap:12px;padding:0 0 14px 0}
.tl li:last-child{padding-bottom:0}
.tl .dot{width:30px;height:30px;flex:none;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:13px;font-weight:800;background:var(--route);color:#fff;z-index:1}
.tl .dot.se{background:var(--ink)}
.tl li:not(:last-child)::before{content:"";position:absolute;left:14px;top:30px;bottom:0;width:2px;background:var(--route-bg)}
.tl .body{flex:1;min-width:0}
.tl .nm{font-weight:700}
.tl .ad{font-size:12.5px;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.tl .leg{font-size:12.5px;color:var(--route);font-weight:600;margin-top:4px}
.tl .go{margin-left:auto;align-self:center}

/* 2. 집 */
.t-house .btn.main{background:var(--house)}
.rv{position:relative;height:200px;border-radius:var(--r);overflow:hidden;background:#dedbd2;margin-bottom:12px;display:flex;align-items:center;justify-content:center;color:var(--sub);font-size:13px;text-align:center}
.rv #roadview{position:absolute;inset:0}
.rv .tg{position:absolute;left:10px;bottom:10px;background:rgba(0,0,0,.6);color:#fff;font-size:12px;padding:2px 9px;border-radius:7px;z-index:2}
.hname{font-size:19px;font-weight:800;margin:0}
.haddr{font-size:13px;color:var(--sub);margin:2px 0 12px}
.sec{font-size:14px;font-weight:700;margin:4px 0 4px;display:flex;align-items:center;gap:6px}
.fact{padding:11px 0;border-top:1px solid #f0eee7}
.fact:first-of-type{border-top:none}
.fact .f{font-weight:700}
.fact .m{font-size:13.5px;color:var(--sub);margin-top:2px}
.checks{margin:6px 0 0;padding-left:20px;color:#3b3e3b;font-size:14px;line-height:1.8}
.safe .map{height:200px}
.legend{display:flex;align-items:center;gap:8px;font-size:12px;color:var(--muted);margin-top:8px}
.legend .bar2{flex:1;height:7px;border-radius:4px;background:linear-gradient(90deg,#ffffb2,#fed976,#feb24c,#fd8d3c,#f03b20,#bd0026)}
.cand{display:block;width:100%;text-align:left;background:#fff;border:1px solid var(--line);border-radius:13px;padding:12px 14px;margin-bottom:8px;font-family:inherit;font-size:15px;cursor:pointer}
.cand small{display:block;color:var(--muted);font-size:12.5px}

/* 3. 화장실 */
.t-toilet .btn.main{background:var(--toilet)}
.trow{display:flex;gap:12px;align-items:center;padding:13px 0;border-top:1px solid #f0eee7}
.trow:first-child{border-top:none;padding-top:2px}
.trow .d{width:58px;flex:none;text-align:center}
.trow .d b{display:block;font-size:17px;font-weight:800;color:var(--toilet);line-height:1.2}
.trow .d span{font-size:11.5px;color:var(--muted)}
.trow .body{flex:1;min-width:0}
.trow .nm{font-weight:700;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.trow .ad{font-size:12.5px;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.trow .chips{margin-top:5px}
.chip.ok{background:var(--toilet-bg);color:var(--toilet)}

/* 4. 약 */
.t-pill .btn.main{background:var(--pill)}
.shots{display:grid;grid-template-columns:1fr 1fr;gap:10px}
.shot{position:relative;aspect-ratio:1/1;border-radius:16px;border:1.5px dashed #d6cfe6;background:var(--pill-bg);display:flex;flex-direction:column;align-items:center;justify-content:center;gap:6px;color:var(--pill);font-weight:700;font-size:14px;overflow:hidden;cursor:pointer}
.shot input{display:none}
.shot img{position:absolute;inset:0;width:100%;height:100%;object-fit:cover}
.shot small{color:#8f7fb0;font-weight:500;font-size:12px}
.or{display:flex;align-items:center;gap:10px;color:var(--muted);font-size:12.5px;margin:18px 0 6px}
.or::before,.or::after{content:"";flex:1;height:1px;background:var(--line)}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:8px}
.pc{display:flex;gap:12px;padding:12px 0;border-top:1px solid #f0eee7}
.pc:first-child{border-top:none}
.pc img{width:76px;height:42px;object-fit:contain;border-radius:8px;background:#f6f4ef;flex:none}
.pc .nm{font-weight:700;line-height:1.35}
.pc .co{font-size:12.5px;color:var(--muted)}
.conf{font-size:11.5px;font-weight:700;padding:2px 8px;border-radius:999px;margin-left:4px;vertical-align:1px}
.conf.high{background:var(--toilet-bg);color:var(--toilet)} .conf.mid{background:var(--route-bg);color:var(--route)} .conf.low{background:#f2f0ea;color:var(--sub)}
.chip.sig{background:var(--warn-bg);color:var(--warn)}
.gh{font-size:13px;color:var(--sub);margin:2px 0 6px}

/* 주소 자동완성 */
.ac{position:relative;flex:1;min-width:0}
.ac input{width:100%}
.ac input.picked{border-color:var(--route);background:#fff}
.acl{position:absolute;left:0;right:0;top:52px;background:#fff;border:1px solid var(--line);border-radius:14px;
  box-shadow:0 10px 28px rgba(0,0,0,.12);z-index:50;max-height:280px;overflow:auto;display:none}
.acl.on{display:block}
.acl button{display:block;width:100%;text-align:left;padding:10px 14px;border:0;border-top:1px solid #f0eee7;background:none;font:inherit;font-size:15px;color:var(--ink);cursor:pointer}
.acl button:first-child{border-top:0}
.acl button:active,.acl button:hover{background:#f6f4ef}
.acl small{display:block;color:var(--muted);font-size:12px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.acl small.j{color:#b4b6b1;font-size:11.5px}
.acl .rh{display:flex;align-items:center;justify-content:space-between;padding:8px 14px 4px;font-size:12px;font-weight:700;color:var(--muted)}
.acl .rh .rc{width:auto;padding:2px 4px;border:0;background:none;font-size:12px;color:var(--muted);text-decoration:underline;cursor:pointer}
.acl .rh+button{border-top:0}
.acl .none{padding:12px 14px;color:var(--muted);font-size:13px}

.ctabs{display:flex;gap:5px;overflow-x:auto;margin:2px 0 10px;scrollbar-width:none}
.ctabs::-webkit-scrollbar{display:none}
.ctabs button{flex:none;border:1px solid var(--line);background:var(--card);color:var(--sub);border-radius:999px;padding:6px 9px;font:600 12.5px/1 inherit;font-family:inherit;cursor:pointer}
.ctabs button.on{background:var(--house);border-color:var(--house);color:#fff}
.ai{background:linear-gradient(135deg,#fff7ef,#fff);border:1px solid #f3d9c2}
.ai .sec{display:flex;align-items:center;gap:6px}
.ai .sec i{font-style:normal;font-size:11px;font-weight:700;color:#fff;background:#e0782f;border-radius:6px;padding:2px 6px}
.ai ul{margin:6px 0 0;padding-left:18px;font-size:14.5px;line-height:1.6}
.ai .sk{height:14px;border-radius:6px;background:linear-gradient(90deg,#f1ece4,#faf7f2,#f1ece4);background-size:200% 100%;animation:sk 1.2s infinite;margin:8px 0}
@keyframes sk{to{background-position:-200% 0}}
@media print{.ci{position:static}
  body{background:#fff}
  .bar a.back,.bar .tag,.btn,.ctabs,.swap{display:none!important}
  .card{break-inside:avoid;border-color:#ddd}
  .cols{display:block!important}
  .wt{break-inside:avoid}}

.swap{display:flex;align-items:center;gap:4px;margin:-2px auto 6px;border:1px dashed var(--line);background:transparent;color:var(--muted);border-radius:999px;padding:3px 10px;font:600 12px/1.4 inherit;font-family:inherit;cursor:pointer}
.swap:hover{color:var(--route);border-color:var(--route)}
.swap.in{display:inline-flex;margin:0 0 0 8px;vertical-align:middle;padding:2px 8px}
.swap:disabled{opacity:.5}
.hero.mine{background:#4b5563!important}
.hero .back2{margin-top:10px;background:#fff;color:#1b1d1c;border:0}

.tl .dot{cursor:pointer;transition:transform .15s}
.tl .dot:hover{transform:scale(1.1)}
.tl li.on .nm{color:var(--route)}
.tl li.on .dot{box-shadow:0 0 0 4px var(--route-bg)}
.mini{margin-top:10px}
.mini .mh{display:flex;align-items:center;gap:8px;margin:0 4px 6px;font-size:14px}
.mini .mh b{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.mini .mh a{font-size:12.5px;color:var(--route);font-weight:600;text-decoration:none;flex:none}
.minirv{position:relative;height:180px;border-radius:12px;overflow:hidden;background:#dedbd2}
.minirv .mrmsg{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;color:var(--sub);font-size:13px;z-index:3;background:#dedbd2}

.mini .allv{flex:none;border:1px solid var(--line);background:var(--card);border-radius:999px;padding:4px 10px;font:600 12.5px/1.2 inherit;font-family:inherit;color:var(--sub);cursor:pointer}
.mini .allv:hover{color:var(--ink)}

/* 화장실 작은 로드뷰: 안전로드 검색결과와 같은 크기 */
.sr-rv{position:relative;flex-shrink:0;width:84px;height:62px;border-radius:10px;overflow:hidden;background:#eef1f5}
.sr-rv-pano{position:absolute;left:0;top:0;width:336px;height:248px;transform:scale(.25);transform-origin:0 0}
.sr-rv-msg{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;text-align:center;padding:4px;font-size:10px;line-height:1.3;color:#94a3b8;z-index:2}
.sr-rv-cover{position:absolute;inset:0;z-index:3}
.trow .dl{font-size:12.5px;color:var(--sub);margin-top:3px}
.trow .dl{display:flex;align-items:center;gap:6px;flex-wrap:nowrap;white-space:nowrap;font-size:12.5px}
.trow .dl b{color:var(--toilet);font-weight:800}
.trow .tm{display:inline-flex;align-items:center;gap:2px;font-weight:600;color:var(--sub)}
.trow .tm svg{width:14px;height:14px;color:var(--muted);flex:none}
.trow .btn.sm{padding:0 9px;flex:none;font-size:12.5px}
.trow{gap:10px}

/* 집 미리보기: 건축물대장 값 표 */
.spec{display:grid;grid-template-columns:72px 1fr;gap:0;margin:6px 0 0;font-size:14.5px}
.spec dt,.spec dd{margin:0;padding:9px 0;border-top:1px solid #f0eee7}
.spec dt:first-of-type,.spec dt:first-of-type+dd{border-top:none}
.spec dt{color:var(--muted);font-weight:600;font-size:13.5px}
.spec dd{font-weight:600}
.spec dd.muted{color:var(--muted);font-weight:500}
.fact.warnf .f::before{content:"!";display:inline-flex;align-items:center;justify-content:center;width:18px;height:18px;margin-right:6px;border-radius:50%;background:var(--house-bg);color:var(--house);font-size:12px;font-weight:800;vertical-align:1px}

/* 조심할 점: 메인화면처럼 2x2 카드 */
.warns{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-top:4px}
.wt{background:#fffaf5;border:1px solid #f6e3d2;border-radius:16px;padding:13px 13px 12px}
.wt .wi{width:36px;height:36px;border-radius:11px;background:var(--house-bg);color:var(--house);display:flex;align-items:center;justify-content:center}
.wt .wi svg{width:21px;height:21px}
.wt .t{font-size:15px;font-weight:700;margin:10px 0 2px;line-height:1.3}
.wt .d{font-size:12.5px;color:var(--sub);line-height:1.45;word-break:keep-all}

/* 집 미리보기 첫 화면 */
.intro{margin:6px 4px 16px}
.intro h2{font-size:23px;line-height:1.35;margin:0;font-weight:800;letter-spacing:-0.02em}
.intro p{margin:6px 0 0;font-size:14px;color:var(--sub)}
.gives{display:grid;grid-template-columns:1fr 1fr;gap:10px}
.gv{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:14px 13px}
.gv .wi{width:36px;height:36px;border-radius:11px;background:var(--house-bg);color:var(--house);display:flex;align-items:center;justify-content:center}
.gv .wi svg{width:20px;height:20px}
.gv .t{font-size:15px;font-weight:700;margin:10px 0 2px}
.gv .d{font-size:12.5px;color:var(--sub);line-height:1.45}

/* 집 미리보기 첫 화면: 알려주는 것 한 줄씩 */
.gives1{padding:6px 16px}
.g1{display:flex;align-items:center;gap:10px;padding:10px 0;border-top:1px solid #f0eee7;font-size:14px}
.g1:first-child{border-top:none}
.g1 .wi{flex:none;width:30px;height:30px;border-radius:9px;background:var(--house-bg);color:var(--house);display:flex;align-items:center;justify-content:center}
.g1 .wi svg{width:17px;height:17px}
.g1 b{flex:none;width:68px;font-weight:700}
.g1 span:last-child{flex:1;min-width:0;color:var(--sub);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}

/* 화장실: 내 위치 + 길안내 선택 */
.here{display:flex;align-items:center;gap:10px;background:var(--card);border:1px solid var(--line);border-radius:14px;padding:11px 14px;margin-bottom:12px}
.here .pin{flex:none;width:10px;height:10px;border-radius:50%;background:var(--toilet);box-shadow:0 0 0 5px var(--toilet-bg)}
.here small{display:block;font-size:11.5px;color:var(--muted);font-weight:600}
.here b{font-size:14.5px;font-weight:700}
.nav{display:none;position:fixed;inset:0;z-index:50;background:rgba(15,20,18,.45);align-items:flex-end;justify-content:center}
.nav.on{display:flex}
.nav .sheet{width:100%;max-width:480px;background:var(--card);border-radius:22px 22px 0 0;padding:18px 16px calc(18px + env(safe-area-inset-bottom))}
.nav .sh{display:flex;align-items:center;gap:8px;margin-bottom:6px}
.nav .sh b{flex:1;font-size:16px}
.nav .sh button{width:32px;height:32px;border:none;border-radius:50%;background:#f0eee7;font-size:18px;cursor:pointer}
.navb{display:flex;align-items:center;gap:12px;height:52px;padding:0 14px;margin-top:8px;border:1px solid var(--line);border-radius:14px;color:var(--ink);font-weight:700;text-decoration:none}
.navb span{width:28px;height:28px;border-radius:8px;display:flex;align-items:center;justify-content:center;font-weight:800;font-size:14px}
@media (min-width:960px){.nav{align-items:center}.nav .sheet{border-radius:22px}}

.gpsat{display:flex;align-items:center;gap:8px;margin:8px 2px 0;font-size:13.5px;color:var(--sub);font-weight:600}
.gpsat .pin{flex:none;width:8px;height:8px;border-radius:50%;background:var(--route);box-shadow:0 0 0 4px var(--route-bg)}

.sr-rv{cursor:pointer}
.big{display:none;position:fixed;inset:0;z-index:49;background:rgba(15,20,18,.55);align-items:center;justify-content:center;padding:12px}
.big.on{display:flex}
.big .bbox{width:100%;max-width:720px;background:var(--card);border-radius:22px;padding:16px}
.big .sh{display:flex;align-items:center;gap:8px;margin-bottom:10px}
.big .sh b{display:block;font-size:16px}
.big .sh small{display:block;font-size:12.5px;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.big .sh button{flex:none;width:32px;height:32px;border:none;border-radius:50%;background:#f0eee7;font-size:18px;cursor:pointer}
.bigrv{position:relative;height:min(62vh,520px);border-radius:14px;overflow:hidden;background:#dedbd2}
.bigrv .mrmsg{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;color:var(--sub);font-size:13px;z-index:3;background:#dedbd2}
.t-toilet .big .btn.main{background:var(--toilet)}

/* 페이지 맨 아래 출처 */
.src{margin:22px 4px 0;padding-top:12px;border-top:1px solid var(--line);font-size:11.5px;color:var(--muted);line-height:1.7}
.src b{display:block;font-weight:700;color:var(--sub);margin-bottom:2px}
.src span{display:block}
.src em{font-style:normal;display:inline-block;min-width:92px;color:var(--sub)}
.here b{display:block;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.here>div{min-width:0;flex:1}
.gpsat{min-width:0}
.gpsat .at{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}

/* 순서 고정: 칸 안 칩 + 자물쇠, 누르면 반투명 플로팅 바 */
.stop{position:relative}
.pinac input{padding-right:42px}
.stop.pinned .pinac input{padding-left:76px}
.pchip{position:absolute;left:10px;top:50%;transform:translateY(-50%);z-index:2;display:none;height:24px;padding:0 9px;border-radius:999px;background:var(--route);color:#fff;font-size:12px;font-weight:700;align-items:center;pointer-events:none;white-space:nowrap}
.stop.pinned .pchip{display:inline-flex}
.lockb{position:absolute;right:6px;top:50%;transform:translateY(-50%);z-index:2;width:34px;height:34px;border:0;border-radius:10px;background:none;color:#b3b5b0;cursor:pointer;display:flex;align-items:center;justify-content:center}
.lockb i{display:flex}.lockb svg{width:19px;height:19px}
.lockb .on{display:none}
.stop.pinned .lockb{color:var(--route)}
.stop.pinned .lockb .on{display:flex}.stop.pinned .lockb .off{display:none}
.lockb:disabled{opacity:.35;cursor:default}
.stop.open{z-index:20}
.stop .x{width:30px}
.pinbar{position:absolute;left:36px;right:30px;top:calc(100% + 4px);z-index:30;display:flex;justify-content:space-around;gap:4px;padding:12px 8px 10px;
  background:rgba(255,255,255,.92);-webkit-backdrop-filter:blur(8px);backdrop-filter:blur(8px);border-radius:16px;box-shadow:0 4px 20px rgba(0,0,0,.18)}
.pinbar button{display:flex;flex-direction:column;align-items:center;gap:5px;border:0;background:none;padding:0;cursor:pointer;font-family:inherit;min-width:0;flex:1;animation:pbIn .18s ease both}
.pinbar button:nth-child(2){animation-delay:.03s}.pinbar button:nth-child(3){animation-delay:.06s}.pinbar button:nth-child(4){animation-delay:.09s}
.pinbar button:nth-child(5){animation-delay:.12s}.pinbar button:nth-child(6){animation-delay:.15s}.pinbar button:nth-child(7){animation-delay:.18s}
@keyframes pbIn{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:none}}
.pinbar b{width:40px;height:40px;border-radius:50%;background:linear-gradient(135deg,#3b82f6,#2563eb);box-shadow:0 4px 12px rgba(37,99,235,.35);color:#fff;font-size:15px;font-weight:800;display:flex;align-items:center;justify-content:center;transition:transform .15s}
.pinbar button:active b{transform:scale(.92)}
.pinbar b.on{outline:3px solid #bfd3fb;outline-offset:2px}
.pinbar span{font-size:11.5px;font-weight:700;color:#1e293b;white-space:nowrap;max-width:56px;overflow:hidden;text-overflow:ellipsis}
.pinbar button:disabled{cursor:default}
.pinbar button:disabled b{background:#e5e7eb;box-shadow:none;color:#9ca3af}
.pinbar button:disabled span{color:#a3a6a1;font-weight:500}
.pinbar.many{left:0;right:0;padding:10px 4px 8px}
.pinbar.many b{width:34px;height:34px;font-size:13.5px}
.pinbar.many span{font-size:10.5px;max-width:44px}
.pinbar .free b{background:linear-gradient(135deg,#94a3b8,#64748b);box-shadow:0 4px 12px rgba(0,0,0,.18)}
.ptoast{display:none;margin-top:10px;padding:9px 12px;border-radius:10px;background:#1b1d1c;color:#fff;font-size:13px}
.ptoast.on{display:block}
.pint{display:inline-flex;align-items:center;gap:2px;margin-left:6px;padding:2px 8px;border-radius:999px;background:var(--route);color:#fff;font-size:11.5px;font-weight:700;vertical-align:2px}
.pint svg{width:12px;height:12px}
.tl .cum{font-size:12px;color:var(--muted);margin-top:2px}
.mini .mh{margin:0 4px 8px}
.macts{display:flex;gap:6px;margin:0 0 8px}
.macts .ma{flex:1;display:flex;align-items:center;justify-content:center;height:38px;border:1px solid var(--line);border-radius:12px;background:var(--card);color:var(--ink);font-family:inherit;font-size:13.5px;font-weight:700;line-height:1;padding:0;text-decoration:none;cursor:pointer;white-space:nowrap}
.macts .ma:active{transform:scale(.96)}
.macts .ma[style*="none"]{display:none!important}

/* 도착: 두 칸 세그먼트 */
.seg{display:flex;background:#f0eee7;border-radius:12px;padding:3px;gap:3px}
.seg input{display:none}
.seg label{flex:1;height:38px;display:flex;align-items:center;justify-content:center;border-radius:10px;font-size:13.5px;font-weight:600;color:var(--sub);cursor:pointer;transition:background .15s,color .15s}
.seg input:checked+label{background:#fff;color:var(--route);font-weight:700;box-shadow:0 1px 4px rgba(0,0,0,.08)}

.leaflet-tooltip.mlab{background:#fff;border:0;border-radius:8px;padding:2px 7px;font:700 11.5px/1.35 Pretendard,"Noto Sans CJK KR",sans-serif;color:#1b1d1c;box-shadow:0 1px 5px rgba(0,0,0,.22);white-space:nowrap}
.leaflet-tooltip.mlab:before{display:none}
.leaflet-tooltip.mlab.se{color:#fff;background:#1b1d1c}

/* ---------- PC 화면: 넓게, 입력은 왼쪽·결과는 오른쪽 ---------- */
.ph{display:none}
@media (min-width:960px){

  /* PC 글자·요소 크게 (폰 대비 약 1.2배) */
  html,body{font-size:18.0px}
  .bar h1{font-size:22.8px}
  .bar .tag{font-size:14.4px}
  .hello .date{font-size:15.6px}
  .hello h1{font-size:31.2px}
  .tile .t{font-size:20.4px}
  .tile .d{font-size:15.0px}
  .tile .no{font-size:14.4px}
  .note{font-size:14.4px}
  .hero b{font-size:15.6px}
  .hero .big{font-size:36.0px}
  .hero .sm{font-size:15.6px}
  label.l{font-size:15.6px}
  input[type=text],select{font-size:19.2px}
  .btn{font-size:18.0px}
  .btn.sm{font-size:15.6px}
  .btn.main{font-size:19.2px}
  .err{font-size:16.8px}
  .hint{font-size:15.0px}
  .chip{font-size:15.0px}
  .toggle label{font-size:15.6px}
  .stop .n{font-size:15.6px}
  .stop .x{font-size:24.0px}
  .tl .dot{font-size:15.6px}
  .tl .ad{font-size:15.0px}
  .tl .leg{font-size:15.0px}
  .rv{font-size:15.6px}
  .rv .tg{font-size:14.4px}
  .hname{font-size:22.8px}
  .haddr{font-size:15.6px}
  .sec{font-size:16.8px}
  .fact .m{font-size:16.2px}
  .checks{font-size:16.8px}
  .legend{font-size:14.4px}
  .cand{font-size:18.0px}
  .cand small{font-size:15.0px}
  .trow .d b{font-size:20.4px}
  .trow .d span{font-size:13.8px}
  .trow .ad{font-size:15.0px}
  .shot{font-size:16.8px}
  .shot small{font-size:14.4px}
  .or{font-size:15.0px}
  .pc .co{font-size:15.0px}
  .conf{font-size:13.8px}
  .gh{font-size:15.6px}
  .acl button{font-size:18.0px}
  .acl small{font-size:14.4px}
  .acl small.j{font-size:13.8px}
  .acl .none{font-size:15.6px}
  .ai .sec i{font-size:13.2px}
  .ai ul{font-size:17.4px}
  .mini .mh{font-size:16.8px}
  .mini .mh a{font-size:15.0px}
  .minirv .mrmsg{font-size:15.6px}
  .wrap{max-width:1320px}
  .bar h1{font-size:26px}
  .hello h1{font-size:40px}
  .tile .t{font-size:21px} .tile .d{font-size:15px}
  input[type=text],select{height:58px;padding:0 18px;font-size:19px}
  .btn{height:56px;padding:0 20px}
  .btn.sm{height:44px;padding:0 14px}
  .btn.main{height:62px;font-size:19px}
  .tl li:not(:last-child)::before{left:17px;top:36px}
  .tl li{padding-bottom:18px}
  .bar a.back{width:46px;height:46px}
  .stop .n{width:34px;height:34px}
  .tl .dot{width:36px;height:36px;min-width:36px}
  .hero{padding:22px}
  .hero .big{font-size:40px}
  .cols{grid-template-columns:480px 1fr;gap:24px}
  .card{padding:24px;border-radius:22px}
  .sec{margin-bottom:10px}
  .wrap{padding:28px 32px 60px}
  .ci{top:22px;right:32px;height:64px;max-width:none}
  .bar{padding-right:260px}
  .tiles{grid-template-columns:repeat(4,1fr);gap:16px}
  .tile{min-height:220px;padding:22px}
  .cols{display:grid;align-items:start}
  .colA{position:sticky;top:16px}
  .t-house .cols{grid-template-columns:1fr 1fr}
  .t-house .colA{position:static}
  .rv{height:340px}
  .map{height:420px}
  #map{height:480px}
  .card{padding:20px}
  .ph p{margin:0}
  .ph{display:flex;align-items:center;justify-content:center;text-align:center;min-height:420px;border:2px dashed var(--line);border-radius:var(--r);color:var(--muted);font-size:15px;line-height:1.7}
  .t-house form.card,.t-house .wrap>.card{max-width:640px;margin-left:auto;margin-right:auto}
  .note{max-width:none}
  .mbr{display:none}
  .minirv{height:260px!important}
  .src{font-size:13px}
  .src em{min-width:120px}
  .src span{display:inline;margin-right:18px}
  .src b{display:inline;margin-right:14px}
  .intro p{font-size:16px}
  .g1{font-size:16px}
  .g1 b{width:84px}
  .intro,.t-house .gives1,.t-house .wrap>.sec,.t-house .wrap>.hint{max-width:640px;margin-left:auto!important;margin-right:auto!important}
  .intro h2{font-size:30px}
  .gv .t{font-size:17px}
  .gv .d{font-size:14px}
  .wt .t{font-size:17px}
  .wt .d{font-size:14px}
  .wt .wi{width:42px;height:42px}
  .spec{grid-template-columns:96px 1fr;font-size:17px}
  .spec dt{font-size:15.5px}
  .sr-rv{width:120px;height:88px}
  .sr-rv-pano{width:480px;height:352px}
}

/* 큰 로드뷰 속 화장실 핀 */
.rvpin{display:flex;flex-direction:column;align-items:center;pointer-events:none;filter:drop-shadow(0 2px 4px rgba(0,0,0,.45))}
.rvpin b{background:#e11d48;color:#fff;font-size:14px;font-weight:800;padding:6px 11px;border-radius:999px;white-space:nowrap;border:2px solid #fff}
.rvpin i{width:0;height:0;border-left:9px solid transparent;border-right:9px solid transparent;border-top:13px solid #e11d48;margin-top:-1px;animation:rvbob 1.1s ease-in-out infinite}
@keyframes rvbob{50%{transform:translateY(5px)}}
.rvpin.sm{filter:none}
.rvpin.sm i{border-left-width:19px;border-right-width:19px;border-top-width:30px;border-top-color:#ff1f4b;
  filter:drop-shadow(0 0 1.5px #fff) drop-shadow(0 0 1.5px #fff) drop-shadow(0 0 1.5px #fff) drop-shadow(0 2px 4px rgba(0,0,0,.7));
  animation:rvbob .9s ease-in-out infinite}
.chip.upd{background:transparent;border:1px solid var(--line);color:var(--muted);font-weight:500}
.chip.upd.old{border-color:#f3c98b;color:#b45309;background:#fff7ed}
'''

TRIP_TEMPLATES = {
    "trip/_ac.html": r'''<script>
// 주소 자동완성 (동선·집 미리보기 공용)
var _acEsc=(t=>String(t??"").replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c])));
// 주소 자동완성: 안전로드 경로찾기와 같은 화면·속도 (3글자부터, 0.4초 뒤, 5개까지). 실제 주소가 먼저 뜨도록 출장 도구함 전용 검색 사용
// 최근 검색: 서버에 보내지 않고 이 기기 브라우저에만 5개까지 (동선·집 미리보기 공용)
const _RK="trip_recent_v1";
function recentGet(){try{return JSON.parse(localStorage.getItem(_RK)||"[]").slice(0,5)}catch(e){return []}}
function recentAdd(pl){try{const key=pl.road_address_name||pl.address_name||pl.place_name;
  const list=recentGet().filter(x=>(x.road_address_name||x.address_name||x.place_name)!==key);
  list.unshift({place_name:pl.place_name||"",road_address_name:pl.road_address_name||"",address_name:pl.address_name||"",x:pl.x,y:pl.y});
  localStorage.setItem(_RK,JSON.stringify(list.slice(0,5)));}catch(e){}}
function recentClear(){try{localStorage.removeItem(_RK)}catch(e){}}
function debounce(fn,ms){let t;return function(...a){clearTimeout(t);t=setTimeout(()=>fn.apply(this,a),ms);};}
function attachSuggest(inp,onPick,onClear){
  const box=document.createElement("div");box.className="acl";inp.parentElement.appendChild(box);
  const close=()=>{box.classList.remove("on");box.innerHTML="";};
  inp.addEventListener("input",()=>{if(onClear)onClear();});
  function pick(pl){inp.value=shortAddr(pl.place_name||pl.road_address_name||pl.address_name||"");close();recentAdd(pl);if(onPick)onPick(pl);}
  function showRecent(){
    if(inp.value.trim())return;
    const list=recentGet();if(!list.length){close();return;}
    box.innerHTML='<div class="rh"><span>최근 검색</span><button type="button" class="rc">지우기</button></div>'+list.map((pl,i)=>{
      const road=pl.road_address_name||"",jibun=pl.address_name||"";
      const title=pl.place_name||road||jibun,sub=(road&&road!==title)?road:((jibun&&jibun!==title)?jibun:"");
      return `<button type="button" data-r="${i}">${_acEsc(shortAddr(title))}${sub?`<small>${_acEsc(shortAddr(sub))}</small>`:""}</button>`;}).join("");
    box.querySelector(".rc").onmousedown=e=>{e.preventDefault();recentClear();close();};
    box.querySelectorAll("button[data-r]").forEach(b=>b.onmousedown=e=>{e.preventDefault();pick(list[+b.dataset.r]);});
    box.classList.add("on");
  }
  inp.addEventListener("focus",showRecent);
  inp.addEventListener("click",showRecent);
  inp.addEventListener("input",()=>{if(!inp.value.trim())showRecent();});
  inp.addEventListener("input",debounce(async function(){
    const q=inp.value.trim();
    if(q.length<3||q==="현재 위치"){close();return;}
    try{
      const data=await (await fetch("{{ url_for('trip.api_suggest') }}?q="+encodeURIComponent(q))).json();
      if(document.activeElement!==inp)return;   // 다른 곳을 눌렀으면 늦게 온 결과는 띄우지 않음
      const docs=(data.documents||[]).slice(0,5);
      if(inp.value.trim()!==q)return;
      if(!docs.length){box.innerHTML='<div class="none">검색 결과가 없습니다.</div>';box.classList.add("on");return;}
      box.innerHTML=docs.map((pl,i)=>{
        const road=pl.road_address_name||"",jibun=pl.address_name||"";
        const title=pl.place_name||road||jibun;
        const r2=(road&&road!==title)?`<small>${_acEsc(shortAddr(road))}</small>`:"",j2=(jibun&&jibun!==title)?`<small class="j">${_acEsc(shortAddr(jibun))}</small>`:"";
        return `<button type="button" data-i="${i}">${_acEsc(shortAddr(title))}${r2}${j2}</button>`;
      }).join("");
      box.querySelectorAll("button").forEach(b=>b.onmousedown=e=>{e.preventDefault();pick(docs[+b.dataset.i]);});
      box.classList.add("on");
    }catch(err){close();}
  },400));
  document.addEventListener("click",e=>{if(e.target!==inp&&!box.contains(e.target))close();});
}
</script>
''',
    "trip/_m.html": r'''{% macro icon(name) -%}
{%- if name == 'route' -%}
<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="6" cy="19" r="2.2"/><circle cx="18" cy="5" r="2.2"/><path d="M8.2 19H15a3.5 3.5 0 0 0 0-7H9a3.5 3.5 0 0 1 0-7h6.8"/></svg>
{%- elif name == 'house' -%}
<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 10.5 12 3l9 7.5"/><path d="M5 9v11h14V9"/><path d="M10 20v-5.5h4V20"/></svg>
{%- elif name == 'toilet' -%}
<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="7" cy="4.5" r="1.8"/><circle cx="17" cy="4.5" r="1.8"/><path d="M5 9h4l.6 6H8.5v5.5h-3V15H4.4z"/><path d="M15 9h4l2 7h-2.5v4.5h-3V16H13z"/><path d="M12 7v14"/></svg>
{%- elif name == 'pill' -%}
<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="2.8" y="8.2" width="18.4" height="7.6" rx="3.8" transform="rotate(-40 12 12)"/><path d="m9.2 8.6 5.6 6.8"/></svg>
{%- elif name == 'board' -%}
<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 5h16v11H9l-5 4z"/><path d="M8 9h8M8 12.5h5"/></svg>
{%- elif name == 'cards' -%}
<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="7" width="13" height="14" rx="2"/><path d="M8 3h11a2 2 0 0 1 2 2v12"/></svg>
{%- elif name == 'back' -%}
<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M15 5l-7 7 7 7"/></svg>
{%- endif -%}
{%- endmacro %}
{% macro topbar(title) -%}
<div class="bar"><a class="back" href="{{ url_for('trip.home') }}" aria-label="홈으로">{{ icon('back') }}</a><h1>{{ title }}</h1>{% if demo %}<span class="tag">예시 모드</span>{% endif %}</div>
{%- endmacro %}

{% macro wicon(name) -%}
<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
{%- if name == 'clock' -%}<circle cx="12" cy="12" r="8.5"/><path d="M12 7.5V12l3 2"/>
{%- elif name == 'fire' -%}<path d="M12 3c1 3.5 5 5.5 5 10a5 5 0 0 1-10 0c0-2.5 1.5-3.8 2.5-5 .3 1.6 1 2.5 2 3 0-3 .2-5.5.5-8z"/>
{%- elif name == 'brick' -%}<rect x="3" y="5" width="18" height="14" rx="1.5"/><path d="M3 9.7h18M3 14.3h18M9 5v4.7M15 9.7v4.6M9 14.3V19"/>
{%- elif name == 'roof' -%}<path d="M2.5 12 12 4.5 21.5 12"/><path d="M5 10.5V20h14v-9.5"/><path d="M8 14h8"/>
{%- elif name == 'store' -%}<path d="M4 9.5 5.5 4h13L20 9.5"/><path d="M4 9.5a2.7 2.7 0 0 0 5.3 0 2.7 2.7 0 0 0 5.4 0 2.7 2.7 0 0 0 5.3 0"/><path d="M5.5 11.5V20h13v-8.5"/><path d="M10 20v-4.5h4V20"/>
{%- elif name == 'drop' -%}<path d="M12 3.5s6 6.4 6 10.5a6 6 0 0 1-12 0c0-4.1 6-10.5 6-10.5z"/>
{%- elif name == 'stairs' -%}<path d="M3 20h5v-5h5v-5h5V5h3"/>
{%- elif name == 'lift' -%}<rect x="5" y="3" width="14" height="18" rx="2"/><path d="m9.5 9 2.5-2.5L14.5 9M9.5 15l2.5 2.5 2.5-2.5"/>
{%- elif name == 'sun' -%}<circle cx="12" cy="12" r="4"/><path d="M12 2.5v2M12 19.5v2M2.5 12h2M19.5 12h2M5.3 5.3l1.4 1.4M17.3 17.3l1.4 1.4M5.3 18.7l1.4-1.4M17.3 6.7l1.4-1.4"/>
{%- elif name == 'hill' -%}<path d="M2 19 9 8l4 6 2.5-3.5L22 19z"/>
{%- else -%}<path d="M12 4 2.5 20h19z"/><path d="M12 10v4.5M12 17.3v.2"/>
{%- endif -%}
</svg>
{%- endmacro %}

{% macro src(items) -%}
<div class="src"><b>출처</b>{% for k, v in items %}<span><em>{{ k }}</em>{{ v }}</span>{% endfor %}</div>
{%- endmacro %}
''',
    "trip/_pill_cn.html": r'''{% raw %}
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
.pill-mode{ width:auto !important; height:28px !important; min-width:0 !important; margin:0 !important; padding:0 10px !important; border:1px solid #e2d4f6 !important; border-radius:999px !important; background:#f1eafb !important; color:#7440c2 !important; font-size:12px !important; font-weight:700 !important; white-space:nowrap; box-shadow:none !important; cursor:pointer; }
.pill-feat.pill-manual{ display:none; margin-top:0; }
.pill-manual .pill-go{ margin-top:10px !important; }
.pill-shots{ display:grid; grid-template-columns:1fr 1fr; gap:10px; }
.pill-shot{ position:relative; display:flex; flex-direction:column; align-items:center; justify-content:center; height:120px; padding:6px 8px 34px; box-sizing:border-box; border:1.5px dashed #c9b0ee; border-radius:12px; background:#faf7fe; color:#7440c2; font-size:13px; font-weight:700; cursor:pointer; overflow:hidden; text-align:center; }
.pill-shot input{ display:none; }
.pill-shot img{ position:absolute; inset:0; width:100%; height:100%; object-fit:cover; }
.pill-shot small{ font-size:11px; font-weight:500; color:#6b7280; margin-top:3px; padding:0 6px; word-break:keep-all; }
.pill-shot.drag{ background:#f4eefc; border-color:#8b55d6; border-style:solid; }
.pill-gal{ position:absolute; right:5px; bottom:5px; z-index:2; width:30px !important; height:30px !important; min-width:0 !important; margin:0 !important; padding:0 !important; border:1px solid #e2d4f6 !important; border-radius:8px !important; background:rgba(255,255,255,0.95) !important; color:#7440c2 !important; display:flex; align-items:center; justify-content:center; box-shadow:0 1px 4px rgba(15,23,42,0.15) !important; cursor:pointer; }
.pill-gal svg{ width:18px; height:18px; display:block; }
.pill-tip{ display:flex; gap:4px; margin:10px 0 0; font-size:12px; color:#6b7280; line-height:1.5; word-break:keep-all; overflow-wrap:break-word; }
.pill-tip span:first-child{ flex:none; }  /* ※ 뒤로 줄바꿈된 글이 윗줄 첫 글자에 맞춰짐 */
.pill-go{ display:block; width:100% !important; height:44px !important; margin:12px 0 0 !important; padding:0 !important; border:none !important; border-radius:10px !important; background:#8b55d6 !important; color:#fff !important; font-size:15px !important; font-weight:800 !important; box-shadow:none !important; cursor:pointer; }
.pill-go:disabled{ background:#c9b0ee !important; cursor:wait; }
.pill-msg{ display:none; margin-top:12px; padding:10px 12px; border-radius:10px; background:#fff7ed; border:1px solid #fdba74; color:#9a3412; font-size:13px; line-height:1.55; word-break:keep-all; }
.pill-feat{ display:none; margin-top:14px; padding:10px 12px; border-radius:12px; background:#f1eafb; border:1px solid #e2d4f6; }
.pill-feat-title{ font-size:12.5px; font-weight:800; color:#4b2585; }
.pill-feat-help{ margin:3px 0 8px; font-size:11.5px; color:#4b5563; line-height:1.45; word-break:keep-all; }
.pill-feat-row{ display:grid; grid-template-columns:1fr 1fr 1fr; gap:6px; }
.pill-feat-row input{ grid-column:1 / -1; }
/* 앞면·뒷면 글자 두 칸 */
.pill-imp2{ display:grid; grid-template-columns:1fr 1fr; gap:6px; margin-bottom:6px; }
.pill-imp2 label{ display:flex; flex-direction:column; gap:3px; min-width:0; font-size:11.5px; font-weight:700; color:#4b2585; }
.pill-imp2 input{ width:100%; height:38px; margin:0; padding:0 10px; border:1px solid #e2d4f6; border-radius:8px; font-size:14px; font-family:inherit; background:#fff; box-sizing:border-box; }
.pill-imp2 input:focus{ outline:none; border-color:#8b55d6; box-shadow:0 0 0 3px rgba(139,85,214,0.12); }
.pill-imp2 input.err, .pill-imp2 input.err:focus{ border-color:#ef4444; box-shadow:0 0 0 3px rgba(239,68,68,0.15); }
/* 상단 찾기 방식 탭 */
.pill-tabs{ flex-basis:100%; display:grid; grid-template-columns:1fr 1fr; gap:4px; margin-top:12px; padding:4px; background:#f1f5f9; border-radius:12px; }
.pill-tab{ display:flex !important; align-items:center; justify-content:center; gap:6px; width:auto !important; height:40px !important; margin:0 !important; padding:0 6px !important; border:none !important; border-radius:9px !important; background:transparent !important; color:#64748b !important; font-size:14px !important; font-weight:700 !important; font-family:inherit; box-shadow:none !important; cursor:pointer; white-space:nowrap; }
.pill-tab svg{ width:18px; height:18px; flex:none; }
.pill-tab.on{ background:#fff !important; color:#7440c2 !important; box-shadow:0 1px 4px rgba(15,23,42,0.12) !important; }
/* 모양 선택: 모양 그림이 보이는 선택창 (원래 select는 숨겨 두고 값만 사용) */
.ps-wrap{ position:relative; min-width:0; }
.ps-btn{ width:100% !important; height:36px !important; margin:0 !important; padding:0 8px !important; display:flex !important; align-items:center; gap:5px; border:1px solid #e2d4f6 !important; border-radius:8px !important; background:#fff !important; color:#111827 !important; font-size:13px !important; font-weight:400 !important; font-family:inherit; box-shadow:none !important; cursor:pointer; text-align:left; }
.ps-btn svg{ flex:none; width:22px; height:16px; }
.ps-btn .ps-name{ flex:1; min-width:0; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.ps-btn .ps-caret{ flex:none; color:#6b7280; font-size:10px; }
.ps-pop{ display:none; position:fixed; z-index:100005; width:252px; max-width:calc(100vw - 24px); padding:6px; background:#fff; border:1px solid #e2d4f6; border-radius:12px; box-shadow:0 10px 26px rgba(15,23,42,0.18); grid-template-columns:repeat(4, 1fr); gap:4px; }
.ps-pop.open{ display:grid; }
.ps-opt{ display:flex !important; flex-direction:column; align-items:center; justify-content:center; gap:3px; width:auto !important; height:auto !important; margin:0 !important; padding:6px 2px !important; border:1px solid transparent !important; border-radius:8px !important; background:#fff !important; color:#374151 !important; font-size:11px !important; font-weight:600 !important; font-family:inherit; box-shadow:none !important; cursor:pointer; white-space:nowrap; }
.ps-opt svg{ width:30px; height:22px; }
.ps-opt:hover{ background:#f7f2fd !important; }
.ps-opt.sel{ background:#f1eafb !important; border-color:#c9b0ee !important; color:#7440c2 !important; }
.pill-feat-row input, .pill-feat-row select{ width:100%; height:36px; margin:0; padding:0 8px; border:1px solid #e2d4f6; border-radius:8px; font-size:13px; font-family:inherit; background:#fff; box-sizing:border-box; }
.pill-re{ width:100% !important; height:34px !important; margin:8px 0 0 !important; padding:0 !important; border:1px solid #c9b0ee !important; border-radius:8px !important; background:#fff !important; color:#7440c2 !important; font-size:13px !important; font-weight:700 !important; box-shadow:none !important; cursor:pointer; }
.pill-list{ margin-top:12px; display:flex; flex-direction:column; gap:10px; }
.pill-group + .pill-group{ margin-top:18px; padding-top:14px; border-top:2px dashed #e5e7eb; }
.pill-group-title{ font-size:15px; font-weight:800; color:#111827; }
.pill-group .pill-feat{ display:block; }
.pill-card{ display:flex; gap:12px; padding:10px; border:1px solid #e5e7eb; border-radius:12px; }
.pill-card img{ flex:none; width:112px; height:62px; object-fit:contain; border-radius:6px; background:#f9fafb; cursor:zoom-in; }
/* 식약처 사진 크게 보기 */
.pill-zoom{ display:none; position:fixed; inset:0; z-index:100010; background:rgba(15,23,42,0.88); align-items:center; justify-content:center; flex-direction:column; padding:16px; box-sizing:border-box; cursor:zoom-out; }
.pill-zoom.show{ display:flex; }
.pill-zoom img{ max-width:100%; max-height:calc(100% - 60px); object-fit:contain; border-radius:10px; background:#fff; }
.pill-zoom-cap{ margin-top:10px; max-width:100%; color:#fff; font-size:14px; font-weight:700; text-align:center; word-break:keep-all; overflow-wrap:anywhere; }
.pill-zoom-x{ position:absolute; top:max(12px, env(safe-area-inset-top)); right:12px; width:40px !important; height:40px !important; min-width:0 !important; margin:0 !important; padding:0 !important; border:none !important; border-radius:999px !important; background:rgba(255,255,255,0.18) !important; color:#fff !important; font-size:22px !important; line-height:1 !important; box-shadow:none !important; cursor:pointer; }
.pill-info{ flex:1; min-width:0; }
.pill-name{ font-size:14px; font-weight:800; line-height:1.35; word-break:keep-all; overflow-wrap:anywhere; }
.pill-meta{ margin-top:3px; font-size:12px; color:#6b7280; line-height:1.45; word-break:keep-all; overflow-wrap:anywhere; }
.pill-conf{ display:inline-block; margin-right:4px; padding:1px 7px; border-radius:6px; font-size:11px; font-weight:800; vertical-align:1px; }
.pill-conf.high{ background:#dcfce7; color:#15803d; }
.pill-conf.mid{ background:#ece1fb; color:#7440c2; }
.pill-conf.low{ background:#f3f4f6; color:#6b7280; }
.pill-badge{ display:inline-block; margin-right:4px; padding:1px 7px; border-radius:6px; background:#ede9fe; color:#6d28d9; font-size:11px; font-weight:800; vertical-align:1px; }
.pill-actions{ display:flex; flex-wrap:wrap; gap:6px; margin-top:6px; }
.pill-link{ font-size:12px; font-weight:700; color:#8b55d6; text-decoration:none; }
.pill-kind{ display:inline-block; margin-right:4px; padding:0 6px; border-radius:5px; background:#fef3c7; color:#92400e; font-size:11px; font-weight:800; }
.pill-card.picked{ border-color:#8b55d6; box-shadow:0 0 0 2px rgba(139,85,214,0.18); }
.pill-pick{ width:auto !important; height:26px !important; margin:0 !important; padding:0 10px !important; border:1px solid #c9b0ee !important; border-radius:999px !important; background:#fff !important; color:#7440c2 !important; font-size:12px !important; font-weight:700 !important; box-shadow:none !important; cursor:pointer; }
.pill-card.picked .pill-pick{ background:#8b55d6 !important; border-color:#8b55d6 !important; color:#fff !important; }
.pill-pick-help{ margin:8px 0 2px; font-size:12px; color:#92400e; font-weight:700; word-break:keep-all; }
.pill-care{ margin-top:18px; padding:14px; border-radius:14px; background:#fffbeb; border:1px solid #fcd34d; }
.pill-care-t{ font-size:14px; font-weight:800; color:#111827; }
.pill-care-kinds{ margin-top:6px; font-size:13px; color:#374151; line-height:1.6; word-break:keep-all; }
.pill-care-sub{ margin-top:12px; font-size:13px; font-weight:800; color:#92400e; }
.pill-care-sig{ margin:4px 0 0; padding-left:18px; font-size:13px; color:#374151; line-height:1.6; }
.pill-care-go{ display:block; width:100% !important; height:42px !important; margin:12px 0 0 !important; padding:0 !important; border:none !important; border-radius:10px !important; background:#d97706 !important; color:#fff !important; font-size:14px !important; font-weight:800 !important; box-shadow:none !important; cursor:pointer; }
.pill-care-meds{ display:block; width:100% !important; height:42px !important; margin:12px 0 0 !important; padding:0 !important; border:1.5px solid #d97706 !important; border-radius:10px !important; background:#fff !important; color:#b45309 !important; font-size:14px !important; font-weight:800 !important; box-shadow:none !important; cursor:pointer; }
.pill-care-meds:disabled{ border-color:#fcd34d !important; color:#d6b25a !important; cursor:default; }
.pill-care-go + .pill-care-meds{ margin-top:8px !important; }
.pill-meds-flash{ background:#fef3c7 !important; border-color:#d97706 !important; box-shadow:0 0 0 3px rgba(217,119,6,0.25) !important; transition:background .3s, box-shadow .3s; }
.pill-care-go:disabled{ background:#fcd34d !important; cursor:default; }
.pill-care-note{ margin-top:8px; font-size:11px; color:#92400e; line-height:1.5; word-break:keep-all; }
.pill-yes{ width:auto !important; height:26px !important; margin:0 !important; padding:0 10px !important; border:none !important; border-radius:999px !important; background:#7c3aed !important; color:#fff !important; font-size:12px !important; font-weight:700 !important; box-shadow:none !important; cursor:pointer; }
.pill-loading{ display:none; position:fixed; inset:0; z-index:100003; background:rgba(0,0,0,0.5); align-items:center; justify-content:center; }
.pill-loading.show{ display:flex; }
.pill-loading-box{ box-sizing:border-box; width:86%; max-width:320px; background:#fff; border-radius:20px; padding:34px 24px 26px; text-align:center; display:flex; flex-direction:column; align-items:center; }
.pill-spinner{ width:42px; height:42px; border:5px solid #eee; border-top-color:#8b55d6; border-radius:50%; animation:pillSpin 1s linear infinite; }
@keyframes pillSpin{ to{ transform:rotate(360deg); } }
.pill-load-title{ margin:14px 0 0; font-size:15px; font-weight:700; line-height:1.35; color:#111827; }
.pill-load-sub{ margin:8px 0 0; font-size:13px; line-height:1.5; color:#6b7280; word-break:keep-all; }
.pill-steps{ display:flex; gap:6px; width:150px; margin:16px auto 0; }
.pill-step{ flex:1; height:6px; border-radius:999px; background:#e5e7eb; transition:background .3s; }
.pill-step.on{ background:#8b55d6; }
.pill-load-ci{ width:auto; max-width:96px; max-height:36px; object-fit:contain; margin-top:24px; opacity:0.82; display:block; }
.pill-foot{ flex:none; padding:8px 16px; border-top:1px solid #f1f5f9; font-size:11px; color:#9ca3af; line-height:1.5; word-break:keep-all; }
@media (max-width:480px){
  .pill-shot{ height:118px; }
  .pill-feat-row{ gap:5px; }
  .ps-btn{ padding:0 6px !important; gap:4px; font-size:12.5px !important; }
  .ps-btn .ps-caret{ display:none; }
  .pill-card img{ width:96px; height:54px; }
}
</style>

<div id="pillZoom" class="pill-zoom" role="dialog" aria-label="알약 사진 크게 보기">
  <button type="button" class="pill-zoom-x" aria-label="닫기">×</button>
  <img alt="">
  <div class="pill-zoom-cap"></div>
</div>
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
    <div class="pill-foot">참고용 후보입니다. 정확한 확인은 약사·의사에게 문의하세요.</div>
  </div>
</div>

<div id="pillLoading" class="pill-loading">
  <div class="pill-loading-box">
    <div class="pill-spinner"></div>
    <p class="pill-load-title" id="pillLoadTitle"></p>
    <p class="pill-load-sub" id="pillLoadSub"></p>
    <div class="pill-steps"><div class="pill-step"></div><div class="pill-step"></div><div class="pill-step"></div><div class="pill-step"></div></div>
    <img src="/ci" class="pill-load-ci" alt="" onerror="this.style.display='none'">
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
    fetch("/trip/api/pill/search", {
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
      return fetch("/trip/api/pill/locate", { method:"POST", body:fd, credentials:"same-origin" })
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
  /* 후보 사진을 누르면 화면 가득 크게 보기. 아무 곳이나 누르거나 뒤로가기로 닫힘 */
  var zoom = document.getElementById("pillZoom"), zoomPushed = false, zoomBackSkip = false;
  function openZoom(src, cap){
    zoom.querySelector("img").src = src;
    zoom.querySelector(".pill-zoom-cap").textContent = cap || "";
    zoom.classList.add("show");
    try{ history.pushState({ pillZoom:1 }, ""); zoomPushed = true; }catch(e){ zoomPushed = false; }
  }
  function hideZoom(){ zoom.classList.remove("show"); zoom.querySelector("img").removeAttribute("src"); }
  function closeZoom(){
    if(!zoom.classList.contains("show")) return;
    hideZoom();
    if(zoomPushed){ zoomPushed = false; zoomBackSkip = true; try{ history.back(); }catch(e){ zoomBackSkip = false; } }
  }
  zoom.addEventListener("click", function(e){ e.stopPropagation(); closeZoom(); });
  document.addEventListener("keydown", function(e){ if(e.key === "Escape" && zoom.classList.contains("show")){ e.stopPropagation(); closeZoom(); } }, true);

  function renderCards(box, cands){
    box.innerHTML = "";
    (cands || []).forEach(function(c){
      var card = document.createElement("div");
      card.className = "pill-card";
      var prints = [c.print_front, c.print_back].filter(function(x){ return x; }).join(" / ");
      card.innerHTML =
        (c.image ? '<img src="' + esc(c.image) + '" alt="' + esc(c.name) + ' 사진 (눌러서 크게 보기)" loading="lazy">' : '') +
        '<div class="pill-info">' +
          '<div class="pill-name">' + (c.conf ? '<span class="pill-conf ' + esc(c.conf) + '">' + esc(c.conf_label) + '</span>' : '') + (c.dementia ? '<span class="pill-badge">치매약</span>' : '') + esc(c.name).replace(/\(/g, '<wbr>(') + '</div>' +
          '<div class="pill-meta">' + (c.care && c.care.kind && !c.dementia ? '<span class="pill-kind">' + esc(c.care.kind) + '</span>' : '') + esc(c.company) + ' · ' + esc(c.etc_otc) + (c.cls ? ' · ' + esc(c.cls) : '') + '</div>' +
          '<div class="pill-meta">각인 ' + esc(prints || "-") + ' · ' + esc(c.color) + ' · ' + esc(c.shape) + '</div>' +
          '<div class="pill-actions">' +
            '<a class="pill-link" href="' + esc(c.detail_url) + '" target="_blank" rel="noopener noreferrer">상세정보(효능·용법) ↗</a>' +
          '</div>' +
        '</div>';
      var cimg = card.querySelector("img");
      if(cimg) cimg.addEventListener("click", function(e){ e.stopPropagation(); openZoom(c.image, c.name); });
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
     - 한 알이든 여러 알이든, 후보 수·확신도와 관계없이 알약마다 반드시 하나를 직접 고름
       (실물과 같은 약인지 사람이 확인하는 단계) */
  var careState = [], careBoxRef = null;
  var SIGNAL_TEXT = {
    "낙상 주의": "낙상 위험이 있음",
    "어지럼 주의": "일어설 때 어지럼으로 넘어질 위험이 있음",
    "야간 화장실 낙상 주의": "밤에 화장실을 자주 가 낙상 위험이 있음",
    "식사·영양 관리": "식사와 영양 관리가 필요함",
    "넘어짐 시 출혈 주의": "넘어지면 출혈 위험이 커 낙상 예방이 필요함",
    "인지 지원": "치매로 인지 지원이 필요함"
  };
  /* 약 이름에서 괄호 속 성분명 빼기: 세틸란캡슐200mg(아세틸시스테인) → 세틸란캡슐200mg */
  function shortName(n){ var t = String(n || "").replace(/\s*\([^)]*\)/g, "").trim(); return t || String(n || ""); }
  function uniqList(a){ var o = []; a.forEach(function(x){ if(x && o.indexOf(x) === -1) o.push(x); }); return o; }
  function careOf(st){
    var c = st.cands;
    if(!c.length) return { status:"none" };
    if(st.sel !== null && c[st.sel]) return { status:"sel", care:c[st.sel].care };
    return { status:"pick" };
  }
  function setupChoice(gi, glist, cands){
    var st = careState[gi];
    st.cands = cands; st.sel = null;
    var old = glist.parentNode && glist.parentNode.querySelector(".pill-pick-help");
    if(old) old.remove();
    if(!cands.length) return;
    var help = document.createElement("div");
    help.className = "pill-pick-help";
    help.textContent = "실물과 같은 약을 하나 골라 주세요.";
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
    var kinds = [], names = [], sigMap = {}, pending = 0;
    careState.forEach(function(st){
      var r = careOf(st);
      if(r.status === "pick"){ pending++; return; }
      if(r.status === "none") return;
      kinds.push(r.care.kind);
      if(st.sel !== null && st.cands[st.sel]) names.push(st.cands[st.sel].name);
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
    /* 조사서식(/survey)에서 연 경우: 사례검색을 새 창으로 열어 작성 중인 서식이 지워지지 않게 함 */
    var onSurvey = !!(surveyMode && document.querySelector('[name="s_meds"]'));
    /* 복용약 검색(홈)에서 연 경우만: 고른 약 이름(괄호 속 성분명 제외)을 자체조사 서식 '복용약' 칸으로 넘기는 버튼 */
    var unames = uniqList(names.map(shortName));
    h += '<button type="button" class="pill-care-go"' + (ukinds.length ? '' : ' disabled') + '>이 내용으로 돌봄 서비스 찾기</button>';
    if(!surveyMode){
      h += '<button type="button" class="pill-care-meds"' + (unames.length ? '' : ' disabled') + '>지자체 자체조사 서식 \'복용약\'에 넣기</button>';
    }
    h += '<div class="pill-care-note">약 종류로 본 참고 사항이며 의학적 판단이 아닙니다.' +
      (onSurvey ? ' 사례검색은 작성 중인 조사서식이 지워지지 않도록 새 창으로 열립니다.' : '') + '</div>';
    box.innerHTML = h;
    var medsBtn = box.querySelector(".pill-care-meds");
    if(medsBtn) medsBtn.addEventListener("click", function(){
      /* 서버를 거치지 않고 주소 # 뒤에 담아 조사서식으로 이동 (# 뒤는 서버로 전송되지 않음) */
      location.href = "/survey#pillmeds=" + encodeURIComponent(unames.join("\n"));
    });
    var go = box.querySelector(".pill-care-go");
    if(go) go.addEventListener("click", function(){
      var q = ukinds.join("·") + " 복용 중." + sigs.map(function(sg){ return " " + (SIGNAL_TEXT[sg] || sg) + "."; }).join("");
      var url = "/desc?query=" + encodeURIComponent(q);
      if(onSurvey){ window.open(url, "_blank", "noopener"); } else { location.href = url; }
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
      fetch("/trip/api/pill/search", {
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
    /* 출장 도구함은 팝업이 아니라 화면 안에 있으므로 화면 전체를 결과 위치로 스크롤 */
    var target = (msg.style.display === "block") ? msg : list;
    if(!target) return;
    setTimeout(function(){
      var top = target.getBoundingClientRect().top + window.pageYOffset - 12;
      window.scrollTo({ top: Math.max(0, top), behavior: "smooth" });
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
      return fetch("/trip/api/pill/identify", { method:"POST", body:fd, credentials:"same-origin" });
    }).then(function(r){ return r.json(); }).then(handle)
      .catch(function(){ showMsg("연결 오류가 발생했습니다. 잠시 후 다시 시도해 주세요."); })
      .finally(function(){ stopLoading(); goBtn.disabled = false; goBtn.textContent = "검색"; });
  });

  /* survey=true 이면 치매약 후보에 '예 선택' 버튼 표시 (사전조사 화면) */
  window.openPill = function(survey, restored){
    surveyMode = !!survey;
    if(!restored){
      
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
  /* 조사서식(/survey) 진입 시: 복용약 검색에서 넘긴 약 이름을 '복용약' 칸에 덧붙임 */
  (function receiveMeds(){
    var m = /[#&]pillmeds=([^&]*)/.exec(location.hash || "");
    if(!m) return;
    try{ history.replaceState(null, "", location.pathname + location.search); }catch(e){}
    var input = document.querySelector('[name="s_meds"]');
    if(!input) return;
    /* '복용약' 칸은 자체조사 탭에 있으므로 그 탭으로 전환 */
    if(typeof window.switchTab === "function"){ try{ window.switchTab("self"); }catch(e){} }
    var add = [];
    try{ add = decodeURIComponent(m[1]).split("\n"); }catch(e){ return; }
    var cur = input.value.split(/\s*,\s*/).filter(function(x){ return x; });
    add.forEach(function(n){ n = n.trim(); if(n && cur.indexOf(n) === -1) cur.push(n); });
    input.value = cur.join(", ");
    input.dispatchEvent(new Event("input", { bubbles:true }));
    input.dispatchEvent(new Event("change", { bubbles:true }));
    setTimeout(function(){
      try{ input.scrollIntoView({ block:"center", behavior:"smooth" }); }catch(e){}
      input.classList.add("pill-meds-flash");
      setTimeout(function(){ input.classList.remove("pill-meds-flash"); }, 2500);
    }, 400);
  })();

  window.closePill = function(){
    hidePill();
    /* X·바깥 클릭으로 닫으면 추가한 기록도 정리 */
    if(historyPushed){ historyPushed = false; try{ history.back(); }catch(e){} }
  };
  /* 뒤로가기 → 팝업 닫기 (메인화면 유지) */
  window.addEventListener("popstate", function(){
    /* 사진 크게 보기가 열려 있으면 그것만 닫고 알약 팝업은 유지 */
    if(zoomBackSkip){ zoomBackSkip = false; return; }   /* 사진을 눌러 닫으며 생긴 뒤로가기는 무시 */
    if(zoomPushed){ zoomPushed = false; hideZoom(); return; }
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
{% endraw %}''',
    "trip/base.html": r'''<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="theme-color" content="#f4f2ec">
<title>{% block title %}출장 도구함{% endblock %}</title>
<link rel="stylesheet" href="{{ url_for('trip.css') }}">
{% block head %}{% endblock %}
</head>
<body class="{% block theme %}{% endblock %}">
<div class="wrap">
<img class="ci" src="/ci" alt="국민건강보험공단" onerror="this.remove()">
{% block body %}{% endblock %}
</div>
<script>
/* 화면용 주소: 맨 앞 시·도는 빼고 시·군·구부터 (검색·계산에는 원래 주소 그대로 씀) */
function shortAddr(s){s=String(s||"").trim();const t=s.split(" ");
  const SH=["서울","부산","대구","인천","광주","대전","울산","세종","경기","강원","충북","충남","전북","전남","경북","경남","제주"];
  if(t.length>=2&&/[시군구]$/.test(t[1])&&(/[시도]$/.test(t[0])||SH.includes(t[0])))return t.slice(1).join(" ");return s;}
</script>
{% block script %}{% endblock %}
</body>
</html>
''',
    "trip/home.html": r'''{% extends "trip/base.html" %}
{% from "trip/_m.html" import icon %}
{% block theme %}t-home{% endblock %}
{% block body %}
<div class="hello">
  <div class="date" id="today"></div>
  <h1>오늘 출장,<br> 무엇부터 할까요?</h1>
</div>
<div class="tiles">
  <a class="tile route" href="{{ url_for('trip.route_page') }}">
    <span class="ico">{{ icon('route') }}</span>
    <span><div class="t">최적 동선</div><div class="d">방문지를 넣으면 가장 빠른 순서로 짜드려요</div></span></a>
  <a class="tile house" href="{{ url_for('trip.house_page') }}">
    <span class="ico">{{ icon('house') }}</span>
    <span><div class="t">집 미리보기</div><div class="d">주소 하나로 어떤 집인지 미리 알고 가요</div></span></a>
  <a class="tile board" href="{{ url_for('trip.board_page') }}">
    <span class="ico">{{ icon('board') }}</span>
    <span><div class="t">큰 글씨 대화</div><div class="d">귀가 어두운 분께 글자를 크게 보여드려요</div></span></a>
  <a class="tile cards" href="{{ url_for('trip.cards_page') }}">
    <span class="ico">{{ icon('cards') }}</span>
    <span><div class="t">통합판정<br>낱말카드</div><div class="d">준비 중이에요</div></span></a>
  <a class="tile toilet" href="{{ url_for('trip.toilet_page') }}">
    <span class="ico">{{ icon('toilet') }}</span>
    <span><div class="t">내 근처 화장실</div><div class="d">지금 위치에서 가까운 공중화장실</div></span></a>
  <a class="tile pill" href="{{ url_for('trip.pill_page') }}">
    <span class="ico">{{ icon('pill') }}</span>
    <span><div class="t">복용약 찾기</div><div class="d">알약 사진으로 어떤 약인지 확인</div></span></a>
</div>
<p class="note">이름·주민번호·전화번호는 받지 않고,<br class="mbr"> 입력한 주소·위치·사진은 서버에 저장하지 않아요.<br class="mbr"> 최근 검색 주소만 이 기기에 5개까지 남아요.{% if demo %}<br>지금은 예시 모드라 실제 조회 대신 예시 값이 나와요.{% endif %}</p>
{% endblock %}
{% block script %}
<script>
var d=new Date(),w="일월화수목금토"[d.getDay()];
document.getElementById("today").textContent=(d.getMonth()+1)+"월 "+d.getDate()+"일 "+w+"요일";
</script>
{% endblock %}
''',
    "trip/house.html": r'''{% extends "trip/base.html" %}
{% from "trip/_m.html" import src, topbar, wicon with context %}
{% block title %}집 미리보기 · 출장 도구함{% endblock %}
{% block theme %}t-house{% endblock %}
{% block body %}
{{ topbar('집 미리보기') }}
{% if error %}<div class="err">{{ error }}</div>{% endif %}
{% if cands %}
<div class="card">
  <div class="sec">'{{ q }}'(으)로 여러 곳이 나왔어요</div>
  <p class="hint" style="margin:0 0 10px">방문할 곳을 고르세요.</p>
  {% for c in cands %}
  <form method="post" action="{{ url_for('trip.house_search') }}">
    <input type="hidden" name="q" value="{{ q }}"><input type="hidden" name="floor" value="{{ floor }}"><input type="hidden" name="pick" value="{{ loop.index0 }}">
    <button class="cand" type="submit">{{ c.label|short_addr }}<small>{{ (c.road_address or c.jibun_address)|short_addr }}</small></button>
  </form>
  {% endfor %}
</div>
{% else %}
<div class="intro">
  <h2>가기 전에,<br>어떤 집인지 먼저 봐요</h2>
  <p>주소 하나로 건물 사진·구조·주변 치안까지 확인해요.</p>
</div>
<form class="card" method="post" action="{{ url_for('trip.house_search') }}" autocomplete="off">
  <label class="l" for="q">주소 또는 단지명</label>
  <span class="ac" style="display:block"><input type="text" id="q" name="q" value="{{ q or '' }}" placeholder="예: 광주전라제주지역본부"></span>
  <input type="hidden" name="addr" id="addr"><input type="hidden" name="label" id="label">
  <button class="btn main" type="submit">집 미리보기</button>
</form>
<div class="sec" style="margin:22px 4px 10px">이런 걸 알려줘요</div>
<div class="card gives1">
  <div class="g1"><span class="wi">{{ wicon('roof') }}</span><b>건물 사진</b><span>집 앞 로드뷰</span></div>
  <div class="g1"><span class="wi">{{ wicon('brick') }}</span><b>이 집은</b><span>용도⁠·⁠구조⁠·⁠준공⁠·⁠승강기</span></div>
  <div class="g1"><span class="wi">{{ wicon('alert') }}</span><b>조심할 점</b><span>계단⁠·⁠노후⁠·⁠지하층</span></div>
  <div class="g1"><span class="wi">{{ wicon('hill') }}</span><b>주변 치안</b><span>반경 300m 범죄주의구간</span></div>
</div>
{% if demo %}<p class="hint">예시 모드: 라인2차, 미소래를 넣어보세요. 공개 자료로 확인한 값만 들어 있어요.</p>{% endif %}
{% endif %}
{{ src([("건물 정보","국토교통부 건축HUB 건축물대장"),("로드뷰·주소","카카오맵"),("범죄주의구간","행정안전부 생활안전지도")]) }}
{% endblock %}
{% block script %}
{% include "trip/_ac.html" %}
<script>
(function(){
  var q=document.getElementById("q");if(!q)return;
  attachSuggest(q,function(pl){document.getElementById("addr").value=pl.address_name||pl.road_address_name||"";
      document.getElementById("label").value=pl.place_name||"";q.classList.add("picked");},
    function(){document.getElementById("addr").value="";document.getElementById("label").value="";q.classList.remove("picked");});
})();
(function(){const u=new URLSearchParams(location.search);
  if(u.get("go")!=="1"||!u.get("q"))return;
  const f=document.querySelector("form.card");if(!f)return;
  f.querySelector("input[name=q]").value=u.get("q");
  const a=f.querySelector("input[name=addr]");if(a)a.value=u.get("addr")||"";
  const l=f.querySelector("input[name=label]");if(l)l.value=u.get("q");
  history.replaceState(null,"",location.pathname);f.submit();})();
</script>
{% endblock %}
''',
    "trip/house_card.html": r'''{% extends "trip/base.html" %}
{% from "trip/_m.html" import src, topbar, wicon with context %}
{% block title %}{{ ((bld and bld.name) or loc.label)|short_addr }} · 집 미리보기{% endblock %}
{% block theme %}t-house{% endblock %}
{% block head %}<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">{% endblock %}
{% block body %}
{{ topbar('집 미리보기') }}
<div class="cols"><div class="colA">
<div class="rv">
  <div id="roadview"></div>
  <div id="rvMsg">{% if kakao_js_key %}건물 사진 불러오는 중{% else %}건물 정면 로드뷰<br><small class="muted">카카오 JavaScript 키를 넣으면 보여요</small>{% endif %}</div>
  <span class="tg">{{ ((bld and bld.name) or loc.label)|short_addr }}</span>
</div>

<div class="card">
  <p class="hname">{{ ((bld and bld.name) or loc.label)|short_addr }}</p>
  <p class="haddr">{{ (loc.road_address or loc.jibun_address)|short_addr }}</p>

  <div class="sec">이 집은</div>
  {% if rows %}
  <dl class="spec">{% for k, v in rows %}<dt>{{ k }}</dt><dd{% if v in ('대장에 안 적힘', '실제 조회하면 표시') %} class="muted"{% endif %}>{{ v }}</dd>{% endfor %}
</dl>
  {% elif missing %}
  <div class="fact"><div class="m">건축물대장에서 이 주소의 건물을 찾지 못했어요. 무허가·미등기 건물이거나, 대장에 다른 지번으로 올라가 있을 수 있어요.</div></div>
  {% elif not facts %}
  <div class="fact"><div class="m">건물 정보를 불러오지 못했어요. 현장에서 확인해 주세요.</div></div>
  {% endif %}

  {% if facts %}
  <div class="sec" style="margin-top:18px">이런 점을 조심하세요</div>
  <div class="warns">{% for ic, f, m in facts %}
    <div class="wt"><span class="wi">{{ wicon(ic) }}</span><div class="t">{{ f|replace("·", "⁠·⁠") }}</div><div class="d">{{ m|replace("·", "⁠·⁠") }}</div></div>
  {% endfor %}</div>
  {% elif rows %}
  <p class="hint" style="margin:14px 0 0">대장 정보로는 특별히 조심할 점이 보이지 않아요.</p>
  {% endif %}
</div>

</div><div class="colB">
<div class="card safe">
  <div class="sec">주변 치안 <span class="muted" style="font-weight:500;font-size:12px">생활안전지도 · 범죄주의구간</span></div>
  {% if safemap_key %}<div class="ctabs" id="crimeChips">{% for c in crime_layers %}<button type="button" data-i="{{ loop.index0 }}"{% if loop.first %} class="on"{% endif %}>{{ c.name }}</button>{% endfor %}</div>{% endif %}
  <div class="map" id="safeMap">{% if not safemap_key %}<div style="height:100%;display:flex;align-items:center;justify-content:center;text-align:center;color:var(--sub);font-size:13px;padding:16px">생활안전지도 키를 넣으면<br>집 주변 범죄주의구간이 색으로 겹쳐져요</div>{% endif %}</div>
  <div class="legend">낮음<span class="bar2"></span>높음 (10등급)</div>
  <p class="hint" id="safeNote">치안 정보 불러오는 중</p>
  <p class="hint">5대 범죄(살인·강도·성폭력·절도·폭력) 발생 밀도예요.<br>전체는 5대 범죄 합산, 나머지는 종류별이에요.<br>등급이 높다고 지금 위험하다는 뜻은 아니에요.<br>진한 길이 집 앞에 있으면 야간·단독 방문은 피하세요.</p>
</div>

<div class="card">
  <div class="sec">가서 볼 것</div>
  <ul class="checks">{% for c in checks %}<li>{{ c }}</li>{% endfor %}</ul>
  <div class="row" style="margin-top:14px">
    <a class="btn" style="flex:1" href="https://map.kakao.com/link/roadview/{{ loc.lat }},{{ loc.lng }}" target="_blank" rel="noopener">로드뷰 크게</a>
    <button class="btn" style="flex:1" type="button" onclick="window.print()">인쇄</button>
  </div>
</div>
</div></div>
<p class="hint">집 안 구조는 현장에서 확인하세요.</p>
<a class="btn" style="width:100%;margin-top:10px" href="{{ url_for('trip.house_page') }}">다른 집</a>
{{ src([("건물 정보", (source if demo and source else "국토교통부 건축HUB 건축물대장")),("로드뷰·주소","카카오맵"),("범죄주의구간","행정안전부 생활안전지도"),("지도","© OpenStreetMap")]) }}
{% endblock %}
{% block script %}
{% if kakao_js_key %}
<script src="https://dapi.kakao.com/v2/maps/sdk.js?appkey={{ kakao_js_key }}&autoload=false"></script>
<script>
(function(){
  var LAT={{ loc.lat }},LNG={{ loc.lng }},msg=document.getElementById("rvMsg"),
      PIN_NAME={{ (((bld and bld.name) or loc.label)|short_addr)|tojson }};
  function bearing(a,b){var r=Math.PI/180,y=Math.sin((b.getLng()-a.getLng())*r)*Math.cos(b.getLat()*r),
    x=Math.cos(a.getLat()*r)*Math.sin(b.getLat()*r)-Math.sin(a.getLat()*r)*Math.cos(b.getLat()*r)*Math.cos((b.getLng()-a.getLng())*r);
    return (Math.atan2(y,x)/r+360)%360;}
  if(!window.kakao||!kakao.maps){msg.innerHTML="로드뷰를 불러오지 못했어요";return;}
  kakao.maps.load(function(){
    var t=new kakao.maps.LatLng(LAT,LNG),el=document.getElementById("roadview"),
        rv=new kakao.maps.Roadview(el),cl=new kakao.maps.RoadviewClient(),
        pe=document.createElement("div"),ov;
    // 로드뷰 속 이 집 위치 팻말 (이름 · 거리 ▼)
    pe.className="rvpin";ov=new kakao.maps.CustomOverlay({position:t,content:pe,xAnchor:.5,yAnchor:1});
    (function tryR(rs){
      if(!rs.length){msg.style.display="none";var m=new kakao.maps.Map(el,{center:t,level:3});new kakao.maps.Marker({position:t,map:m});return;}
      cl.getNearestPanoId(t,rs[0],function(id){
        if(id===null)return tryR(rs.slice(1));
        rv.setPanoId(id,t);
        kakao.maps.event.addListener(rv,"init",function(){
          var q=rv.getPosition();if(!q)return;
          var R=Math.PI/180,x=Math.pow(Math.sin((LAT-q.getLat())*R/2),2)+Math.cos(q.getLat()*R)*Math.cos(LAT*R)*Math.pow(Math.sin((LNG-q.getLng())*R/2),2),
              d=Math.round(12742000*Math.asin(Math.sqrt(x))),nm=PIN_NAME.length>12?PIN_NAME.slice(0,12)+"…":PIN_NAME;
          pe.innerHTML="<b></b><i></i>";pe.firstChild.textContent=nm+(d>=10?" · "+(d<1000?d+"m":(d/1000).toFixed(1)+"km"):"");
          ov.setMap(rv);
          var vp=null;try{vp=rv.getProjection().viewpointFromCoords(ov.getPosition(),ov.getAltitude());}catch(e){}
          rv.setViewpoint(vp?{pan:vp.pan,tilt:vp.tilt,zoom:0}:{pan:bearing(q,t),tilt:5,zoom:0});msg.style.display="none";});
      });
    })([50,100,200]);
  });
})();
</script>
{% endif %}
{% if safemap_key %}
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script>
(function(){
  if(!window.L)return;
  var c=[{{ loc.lat }},{{ loc.lng }}];
  var m=L.map("safeMap",{zoomControl:false,attributionControl:false}).setView(c,16);
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",{maxZoom:19,className:"basemap"}).addTo(m);
  // 생활안전지도 범죄주의구간(전체) WMS. 공식 예제: openapi2/IF_0087_WMS, serviceKey, 파라미터는 소문자
  // 생활안전지도 범죄주의구간 WMS. 종류별로 IF 번호·스타일이 다름 (서버 설정 TRIP_CRIME_LAYERS)
  var LAYERS={{ crime_layers|tojson }},note=document.getElementById("safeNote"),cur=null;
  function show(i){
    var L0=LAYERS[i],bad=0,ok=0;
    if(cur)m.removeLayer(cur);
    note.style.color="";note.textContent=L0.name+" 불러오는 중";
    cur=L.tileLayer.wms(L0.url,{layers:"A2SM_CRMNLHSPOT_TOT",styles:L0.style,
      format:"image/png",transparent:true,serviceKey:"{{ safemap_key }}",opacity:1,className:"crimelayer"});
    cur.on("tileerror",function(){bad++;});
    cur.on("tileload",function(){ok++;});
    cur.on("load",function(){
      if(bad&&!ok){note.textContent=(i?L0.name+" 지도를":"치안 정보를")+" 불러오지 못했어요. 생활안전지도 키 승인·사이트 주소를 확인해 주세요.";note.style.color="#b4332f";}
      else{note.textContent="["+L0.name+"] 색이 칠해진 길이 없으면 이 주변은 "+(i?L0.name+" ":"")+"범죄주의구간이 아니에요.";}
    });
    cur.addTo(m);cur.setZIndex(5);
  }
  document.querySelectorAll("#crimeChips button").forEach(function(b){
    b.onclick=function(){document.querySelectorAll("#crimeChips button").forEach(function(x){x.classList.remove("on");});
      b.classList.add("on");show(+b.dataset.i);};
  });
  show(0);
  L.circle(c,{radius:300,color:"#e0782f",weight:1.5,dashArray:"4 4",fill:false}).addTo(m);
  L.circleMarker(c,{radius:8,color:"#fff",weight:3,fillColor:"#e0782f",fillOpacity:1}).addTo(m);
})();
</script>
{% endif %}
{% endblock %}
''',
    "trip/pill.html": r'''{% extends "trip/base.html" %}
{% from "trip/_m.html" import src, topbar with context %}
{% block title %}복용약 찾기 · 출장 도구함{% endblock %}
{% block theme %}t-pill{% endblock %}
{% block body %}
{{ topbar('복용약 찾기') }}
{{ src([("알약 정보","식품의약품안전처 의약품 낱알식별"),("사진 판독","OpenAI")]) }}
{% endblock %}
{% block script %}
{% include "trip/_pill_cn.html" %}
<style>
/* 케어내비 알약 확인과 내용·기능은 같고, 팝업 대신 출장 도구함 화면 안에 카드로 보여줌 */
.t-pill .pill-modal{display:block!important;position:static;inset:auto;background:none;padding:0;z-index:auto;max-width:480px;margin:0 auto}
.t-pill .pill-box{max-width:none;max-height:none;border:1px solid var(--line);border-radius:var(--r);box-shadow:none;overflow:visible;color:var(--ink)}
.t-pill .pill-head{border-bottom:none;padding:16px 16px 4px}
.t-pill .pill-head>div:first-child,.t-pill .pill-head-btns{display:none}
.t-pill .pill-sub{margin-top:0;color:var(--sub)}
.t-pill .pill-body{overflow:visible;padding:14px 16px 16px}
.t-pill .pill-foot{border-top:1px solid var(--line);color:var(--muted)}
.t-pill .pill-shot{border-radius:14px}
.t-pill .pill-go,.t-pill .pill-tab{font-family:inherit}
.t-pill .pill-go{height:52px!important;border-radius:14px!important}
.t-pill .pill-card{border-color:var(--line);border-radius:14px}
/* 출장 도구함에는 케어내비 사례검색·조사서식이 없어서 연결 버튼은 숨김 */
.pill-care-go,.pill-care-meds{display:none!important}
@media (min-width:960px){
  .t-pill .pill-modal{max-width:760px}
  .t-pill .pill-shot{height:180px}
  .t-pill .pill-sub,.t-pill .pill-tip{font-size:15px}
  .t-pill .pill-tab{height:48px!important;font-size:16px!important}
  .t-pill .pill-shot{font-size:16px}
  .t-pill .pill-shot small{font-size:13px}
  .t-pill .pill-go{height:58px!important;font-size:18px!important}
  .t-pill .pill-feat-title{font-size:15px}
  .t-pill .pill-feat-help,.t-pill .pill-imp2 label{font-size:13.5px}
  .t-pill .pill-imp2 input{height:46px;font-size:16px}
  .t-pill .ps-btn{height:44px!important;font-size:15px!important}
  .t-pill .pill-name{font-size:16px}
  .t-pill .pill-meta{font-size:13.5px}
  .t-pill .pill-foot{font-size:12.5px}
}
</style>
<script>
(function(){
  // 팝업 대신 화면 안에 펼쳐 둠: 열 때 기록을 추가하지 않게 하고, 화면 스크롤도 막지 않음
  var wrap=document.querySelector(".wrap"),modal=document.getElementById("pillModal");
  if(!modal)return;
  var srcEl=document.querySelector(".wrap > .src");
  if(srcEl) wrap.insertBefore(modal, srcEl); else wrap.appendChild(modal);
  try{ if(!(history.state&&history.state.pillModal)) history.replaceState({pillModal:true},""); }catch(e){}
  if(!modal.classList.contains("show")) openPill(false);
  document.body.style.overflow="";
  window.closePill=function(){location.href="{{ url_for('trip.home') }}";};
  // 혹시 닫히면 다시 펼침
  new MutationObserver(function(){ if(!modal.classList.contains("show")){ modal.classList.add("show"); document.body.style.overflow=""; } })
    .observe(modal,{attributes:true,attributeFilter:["class"]});
})();
</script>
{% endblock %}
''',
    "trip/route.html": r'''{% extends "trip/base.html" %}
{% from "trip/_m.html" import src, topbar with context %}
{% block title %}최적 동선 · 출장 도구함{% endblock %}
{% block theme %}t-route{% endblock %}
{% block head %}<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">{% endblock %}
{% block body %}
{{ topbar('최적 동선') }}
<div class="cols"><div class="colA">
<div class="card" id="form">
  <label class="l">출발지</label>
  <div class="row"><span class="ac"><input type="text" id="start" placeholder="예: 광주전라제주지역본부" autocomplete="off"></span>
    <button class="btn sm" type="button" id="gpsBtn">현재 위치</button></div>
  <p class="gpsat" id="gpsAt" style="display:none"></p>
  <label class="l">방문지 <span class="muted" style="font-weight:500">· 순서 상관없이 넣으세요 (최대 {{ max_stops }}곳)</span></label>
  <div id="stops"></div>
  <button class="btn ghost" type="button" id="addStop">+ 방문지 추가</button>
  <label class="l">도착</label>
  <div class="seg"><input type="radio" name="endmode" id="back" checked><label for="back">출발지로 돌아오기</label><input type="radio" name="endmode" id="other"><label for="other">다른 곳에서 끝내기</label></div>
  <div id="endBox" style="display:none;margin-top:8px"><span class="ac" style="display:block"><input type="text" id="end" placeholder="도착지 주소" autocomplete="off"></span></div>
  <button class="btn main" id="go" type="button">최적 동선 찾기</button>
  <div id="msg"></div>
  <div class="ptoast" id="pinToast"></div>
  {% if demo %}<p class="hint">예시 모드: 지사, 라인2차, 미소래, 라인1차를 넣어보세요.<br>시간은 직선거리로 추정한 값이에요.</p>{% endif %}
</div>
</div><div class="colB">
<div id="result" style="display:none"></div>
<div class="ph" id="ph"><p>방문지를 넣고 <b>최적 동선 찾기</b>를 누르면<br>여기에 순서와 지도가 나와요</p></div>
</div></div>
<div class="big" id="big"><div class="bbox">
  <div class="sh"><div style="flex:1;min-width:0"><b id="bigT"></b><small id="bigA"></small></div><button type="button" id="bigX" aria-label="닫기">×</button></div>
  <div class="bigrv"><div id="bigRv" style="position:absolute;inset:0"></div><div class="mrmsg" id="bigMsg"></div></div>
</div></div>
{{ src([("경로·시간","카카오모빌리티 길찾기"),("주소 검색·로드뷰","카카오맵"),("지도","© OpenStreetMap")]) }}
{% endblock %}
{% block script %}
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
{% if kakao_js_key %}<script src="https://dapi.kakao.com/v2/maps/sdk.js?appkey={{ kakao_js_key }}&autoload=false"></script>{% endif %}
{% include "trip/_ac.html" %}
<script>
const MAX={{ max_stops }}; let gps=null,lastBody=null,bestRes=null;
const PINI='<svg viewBox="0 0 24 24" fill="currentColor"><path d="M16 9V4h1c.55 0 1-.45 1-1s-.45-1-1-1H7c-.55 0-1 .45-1 1s.45 1 1 1h1v5c0 1.66-1.34 3-3 3v2h5.97v7l1 1 1-1v-7H19v-2c-1.66 0-3-1.34-3-3z"/></svg>';
const $=s=>document.querySelector(s);
const esc=t=>String(t??"").replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const dur=s=>{const m=Math.round(s/60);return m>=60?`${Math.floor(m/60)}시간 ${m%60}분`:`${m}분`};
const km=m=>m<1000?`${m}m`:`${(m/1000).toFixed(1)}km`;

const pickOf=inp=>{try{return inp.dataset.pick?JSON.parse(inp.dataset.pick):null}catch(e){return null}};
function routePick(inp){
  attachSuggest(inp,pl=>{inp.dataset.pick=JSON.stringify({label:pl.place_name||"",road_address:pl.road_address_name||pl.address_name||"",lat:+pl.y,lng:+pl.x});inp.classList.add("picked");},
    ()=>{delete inp.dataset.pick;inp.classList.remove("picked");});
}
routePick($("#start"));routePick($("#end"));

function swapInputs(a,b){
  [a.value,b.value]=[b.value,a.value];
  const pa=a.dataset.pick,pb=b.dataset.pick;
  if(pb)a.dataset.pick=pb;else delete a.dataset.pick;
  if(pa)b.dataset.pick=pa;else delete b.dataset.pick;
  a.classList.toggle("picked",!!a.dataset.pick);b.classList.toggle("picked",!!b.dataset.pick);
}
function renumber(){
  const rows=[...document.querySelectorAll("#stops .stop")];
  rows.forEach((r,i)=>r.querySelector(".n").textContent=i+1);
  $("#addStop").style.display=rows.length>=MAX?"none":"";}
/* ---- 순서 고정: 채운 방문지 기준으로 '몇 번째'에 꼭 넣기 ---- */
const filledRows=()=>[...document.querySelectorAll("#stops .stop")].filter(r=>r.querySelector("input").value.trim());
const pinLabel=v=>v==="last"?"마지막":v+"번째";
function setPin(row,v){
  const chip=row.querySelector(".pchip");
  if(v){row.dataset.pin=v;row.classList.add("pinned");chip.textContent=pinLabel(v);}
  else{delete row.dataset.pin;row.classList.remove("pinned");chip.textContent="";}
}
function checkPins(){
  const rows=[...document.querySelectorAll("#stops .stop")],F=filledRows().length;let freed=false;
  const hasLast=rows.some(r=>r.dataset.pin==="last"&&r.querySelector("input").value.trim());
  rows.forEach(r=>{
    const filled=!!r.querySelector("input").value.trim(),v=r.dataset.pin;
    r.querySelector(".lockb").disabled=!filled||F<2;
    if(!v)return;
    if(!filled||F<2||(v!=="last"&&(+v>F||(+v===F&&hasLast)))){setPin(r,null);freed=true;}
  });
  if(freed)toast("방문지 수가 바뀌어 순서 고정이 풀렸어요.");
}
function toast(t){const el=$("#pinToast");el.textContent=t;el.classList.add("on");clearTimeout(el._t);el._t=setTimeout(()=>el.classList.remove("on"),2200);}
function closePin(){document.querySelectorAll(".pinbar").forEach(x=>x.remove());document.querySelectorAll(".stop.open").forEach(x=>x.classList.remove("open"));}
/* 케어내비 + 메뉴처럼 반투명 바가 칸 아래에 떠오름 (화면은 밀리지 않음) */
function openPin(row){
  closePin();document.querySelectorAll(".acl.on").forEach(x=>x.classList.remove("on"));
  const F=filledRows().length;if(F<2)return;
  const opts=[...Array(F-1).keys()].map(k=>String(k+1)).concat(["last"]);
  const taken={};filledRows().forEach(r=>{if(r!==row&&r.dataset.pin)taken[r.dataset.pin]=r.querySelector("input").value.trim();});
  const bar=document.createElement("div");bar.className="pinbar"+(opts.length+(row.dataset.pin?1:0)>5?" many":"");
  bar.innerHTML=opts.map(v=>{const t=taken[v],cur=row.dataset.pin===v;
      return `<button type="button" data-v="${v}" ${t?"disabled":""}><b class="${cur?"on":""}">${v==="last"?"끝":v}</b><span>${t?esc(t.slice(0,5)):pinLabel(v)}</span></button>`;}).join("")
    +(row.dataset.pin?'<button type="button" data-v="" class="free"><b>✕</b><span>풀기</span></button>':"");
  bar.onclick=e=>{e.stopPropagation();const b=e.target.closest("button[data-v]");if(!b||b.disabled)return;setPin(row,b.dataset.v||null);closePin();};
  row.classList.add("open");row.appendChild(bar);
}
document.addEventListener("click",e=>{if(!e.target.closest(".pinbar"))closePin();});
function addStop(v=""){const d=document.createElement("div");d.className="stop";
  d.innerHTML=`<span class="n"></span><span class="ac pinac"><span class="pchip"></span><input type="text" placeholder="방문할 집 주소나 단지명" value="${esc(v)}" autocomplete="off"><button class="lockb" type="button" aria-label="순서 고정" title="순서 고정"><i class="off"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><rect x="5" y="10" width="14" height="11" rx="2"/><path d="M8 10V7a4 4 0 0 1 7.6-1.8"/></svg></i><i class="on"><svg viewBox="0 0 24 24" fill="currentColor"><path d="M18 8h-1V6A5 5 0 0 0 7 6v2H6a2 2 0 0 0-2 2v10a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V10a2 2 0 0 0-2-2zM9 6a3 3 0 0 1 6 0v2H9V6z"/></svg></i></button></span><button class="x" type="button" aria-label="삭제">×</button>`;
  routePick(d.querySelector("input"));
  d.querySelector(".lockb").onclick=e=>{e.stopPropagation();if(d.querySelector(".pinbar"))closePin();else openPin(d);};
  d.querySelector("input").addEventListener("input",()=>setTimeout(checkPins,0));
  d.querySelector("input").addEventListener("change",checkPins);
  d.querySelector(".x").onclick=()=>{if(document.querySelectorAll("#stops .stop").length>1){d.remove();renumber();checkPins();}};
  $("#stops").appendChild(d);renumber();}
addStop();addStop();addStop();checkPins();
$("#addStop").onclick=()=>{addStop();checkPins();};
const endSync=()=>{$("#endBox").style.display=$("#back").checked?"none":"";};
$("#back").onchange=endSync;$("#other").onchange=endSync;
$("#gpsBtn").onclick=()=>{
  if(!navigator.geolocation){alert("위치를 쓸 수 없는 기기예요.");return;}
  $("#gpsBtn").textContent="찾는 중…";
  navigator.geolocation.getCurrentPosition(p=>{gps=[p.coords.latitude,p.coords.longitude];$("#start").value="현재 위치";$("#gpsBtn").textContent="현재 위치 ✓";
    // 지금 어디인지 주소로 보여줌
    const at=$("#gpsAt");at.style.display="";at.textContent="위치 확인 중…";
    fetch("{{ url_for('trip.api_where') }}?lat="+gps[0]+"&lng="+gps[1]).then(r=>r.json()).then(d=>{
      if(!gps)return;at.innerHTML=d.address?`<span class="pin"></span><span class="at">${esc(d.address)}</span>`:"주소를 찾지 못했어요. 지도에서 위치를 확인하세요.";
    }).catch(()=>{at.style.display="none";});},
    ()=>{$("#gpsBtn").textContent="현재 위치";alert("위치를 가져오지 못했어요.");},{enableHighAccuracy:true,timeout:10000});};
$("#start").oninput=()=>{if(gps&&$("#start").value!=="현재 위치"){gps=null;$("#gpsBtn").textContent="현재 위치";$("#gpsAt").style.display="none";}};

function saveLast(r,body){try{sessionStorage.setItem("trip_route_last",JSON.stringify({r,body,pins:[...document.querySelectorAll("#stops .stop")].map(x=>x.dataset.pin||"")}))}catch(e){}}
function restoreLast(){
  let d=null;try{d=JSON.parse(sessionStorage.getItem("trip_route_last")||"null")}catch(e){}
  const nav=(performance.getEntriesByType&&performance.getEntriesByType("navigation")[0])||{};
  if(!d||nav.type!=="back_forward")return;
  const b=d.body;$("#start").value=b.start||"";
  if(b.picks&&b.picks.start){$("#start").dataset.pick=JSON.stringify(b.picks.start);$("#start").classList.add("picked");}
  if(b.gps){gps=b.gps;$("#gpsBtn").textContent="현재 위치 ✓";}
  document.querySelectorAll("#stops .stop").forEach(x=>x.remove());
  b.stops.forEach((v,i)=>{addStop(v);const row=[...document.querySelectorAll("#stops .stop")].pop(),inp=row.querySelector("input");
    if(b.picks&&b.picks.stops&&b.picks.stops[i]){inp.dataset.pick=JSON.stringify(b.picks.stops[i]);inp.classList.add("picked");}
    if(b.pins&&b.pins[i])setPin(row,b.pins[i]);});
  $("#back").checked=b.return_to_start;$("#other").checked=!b.return_to_start;$("#endBox").style.display=b.return_to_start?"none":"";$("#end").value=b.end||"";
  checkPins();lastBody=b;bestRes=d.r;show(d.r);
  if(history.state&&history.state.tripFocus!=null)setTimeout(()=>focusPt(history.state.tripFocus,true),300);   // 집 미리보기에서 돌아오면 보던 곳 그대로
}
// 맨 위 ‹ 버튼도 한 곳을 보는 중이면 전체 경로로
document.querySelector(".bar a.back").addEventListener("click",e=>{if(FOCUS!=null){e.preventDefault();closeFocus();}});
$("#go").onclick=async()=>{
  if(history.state&&history.state.tripFocus!=null)history.replaceState(null,"");
  const stopInputs=[...document.querySelectorAll("#stops input")].filter(i=>i.value.trim());
  const stops=stopInputs.map(i=>i.value.trim());
  const picks={start:pickOf($("#start")),end:pickOf($("#end")),stops:stopInputs.map(pickOf)};
  const pins=stopInputs.map(i=>i.closest(".stop").dataset.pin||null);
  const body={start:$("#start").value.trim(),stops,end:$("#end").value.trim(),return_to_start:$("#back").checked,gps,picks,pins};
  lastBody=body;
  $("#msg").innerHTML="";const b=$("#go");b.disabled=true;b.innerHTML='<span class="spin"></span> 순서 비교하는 중';
  try{const r=await (await fetch("/trip/api/route",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)})).json();
    if(!r.ok){$("#msg").innerHTML=`<div class="err" style="margin:12px 0 0">${esc(r.message)}</div>`;return;}
    bestRes=r;show(r);saveLast(r,body);}
  catch(e){$("#msg").innerHTML='<div class="err" style="margin:12px 0 0">연결에 실패했어요.</div>';}
  finally{b.disabled=false;b.textContent="최적 동선 찾기";}
};

async function reorder(i){
  // 결과에서 i번째와 i+1번째 방문지를 바꿔 그 순서대로 다시 계산
  const cur=window._curRes,o=cur.order.slice(1,-1);
  [o[i-1],o[i]]=[o[i],o[i-1]];
  const body=Object.assign({},lastBody,{keep_order:true,stops:o.map(p=>p.label||p.input),
    picks:Object.assign({},lastBody.picks,{stops:o.map(p=>({label:p.label||p.input,road_address:p.road_address||"",lat:p.lat,lng:p.lng}))})});
  document.querySelectorAll("#result .swap").forEach(b=>b.disabled=true);
  try{const r=await (await fetch("/trip/api/route",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)})).json();
    if(!r.ok){alert(r.message);return;}
    r.order.slice(1,-1).forEach((p,k)=>{p.input=o[k].input;p.label=o[k].label;});
    show(r);}
  catch(e){alert("연결에 실패했어요.");}
  finally{document.querySelectorAll("#result .swap").forEach(b=>b.disabled=false);}
}

function show(r){
  window._curRes=r;
  const o=r.order,last=o.length-1;
  let saved="";
  if(r.fixed){const diff=r.total_duration-bestRes.total_duration;
    saved=diff>=60?`최적 순서보다 ${dur(diff)} 더 걸려요`:diff<=-60?`최적 순서보다 ${dur(-diff)} 빨라요`:"최적 순서와 거의 같아요";}
  else if(r.saved_vs_input>=60)saved=`입력한 순서보다 ${dur(r.saved_vs_input)} 빨라요`;
  else if(r.saved_vs_worst>=60)saved=`가장 느린 순서보다 ${dur(r.saved_vs_worst)} 빨라요`;
  else saved="입력한 순서가 이미 가장 빨라요";
  let tl="",cum=0;
  o.forEach((p,i)=>{
    if(i>0)cum+=r.legs[i-1].duration;
    const se=i===0||i===last, label=i===0?"출발":i===last?"도착":i;
    const nm=shortAddr(se?(i===last&&r.return_to_start?"출발지로 복귀":p.label||p.input):(p.label||p.input));
    const go=se?"":`<a class="btn sm go" href="https://map.kakao.com/link/to/${encodeURIComponent(p.label||p.input)},${p.lat},${p.lng}" target="_blank" rel="noopener">길안내</a>`;
    const leg=i<last?`<div class="leg">↓ ${dur(r.legs[i].duration)} · ${km(r.legs[i].distance)}</div>`:"";
    tl+=`<li><span class="dot ${se?"se":""}" role="button" tabindex="0" title="지도에서 보기" onclick="focusPt(${i})">${label}</span><div class="body"><div class="nm">${esc(nm)}${p.pin?`<span class="pint">${PINI}${esc(p.pin)}</span>`:""}</div><div class="ad">${esc(shortAddr(p.road_address||p.input||""))}</div>${i>0?`<div class="cum">출발 후 이동 약 ${dur(cum)}</div>`:""}${leg}</div>${go}</li>`;
  });
  $("#result").innerHTML=`
    <div class="hero${r.fixed?" mine":""}"><b>${r.fixed?"내가 바꾼 순서":"최적 동선"}${r.demo?" (예시 추정)":""}</b><div class="big">${dur(r.total_duration)}</div>
      <div class="sm">${km(r.total_distance)} · ${r.fixed?"":r.orders_checked+"가지 순서 비교 · "}${saved}</div>
      ${r.fixed?'<button type="button" class="btn sm back2" onclick="show(bestRes)">최적 순서로 되돌리기</button>':""}</div>
    <div class="card" style="padding:10px"><div class="map" id="map"></div>
      <div id="mini" class="mini" style="display:none"><div class="mh"><b id="miniT"></b></div><div class="macts"><a id="miniHouse" class="ma">집 미리보기</a><a id="miniBig" class="ma" href="#">로드뷰 크게</a><button type="button" class="ma" onclick="closeFocus()">전체 경로</button></div>
        <div class="minirv"><div id="miniRv" style="position:absolute;inset:0"></div><div class="mrmsg" id="miniMsg"></div></div></div>
      <p class="hint" style="margin:8px 4px 0">번호를 누르면 그곳이 어딘지 지도와 로드뷰로 보여줘요.<br>같은 번호를 다시 누르거나 '전체 경로'를 누르면 원래대로 돌아가요.</p></div>
    <div class="card"><ul class="tl">${tl}</ul></div>
    ${r.demo?'<p class="hint">예시 모드라 직선거리로 추정한 시간이에요.<br>실제 키를 넣으면 실시간 교통을 반영해요.</p>':'<p class="hint">실시간 교통을 반영한 자동차 기준이에요.</p>'}`;
  $("#result").style.display="";if($("#ph"))$("#ph").remove();
  drawMap(r);
  if(!r.fixed)$("#result").scrollIntoView({behavior:"smooth"});
}

let MAP=null,MARK=[],RV=null,RVC=null,RVPIN=null,ALL=[],FOCUS=null;
/* 로드뷰 속 방문지 팻말: 카메라를 팻말 정면으로 */
function aimRv(rv,ov,g){try{const q=rv.getPosition();if(!q)return;ov.setMap(rv);
  let vp=null;try{vp=rv.getProjection().viewpointFromCoords(ov.getPosition(),ov.getAltitude());}catch(e){}
  rv.setViewpoint(vp?{pan:vp.pan,tilt:vp.tilt,zoom:0}:{pan:bearing({lat:q.getLat(),lng:q.getLng()},g),tilt:5,zoom:0});}catch(e){}}
function distM(a1,o1,a2,o2){const R=Math.PI/180,x=Math.sin((a2-a1)*R/2)**2+Math.cos(a1*R)*Math.cos(a2*R)*Math.sin((o2-o1)*R/2)**2;return 12742000*Math.asin(Math.sqrt(x));}
/* 큰 로드뷰 (앱 안): 화장실과 같은 방식. 매번 새로 만들고, 폰 뒤로가기로 닫힘 */
function openBigRv(p,nm){
  $("#bigT").textContent=nm;$("#bigA").textContent=shortAddr(p.road_address||p.input||"");
  $("#big").classList.add("on");history.pushState({tripFocus:FOCUS,tripBig:1},"");
  const msg=$("#bigMsg");msg.style.display="";msg.textContent="로드뷰 불러오는 중";
  if(!(window.kakao&&kakao.maps)){msg.textContent="로드뷰를 불러오지 못했어요";return;}
  kakao.maps.load(()=>{
    const box=$("#bigRv");box.innerHTML="";
    const rv=new kakao.maps.Roadview(box),cl=new kakao.maps.RoadviewClient(),pos=new kakao.maps.LatLng(p.lat,p.lng);
    const pe=document.createElement("div");pe.className="rvpin";
    const ov=new kakao.maps.CustomOverlay({position:pos,content:pe,xAnchor:.5,yAnchor:1});
    kakao.maps.event.addListener(rv,"init",()=>{const q=rv.getPosition();if(!q)return;
      const d=Math.round(distM(q.getLat(),q.getLng(),p.lat,p.lng)),lb=nm.length>12?nm.slice(0,12)+"…":nm;
      pe.innerHTML=`<b>${esc(lb)}${d>=10?` · ${d<1000?d+"m":(d/1000).toFixed(1)+"km"}`:""}</b><i></i>`;
      aimRv(rv,ov,{lat:p.lat,lng:p.lng});msg.style.display="none";});
    (function tryR(rs){
      if(!rs.length){msg.textContent="이 근처엔 로드뷰 사진이 없어요";return;}
      cl.getNearestPanoId(pos,rs[0],id=>{if(id===null)return tryR(rs.slice(1));rv.setPanoId(id,pos);});
    })([50,100,200]);
  });
}
function closeBigRv(){if(!$("#big").classList.contains("on"))return;
  if(history.state&&history.state.tripBig)history.back();else $("#big").classList.remove("on");}
document.addEventListener("click",e=>{if(e.target.id==="big"||e.target.id==="bigX")closeBigRv();});
function unfocus(){
  // 번호 누르기 전 상태로: 전체 경로가 보이게, 로드뷰 닫기
  FOCUS=null;
  document.querySelectorAll("#result .tl li").forEach(li=>li.classList.remove("on"));
  if(MAP){MAP.closePopup();if(ALL.length)MAP.fitBounds(ALL,{padding:[28,28]});}
  $("#mini").style.display="none";
}
function bearing(a,b){const r=Math.PI/180,y=Math.sin((b.lng-a.lng)*r)*Math.cos(b.lat*r),
  x=Math.cos(a.lat*r)*Math.sin(b.lat*r)-Math.sin(a.lat*r)*Math.cos(b.lat*r)*Math.cos((b.lng-a.lng)*r);
  return (Math.atan2(y,x)/r+360)%360;}
/* 번호를 눌러 한 곳을 볼 때 기록을 하나 쌓아서, 폰 뒤로가기·‹ 버튼이 '전체 경로'와 같게 동작 */
function closeFocus(){
  if(history.state&&history.state.tripFocus!=null)history.back();   // popstate에서 unfocus
  else unfocus();
}
window.addEventListener("popstate",e=>{
  if($("#big").classList.contains("on")){$("#big").classList.remove("on");if(!(e.state&&e.state.tripBig))return;}
  const f=e.state&&e.state.tripFocus;
  if(f==null){if(FOCUS!=null)unfocus();}
  else if(window._curRes&&FOCUS!==f)focusPt(f,true);
});
function focusPt(i,noHist){
  const r=window._curRes,o=r.order,last=o.length-1;
  if(i===last&&r.return_to_start)i=0;
  if(FOCUS===i&&!noHist){closeFocus();return;}   // 같은 번호를 다시 누르면 원래대로
  if(!noHist){
    if(history.state&&history.state.tripFocus!=null)history.replaceState({tripFocus:i},"");
    else history.pushState({tripFocus:i},"");
  }
  FOCUS=i;
  const p=o[i],nm=shortAddr(i===0?(p.label||p.input||"출발"):(p.label||p.input));
  document.querySelectorAll("#result .tl li").forEach((li,k)=>li.classList.toggle("on",k===i||(i===0&&k===last&&r.return_to_start)));
  if(MAP){MAP.setView([p.lat,p.lng],17,{animate:true});
    const mk=MARK[i];if(mk)mk.bindPopup(`<b>${esc(nm)}</b><br><small>${esc(shortAddr(p.road_address||p.input||""))}</small>`).openPopup();}
  const box=$("#mini");box.style.display="";$("#miniT").textContent=(i===0?"출발 · ":i===last?"도착 · ":i+"번 · ")+nm;
  $("#miniBig").onclick=e=>{e.preventDefault();openBigRv(p,nm);};
  $("#miniHouse").href=`{{ url_for('trip.house_page') }}?go=1&q=${encodeURIComponent(p.label||p.input||"")}&addr=${encodeURIComponent(p.road_address||p.input||"")}`;
  $("#miniHouse").style.display=(i===0||i===last)?"none":"";
  const msg=$("#miniMsg");msg.style.display="";
  if(!window.kakao||!kakao.maps){msg.textContent="카카오 JavaScript 키를 넣으면 로드뷰가 보여요";return;}
  msg.textContent="로드뷰 불러오는 중";
  kakao.maps.load(()=>{
    const t=new kakao.maps.LatLng(p.lat,p.lng);
    if(!RV){RV=new kakao.maps.Roadview($("#miniRv"));RVC=new kakao.maps.RoadviewClient();
      const pe=document.createElement("div");pe.className="rvpin sm";pe.innerHTML="<i></i>";
      RVPIN=new kakao.maps.CustomOverlay({position:t,content:pe,xAnchor:.5,yAnchor:1});
      kakao.maps.event.addListener(RV,"init",()=>{aimRv(RV,RVPIN,RV._tgt);msg.style.display="none";});}
    RV._tgt={lat:p.lat,lng:p.lng};RVPIN.setPosition(t);
    (function tryR(rs){
      if(!rs.length){msg.textContent="이 근처엔 로드뷰 사진이 없어요";return;}
      RVC.getNearestPanoId(t,rs[0],id=>{if(id===null)return tryR(rs.slice(1));
        RV.setPanoId(id,t);
        setTimeout(()=>{const q=RV.getPosition();if(q){aimRv(RV,RVPIN,RV._tgt);msg.style.display="none";}},700);});
    })([50,100,200]);
  });
  if(innerWidth<960)box.scrollIntoView({behavior:"smooth",block:"nearest"});
}

function pinName(p){
  let t=String(p.label||p.input||"").trim();
  if(!t||t==="현재 위치")return t||"출발";
  t=shortAddr(t);   // 맨 앞 시·도는 항상 뺌 (전북특별자치도 익산시 모현동 → 익산시 모현동)
  const w=t.split(" ");
  const isAddr=/\d/.test(t)||/(시|군|구|읍|면|동|리|로|길)$/.test(w[w.length-1]);
  if(isAddr&&w.length>2)t=w.slice(-2).join(" ");   // 주소면 끝 두 단어 (예: 누동길 23)
  return t.length>10?t.slice(0,10)+"…":t;
}
function drawMap(r){
  const el=$("#map"),o=r.order,last=o.length-1;
  RV=null;MARK=[];ALL=[];FOCUS=null;
  if(window.L){
    const m=L.map(el,{zoomControl:false,attributionControl:false});MAP=m;
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",{maxZoom:19}).addTo(m);
    const all=[];
    r.legs.forEach(l=>{if(l.path.length){L.polyline(l.path,{color:"#2f6fed",weight:5,opacity:.85}).addTo(m);all.push(...l.path);}});
    o.forEach((p,i)=>{if(i===last&&r.return_to_start)return;
      const t=i===0?"출발":i===last?"도착":i;
      MARK[i]=L.marker([p.lat,p.lng],{icon:L.divIcon({className:"",html:`<div style="background:${i===0||i===last?"#1b1d1c":"#2f6fed"};color:#fff;border:3px solid #fff;border-radius:999px;min-width:30px;height:30px;padding:0 6px;display:flex;align-items:center;justify-content:center;font:800 12px Pretendard,sans-serif;box-shadow:0 2px 6px rgba(0,0,0,.25)">${t}</div>`,iconSize:[30,30],iconAnchor:[15,15]})}).addTo(m).on("click",()=>focusPt(i));
      // 번호 위에 짧은 이름표 (장소명, 없으면 주소 끝 두 단어)
      MARK[i].bindTooltip(esc(pinName(p)),{permanent:true,direction:"top",offset:[0,-16],className:"mlab"+(i===0||i===last?" se":"")});
      all.push([p.lat,p.lng]);});
    ALL=all;m.fitBounds(all,{padding:[28,28]});
    return;
  }
  // 지도 라이브러리를 못 불러오면 간단한 그림으로 대신
  const lats=o.map(p=>p.lat),lngs=o.map(p=>p.lng),pad=30,W=el.clientWidth||340,H=el.clientHeight||240;
  const x0=Math.min(...lngs),x1=Math.max(...lngs),y0=Math.min(...lats),y1=Math.max(...lats);
  const sx=v=>pad+(v-x0)/((x1-x0)||1)*(W-2*pad),sy=v=>H-pad-(v-y0)/((y1-y0)||1)*(H-2*pad);
  let svg=`<svg width="${W}" height="${H}" xmlns="http://www.w3.org/2000/svg"><rect width="100%" height="100%" fill="#eceae3"/>`;
  svg+=`<polyline fill="none" stroke="#2f6fed" stroke-width="4" stroke-linejoin="round" stroke-linecap="round" points="${o.map(p=>sx(p.lng)+","+sy(p.lat)).join(" ")}"/>`;
  o.forEach((p,i)=>{if(i===last&&r.return_to_start)return;const t=i===0?"출발":i===last?"도착":i,c=i===0||i===last?"#1b1d1c":"#2f6fed";
    svg+=`<circle cx="${sx(p.lng)}" cy="${sy(p.lat)}" r="${i===0?19:15}" fill="${c}" stroke="#fff" stroke-width="3"/><text x="${sx(p.lng)}" y="${sy(p.lat)+4.5}" text-anchor="middle" font-size="${i===0?11:13}" font-weight="800" fill="#fff" font-family="sans-serif">${t}</text>`;});
  el.innerHTML=svg+"</svg>";
}
restoreLast();
</script>
{% endblock %}
''',
    "trip/toilet.html": r'''{% extends "trip/base.html" %}
{% from "trip/_m.html" import src, topbar with context %}
{% block title %}내 근처 화장실 · 출장 도구함{% endblock %}
{% block theme %}t-toilet{% endblock %}
{% block body %}
{{ topbar('내 근처 화장실') }}
<div class="cols"><div class="colA">
<div class="card">
  <div class="sec">조건</div>
  <div class="toggle" style="margin-top:6px" id="conds">
    <input type="checkbox" id="all" checked><label for="all">전체</label>
    <input type="checkbox" id="always"><label for="always">상시 개방</label>
    <input type="checkbox" id="bell"><label for="bell">비상벨</label>
    <input type="checkbox" id="acc"><label for="acc">장애인용</label>
  </div>
  <button class="btn main" id="find" type="button">지금 위치에서 찾기</button>
  <div id="msg"></div>
</div>
</div><div class="colB">
<div id="here" class="here" style="display:none"></div>
<div id="list"></div>
<p class="hint">반경 5km 안에서 가까운 15곳을 보여줘요.<br>문을 닫는 곳은 빼요.{% if demo %}<br>지금은 예시 3곳이에요.{% endif %}<span id="tdate">{% if toilet_date %}<br>행정안전부 화장실 자료 · {{ toilet_date }} 갱신{% endif %}</span></p>
</div></div>
<div class="big" id="big"><div class="bbox">
  <div class="sh"><div style="flex:1;min-width:0"><b id="bigT"></b><small id="bigA"></small></div><button type="button" id="bigX" aria-label="닫기">×</button></div>
  <div class="bigrv"><div id="bigRv" style="position:absolute;inset:0"></div><div class="mrmsg" id="bigMsg"></div></div>
  <button class="btn main" type="button" id="bigNav" style="margin-top:12px">길안내</button>
</div></div>
<div class="nav" id="nav"><div class="sheet">
  <div class="sh"><b id="navT"></b><button type="button" id="navX" aria-label="닫기">×</button></div>
  <p class="hint" style="margin:0 0 10px">쓰는 지도 앱을 고르세요.<br>앱이 없으면 웹으로 열려요.</p>
  <a id="navKakao" class="navb" target="_blank" rel="noopener"><span style="background:#fee500;color:#191600">K</span>카카오맵</a>
  <a id="navNaver" class="navb" target="_blank" rel="noopener"><span style="background:#03c75a;color:#fff">N</span>네이버지도</a>
  <a id="navGoogle" class="navb" target="_blank" rel="noopener"><span style="background:#4285f4;color:#fff">G</span>구글지도</a>
</div></div>
{{ src([("공중화장실","행정안전부 전국공중화장실표준데이터"),("차 시간","카카오모빌리티 길찾기"),("내 위치·로드뷰","카카오맵")]) }}
{% endblock %}
{% block script %}
{% if kakao_js_key %}<script src="https://dapi.kakao.com/v2/maps/sdk.js?appkey={{ kakao_js_key }}&autoload=false"></script>{% endif %}
<script>
const $=s=>document.querySelector(s);
const esc=t=>String(t??"").replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const km=m=>m<1000?`${m}m`:`${(m/1000).toFixed(1)}km`;
const DEMO={{ 'true' if demo else 'false' }};
const CAR='<svg viewBox="0 0 24 24" fill="currentColor"><path d="M18.92 6.01C18.72 5.42 18.16 5 17.5 5h-11c-.66 0-1.21.42-1.42 1.01L3 12v8c0 .55.45 1 1 1h1c.55 0 1-.45 1-1v-1h12v1c0 .55.45 1 1 1h1c.55 0 1-.45 1-1v-8l-2.08-5.99zM6.5 16c-.83 0-1.5-.67-1.5-1.5S5.67 13 6.5 13s1.5.67 1.5 1.5S7.33 16 6.5 16zm11 0c-.83 0-1.5-.67-1.5-1.5s.67-1.5 1.5-1.5 1.5.67 1.5 1.5-.67 1.5-1.5 1.5zM5 11l1.5-4.5h11L19 11H5z"/></svg>';
const WALK='<svg viewBox="0 0 24 24" fill="currentColor"><path d="M13.5 5.5c1.1 0 2-.9 2-2s-.9-2-2-2-2 .9-2 2 .9 2 2 2zM9.8 8.9 7 23h2.1l1.8-8 2.1 2v6h2v-7.5l-2.1-2 .6-3C14.8 12 16.8 13 19 13v-2c-1.9 0-3.5-1-4.3-2.4l-1-1.6c-.4-.6-1-1-1.7-1-.3 0-.5.1-.8.1L6 8.3V13h2V9.6l1.8-.7"/></svg>';
function search(lat,lng){
  const q=new URLSearchParams({lat,lng,always:$("#always").checked?1:0,bell:$("#bell").checked?1:0,acc:$("#acc").checked?1:0});
  fetch("/trip/api/toilets?"+q).then(r=>r.json()).then(r=>{
    done();
    if(r.here){$("#here").innerHTML=`<span class="pin"></span><div><small>내 위치</small><b>${esc(r.here)}</b></div>`;$("#here").style.display="";}
    if(r.date)$("#tdate").innerHTML="<br>행정안전부 화장실 자료 · "+esc(r.date)+" 갱신";
    if(!r.ok||!r.items.length){$("#msg").innerHTML=`<div class="err" style="margin:12px 0 0">${esc(r.message||"찾지 못했어요.")}</div>`;$("#list").innerHTML="";return;}
    $("#list").innerHTML=`<div class="card">${r.items.map(t=>`
      <div class="trow"><div class="sr-rv" data-lat="${t.lat}" data-lng="${t.lng}" data-i="${r.items.indexOf(t)}" role="button" title="로드뷰 크게 보기"><div class="sr-rv-pano"></div><div class="sr-rv-msg">로드뷰</div><div class="sr-rv-cover"></div></div>
        <div class="body"><div class="nm">${esc(t.name||"공중화장실")}</div><div class="ad">${esc(shortAddr(t.address))}</div>
          <div class="dl"><b>${km(t.distance)}</b>
            <span class="tm" title="차로">${CAR}${t.car_real?"":"약 "}${t.car_min}분</span>
            <span class="tm" title="걸어서">${WALK}${t.walk_min}분</span></div>
          <div class="chips">${t.open==="상시"?'<span class="chip ok">상시 개방</span>':(t.open?`<span class="chip">${esc(t.open_label)}</span>`:"")}
          ${t.bell?'<span class="chip">비상벨</span>':""}${t.accessible?'<span class="chip">장애인</span>':""}${upd(t.updated)}</div></div>
        <button class="btn sm" type="button" data-i="${r.items.indexOf(t)}">길안내</button></div>`).join("")}</div>`;
    ITEMS=r.items;
    $("#list").querySelectorAll("button[data-i]").forEach(b=>b.onclick=()=>openNav(ITEMS[+b.dataset.i]));
    $("#list").querySelectorAll(".sr-rv").forEach(b=>b.onclick=()=>openBig(ITEMS[+b.dataset.i]));
    watchRv();
  }).catch(()=>{done();$("#msg").innerHTML='<div class="err" style="margin:12px 0 0">연결에 실패했어요.</div>';});
}
/* 화장실마다 자료 마지막 수정 연월. 2년 넘은 자료는 주황색으로 (현장 확인 필요) */
function upd(u){if(!u)return"";const [y,m]=u.split("-").map(Number),now=new Date(),old=(now.getFullYear()-y)*12+(now.getMonth()+1-m)>=24;
  return `<span class="chip upd${old?" old":""}" title="이 화장실 정보를 지자체가 마지막으로 고친 때">${y}.${String(m).padStart(2,"0")} 자료</span>`;}
/* 작은 로드뷰: 안전로드 검색결과와 같은 방식 (100m 안 로드뷰 → 화장실 쪽으로 카메라 회전, 화면 밖이면 내림) */
let rvObs=null;
function initRv(box){
  const pano=box.querySelector(".sr-rv-pano"),msg=box.querySelector(".sr-rv-msg"),lat=+box.dataset.lat,lng=+box.dataset.lng;
  if(!(window.kakao&&kakao.maps)){msg.textContent="로드뷰 없음";return;}
  kakao.maps.load(()=>{
    try{
      const cl=new kakao.maps.RoadviewClient(),rv=new kakao.maps.Roadview(pano),pos=new kakao.maps.LatLng(lat,lng);
      cl.getNearestPanoId(pos,100,id=>{
        if(id===null){msg.textContent="로드뷰 없음";return;}
        msg.style.display="none";rv.setPanoId(id,pos);
        // 작은 로드뷰에도 화장실 위치 화살표 (글자 없이 작게)
        const pin=document.createElement("div");pin.className="rvpin sm";pin.innerHTML="<i></i>";
        const ov=new kakao.maps.CustomOverlay({position:pos,content:pin,xAnchor:.5,yAnchor:1});
        kakao.maps.event.addListener(rv,"init",()=>{try{const p=rv.getPosition();if(!p)return;
          ov.setMap(rv);
          let vp=null;try{vp=rv.getProjection().viewpointFromCoords(ov.getPosition(),ov.getAltitude());}catch(e){}
          rv.setViewpoint(vp?{pan:vp.pan,tilt:vp.tilt,zoom:0}:{pan:bearingTo(p,lat,lng),tilt:0,zoom:0});}catch(e){}});
      });
    }catch(e){msg.textContent="로드뷰 없음";}
  });
}
function watchRv(){
  const boxes=document.querySelectorAll("#list .sr-rv");
  if(rvObs)rvObs.disconnect();
  if(!("IntersectionObserver" in window)){boxes.forEach(initRv);return;}
  rvObs=new IntersectionObserver(ents=>ents.forEach(en=>{
    const b=en.target;
    if(en.isIntersecting&&b.dataset.loaded!=="1"){b.dataset.loaded="1";initRv(b);}
    else if(!en.isIntersecting&&b.dataset.loaded==="1"){b.dataset.loaded="0";b.querySelector(".sr-rv-pano").innerHTML="";
      const m=b.querySelector(".sr-rv-msg");m.style.display="";m.textContent="로드뷰";}
  }),{rootMargin:"160px 0px"});
  boxes.forEach(b=>rvObs.observe(b));
}
/* 조건: 아무것도 안 고르면 '전체'. 하나라도 고르면 '전체'는 꺼짐 */
let ITEMS=[];
const CONDS=["always","bell","acc"];
$("#all").onchange=()=>{if($("#all").checked)CONDS.forEach(id=>$("#"+id).checked=false);else if(!CONDS.some(id=>$("#"+id).checked))$("#all").checked=true;};
CONDS.forEach(id=>$("#"+id).addEventListener("change",()=>{$("#all").checked=!CONDS.some(c=>$("#"+c).checked);}));

/* 길안내: 카카오맵·네이버지도·구글지도 중 고르기 (앱이 없으면 웹으로 열림) */
function openNav(t){
  const nm=t.name||"공중화장실",q=encodeURIComponent(nm),addr=encodeURIComponent(t.address||nm);
  $("#navT").textContent=nm;
  $("#navKakao").href=`https://map.kakao.com/link/to/${q},${t.lat},${t.lng}`;
  $("#navNaver").href=`https://map.naver.com/p/search/${addr}`;
  $("#navGoogle").href=`https://www.google.com/maps/dir/?api=1&destination=${t.lat},${t.lng}&travelmode=walking`;
  $("#nav").classList.add("on");
}
document.addEventListener("click",e=>{if(e.target.id==="nav"||e.target.id==="navX")$("#nav").classList.remove("on");});
/* 작은 로드뷰를 누르면 큰 로드뷰 (돌려 볼 수 있음) */
let BIG=null,BIGC=null;
function distM(a1,o1,a2,o2){const R=Math.PI/180,x=Math.sin((a2-a1)*R/2)**2+Math.cos(a1*R)*Math.cos(a2*R)*Math.sin((o2-o1)*R/2)**2;return 12742000*Math.asin(Math.sqrt(x));}
function bearingTo(p,lat,lng){const R=Math.PI/180,f1=p.getLat()*R,f2=lat*R,dl=(lng-p.getLng())*R;
  const y=Math.sin(dl)*Math.cos(f2),x=Math.cos(f1)*Math.sin(f2)-Math.sin(f1)*Math.cos(f2)*Math.cos(dl);
  return ((Math.atan2(y,x)*180/Math.PI)+360)%360;}
function openBig(t,noHist){
  $("#bigT").textContent=t.name||"공중화장실";$("#bigA").textContent=shortAddr(t.address||"")+(t.updated?` · ${t.updated.replace("-",".")} 자료`:"");
  $("#bigNav").onclick=()=>{closeBig(true);openNav(t);};
  $("#big").classList.add("on");
  // 폰 뒤로가기를 누르면 창만 닫히게 기록을 하나 쌓음
  if(!noHist)history.pushState({tripBig:1},"");
  const msg=$("#bigMsg");msg.style.display="";msg.textContent="로드뷰 불러오는 중";
  if(!(window.kakao&&kakao.maps)){msg.textContent="로드뷰를 불러오지 못했어요";return;}
  kakao.maps.load(()=>{
    // 작은 로드뷰와 똑같이: 매번 새로 만들고, 사진이 다 열린 뒤(init) 화장실 쪽으로 카메라를 돌림
    const box=$("#bigRv");box.innerHTML="";
    const rv=new kakao.maps.Roadview(box),cl=new kakao.maps.RoadviewClient(),pos=new kakao.maps.LatLng(t.lat,t.lng);
    // 화장실 위치에 핀(이름표 + 사진 찍힌 곳에서 거리). 로드뷰를 돌리면 건물에 붙어서 같이 움직임
    const pin=document.createElement("div");pin.className="rvpin";
    const ov=new kakao.maps.CustomOverlay({position:pos,content:pin,xAnchor:.5,yAnchor:1});
    const aim=()=>{try{const p=rv.getPosition();if(!p)return;
      const d=Math.round(distM(p.getLat(),p.getLng(),t.lat,t.lng));
      pin.innerHTML=`<b>화장실${d>=10?` · ${d<1000?d+"m":(d/1000).toFixed(1)+"km"}`:""}</b><i></i>`;
      ov.setMap(rv);
      let vp=null;try{vp=rv.getProjection().viewpointFromCoords(ov.getPosition(),ov.getAltitude());}catch(e){}
      rv.setViewpoint(vp?{pan:vp.pan,tilt:vp.tilt,zoom:0}:{pan:bearingTo(p,t.lat,t.lng),tilt:0,zoom:0});
      msg.style.display="none";}catch(e){}};
    kakao.maps.event.addListener(rv,"init",aim);
    (function tryR(rs){
      if(!rs.length){msg.textContent="이 근처엔 로드뷰 사진이 없어요";return;}
      cl.getNearestPanoId(pos,rs[0],id=>{if(id===null)return tryR(rs.slice(1));rv.setPanoId(id,pos);});
    })([100,200]);
  });
}
function closeBig(viaCode){
  if(!$("#big").classList.contains("on"))return;
  if(history.state&&history.state.tripBig)history.back();   // popstate에서 닫힘
  else $("#big").classList.remove("on");
}
window.addEventListener("popstate",()=>{$("#big").classList.remove("on");});
document.addEventListener("click",e=>{if(e.target.id==="big"||e.target.id==="bigX")closeBig();});
function done(){const b=$("#find");b.disabled=false;b.textContent="지금 위치에서 찾기";}
$("#find").onclick=()=>{
  $("#msg").innerHTML="";const b=$("#find");b.disabled=true;b.innerHTML='<span class="spin"></span> 위치 확인 중';
  if(!navigator.geolocation){ if(DEMO) return search(35.1395,126.7935); done(); $("#msg").innerHTML='<div class="err" style="margin:12px 0 0">위치를 쓸 수 없는 기기예요.</div>'; return;}
  navigator.geolocation.getCurrentPosition(p=>search(p.coords.latitude,p.coords.longitude),
    ()=>{ if(DEMO) return search(35.1395,126.7935); done(); $("#msg").innerHTML='<div class="err" style="margin:12px 0 0">위치를 가져오지 못했어요. 위치 권한을 켜주세요.</div>'; },
    {enableHighAccuracy:true,timeout:10000,maximumAge:0});
};
</script>
{% endblock %}
''',
}

# ---------- 5. 큰 글씨 대화 · 6. 낱말카드 ----------
#   - 큰 글씨 대화: 귀가 어두운 분께 문장을 화면 가득 크게 보여주고, 예/아니요/모르겠어요로 답을 받음
#   - 쓴 글·손글씨는 서버로 보내지도, 저장하지도 않음 (직원이 추가한 '내 문장'만 그 기기에 남음)
#   - 낱말카드: 자리만 만들어 둠 (내용은 나중에)
TRIP_BOARD_PHRASES = [  # (탭 이름, 문장들) — 문장을 고치거나 더하려면 여기만 바꾸면 됨
    ("인사", ["안녕하세요", "국민건강보험공단에서 왔어요", "요양 등급 때문에 확인하러 왔어요",
            "잠깐 앉아서 이야기해도 될까요?", "천천히 말씀해 주세요", "다시 한 번 말씀해 주세요",
            "글로 써서 보여 드릴게요"]),
    ("생활", ["혼자 사세요?", "같이 사는 가족이 있어요?", "식사는 잘 하세요?", "약은 잘 드세요?",
            "밤에 잠은 잘 주무세요?", "혼자 화장실 가실 수 있어요?", "혼자 씻으실 수 있어요?",
            "최근에 넘어진 적 있어요?"]),
    ("몸 상태", ["어디가 제일 불편하세요?", "아픈 곳을 손으로 가리켜 주세요", "많이 아프세요?",
              "다니는 병원이 있어요?", "걷기가 불편하세요?", "잘 안 들리세요?", "잘 안 보이세요?"]),
    ("서류", ["신분증 보여 주세요", "여기에 이름 써 주세요", "여기에 도장 찍어 주세요",
            "이 서류는 잘 보관하세요", "보호자 연락처가 필요해요"]),
    ("마무리", ["오늘 확인은 끝났어요", "결과는 우편으로 가요", "궁금하면 공단에 전화하세요\n1577-1000",
              "고생 많으셨어요", "건강하세요"]),
]


@trip_bp.get("/board", endpoint="board_page")
def trip_board_page():
    return render_template("trip/board.html", phrases=TRIP_BOARD_PHRASES)


@trip_bp.get("/cards", endpoint="cards_page")
def trip_cards_page():
    return render_template("trip/cards.html")


TRIP_CSS += r'''
/* 5. 큰 글씨 대화 · 6. 낱말카드 */
:root{--board:#c23a63;--board-bg:#fbe9ef;--cards:#4a6b8a;--cards-bg:#e8eef4}
.tile.board .ico{background:var(--board-bg);color:var(--board)}
/* 홈: 폰에서 메뉴 6개가 한 화면에 들어오게. 원래 여백·비율은 두고, 카드 높이만 화면 높이에 맞춰 줄임
   (카드 안은 아이콘 바로 아래 제목, 큰 제목과 카드 사이는 넓게) */
@media (max-width:959px){
  .t-home .hello{margin-bottom:30px}
  .t-home .tiles{gap:10px;grid-auto-rows:1fr}
  .t-home .tile{min-height:0;justify-content:flex-start;padding:16px}
  .t-home .tile .t{margin:14px 0 3px}
  .t-home .tile .d{display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
}
@media (max-width:959px) and (max-height:760px){
  .t-home .tile .ico{width:40px;height:40px;border-radius:13px}
  .t-home .tile .ico svg{width:22px;height:22px}
  .t-home .tile .t{font-size:16px;margin:10px 0 2px}
  .t-home .tile .d{font-size:12px}
  .t-home .tile.cards .d{display:none}
}
.tile.cards .ico{background:var(--cards-bg);color:var(--cards)}
@media (min-width:960px){.tiles{grid-template-columns:repeat(3,1fr)}}
.t-board .btn.main{background:var(--board)}
.t-board .ctabs button.on{background:var(--board);border-color:var(--board);color:#fff}
.t-board textarea{width:100%;min-height:110px;border:1px solid var(--line);border-radius:13px;padding:12px 14px;font-family:inherit;font-size:20px;font-weight:600;line-height:1.45;background:#fbfaf7;color:var(--ink);resize:vertical}
.t-board textarea:focus{outline:none;border-color:var(--ink);background:#fff}
.pgrid{display:grid;grid-template-columns:1fr 1fr;gap:8px}
.pbtn{position:relative;min-height:58px;text-align:left;padding:10px 12px;border:1px solid var(--line);border-radius:13px;background:#fff;font-family:inherit;font-size:15px;font-weight:600;line-height:1.35;color:var(--ink);cursor:pointer;white-space:pre-line}
.pbtn:active{background:var(--board-bg)}
.pbtn .x{position:absolute;top:2px;right:2px;width:30px;height:30px;border:none;background:none;color:var(--muted);font-size:18px;cursor:pointer}
.pbtn.my{padding-right:30px}
.wrow{display:flex;gap:8px;margin-top:10px}.wrow .btn{flex:1;height:50px}
.btn.mic{color:var(--board);border-color:var(--board)}.btn.wclr{color:var(--sub)}
.btn.mic.on{background:var(--board);color:#fff}
.myadd{display:flex;gap:8px;margin-top:10px}
.myadd input{flex:1}
/* 크게 보기 화면 */
.pd{display:none;position:fixed;inset:0;z-index:60;background:#fff;color:#111;flex-direction:column}
.pd.on{display:flex}
.pd.hc{background:#000;color:#ffe600}
.pd-face{flex:1;min-height:0;display:flex;flex-direction:column;padding:16px 14px 10px;transition:transform .25s}
.pd.flip .pd-face{transform:rotate(180deg)}
.pd-txt{flex:1;min-height:0;display:flex;align-items:center;justify-content:center;text-align:center;overflow:hidden;cursor:pointer}
.pd-txt span{display:inline-block;max-width:100%;font-weight:800;line-height:1.25;letter-spacing:-0.02em;white-space:pre-line;word-break:keep-all;overflow-wrap:normal}
.pd-txt.ans span{color:#fff;padding:.1em .5em;border-radius:.25em}
.pd-txt.ans.yes span{background:#13863f}.pd-txt.ans.no span{background:#c0262d}.pd-txt.ans.dk span{background:#6b6f72}
.pd-ans{display:none;grid-template-columns:1fr 1fr 1fr;gap:10px;margin-top:10px}
.pd-ans button{height:84px;border:none;border-radius:18px;color:#fff;font-family:inherit;font-size:28px;font-weight:800;line-height:1;cursor:pointer}
.pd-ans .yes{background:#13863f}.pd-ans .no{background:#c0262d}.pd-ans .dk{background:#6b6f72;font-size:20px;letter-spacing:-0.04em}
.pd-pad{display:none;flex:1;min-height:0;margin:16px 14px 10px;border:2px dashed #c9c6bd;border-radius:18px;touch-action:none;background:#fff}
.pd.hc .pd-pad{background:#000;border-color:#555}
.pd.drawing .pd-face{display:none}.pd.drawing .pd-pad{display:block}
.pd-pad{transition:transform .25s}.pd.flip .pd-pad{transform:rotate(180deg)}
.pd-tools{display:flex;gap:8px;padding:8px 14px calc(12px + env(safe-area-inset-bottom));border-top:1px solid #e7e4dc;background:#f4f2ec}
.pd.hc .pd-tools{background:#111;border-color:#333}
.pd-tools button{flex:1;height:50px;border:1px solid #d9d6cd;border-radius:13px;background:#fff;color:#1b1d1c;font-family:inherit;font-size:14px;font-weight:700;line-height:1.2;cursor:pointer;padding:0 4px}
.pd-tools button.on{background:#1b1d1c;color:#fff;border-color:#1b1d1c}
.pd.hc .pd-tools button{background:#222;color:#ffe600;border-color:#444}.pd.hc .pd-tools button.on{background:#ffe600;color:#000;border-color:#ffe600}
.pd.answers .pd-ans{display:grid}.pd.drawing #tAns{display:none}
.pd-zoom{position:absolute;top:calc(10px + env(safe-area-inset-top));right:10px;z-index:3;display:flex;gap:8px}
.pd-zoom button{width:48px;height:48px;border-radius:50%;border:1px solid #d9d6cd;background:rgba(255,255,255,.92);color:#1b1d1c;font-family:inherit;font-size:28px;font-weight:700;line-height:1;cursor:pointer;display:flex;align-items:center;justify-content:center;padding:0}
.pd-zoom button:disabled{opacity:.3}
.pd.hc .pd-zoom button{background:#222;color:#ffe600;border-color:#444}
.pd.drawing .pd-zoom{display:none}
.pd-face{padding-top:66px}
.pd-tools .clr{display:none}.pd.drawing .pd-tools .clr{display:block}
@media (min-width:960px){.t-board .wrap,.t-cards .wrap{max-width:820px;margin-left:auto;margin-right:auto}.t-board .ctabs button{font-size:15px;padding:9px 14px}.pd-tools{justify-content:center}.pd-tools button{flex:0 1 160px;height:54px;font-size:16px}.pd-zoom button{width:56px;height:56px}.pbtn{font-size:17px;min-height:64px}.pgrid{grid-template-columns:1fr 1fr 1fr}.pd-ans button{height:110px;font-size:40px}.pd-ans .dk{font-size:30px}}
'''


TRIP_TEMPLATES["trip/board.html"] = r'''{% extends "trip/base.html" %}
{% from "trip/_m.html" import topbar with context %}
{% block title %}큰 글씨 대화 · 출장 도구함{% endblock %}
{% block theme %}t-board{% endblock %}
{% block body %}
{{ topbar('큰 글씨 대화') }}
<div class="card">
  <label class="l" for="w">보여줄 말</label>
  <textarea id="w" placeholder="여기에 쓰거나, 아래 버튼을 눌러 말하세요"></textarea>
  <div class="wrow">
  <button class="btn mic" type="button" id="mic" hidden><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5.5 11a6.5 6.5 0 0 0 13 0M12 17.5V21"/></svg><span>말로 입력</span></button>
  <button class="btn wclr" type="button" id="wClr">지우기</button>
  </div>
  <button class="btn main" type="button" id="showW">크게 보여주기</button>
  <p class="hint" id="wHint">쓴 글은 저장하지 않아요.</p>
</div>

<div class="card">
  <div class="sec">자주 쓰는 말</div>
  <div class="ctabs" id="tabs"></div>
  <div class="pgrid" id="grid"></div>
  <div class="myadd" id="myadd" style="display:none">
    <input type="text" id="myIn" maxlength="60" placeholder="내 문장 추가">
    <button class="btn" type="button" id="myBtn">추가</button>
  </div>
  <p class="hint" id="myHint" style="display:none">내 문장은 이 기기에만 남아요.<br>이름·주소·전화번호는 넣지 마세요.</p>
</div>
<p class="note">누르면 화면 가득 크게 보여요.<br>어르신이 버튼으로 답하게 하려면 큰 화면에서 [답 버튼]을 켜세요.</p>

<div class="pd" id="pd">
  <div class="pd-zoom"><button type="button" id="zOut" aria-label="글자 작게">−</button><button type="button" id="zIn" aria-label="글자 크게">+</button></div>
  <div class="pd-face">
    <div class="pd-txt" id="txt"><span id="txtS"></span></div>
    <div class="pd-ans">
      <button type="button" class="yes" data-a="yes">예</button>
      <button type="button" class="no" data-a="no">아니요</button>
      <button type="button" class="dk" data-a="dk">모르겠어요</button>
    </div>
  </div>
  <canvas class="pd-pad" id="pad"></canvas>
  <div class="pd-tools">
    <button type="button" id="tClose">닫기</button>
    <button type="button" id="tFlip">뒤집기</button>
    <button type="button" id="tHc">고대비</button>
    <button type="button" id="tPad">손글씨</button>
    <button type="button" id="tAns">답 버튼</button>
    <button type="button" id="tClr" class="clr">지우기</button>
  </div>
</div>
<script type="application/json" id="phr">{{ phrases|tojson }}</script>
{% endblock %}
{% block script %}
{% raw %}
<script>
(function(){
const $=s=>document.querySelector(s);
const PH=JSON.parse($("#phr").textContent), MYKEY="trip_board_my", MYTAB="내 문장";
const PII=/\d{6,}|\d{2,4}[-\s.]\d{3,4}[-\s.]\d{4}/;
let tab=0, lock=null;

function loadMy(){try{const a=JSON.parse(localStorage.getItem(MYKEY)||"[]");return Array.isArray(a)?a.filter(x=>typeof x==="string"):[];}catch(e){return [];}}
function saveMy(a){try{localStorage.setItem(MYKEY,JSON.stringify(a.slice(0,30)));}catch(e){}}

function tabs(){
  const names=PH.map(p=>p[0]).concat([MYTAB]);
  $("#tabs").innerHTML="";
  names.forEach((n,i)=>{const b=document.createElement("button");b.type="button";b.textContent=n;
    if(i===tab)b.className="on";b.onclick=()=>{tab=i;tabs();grid();};$("#tabs").appendChild(b);});
}
function grid(){
  const my=tab===PH.length, list=my?loadMy():PH[tab][1], g=$("#grid");
  g.innerHTML="";
  $("#myadd").style.display=my?"flex":"none";$("#myHint").style.display=my?"block":"none";
  if(my&&!list.length){g.innerHTML='<p class="hint" style="grid-column:1/-1;margin:0">자주 쓰는 말을 추가해 두세요.</p>';return;}
  list.forEach((t,i)=>{
    const b=document.createElement("button");b.type="button";b.className="pbtn"+(my?" my":"");b.textContent=t;
    b.onclick=()=>show(t);
    if(my){const x=document.createElement("button");x.type="button";x.className="x";x.textContent="×";x.setAttribute("aria-label","지우기");
      x.onclick=e=>{e.stopPropagation();const a=loadMy();a.splice(i,1);saveMy(a);grid();};b.appendChild(x);}
    g.appendChild(b);
  });
}
$("#myBtn").onclick=()=>{
  const v=$("#myIn").value.trim();if(!v)return;
  if(PII.test(v)){alertLine("숫자가 긴 내용(전화·주민번호 등)은 저장할 수 없어요.");return;}
  const a=loadMy();if(!a.includes(v))a.unshift(v);saveMy(a);$("#myIn").value="";grid();
};
$("#myIn").addEventListener("keydown",e=>{if(e.key==="Enter"){e.preventDefault();$("#myBtn").click();}});
function alertLine(m){const h=$("#myHint");h.style.display="block";h.style.color="var(--bad)";h.textContent=m;
  setTimeout(()=>{h.style.color="";h.innerHTML="내 문장은 이 기기에만 남아요.<br>이름·주소·전화번호는 넣지 마세요.";},3000);}

/* 크게 보기 */
const pd=$("#pd"), txt=$("#txt"), sp=$("#txtS"), zIn=$("#zIn"), zOut=$("#zOut"), ZKEY="trip_board_zoom", ZMIN=-3, ZMAX=6;
let zoom=0;try{zoom=parseInt(sessionStorage.getItem(ZKEY)||"0",10)||0;}catch(e){}  /* 탭을 닫기 전까지 유지 */
function setZoom(z){zoom=Math.max(ZMIN,Math.min(ZMAX,z));try{sessionStorage.setItem(ZKEY,String(zoom));}catch(e){}fit();}
let capZ=ZMAX;
zIn.onclick=()=>{if(!zIn.disabled)setZoom(zoom+1);};zOut.onclick=()=>setZoom(Math.min(zoom,capZ)-1);  /* 최대에서 −를 누르면 바로 한 단계 작아지게 */
let cur="";
function fit(){
  if(!pd.classList.contains("on")||pd.classList.contains("drawing"))return;
  const W=txt.clientWidth, H=txt.clientHeight;
  if(txt.classList.contains("ans")){  /* 답: 글자 수로 크기 계산 (좌우 여백 포함, 상자 밖으로 안 나가게) */
    const n=[...sp.textContent].length;sp.style.fontSize=Math.floor(Math.min(W*0.82/(n+1),H*0.4))+"px";return;}
  /* 기본(zoom 0) = 단어를 끊지 않고 화면에 맞는 최대 크기.
     [+]로 더 키우면 단어 안에서도 줄을 바꿔 화면 안에서 더 크게 (끊어서 맞는 최대 크기까지) */
  function best(wb){sp.style.wordBreak=wb;let lo=16, hi=Math.floor(Math.max(24,Math.min(H,W)));
    while(hi-lo>1){const m=(lo+hi)>>1;sp.style.fontSize=m+"px";
      if(sp.scrollWidth<=sp.clientWidth+1&&sp.offsetWidth<=W&&sp.offsetHeight<=H)lo=m;else hi=m;}
    return Math.floor(lo*0.97);}
  const S1=best("keep-all"), S2=Math.max(S1,best("break-all")), t=Math.round(S1*Math.pow(1.25,zoom));
  if(t<=S1){sp.style.wordBreak="keep-all";sp.style.fontSize=t+"px";}
  else{sp.style.wordBreak="break-all";sp.style.fontSize=Math.min(t,S2)+"px";}
  capZ=Math.max(0,Math.ceil(Math.log(S2/S1)/Math.log(1.25)-1e-9));  /* 이 문장에서 더 커지지 않는 단계 */
  zIn.disabled=t>=S2;zOut.disabled=zoom<=ZMIN;
}
function setText(t,cls){sp.textContent=t;txt.className="pd-txt"+(cls?" ans "+cls:"");fit();}
if(document.fonts&&document.fonts.ready)document.fonts.ready.then(fit);
async function wake(){try{if("wakeLock" in navigator)lock=await navigator.wakeLock.request("screen");}catch(e){lock=null;}}
function show(t){
  t=String(t||"").trim();if(!t)return;cur=t;
  const was=pd.classList.contains("on");
  pd.classList.add("on");pd.classList.remove("drawing");$("#tPad").classList.remove("on");
  document.body.style.overflow="hidden";
  setText(t);wake();
  if(!was)history.pushState({pd:1},"");
}
function hide(){pd.classList.remove("on");document.body.style.overflow="";try{lock&&lock.release();}catch(e){}lock=null;}
/* 말로 입력: 브라우저 음성인식이 되면 버튼을 보여줌 (앱 화면 등 안 되는 곳은 키보드 마이크 안내) */
(function(){
  const SR=window.SpeechRecognition||window.webkitSpeechRecognition, mic=$("#mic"), w=$("#w");
  if(!SR){w.placeholder="여기에 쓰거나, 키보드의 마이크로 말하세요";$("#wHint").innerHTML="키보드의 마이크 버튼으로 말해도 글자로 바뀌어요.<br>쓴 글은 저장하지 않아요.";return;}
  mic.hidden=false;
  $("#wHint").innerHTML="말로 입력은 음성인식 서비스(구글 등)를 거쳐요.<br>이름·주민번호는 말하지 마세요. 쓴 글은 저장하지 않아요.";
  let rec=null, base="";
  $("#wClr").addEventListener("click",()=>{if(rec){try{rec.abort();}catch(e){}}});
  /* 시작·종료 소리: 케어내비 사례검색 음성입력(playBeep)과 같은 소리 (시작 880Hz, 종료 660Hz, 0.18초) */
  function playBeep(type){
    try{
      const AC=window.AudioContext||window.webkitAudioContext;if(!AC)return;
      const ctx=new AC(), osc=ctx.createOscillator(), gain=ctx.createGain();
      osc.type="sine";osc.frequency.value=(type==="start")?880:660;
      gain.gain.setValueAtTime(0.001,ctx.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.7,ctx.currentTime+0.01);
      gain.gain.exponentialRampToValueAtTime(0.001,ctx.currentTime+0.18);
      osc.connect(gain);gain.connect(ctx.destination);
      osc.start();osc.stop(ctx.currentTime+0.18);
    }catch(e){}
  }
  function stop(){if(rec)playBeep("end");mic.classList.remove("on");mic.querySelector("span").textContent="말로 입력";rec=null;}
  mic.onclick=()=>{
    if(rec){try{rec.stop();}catch(e){}return;}
    try{rec=new SR();}catch(e){return;}
    /* 안드로이드 크롬은 연속 듣기(continuous)에서 같은 말을 반복해서 돌려주는 문제가 있어
       한 번 말하면 멈추게 하고, 마지막 결과만 씀. 더 말하려면 버튼을 다시 누르면 뒤에 이어 붙음 */
    rec.lang="ko-KR";rec.interimResults=true;rec.continuous=false;rec.maxAlternatives=1;
    base=w.value.trim()?w.value.trim()+" ":"";
    rec.onresult=e=>{const r=e.results[e.results.length-1];w.value=base+String(r[0].transcript||"").trim();};
    rec.onerror=e=>{if(e.error==="not-allowed")$("#wHint").textContent="마이크 권한을 허용해 주세요.";};
    rec.onend=stop;
    mic.classList.add("on");mic.querySelector("span").textContent="듣는 중 · 말이 끝나면 멈춰요";
    playBeep("start");
    try{rec.start();}catch(e){stop();}
  };
})();
$("#wClr").onclick=()=>{$("#w").value="";};
$("#showW").onclick=()=>{const v=$("#w").value;if(!v.trim()){$("#w").focus();return;}show(v);};
document.querySelectorAll(".pd-ans button").forEach(b=>{b.onclick=()=>setText(b.textContent,b.dataset.a);});
txt.onclick=()=>{if(txt.classList.contains("ans"))setText(cur);};
$("#tClose").onclick=()=>history.back();
window.addEventListener("popstate",hide);
$("#tFlip").onclick=()=>{pd.classList.toggle("flip");$("#tFlip").classList.toggle("on");};
$("#tHc").onclick=()=>{pd.classList.toggle("hc");$("#tHc").classList.toggle("on");drawColor();};
window.addEventListener("resize",()=>{fit();sizePad();});
document.addEventListener("visibilitychange",()=>{if(document.visibilityState==="visible"&&pd.classList.contains("on"))wake();});

/* 손글씨 (어르신이 손가락으로 쓰기, 저장 안 함) */
const pad=$("#pad"), ctx=pad.getContext("2d");let drawing=false, last=null;
function drawColor(){ctx.strokeStyle=pd.classList.contains("hc")?"#ffe600":"#111";}
function sizePad(){
  if(!pd.classList.contains("drawing"))return;
  const r=pad.getBoundingClientRect(), d=window.devicePixelRatio||1;
  pad.width=Math.round(r.width*d);pad.height=Math.round(r.height*d);
  ctx.setTransform(d,0,0,d,0,0);ctx.lineWidth=6;ctx.lineCap="round";ctx.lineJoin="round";drawColor();
}
$("#tAns").onclick=()=>{const on=pd.classList.toggle("answers");$("#tAns").classList.toggle("on",on);if(!on&&txt.classList.contains("ans"))setText(cur);else fit();};
$("#tPad").onclick=()=>{
  const on=pd.classList.toggle("drawing");$("#tPad").classList.toggle("on",on);
  if(on)sizePad();else fit();
};
$("#tClr").onclick=()=>ctx.clearRect(0,0,pad.width,pad.height);
function pt(e){const r=pad.getBoundingClientRect(),x=e.clientX-r.left,y=e.clientY-r.top;
  return pd.classList.contains("flip")?{x:r.width-x,y:r.height-y}:{x:x,y:y};}  /* 뒤집힌 상태면 좌표도 뒤집음 */
pad.addEventListener("pointerdown",e=>{drawing=true;last=pt(e);pad.setPointerCapture(e.pointerId);
  ctx.beginPath();ctx.arc(last.x,last.y,3,0,Math.PI*2);ctx.fillStyle=ctx.strokeStyle;ctx.fill();});
pad.addEventListener("pointermove",e=>{if(!drawing)return;const p=pt(e);
  ctx.beginPath();ctx.moveTo(last.x,last.y);ctx.lineTo(p.x,p.y);ctx.stroke();last=p;});
["pointerup","pointercancel","pointerleave"].forEach(n=>pad.addEventListener(n,()=>{drawing=false;}));

tabs();grid();
})();
</script>
{% endraw %}
{% endblock %}
'''


TRIP_TEMPLATES["trip/cards.html"] = r'''{% extends "trip/base.html" %}
{% from "trip/_m.html" import topbar with context %}
{% block title %}통합판정 낱말카드 · 출장 도구함{% endblock %}
{% block theme %}t-cards{% endblock %}
{% block body %}
{{ topbar('통합판정 낱말카드') }}
{% endblock %}
'''


app.jinja_loader = _TripChoiceLoader([app.jinja_loader, _TripDictLoader(TRIP_TEMPLATES)])
app.register_blueprint(trip_bp)
# ===============  출장 도구함 모듈 끝  ============================================


if __name__ == "__main__":



    port = int(os.environ.get("PORT", 5000))



    app.run(host="0.0.0.0", port=port, debug=False)