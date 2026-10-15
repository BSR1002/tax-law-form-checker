"""Run the metadata monitor and export a credential-free, read-only dashboard feed."""
import json
import os
import re
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

from law_monitor import LAWS, STATE, revision, run, LawClient, atomic_json

FEED = Path(__file__).parent / "public" / "monitoring.json"
RETENTION_DAYS = 90


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def read_baseline(path):
    path = Path(path)
    if not path.exists():
        return None
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or set(raw) != set(LAWS):
        raise ValueError("Invalid baseline")
    return {name: revision(raw[name]) for name in LAWS}


def initial_feed(baseline=None):
    """A saved baseline is not evidence of a successful lookup at export time."""
    return {
        "schema_version": 1, "data_mode": "live", "timezone": "Asia/Seoul",
        "generated_at": timestamp(), "last_checked_at": None,
        "last_success_at": None, "history_started_at": None,
        "history_retention_days": RETENTION_DAYS, "latest_run": None,
        "source": "국가법령정보센터 / GitHub Actions",
        "notice": "시행일자 내림차순의 최신 연혁이며 미래 시행 연혁을 포함할 수 있습니다. 메타데이터 변경은 서식·본문 변경 확정을 뜻하지 않습니다.",
        "laws": [dict(
            id=str(index), name=name, category="시행규칙",
            effective_date=(baseline[name]["effective_date"] if baseline else None),
            mst=(baseline[name]["mst"] if baseline else None),
            status="unverified", checked_at=None, last_success_at=None,
            original_url=None,
        ) for index, name in enumerate(LAWS, 1)],
        "changes": [], "runs": [],
    }


def load_feed(path):
    path = Path(path)
    if not path.exists():
        return initial_feed()
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != 1:
        raise ValueError("Unsupported dashboard schema")
    return data


def run_identity(env):
    repo, run_id = env.get("GITHUB_REPOSITORY", ""), env.get("GITHUB_RUN_ID", "")
    attempt = env.get("GITHUB_RUN_ATTEMPT", "1")
    if re.fullmatch(r"[\w.-]+/[\w.-]+", repo) and run_id.isdigit() and attempt.isdigit():
        return f"{run_id}:{attempt}", f"https://github.com/{repo}/actions/runs/{run_id}"
    return "local:" + timestamp(), None


def update_feed(feed, previous, current, result, attempts, checked_at, identity, run_url):
    """Only explicitly selected metadata is published; exceptions and credentials never are."""
    success = result != "failed"
    feed["generated_at"] = checked_at
    feed["last_checked_at"] = checked_at
    feed["history_started_at"] = feed.get("history_started_at") or checked_at
    if success:
        feed["last_success_at"] = checked_at
    old_rows = {row["name"]: row for row in feed["laws"]}
    rows, changes = [], []
    for index, name in enumerate(LAWS, 1):
        known = current[name] if success else (previous[name] if previous else None)
        changed = success and previous is not None and previous[name] != current[name]
        status = ("changed" if changed else "baseline_initialized" if previous is None else "unchanged") if success else "check_failed"
        rows.append(dict(
            id=str(index), name=name, category="시행규칙",
            effective_date=known["effective_date"] if known else None,
            mst=known["mst"] if known else None, status=status,
            checked_at=checked_at,
            last_success_at=checked_at if success else old_rows.get(name, {}).get("last_success_at"),
            original_url=None,
        ))
        if changed:
            changes.append(dict(
                id=identity + ":" + str(index), law_id=str(index), law_name=name,
                detected_at=checked_at, previous=previous[name], current=current[name],
                changed_fields=[key for key in ("effective_date", "mst") if previous[name][key] != current[name][key]],
                run_url=run_url, issue_url=None,
            ))
    run_record = dict(
        id=identity, checked_at=checked_at, status="success" if success else "failed",
        result=result, attempts=attempts, changed_count=len(changes) if success else None,
        error_summary=None if success else "모니터링 또는 알림 처리 실패: 법령 변경 여부 확인 불가. 기존 기준 유지.",
        run_url=run_url, issue_url=None,
    )
    cutoff = (datetime.fromisoformat(checked_at) - timedelta(days=RETENTION_DAYS)).isoformat()
    feed["laws"] = rows
    feed["latest_run"] = run_record
    feed["runs"] = [run_record] + [r for r in feed["runs"] if r["id"] != identity and r["checked_at"] >= cutoff]
    feed["changes"] = changes + [c for c in feed["changes"] if not c["id"].startswith(identity + ":") and c["detected_at"] >= cutoff]
    return feed


def execute(monitor, state_path=STATE, feed_path=FEED, sleep=time.sleep, env=None):
    env = os.environ if env is None else env
    # Reject corrupt local state before running; never silently discard historical records.
    feed = load_feed(feed_path)
    previous = read_baseline(state_path)
    identity, run_url = run_identity(env)
    result = "failed"
    current = None
    for attempts in range(1, 4):
        print(f"Law monitor attempt {attempts}/3", flush=True)
        try:
            result = monitor()
            if result not in ("no_changes", "baseline_initialized", "changes_notified"):
                raise ValueError("Invalid monitor result")
            current = read_baseline(state_path)
            if current is None:
                raise ValueError("Missing baseline after success")
            break
        except Exception:
            result = "failed"
            print("Law monitor attempt failed.", flush=True)
            if attempts < 3:
                sleep(180)
    checked_at = timestamp()
    atomic_json(feed_path, update_feed(feed, previous, current, result, attempts, checked_at, identity, run_url))
    if env.get("GITHUB_OUTPUT"):
        with open(env["GITHUB_OUTPUT"], "a", encoding="utf-8") as stream:
            stream.write("result=" + ("exhausted" if result == "failed" else "success") + "\n")
    return 1 if result == "failed" else 0


def main():
    try:
        def monitor():
            oc = os.environ["LAW_OC"].strip()
            if not oc:
                raise ValueError("Missing credential")
            return run(LawClient(oc))
        return execute(monitor)
    except Exception:
        print("Dashboard export failed; inspect configuration and state. No sensitive details logged.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
