import os
import requests
import hashlib
import difflib
from io import BytesIO
from pypdf import PdfReader
from dotenv import load_dotenv

load_dotenv()

law_name = input("조회할 법령명을 입력하세요: ").strip()
form_name = input("조회할 서식명을 입력하세요: ").strip()

law_oc = os.getenv("LAW_OC")

url = "https://www.law.go.kr/DRF/lawSearch.do"

params = {
    "OC": law_oc,
    "target": "eflaw",
    "type": "JSON",
    "query": law_name,
    "nw": 1,
    "sort": "efdes",
    "display": 100
}

response = requests.get(url, params=params, timeout=20)
response.raise_for_status()

data = response.json()

laws = data.get("LawSearch", {}).get("law", [])

if isinstance(laws, dict):
    laws = [laws]

print(f"{law_name} 연혁 건수:", len(laws))
print("-" * 50)

for index, law in enumerate(laws[:10], start=1):
    print("선택번호:", index)
    print("상태:", law.get("현행연혁코드"))
    print("개정구분:", law.get("제개정구분명"))
    print("공포일자:", law.get("공포일자"))
    print("시행일자:", law.get("시행일자"))
    print("법령일련번호:", law.get("법령일련번호"))
    print("-" * 50)

current_input = input("비교할 현재 버전 선택번호를 입력하세요: ").strip()
previous_input = input("비교할 이전 버전 선택번호를 입력하세요: ").strip()

try:
    current_choice = int(current_input)
    previous_choice = int(previous_input)
except ValueError:
    print("선택번호는 숫자로 입력해주세요.")
    raise SystemExit

if current_choice <= 0 or previous_choice <= 0:
    print("선택번호는 1 이상의 숫자로 입력해주세요.")
    raise SystemExit


max_choice = min(10, len(laws))

if current_choice > max_choice or previous_choice > max_choice:
    print(f"선택번호는 1부터 {max_choice}까지 입력해주세요.")
    raise SystemExit

if current_choice == previous_choice:
    print("현재 버전과 이전 버전은 서로 다른 번호를 선택해주세요.")
    raise SystemExit


target_title = form_name

def normalize_search_text(text):
    return "".join(text.split())

def get_target_form(mst, efyd):
    detail_url = "https://www.law.go.kr/DRF/lawService.do"

    detail_params = {
        "OC": law_oc,
        "target": "eflaw",
        "type": "JSON",
        "MST": mst,
        "efYd": efyd
    }

    detail_response = requests.get(
        detail_url,
        params=detail_params,
        timeout=20
    )
    detail_response.raise_for_status()

    detail_data = detail_response.json()

    law_detail = detail_data.get("법령", {})
    byl = law_detail.get("별표", {})
    units = byl.get("별표단위", [])

    if isinstance(units, dict):
        units = [units]

    for unit in units:
        title = unit.get("별표제목", "") or ""

        normalized_title = normalize_search_text(title)
        normalized_target = normalize_search_text(target_title)

        if normalized_target in normalized_title:
            return unit

    return None


test_law = laws[current_choice - 1]

test_form = get_target_form(
    test_law.get("법령일련번호"),
    test_law.get("시행일자")
)

print("=" * 50)
print("연혁 서식 테스트")
print("시행일자:", test_law.get("시행일자"))
print("법령일련번호:", test_law.get("법령일련번호"))

file_hash = None
if test_form:
    print("서식 찾음")
    print("별표번호:", test_form.get("별표번호"))
    print("별표제목:", test_form.get("별표제목"))
    print("HWP파일:", test_form.get("별표서식파일링크"))
    print("PDF파일:", test_form.get("별표서식PDF파일링크"))
else:
    print("해당 서식을 찾지 못했습니다.")
    print("서식명을 확인한 후 다시 실행해주세요.")
    raise SystemExit


if test_form:
    hwp_link = test_form.get("별표서식파일링크")

    if hwp_link:
        file_url = "https://www.law.go.kr" + hwp_link

        file_response = requests.get(file_url, timeout=30)
        file_response.raise_for_status()

        print("HWP 다운로드 성공")
        print("파일 크기:", len(file_response.content), "bytes")

        file_hash = hashlib.sha256(file_response.content).hexdigest()
        print("HWP SHA256:", file_hash)


previous_law = laws[previous_choice - 1]
print("=" * 50)
print("비교 대상 연혁")
print("현재 시행일자:", test_law.get("시행일자"))
print("현재 법령일련번호:", test_law.get("법령일련번호"))
print("이전 시행일자:", previous_law.get("시행일자"))
print("이전 법령일련번호:", previous_law.get("법령일련번호"))



previous_form = get_target_form(
    previous_law.get("법령일련번호"),
    previous_law.get("시행일자")
)

if not previous_form:
  print("이전 연혁에서 해당 서식을 찾지 못했습니다.")
  print("다른 연혁을 선택하거나 서식명을 확인해주세요.")
  raise SystemExit



if previous_form:
    previous_hwp_link = previous_form.get("별표서식파일링크")

    if previous_hwp_link:
        previous_file_url = "https://www.law.go.kr" + previous_hwp_link

        previous_response = requests.get(
            previous_file_url,
            timeout=30
        )
        previous_response.raise_for_status()

        previous_hash = hashlib.sha256(
            previous_response.content
        ).hexdigest()

        print("=" * 50)
        print("직전 연혁 비교")
        print("직전 시행일자:", previous_law.get("시행일자"))
        print("직전 HWP SHA256:", previous_hash)

if file_hash is not None:
        print("파일 동일 여부:", file_hash == previous_hash)


def extract_pdf_text(pdf_link):
    pdf_url = "https://www.law.go.kr" + pdf_link

    pdf_response = requests.get(pdf_url, timeout=30)
    pdf_response.raise_for_status()

    reader = PdfReader(BytesIO(pdf_response.content))

    text_parts = []

    for page in reader.pages:
        page_text = page.extract_text() or ""
        text_parts.append(page_text)

    return "\n".join(text_parts)


current_pdf_link = test_form.get("별표서식PDF파일링크")
previous_pdf_link = previous_form.get("별표서식PDF파일링크")

if not current_pdf_link:
    print("현재 연혁의 PDF 서식 링크를 찾지 못했습니다.")
    raise SystemExit

if not previous_pdf_link:
    print("이전 연혁의 PDF 서식 링크를 찾지 못했습니다.")
    raise SystemExit



current_text = extract_pdf_text(current_pdf_link)
previous_text = extract_pdf_text(previous_pdf_link)

print("=" * 50)
print("PDF 실제 텍스트 비교")
print("현재 시행일자:", test_law.get("시행일자"))
print("직전 시행일자:", previous_law.get("시행일자"))
print("현재 PDF 텍스트 길이:", len(current_text))
print("직전 PDF 텍스트 길이:", len(previous_text))
print("PDF 텍스트 동일 여부:", current_text == previous_text)


def normalize_text(text):
    return " ".join(text.split())


current_normalized = normalize_text(current_text)
previous_normalized = normalize_text(previous_text)

print("=" * 50)
print("PDF 정규화 텍스트 비교")
print("현재 정규화 길이:", len(current_normalized))
print("직전 정규화 길이:", len(previous_normalized))
print("정규화 후 동일 여부:", current_normalized == previous_normalized)


current_lines = [
    line.strip()
    for line in current_text.splitlines()
    if line.strip()
]

previous_lines = [
    line.strip()
    for line in previous_text.splitlines()
    if line.strip()
]

diff = list(
    difflib.unified_diff(
        previous_lines,
        current_lines,
        fromfile=str(previous_law.get("시행일자")),
        tofile=str(test_law.get("시행일자")),
        lineterm=""
    )
)

print("=" * 50)
print("PDF 변경 내용")

for line in diff[:80]:
    print(line)

def compact_text(text):
   return "".join(text.split())


current_compact = compact_text(current_text)
previous_compact = compact_text(previous_text)

print("=" * 50)
print("PDF 공백 완전 제거 비교")
print("현재 글자 수:", len(current_compact))
print("직전 글자 수:", len(previous_compact))
print("내용 동일 여부:", current_compact == previous_compact)


similarity = difflib.SequenceMatcher(
    None,
    previous_compact,
    current_compact
).ratio()

print("=" * 50)
print("PDF 내용 유사도")
print("유사도:", round(similarity * 100, 2), "%")


matcher = difflib.SequenceMatcher(
    None,
    previous_compact,
    current_compact
)

print("=" * 50)
print("실제 문자 변경 후보")

change_count = 0

for tag, i1, i2, j1, j2 in matcher.get_opcodes():
    if tag != "equal":
        change_count += 1

        old_text = previous_compact[i1:i2]
        new_text = current_compact[j1:j2]

        print("-" * 50)
        print("변경 유형:", tag)
        print("이전:", old_text[:300])
        print("현재:", new_text[:300])

print("-" * 50)
print("변경 후보 구간 수:", change_count)


minor_changes = []
content_changes = []

for tag, i1, i2, j1, j2 in matcher.get_opcodes():
    if tag == "equal":
        continue

    old_text = previous_compact[i1:i2]
    new_text = current_compact[j1:j2]

    # 아주 짧은 변경은 번호 변경 등으로 우선 분리
    if len(old_text) <= 3 and len(new_text) <= 3:
        minor_changes.append({
            "type": tag,
            "old": old_text,
            "new": new_text
        })
    else:
        content_changes.append({
            "type": tag,
            "old": old_text,
            "new": new_text
        })

print("=" * 50)
print("변경 후보 분류 결과")
print("내용 변경 후보:", len(content_changes), "건")
print("단순 번호/짧은 변경 후보:", len(minor_changes), "건")

print("-" * 50)
print("단순 번호/짧은 변경 후보")

for change in minor_changes:
    print("유형:", change["type"])
    print("이전:", change["old"])
    print("현재:", change["new"])
    print("-" * 50)


print("-" * 50)
print("내용 변경 후보")

for change in content_changes:
    print("유형:", change["type"])
    print("이전:", change["old"][:300])
    print("현재:", change["new"][:300])
    print("-" * 50)

meaningful_changes = []

law_header = "■" + normalize_search_text(law_name)

for change in content_changes:
    old_text = change["old"]
    new_text = change["new"]

    # PDF에서 반복적으로 잡히는 법령명 머리말은 제외
    if old_text == law_header and new_text == "":
        continue

    meaningful_changes.append(change)

print("=" * 50)
print("내용 변경 검토 대상")
print("내용 변경:", len(meaningful_changes), "건")

for change in meaningful_changes:
    print("-" * 50)
    print("유형:", change["type"])
    print("이전:", change["old"][:300])
    print("현재:", change["new"][:300])

results = meaningful_changes + minor_changes

print("=" * 50)
print("비교 완료")
print("최종 의미 있는 변경 후보:", len(results), "건")
print(results)