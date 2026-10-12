from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

from PIL import Image, ImageDraw
import pytest


def sequence(tmp_path, *, positions=(10.0, 10.5, 11.0), states=None, colors=None):
    frames, observations = [], []
    colors = colors or [30] * len(positions)
    states = states or ["playing"] * len(positions)
    for index, (position, state, color) in enumerate(zip(positions, states, colors)):
        path = tmp_path / f"frame-{index}.png"
        Image.new("RGB", (160, 96), (color, color, color)).save(path)
        capture_id = f"capture-{index}"
        frames.append({"image_path": str(path), "sha256": sha256(path.read_bytes()).hexdigest(),
            "capture_id": capture_id, "elapsed_ms": index * 500,
            "window_identity": {"handle": 10, "process_id": 20, "process_create_time": 30.0}})
        observations.append({"capture_id": capture_id, "position_seconds": position, "state": state})
    return frames, {"bbox": [0, 0, 160, 96], "content_bbox": [0, 0, 160, 96], "masks": []}, observations


def evaluate(args, policy=None):
    from app.execution.video_playback_evidence import evaluate_playback_sequence
    result = evaluate_playback_sequence(*args, policy=policy)
    assert set(result) == {"status", "reason", "metrics"}
    assert result["reason"] and all(isinstance(code, str) for code in result["reason"])
    json.dumps(result, allow_nan=False)
    return result


def replace_image(frame, image, *, format="PNG"):
    image.save(frame["image_path"], format=format)
    frame["sha256"] = sha256(Path(frame["image_path"]).read_bytes()).hexdigest()


@pytest.mark.parametrize("colors", [(30, 110, 190), (30, 30, 30), (30, 31, 32)])
def test_sustained_progress_confirms_moving_static_and_low_change_video(tmp_path, colors):
    result = evaluate(sequence(tmp_path, colors=colors))
    assert result["status"] == "playing"
    assert result["reason"] == ["sustained_progress"]
    metrics = result["metrics"]
    assert metrics["frame_count"] == metrics["usable_frame_count"] == 3
    assert metrics["span_ms"] == metrics["usable_span_ms"] == 1000
    assert metrics["image_size"] == [160, 96]
    assert metrics["positive_progress_intervals"] == 2
    assert metrics["progress_seconds"] == metrics["progress_rate"] == 1
    assert len(metrics["motion_pairs"]) == 2


def test_identical_png_hashes_are_valid_for_distinct_new_capture_ids(tmp_path):
    args = sequence(tmp_path)
    assert len({frame["sha256"] for frame in args[0]}) == 1
    assert evaluate(args)["status"] == "playing"


def test_decimal_progress_threshold_is_not_lost_to_binary_subtraction(tmp_path):
    result = evaluate(sequence(tmp_path, positions=(10.0, 10.1, 10.5)))
    assert result["status"] == "playing"
    assert result["metrics"]["positive_progress_intervals"] == 2


@pytest.mark.parametrize("state,status", [
    ("paused", "not_playing"), ("ended", "not_playing"), ("error", "not_playing"),
    ("ad", "not_playing"), ("loading", "loading")])
def test_terminal_conflict_cannot_be_overridden_by_motion_or_progress(tmp_path, state, status):
    result = evaluate(sequence(tmp_path, states=("playing", "playing", state), colors=(20, 120, 220)))
    assert result["status"] == status
    assert result["reason"] == [state]
    assert not result["metrics"]["semantic_review_suggested"]


def test_loading_before_latest_trusted_sequence_requires_three_fresh_playing_frames(tmp_path):
    args = sequence(tmp_path, states=("loading", "playing", "playing"))
    result = evaluate(args)
    assert result["status"] == "uncertain"
    assert result["metrics"]["usable_frame_count"] == 2
    args = sequence(tmp_path, positions=(9.5, 10, 10.5, 11), states=("loading", "playing", "playing", "playing"))
    assert evaluate(args)["status"] == "playing"


def test_unknown_state_does_not_prove_target_playback_even_with_position(tmp_path):
    assert evaluate(sequence(tmp_path, states=("unknown",) * 3))["status"] == "uncertain"


def test_distributed_motion_only_suggests_semantic_review(tmp_path):
    result = evaluate(sequence(tmp_path, positions=(None,) * 3, colors=(20, 120, 220)))
    assert result["status"] == "uncertain"
    assert result["metrics"]["semantic_review_suggested"]
    assert all(pair["distributed_motion"] for pair in result["metrics"]["motion_pairs"])


def test_static_video_without_visible_progress_remains_uncertain(tmp_path):
    result = evaluate(sequence(tmp_path, positions=(None,) * 3))
    assert result["status"] == "uncertain"
    assert not result["metrics"]["semantic_review_suggested"]


def test_unmasked_subtitle_only_motion_is_not_distributed_playback_evidence(tmp_path):
    args = sequence(tmp_path, positions=(None,) * 3)
    for index, frame in enumerate(args[0]):
        image = Image.new("RGB", (160, 96), (30, 30, 30))
        ImageDraw.Draw(image).rectangle((0, 88, 159, 95), fill=(index * 100,) * 3)
        replace_image(frame, image)
    result = evaluate(args)
    assert result["status"] == "uncertain"
    assert not result["metrics"]["semantic_review_suggested"]


@pytest.mark.parametrize("scene", ["layout_shift", "multiple_players", "loading_spinner"])
def test_unbound_scene_motion_cannot_prove_target_video(tmp_path, scene):
    args = sequence(tmp_path, positions=(None,) * 3,
        states=(("loading",) * 3 if scene == "loading_spinner" else ("unknown",) * 3))
    for index, frame in enumerate(args[0]):
        image = Image.new("RGB", (160, 96), "black")
        draw = ImageDraw.Draw(image)
        if scene == "layout_shift":
            draw.rectangle((index * 30, 10, index * 30 + 50, 80), fill="white")
        elif scene == "multiple_players":
            draw.rectangle((0, 0, 70, 95), fill=(index * 100,) * 3)
            draw.rectangle((90, 0, 159, 95), fill=((2 - index) * 100,) * 3)
        else:
            draw.arc((50, 20, 110, 80), start=index * 90, end=index * 90 + 45, fill="white", width=5)
        replace_image(frame, image)
    assert evaluate(args)["status"] == ("loading" if scene == "loading_spinner" else "uncertain")


@pytest.mark.parametrize("positions", [
    (10, 10, 11), (10, 40, 40), (10, 13, 16), (10, 9, 10),
    (10, 10.01, 10.02), (10, None, 11)])
def test_seek_regression_jitter_or_missing_reading_cannot_confirm(tmp_path, positions):
    assert evaluate(sequence(tmp_path, positions=positions))["status"] == "uncertain"


def test_subtitles_or_danmaku_masks_are_excluded_by_union_not_double_counted(tmp_path):
    args = sequence(tmp_path, positions=(None,) * 3)
    for index, frame in enumerate(args[0]):
        image = Image.new("RGB", (160, 96), (30, 30, 30))
        ImageDraw.Draw(image).rectangle((0, 80, 159, 95), fill=(index * 100,) * 3)
        replace_image(frame, image)
    args[1]["masks"] = [[0, 80, 160, 16], [0, 80, 160, 16]]
    result = evaluate(args)
    assert result["status"] == "uncertain"
    assert result["metrics"]["valid_content_pixels"] == 160 * 80
    assert result["metrics"]["masked_fraction"] == pytest.approx(1 / 6)
    assert all(pair["changed_pixel_fraction"] == 0 for pair in result["metrics"]["motion_pairs"])


def test_control_mask_outside_content_is_valid_and_does_not_hide_content(tmp_path):
    args = sequence(tmp_path)
    args[1]["content_bbox"] = [0, 0, 160, 80]
    args[1]["masks"] = [[0, 80, 160, 16]]
    result = evaluate(args)
    assert result["status"] == "playing"
    assert result["metrics"]["masked_fraction"] == 0


@pytest.mark.parametrize("mutate,reason", [
    (lambda f, r, o: f[1].update(capture_id=f[0]["capture_id"]), "capture_id_invalid"),
    (lambda f, r, o: f[1].update(elapsed_ms=0), "elapsed_invalid"),
    (lambda f, r, o: f[1].update(elapsed_ms=-1), "elapsed_invalid"),
    (lambda f, r, o: f[1].update(elapsed_ms=float("nan")), "elapsed_invalid"),
    (lambda f, r, o: f[1].update(elapsed_ms=True), "elapsed_invalid"),
    (lambda f, r, o: f[1].update(sha256="0" * 64), "image_hash_mismatch"),
    (lambda f, r, o: f[1].update(sha256="invalid"), "image_hash_invalid"),
    (lambda f, r, o: f[1].pop("image_path"), "frame_fields_invalid"),
    (lambda f, r, o: f[1]["window_identity"].update(handle=11), "identity_changed"),
    (lambda f, r, o: f[1]["window_identity"].update(process_id=21), "identity_changed"),
    (lambda f, r, o: f[1]["window_identity"].update(process_create_time=31), "identity_changed"),
    (lambda f, r, o: f[1]["window_identity"].update(process_id=True), "identity_invalid"),
    (lambda f, r, o: f[1]["window_identity"].update(process_create_time=float("inf")), "identity_invalid"),
    (lambda f, r, o: o[1].update(capture_id="another-frame"), "observation_invalid"),
    (lambda f, r, o: o[1].update(state="buffering"), "observation_invalid"),
    (lambda f, r, o: o[1].update(position_seconds=float("nan")), "position_invalid"),
    (lambda f, r, o: o[1].update(position_seconds=float("inf")), "position_invalid"),
    (lambda f, r, o: o[1].update(position_seconds=True), "position_invalid"),
    (lambda f, r, o: o[1].update(position_seconds="10"), "position_invalid"),
    (lambda f, r, o: o[1].update(position_seconds=-1), "position_invalid"),
    (lambda f, r, o: r.update(bbox=[1, 0, 160, 96]), "region_invalid"),
    (lambda f, r, o: r.update(content_bbox=[0, 0, 161, 96]), "region_invalid"),
    (lambda f, r, o: r.update(content_bbox=[0, 0, 0, 96]), "region_invalid"),
    (lambda f, r, o: r.update(content_bbox=[0, 0, 160.0, 96]), "region_invalid"),
    (lambda f, r, o: r.update(masks=[[0, 0, 160, 49]]), "masked_content_insufficient"),
    (lambda f, r, o: r.update(masks=[[0, 0, 161, 1]]), "mask_invalid"),
    (lambda f, r, o: r.update(masks=[[0, 0, -1, 1]]), "mask_invalid"),
    (lambda f, r, o: r.update(content_bbox=[0, 0, 15, 15]), "masked_content_insufficient"),
])
def test_bad_binding_data_and_geometry_refuse_without_nonfinite_json(tmp_path, mutate, reason):
    args = sequence(tmp_path)
    mutate(*args)
    result = evaluate(args)
    assert result["status"] == "uncertain"
    assert result["reason"] == [reason]
    assert not result["metrics"]["semantic_review_suggested"]


@pytest.mark.parametrize("case", ["short", "too_many", "short_span", "reordered", "missing_observation"])
def test_sampling_count_order_and_span_are_real_evidence_gates(tmp_path, case):
    args = sequence(tmp_path, positions=tuple(10 + i * 0.5 for i in range(8 if case == "too_many" else 3)))
    frames, _, observations = args
    if case == "short":
        frames.pop()
        observations.pop()
    elif case == "short_span":
        for index, frame in enumerate(frames):
            frame["elapsed_ms"] = index * 400
    elif case == "reordered":
        frames.reverse()
        observations.reverse()
    elif case == "missing_observation":
        observations.pop()
    assert evaluate(args)["status"] == "uncertain"


@pytest.mark.parametrize("case", ["size", "jpeg", "corrupt", "missing", "animated"])
def test_png_bytes_dimensions_and_file_integrity_are_required(tmp_path, case):
    args = sequence(tmp_path)
    frame = args[0][1]
    if case == "size":
        replace_image(frame, Image.new("RGB", (161, 96)))
    elif case == "jpeg":
        replace_image(frame, Image.new("RGB", (160, 96)), format="JPEG")
    elif case == "animated":
        Image.new("RGB", (160, 96)).save(frame["image_path"], format="PNG", save_all=True,
            append_images=[Image.new("RGB", (160, 96), "white")], duration=100)
        frame["sha256"] = sha256(Path(frame["image_path"]).read_bytes()).hexdigest()
    elif case == "corrupt":
        Path(frame["image_path"]).write_bytes(b"not a png")
        frame["sha256"] = sha256(b"not a png").hexdigest()
    else:
        frame["image_path"] = str(tmp_path / "absent.png")
    assert evaluate(args)["status"] == "uncertain"


@pytest.mark.parametrize("policy", [
    {"min_frame_count": 2}, {"min_span_ms": 999}, {"max_masked_fraction": 0.9},
    {"min_positive_intervals": 1}, {"max_progress_rate": float("nan")},
    {"min_progress_delta_seconds": True}, {"unknown": 1}, []])
def test_policy_cannot_silently_weaken_core_contract_or_contain_bad_values(tmp_path, policy):
    result = evaluate(sequence(tmp_path), policy=policy)
    assert result["status"] == "uncertain"
    assert result["reason"] == ["policy_invalid"]


def test_inputs_are_not_mutated_and_extra_frame_metadata_is_permitted(tmp_path):
    args = sequence(tmp_path)
    args[0][0]["source_note"] = "synthetic"
    original = deepcopy(args)
    assert evaluate(args)["status"] == "playing"
    assert args == original


@pytest.mark.parametrize("field", ["elapsed_ms", "position_seconds", "process_create_time", "policy"])
def test_unrepresentable_integer_is_rejected_without_exception_or_invalid_json(tmp_path, field):
    args = sequence(tmp_path)
    huge = 10 ** 400
    policy = None
    if field == "elapsed_ms":
        args[0][1][field] = huge
    elif field == "position_seconds":
        args[2][1][field] = huge
    elif field == "process_create_time":
        args[0][1]["window_identity"][field] = huge
    else:
        policy = {"min_span_ms": huge}
    assert evaluate(args, policy=policy)["status"] == "uncertain"
