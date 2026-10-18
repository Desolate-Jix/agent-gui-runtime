import pytest

from app.learning_memory.target_selectors import resolve_row_action, resolve_visible_row


def scene():
    identity = {"handle": 91, "process_id": 42, "process_create_time": 17.5}
    capture = {"capture_id": "cap-2", "window_identity": identity, "image_size": {"width": 800, "height": 600}, "run_id": "run-2"}
    container = {"container_id": "results", "capture_id": "cap-2", "window_identity": identity, "bbox": {"x": 10, "y": 40, "w": 490, "h": 360}, "complete": True}
    def row(row_id, record_id, title, price, y):
        return {"row_id": row_id, "container_id": "results", "capture_id": "cap-2", "window_identity": identity,
                "bbox": {"x": 20, "y": y, "w": 430, "h": 40}, "properties": {"record_id": record_id, "title": title, "price": price},
                "actions": [{"action_id": f"open-{record_id}", "row_id": row_id, "capture_id": "cap-2", "window_identity": identity,
                             "name": "Open detail", "control_type": "Button", "automation_id": "openDetail", "bbox": {"x": 350, "y": y + 5, "w": 90, "h": 30}}]}
    rows = [row("row-a", "A-1", "Same title", "$11", 50), row("row-b", "B-2", "Same title", "$19", 110)]
    bindings = {"run_id": "run-2", "inputs": {"wanted_id": "B-2"}, "outputs": {"read-price.latest_price": {"run_id": "run-2", "value": "$19"}}}
    return capture, container, rows, bindings


def match(capture, container, rows, bindings, constraints):
    return resolve_visible_row(container=container, rows=rows, constraints=constraints, bindings=bindings, capture=capture)


def input_id():
    return [{"property": "record_id", "operator": "eq", "value": {"source": "input", "name": "wanted_id"}}]


def test_reordered_and_inserted_rows_select_current_unique_identity():
    capture, container, rows, bindings = scene()
    selected = match(capture, container, list(reversed(rows)), bindings, input_id())
    assert selected["row_id"] == "row-b"
    candidate = resolve_row_action(selected, {"name": "Open detail", "control_type": "Button", "automation_id": "openDetail"}, capture)
    assert candidate["candidate"]["action_id"] == "open-B-2"
    assert candidate["candidate"]["click_point"] == {"x": 395, "y": 130}
    inserted = dict(rows[0], row_id="row-c", bbox={"x": 20, "y": 170, "w": 430, "h": 40}, properties={"record_id": "C-3", "title": "New", "price": "$99"}, actions=[])
    assert match(capture, container, [inserted, *rows], bindings, input_id())["row_id"] == "row-b"


def test_same_title_requires_id_and_dynamic_price_uses_current_rows():
    capture, container, rows, bindings = scene()
    with pytest.raises(ValueError, match="ambiguous"):
        match(capture, container, rows, bindings, [{"property": "title", "operator": "eq", "value": {"source": "constant", "value": "Same title"}}])
    rows[1]["properties"]["price"] = "$21"
    bindings["outputs"]["read-price.latest_price"]["value"] = "$21"
    selected = match(capture, container, rows, bindings, input_id() + [{"property": "price", "operator": "eq", "value": {"source": "output", "step_id": "read-price", "name": "latest_price"}}])
    assert selected["properties"]["price"] == "$21"
    with pytest.raises(ValueError, match="missing"):
        match(capture, container, rows, bindings, [{"property": "record_id", "operator": "eq", "value": {"source": "constant", "value": "absent"}}])


def test_stale_output_missing_input_and_incomplete_list_fail_closed():
    capture, container, rows, bindings = scene()
    bindings["outputs"]["read-price.latest_price"]["run_id"] = "run-old"
    with pytest.raises(ValueError, match="stale_output"):
        match(capture, container, rows, bindings, [{"property": "price", "operator": "eq", "value": {"source": "output", "step_id": "read-price", "name": "latest_price"}}])
    with pytest.raises(ValueError, match="missing_input"):
        match(capture, container, rows, bindings, [{"property": "record_id", "operator": "eq", "value": {"source": "input", "name": "unknown"}}])
    with pytest.raises(ValueError, match="incomplete"):
        match(capture, dict(container, complete=False), rows, bindings, input_id())


def test_stale_capture_wrong_window_out_of_bounds_and_other_row_action_rejected():
    capture, container, rows, bindings = scene()
    with pytest.raises(ValueError, match="capture"):
        match(dict(capture, capture_id="cap-3"), container, rows, bindings, input_id())
    with pytest.raises(ValueError, match="window"):
        match(dict(capture, window_identity={**capture["window_identity"], "handle": 999}), container, rows, bindings, input_id())
    with pytest.raises(ValueError, match="bbox"):
        match(capture, container, [dict(rows[0], bbox={"x": 20, "y": 50, "w": 900, "h": 40}), rows[1]], bindings, input_id())
    selected = match(capture, container, rows, bindings, input_id())
    selected["actions"][0]["row_id"] = "row-a"
    with pytest.raises(ValueError, match="row"):
        resolve_row_action(selected, {"name": "Open detail", "control_type": "Button"}, capture)


def test_current_layout_change_recomputes_action_point_without_old_coordinates():
    capture, container, rows, bindings = scene()
    capture["capture_id"] = "cap-3"
    capture["image_size"] = {"width": 1000, "height": 700}
    container["capture_id"] = "cap-3"
    for row in rows:
        row["capture_id"] = "cap-3"
        row["bbox"] = {**row["bbox"], "x": row["bbox"]["x"] + 30}
        for action in row["actions"]:
            action["capture_id"] = "cap-3"
            action["bbox"] = {**action["bbox"], "x": action["bbox"]["x"] + 30}
    selected = match(capture, container, rows, bindings, input_id())
    candidate = resolve_row_action(selected, {"name": "Open detail", "control_type": "Button"}, capture)["candidate"]
    assert candidate["capture_id"] == "cap-3"
    assert candidate["click_point"] == {"x": 425, "y": 130}


def test_duplicate_row_and_ambiguous_row_actions_refuse_selection():
    capture, container, rows, bindings = scene()
    with pytest.raises(ValueError, match="row_duplicate"):
        match(capture, container, [rows[0], rows[0]], bindings, input_id())
    selected = match(capture, container, rows, bindings, input_id())
    selected["actions"].append({**selected["actions"][0], "action_id": "open-other"})
    with pytest.raises(ValueError, match="row_action_ambiguous"):
        resolve_row_action(selected, {"name": "Open detail", "control_type": "Button"}, capture)


def test_nonfinite_process_incarnation_rejected():
    capture, container, rows, bindings = scene()
    capture["window_identity"] = {**capture["window_identity"], "process_create_time": float("inf")}
    with pytest.raises(ValueError, match="window_identity_invalid"):
        match(capture, container, rows, bindings, input_id())
