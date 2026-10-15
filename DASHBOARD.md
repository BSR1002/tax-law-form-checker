# Figma 법령 변경 모니터 연결

게시 화면: https://kiosk-green-29140301.figma.site/

## 공개 데이터 주소

https://raw.githubusercontent.com/BSR1002/tax-law-form-checker/main/public/monitoring.json

읽기 전용 공개 JSON입니다. 인증키나 GitHub 토큰은 필요하지 않습니다.
브라우저에서는 이 파일만 GET하고 국가법령정보센터 API를 직접 호출하지 않습니다.
raw 파일 배포 캐시로 인해 갱신 내용이 즉시 반영되지 않을 수 있습니다.
웹 화면은 마지막 확인 시각을 표시하고 오래된 결과를 최신 확인으로 오인하지 않도록 해야 합니다.

## 생성 및 갱신

`dashboard_monitor.py`는 기존 `law_monitor.run`을 사용합니다. 3분 간격으로 최대 3회
시도한 뒤 `public/monitoring.json`을 원자적으로 저장합니다. 기존 법령 변경 알림과
오류 이슈 정책은 유지합니다. Daily law monitor workflow가 성공과 조회 실패 모두에서
공개 결과를 커밋하며 실패 시 비교 기준 파일은 커밋하지 않습니다.

초기 공개 파일의 법령 값은 기존 baseline에서 가져왔지만 조회 성공 시각은 알 수 없어
`unverified`로 표시합니다. 첫 실제 실행부터 확인 시각과 이력을 기록합니다.
과거 GitHub 실행 기록을 소급 생성하지 않습니다. 이력은 최근 90일을 유지하며
`history_started_at`은 이력 수집 시작 시각입니다. `runs`의 각 항목은 재시도 3번을
포괄하는 한 실행입니다. 재실행은 GitHub run attempt로 구분합니다.

## 스키마 버전 1

- `schema_version`: 1, `data_mode`: live, `timezone`: Asia/Seoul.
- `generated_at`: 파일 생성 시각. 조회 성공 시각이 아닙니다.
- `last_checked_at`: 마지막 실행에서 시도가 끝난 시각. 초기에는 null.
- `last_success_at`: 마지막 전체 모니터링 성공 시각. 초기/성공 이력 없으면 null.
- `latest_run`: 마지막 실행 결과 또는 null.
- `laws`: id, name, category, effective_date, mst, status, checked_at,
  last_success_at, original_url.
- `effective_date`: YYYYMMDD 문자열. `mst`도 문자열로 취급합니다.
- `status`: changed / unchanged / baseline_initialized / check_failed / unverified.
- `changes`: id, law_id, law_name, detected_at, previous, current,
  changed_fields, run_url, issue_url. previous/current는 effective_date, mst만 포함합니다.
- `runs`: id, checked_at, status(success/failed), result, attempts,
  changed_count, error_summary, run_url, issue_url.
- `result`: no_changes / baseline_initialized / changes_notified / failed.
- 날짜·시각은 UTC offset을 포함한 ISO 8601이며 화면에서 KST로 변환합니다.
- 제공되지 않은 원문/이슈 URL은 null입니다. 임의로 생성하지 않습니다.
- 실패 시 changed_count는 null입니다. 0건이나 변경 없음으로 바꾸지 않습니다.
- 실패 시 법령 값과 last_success_at은 마지막 정상 데이터를 유지합니다.
- 모니터 실패에는 API 조회뿐 아니라 변경 알림 실패도 포함됩니다.

## Figma Make 수정 지침

현재 화면과 데모 모드는 유지하고 실제 모드의 데이터 어댑터만 위 주소에 연결합니다.
필드 이름은 기존 UI 타입으로 변환합니다. last_checked_at과 last_success_at을
각각 표시하고, null은 데이터 미제공으로 표시합니다. last_success_at이 null이면
실패 화면에서 '마지막 정상 데이터'라고 단정하지 않습니다.
법령 목록의 변경 없음과 과거 changes의 변경 감지는 서로 다른 기준입니다.
최근 30일 변경 법령 수는 changes를 기간 필터 후 law_id로 중복 제거해 계산합니다.
조회 실패 실행 수는 runs 중 해당 기간의 failed 개수입니다.
최초 기준 등록은 변경으로 계산하지 않습니다.
전체 카드/목록은 동일한 데이터를 사용합니다.

`unverified`는 미확인, `check_failed`는 확인 실패로 표시합니다.
본문 비교, 세무 영향, 과거 실행 이력은 만들지 않습니다. 미래 시행 연혁을 포함할
수 있으므로 '현재 시행 법령'으로 단정하지 않습니다.
연결 실패 시 오류 안내를 표시하고 데모로 자동 전환하지 않습니다.
새로고침은 JSON 재조회만 수행하며 Actions나 이슈를 실행하지 않습니다.

## 검증

`python -m unittest -v test_law_monitor test_dashboard_monitor`

이 검증은 외부 API를 호출하지 않습니다. 실제 API/자동 커밋 결과는 다음
Daily law monitor 실행 후 확인해야 합니다. Actions 자체가 시작되지 않거나
데이터 저장 전에 중단되면 파일 갱신도 없으므로 시간 경과에 따른 오래된 정보
안내가 필요합니다. 웹 연동 후 브라우저에서 접근·오류·KST 변환을 확인합니다.
