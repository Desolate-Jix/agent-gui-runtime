import hashlib
import json
import math
from pathlib import Path
import re
from app.desktop_review.external_mapping import canonical_json_bytes

_PREVIEW = "session_epoch_admission_preview.v1"
_RECORD = "session_epoch_admission.v1"
_PHASES = {"prepared", "launch_started", "host_created", "pointer_published", "ready"}

def _require(condition, code):
    if not condition:
        raise ValueError("epoch_admission_" + code)


def _read(path):
    try:
        raw = path.read_bytes()
        value = json.loads(raw.decode("utf-8"), parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
        _require(isinstance(value, dict), "snapshot_invalid")
        return value, raw
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("epoch_admission_snapshot_invalid") from error


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


class SessionEpochReadContract:
    def __init__(self, instant):
        self.instant = instant


    def _session(self, name):
        _require(isinstance(name, str) and re.fullmatch(r"session-[0-9a-f]{32}", name), "session_invalid")
        root = Path(self.instant.data_root).resolve()
        path = (root / name).resolve()
        _require(path.parent == root, "session_outside_root")
        return path


    def _config_matches(self, pointer):
        _require(all(pointer.get(key) == getattr(self.instant, key) for key in
                     ("recognition_source", "delegate_profile", "api_profile")), "configuration_changed")
        profile = getattr(self.instant, "decision_profile", None)
        _require(pointer.get("decision_profile") == profile, "configuration_changed")
        if profile is not None:
            digest = getattr(self.instant, "decision_profile_sha256", None)
            if digest is None:
                from app.judgment.profile import load_decision_profile
                load_decision_profile(profile)
                digest = _sha(Path(profile).read_bytes())
            _require(pointer.get("decision_profile_sha256") == digest, "configuration_changed")


    def pending_request(self):
        root = Path(self.instant.data_root).resolve()
        folder = root / "recovery-admissions"
        if not folder.exists():
            return None
        _require(folder.is_dir() and folder.resolve() == folder, "record_path_invalid")
        current = Path(self.instant.session).resolve()
        records = []
        from app.core.instant_attachment_transport import _validate_request_id
        for path in sorted(folder.glob("*.json")):
            _require(path.resolve() == path, "record_path_invalid")
            record, _ = _read(path)
            if (record.get("new_session_name") != current.name
                    and record.get("new_host_identity") != self.instant.host_identity):
                continue
            _validate_request_id(path.stem)
            _require(path.stem.isascii(), "request_id_invalid")
            _, new, _ = self._validate(record, path.stem, record.get("preview_sha256"))
            pointer, _ = _read(root / "latest-session.json")
            _require(new == current and pointer == self._new_pointer(record)
                     and self.instant.host_identity == record["new_host_identity"], "session_changed")
            records.append(record)
        _require(len(records) <= 1, "record_conflict")
        if not records or records[0]["phase"] == "ready":
            return None
        # 宿主就绪不等于准入已结算；这里只读原请求，不自动完成或重启。
        return {"request_id": records[0]["request_id"], "preview_sha256": records[0]["preview_sha256"]}


    def _validate(self, record, request_id, digest):
        _require(set(record) == {"contract_version", "request_id", "preview_sha256", "preview",
                                "new_session_name", "phase", "new_host_identity"}, "record_invalid")
        _require(record.get("contract_version") == _RECORD and record.get("request_id") == request_id
                 and record.get("preview_sha256") == digest and record.get("phase") in _PHASES, "record_invalid")
        preview = record.get("preview")
        _require(isinstance(preview, dict) and set(preview) == {"contract_version", "source_session",
            "original_pointer_raw_utf8", "resource_proof", "input_proof", "preview_sha256"}, "record_invalid")
        _require(preview.get("contract_version") == _PREVIEW and preview.get("preview_sha256") == digest
                 and _sha(canonical_json_bytes({k: v for k, v in preview.items() if k != "preview_sha256"})) == digest,
                 "record_preview_invalid")
        old = Path(preview["source_session"]).resolve()
        _require(old == self._session(old.name), "record_source_invalid")
        new = self._session(record["new_session_name"])
        _require(old != new, "record_source_invalid")
        pointer = json.loads(preview["original_pointer_raw_utf8"])
        _require(pointer.get("name") == old.name, "record_source_invalid")
        self._config_matches(pointer)
        _require(preview["resource_proof"].get("resources_cleanup_verified") is True
                 and preview["input_proof"].get("input_terminal_settlement_verified") is True
                 and preview["resource_proof"].get("original_snapshots", {}).get("pointer") ==
                 _sha(preview["original_pointer_raw_utf8"].encode("utf-8")), "record_proof_invalid")
        proof = preview["resource_proof"]
        _require(proof.get("session_name") == old.name and proof.get("host_identity") == pointer.get("host_identity")
                 and proof.get("recognition_source") == self.instant.recognition_source, "record_proof_invalid")
        identity = record["new_host_identity"]
        if record["phase"] in {"prepared", "launch_started"}:
            _require(identity is None, "record_identity_invalid")
        else:
            self._identity(identity)
        return old, new, pointer


    @staticmethod
    def _identity(identity):
        _require(isinstance(identity, dict) and set(identity) == {"pid", "created"}
            and type(identity["pid"]) is int and identity["pid"] > 0
            and type(identity["created"]) in (int, float) and math.isfinite(identity["created"])
            and identity["created"] > 0, "host_identity_invalid")


    def _new_pointer(self, record):
        return {"name": record["new_session_name"], "host_identity": record["new_host_identity"],
                **{key: getattr(self.instant, key) for key in
                   ("recognition_source", "delegate_profile", "api_profile")},
                **({key: getattr(self.instant, key) for key in ("decision_profile", "decision_profile_sha256")}
                   if getattr(self.instant, "decision_profile", None) is not None else {})}

