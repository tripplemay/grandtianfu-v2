from spatial_core import ModelValidationError, validate_model


def base_model():
    return {
        "schema_version": "2.0",
        "model_id": "model-1",
        "revision": 1,
        "units": {"length": "mm", "angle": "deg"},
        "source": {"asset_id": "asset-1", "kind": "bitmap", "sha256": "abc"},
        "confidence": 0.8,
        "rooms": [{"id": "room-1"}],
        "walls": [{"id": "wall-1"}],
        "openings": [],
        "furniture_instances": [
            {
                "id": "sofa-1",
                "catalog_id": "sofa",
                "transform": {"x": 1000, "y": 2000, "z": 0, "rotation_z": 90},
                "dimensions": {"width": 2200, "depth": 900, "height": 850},
                "room_id": "room-1",
                "confidence": 1.0,
            }
        ],
        "cameras": [],
        "materials": [],
    }


def test_valid_model_is_returned_unchanged():
    model = base_model()
    assert validate_model(model) is model


def test_duplicate_object_ids_are_rejected():
    model = base_model()
    model["rooms"].append({"id": "room-1"})
    try:
        validate_model(model)
    except ModelValidationError as exc:
        assert "duplicate id" in str(exc)
    else:
        raise AssertionError("duplicate ids must fail")


def test_non_positive_furniture_dimensions_are_rejected():
    model = base_model()
    model["furniture_instances"][0]["dimensions"]["width"] = 0
    try:
        validate_model(model)
    except ModelValidationError as exc:
        assert "width" in str(exc)
    else:
        raise AssertionError("non-positive dimensions must fail")

