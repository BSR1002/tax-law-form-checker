## Open API 기반 최신법령·서식 변경점검 PoC

세무조정 업무에서 반복적으로 수행하던 법령·서식 개정 확인을 자동화하기 위해 기획한 프로젝트입니다.
국가법령정보센터 Open API를 활용해 HWP Hash → PDF Text → 상세 변경 비교의 단계적 검증 구조를 구현했습니다.

* Role: 업무 문제 정의 · 비교 Rule/예외 기준 설계 · 결과 검증 및 개선
* Implementation: 생성형 AI 활용 Python 구현
* Tech: Python · Open API · Streamlit · GitHub
* 검증: 3개 시행규칙 / 816개 서식 비교 · 변경 서식 7개 탐지 · 상세 변경 82건 추출



\---

# 법령서식 Scanner / Comparator

* Scanner(스캔): 전체 서식을 번호+가지번호로 매칭하고 HWP SHA-256, PDF 텍스트 순서로 비교합니다.
* Comparator(비교): `comparator.py`에서 개별 서식의 구체적인 문자 변경을 분석합니다.
Scanner가 PDF 텍스트 변경을 감지하면 자동 호출합니다. 기존 `form\_history.py`는 독립 실행용입니다.

## 설치 및 실행

```bash
python -m pip install -r requirements.txt
cp .env.example .env
```

`.env`에 기존 국가법령정보센터 OPEN API의 `LAW\_OC`를 입력합니다.

```bash
python scanner.py --mode MANUAL --law "법인세법 시행규칙"
python scanner.py --mode AUTO --law "법인세법 시행규칙"
python -m unittest -v
```

MANUAL은 표시되는 연혁 목록에서 현재/기준 번호를 선택합니다. 자동화 실행은
`--current 1 --previous 2`처럼 번호를 지정할 수 있지만, 실행할 때마다 목록이
달라질 수 있으므로 먼저 시행일자와 MST를 확인하세요.

## 모드 및 저장

MANUAL은 지정한 두 연혁을 비교하며 AUTO의 상태 파일을 수정하지 않습니다.
AUTO 최초 실행은 최신 연혁의 전체 HWP 해시를 기준 상태로 저장합니다.
최초 실행은 과거 대비 비교가 아니므로 신규/삭제 건수는 0입니다.
두 번째 실행부터 MST와 시행일자가 모두 같으면 파일 다운로드를 생략합니다.
새 연혁이면 저장된 HWP 해시를 재사용하여 이전 HWP 다운로드를 줄입니다.
최신 연혁은 API가 반환한 시행일자 내림차순 기준이며 미래 시행 연혁도 포함됩니다.

* `scan\_results.json`: 이번 결과와 비교한 연혁, 신규/삭제/텍스트 변경/변경 없음/확인 필요 서식.
* `scan\_state.json`: 성공한 AUTO의 기준 연혁, 서식 링크, HWP 해시, 검사한 PDF 텍스트 해시.
* `--output`, `--state`: 저장 경로 변경. 여러 법령은 법령별로 다른 상태 경로를 사용합니다.

각 파일은 임시 파일 작성 후 교체합니다. 결과를 먼저 저장하고 성공한 AUTO에서만
상태를 갱신합니다. 일부 서식의 다운로드/판독이 실패하면 `partial`로 저장하며
이전 성공 상태를 유지해 다음 실행에서 다시 검사합니다.
동일한 결과/상태 경로에 여러 실행을 동시에 진행하지 마세요.
검색/상세 API 자체가 실패하면 기존 결과/상태 파일은 유지되며 종료코드 1을 반환합니다.

## 판정 기준

공통 서식 전체의 HWP 파일을 비교합니다. 제목이나 시행일자가 같아도 생략하지 않습니다.
HWP가 다른 공통 서식만 PDF를 다운로드해 공백을 제외한 텍스트 해시를 비교합니다.
PDF 텍스트가 같으면 `unchanged\_forms`에 `pdf\_text\_equal` 사유를 기록합니다.
이는 텍스트 비교이며 표 배치, 이미지, 글꼴 등의 시각적 동일성을 보장하지 않습니다.
제목/시행일자 차이는 `metadata\_changed`에 별도로 남깁니다.

빈 파일, HTML 오류 응답, 누락 링크, PDF 판독 불가(텍스트 없는 페이지 포함)는
`review\_required\_forms`에 실패 단계와 오류 유형을 기록합니다.
HWPX는 현재 지원하지 않으며 HWP 파일 형식 검사에서 확인 필요로 분류합니다.
신규 서식은 현재 HWP를 검사하고, 삭제 서식은 이전 목록을 통해 판정합니다.
서식 번호+가지번호가 바뀐 경우에는 신규/삭제로 분류합니다.

종료코드: 0 정상(기준 생성/새 연혁 없음 포함), 1 실행 실패, 2 일부 서식 확인 필요.

## 실제 API 테스트 포인트

1. MANUAL: 2026-03-20과 2026-01-02를 선택해 서식 0003/00이 텍스트 변경에 포함되는지 확인.
2. MANUAL: 2026-01-02와 2025-10-31의 서식 0003/00은 기존 Comparator에서 변경 0건이었으므로 해당 서식의 판정을 대조.
3. AUTO 최초 실행 후 재실행: `baseline\_initialized` → `no\_new\_revision`, 파일 검사 생략 확인.
4. 결과 JSON의 신규·삭제·변경·확인 필요 항목과 연혁 MST/시행일자 확인.

기존의 '16건/0건'은 Comparator의 특정 서식 변경 구간 수입니다.
Scanner의 전체 변경 서식 수와 같은 수치가 아닙니다.
Scanner 실행만으로 변경 서식의 Comparator 상세 비교까지 수행합니다.
`changed\_forms\[].comparison.changes`에 `type`(insert/delete/replace), `old`, `new`와
공백 제거 후 텍스트 기준 위치(start 포함/end 제외)를 저장합니다.
`comparison.change\_count`는 서식별 변경 구간 수, `detail\_change\_count`는 전체 합계입니다.
짧은 번호 변경도 포함하며, 기존 법령명 머리말 삭제 제외 규칙은
`comparison.excluded\_changes`에 사유와 함께 남깁니다.
반복 문구를 놓치지 않도록 SequenceMatcher의 autojunk를 끄므로 기존 구간 수와 달라질 수 있습니다.

상세 비교 실패는 `review\_required\_forms`에 `failed\_stage: comparator`로 기록합니다.
이때 감지한 `pdf\_changed: true`도 유지하며 AUTO 기준 상태는 갱신하지 않습니다.
PDF 텍스트는 실행 중 재사용하여 재다운로드를 피합니다. 이전 해시만 저장되어 있는
AUTO에서는 상세 비교에 필요할 때 이전 PDF를 한 번 다운로드합니다.
기존 AUTO 상태 파일과 호환되며, 이미 점검한 연혁을 다시 상세 비교하려면 MANUAL을 사용하세요.

이번 작업 검증 범위
Scanner의 실제 API 검증은 사용자가 완료했다고 확인했습니다.
이번 Comparator 자동 연결은 로컬 자동 테스트로 검증했으며, 연결 후 실제 API 검증은 별도로 필요합니다.
자동 테스트는 API 응답/파일 비교를 대체한 데이터로 분류, 다운로드 생략,
오류 처리, 상태 보존, JSON 저장을 검증합니다.

