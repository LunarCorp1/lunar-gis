"""End-to-end suitability workflow (offline, deterministic).

Scenario: "Find suitable locations for a health facility using
available spatial data."

Conceptual chain under test (all offline-capable steps execute for
real; QGIS/network/LLM steps are represented by their validated
offline seams):

request → offline plan → requirement → inventory → check (AVAILABLE)
→ AHP weighting → sensitivity → report → provenance lineage

No QGIS, no network, no LLM. Every step asserts real outputs.
"""

from __future__ import annotations

from lunar_gis.agent.execution import ControlledExecutor
from lunar_gis.agent.registry import ToolExecutionContext
from lunar_gis.data.data_tools import check_requirement_handler
from lunar_gis.data.discovery_qgis import discover_project
from lunar_gis.data.fulfillment import plan_from_dicts
from lunar_gis.reports.report_tools import generate_handler
from lunar_gis.ui.controller import build_registry, create_executor, default_context, run_tool
from tests.fixtures.qgis_fakes import (
    FakeExtent,
    FakeFeature,
    FakeFields,
    FakeField,
    FakeGeometry,
    FakeLayer,
    FakeProject,
)

TAKEN_AT = "2026-09-21T00:00:00+00:00"


def _project() -> FakeProject:
    clinics = FakeLayer(
        layer_id="clinics",
        name="clinics",
        provider="ogr",
        geometry_type=0,
        feature_count=4,
        crs_authid="EPSG:4326",
        extent=FakeExtent(0.0, 0.0, 10.0, 10.0),
        fields=FakeFields([FakeField("id", "Int"), FakeField("capacity", "Int")]),
        is_valid=True,
        source="/data/clinics.gpkg",
        features=[
            FakeFeature(fid=i + 1, attributes={"id": i + 1, "capacity": 10 * i}, geometry=FakeGeometry(valid=True))
            for i in range(4)
        ],
    )
    roads = FakeLayer(
        layer_id="roads",
        name="roads",
        provider="ogr",
        geometry_type=1,
        feature_count=6,
        crs_authid="EPSG:4326",
        extent=FakeExtent(0.0, 0.0, 10.0, 10.0),
        fields=FakeFields([FakeField("id", "Int")]),
        is_valid=True,
        source="/data/roads.gpkg",
        features=[
            FakeFeature(fid=i + 1, attributes={"id": i + 1}, geometry=FakeGeometry(valid=True)) for i in range(6)
        ],
    )
    return FakeProject(layers={"clinics": clinics, "roads": roads})


def test_suitability_workflow_end_to_end() -> None:
    user_request = "Find suitable locations for a health facility using available spatial data"

    # 1. Offline plan drafts a requirement (heuristic, labeled).
    from lunar_gis.ai.planner import plan_offline

    plan = plan_offline(user_request)
    assert plan.ok is True
    assert plan.requirement is not None
    assert plan.requirement["geometry"] == "Point"

    # 2. Inventory snapshot over the fake project.
    inventory = discover_project(_project(), taken_at=TAKEN_AT)
    assert inventory.total_count == 2
    assert [r.layer_id for r in inventory.records] == ["clinics", "roads"]

    # 3. Requirement → AVAILABLE local layer (clinics).
    requirement = {
        "name": "health-facility-sites",
        "geometry": "Point",
        "required_fields": ["capacity"],
        "field_types": {"capacity": "Int"},
    }
    fulfillment = plan_from_dicts(requirement, inventory)
    assert fulfillment.availability.value == "available"
    assert fulfillment.layer_id == "clinics"

    # 4. Same verdict through the governed tool path.
    from lunar_gis.data.data_tools import _inventory_to_dict

    checked = check_requirement_handler({"requirement": requirement, "inventory": _inventory_to_dict(inventory)})
    assert checked["ok"] is True
    assert checked["availability"] == "available"

    # 5. AHP weighting through the governed executor (deterministic).
    registry = build_registry()
    executor: ControlledExecutor = create_executor(registry)
    context: ToolExecutionContext = default_context()
    ahp = run_tool(
        executor,
        "analysis.ahp",
        {
            "criteria": ["proximity", "capacity", "cost"],
            "matrix": [[1, 3, 5], [1 / 3, 1, 3], [1 / 5, 1 / 3, 1]],
        },
        context,
    )
    assert ahp["ok"] is True
    weights = ahp["output"]["data"]["weights"]
    assert abs(sum(weights) - 1.0) < 1e-9
    consistency = ahp["output"]["data"]["consistency_flag"]
    assert isinstance(consistency, str) and consistency

    # 6. Sensitivity through the governed executor.
    sens = run_tool(
        executor,
        "analysis.ahp_sensitivity",
        {
            "criteria": ["proximity", "capacity", "cost"],
            "matrix": [[1, 3, 5], [1 / 3, 1, 3], [1 / 5, 1 / 3, 1]],
        },
        context,
    )
    assert sens["ok"] is True

    # 7. Reproducible report over the whole chain.
    report = generate_handler(
        {
            "title": "Health facility suitability",
            "user_request": user_request,
            "sections": {
                "requirements": [requirement],
                "data_used": [{"ref": "clinics", "kind": "layer-ref", "validation": "VALID"}],
                "analysis": [
                    {
                        "title": "AHP weighting",
                        "weights": dict(zip(["proximity", "capacity", "cost"], weights)),
                        "cr": ahp["output"]["data"]["cr"],
                        "consistency_flag": consistency,
                    }
                ],
                "results": [{"summary": "clinics layer satisfies the Point+capacity requirement"}],
                "warnings": list(fulfillment.warnings),
                "engine_versions": {"ahp": "2.0.0"},
            },
        }
    )
    assert report["ok"] is True
    assert "Health facility suitability" in report["html"]
    assert report["identity"]

    # 8. Provenance: register the outcome, read the lineage back.
    from lunar_gis.provenance.records import make_record
    from lunar_gis.provenance.store import ProvenanceStore

    store = ProvenanceStore()
    identity = store.append(
        make_record(
            subject_kind="layer-ref",
            subject_ref="clinics",
            origin_kind="project",
            license_spdx="NONE-declared",
            retrieved_at=TAKEN_AT,
            requirement_ref="health-facility-sites",
        )
    )
    lineage = store.lineage(identity)
    assert lineage["found"] is True
    assert lineage["subject"]["ref"] == "clinics"

    # 9. Repeatability: same inputs → same classification + same report identity.
    again = plan_from_dicts(requirement, inventory)
    assert again == fulfillment
    report2 = generate_handler(
        {
            "title": "Health facility suitability",
            "user_request": user_request,
            "sections": {
                "requirements": [requirement],
                "data_used": [{"ref": "clinics", "kind": "layer-ref", "validation": "VALID"}],
                "analysis": [
                    {
                        "title": "AHP weighting",
                        "weights": dict(zip(["proximity", "capacity", "cost"], weights)),
                        "cr": ahp["output"]["data"]["cr"],
                        "consistency_flag": consistency,
                    }
                ],
                "results": [{"summary": "clinics layer satisfies the Point+capacity requirement"}],
                "warnings": list(fulfillment.warnings),
                "engine_versions": {"ahp": "2.0.0"},
            },
        }
    )
    assert report2["identity"] == report["identity"]
