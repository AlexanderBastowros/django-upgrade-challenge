"""OpenAPI contract tests.

* The schema must generate with zero drf-spectacular warnings/errors and
  validate against the OpenAPI 3 spec.
* The documented API surface (method + path) must match the snapshot in
  ``tests/snapshots/api_surface.txt``. If you intentionally add/remove an
  endpoint, regenerate with ``UPDATE_API_SNAPSHOT=1 pytest tests/test_schema.py``.
"""
import os
from pathlib import Path

import pytest
import yaml
from django.core.management import call_command

SNAPSHOT = Path(__file__).parent / "snapshots" / "api_surface.txt"
HTTP_METHODS = {"get", "post", "put", "patch", "delete"}


@pytest.fixture(scope="module")
def schema(tmp_path_factory, django_db_blocker):
    path = tmp_path_factory.mktemp("schema") / "schema.yml"
    with django_db_blocker.unblock():
        call_command("spectacular", "--file", str(path), "--validate", "--fail-on-warn")
    return yaml.safe_load(path.read_text())


def surface(schema):
    return sorted(
        "%s %s" % (method.upper(), path)
        for path, item in schema["paths"].items()
        for method in item
        if method in HTTP_METHODS
    )


def test_api_surface_matches_snapshot(schema):
    current = surface(schema)
    if os.environ.get("UPDATE_API_SNAPSHOT"):
        SNAPSHOT.write_text("\n".join(current) + "\n")
    expected = SNAPSHOT.read_text().split("\n")
    expected = [line for line in expected if line]
    missing = sorted(set(expected) - set(current))
    added = sorted(set(current) - set(expected))
    assert not missing and not added, "missing=%s added=%s" % (missing, added)


def test_every_operation_is_tagged_and_has_success_response(schema):
    for path, item in schema["paths"].items():
        for method, op in item.items():
            if method not in HTTP_METHODS:
                continue
            assert op.get("tags"), "%s %s has no tags" % (method, path)
            assert any(code.startswith("2") for code in op["responses"]), "%s %s has no 2xx" % (method, path)


def test_crud_resource_count(schema):
    crud = [
        path
        for path, item in schema["paths"].items()
        if path.endswith("{id}/") and {"get", "put", "patch", "delete"} <= set(item)
    ]
    assert len(crud) >= 20, crud


def test_bearer_auth_documented(schema):
    schemes = schema["components"]["securitySchemes"]
    assert schemes["jwtAuth"]["scheme"] == "bearer"


def test_enum_names_are_stable(schema):
    names = set(schema["components"]["schemas"])
    for enum in (
        "OrderStatusEnum",
        "PaymentStatusEnum",
        "ShipmentStatusEnum",
        "ProductStatusEnum",
        "StoreStatusEnum",
        "ActionVerbEnum",
    ):
        assert enum in names
