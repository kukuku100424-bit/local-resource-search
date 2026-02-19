from flask import Flask, render_template_string, request, jsonify
import pandas as pd
import os
import re

# ★ .env 파일에서 API키 불러오기
from dotenv import load_dotenv
load_dotenv()

import numpy as np
from sklearn.metrics.pairwise import cosine_similarity
from openai import OpenAI

def extract_conditions_display(query):
    try:
        client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

        prompt=f"""

너는 복지서비스 검색 시스템의 자연어 해석기다.
설명하지 말고 반드시 JSON만 출력한다.

[지역 규칙]
- 목포 관련 표현 → "목포시"
- 나주 관련 표현 → "나주시"
- 영암 관련 표현 → "영암군"

[가구유형 규칙]
- 혼자 삶, 배우자 사망, 보호자 없음 → "독거"
- 부부 거주 → "노인부부"

[Y/N 판단]
- 방문/찾아옴 → 방문형서비스="Y"
- 거동불편/낙상 → 거동불편="Y"
- 우울/외로움 → 정서지원="Y"
- 장애/치매 → 장애여부="Y"

전화번호 요청 시 contact_request=true

JSON 형식:
{{
"시군구": string|null,
"가구유형": string|null,
"방문형서비스": "Y"|null,
"거동불편": "Y"|null,
"정서지원": "Y"|null,
"장애여부": "Y"|null,
"contact_request": true|false
}}

문장: {query}
"""


        res = client.chat.completions.create(
            model="gpt-4.1-mini",
            messages=[{"role":"user","content":prompt}],
            temperature=0
        )

        import json, re
        text=res.choices[0].message.content
        print("GPT응답:", text, flush=True)

        match=re.search(r'\{.*\}',text,re.S)

        if not match:
            return []

        data=json.loads(match.group())

        display=[]
        for k,v in data.items():
            display.append(f"{k}: {v}")

        return display

    except Exception as e:
        print("조건표시 실패:",e)
        return []


app = Flask(__name__)

FILE_PATH = "service_resources.xlsx"

try:
    df = pd.read_excel(FILE_PATH)
    df.columns = df.columns.str.replace(" ","")
except Exception as e:
    print("엑셀 로드 실패:", e)
    df = pd.DataFrame()


# ================= ROUTES =================
@app.route("/")
def home():
    return render_template_string(HOME_HTML, style=BASE_STYLE)

@app.route("/combo", methods=["GET","POST"])
def combo():
    family_types = sorted(df["가구유형"].dropna().unique().tolist()) if "가구유형" in df.columns else []
    disabilities = sorted(df["장애여부"].dropna().unique().tolist()) if "장애여부" in df.columns else []
    services = sorted(df["방문형서비스"].dropna().unique().tolist()) if "방문형서비스" in df.columns else []


    results=None
    age=family_type=disability=service_type=region=keyword=""

    if request.method=="POST":
        age=request.form.get("age","").strip()
        family_type=request.form.get("family_type","")
        disability=request.form.get("disability","")
        service_type=request.form.get("service_type","")
        region=request.form.get("region","").strip()
        keyword=request.form.get("keyword","").strip()

        filtered=df.copy()

        if age.isdigit() and "연령" in df.columns:
            filtered = filtered[pd.to_numeric(filtered["연령"], errors="coerce") >= int(age)]

        if family_type and "가구유형" in filtered.columns:
            filtered = filtered[filtered["가구유형"].astype(str).str.contains(family_type, na=False)]

        if disability and "장애여부" in filtered.columns:
            filtered = filtered[filtered["장애여부"].astype(str).str.contains(disability, na=False)]

        if service_type and "방문형서비스" in filtered.columns:
            filtered = filtered[filtered["방문형서비스"].astype(str).str.contains(service_type, na=False)]

        if region and "지역" in filtered.columns:
            filtered = filtered[filtered["지역"].astype(str).str.contains(region, na=False)]

        if keyword: filtered = filtered[filtered.apply(lambda x: keyword.lower() in str(x.to_dict()).lower(), axis=1)]
 
        results=filtered.reset_index()[["index","프로그램명칭"]].dropna().to_dict("records")
        cond_display = extract_conditions_display(query)  # 있으면 유지

    return render_template_string(
        COMBO_HTML, style=BASE_STYLE,
        family_types=family_types, disabilities=disabilities,
        services=services, results=results,
        age=age,family_type=family_type,
        disability=disability,service_type=service_type,
        region=region,keyword=keyword
    )

@app.route("/detail/<int:idx>")
def detail(idx):
    if idx >= len(df):
        return jsonify({
            "프로그램명칭":"데이터가 변경되었습니다",
            "기관명":"다시 검색해주세요",
            "기관 연락처":"",
            "기관주소":""
        })

    r=df.iloc[idx]
    return jsonify({
        "프로그램명칭":str(r.get("프로그램명칭","")),
        "기관명":str(r.get("서비스제공기관명","")),
        "기관 연락처":str(r.get("기관연락처","")),
        "기관주소":str(r.get("기관주소",""))
    })

    

        
@app.route("/desc", methods=["GET","POST"])
def desc():
    cond_display = ""
    query=""
    results=None

    if request.method=="POST":
        query=request.form["query"]
        cond_display = extract_conditions_display(query)

        # 의미검색 실행 (RAG)
        found = semantic_search(query, 7)

        results = []

    return render_template_string(
        DESC_HTML,
        style=BASE_STYLE,
        query=query,
        results=results,
        message=None,
        cond_display=cond_display

    )


@app.route("/care", methods=["GET"])
def care():
    return render_template_string(
        CARE_HTML, style=BASE_STYLE,
        questions=list(enumerate(CARE_QUESTIONS))
    )


@app.route("/care_check", methods=["POST"])
def care_check():
    score=0
    dementia=request.form.get("dementia","n")

    if dementia=="y":
        return jsonify({"result":"통합돌봄 지원 대상 (치매약 복용)","score":"판정 제외"})

    for i in range(7):
        val=request.form.get(f"q{i}")
        if val is None or val=="":
            val=0
        score+=int(val)

    if score<=1:
        result="지원 대상 아님"
    elif score<=3:
        result="지자체 자체조사 대상"
    else:
        result="통합판정조사 대상"

    return jsonify({"result":result,"score":score})


