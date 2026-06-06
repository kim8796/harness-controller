from __future__ import annotations

from conftest import load_script_module


def _load_module():
    return load_script_module("harness_gate_router", "scripts/harness_gate_router.py")


def test_route_pending_gates_splits_product_setup_and_external_actions() -> None:
    module = _load_module()
    route = module.route_pending_gates(
        pending_gate_ids=["auth", "store_release_readiness", "ui_backend_integration"],
        setup_readiness={"missing_gate_ids": ["auth"]},
    )

    assert route["primary_action_kind"] == "product-actionable"
    assert route["pending_gate_ids"] == ["auth", "store_release_readiness", "ui_backend_integration"]
    assert route["by_kind"]["setup-actionable"] == ["auth"]
    assert route["by_kind"]["external-account"] == ["store_release_readiness"]
    assert route["by_kind"]["product-actionable"] == ["ui_backend_integration"]


def test_setup_only_pending_gate_routes_to_setup_action() -> None:
    module = _load_module()
    route = module.route_pending_gates(
        pending_gate_ids=["auth"],
        setup_readiness={"missing_gate_ids": ["auth"]},
    )

    assert route["primary_action_kind"] == "setup-actionable"
    assert route["by_kind"]["setup-actionable"] == ["auth"]


def test_controller_and_publication_gate_reasons_route_to_non_product_actions() -> None:
    module = _load_module()
    route = module.route_pending_gates(
        pending_gate_ids=["deployment", "db_persistence"],
        reason_by_gate={
            "deployment": "merge pending for PR #7",
            "db_persistence": "controller verifier crashed while checking gate",
        },
    )

    assert route["by_kind"]["publication-actionable"] == ["deployment"]
    assert route["by_kind"]["controller-actionable"] == ["db_persistence"]
    assert route["primary_action_kind"] == "publication-actionable"


def test_gate_router_detects_gate_debt_from_status_payload() -> None:
    module = _load_module()

    assert module.has_pending_gate_debt({"goal_gate_status": {"status": "pending", "pending_gate_ids": ["auth"]}})
    assert module.has_pending_gate_debt(
        {"goal_gate_status": {"status": "pending", "pending_gate_ids": ["store_release_readiness"]}}
    )
    assert not module.has_pending_gate_debt(
        {"goal_gate_status": {"status": "passed", "pending_gate_ids": ["auth"]}}
    )
