from __future__ import annotations

from conftest import load_script_module


def _load_module():
    return load_script_module("harness_bootstrap_wizard", "scripts/harness_bootstrap_wizard.py")


def test_bootstrap_goal_template_uses_product_goal_not_mvp() -> None:
    module = _load_module()
    drafts = module.build_drafts(
        {
            "product_name": "Chat",
            "product_goal": "배포 가능한 채팅 서비스",
            "primary_users": "운영자와 사용자",
            "main_paths": ["src/**", "tests/**"],
            "validation_command": "npm run validate",
            "first_goal_active": True,
        }
    )

    goals = next(draft.content for draft in drafts if draft.path.as_posix() == "docs/harness/GOALS.md")
    assert "## Goal: Chat 제품 목표" in goals
    assert "## Goal: Chat MVP" not in goals
    assert '"product"' in goals
    assert '"mvp"' not in goals
