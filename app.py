from flask import Flask, render_template_string, request
import pandas as pd

app = Flask(__name__)

# 엑셀 파일 경로
EXCEL_PATH = 'service_resources.xlsx'

# HTML 템플릿 (단일 파일 구조)
HTML = '''
<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="UTF-8">
  <title>지자체 서비스자원 검색</title>
  <style>
    body { font-family: Pretendard, sans-serif; max-width: 720px; margin: 30px auto; padding: 10px; }
    input, select { width: 100%; padding: 8px; margin-bottom: 10px; border-radius: 8px; border: 1px solid #ccc; }
    button { padding: 10px 15px; border: none; border-radius: 8px; background-color: #007bff; color: white; cursor: pointer; }
    button:hover { background-color: #0056b3; }
    .result { margin-top: 30px; padding: 15px; border-radius: 12px; background: #f8f9fa; }
    h2 { font-size: 20px; }
  </style>
</head>
<body>
  <h1>지자체 서비스자원 검색 시스템</h1>
  <form method="POST">
    <label>연령 (이상):</label>
    <input type="number" name="age" placeholder="예: 70">

    <label>가구유형:</label>
    <select name="family">
      <option value="">무관</option>
      <option value="독거">독거</option>
      <option value="다인가구">다인가구</option>
    </select>

    <label>장애여부:</label>
    <select name="disability">
      <option value="">무관</option>
      <option value="Y">Y</option>
      <option value="N">N</option>
    </select>

    <label>방문형서비스:</label>
    <select name="visit">
      <option value="">무관</option>
      <option value="Y">Y</option>
      <option value="N">N</option>
    </select>

    <label>지역:</label>
    <input type="text" name="region" placeholder="예: 중랑구">

    <label>기타 키워드:</label>
    <input type="text" name="keyword" placeholder="예: 정서지원, 에너지">

    <button type="submit">검색하기 🔍</button>
  </form>

  {% if results is not none %}
  <div class="result">
    {% if results|length == 0 %}
      <p>조건에 일치하는 자원이 없습니다.</p>
    {% else %}
      <h2>검색 결과 (총 {{ results|length }}건)</h2>
      <ul>
      {% for item in results %}
        <li>{{ item }}</li>
      {% endfor %}
      </ul>
    {% endif %}
  </div>
  {% endif %}
</body>
</html>
'''

@app.route('/', methods=['GET', 'POST'])
def search():
    df = pd.read_excel(EXCEL_PATH)
    results = None

    if request.method == 'POST':
        age = request.form.get('age')
        family = request.form.get('family')
        disability = request.form.get('disability')
        visit = request.form.get('visit')
        region = request.form.get('region', '').strip()
        keyword = request.form.get('keyword', '').strip()

        filtered = df.copy()

        if age:
            filtered = filtered[filtered['연령'] <= int(age)]
        if family:
            filtered = filtered[filtered['가구유형'].astype(str).str.contains(family)]
        if disability:
            filtered = filtered[filtered['장애여부'].astype(str) == disability]
        if visit:
            filtered = filtered[filtered['방문형서비스'].astype(str) == visit]
        if region:
            filtered = filtered[filtered['지역'].astype(str).str.contains(region)]
        if keyword:
            filtered = filtered[filtered['기타'].astype(str).str.contains(keyword)]

        results = filtered['프로그램명칭'].dropna().unique().tolist()

    return render_template_string(HTML, results=results)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000, debug=True)
