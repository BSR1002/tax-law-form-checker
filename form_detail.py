import os
import requests
from dotenv import load_dotenv

load_dotenv()

law_oc = os.getenv("LAW_OC")

url = "https://www.law.go.kr/DRF/lawService.do"

params = {
    "OC": law_oc,
    "target": "eflaw",
    "type": "JSON",
    "MST": "287787",
    "efYd": "20260701"
}

response = requests.get(url, params=params, timeout=20)
response.raise_for_status()

data = response.json()

law = data.get("법령", {})

print("법인세법 시행규칙 상세 조회 성공")
print("HTTP 상태코드:", response.status_code)
print("법령 내부 항목:")
print(list(law.keys()))

byl = law.get("별표", {})

print("별표 데이터 형식:", type(byl).__name__)

if isinstance(byl, dict):
    print("별표 내부 항목:")
    print(list(byl.keys()))


    byl_units = byl.get("별표단위", [])

print("별표단위 데이터 형식:", type(byl_units).__name__)

if isinstance(byl_units, list):
    print("별표단위 개수:", len(byl_units))
    if byl_units:
        print("첫 번째 별표단위 항목:")
        print(list(byl_units[0].keys()))


target_title = "법인세 과세표준 및 세액조정계산서"

for unit in byl_units:
    title = unit.get("별표제목", "") or ""

    if target_title in title:
        print("-" * 50)
        print("대상 서식 찾음")
        print("별표번호:", unit.get("별표번호"))
        print("별표제목:", unit.get("별표제목"))
        print("별표제목문자열:", unit.get("별표제목문자열"))
        print("별표시행일자:", unit.get("별표시행일자"))

        content = unit.get("별표내용", "") or ""

        print("'개정' 문구 포함 여부:", "개정" in content)

        if "개정" in content:
            index = content.find("개정")
            start = max(0, index - 100)
            end = index + 150
            print("개정 문구 주변 내용:")
            print(content[start:end])

        print("-" * 50)
        break