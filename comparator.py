"""Comparator(비교): 입력/네트워크 없이 PDF 텍스트의 상세 변경을 반환한다."""
from difflib import SequenceMatcher


def normalize_text(text):
    return "".join(text.split())


def compare_texts(previous_text, current_text, law_name=""):
    previous = normalize_text(previous_text)
    current = normalize_text(current_text)
    if not previous or not current:
        raise ValueError("비교할 PDF 텍스트가 비어 있습니다.")
    changes = []
    excluded = []
    header = "■" + normalize_text(law_name) if law_name else None
    # 반복되는 번호/문구도 비교 대상으로 유지한다.
    matcher = SequenceMatcher(None, previous, current, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        change = {"type": tag, "old": previous[i1:i2], "new": current[j1:j2],
                  "previous_start": i1, "previous_end": i2,
                  "current_start": j1, "current_end": j2}
        # 기존 Comparator의 법령명 머리말 삭제 제외 규칙을 보존하되 기록은 남긴다.
        if tag == "delete" and change["old"] == header:
            excluded.append({**change, "reason": "law_header_removed"})
        else:
            changes.append(change)
    return {"status": "completed", "normalization": "remove_whitespace",
            "change_count": len(changes), "changes": changes,
            "excluded_changes": excluded}
