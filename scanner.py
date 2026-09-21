"""Scanner(스캔): HWP 전체 해시 검사 후 PDF 텍스트 2차 비교."""
import argparse
import hashlib
import html
import json
import os
import tempfile
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from urllib.parse import urljoin

import requests
from dotenv import load_dotenv
from pypdf import PdfReader
from comparator import compare_texts

BASE = "https://www.law.go.kr"


def clean(value):
    return html.unescape(str(value or "")).strip()


def compact(value):
    return "".join(clean(value).split())


def items(value):
    return [value] if isinstance(value, dict) else (value or [])


class LawClient:
    def __init__(self, oc):
        self.oc = oc
        self.session = requests.Session()
        self.pdf_text_cache = {}

    def api(self, endpoint, **params):
        r = self.session.get(BASE + "/DRF/" + endpoint,
            params={"OC": self.oc, "target": "eflaw", "type": "JSON", **params}, timeout=30)
        r.raise_for_status()
        return r.json()

    def histories(self, name):
        found = {}
        page = 1
        while True:
            data = self.api("lawSearch.do", query=name, nw="1,3", sort="efdes", display=100, page=page)
            if not isinstance(data.get("LawSearch"), dict):
                raise ValueError("법령 검색 응답 오류")
            block = data["LawSearch"]
            rows = items(block.get("law"))
            for row in rows:
                if compact(row.get("법령명한글")) != compact(name):
                    continue
                rev = {"mst": clean(row.get("법령일련번호")),
                       "effective_date": clean(row.get("시행일자"))}
                if not rev["mst"].isdigit() or not rev["effective_date"].isdigit():
                    raise ValueError("연혁 MST/시행일자 오류")
                found[(rev["mst"], rev["effective_date"])] = rev
            if page * 100 >= int(block.get("totalCnt", len(rows))) or not rows:
                break
            page += 1
        if not found:
            raise ValueError("정확한 법령명에 해당하는 연혁이 없습니다.")
        return sorted(found.values(), key=lambda r: (r["effective_date"], int(r["mst"])), reverse=True)

    def forms(self, rev):
        data = self.api("lawService.do", MST=rev["mst"], efYd=rev["effective_date"])
        law = data.get("법령")
        if not isinstance(law, dict) or "기본정보" not in law:
            raise ValueError("법령 상세 응답 오류")
        result = {}
        for unit in items((law.get("별표") or {}).get("별표단위")):
            if clean(unit.get("별표구분")) != "서식":
                continue
            number = clean(unit.get("별표번호"))
            branch = clean(unit.get("별표가지번호")) or "0"
            if not number.isdigit() or not branch.isdigit():
                raise ValueError("서식 번호/가지번호 오류")
            number, branch = number.zfill(4), branch.zfill(2)
            key = number + ":" + branch
            if key in result:
                raise ValueError("중복 서식 식별값: " + key)
            result[key] = {"number": number, "branch_number": branch,
                "title": clean(unit.get("별표제목문자열") or unit.get("별표제목")),
                "effective_date": clean(unit.get("별표시행일자")),
                "hwp_url": clean(unit.get("별표서식파일링크")),
                "pdf_url": clean(unit.get("별표서식PDF파일링크"))}
        return result

    def download(self, link, kind):
        if not link:
            raise ValueError(kind.upper() + " 링크 없음")
        r = self.session.get(urljoin(BASE, html.unescape(link)), timeout=30)
        r.raise_for_status()
        signature = b"%PDF-" if kind == "pdf" else bytes.fromhex("d0cf11e0a1b11ae1")
        if not r.content.startswith(signature):
            raise ValueError(kind.upper() + " 파일 형식 오류")
        return r.content

    def hwp_hash(self, form):
        return hashlib.sha256(self.download(form["hwp_url"], "hwp")).hexdigest()

    def pdf_text(self, form):
        link = form["pdf_url"]
        if link in self.pdf_text_cache:
            return self.pdf_text_cache[link]
        reader = PdfReader(BytesIO(self.download(form["pdf_url"], "pdf")))
        pages = [compact(page.extract_text() or "") for page in reader.pages]
        if not pages or any(not page for page in pages):
            raise ValueError("PDF 텍스트 판독 불가")
        text = "".join(pages)
        self.pdf_text_cache[link] = text
        return text

    def pdf_hash(self, form):
        return hashlib.sha256(self.pdf_text(form).encode("utf-8")).hexdigest()


def atomic_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         delete=False, suffix=".tmp") as stream:
            temporary = stream.name
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        os.replace(temporary, path)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)


def load_state(path, name):
    if not Path(path).exists():
        return None
    state = json.loads(Path(path).read_text(encoding="utf-8"))
    if state.get("schema_version") != 1 or state.get("law_name") != name:
        raise ValueError("상태 파일 버전/법령명이 다릅니다. 별도 --state 경로를 사용하세요.")
    rev = state.get("current", {})
    if not rev.get("mst") or not rev.get("effective_date") or not isinstance(state.get("forms"), dict):
        raise ValueError("상태 파일이 손상되었습니다.")
    for form in state["forms"].values():
        if not all(k in form for k in ("number", "branch_number", "title", "effective_date",
                                      "hwp_url", "pdf_url")) or not form.get("hwp_sha256"):
            raise ValueError("상태 파일의 서식 정보가 불완전합니다.")
    return state


def result_header(name, mode, current, previous):
    return {"schema_version": 1, "law_name": name, "mode": mode,
        "scanned_at": datetime.now(timezone.utc).isoformat(),
        "current": current, "previous": previous, "new_forms": [], "deleted_forms": [],
        "changed_forms": [], "unchanged_forms": [], "review_required_forms": [],
        "unchanged_count": 0, "baseline_count": 0, "detail_change_count": 0}


def scan(client, name, mode, current, previous, old_forms=None, progress=print):
    if isinstance(client, LawClient):
        client.pdf_text_cache.clear()
    now_forms = client.forms(current)
    old_forms = old_forms if old_forms is not None else (client.forms(previous) if previous else {})
    result = result_header(name, mode, current, previous)
    result["status"] = "completed" if previous else "baseline_initialized"
    for index, key in enumerate(sorted(now_forms), 1):
        now, old = now_forms[key], old_forms.get(key)
        row = {"number": now["number"], "branch_number": now["branch_number"],
            "title": now["title"], "current": now, "previous": old,
            "hwp_changed": None, "pdf_changed": None}
        stage = "current_hwp"
        try:
            now["hwp_sha256"] = client.hwp_hash(now)
            if old is None:
                if previous:
                    result["new_forms"].append(row)
                else:
                    result["baseline_count"] += 1
            else:
                stage = "previous_hwp"
                old_hash = old.get("hwp_sha256") or client.hwp_hash(old)
                row["hwp_changed"] = now["hwp_sha256"] != old_hash
                row["metadata_changed"] = any(now[k] != old[k] for k in ("title", "effective_date"))
                row["previous_hwp_sha256"] = old_hash
                if row["hwp_changed"]:
                    stage = "previous_pdf"
                    old_pdf = old.get("pdf_text_sha256") or client.pdf_hash(old)
                    stage = "current_pdf"
                    now["pdf_text_sha256"] = client.pdf_hash(now)
                    row["pdf_changed"] = old_pdf != now["pdf_text_sha256"]
                    if row["pdf_changed"]:
                        stage = "comparator"
                        previous_text = client.pdf_text(old)
                        current_text = client.pdf_text(now)
                        # 저장된 해시와 다시 받은 이전 PDF가 다르면 정확한 비교를 보장할 수 없다.
                        if hashlib.sha256(previous_text.encode("utf-8")).hexdigest() != old_pdf:
                            raise ValueError("이전 PDF가 저장된 해시와 다릅니다.")
                        row["comparison"] = compare_texts(previous_text, current_text, name)
                row["reason"] = "pdf_text_changed" if row["pdf_changed"] else (
                    "pdf_text_equal" if row["hwp_changed"] else "hwp_equal")
                result["changed_forms" if row["pdf_changed"] else "unchanged_forms"].append(row)
        except Exception as exc:
            # 서식별 오류를 기록하고 나머지 검사를 계속한다. 인증값 포함 URL은 기록하지 않는다.
            row.update(reason="comparison_failed", failed_stage=stage, error_type=type(exc).__name__)
            if stage == "comparator":
                row["comparison"] = {"status": "failed", "error_type": type(exc).__name__}
            result["review_required_forms"].append(row)
        if progress and (index % 20 == 0 or index == len(now_forms)):
            progress(f"Scanner: {index}/{len(now_forms)} 서식 검사")
    result["deleted_forms"] = [old_forms[k] for k in sorted(old_forms.keys() - now_forms.keys())]
    result["unchanged_count"] = len(result["unchanged_forms"])
    result["detail_change_count"] = sum(
        row["comparison"]["change_count"] for row in result["changed_forms"])
    result["current_count"], result["previous_count"] = len(now_forms), len(old_forms)
    if result["review_required_forms"]:
        result["status"] = "partial"
    state = {"schema_version": 1, "law_name": name, "current": current, "forms": now_forms}
    return result, state


def run(client, name, mode, output, state_path, current=None, previous=None, progress=print):
    mode = mode.upper()
    if mode not in ("AUTO", "MANUAL"):
        raise ValueError("모드는 AUTO 또는 MANUAL이어야 합니다.")
    if Path(output).resolve() == Path(state_path).resolve():
        raise ValueError("결과/상태 파일 경로는 달라야 합니다.")
    state = load_state(state_path, name) if mode == "AUTO" else None
    if mode == "AUTO":
        current = client.histories(name)[0]
        previous = state["current"] if state else None
        if current == previous:
            result = result_header(name, mode, current, previous)
            result.update(status="no_new_revision", skipped_count=len(state["forms"]))
            atomic_json(output, result)
            return result
    elif not current or not previous or current == previous:
        raise ValueError("MANUAL에서는 서로 다른 두 연혁이 필요합니다.")
    if previous and current["effective_date"] < previous["effective_date"]:
        raise ValueError("현재 연혁이 기준 연혁보다 과거입니다.")
    result, next_state = scan(client, name, mode, current, previous,
                             state["forms"] if state else None, progress)
    atomic_json(output, result)
    if mode == "AUTO" and result["status"] != "partial":
        atomic_json(state_path, next_state)
    return result


def main():
    load_dotenv()
    parser = argparse.ArgumentParser(description="Scanner(스캔): 전체 법령서식 변경 감지")
    parser.add_argument("--mode", choices=["AUTO", "MANUAL"], default="MANUAL")
    parser.add_argument("--law")
    parser.add_argument("--current", type=int, help="MANUAL 현재 연혁 선택번호")
    parser.add_argument("--previous", type=int, help="MANUAL 기준 연혁 선택번호")
    parser.add_argument("--output", default="scan_results.json")
    parser.add_argument("--state", default="scan_state.json")
    args = parser.parse_args()
    try:
        name = (args.law or input("조회할 정확한 법령명: ")).strip()
        if not name or not os.getenv("LAW_OC"):
            raise ValueError("법령명과 .env의 LAW_OC가 필요합니다.")
        client = LawClient(os.environ["LAW_OC"])
        current = previous = None
        if args.mode == "MANUAL":
            histories = client.histories(name)
            for i, rev in enumerate(histories, 1):
                print(f"{i} | 시행일자 {rev['effective_date']} | MST {rev['mst']}")
            ci = args.current if args.current is not None else int(input("현재 연혁 선택번호: "))
            pi = args.previous if args.previous is not None else int(input("기준 연혁 선택번호: "))
            if not (1 <= ci <= len(histories) and 1 <= pi <= len(histories)):
                raise ValueError("연혁 선택번호 범위를 확인하세요.")
            current, previous = histories[ci - 1], histories[pi - 1]
        result = run(client, name, args.mode, args.output, args.state, current, previous)
        print("Scanner 완료:", result["status"])
        for key, label in [("new_forms", "신규"), ("deleted_forms", "삭제"),
                           ("changed_forms", "텍스트 변경"), ("review_required_forms", "확인 필요")]:
            print(f"{label}: {len(result[key])}건")
        print("결과 저장:", args.output)
        print("Comparator 상세 변경:", result["detail_change_count"], "건")
        return 2 if result["status"] == "partial" else 0
    except (ValueError, OSError, requests.RequestException) as exc:
        print("Scanner 실패:", type(exc).__name__)
        print("상세 오류:", repr(exc))
        if isinstance(exc, ValueError) and not isinstance(exc, requests.RequestException):
            print(str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
