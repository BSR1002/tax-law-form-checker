"""Streamlit integration: environment credentials and file-free MANUAL scans."""
import os
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

from scanner import LawClient, scan


@contextmanager
def law_client():
    load_dotenv(Path(__file__).with_name(".env"), override=False)
    oc = os.environ.get("LAW_OC", "").strip()
    if not oc:
        raise ValueError("LAW_OC 설정이 필요합니다.")
    client = LawClient(oc)
    try:
        yield client
    finally:
        client.session.close()


def lookup_histories(name):
    name = name.strip()
    if not name:
        raise ValueError("정확한 법령명을 입력하세요.")
    with law_client() as client:
        return client.histories(name)


def validate_versions(current, previous):
    for revision in (current, previous):
        if not isinstance(revision, dict):
            raise ValueError("두 버전을 선택하세요.")
        mst = revision.get("mst", "")
        date = revision.get("effective_date", "")
        if not isinstance(mst, str) or not mst.isascii() or not mst.isdigit():
            raise ValueError("버전 식별값이 올바르지 않습니다.")
        if not isinstance(date, str) or len(date) != 8 or not date.isascii() or not date.isdigit():
            raise ValueError("시행일자가 올바르지 않습니다.")
        datetime.strptime(date, "%Y%m%d")
    if current == previous:
        raise ValueError("서로 다른 두 버전을 선택하세요.")
    if current["effective_date"] < previous["effective_date"]:
        raise ValueError("현재 버전은 기준 버전보다 과거일 수 없습니다.")


def run_manual(name, current, previous, progress=None):
    name = name.strip()
    if not name:
        raise ValueError("정확한 법령명을 입력하세요.")
    validate_versions(current, previous)
    with law_client() as client:
        result, _ = scan(client, name, "MANUAL", dict(current), dict(previous), progress=progress)
    return result


def version_label(revision):
    date = revision["effective_date"]
    return f"시행 {date[:4]}-{date[4:6]}-{date[6:]} | MST {revision['mst']}"
