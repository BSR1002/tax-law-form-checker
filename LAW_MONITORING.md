# 매일 법령 버전 모니터링

법인세법 시행규칙, 소득세법 시행규칙, 조세특례제한법 시행규칙만 관리합니다.
기존 `LawClient.histories(name)[0]`의 시행일자와 MST를 함께 비교합니다.
기존 histories 정렬을 그대로 따르므로 미래 시행일 버전이 먼저 반환되면 그 버전도 감지합니다.
법령 버전 변경은 개별 서식 변경의 확정 판정이 아닙니다.

최초 실행은 `law_monitor_state.json`을 생성하고 알림 없이 기준으로 커밋합니다.
변경이 없으면 Issue와 커밋을 만들지 않습니다. 변경 시 세 법령의 상태를 한 Issue로
알리고 성공한 뒤 새 state를 저장합니다. 일부 API 조회 또는 Issue 생성이 실패하면
state를 갱신하지 않습니다. state 커밋/푸시 실패 후 재실행해도 동일 변경의 Issue는
본문 식별값으로 찾아 재사용합니다(닫힌 Issue 포함). Issue를 삭제하면 중복 방지가 불가능합니다.
HWP/PDF 다운로드나 Scanner 실행은 없으며 알림 후 사람이 MANUAL 상세 비교합니다.

## 설정

1. 추가된 네 파일을 저장소 기본 브랜치에 반영합니다. state는 직접 만들지 않습니다.
2. Settings → Secrets and variables → Actions → New repository secret에서
   `LAW_OC`에 발급받은 값을 등록합니다. 코드/커밋/Issue에 키를 입력하지 마세요.
3. 저장소 Issues를 활성화하고 Actions의 contents/Issues 쓰기 권한을 허용합니다.
   기본 브랜치 보호 규칙이 봇의 상태 커밋을 막으면 관리자 정책 조정이 필요합니다.
4. Actions → Daily law monitor → Run workflow에서 기본 브랜치를 선택합니다.
   최초 결과는 `baseline_initialized`, 두 번째는 `no_changes`여야 합니다.
5. GitHub Watch → Custom → Issues 및 계정 이메일 알림을 설정합니다.
   Issue 생성만으로 모든 사용자에게 이메일이 전달되지는 않습니다.

매일 UTC 00:00(한국시간 오전 9시) 실행 예정이며 GitHub 상황에 따라 지연될 수 있습니다.
예약 실행은 기본 브랜치에서 동작합니다. 공개 저장소의 장기 비활동으로 예약이 중단되면
Actions에서 다시 활성화하세요. 오류 실행은 Actions 탭에서 확인하세요.

## 테스트

`python -m pip install -r requirements.txt`

`python -m unittest -v test_law_monitor`

테스트는 API 키나 네트워크 없이 baseline, 변경 없음, 날짜/MST 변경, 복수 변경,
조회 실패, 알림 실패, 인증정보 로그 차단, 재실행 Issue 중복 방지를 확인합니다.
실제 API와 GitHub 쓰기는 위 수동 실행으로 확인합니다.
