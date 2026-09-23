from app.operation.recognition.form_label_binding import bind_form_label, infer_form_label_bindings


def item(rid, name, kind, box, *, parent=(1,), labeled_by=None):
    return {"runtime_id": rid, "name": name, "control_type": kind,
            "bbox": box, "parent_id": parent, "labeled_by": labeled_by, "visible": True}


def test_unique_visible_label_binds_only_adjacent_unnamed_dropdown():
    nodes = [
        item((2,), "Eligibility to work", "Text", (451, 837, 180, 18)),
        item((3,), "", "ComboBox", (451, 857, 433, 30)),
        item((4,), "Desired Salary (optional)", "Text", (451, 986, 200, 18)),
        item((5,), "", "ComboBox", (451, 1006, 433, 31)),
        item((6,), "", "ComboBox", (451, 1036, 433, 30)),
    ]
    assert bind_form_label("Eligibility to work", "ComboBox", nodes) == (3,)
    assert bind_form_label("Desired Salary (optional)", "ComboBox", nodes) is None


def test_explicit_labeled_by_takes_priority_over_geometry():
    nodes = [item((2,), "Eligibility to work", "Text", (451, 837, 180, 18)),
             item((3,), "", "ComboBox", (451, 857, 433, 30)),
             item((4,), "", "ComboBox", (451, 1006, 433, 31), labeled_by=(2,))]
    assert bind_form_label("Eligibility to work", "ComboBox", nodes) == (4,)


def test_duplicate_target_labels_or_overlapping_controls_refuse_binding():
    nodes = [item((2,), "Eligibility to work", "Text", (451, 837, 180, 18)),
             item((3,), "Eligibility to work", "Text", (451, 837, 180, 18)),
             item((4,), "", "ComboBox", (451, 857, 433, 30))]
    assert bind_form_label("Eligibility to work", "ComboBox", nodes) is None
    nodes.pop(1)
    nodes.append(item((5,), "", "ComboBox", (451, 857, 433, 30)))
    assert bind_form_label("Eligibility to work", "ComboBox", nodes) is None


def test_different_parent_or_distant_label_never_authorizes_geometry():
    nodes = [item((2,), "Eligibility to work", "Text", (451, 837, 180, 18)),
             item((3,), "", "ComboBox", (451, 857, 433, 30), parent=(9,))]
    assert bind_form_label("Eligibility to work", "ComboBox", nodes) is None
    nodes[1]["parent_id"] = (1,)
    nodes[1]["bbox"] = (451, 1006, 433, 31)
    assert bind_form_label("Eligibility to work", "ComboBox", nodes) is None


def test_visible_label_is_alias_for_named_field_without_replacing_its_name():
    nodes = [item((2,), "Email", "Text", (451, 837, 180, 18)),
             item((3,), "Email address", "Edit", (451, 857, 433, 30))]
    nodes[1]["control_id"] = "field-3"
    assert infer_form_label_bindings(nodes) == [{"control_id": "field-3", "runtime_id": [3],
        "label": "Email", "source": "visible_label_geometry"}]
    assert nodes[1]["name"] == "Email address"


def test_snapshot_ancestor_chain_uses_nearest_parent_first():
    label = item((2,), "Email", "Text", (451, 837, 180, 18))
    field = item((3,), "Email address", "Edit", (451, 857, 433, 30))
    label.pop("parent_id")
    field.pop("parent_id")
    label["ancestor_control_ids"] = ["group-a", "document"]
    field["ancestor_control_ids"] = ["group-b", "document"]
    assert infer_form_label_bindings([label, field]) == []
    field["ancestor_control_ids"][0] = "group-a"
    assert infer_form_label_bindings([label, field])[0]["label"] == "Email"


def test_unknown_visibility_cannot_be_used_as_current_label_evidence():
    nodes = [item((2,), "Email", "Text", (451, 837, 180, 18)),
             item((3,), "", "Edit", (451, 857, 433, 30))]
    nodes[0].pop("visible")
    assert infer_form_label_bindings(nodes) == []


def test_file_buttons_bind_by_unique_adjacent_labels_despite_same_name():
    cover = item((10,), "选择文件: 未选择文件", "Button", (451, 182, 240, 24))
    qualification = item((11,), "选择文件: 未选择文件", "Button", (451, 241, 240, 24))
    cover["patterns"] = ["Invoke", "Value"]
    qualification["patterns"] = ["Invoke", "Value"]
    cover["control_id"] = "file-cover"
    qualification["control_id"] = "file-qualification"
    nodes = [item((2,), "Cover Letter Text", "Text", (451, 160, 70, 15)), cover,
             item((3,), "qualification", "Text", (451, 219, 100, 15)), qualification]
    bindings = infer_form_label_bindings(nodes)
    assert bindings == [
        {"control_id": "file-cover", "runtime_id": [10], "label": "Cover Letter Text",
         "source": "visible_label_geometry"},
        {"control_id": "file-qualification", "runtime_id": [11], "label": "qualification",
         "source": "visible_label_geometry"},
    ]
    assert bind_form_label("Cover Letter Text", "Button", nodes) == (10,)
    assert bind_form_label("qualification", "Button", nodes) == (11,)
    assert cover["name"] == qualification["name"] == "选择文件: 未选择文件"


def test_only_invoke_value_buttons_are_file_control_candidates():
    label = item((2,), "Resume", "Text", (451, 160, 70, 15))
    button = item((3,), "Choose file", "Button", (451, 182, 240, 24))
    button["patterns"] = ["Invoke"]
    assert bind_form_label("Resume", "Button", [label, button]) is None
    button["patterns"] = ["Invoke", "Value"]
    assert bind_form_label("Resume", "Button", [label, button]) == (3,)
    ordinary = item((4,), "Open", "Button", (451, 182, 240, 24))
    ordinary["patterns"] = ["Invoke"]
    assert bind_form_label("Resume", "Button", [label, ordinary]) is None


def test_tall_file_button_does_not_shadow_adjacent_preferred_name_edit():
    label = item((42, 879), "Preferred Name", "Text", (1047, 443, 91, 15))
    field = item((42, 15), "\ufffc", "Edit", (1047, 465, 451, 31))
    field["control_id"] = "uia_58_candidatecustomfield_1"
    upload = item((42, 8), "Choose file", "Button", (1030, 270, 190, 1378))
    upload["patterns"] = ["Invoke", "Value"]
    upload["control_id"] = "uia_48_candidateresume"
    nodes = [upload, label, field]
    assert bind_form_label("Preferred Name", "Edit", nodes) == (42, 15)
    assert infer_form_label_bindings(nodes) == [{
        "control_id": "uia_58_candidatecustomfield_1", "runtime_id": [42, 15],
        "label": "Preferred Name", "source": "visible_label_geometry"}]
    upload["bbox"] = (1030, 270, 190, 248)
    assert bind_form_label("Preferred Name", "Edit", nodes) is None
