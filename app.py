from flask import Flask, render_template_string, request, jsonify
import pandas as pd
import os
import re

# ★ .env 파일에서 API키 불러오기
from dotenv import load_dotenv
load_dotenv()

app = Flask(__name__)

from openai import OpenAI
client = OpenAI()

FILE_PATH = "service_resources.xlsx"

try:
    df = pd.read_excel(FILE_PATH)
    df.columns = df.columns.str.replace(" ","")   # ★ 여기 추가
except Exception as e:
    print("엑셀 로드 실패:", e)
    df = pd.DataFrame()

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

def ai_extract_condition(text):

    prompt = f"""
너는 복지 서비스 검색 시스템이다.
사용자의 문장에서 검색 조건을 JSON으로 추출해라.

가능한 키:
지역
연령
가구유형
서비스욕구

설명 없이 JSON만 출력해라.

문장:
{text}
"""

    try:
        res = client.responses.create(
            model="gpt-4.1-mini",
            input=prompt,
            temperature=0
        )

        import json
        import re

        content = res.output[0].content[0].text

        # JSON 부분만 추출
        match = re.search(r'\{.*\}', content, re.S)
        if match:
            return json.loads(match.group())
        else:
            return {}

    except Exception as e:
        print("GPT 조건추출 실패:", e)
        return {}



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
    query=""
    results=None
    message=None
    cond_display=[]

    if request.method=="POST":
        query=request.form["query"]
    

        # GPT 조건 추출
        cond = ai_extract_condition(query)

        import sys
        try:
            print("GPT 추출:", cond, flush=True)
            sys.stdout.flush()
        except Exception as e:
            print("로그출력실패:", e, flush=True)

        cond_display=[]
        if isinstance(cond, dict):
            for k,v in cond.items():
                cond_display.append(f"{k}: {v}")


        if not cond:
            message="검색어에서 조건을 찾지 못했습니다."
            results=[]
            cond_display=[]
        else:
            f=df.copy()

            # AND 조건
            if "지역" in cond and "지역" in df.columns:
                f=f[f["지역"].astype(str).str.contains(str(cond["지역"]),na=False)]

            if "연령" in cond and "연령" in df.columns:
                try:
                    age=int(re.sub(r'[^0-9]', '', str(cond["연령"])) or 0)
                    f=f[pd.to_numeric(f["연령"],errors="coerce")>=age]
                except:
                    pass

            # OR 조건
            or_mask=None
            for key in ["가구유형","서비스욕구"]:
                if key in cond and key in df.columns:
                    m=f[key].astype(str).str.contains(str(cond[key]),na=False)
                    or_mask = m if or_mask is None else (or_mask | m)

            if or_mask is not None:
                f=f[or_mask]

            results=f.reset_index()[["index","프로그램명칭"]].dropna().to_dict("records")

    return render_template_string(
        DESC_HTML,
        style=BASE_STYLE,
        query=query,
        results=results,
        message=message,
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



if __name__=="__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
