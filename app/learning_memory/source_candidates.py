"""查找同界面的新证据；只读记录，采用复用既有版本服务。"""
import hashlib
from pathlib import Path
import re

from .event_store import LearningEventStore
from .receipt_adapter import content_hash


def _store(library, session_name):
    if not isinstance(session_name, str) or not re.fullmatch(r"session-[A-Za-z0-9_-]+", session_name):
        raise ValueError("invalid source session")
    root = library._artifact_root.parent.resolve()
    session = (root / session_name).resolve()
    if session.parent != root or not session.is_dir():
        raise ValueError("source session must belong to this memory data directory")
    return LearningEventStore(session)


def list_candidates(library, interface_id, *, limit=40, scan_limit=1000):
    current = library.load_interface_content(interface_id)
    source = current["source"]
    if source.get("kind") != "execution_memory_v1":
        raise ValueError("source adoption requires execution memory")
    candidates, errors, scanned = [], [], 0
    sessions = sorted(library._artifact_root.parent.glob("session-*"), key=lambda p: p.stat().st_mtime, reverse=True)
    for session in sessions:
        if not session.is_dir():
            continue
        store = _store(library, session.name)
        for path in store.root.glob("learning-*/reviews/*/current.json"):
            if scanned >= scan_limit or len(candidates) >= limit:
                return {"candidates": candidates, "errors": errors, "truncated": True, "scanned": scanned}
            scanned += 1
            learning_id, event_id = path.parents[2].name, path.parent.name
            try:
                record = store._review(learning_id, event_id)
                if record is None:
                    continue
                for view in ("before", "after"):
                    identity = record["review"][view]
                    if (identity is None or identity["interface_key"] != source["interface_key"]
                            or identity["state_key"] != source["state_key"]
                            or identity["frame_sha256"] == source["screenshot_sha256"]):
                        continue
                    if len(candidates) >= limit:
                        return {"candidates": candidates, "errors": errors, "truncated": True, "scanned": scanned}
                    candidates.append({"session_name": session.name, "learning_id": learning_id,
                        "event_id": event_id, "view": view, "review_sha256": record["review_sha256"],
                        "event_sha256": record["review"]["event_sha256"],
                        "frame_sha256": identity["frame_sha256"], "meaning": identity["meaning"]})
            except (OSError, ValueError, KeyError, RuntimeError) as error:
                if len(errors) < 10:
                    errors.append({"event_id": event_id, "error": str(error)})
    return {"candidates": candidates, "errors": errors, "truncated": False, "scanned": scanned}


def preview_candidate(library, interface_id, candidate):
    current = library.load_interface_content(interface_id)
    store = _store(library, candidate["session_name"])
    event = store._event(candidate["learning_id"], candidate["event_id"])
    record = store._review(candidate["learning_id"], candidate["event_id"])
    if (content_hash(event) != candidate["event_sha256"] or record is None
            or record["review_sha256"] != candidate["review_sha256"]):
        raise ValueError("source candidate changed; refresh the candidate list")
    view = candidate["view"]
    if view not in {"before", "after"}:
        raise ValueError("invalid source view")
    identity = record["review"][view]
    if (identity is None or identity["interface_key"] != current["source"].get("interface_key")
            or identity["state_key"] != current["source"].get("state_key")
            or identity["frame_sha256"] != candidate["frame_sha256"]):
        raise ValueError("source does not match the selected interface/state")
    store._verify_review_frames(event, record["review"])
    path = Path(event[view]["image_path"])
    path = path if path.is_absolute() else store.session / path
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != candidate["frame_sha256"]:
        raise ValueError("source image changed during preview")
    return {"png": raw, "candidate": candidate}


def adopt_candidate(library, interface_id, candidate, revision, digest, request_id):
    preview_candidate(library, interface_id, candidate)
    store = _store(library, candidate["session_name"])
    request = {key: candidate[key] for key in ("event_id", "event_sha256", "review_sha256", "view")}
    request.update(interface_id=interface_id, expected_revision=revision, expected_sha256=digest,
                   regions=[], recognition_text="")
    return library.adopt_observation(store, candidate["learning_id"], request, request_id)
