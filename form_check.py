import os
import requests
from dotenv import load_dotenv

load_dotenv()

law_oc = os.getenv("LAW_OC")

url = "https://www.law.go.kr/DRF/lawSearch.do"

params = {
    "OC": law_oc,
    "target": "licbyl",
    "type": "JSON",
    "search": 2,
    "query":  "법인세법 시행규칙",
    "display": 200
}

response = requests.get(url, params=params, timeout=20)
response.raise_for_status()

data = response.json()

result = data.get("licBylSearch", {})

forms = result.get("licbyl", [])

if isinstance(forms, dict):
    forms = [forms]

print("검색 건수:", result.get("totalCnt"))
print("-" * 50)

target_form = "법인세 과세표준 및 세액조정계산서"

for form in forms:
    form_name = form.get("별표명", "")

    if target_form in form_name:
        print("찾았습니다!")
        print("-" * 50)
        print("서식명:", form.get("별표명"))
        print("관련법령명:", form.get("관련법령명"))
        print("별표번호:", form.get("별표번호"))
        print("별표종류:", form.get("별표종류"))
        print("공포일자:", form.get("공포일자"))
        print("개정구분:", form.get("제개정구분명"))
        print("관련법령일련번호:", form.get("관련법령일련번호"))
        print("별표일련번호:", form.get("별표일련번호"))
        print("HWP파일링크:", form.get("별표서식파일링크"))
        print("PDF파일링크:", form.get("별표서식PDF파일링크"))
        print("-" * 50)