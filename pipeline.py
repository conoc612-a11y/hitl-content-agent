from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from uuid import uuid4


DATA_DIR = Path("data")
PENDING_FILE = DATA_DIR / "pending.json"
PUBLISHED_FILE = DATA_DIR / "published.jsonl"
REJECTED_FILE = DATA_DIR / "rejected.jsonl"
AUDIT_FILE = DATA_DIR / "audit_log.jsonl"

SENSITIVE_TERMS = ["무조건", "확실히", "투자 보장", "완치", "부작용 없음", "최고"]
NUMBER_RE = re.compile(r"\d+(?:\.\d+)?\s*(?:%|퍼센트|원|만원|명|건|배|개|일|시간)")
SOURCE_RE = re.compile(r"출처\s*:|자료\s*:|https?://", re.IGNORECASE)


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def ensure_data_dir() -> None:
    DATA_DIR.mkdir(exist_ok=True)
    if not PENDING_FILE.exists():
        PENDING_FILE.write_text("[]", encoding="utf-8")


def load_pending() -> list[dict]:
    ensure_data_dir()
    return json.loads(PENDING_FILE.read_text(encoding="utf-8"))


def save_pending(items: list[dict]) -> None:
    ensure_data_dir()
    PENDING_FILE.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")


def append_jsonl(path: Path, item: dict) -> None:
    ensure_data_dir()
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(item, ensure_ascii=False) + "\n")


def read_jsonl(path: Path) -> list[dict]:
    ensure_data_dir()
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def make_draft(request_text: str) -> str:
    request_text = request_text.strip()
    title = request_text.splitlines()[0][:45] or "새 콘텐츠"
    body = request_text.replace("\n", " ").strip()
    return (
        f"[발행 초안] {title}\n\n"
        f"핵심 메시지: {body}\n\n"
        "독자가 바로 이해할 수 있도록 배경, 주요 내용, 다음 행동을 간단히 정리했습니다. "
        "필요한 경우 본문 하단의 출처와 수치를 확인한 뒤 발행합니다."
    )


def evaluate(request_text: str, draft: str) -> dict:
    combined = f"{request_text}\n{draft}"
    has_number = bool(NUMBER_RE.search(combined))
    has_source = bool(SOURCE_RE.search(combined))
    sensitive_hits = [term for term in SENSITIVE_TERMS if term in combined]

    score = 1.0
    score -= 0.2 if len(draft) < 180 else 0
    score -= 0.2 if "다음 행동" not in draft and "신청" not in combined and "확인" not in combined else 0
    score -= 0.15 if has_number and not has_source else 0
    score -= 0.15 if sensitive_hits else 0
    score = round(max(score, 0), 2)

    reasons = []
    if has_number and not has_source:
        reasons.append("출처 없는 수치가 있어 사실 오류나 과장 발행 위험이 있습니다.")
    if score < 0.75:
        reasons.append(f"검수 점수 {score}가 기준 0.75보다 낮아 품질 확인이 필요합니다.")
    if sensitive_hits:
        reasons.append("민감하거나 단정적인 표현이 포함되어 브랜드/법적 리스크가 있습니다: " + ", ".join(sensitive_hits))

    return {
        "quality_score": score,
        "has_unsourced_number": has_number and not has_source,
        "sensitive_terms": sensitive_hits,
        "needs_approval": bool(reasons),
        "reasons": reasons,
        "basis": [
            "수치가 있으면 출처 표기 여부를 확인합니다.",
            "품질 점수가 0.75 미만이면 사람이 문맥과 톤을 확인합니다.",
            "민감어가 있으면 외부 발행 전 사람이 위험 표현을 확인합니다.",
        ],
    }


def publish(item: dict, decision: str = "auto_published", reviewer_note: str = "") -> dict:
    output = {
        **item,
        "status": "published",
        "decision": decision,
        "reviewer_note": reviewer_note,
        "published_at": now(),
    }
    append_jsonl(PUBLISHED_FILE, output)
    append_jsonl(AUDIT_FILE, {"id": item["id"], "event": decision, "time": now(), "note": reviewer_note})
    return output


def process_request(request_text: str) -> dict:
    draft = make_draft(request_text)
    review = evaluate(request_text, draft)
    item = {
        "id": uuid4().hex[:8],
        "created_at": now(),
        "request_text": request_text.strip(),
        "draft": draft,
        "review": review,
        "resume_action": "승인되면 published.jsonl에 발행 기록을 저장합니다.",
    }

    if review["needs_approval"]:
        item["status"] = "pending"
        pending = load_pending()
        pending.append(item)
        save_pending(pending)
        append_jsonl(AUDIT_FILE, {"id": item["id"], "event": "paused_for_human", "time": now()})
        return item

    item["status"] = "auto_published"
    return publish(item)


def approve(item_id: str, reviewer_note: str = "") -> dict | None:
    pending = load_pending()
    item = next((x for x in pending if x["id"] == item_id), None)
    if not item:
        return None
    save_pending([x for x in pending if x["id"] != item_id])
    return publish(item, "human_approved", reviewer_note)


def reject(item_id: str, reviewer_note: str = "") -> dict | None:
    pending = load_pending()
    item = next((x for x in pending if x["id"] == item_id), None)
    if not item:
        return None
    save_pending([x for x in pending if x["id"] != item_id])
    output = {**item, "status": "rejected", "decision": "human_rejected", "reviewer_note": reviewer_note, "rejected_at": now()}
    append_jsonl(REJECTED_FILE, output)
    append_jsonl(AUDIT_FILE, {"id": item_id, "event": "human_rejected", "time": now(), "note": reviewer_note})
    return output


def stats() -> dict:
    return {
        "pending": len(load_pending()),
        "published": len(read_jsonl(PUBLISHED_FILE)),
        "rejected": len(read_jsonl(REJECTED_FILE)),
    }


def reset_demo_data() -> None:
    ensure_data_dir()
    for path in [PENDING_FILE, PUBLISHED_FILE, REJECTED_FILE, AUDIT_FILE]:
        if path.exists():
            path.unlink()
    ensure_data_dir()


def self_check() -> None:
    reset_demo_data()
    safe = process_request("신규 기능 업데이트 안내. 사용자는 설정 화면에서 알림을 켤 수 있습니다.")
    risky = process_request("이번 캠페인은 전환율 35% 상승을 무조건 보장합니다.")
    assert safe["status"] == "published"
    assert risky["status"] == "pending"
    assert stats()["pending"] == 1
    assert approve(risky["id"], "수치 출처 확인 후 승인")
    assert stats()["pending"] == 0
    assert stats()["published"] == 2


if __name__ == "__main__":
    self_check()
    print("self_check passed")
