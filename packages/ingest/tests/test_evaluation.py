import pytest
from ingest import AnnotationError, evaluate_model, evaluate_rooms, load_annotation, rect_iou


def annotation():
    return {
        "schema_version": "stage-4e-annotation-v1",
        "asset_sha256": "a" * 64,
        "pixel_size": {"width": 800, "height": 600},
        "rooms": [{"id": "room-a", "rect": [10, 20, 300, 200]},
                  {"id": "room-b", "rect": [320, 20, 200, 200]}],
        "walls": [{"id": "wall-a", "axis": "h", "x": 10, "y": 20, "length": 300}],
        "openings": [{"id": "opening-a", "host_wall_id": "wall-a", "kind": "door", "offset": 100, "width": 80}],
    }


def test_annotation_contract_normalizes_and_validates_references():
    normalized = load_annotation(annotation())
    assert normalized["schema_version"] == "stage-4e-annotation-v1"
    assert normalized["rooms"][0]["rect"] == [10.0, 20.0, 300.0, 200.0]
    assert normalized["openings"][0]["host_wall_id"] == "wall-a"


@pytest.mark.parametrize("mutator, message", [
    (lambda value: value.update(schema_version="bad"), "schema_version"),
    (lambda value: value.update(asset_sha256="bad"), "asset_sha256"),
    (lambda value: value["rooms"].append(value["rooms"][0].copy()), "duplicate ids"),
    (lambda value: value["openings"][0].update(host_wall_id="missing"), "unknown wall"),
    (lambda value: value["walls"][0].update(axis=[]), "axis must"),
    (lambda value: value["openings"][0].update(kind={}), "kind must"),
])
def test_annotation_contract_rejects_invalid_documents(mutator, message):
    value = annotation()
    mutator(value)
    with pytest.raises(AnnotationError, match=message):
        load_annotation(value)


def test_room_metrics_are_deterministic_and_thresholded():
    truth = annotation()["rooms"]
    predicted = [{"id": "p-a", "rect": [10, 20, 300, 200]},
                 {"id": "p-b", "rect": [340, 20, 180, 200]},
                 {"id": "p-extra", "rect": [600, 20, 100, 100]}]
    result = evaluate_rooms(predicted, truth)
    assert result["matched_count"] == 1
    assert result["precision"] == pytest.approx(1 / 3)
    assert result["recall"] == 0.5
    assert result["f1"] == pytest.approx(0.4)
    assert result["matches"][0]["predicted_id"] == "p-a"
    assert evaluate_rooms(predicted, truth) == result


def test_room_metrics_reject_duplicate_prediction_ids():
    truth = annotation()["rooms"]
    with pytest.raises(AnnotationError, match="duplicate ids"):
        evaluate_rooms([{"id": "same", "rect": truth[0]["rect"]},
                        {"id": "same", "rect": truth[1]["rect"]}], truth)


def test_room_metrics_validate_empty_prediction_truth_and_boolean_threshold():
    with pytest.raises(AnnotationError, match="truth room broken.rect"):
        evaluate_rooms([], [{"id": "broken", "rect": [0, 0, -1, 10]}])
    with pytest.raises(AnnotationError, match="between 0 and 1"):
        evaluate_rooms([], [], iou_threshold=True)


def test_evaluate_model_maps_world_rectangles_to_annotation_pixels():
    model = {"source": {"sha256": "a" * 64},
             "ingest": {"pixel_size": {"width": 800.0, "height": 600.0}, "mm_per_pixel": 10},
             "rooms": [{"id": "room-a", "rect": [100, 200, 3000, 2000]},
                       {"id": "room-extra", "rect": [9000, 200, 1000, 1000]}]}
    result = evaluate_model(model, annotation())
    assert result["rooms"]["matched_count"] == 1
    assert result["rooms"]["recall"] == 0.5


def test_rect_iou_handles_non_overlap_and_exact_match():
    assert rect_iou([0, 0, 10, 10], [20, 20, 2, 2]) == 0
    assert rect_iou([0, 0, 10, 10], [0, 0, 10, 10]) == 1
