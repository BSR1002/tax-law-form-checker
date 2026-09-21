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
    "search": 1,
    "query": "법인세 과세표준 및 세액조정계산서",
    "knd": 3,
    "display": 20
}

response = requests.get(url, params=params, timeout=20)
response.raise_for_status()

data = response.json()

print("서식 검색 요청 성공")
print("HTTP 상태코드:", response.status_code)
print("응답 최상위 항목:", list(data.keys()))