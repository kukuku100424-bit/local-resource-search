from flask import Flask, request, jsonify, render_template_string, Response, send_file, session

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

from io import BytesIO





def update_visitors():



    if not SUPABASE_URL or not SUPABASE_KEY:

        print("Supabase 환경변수 없음")

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

        print("Supabase visit_stats 조회 상태:", r.status_code, r.text)



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

        today = str(row.get("today_date", date.today()))

        today_count = int(row.get("today_count", 0))



        now_time = time.time()

        last_counted_at = session.get("last_visit_counted_at", 0)



        # 같은 브라우저에서 1시간 안에 다시 접속하면 카운트 증가 안 함

        if last_counted_at and now_time - float(last_counted_at) < 3600:

            print("1시간 이내 재방문: 방문자 수 증가 안 함")

            return {

                "total": total,

                "today_count": today_count

            }



        now_day = str(date.today())



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

            "updated_at": datetime.now().isoformat()

        }



        r2 = requests.patch(

            url,

            headers=headers,

            json=update_data

        )



        print("Supabase visit_stats 업데이트 상태:", r2.status_code, r2.text)



        r3 = requests.post(

            f"{SUPABASE_URL}/rest/v1/visit_logs",

            headers=headers,

            json={

                "ip": request.headers.get(

                    "X-Forwarded-For",

                    request.remote_addr

                )

            }

        )



        print("Supabase visit_logs 저장 상태:", r3.status_code, r3.text)



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

            "town": data.get("town", ""),

            "categories": data.get("categories", []),

            "result_count": data.get("result_count", 0),

            "ip": request.headers.get(

                "X-Forwarded-For",

                request.remote_addr

            )

        }



        print("Supabase 저장 payload:", payload)



        r = requests.post(

            f"{SUPABASE_URL}/rest/v1/search_logs",

            headers=headers,

            json=payload

        )



        print("Supabase search_logs 저장 상태:", r.status_code, r.text)



    except Exception as e:

        print("검색로그 Supabase 처리 오류:", e)





app = Flask(__name__)

app.secret_key = os.environ.get("SECRET_KEY", "safe-map-secret-key")

Compress(app)





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

DATA_CACHE = None





TYPE_COLORS = {

    "상습결빙지역": "#06b6d4",

    "공중화장실": "#f59e0b",

    "교통사고위험지역": "#ef4444"   # 추가

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



    return f"{city} {town} 위치 정보입니다."



def sample_date(category):



    m = {

        "상습결빙지역": "2025-12-28",

        "공중화장실": "2025-01-01",

        "교통사고위험지역": "2025-01-01"   # 추가

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



    if not os.path.exists(FILE_PATH):

        raise FileNotFoundError(f"{FILE_PATH} 파일이 없습니다.")



    df = pd.read_excel(FILE_PATH)

    

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



    for col in ["구분", "시도", "시군구", "주소", "읍면동", "사고설명", "날짜", "사진URL"]:

        df[col] = df[col].apply(safe_str)

    df["구분"] = df["구분"].str.strip()



    df["위도"] = pd.to_numeric(df["위도"], errors="coerce")

    df["경도"] = pd.to_numeric(df["경도"], errors="coerce")



    # 좌표 없는 건 자동 제외

    df = df[df["위도"].notna() & df["경도"].notna()].copy()



    DATA_CACHE = df

    return DATA_CACHE





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



    return {

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

@media(min-width:901px){.mobile-map-popup{display:none!important;}}



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

.mobile-result-header{padding:10px 14px;font-weight:700;font-size:13px;border-bottom:1px solid #f1f5f9;}

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



      <!-- 조회 조건 -->

      <div class="s-card">

        <div class="s-card-label">

          <span>조회 조건</span>

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

      </div>



      <!-- 빠른 찾기 -->

      <div class="s-card">

        <div class="s-card-label"><span>빠른 찾기</span></div>

        <div class="btn-grid" style="margin-bottom:6px;">

          <button class="btn-action btn-kakao" onclick="openRouteSearch()">경로주변 찾기</button>

          <button class="btn-action btn-kakao" onclick="openAddressSearch()">주소로 찾기</button>

          <button class="btn-action" onclick="findNearestToilet()">내 주변 화장실</button>

          <button class="btn-action" onclick="findNearestDanger()">내 주변 위험지역</button>

        </div>

        <button class="btn-action sexoffender-btn" style="margin-bottom:6px;" onclick="openSexOffenderApp()">성범죄자 알림e</button>

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

        <button class="btn-action" onclick="openAdminStats()">관리자 통계</button>

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

  </div>



  <div class="mobile-result-panel" id="mobileResultPanel">

    <div class="mobile-result-header">

      검색 결과 <span id="mobileResultCount">0</span>건

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

      <span class="map-legend-dot" style="background:#2563eb"></span>

      내 위치

    </div>

  </div>



  <div class="loading" id="loadingBox">데이터를 불러오는 중입니다...</div>

</div>

<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>

<script src="https://unpkg.com/leaflet.markercluster@1.5.3/dist/leaflet.markercluster.js"></script>



{% raw %}<script>

let ALL_DATA_CACHE = null;





const CATEGORY_COLORS = {

  "상습결빙지역": "#06b6d4",

  "공중화장실": "#f59e0b",

  "교통사고위험지역": "#ef4444"

};



const CATEGORY_LIST = [

  "상습결빙지역",

  "공중화장실",

  "교통사고위험지역"

];





const map = L.map("map", { zoomControl:true }).setView([34.85, 126.90], 9);



setTimeout(()=>{

  map.invalidateSize();

},500);



let userLat = null;

let userLng = null;

function showMsg(text){



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





function closeMsg(){

  const modal = document.getElementById("msgModal");

  if(modal){

    modal.style.display = "none";

  }

}



function showMobileResults(items, userLat, userLng){

  history.pushState({mobileResult:true}, "");



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

      distText = `<span class="mobile-result-distance">${dist} m</span>`;

    }



    const el = document.createElement("div");

    el.className = "mobile-result-item";

    el.innerHTML = `

      <b>${item.구분}</b><br>

      ${item.시군구} ${item.읍면동}<br>

      ${distText}

    `;



    el.onclick = function(){



  if(window.mobileLeafletMap){



    window.mobileLeafletMap.flyTo(

      [item.위도,item.경도],

      16,

      {

        duration:1.2,

        easeLinearity:0.25

      }

    );



    window.mobileLeafletMap.once("moveend", function(){



      if(window.mobileMarkerGroup){



        window.mobileMarkerGroup.eachLayer(function(layer){



          if(layer.itemData && layer.itemData.순번 === item.순번){

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

      <span>${cat}</span>

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

  const rvHeight = isMobile() ? "220px" : "280px";

  const popupWidth = isMobile() ? 290 : 480;

  return `

  <div class="popup-wrap" style="width:${popupWidth}px;">



  <!-- 로드뷰 컨테이너 -->

  <div id="${rvId}" style="width:100%;height:${rvHeight};border-radius:10px;border:1px solid #e5e7eb;margin-bottom:8px;background:#f1f5f9;overflow:hidden;position:relative;">

    <div style="position:absolute;inset:0;display:flex;align-items:center;justify-content:center;font-size:12px;color:#94a3b8;" id="${rvId}_msg">로드뷰 불러오는 중...</div>

  </div>



  <div class="popup-title">${escapeHtml(item.구분)}</div>

  <div class="popup-meta">

  주소: ${escapeHtml(item.주소)}

  </div>



  <!-- 별점 UI: 평가하기 버튼 -->

  <div id="rating_wrap_${sid}" style="margin-top:8px;display:flex;align-items:center;gap:8px;flex-wrap:wrap;">

    <button onclick="openRatingModal('${sid}')" style="

      height:30px;padding:0 12px;border:1px solid #f59e0b;border-radius:8px;

      background:#fffbeb;font-size:12px;cursor:pointer;font-weight:700;color:#b45309;">

      ★ 평가하기

    </button>

    <span id="avg_${sid}" style="font-size:12px;color:#f59e0b;font-weight:700;"></span>

  </div>



  <!-- 5번: 코멘트 버튼 -->

  <button onclick="openComments('${sid}')" style="

    margin-top:6px;width:100%;height:32px;border:1px solid #e2e8f0;

    border-radius:8px;background:#f8fafc;font-size:13px;cursor:pointer;font-weight:600;color:#374151;">

    코멘트 보기 / 작성

  </button>



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



// 로드뷰 초기화 함수 (팝업 열릴 때 호출)

function initRoadview(containerId, lat, lng){

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

          if(msg) msg.textContent = "📷 이 위치는 로드뷰가 없습니다.";

        } else {

          if(msg) msg.style.display = "none";

          roadview.setPanoId(panoId, position);

          // 초기 시야각: 수평(pitch=0), 정면 바라보기

          roadview.setViewpoint({

            pan: 0,

            tilt: 0,

            zoom: 0

          });

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

  const res = await fetch("/data");

  const result = await res.json();

  ALL_DATA_CACHE = result.data;

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



    marker.bindPopup(popupHtml,{maxWidth: isMobile() ? 310 : 520});



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

  categories.forEach(cat => params.append("category", cat));



  try{



    const res = await fetch("/data?" + params.toString());

    const result = await res.json();

    const data = result.data;

    const total = result.total;



    // 5000개 초과 시 서버 부하 방지 팝업
    if(result.too_many){
      setLoading(false);
      showMsg(`🚨 검색 결과가 너무 많습니다 (${total.toLocaleString()}건)

시도 → 시군구 → 읍면동 순서로 범위를 좁히거나,
위험지역 구분을 선택해 상세 검색해 주세요.`);
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

    town:towns.join(","),

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



      marker.bindPopup(popupHtml, { maxWidth: isMobile() ? 310 : 520 });

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



  // 전체 마커 다시 표시

  loadAllMarkers();



}



window.addEventListener("load", function(){

  setTimeout(()=>{

    map.invalidateSize();

  },1000);

});



window.addEventListener("DOMContentLoaded", function(){



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

    loadAllMarkers();

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



  setTimeout(()=>{

    input.focus();

  },100);



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



  if(input.value !== "1234"){

    if(msg){

      msg.textContent = "암호가 틀렸습니다.";

    }

    input.focus();

    return;

  }



  window.location.href = "/stats";



}



function isMobile(){

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



  if(!history.state || !history.state.mobileMap){

    history.pushState({mobileMap:true}, "");

  }



  if(!isMobile()) return;



  const popup = document.getElementById("mobileMapPopup");

  popup.style.display = "flex";



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



  marker.bindPopup(popupHtml,{maxWidth:290});



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

  const res = await fetch("/data");

  const result = await res.json();

  ALL_DATA_CACHE = result.data;

}



const data = ALL_DATA_CACHE;



  const radius = 5000;



  const filtered = [];



  data.forEach(item=>{

    

    console.log(item.구분,targetType);



    if(item.구분 !== targetType) return;



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

    showMsg("주변에 데이터가 없습니다.");



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



marker.bindPopup(popupHtml,{maxWidth:290});



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

      distText = dist + " m";

    }



    const el = document.createElement("div");



    el.className = "mobile-result-item";



    el.innerHTML = `

      <b>${item.구분}</b><br>

      ${item.시군구} ${item.읍면동}<br>

      <span class="mobile-result-distance">${distText}</span>

    `;

    el.onclick = function(){



  map.flyTo([item.위도,item.경도],16);



  map.once("moveend", function(){



    markerGroup.eachLayer(function(layer){



      if(layer.itemData && layer.itemData.순번 === item.순번){

        layer.openPopup();

      }



    });



  });



  if(window.mobileLeafletMap){



    window.mobileLeafletMap.flyTo(

      [item.위도,item.경도],

      16,

      {

        duration:1.2,

        easeLinearity:0.25

      }

    );



    window.mobileLeafletMap.once("moveend", function(){



      if(window.mobileMarkerGroup){



        window.mobileMarkerGroup.eachLayer(function(layer){



          if(layer.itemData && layer.itemData.순번 === item.순번){

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

  const res = await fetch("/data");

  const result = await res.json();

  ALL_DATA_CACHE = result.data;

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



if(window.mobileLeafletMap){

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

  window.mobileMarkerGroup.clearLayers();



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



if(window.mobileLeafletMap){



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



function openRouteSearch(){



  document.getElementById("routePopup").style.display="flex";



  setTimeout(function(){



    const input = document.getElementById("startInput");



    if(input){

      input.focus();

      input.click();

    }



  }, 100);



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

  const res = await fetch("/data");

  const result = await res.json();

  ALL_DATA_CACHE = result.data;

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

    marker.bindPopup(popupHtml,{maxWidth:290});

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



  showMsg(

      `경로 주변 시설\n\n공중화장실 ${toiletCount}개\n상습결빙지역 ${iceCount}개\n교통사고위험지역 ${accidentCount}개`

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

  setTimeout(()=>document.getElementById("addrSearchInput").focus(),100);

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

    const res = await fetch("/data");

    const result = await res.json();

    ALL_DATA_CACHE = result.data;

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

    marker.bindPopup(buildPopupHtml(item),{maxWidth:290});

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

  "전체": "#475569"

};

const PILL_IDS = {

  "전체": "pill_all",

  "상습결빙지역": "pill_ice",

  "공중화장실": "pill_toilet",

  "교통사고위험지역": "pill_accident"

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

        if(layer.itemData.구분 === cat){

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

      const title = el.querySelector("b");

      if(title && title.textContent === cat){

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

  "전체": "#475569"

};

let pcPillActive = "전체";



function pcPillFilter(cat){

  pcPillActive = cat;

  ["전체","상습결빙지역","공중화장실","교통사고위험지역"].forEach(k=>{

    const id = "pc_pill_" + (k==="전체"?"all":k==="상습결빙지역"?"ice":k==="공중화장실"?"toilet":"accident");

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

      if(layer._icon) layer._icon.style.display = layer.itemData.구분===cat ? "" : "none";

    }

  });

  // 결과 목록 필터 + 건수 업데이트

  const list = document.getElementById("mobileResultList");

  if(!list) return;

  const items = list.querySelectorAll(".mobile-result-item");

  items.forEach(el=>{

    const b = el.querySelector("b");

    el.style.display = (cat==="전체" || (b && b.textContent===cat)) ? "" : "none";

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

  const popup = e.popup;

  const marker = popup._source;

  const item = marker && marker.itemData;

  if(!item) return;

  const sid = String(item.순번);

  loadRating(sid);

  // 로드뷰: 약간 딜레이 후 DOM 안정되면 초기화

  setTimeout(()=> initRoadview("rv_" + sid, item.위도, item.경도), 200);

  // 검색결과 패널 숨기기

  const panel = document.getElementById("mobileResultPanel");

  if(panel && panel.style.display !== "none"){

    panel._wasVisible = true;

    panel.style.display = "none";

  }

  // 모바일: 팝업이 화면 중앙에 오도록 지도 pan

  if(isMobile()){

    setTimeout(()=>{

      const theMap = window.mobileLeafletMap || map;

      if(theMap && popup._latlng){

        // 팝업 높이만큼 위로 오프셋해서 중앙에 맞춤

        const popupHeight = 360; // 팝업 대략 높이(px)

        const containerHeight = theMap.getSize().y;

        const offset = (containerHeight / 2) - (popupHeight / 2) - 30;

        theMap.panBy([0, -Math.max(offset, 0)], {animate:true, duration:0.3});

      }

    }, 150);

  }

}



function onPopupClose(e){

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

    const res = await fetch("/api/rating?spot_id="+encodeURIComponent(sid));

    const d = await res.json();

    const myScore = parseInt(localStorage.getItem("rating_"+sid)||"0");

    renderStars(sid, myScore, d.avg||0, d.count||0);

  }catch(e){}

}



// 별점 모달

let _ratingModalSid = null;

let _ratingSelected = 0;



function openRatingModal(sid){

  _ratingModalSid = sid;

  _ratingSelected = parseInt(localStorage.getItem("rating_"+sid)||"0");

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

      body: JSON.stringify({spot_id: sid, score: score})

    });

    const d = await res.json();

    if(d.ok){

      localStorage.setItem("rating_"+sid, score);

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

    const res = await fetch("/api/comments?spot_id="+encodeURIComponent(sid));

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

    await fetch("/api/comments", {

      method:"POST",

      headers:{"Content-Type":"application/json"},

      body: JSON.stringify({spot_id: sid, content: content})

    });

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

        const res = await fetch("/data");

        const result = await res.json();

        ALL_DATA_CACHE = result.data;

      }

      const found = ALL_DATA_CACHE.find(d => String(d.순번) === String(gotoSpot));

      if(!found){

        alert("해당 지점을 데이터에서 찾을 수 없습니다. (지점번호: " + gotoSpot + ")");

        return;

      }

      const targetLat = found.위도;

      const targetLng = found.경도;



      function openMarkerPopup(mGroup){

        mGroup.eachLayer(function(layer){

          if(layer.itemData && String(layer.itemData.순번) === String(gotoSpot)){

            layer.openPopup();

          }

        });

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

              marker.bindPopup(buildPopupHtml(item), {maxWidth:290});

              window.mobileMarkerGroup.addLayer(marker);

            });

          }

          setTimeout(()=>{

            if(window.mobileLeafletMap){

              window.mobileLeafletMap.flyTo([targetLat, targetLng], 17);

              window.mobileLeafletMap.once("moveend", function(){

                if(window.mobileMarkerGroup) openMarkerPopup(window.mobileMarkerGroup);

              });

            }

          }, 400);

        }

        setTimeout(doMobileGoto, 600);

      } else {

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



<div id="msgText" style="

font-size:16px;

margin-bottom:18px;

line-height:1.7;

white-space:pre-line;

color:#0f172a;

font-weight:700;

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

  <textarea id="commentInput" placeholder="이 지점에 대한 의견을 남겨주세요..." style="

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

    return send_file(apk_path, as_attachment=True, download_name="safeload.apk", mimetype="application/vnd.android.package-archive")



@app.route("/")

def index():



    visitor = update_visitors()



    return render_template_string(

        HTML,

        total_visit=visitor["total"],

        today_visit=visitor["today_count"],

        kakao_key=KAKAO_KEY or "",

        kakao_js_key=KAKAO_JS_KEY or ""

    )





@app.route("/log_search", methods=["POST"])

def log_search():



    data = request.get_json() or {}



    save_search_log(data)



    return jsonify({"ok": True})





# ===== 5번: 별점 API =====

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

            f"{SUPABASE_URL}/rest/v1/spot_ratings?spot_id=eq.{quote(spot_id)}&select=score",

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

    spot_id = str(data.get("spot_id", ""))

    score = int(data.get("score", 0))

    if not spot_id or score < 1 or score > 5 or not SUPABASE_URL or not SUPABASE_KEY:

        return jsonify({"ok": False})

    ip = request.headers.get("X-Forwarded-For", request.remote_addr)

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

            json={"spot_id": spot_id, "score": score}

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

            f"{SUPABASE_URL}/rest/v1/spot_comments?spot_id=eq.{quote(spot_id)}&order=created_at.desc&limit=50",

            headers=headers

        )

        rows = r.json()

        if not isinstance(rows, list):

            return jsonify({"comments": []})

        return jsonify({"comments": rows})

    except Exception as e:

        return jsonify({"comments": []})





@app.route("/api/comments", methods=["POST"])

def post_comment():

    data = request.get_json() or {}

    spot_id = str(data.get("spot_id", ""))

    content = str(data.get("content", "")).strip()

    if not spot_id or not content or not SUPABASE_URL or not SUPABASE_KEY:

        return jsonify({"ok": False})

    try:

        headers = {

            "apikey": SUPABASE_KEY,

            "Authorization": f"Bearer {SUPABASE_KEY}",

            "Content-Type": "application/json",

            "Prefer": "return=representation"

        }

        requests.post(

            f"{SUPABASE_URL}/rest/v1/spot_comments",

            headers=headers,

            json={"spot_id": spot_id, "content": content}

        )

        return jsonify({"ok": True})

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





# ===== 관리자: 코멘트 전체 조회 =====

@app.route("/api/admin/comments", methods=["GET"])

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

        return jsonify({"comments": rows})

    except Exception as e:

        return jsonify({"comments": []})





# ===== 관리자: 코멘트 삭제 =====

@app.route("/api/admin/comments/<int:comment_id>", methods=["DELETE"])

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

        return jsonify({"ratings": rows})

    except Exception as e:

        return jsonify({"ratings": []})





# ===== 관리자: 별점 삭제 =====

@app.route("/api/admin/ratings/<int:rating_id>", methods=["DELETE"])

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



        print("Supabase 관리자페이지 조회 상태:", res.status_code, res.text)



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

            return """

            <h2>조회 통계</h2>

            <p>아직 조회 기록이 없습니다.</p>

            <p><a href="/">돌아가기</a></p>

            """



        df = pd.DataFrame(logs)



        if df.empty or "created_at" not in df.columns:

            return """

            <h2>조회 통계</h2>

            <p>조회 기록 형식이 올바르지 않습니다.</p>

            <p><a href="/">돌아가기</a></p>

            """



        for col in ["province", "city", "town", "categories", "result_count"]:

            if col not in df.columns:

                df[col] = ""



        df["day"] = pd.to_datetime(

            df["created_at"],

            errors="coerce"

        ).dt.strftime("%Y-%m-%d")



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

          max-height:400px;

          overflow-y:auto;

          margin-bottom:30px;

          border:1px solid #ddd;

          border-radius:6px;

        }

        .table-wrap table{

          margin-bottom:0;

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

        </style>

        </head>

        <body>



        <h2>조회 통계</h2>



        <a class="btn" href="/">돌아가기</a>

        <a class="btn" href="/stats_excel">엑셀 다운로드</a>



        <h3>날짜별·지역별 조회 수</h3>

        <div class="table-wrap">{{ region_table|safe }}</div>



        <h3>날짜별·위험지역 체크 수</h3>

        <div class="table-wrap">{{ category_table|safe }}</div>



        <h3>💬 코멘트 관리</h3>

        <div id="commentAdminArea">불러오는 중...</div>



        <h3 style="margin-top:32px;">⭐ 별점 관리</h3>

        <div id="ratingAdminArea">불러오는 중...</div>



        <script>

        async function loadAdminComments(){

          const res = await fetch('/api/admin/comments');

          const d = await res.json();

          const area = document.getElementById('commentAdminArea');

          if(!d.comments || d.comments.length===0){

            area.innerHTML='<p style="color:#94a3b8;">등록된 코멘트가 없습니다.</p>';

            return;

          }

          let html = '<div class="table-wrap"><table><thead><tr><th>ID</th><th>지점번호</th><th>내용</th><th>작성일시</th><th>삭제/이동</th></tr></thead><tbody>';

          d.comments.forEach(c=>{

            html += `<tr>

              <td>${c.id}</td>

              <td>${c.spot_id}</td>

              <td style="max-width:300px;word-break:break-all;">${c.content}</td>

              <td>${c.created_at ? c.created_at.slice(0,16).replace('T',' ') : ''}</td>

              <td style="white-space:nowrap;">

                <button class="btn-del" onclick="deleteComment(${c.id}, this)">삭제</button>

                <button class="btn-goto" onclick="gotoSpot('${c.spot_id}')">이동</button>

              </td>

            </tr>`;

          });

          html += '</tbody></table></div>';

          area.innerHTML = html;

        }



        async function deleteComment(id, btn){

          if(!confirm('이 코멘트를 삭제하시겠습니까?')) return;

          btn.disabled = true;

          btn.textContent = '삭제중...';

          const res = await fetch('/api/admin/comments/' + id, {method:'DELETE'});

          const d = await res.json();

          if(d.ok){

            btn.closest('tr').remove();

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

          let html = '<div class="table-wrap"><table><thead><tr><th>ID</th><th>지점번호</th><th>별점</th><th>작성일시</th><th>삭제/이동</th></tr></thead><tbody>';

          d.ratings.forEach(r=>{

            const stars = '★'.repeat(r.score||0) + '☆'.repeat(5-(r.score||0));

            html += `<tr>

              <td>${r.id}</td>

              <td>${r.spot_id}</td>

              <td style="color:#f59e0b;font-weight:700;letter-spacing:1px;">${stars} (${r.score}점)</td>

              <td>${r.created_at ? r.created_at.slice(0,16).replace('T',' ') : ''}</td>

              <td style="white-space:nowrap;">

                <button class="btn-del" onclick="deleteRating(${r.id}, this)">삭제</button>

                <button class="btn-goto" onclick="gotoSpot('${r.spot_id}')">이동</button>

              </td>

            </tr>`;

          });

          html += '</tbody></table></div>';

          area.innerHTML = html;

        }



        async function deleteRating(id, btn){

          if(!confirm('이 별점을 삭제하시겠습니까?')) return;

          btn.disabled = true;

          btn.textContent = '삭제중...';

          const res = await fetch('/api/admin/ratings/' + id, {method:'DELETE'});

          const d = await res.json();

          if(d.ok){

            btn.closest('tr').remove();

          } else {

            btn.disabled = false;

            btn.textContent = '삭제';

            alert('삭제 실패');

          }

        }



        async function gotoSpot(spotId){

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



        loadAdminComments();

        loadAdminRatings();

        </script>



        </body>

        </html>

        """,

        region_table=region_stats.to_html(index=False),

        category_table=category_stats.to_html(index=False)

        )



    except Exception as e:

        return f"""

        <h2>조회 통계 오류</h2>

        <p>관리자페이지 처리 중 오류가 발생했습니다.</p>

        <pre>{str(e)}</pre>

        <p><a href="/">돌아가기</a></p>

        """



@app.route("/stats_excel")

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



        for col in ["created_at", "province", "city", "town", "categories", "result_count", "ip"]:

            if col not in df.columns:

                df[col] = ""



        df["날짜"] = pd.to_datetime(

            df["created_at"],

            errors="coerce"

        ).dt.strftime("%Y-%m-%d")



        df["조회일시"] = pd.to_datetime(

            df["created_at"],

            errors="coerce"

        ).dt.strftime("%Y-%m-%d %H:%M:%S")



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



        output = BytesIO()



        with pd.ExcelWriter(output, engine="openpyxl") as writer:

            raw_df.to_excel(writer, index=False, sheet_name="전체 조회기록")

            region_stats.to_excel(writer, index=False, sheet_name="지역별 통계")

            category_stats.to_excel(writer, index=False, sheet_name="구분별 통계")



        output.seek(0)



        filename = "safety_map_stats_" + datetime.now().strftime("%Y%m%d_%H%M%S") + ".xlsx"



        return send_file(

            output,

            as_attachment=True,

            download_name=filename,

            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

        )



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



@app.route("/sample-image")

def sample_image():

    category = safe_str(request.args.get("category", "위험지역"))

    city = safe_str(request.args.get("city", ""))

    town = safe_str(request.args.get("town", ""))



    color = TYPE_COLORS.get(category, "#334155")



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





if __name__ == "__main__":



    port = int(os.environ.get("PORT", 5000))



    app.run(host="0.0.0.0", port=port, debug=False)