"""Verify corporate local income tax filing forms using their PDF revision dates."""
import json
import os
import re
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlsplit

from scanner import LawClient, atomic_json

LAW = "지방세법 시행규칙"
SINCE = date(2026, 5, 1)
# 지방세법 시행규칙 제48조의4의 일반 법인 신고 및 조건별 첨부서류.
FORM_KEYS = tuple(f"0043:{n:02}" for n in (0, 2, 3, 4, 5, 9, 10, 12, 13, 14)) + ("0044:06",)
OUTPUT = Path(__file__).parent / "public/local-tax-monitoring.json"


def revision_date(text):
    """Read the form header only, never a date from instructions or examples."""
    header = text[:500]
    match = re.search(r"[<〈](?:개정|신설)\s*(\d{4})\s*\.\s*(\d{1,2})\s*\.\s*(\d{1,2})\s*\.?\s*[>〉]", header)
    if not match:
        raise ValueError("Missing form revision date")
    return date(*map(int, match.groups()))


def check(client, today=None):
    today = today or date.today()
    histories = client.histories(LAW)
    current = next((r for r in histories if r["effective_date"] <= today.strftime("%Y%m%d")), None)
    if current is None:
        raise ValueError("No effective law revision")
    forms = client.forms(current)
    rows = []
    for key in FORM_KEYS:
        row = {"id": key, "status": "review_required", "revision_date": None}
        stage = "form_lookup"
        try:
            form = forms[key]
            row.update(title=form["title"], number=form["number"], branch_number=form["branch_number"])
            stage = "current_pdf"
            text = client.pdf_text(form)
            stage = "revision_date"
            revised = revision_date(text)
            row.update(revision_date=revised.isoformat(), status="revised_since_cutoff" if revised >= SINCE else "before_cutoff")
            # Publish only public law.go.kr document URLs, never API credentials.
            for kind in ("pdf", "hwp"):
                if not form[kind + "_url"]:
                    continue
                link = urljoin("https://www.law.go.kr", form[kind + "_url"])
                parsed = urlsplit(link)
                if parsed.hostname in {"law.go.kr", "www.law.go.kr"} and not re.search(r"(?i)(?:^|&)(oc|key|token)=", parsed.query):
                    row[kind + "_url"] = link
            if revised >= SINCE:
                stage = "current_hwp"
                row["hwp_sha256"] = client.hwp_hash(form)
        except Exception as exc:
            row.update(status="review_required", failed_stage=stage, error_type=type(exc).__name__)
            print(f"::warning::Local tax form {key}: {stage} / {type(exc).__name__}", flush=True)
        rows.append(row)
    return {"schema_version": 1, "law_name": LAW, "since": SINCE.isoformat(),
            "date_basis": "서식 PDF 머리말의 개정·신설일 (기준일 포함)",
            "scope": "제48조의4 일반 법인 확정신고 및 조건별 첨부서식 11종",
            "current": current, "forms": rows,
            "status": "partial" if any(r["status"] == "review_required" for r in rows) else "success",
            "changed_count": sum(r["status"] == "revised_since_cutoff" for r in rows)}


def main():
    checked_at = datetime.now(timezone.utc).isoformat()
    previous = json.loads(OUTPUT.read_text(encoding="utf-8")) if OUTPUT.exists() else {}
    try:
        from zoneinfo import ZoneInfo
        client = LawClient(os.environ["LAW_OC"].strip())
        try:
            result = check(client, datetime.now(ZoneInfo("Asia/Seoul")).date())
        finally:
            client.session.close()
    except Exception as exc:
        print(f"::error::Local tax API lookup failed / {type(exc).__name__}", flush=True)
        result = {"schema_version": 1, "law_name": LAW, "since": SINCE.isoformat(),
                  "status": "failed", "changed_count": None, "forms": [], "error_type": type(exc).__name__}
    result["checked_at"] = checked_at
    result["last_success_at"] = checked_at if result["status"] == "success" else previous.get("last_success_at")
    result["last_successful_data"] = None if result["status"] == "success" else previous.get("last_successful_data") or (previous if previous.get("status") == "success" else None)
    if result["status"] != "success":
        result["changed_count"] = None
    run_id = os.getenv("GITHUB_RUN_ID", "")
    result["run_url"] = f"https://github.com/BSR1002/tax-law-form-checker/actions/runs/{run_id}" if run_id.isdigit() else None
    atomic_json(OUTPUT, result)
    print(f"Local tax verification: {result['status']}; revised forms: {result['changed_count']}")
    return 0 if result["status"] == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())
