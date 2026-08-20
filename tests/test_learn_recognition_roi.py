from app.learn.recognition.roi import bounded_roi_crop_size_for_bbox, build_roi_crop_metadata, restore_local_point_to_screen


def test_roi_transform_replays_local_point_to_screen_point():
    roi = build_roi_crop_metadata(
        source_image_size={"width": 1000, "height": 800},
        candidate_bbox={"x": 400, "y": 300, "w": 100, "h": 40},
        crop_size={"width": 300, "height": 120},
        expand_scale=2.0,
    )

    point = restore_local_point_to_screen(roi["coordinate_transform"], {"x": 150, "y": 60})

    assert roi["contract_version"] == "learn_roi_crop_v1"
    assert roi["coordinate_transform"]["roi_bbox"] == {"x": 350, "y": 280, "w": 200, "h": 80}
    assert roi["coordinate_transform"]["scale_x"] == 1.5
    assert roi["coordinate_transform"]["scale_y"] == 1.5
    assert point == {"x": 450, "y": 320}


def test_roi_expansion_clamps_to_source_image_bounds():
    roi = build_roi_crop_metadata(
        source_image_size={"width": 300, "height": 200},
        candidate_bbox={"x": 5, "y": 4, "w": 80, "h": 40},
        crop_size={"width": 160, "height": 80},
        expand_scale=3.0,
    )

    assert roi["coordinate_transform"]["roi_bbox"] == {"x": 0, "y": 0, "w": 240, "h": 120}
    assert restore_local_point_to_screen(roi["coordinate_transform"], {"x": 0, "y": 0}) == {"x": 0, "y": 0}


def test_bounded_roi_crop_size_caps_wide_search_fields_without_dropping_height():
    crop_size = bounded_roi_crop_size_for_bbox({"x": 633, "y": 184, "w": 850, "h": 48})
    roi = build_roi_crop_metadata(
        source_image_size={"width": 2560, "height": 1400},
        candidate_bbox={"x": 633, "y": 184, "w": 850, "h": 48},
        crop_size=crop_size,
        expand_scale=2.0,
    )

    assert crop_size == {"width": 768, "height": 96}
    assert roi["coordinate_transform"]["scale_x"] == 0.451765
    assert roi["coordinate_transform"]["scale_y"] == 1.0
