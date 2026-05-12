#!/usr/bin/env python3
from __future__ import annotations

# Phase H keeps `cycle.py` as the public orchestration surface while
# implementation-heavy helpers live in smaller package modules.

from .core import *  # noqa: F401,F403
from .core import build_parser as build_parser
from .core import main as main
from .core import run_cycle as run_cycle
from .core import run_loop as run_loop
from .contracts import (
    check_meta_lane_exemption as check_meta_lane_exemption,
    check_test_touches_changed_symbols as check_test_touches_changed_symbols,
    inspect_test_substance as inspect_test_substance,
    load_goal_contracts as load_goal_contracts,
    parse_manager_scope_contract as parse_manager_scope_contract,
    require_goal_anchor as require_goal_anchor,
    validate_implementer_manifest_and_write_evidence as validate_implementer_manifest_and_write_evidence,
    validate_paths_against_scope as validate_paths_against_scope,
    validate_scope_against_backlog as validate_scope_against_backlog,
    validate_selection_scope_identity as validate_selection_scope_identity,
    verify_goal_anchor as verify_goal_anchor,
)
from .live_status import (
    StatusSnapshot as StatusSnapshot,
    build_status_snapshot as build_status_snapshot,
    render_status as render_status,
)
from .model_strategy import resolve_runner_model_plan as resolve_runner_model_plan
from .prompts import (
    build_common_prompt_header as build_common_prompt_header,
    build_lane_prompt as build_lane_prompt,
)
from .routing import (
    activate_selected_backlog_item as activate_selected_backlog_item,
    build_goal_candidate_state as build_goal_candidate_state,
    build_goal_failure_pattern_summary as build_goal_failure_pattern_summary,
    build_goal_progress_summary as build_goal_progress_summary,
    build_goal_program_lane_guidance as build_goal_program_lane_guidance,
    classify_backlog_lane as classify_backlog_lane,
    classify_backlog_lane_from_metadata as classify_backlog_lane_from_metadata,
    collect_goal_maintenance_gaps as collect_goal_maintenance_gaps,
    complete_backlog_item_if_needed as complete_backlog_item_if_needed,
    discover_active_goal_programs as discover_active_goal_programs,
    discover_goal_programs as discover_goal_programs,
    goal_program_by_id as goal_program_by_id,
    prepare_cycle_workspace as prepare_cycle_workspace,
    render_goal_program_focus as render_goal_program_focus,
    select_goal_strategy_summary as select_goal_strategy_summary,
    select_next_autonomy_backlog_item as select_next_autonomy_backlog_item,
    select_next_goal_program_backlog_item as select_next_goal_program_backlog_item,
    select_task as select_task,
)

__all__ = tuple(name for name in globals() if not name.startswith("_"))
