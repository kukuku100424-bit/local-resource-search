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

EXTRA_INFO = {'공중화장실': ['개방시간', '비상벨', '장애인화장실'], '공영주차장': ['요금', '요금상세', '운영평일', '운영토요일', '운영공휴일'], '민영주차장': ['요금', '요금상세', '운영평일', '운영토요일', '운영공휴일'], '자동심장충격기': ['설치장소', '사용시간', '일요일사용'], '교통사고위험지역': ['사고건수', '보행자사고', '야간사고', '중상이상']}

EXTRA_INFO_COLS = ['개방시간', '비상벨', '장애인화장실', '요금', '요금상세', '운영평일', '운영토요일', '운영공휴일', '설치장소', '사용시간', '일요일사용', '사고건수', '보행자사고', '야간사고', '중상이상']





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

    # 항목별 추가 정보는 값이 있는 것만 보냄 (전송량 절약)

    for _c in (EXTRA_INFO.get(category, []) if feature_detail_on() else []):

        _v = re.sub(r"\.0$", "", safe_str(row.get(_c, "")))   # 엑셀이 3 → 3.0 으로 읽는 것 정리

        if _v and _v != "0":

            d[_c] = _v

    return d





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
.mobile-result-item.sr-rich{display:flex;align-items:center;gap:12px;padding:10px 12px!important;}
.mobile-result-item.sr-rich::before{display:none;}
.sr-rv{position:relative;flex-shrink:0;width:84px;height:62px;border-radius:10px;overflow:hidden;background:#eef1f5;}
.sr-rv-pano{position:absolute;left:0;top:0;width:336px;height:248px;transform:scale(.25);transform-origin:0 0;}
.sr-rv-msg{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;text-align:center;padding:4px;font-size:10px;line-height:1.3;color:#94a3b8;z-index:2;}
.sr-rv-cover{position:absolute;inset:0;z-index:3;}
.sr-rv-tag{position:absolute;left:4px;top:4px;z-index:3;width:10px;height:10px;border-radius:50%;border:2px solid #fff;box-shadow:0 1px 3px rgba(0,0,0,.25);}
.sr-txt{flex:1;min-width:0;}
.sr-txt b{display:block;}
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
        <div class="sr-hero-t">출장 지역의 위험구간과 편의시설을 한눈에 확인합니다.</div>
        <div class="sr-hero-s">화장실 · 주차장 · AED · 결빙 · 교통사고 지역 확인</div>
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
    _t.innerHTML = '<div class="sr-ld"><div class="sr-radar"><i></i><i></i><i></i><b><svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 21s-7-6.2-7-11.5a7 7 0 0 1 14 0C19 14.8 12 21 12 21z"/><circle cx="12" cy="9.5" r="2.5"/></svg></b></div><div class="sr-ld-t">내 위치를 찾고 있어요</div><div class="sr-ld-s">처음에는 몇 초 걸릴 수 있어요</div></div>';
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
  if(srRvObserver) srRvObserver.disconnect();
  srRvObserver = ("IntersectionObserver" in window) ? new IntersectionObserver(function(ents){
    ents.forEach(function(en){
      if(!en.isIntersecting) return;
      const box = en.target;
      srRvObserver.unobserve(box);
      initRoadview(box.dataset.pano, +box.dataset.lat, +box.dataset.lng, box.dataset.gubun);
    });
  }, {root: list, rootMargin: "120px 0px"}) : null;
  items.forEach(function(el){
    if(!el.dataset.lat) return;
    const b = el.querySelector("b");
    const label = b ? b.innerHTML : "";
    const old = el.querySelector(".mobile-result-distance");
    const dist = old ? old.textContent.trim() : "";
    const addr = el.dataset.addr || "";
    const id = "srrv_" + (++srRvSeq);
    const area = el.innerHTML.split("<br>")[1] || "";
    el.classList.add("sr-rich");
    el.innerHTML =
      `<div class="sr-rv" id="${id}_box" data-pano="${id}" data-lat="${el.dataset.lat}" data-lng="${el.dataset.lng}" data-gubun="${escapeHtml(el.dataset.gubun || "")}">` +
        `<div class="sr-rv-pano" id="${id}"></div><div class="sr-rv-msg" id="${id}_msg">로드뷰</div><span class="sr-rv-tag" style="background:${SR_TYPE_COLOR[el.dataset.gubun] || "#2563eb"};"></span><div class="sr-rv-cover"></div>` +
      `</div>` +
      `<div class="sr-txt"><b>${label}</b><div class="sr-addr">${addr ? escapeHtml(addr) : area}</div></div>` +
      `<span class="mobile-result-distance">${dist}</span>`;
    const box = document.getElementById(id + "_box");
    if(srRvObserver) srRvObserver.observe(box);
  });
  srFillDistances();
}
function srApplyDistances(lat, lng){
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
  if(sorted) return;
  const frag = document.createDocumentFragment();
  els.forEach(function(el){ frag.appendChild(el); });
  list.appendChild(frag);
  list.scrollTop = 0;
}
function srFillDistances(){
  if(typeof userLat !== "undefined" && userLat && userLng){ srApplyDistances(userLat, userLng); return; }
  if(window.srMyLat){ srApplyDistances(window.srMyLat, window.srMyLng); return; }
  if(srLocAsked || !navigator.geolocation) return;
  srLocAsked = true;
  navigator.geolocation.getCurrentPosition(function(pos){
    srLocAsked = false;
    window.srMyLat = pos.coords.latitude; window.srMyLng = pos.coords.longitude;
    srApplyDistances(window.srMyLat, window.srMyLng);
  }, function(){ srLocAsked = false; }, {enableHighAccuracy:false, timeout:8000, maximumAge:300000});
}
document.addEventListener("DOMContentLoaded", function(){
  if(!window.FEATURE_DETAIL) return;
  const list = document.getElementById("mobileResultList");
  if(!list) return;
  let t = null;
  new MutationObserver(function(){ clearTimeout(t); t = setTimeout(srEnhanceList, 30); }).observe(list, {childList:true});
});
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

    el.dataset.gubun = item.구분; el.dataset.lat = item.위도; el.dataset.lng = item.경도; el.dataset.addr = item.주소 || "";

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



  <div class="popup-title">${gubunLabel(item.구분)}</div>

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
  const name = item.구분 || "위치";
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

      rvClient.getNearestPanoId(position, 100, function(panoId){

        if(panoId === null){

          if(msg) msg.textContent = (containerId.indexOf("srrv_") === 0) ? "로드뷰 없음" : "📷 이 위치는 로드뷰가 없습니다.";

        } else {

          if(msg) msg.style.display = "none";

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

      });

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

    { icon: buildUserIcon() }

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

    { icon: buildUserIcon() }

  );



  window.mobileMarkerGroup.addLayer(userCircle);

  window.mobileMarkerGroup.addLayer(userMarker);



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

    window.mobileMarkerGroup.addLayer(circle);

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

    el.dataset.gubun = item.구분; el.dataset.lat = item.위도; el.dataset.lng = item.경도; el.dataset.addr = item.주소 || "";



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

    { icon: buildUserIcon() }

  );



  window.mobileMarkerGroup.addLayer(userCircle);

  window.mobileMarkerGroup.addLayer(userMarker);

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

    { icon: buildUserIcon() }

  );



  window.mobileMarkerGroup.addLayer(userCircle);

  window.mobileMarkerGroup.addLayer(userMarker);

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
    ["routePopup","addrSearchPopup"].forEach(function(id){
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

  

  if(dist <= radius){

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



  showResultList(filtered, userLat !== null ? userLat : startLat, userLng !== null ? userLng : startLng);



  if(isMobile()){

  syncToMobileMap(filtered, userLat !== null ? userLat : startLat, userLng !== null ? userLng : startLng);

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

  const filtered = data.filter(item => {

    return calcDistance(lat, lng, item.위도, item.경도) <= radius;

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
    const tags = [];
    if(+item.보행자사고) tags.push(`🚶 보행자 ${+item.보행자사고}`);
    if(+item.야간사고) tags.push(`🌙 야간 ${+item.야간사고}`);
    if(+item.중상이상) tags.push(`중상 이상 ${+item.중상이상}`);
    return infoLine(`사고 ${n}건${tags.length ? " (" + tags.join(" · ") + ")" : ""}`);
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

        df = load_df()

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
                     headers=_sb_headers(), timeout=3)
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
        v, _err = _fetch_feature()
    except Exception:
        pass   # 조회 실패 시 직전 값 유지 (처음이면 OFF)
    _FEATURE_CACHE.update(v=v, t=now)
    return v


@app.route("/api/admin/feature", methods=["GET"])
@admin_required
def admin_get_feature():
    try:
        v, err = _fetch_feature()
    except Exception as e:
        return jsonify(ok=False, on=False, error=str(e))
    if err:
        return jsonify(ok=False, on=False, error=err)
    _FEATURE_CACHE.update(v=v, t=time.time())
    return jsonify(ok=True, on=v)


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
          <button class="page-btn" data-page="5" onclick="goToPage(5)">다운</button>
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
        <div class="ft-card">
          <div style="font-size:16px;font-weight:800;margin-bottom:10px;">안전로드 Ver.2</div>
          <div style="display:flex;align-items:center;gap:10px;">
            <b>지도에 적용</b>
            <label class="ft-switch"><input type="checkbox" id="featureDetailToggle" onchange="setFeatureDetail(this.checked)"><span class="ft-slider"></span></label>
            <span id="featureDetailState" class="ft-state" style="background:#f1f5f9;color:#64748b;">확인 중</span>
          </div>
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
          }catch(e){ showFeatureDetail(false, '확인 실패'); }
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
        detail_on=feature_detail_on()
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

    df = load_df()



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



    df = load_df()



    if province:

        df = df[df["시도"] == province]



    cities = sorted(df["시군구"].dropna().astype(str).unique().tolist())



    return jsonify({"cities":cities})





@app.route("/towns")

def towns():



    province = safe_str(request.args.get("province",""))

    city = safe_str(request.args.get("city",""))



    df = load_df()



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



    df = load_df()



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



@app.route("/data/all")

def data_all():



    df = load_df()



    records = df.apply(row_to_dict, axis=1).tolist()



    return jsonify({

        "total": len(records),

        "too_many": False,

        "data": records

    })



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



if __name__ == "__main__":



    port = int(os.environ.get("PORT", 5000))



    app.run(host="0.0.0.0", port=port, debug=False)