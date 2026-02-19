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
            if v is None:
                continue
            if v is False:
                continue
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

# ================== RAG 벡터 DB 생성 ==================

api_key = os.getenv("OPENAI_API_KEY")

if api_key:
    rag_client = OpenAI(api_key=api_key)
else:
    rag_client = None

doc_vectors = None
documents = None

def row_to_text(row):
    return f"""
    {row.get('지역','')} {row.get('시군구','')} 지역에서 제공되는
    {row.get('대분류','')} {row.get('중분류','')} 서비스인
    {row.get('프로그램명칭','')} 이며
    대상 연령은 {row.get('연령','')}세 이상,
    가구유형 {row.get('가구유형','')},
    장애여부 {row.get('장애여부','')},
    방문서비스 {row.get('방문형서비스','')},
    거동불편 지원 {row.get('거동불편','')},
    정서지원 {row.get('정서지원','')},
    기타 {row.get('기타','')}
    """




CARE_QUESTIONS = [
"의자나 소파에서 걸터앉은 상태에서 무릎을 짚고 일어설 수 있습니까?",
"집안에서 6걸음을 이동할 수 있습니까?",
"등을 제외한 몸 전체를 씻을 수 있습니까?",
"상의 입고 단추를 잠글 수 있습니까?",
"하의를 입고 지퍼를 올릴 수 있습니까?",
"소변실수를 하지 않고 화장실에 갈 수 있습니까?",
"화장실에서 변기에 앉아 용변을 볼 수 있습니까?"
]


# ================= 공통 CSS =================
BASE_STYLE = """
* { box-sizing: border-box; }
body { font-family: 'Pretendard', sans-serif; margin:0; padding:20px; background:#f7f9fc; }
h1,h2 { text-align:center; color:#2c3e50; }
label { font-weight:bold; margin-top:10px; display:block; }
input, select, textarea {
  width:100%; padding:12px; font-size:16px;
  border-radius:8px; border:1px solid #ccc; margin-top:5px;
}
button {
  width:100%; padding:14px; font-size:18px;
  background:#0078d7; color:white; border:none;
  border-radius:8px; cursor:pointer; margin-top:15px;
}
button:hover { background:#005fa3; }
.container { max-width:600px; margin:auto; }
.result {
  margin-top:30px; background:white; padding:20px;
  border-radius:8px; box-shadow:0 2px 6px rgba(0,0,0,0.1);
}
.home-btn {
  display:inline-block; background:#2c3e50; color:white;
  text-decoration:none; padding:10px 16px; border-radius:6px;
  margin-bottom:20px;
}
.home-btn:hover { background:#1a252f; }
.bottom-image { width:100%; margin-top:40px; }

/* ★추가: 전화 아이콘 스타일 */
.tel-link { margin-left:8px; font-size:20px; text-decoration:none; }
"""

# ================= HOME =================
HOME_HTML = """
<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>지자체 서비스자원 검색 시스템</title>
<style>{{ style }}</style>
</head>
<body>
<div class="container">
<h1>🏛 지자체 서비스자원 검색 시스템</h1>
<p style="text-align:center;">검색 방식을 선택하세요</p>
<a href="/combo"><button>① 대상자 특성 검색</button></a>
<a href="/desc"><button>② 서술형 검색</button></a>
<a href="/care"><button>③ 통합돌봄 사전조사</button></a>
<img src="/static/bottom.png" class="bottom-image">
</div>
</body>
</html>
"""

# ================= COMBO =================
COMBO_HTML = """
<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>대상자 특성 검색</title>
<style>{{ style }}</style>
</head>
<body>
<div class="container">
<a href="/" class="home-btn">← 홈으로</a>
<h2>대상자 특성 검색</h2>

<form method="post">
<label>연령 (이상)</label>
<input type="text" name="age" placeholder="예: 70" value="{{ age or '' }}">

<label>가구유형</label>
<select name="family_type">
<option value="">무관</option>
{% for f in family_types %}
<option value="{{ f }}" {% if f==family_type %}selected{% endif %}>{{ f }}</option>
{% endfor %}
</select>

<label>장애여부</label>
<select name="disability">
<option value="">무관</option>
{% for d in disabilities %}
<option value="{{ d }}" {% if d==disability %}selected{% endif %}>{{ d }}</option>
{% endfor %}
</select>

<label>방문형서비스</label>
<select name="service_type">
<option value="">무관</option>
{% for s in services %}
<option value="{{ s }}" {% if s==service_type %}selected{% endif %}>{{ s }}</option>
{% endfor %}
</select>

<label>지역</label>
<input type="text" name="region" placeholder="예: 나주시" value="{{ region or '' }}">

<label>기타 키워드</label>
<input type="text" name="keyword" placeholder="예: 정서지원, 에너지" value="{{ keyword or '' }}">

<button type="submit">검색하기 🔍</button>
</form>

{% if results is not none %}
<div class="result">
{% if results|length > 0 %}
<p>총 {{ results|length }}개의 자원을 찾았습니다.</p>
{% for r in results %}
<div style="cursor:pointer;color:#0078d7;"
onclick="openDetail({{ r['index'] }})">
🔹 {{ loop.index }}. {{ r['프로그램명칭'] }}
</div>
{% endfor %}
{% else %}
<p>조건에 맞는 자원이 없습니다.</p>
{% endif %}
</div>
{% endif %}
</div>

<!-- 공통 팝업 -->
<div id="modal" style="display:none;position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,.5)">
<div style="background:white;margin:5% auto;padding:20px;width:90%;max-width:500px;border-radius:10px">
<h3 id="m_title"></h3>
<p><b>기관명:</b> <span id="m_org"></span></p>

<!-- ★기존 줄 교체 -->
<p>
<b>기관 연락처:</b> <span id="m_tel"></span>
<a id="tel_link" class="tel-link" style="display:none;">📞</a>
</p>

<p><b>기관주소:</b> <span id="m_addr"></span></p>
<iframe id="m_map" width="100%" height="250" style="border:0"></iframe>
<button onclick="closeModal()">닫기</button>
</div>
</div>

<script>
/* ★추가: 모바일 판별 */
function isMobile(){
  return /Android|iPhone|iPad|iPod/i.test(navigator.userAgent);
}

function openDetail(idx){
fetch("/detail/"+idx)
.then(r=>r.json())
.then(d=>{
m_title.innerText=d["프로그램명칭"];
m_org.innerText=d["기관명"];
m_tel.innerText=d["기관 연락처"];
m_addr.innerText=d["기관주소"];
m_map.src="https://www.google.com/maps?q="+encodeURIComponent(d["기관주소"])+"&output=embed";

const telLink=document.getElementById("tel_link");
if(isMobile() && d["기관 연락처"]){
  const numMatch = d["기관 연락처"].match(/[0-9-]+/);
  if(numMatch){
    telLink.href="tel:"+numMatch[0];
    telLink.style.display="inline";
  }else{
    telLink.style.display="none";
  }
}else{
  telLink.style.display="none";
}

modal.style.display="block";
});
}
function closeModal(){ modal.style.display="none"; }
</script>
</body>
</html>
"""
# ================= CARE =================
CARE_HTML = """
<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>통합돌봄 사전조사</title>
<style>{{ style }}</style>
</head>
<body>
<div class="container">
<a href="/" class="home-btn">← 홈으로</a>
<h2>통합돌봄 사전조사</h2>

<form id="careForm">
<label>치매 관련 약 복용 여부</label>
<select name="dementia" required>
<option value="">선택</option>
<option value="y">예</option>
<option value="n">아니오</option>
</select>

<hr>

{% for i,q in questions %}
<label>{{i+1}}. {{q}}</label>
<select name="q{{i}}" required>
<option value="">선택</option>
<option value="0">도움 없이 가능</option>
<option value="1">보조도구/준비 필요</option>
<option value="2">타인 도움 필요</option>
</select>
{% endfor %}

<button type="submit">판정하기</button>
</form>
</div>

<!-- 결과 팝업 -->
<div id="resultModal" style="display:none;position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,.5)">
<div style="background:white;margin:10% auto;padding:25px;width:90%;max-width:400px;border-radius:12px;text-align:center">
<h3>사전조사 결과</h3>
<p id="r_text" style="font-size:20px;font-weight:bold"></p>
<p id="r_score"></p>
<button onclick="closeModal()">닫기</button>
</div>
</div>

<script>
document.getElementById("careForm").onsubmit = async function(e){
    e.preventDefault();

    const formData = new FormData(this);

    const res = await fetch("/care_check", {
        method:"POST",
        body:formData
    });

    const data = await res.json();

    document.getElementById("r_text").innerText = data.result;
    document.getElementById("r_score").innerText = "총점: " + data.score;
    document.getElementById("resultModal").style.display="block";
}

function closeModal(){
    document.getElementById("resultModal").style.display="none";
}
</script>
</body>
</html>
"""



# ================= DESC (수정됨) =================
DESC_HTML = """
<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>서술형 검색</title>
<style>{{ style }}</style>
</head>
<body>
<div class="container">
<a href="/" class="home-btn">← 홈으로</a>
<h2>서술형 검색</h2>

<form method="post">
<textarea name="query" placeholder="예: 목포에 사는 독거노인이 이용 가능한 서비스">{{ query }}</textarea>
<button type="submit">검색하기</button>
</form>

{% if message %}
<div class="result">{{ message }}</div>

{% elif results is not none %}
<div class="result">
{% if cond_display %}
<p><b>이 조건으로 검색했습니다</b></p>
<ul>
{% for c in cond_display %}
<li>✔ {{ c }}</li>
{% endfor %}
</ul>
<hr>
{% endif %}

{% if results|length > 0 %}
<p>총 {{ results|length }}개의 자원을 찾았습니다.</p>
{% for r in results %}
<div style="cursor:pointer;color:#0078d7;"
onclick="openDetail({{ r['index'] }})">
🔹 {{ loop.index }}. {{ r['프로그램명칭'] }}
</div>
{% endfor %}
{% else %}
<p>조건에 맞는 자원이 없습니다.</p>
{% endif %}
</div>
{% endif %}
</div>

<!-- 동일 팝업 -->
<div id="modal" style="display:none;position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,.5)">
<div style="background:white;margin:5% auto;padding:20px;width:90%;max-width:500px;border-radius:10px">
<h3 id="m_title"></h3>
<p><b>기관명:</b> <span id="m_org"></span></p>

<!-- ★기존 줄 교체 -->
<p>
<b>기관 연락처:</b> <span id="m_tel"></span>
<a id="tel_link" class="tel-link" style="display:none;">📞</a>
</p>

<p><b>기관주소:</b> <span id="m_addr"></span></p>
<iframe id="m_map" width="100%" height="250" style="border:0"></iframe>
<button onclick="closeModal()">닫기</button>
</div>
</div>

<script>
/* ★추가 */
function isMobile(){
  return /Android|iPhone|iPad|iPod/i.test(navigator.userAgent);
}

function openDetail(idx){
fetch("/detail/"+idx)
.then(r=>r.json())
.then(d=>{
m_title.innerText=d["프로그램명칭"];
m_org.innerText=d["기관명"];
m_tel.innerText=d["기관 연락처"];
m_addr.innerText=d["기관주소"];
m_map.src="https://www.google.com/maps?q="+encodeURIComponent(d["기관주소"])+"&output=embed";

const telLink=document.getElementById("tel_link");
if(isMobile() && d["기관 연락처"]){
  const numMatch = d["기관 연락처"].match(/[0-9-]+/);
  if(numMatch){
    telLink.href="tel:"+numMatch[0];
    telLink.style.display="inline";
  }else{
    telLink.style.display="none";
  }
}else{
  telLink.style.display="none";
}

modal.style.display="block";
});
}
function closeModal(){ modal.style.display="none"; }
</script>
</body>
</html>
"""

def semantic_search(query, top_k=7):
    global doc_vectors, documents

    if rag_client is None:
        print("OPENAI API 없음 → 의미검색 비활성화")
        return df.head(0)

    if len(df) > 1500:
        print("데이터 너무 큼 — 상위 1500개만 사용")
        sample_df = df.head(1500)
    else:
        sample_df = df

    if doc_vectors is None:
        print("RAG 최초 생성 시작")

        documents = sample_df.apply(row_to_text, axis=1).tolist()


        emb = rag_client.embeddings.create(
            model="text-embedding-3-small",
            input=documents
        )
        doc_vectors = np.array([e.embedding for e in emb.data])
        print("RAG 준비 완료:", len(doc_vectors))

    q_emb = rag_client.embeddings.create(
        model="text-embedding-3-small",
        input=query
    ).data[0].embedding

    sims = cosine_similarity([q_emb], doc_vectors)[0]
    top_idx = sims.argsort()[-top_k:][::-1]

    return sample_df.iloc[top_idx]



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
        found = filter_dataframe_by_conditions(df, gpt_json)

        results = found.reset_index()[["index","프로그램명칭"]].to_dict("records")

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


