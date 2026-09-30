"""Revision metadata monitor; never calls the full Scanner."""
import hashlib
import json
import os
import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from scanner import LawClient, atomic_json

LAWS = ("법인세법 시행규칙", "소득세법 시행규칙", "조세특례제한법 시행규칙")
STATE = Path(__file__).with_name("law_monitor_state.json")


def revision(value):
    date, mst = str(value["effective_date"]), str(value["mst"])
    if not re.fullmatch(r"[0-9]{8}", date) or not re.fullmatch(r"[0-9]+", mst):
        raise ValueError("Invalid revision")
    datetime.strptime(date, "%Y%m%d")
    return {"effective_date": date, "mst": mst}


def notify(previous, current):
    """Find an existing event (including closed issues), or create one issue."""
    repo = os.environ["GITHUB_REPOSITORY"]
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", repo):
        raise ValueError("Invalid repository")
    event = json.dumps([previous, current], sort_keys=True, ensure_ascii=True)
    marker = "<!-- law-monitor:" + hashlib.sha256(event.encode()).hexdigest() + " -->"
    session = requests.Session()
    session.headers.update({"Authorization": "Bearer " + os.environ["GITHUB_TOKEN"],
                            "Accept": "application/vnd.github+json"})
    url = f"https://api.github.com/repos/{repo}/issues"
    page = 1
    while True:
        response = session.get(url, params={"state": "all", "per_page": 100, "page": page}, timeout=30)
        response.raise_for_status()
        issues = response.json()
        if not isinstance(issues, list):
            raise ValueError("Invalid issues response")
        if any(marker in (issue.get("body") or "") for issue in issues if "pull_request" not in issue):
            return
        if len(issues) < 100:
            break
        page += 1
    lines = [marker, "법령 버전 변경이 감지되었습니다. 해당 법령의 Scanner MANUAL 상세 비교가 필요합니다.", ""]
    for name in LAWS:
        old, new = previous[name], current[name]
        lines.append(f"### {name}")
        if old == new:
            lines.append("변경 없음")
        else:
            lines.extend([f"- 기존: {old['effective_date']} / MST {old['mst']}",
                          f"- 신규: {new['effective_date']} / MST {new['mst']}"])
    lines.append("\n시행일자/MST 변경 알림이며 개별 서식 변경 확정 결과는 아닙니다. HWP/PDF는 다운로드하지 않았습니다.")
    today = datetime.now(ZoneInfo("Asia/Seoul")).date()
    response = session.post(url, json={"title": f"[법령 개정 감지] {today}", "body": "\n".join(lines)}, timeout=30)
    response.raise_for_status()


def run(client, path=STATE, notifier=notify):
    path = Path(path)
    previous = None
    if path.exists():
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict) or set(raw) != set(LAWS):
            raise ValueError("Invalid monitor state")
        previous = {name: revision(raw[name]) for name in LAWS}
    # Complete all three lookups before any notification or state mutation.
    current = {name: revision(client.histories(name)[0]) for name in LAWS}
    if previous == current:
        return "no_changes"
    if previous is not None:
        notifier(previous, current)
    atomic_json(path, current)
    return "baseline_initialized" if previous is None else "changes_notified"


def main():
    try:
        oc = os.environ["LAW_OC"].strip()
        if not oc:
            raise ValueError("Missing credential")
        print("Law monitor:", run(LawClient(oc)))
        return 0
    except Exception:
        # Request exceptions may contain URLs with OC. Never print exceptions.
        print("Law monitor failed. Check credentials, API access and repository permissions; previous committed state is retained.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
