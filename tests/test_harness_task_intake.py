from __future__ import annotations

from pathlib import Path

import pytest

from conftest import load_script_module


def _load_module():
    return load_script_module("harness_task_intake", "scripts/harness_task_intake.py")


def _safe_request() -> str:
    return "\n".join(
        [
            "# Add welcome copy",
            "",
            "## Goal",
            "- Add concise welcome copy to the product README.",
            "",
            "## Summary",
            "- Update README.md with a short operator-visible note.",
            "",
            "## Acceptance",
            "- README.md contains the welcome copy.",
            "",
            "## File Scope",
            "- README.md",
            "",
            "## Forbidden Scope",
            "- .env*",
            "- runs/**",
            "- reports/**",
            "- targets/**",
            "",
            "## Validation",
            "- `git diff -- README.md`",
            "",
        ]
    )


def test_task_intake_draft_review_and_queue_auto(tmp_path: Path) -> None:
    module = _load_module()
    state_root = tmp_path / "targets" / "demo"

    request = module.create_draft(
        state_root=state_root,
        target_id="demo",
        title="Add welcome copy",
        packet_id="task-demo",
    )
    request.write_text(_safe_request(), encoding="utf-8")

    review = module.review_packet(state_root=state_root, packet_id="task-demo")
    assert review.auto_eligible is True
    assert review.open_questions == ()
    assert "Autonomy-Execute: auto" in review.preview_path.read_text(encoding="utf-8")
    assert not (state_root / "backlog" / "queued").exists()

    queued = module.queue_packet(state_root=state_root, packet_id="task-demo", auto=True)

    body = queued.backlog_path.read_text(encoding="utf-8")
    assert queued.autonomy_execute == "auto"
    assert "Status: queued" in body
    assert "Autonomy-Execute: auto" in body
    assert "Target-ID: demo" in body
    assert "Intake-Packet: task-demo" in body
    discovered = module.harness_loop.discover_backlog_items(state_root)
    assert [item.item_id for item in discovered] == [queued.backlog_id]


def test_task_review_normalizes_natural_language_request_to_canonical_preview(tmp_path: Path) -> None:
    module = _load_module()
    state_root = tmp_path / "targets" / "demo"
    request = module.create_draft(
        state_root=state_root,
        target_id="demo",
        title="Add support note",
        packet_id="task-natural-language",
    )
    request.write_text(
        "\n".join(
            [
                "# Add support note",
                "",
                "Please update README.md with a short support note for operators. "
                "The change is accepted when README.md contains the support note. "
                "Only README.md should change. Validate it with `git diff -- README.md`.",
                "",
            ]
        ),
        encoding="utf-8",
    )

    review = module.review_packet(state_root=state_root, packet_id="task-natural-language")
    preview = review.preview_path.read_text(encoding="utf-8")

    assert review.auto_eligible is True
    assert review.open_questions == ()
    assert review.risk_flags == ()
    assert "Autonomy-Execute: auto" in preview
    assert "## Acceptance" in preview
    assert "README.md contains the support note" in preview
    assert "## File Scope" in preview
    assert "- README.md" in preview
    assert "## Validation" in preview
    assert "- `git diff -- README.md`" in preview
    assert not (state_root / "backlog" / "queued").exists()

    queued = module.queue_packet(state_root=state_root, packet_id="task-natural-language", auto=True)
    body = queued.backlog_path.read_text(encoding="utf-8")
    assert queued.autonomy_execute == "auto"
    assert "Source: task-intake" in body
    assert "Intake-Packet: task-natural-language" in body


def test_task_review_preserves_colon_required_behavior_as_acceptance(tmp_path: Path) -> None:
    module = _load_module()
    state_root = tmp_path / "targets" / "chatapp-test"
    repo = tmp_path / "chatapp-test"
    for relative in ("src/seed.js", "src/app.js", "tests/seed.test.js"):
        path = repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("// fixture\n", encoding="utf-8")
    (repo / "package.json").write_text('{"scripts":{"validate":"node --test"}}\n', encoding="utf-8")
    request = module.create_draft(
        state_root=state_root,
        target_id="chatapp-test",
        title="demo provider seeds",
        packet_id="task-colon-sections",
    )
    request.write_text(
        "\n".join(
            [
                "# demo provider seeds",
                "",
                "Goal:",
                "- Remove overseas region/country/language dummy content from demo and provider-test visible seed data.",
                "",
                "Required behavior:",
                "- Allowed regions: 전체, 서울, 인천, 대전, 대구, 울산, 부산, 경기, 강원, 세종, 제주, 충북, 충남, 전남, 경북, 경남.",
                "- Provide at least 60 discovery users and at least 60 feed items for scroll testing.",
                "- Remove visible language-exchange labels and overseas locations such as California, New York, Fukuoka.",
                "",
                "File Scope:",
                "- src/seed.js",
                "- src/app.js",
                "- tests/**",
                "",
                "Validation:",
                "- `npm run validate`",
                "",
                "Acceptance:",
                "- Demo mode after pressing 데모 시작 shows only Korean regions/personas.",
                "- Demo/provider-test seed fixtures remain excluded from production gate evidence.",
                "",
            ]
        ),
        encoding="utf-8",
    )

    review = module.review_packet(state_root=state_root, packet_id="task-colon-sections", target_repo=repo)
    preview = review.preview_path.read_text(encoding="utf-8")

    assert review.auto_eligible is True
    assert "Remove overseas region/country/language" in preview
    assert "Allowed regions: 전체, 서울" in preview
    assert "at least 60 discovery users" in preview
    assert "California, New York, Fukuoka" in preview
    assert "Demo mode after pressing 데모 시작" in preview
    assert "- src/seed.js" in preview
    assert "- `npm run validate`" in preview

    queued = module.queue_packet(state_root=state_root, packet_id="task-colon-sections", auto=True, target_repo=repo)
    body = queued.backlog_path.read_text(encoding="utf-8")
    assert "Allowed regions: 전체, 서울" in body
    assert "at least 60 discovery users" in body


def test_task_review_infers_gameplay_scope_for_korean_player_count_request(tmp_path: Path) -> None:
    module = _load_module()
    state_root = tmp_path / "targets" / "racegame"
    repo = tmp_path / "racegame"
    for relative in ("client/main.js", "client/styles.css", "server/game.js", "tests/game.test.js"):
        path = repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("// smoke\n", encoding="utf-8")
    (repo / "package.json").write_text(
        '{"scripts":{"lint":"eslint .","test":"node --test","build":"node --check server/game.js"}}\n',
        encoding="utf-8",
    )
    request = module.create_draft(
        state_root=state_root,
        target_id="racegame",
        title="1인 플레이 허용",
        packet_id="task-korean-player-count",
    )
    request.write_text("# 1인 플레이 허용\n\n지금 2인이 최소 인데 1인으로 플레이 가능하게 해\n", encoding="utf-8")

    review = module.review_packet(state_root=state_root, packet_id="task-korean-player-count", target_repo=repo)
    preview = review.preview_path.read_text(encoding="utf-8")

    assert review.auto_eligible is True
    assert review.open_questions == ()
    assert review.risk_flags == ()
    assert "## File Scope" in preview
    assert "- server/**" in preview
    assert "- client/**" in preview
    assert "- tests/**" in preview
    assert "Autonomy-Execute: auto" in preview
    assert "inferred-file-scope" in review.normalization_actions


def test_task_review_infers_provider_ai_and_migration_scope(tmp_path: Path) -> None:
    module = _load_module()
    state_root = tmp_path / "targets" / "chatapp-test"
    repo = tmp_path / "chatapp-test"
    for relative in (
        "src/app.js",
        "src/app/api/ai/reply/route.js",
        "src/lib/openai/ai-replies.js",
        "tests/production-contract.test.js",
        "supabase/migrations/0002_social_discovery_schema.sql",
    ):
        path = repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("// smoke\n", encoding="utf-8")
    (repo / "package.json").write_text('{"scripts":{"test":"node --test","build":"next build"}}\n', encoding="utf-8")
    request = module.create_draft(
        state_root=state_root,
        target_id="chatapp-test",
        title="provider-test AI reply fix",
        packet_id="task-provider-ai-scope",
    )
    request.write_text(
        "\n".join(
            [
                "# provider-test AI reply fix",
                "",
                "provider-test AI 채팅이 /api/ai/reply에서 openai_incomplete_response를 반환한다.",
                "OpenAI Responses API 응답을 안정화하고 profile_public_id_seq migration bug도 확인한다.",
                "검증: npm test 그리고 npm run build",
            ]
        ),
        encoding="utf-8",
    )

    review = module.review_packet(state_root=state_root, packet_id="task-provider-ai-scope", target_repo=repo)
    preview = review.preview_path.read_text(encoding="utf-8")

    assert review.auto_eligible is True
    assert review.open_questions == ()
    assert "## File Scope" in preview
    assert "- src/**" in preview
    assert "- tests/**" in preview
    assert "- supabase/migrations/**" in preview
    assert "Autonomy-Execute: auto" in preview
    assert "inferred-file-scope" in review.normalization_actions


def test_task_review_normalization_does_not_make_unsafe_natural_language_auto(tmp_path: Path) -> None:
    module = _load_module()
    state_root = tmp_path / "targets" / "demo"
    request = module.create_draft(
        state_root=state_root,
        target_id="demo",
        title="Rotate env token",
        packet_id="task-unsafe-natural-language",
    )
    request.write_text(
        "\n".join(
            [
                "# Rotate env token",
                "",
                "Please update .env.local with the new API token and verify by running `cat .env.local`. "
                "The change is accepted when the token is present.",
                "",
            ]
        ),
        encoding="utf-8",
    )

    review = module.review_packet(state_root=state_root, packet_id="task-unsafe-natural-language")

    assert review.auto_eligible is False
    assert review.risk_flags
    assert "Autonomy-Execute: manual-review" in review.preview_path.read_text(encoding="utf-8")
    with pytest.raises(module.TaskIntakeError, match="auto queue 불가"):
        module.queue_packet(state_root=state_root, packet_id="task-unsafe-natural-language", auto=True)


@pytest.mark.parametrize(
    "command",
    [
        "`rm -fr .`",
        "`git clean -fd`",
        "`vercel --prod`",
        "`fly deploy`",
        "`wrangler deploy`",
        "`drizzle-kit push`",
        "`supabase db reset`",
        "`rm -rf README.md`",
        "`rm --recursive --force .`",
        "`python manage.py migrate`",
        "`npm run migrate`",
        "`python ./manage.py migrate`",
        "`python backend/manage.py migrate`",
        "`kubectl apply -f deployment.yaml`",
        "`gh workflow run deploy.yml`",
        "`python -m django migrate`",
        "`kubectl create -f deployment.yaml`",
        "`kubectl set image deployment/app app=image`",
        "`helm upgrade app chart/`",
        "`terraform apply -auto-approve`",
        "`npm run build:deploy`",
        "`npm run test:migrate`",
        "`pnpm run lint:db-reset`",
        "`yarn run check:publish`",
        "`make build-deploy`",
        "`just test-migrate`",
    ],
)
def test_task_review_rejects_validation_command_bypasses(tmp_path: Path, command: str) -> None:
    module = _load_module()
    state_root = tmp_path / "targets" / "demo"
    request = module.create_draft(state_root=state_root, target_id="demo", packet_id="task-dangerous-validation")
    request.write_text(_safe_request().replace("`git diff -- README.md`", command), encoding="utf-8")

    review = module.review_packet(state_root=state_root, packet_id="task-dangerous-validation")

    assert review.auto_eligible is False
    assert review.risk_flags


def test_task_review_rejects_package_script_body_mutation(tmp_path: Path) -> None:
    module = _load_module()
    state_root = tmp_path / "targets" / "demo"
    product = tmp_path / "product"
    product.mkdir()
    (product / "package.json").write_text(
        module.json.dumps({"scripts": {"build": "vercel deploy --prod", "test": "prisma migrate deploy"}}),
        encoding="utf-8",
    )
    request = module.create_draft(state_root=state_root, target_id="demo", packet_id="task-package-script")
    request.write_text(_safe_request().replace("`git diff -- README.md`", "`npm run build`"), encoding="utf-8")

    review = module.review_packet(state_root=state_root, packet_id="task-package-script", target_repo=product)

    assert review.auto_eligible is False
    assert "package script" in " ".join(review.risk_flags)


def test_task_review_allows_safe_package_validation_aggregates(tmp_path: Path) -> None:
    module = _load_module()
    state_root = tmp_path / "targets" / "demo"
    product = tmp_path / "product"
    product.mkdir()
    (product / "package.json").write_text(
        module.json.dumps(
            {
                "scripts": {
                    "validate": "npm run check && npm test && npm run build",
                    "check": "node --check src/app.js",
                    "test": "node --test",
                    "build": "next build",
                    "production:readiness": "node scripts/production-readiness.mjs",
                }
            }
        ),
        encoding="utf-8",
    )
    request = module.create_draft(state_root=state_root, target_id="demo", packet_id="task-safe-aggregate")
    request.write_text(_safe_request().replace("`git diff -- README.md`", "`npm run validate`"), encoding="utf-8")

    review = module.review_packet(state_root=state_root, packet_id="task-safe-aggregate", target_repo=product)

    assert review.auto_eligible is True
    assert review.risk_flags == ()

    readiness = module.create_draft(state_root=state_root, target_id="demo", packet_id="task-safe-readiness")
    readiness.write_text(_safe_request().replace("`git diff -- README.md`", "`npm run production:readiness`"), encoding="utf-8")
    readiness_review = module.review_packet(state_root=state_root, packet_id="task-safe-readiness", target_repo=product)
    assert readiness_review.auto_eligible is True


@pytest.mark.parametrize(
    ("scripts", "expected"),
    [
        ({"validate": "npm run deploy", "deploy": "vercel deploy --prod"}, "deploy"),
        ({"validate": "npm run db:reset", "db:reset": "supabase db reset"}, "destructive"),
        ({"validate": "OPENAI_API_KEY=sk-live-secret-value npm test"}, "secret"),
        ({"validate": "npm run validate"}, "cycle"),
        ({"validate": "next build & sh deploy.sh"}, "ampersand"),
        ({"validate": "next build\nsh deploy.sh"}, "newline"),
    ],
)
def test_task_review_rejects_unsafe_package_validation_aggregates(
    tmp_path: Path,
    scripts: dict[str, str],
    expected: str,
) -> None:
    module = _load_module()
    state_root = tmp_path / "targets" / "demo"
    product = tmp_path / "product"
    product.mkdir()
    (product / "package.json").write_text(module.json.dumps({"scripts": scripts}), encoding="utf-8")
    request = module.create_draft(state_root=state_root, target_id="demo", packet_id=f"task-unsafe-{expected}")
    request.write_text(_safe_request().replace("`git diff -- README.md`", "`npm run validate`"), encoding="utf-8")

    review = module.review_packet(state_root=state_root, packet_id=f"task-unsafe-{expected}", target_repo=product)

    assert review.auto_eligible is False
    assert review.risk_flags


def test_task_review_rejects_package_validation_forwarded_args(tmp_path: Path) -> None:
    module = _load_module()
    state_root = tmp_path / "targets" / "demo"
    product = tmp_path / "product"
    product.mkdir()
    (product / "package.json").write_text(
        module.json.dumps({"scripts": {"validate": "node scripts/validate.mjs"}}),
        encoding="utf-8",
    )
    request = module.create_draft(state_root=state_root, target_id="demo", packet_id="task-forwarded-args")
    request.write_text(
        _safe_request().replace("`git diff -- README.md`", "`npm run validate -- --deploy`"),
        encoding="utf-8",
    )

    review = module.review_packet(state_root=state_root, packet_id="task-forwarded-args", target_repo=product)

    assert review.auto_eligible is False
    assert "arguments" in " ".join(review.risk_flags)

    npm_test = module.create_draft(state_root=state_root, target_id="demo", packet_id="task-forwarded-npm-test")
    npm_test.write_text(
        _safe_request().replace("`git diff -- README.md`", "`npm test -- --deploy`"),
        encoding="utf-8",
    )
    npm_test_review = module.review_packet(state_root=state_root, packet_id="task-forwarded-npm-test", target_repo=product)
    assert npm_test_review.auto_eligible is False
    assert "arguments" in " ".join(npm_test_review.risk_flags)

    yarn_test = module.create_draft(state_root=state_root, target_id="demo", packet_id="task-forwarded-yarn-test")
    yarn_test.write_text(
        _safe_request().replace("`git diff -- README.md`", "`yarn test --deploy`"),
        encoding="utf-8",
    )
    yarn_test_review = module.review_packet(state_root=state_root, packet_id="task-forwarded-yarn-test", target_repo=product)
    assert yarn_test_review.auto_eligible is False
    assert "arguments" in " ".join(yarn_test_review.risk_flags)


def test_task_review_allows_exact_env_example_scope_but_rejects_runtime_env(tmp_path: Path) -> None:
    module = _load_module()
    state_root = tmp_path / "targets" / "demo"
    env_example = module.create_draft(state_root=state_root, target_id="demo", packet_id="task-env-example")
    env_example.write_text(_safe_request().replace("## File Scope\n- README.md", "## File Scope\n- .env.example"), encoding="utf-8")

    review = module.review_packet(state_root=state_root, packet_id="task-env-example")

    assert review.auto_eligible is True
    queued = module.queue_packet(state_root=state_root, packet_id="task-env-example", auto=True)
    body = queued.backlog_path.read_text(encoding="utf-8")
    assert "- .env.example" in body
    assert "- .env*" not in body

    env_runtime = module.create_draft(state_root=state_root, target_id="demo", packet_id="task-env-runtime")
    env_runtime.write_text(_safe_request().replace("## File Scope\n- README.md", "## File Scope\n- .env.local"), encoding="utf-8")
    runtime_review = module.review_packet(state_root=state_root, packet_id="task-env-runtime")
    assert runtime_review.auto_eligible is False
    assert "금지 범위" in " ".join(runtime_review.risk_flags)

    env_test = module.create_draft(state_root=state_root, target_id="demo", packet_id="task-env-test")
    env_test.write_text(_safe_request().replace("## File Scope\n- README.md", "## File Scope\n- .env.test"), encoding="utf-8")
    test_review = module.review_packet(state_root=state_root, packet_id="task-env-test")
    assert test_review.auto_eligible is False
    assert "금지 범위" in " ".join(test_review.risk_flags)


@pytest.mark.parametrize(
    ("scripts", "validation"),
    [
        ({"build": "npm run prod", "prod": "vercel deploy --prod"}, "`npm run build`"),
        ({"test": "npm run release", "release": "prisma migrate deploy"}, "`npm test`"),
        ({"lint": "yarn ship", "ship": "terraform apply -auto-approve"}, "`npm run lint`"),
    ],
)
def test_task_review_rejects_package_script_delegation(tmp_path: Path, scripts: dict[str, str], validation: str) -> None:
    module = _load_module()
    state_root = tmp_path / "targets" / "demo"
    product = tmp_path / "product"
    product.mkdir()
    (product / "package.json").write_text(module.json.dumps({"scripts": scripts}), encoding="utf-8")
    request = module.create_draft(state_root=state_root, target_id="demo", packet_id="task-package-delegation")
    request.write_text(_safe_request().replace("`git diff -- README.md`", validation), encoding="utf-8")

    review = module.review_packet(state_root=state_root, packet_id="task-package-delegation", target_repo=product)

    assert review.auto_eligible is False
    assert "delegates" in " ".join(review.risk_flags)


def test_task_review_rejects_package_script_when_body_unavailable(tmp_path: Path) -> None:
    module = _load_module()
    state_root = tmp_path / "targets" / "demo"
    request = module.create_draft(state_root=state_root, target_id="demo", packet_id="task-package-unknown")
    request.write_text(_safe_request().replace("`git diff -- README.md`", "`npm run build`"), encoding="utf-8")

    review = module.review_packet(state_root=state_root, packet_id="task-package-unknown")

    assert review.auto_eligible is False
    assert "package script" in " ".join(review.risk_flags)


def test_task_review_ai_response_rejects_symlink(tmp_path: Path) -> None:
    module = _load_module()
    state_root = tmp_path / "targets" / "demo"
    request = module.create_draft(state_root=state_root, target_id="demo", packet_id="task-ai-symlink")
    request.write_text("# Task\n\nUpdate README.md\n", encoding="utf-8")
    real_response = tmp_path / "normalizer.json"
    real_response.write_text("{}", encoding="utf-8")
    symlink = tmp_path / "normalizer-link.json"
    symlink.symlink_to(real_response)

    with pytest.raises(module.TaskIntakeError, match="symlink"):
        module.review_packet(state_root=state_root, packet_id="task-ai-symlink", ai_response=symlink)


def test_task_review_normalize_off_rejects_ai_response(tmp_path: Path) -> None:
    module = _load_module()
    state_root = tmp_path / "targets" / "demo"
    request = module.create_draft(state_root=state_root, target_id="demo", packet_id="task-ai-off")
    request.write_text(_safe_request(), encoding="utf-8")
    response = tmp_path / "normalizer-response.json"
    response.write_text(module.json.dumps({"goal": ["x"], "summary": ["x"]}), encoding="utf-8")

    with pytest.raises(module.TaskIntakeError, match="requires normalize mode"):
        module.review_packet(state_root=state_root, packet_id="task-ai-off", normalize="off", ai_response=response)


def test_task_review_ai_response_schema_fails_closed(tmp_path: Path) -> None:
    module = _load_module()
    state_root = tmp_path / "targets" / "demo"
    request = module.create_draft(state_root=state_root, target_id="demo", packet_id="task-ai-schema")
    request.write_text("# Task\n\nUpdate README.md\n", encoding="utf-8")
    missing = tmp_path / "missing.json"
    missing.write_text(module.json.dumps({"goal": ["x"]}), encoding="utf-8")
    unsupported = tmp_path / "unsupported.json"
    unsupported.write_text(
        module.json.dumps(
            {
                "goal": ["x"],
                "summary": ["x"],
                "acceptance": ["x"],
                "file_scope": ["README.md"],
                "validation": ["`git diff -- README.md`"],
                "extra": ["nope"],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(module.TaskIntakeError, match="missing required fields"):
        module.review_packet(state_root=state_root, packet_id="task-ai-schema", ai_response=missing)
    with pytest.raises(module.TaskIntakeError, match="unsupported fields"):
        module.review_packet(state_root=state_root, packet_id="task-ai-schema", ai_response=unsupported)


def test_task_review_ai_response_rejects_secret_payload(tmp_path: Path) -> None:
    module = _load_module()
    state_root = tmp_path / "targets" / "demo"
    request = module.create_draft(state_root=state_root, target_id="demo", packet_id="task-ai-secret")
    request.write_text("# Task\n\nUpdate README.md\n", encoding="utf-8")
    response = tmp_path / "secret.json"
    response.write_text(
        module.json.dumps(
            {
                "goal": ["x"],
                "summary": ["x"],
                "acceptance": ['{"api_key": "abcdef12345678901234567890"}'],
                "file_scope": ["README.md"],
                "validation": ["`git diff -- README.md`"],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(module.TaskIntakeError, match="secret-like"):
        module.review_packet(state_root=state_root, packet_id="task-ai-secret", ai_response=response)


def test_task_review_ai_response_dangerous_validation_is_manual_review(tmp_path: Path) -> None:
    module = _load_module()
    state_root = tmp_path / "targets" / "demo"
    request = module.create_draft(state_root=state_root, target_id="demo", packet_id="task-ai-danger")
    request.write_text("# Task\n\nUpdate README.md\n", encoding="utf-8")
    response = tmp_path / "danger.json"
    response.write_text(
        module.json.dumps(
            {
                "goal": ["x"],
                "summary": ["x"],
                "acceptance": ["README.md changes are present."],
                "file_scope": ["README.md"],
                "validation": ["`git clean -fd`"],
            }
        ),
        encoding="utf-8",
    )

    review = module.review_packet(state_root=state_root, packet_id="task-ai-danger", ai_response=response)

    assert review.auto_eligible is False
    assert review.risk_flags


def test_task_queue_preserves_authoritative_normalized_contract(tmp_path: Path) -> None:
    module = _load_module()
    state_root = tmp_path / "targets" / "demo"
    request = module.create_draft(
        state_root=state_root,
        target_id="demo",
        title="Vague request",
        packet_id="task-ai-normalized",
    )
    request.write_text("# Vague request\n\nMake the operator README clearer.\n", encoding="utf-8")
    response = tmp_path / "normalizer-response.json"
    response.write_text(
        module.json.dumps(
            {
                "goal": ["Clarify the operator README."],
                "summary": ["Update README.md with clearer operator wording."],
                "acceptance": ["README.md includes the clarified operator wording."],
                "file_scope": ["README.md"],
                "validation": ["`git diff -- README.md`"],
            }
        ),
        encoding="utf-8",
    )

    review = module.review_packet(state_root=state_root, packet_id="task-ai-normalized", ai_response=response)
    queued = module.queue_packet(state_root=state_root, packet_id="task-ai-normalized", auto=True)
    body = queued.backlog_path.read_text(encoding="utf-8")

    assert review.auto_eligible is True
    assert review.normalization_used_ai is True
    assert "README.md includes the clarified operator wording." in body
    assert "Autonomy-Execute: auto" in body


def test_task_queue_requires_stored_normalized_contract(tmp_path: Path) -> None:
    module = _load_module()
    state_root = tmp_path / "targets" / "demo"
    request = module.create_draft(state_root=state_root, target_id="demo", packet_id="task-legacy-review")
    request.write_text(_safe_request(), encoding="utf-8")
    review = module.review_packet(state_root=state_root, packet_id="task-legacy-review")
    payload = module.json.loads(review.review_path.read_text(encoding="utf-8"))
    payload.pop("normalized_contract_path", None)
    review.review_path.write_text(module.json.dumps(payload), encoding="utf-8")

    with pytest.raises(module.TaskIntakeError, match="missing normalized contract"):
        module.queue_packet(state_root=state_root, packet_id="task-legacy-review", auto=True)


def test_task_intake_normalizes_safe_config_aliases_for_auto_queue(tmp_path: Path) -> None:
    module = _load_module()
    state_root = tmp_path / "targets" / "demo"
    request = module.create_draft(state_root=state_root, target_id="demo", packet_id="task-config")
    request.write_text(
        _safe_request()
        .replace(
            "## File Scope\n- README.md",
            "\n".join(
                [
                    "## File Scope",
                    "- README.md",
                    "- `vite.config.*`",
                    "- `eslint.config.*`",
                    "- `vitest.config.*`",
                    "- `playwright.config.*`",
                    "- `tailwind.config.*`",
                    "- `postcss.config.*`",
                ]
            ),
        )
        .replace("## Forbidden Scope\n- .env*", "## Forbidden Scope\n- `.env*`"),
        encoding="utf-8",
    )

    review = module.review_packet(state_root=state_root, packet_id="task-config")
    preview = review.preview_path.read_text(encoding="utf-8")

    assert review.auto_eligible is True
    assert {item.original for item in review.scope_adjustments} == {
        "vite.config.*",
        "eslint.config.*",
        "vitest.config.*",
        "playwright.config.*",
        "tailwind.config.*",
        "postcss.config.*",
        ".env*",
    }
    assert "vite.config.*" not in preview
    assert "eslint.config.*" not in preview
    assert "- vite.config.ts" in preview
    assert "- eslint.config.mjs" in preview
    assert "- vitest.config.cts" in preview
    assert "- playwright.config.ts" in preview
    assert "- tailwind.config.mts" in preview
    assert "- postcss.config.cjs" in preview
    assert "- .env.local" in preview
    payload = module.json.loads(review.review_path.read_text(encoding="utf-8"))
    assert len(payload["scope_adjustments"]) == 7

    queued = module.queue_packet(state_root=state_root, packet_id="task-config", auto=True)
    body = queued.backlog_path.read_text(encoding="utf-8")

    assert queued.autonomy_execute == "auto"
    assert "Autonomy-Execute: auto" in body
    assert "vite.config.*" not in body
    assert "- vite.config.cts" in body


def test_task_intake_keeps_unsafe_wildcards_manual_review(tmp_path: Path) -> None:
    module = _load_module()
    state_root = tmp_path / "targets" / "demo"
    request = module.create_draft(state_root=state_root, target_id="demo", packet_id="task-unsafe-glob")
    request.write_text(
        _safe_request().replace("## File Scope\n- README.md", "## File Scope\n- README.md\n- `src/*.ts`"),
        encoding="utf-8",
    )

    review = module.review_packet(state_root=state_root, packet_id="task-unsafe-glob")

    assert review.auto_eligible is False
    assert "안전하지 않은 wildcard" in " ".join(review.risk_flags)
    assert "Autonomy-Execute: manual-review" in review.preview_path.read_text(encoding="utf-8")
    with pytest.raises(module.TaskIntakeError, match="auto queue 불가"):
        module.queue_packet(state_root=state_root, packet_id="task-unsafe-glob", auto=True)

    queued = module.queue_packet(state_root=state_root, packet_id="task-unsafe-glob")
    assert queued.autonomy_execute == "manual-review"


@pytest.mark.parametrize(
    "unsafe_scope",
    [".env*", ".env.test", "HARNESS.md", "docs/harness/**", "scripts/harness_cli.py", "server.PEM", "id_rsa"],
)
def test_task_intake_rejects_secret_and_harness_file_scope(tmp_path: Path, unsafe_scope: str) -> None:
    module = _load_module()
    state_root = tmp_path / "targets" / "demo"
    request = module.create_draft(state_root=state_root, target_id="demo", packet_id="task-pollution")
    request.write_text(
        _safe_request().replace("## File Scope\n- README.md", f"## File Scope\n- {unsafe_scope}"),
        encoding="utf-8",
    )

    review = module.review_packet(state_root=state_root, packet_id="task-pollution")

    assert review.auto_eligible is False
    assert review.risk_flags
    with pytest.raises(module.TaskIntakeError, match="auto queue 불가"):
        module.queue_packet(state_root=state_root, packet_id="task-pollution", auto=True)


def test_task_intake_rejects_mixed_valid_and_unreadable_file_scope(tmp_path: Path) -> None:
    module = _load_module()
    state_root = tmp_path / "targets" / "demo"
    request = module.create_draft(state_root=state_root, target_id="demo", packet_id="task-mixed-scope")
    request.write_text(
        _safe_request().replace("## File Scope\n- README.md", "## File Scope\n- README.md\n- README and docs"),
        encoding="utf-8",
    )

    review = module.review_packet(state_root=state_root, packet_id="task-mixed-scope")

    assert review.auto_eligible is False
    assert "README and docs" in " ".join(review.open_questions)
    with pytest.raises(module.TaskIntakeError, match="auto queue 불가"):
        module.queue_packet(state_root=state_root, packet_id="task-mixed-scope", auto=True)


def test_task_fix_scope_promotes_linked_manual_review_backlog(tmp_path: Path) -> None:
    module = _load_module()
    state_root = tmp_path / "targets" / "demo"
    request = module.create_draft(state_root=state_root, target_id="demo", packet_id="task-fix")
    request.write_text(
        _safe_request().replace("## File Scope\n- README.md", "## File Scope\n- README.md\n- `vite.config.*`"),
        encoding="utf-8",
    )
    module.review_packet(state_root=state_root, packet_id="task-fix")
    queued = module.queue_packet(state_root=state_root, packet_id="task-fix")
    before_body = queued.backlog_path.read_text(encoding="utf-8")

    dry_run = module.fix_scope_packet(state_root=state_root, packet_id="task-fix")

    assert dry_run.applied is False
    assert dry_run.auto_eligible is True
    assert queued.backlog_path.read_text(encoding="utf-8") == before_body

    applied = module.fix_scope_packet(state_root=state_root, packet_id="task-fix", apply=True)
    body = queued.backlog_path.read_text(encoding="utf-8")

    assert applied.applied is True
    assert applied.backlog_path == queued.backlog_path
    assert "Autonomy-Execute: auto" in body
    assert "vite.config.*" not in body
    discovered = module.harness_loop.discover_backlog_items(state_root)
    assert [(item.item_id, item.autonomy_execute) for item in discovered] == [(queued.backlog_id, "auto")]


def test_task_fix_scope_refuses_existing_nested_implementation_evidence(tmp_path: Path) -> None:
    module = _load_module()
    state_root = tmp_path / "targets" / "demo"
    request = module.create_draft(state_root=state_root, target_id="demo", packet_id="task-evidence")
    request.write_text(
        _safe_request().replace("## File Scope\n- README.md", "## File Scope\n- README.md\n- `vite.config.*`"),
        encoding="utf-8",
    )
    module.review_packet(state_root=state_root, packet_id="task-evidence")
    queued = module.queue_packet(state_root=state_root, packet_id="task-evidence")
    evidence = state_root / "runs" / "harness" / "external-demo" / "generated-evidence.json"
    evidence.parent.mkdir(parents=True)
    evidence.write_text(
        module.json.dumps(
            {
                "external_backlog": {
                    "id": queued.backlog_id,
                    "path": queued.backlog_path.relative_to(state_root.resolve()).as_posix(),
                }
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(module.TaskIntakeError, match="existing implementation evidence"):
        module.fix_scope_packet(state_root=state_root, packet_id="task-evidence", apply=True)


def test_task_fix_scope_requires_exact_task_intake_linkage(tmp_path: Path) -> None:
    module = _load_module()
    state_root = tmp_path / "targets" / "demo"
    request = module.create_draft(state_root=state_root, target_id="demo", packet_id="task-linkage")
    request.write_text(
        _safe_request().replace("## File Scope\n- README.md", "## File Scope\n- README.md\n- `vite.config.*`"),
        encoding="utf-8",
    )
    module.review_packet(state_root=state_root, packet_id="task-linkage")
    queued = module.queue_packet(state_root=state_root, packet_id="task-linkage")
    body = queued.backlog_path.read_text(encoding="utf-8").replace("Intake-Packet: task-linkage\n", "")
    queued.backlog_path.write_text(body, encoding="utf-8")

    with pytest.raises(module.TaskIntakeError, match="intake packet mismatch"):
        module.fix_scope_packet(state_root=state_root, packet_id="task-linkage", apply=True)


def test_task_fix_scope_rolls_back_when_canonical_discovery_fails(monkeypatch, tmp_path: Path) -> None:
    module = _load_module()
    state_root = tmp_path / "targets" / "demo"
    request = module.create_draft(state_root=state_root, target_id="demo", packet_id="task-rollback")
    request.write_text(
        _safe_request().replace("## File Scope\n- README.md", "## File Scope\n- README.md\n- `vite.config.*`"),
        encoding="utf-8",
    )
    module.review_packet(state_root=state_root, packet_id="task-rollback")
    queued = module.queue_packet(state_root=state_root, packet_id="task-rollback")
    before = queued.backlog_path.read_text(encoding="utf-8")

    real_discover = module._discover_backlog_items_strict
    calls = {"count": 0}

    def fake_discover(discover_root: Path):
        calls["count"] += 1
        if calls["count"] == 1:
            return real_discover(discover_root)
        return ()

    monkeypatch.setattr(module, "_discover_backlog_items_strict", fake_discover)

    with pytest.raises(module.TaskIntakeError, match="fixed backlog is not visible"):
        module.fix_scope_packet(state_root=state_root, packet_id="task-rollback", apply=True)
    assert queued.backlog_path.read_text(encoding="utf-8") == before


def _file_snapshot(root: Path) -> dict[str, bytes]:
    if not root.exists():
        return {}
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file() and not path.is_symlink()
    }


def test_task_intake_summarize_packets_reports_states_and_stale_review(tmp_path: Path) -> None:
    module = _load_module()
    state_root = tmp_path / "targets" / "demo"

    request = module.create_draft(state_root=state_root, target_id="demo", packet_id="task-demo")
    request.write_text(_safe_request(), encoding="utf-8")

    summaries = module.summarize_packets(state_root, target_id="demo")
    assert len(summaries) == 1
    assert summaries[0].packet_id == "task-demo"
    assert summaries[0].review_status == "not-reviewed"
    assert summaries[0].auto_eligible is None
    assert summaries[0].queued_backlog_path is None

    module.review_packet(state_root=state_root, packet_id="task-demo")
    summaries = module.summarize_packets(state_root, target_id="demo")
    assert summaries[0].review_status == "reviewed"
    assert summaries[0].auto_eligible is True
    assert summaries[0].open_question_count == 0
    assert summaries[0].risk_flag_count == 0

    request.write_text(_safe_request() + "\n## Notes\n\n- Update added after review.\n", encoding="utf-8")
    summaries = module.summarize_packets(state_root, target_id="demo")
    assert summaries[0].review_status == "stale"
    assert summaries[0].auto_eligible is None

    module.review_packet(state_root=state_root, packet_id="task-demo")
    queued = module.queue_packet(state_root=state_root, packet_id="task-demo", auto=True)
    summaries = module.summarize_packets(state_root, target_id="demo")
    assert summaries[0].review_status == "reviewed"
    assert summaries[0].queued_backlog_path == queued.backlog_path
    assert summaries[0].autonomy_execute == "auto"


def test_task_intake_summarize_packets_is_read_only(tmp_path: Path) -> None:
    module = _load_module()
    state_root = tmp_path / "targets" / "demo"
    request = module.create_draft(state_root=state_root, target_id="demo", packet_id="task-demo")
    request.write_text(_safe_request(), encoding="utf-8")
    module.review_packet(state_root=state_root, packet_id="task-demo")
    before = _file_snapshot(state_root)

    summaries = module.summarize_packets(state_root, target_id="demo")

    assert summaries[0].packet_id == "task-demo"
    assert _file_snapshot(state_root) == before
    assert not (state_root / "backlog" / "queued").exists()


@pytest.mark.parametrize("state", ["active", "blocked", "completed"])
def test_task_intake_summarize_does_not_treat_non_queued_backlog_as_runnable(
    tmp_path: Path,
    state: str,
) -> None:
    module = _load_module()
    state_root = tmp_path / "targets" / "demo"
    request = module.create_draft(state_root=state_root, target_id="demo", packet_id="task-demo")
    request.write_text(_safe_request(), encoding="utf-8")
    module.review_packet(state_root=state_root, packet_id="task-demo")
    queued = module.queue_packet(state_root=state_root, packet_id="task-demo", auto=True)
    destination = state_root / "backlog" / state / queued.backlog_path.name
    destination.parent.mkdir(parents=True, exist_ok=True)
    body = queued.backlog_path.read_text(encoding="utf-8").replace("Status: queued", f"Status: {state}", 1)
    destination.write_text(body, encoding="utf-8")
    queued.backlog_path.unlink()

    summary = module.summarize_packets(state_root, target_id="demo")[0]

    assert summary.queued_backlog_path is None
    assert summary.backlog_path == destination
    assert summary.backlog_status == state
    assert summary.autonomy_execute == "auto"


def test_task_intake_summarize_redacts_secret_like_request_title(tmp_path: Path) -> None:
    module = _load_module()
    state_root = tmp_path / "targets" / "demo"
    request = module.create_draft(state_root=state_root, target_id="demo", packet_id="task-secret")
    request.write_text("# Safe heading\n\n## Summary\n\n- API_KEY=abcdef12345678901234567890\n", encoding="utf-8")

    summary = module.summarize_packets(state_root, target_id="demo")[0]

    assert summary.title == "비밀값 확인 필요"
    assert summary.request_issue == "secret-like-request"
    assert summary.review_status == "not-reviewed"


def test_task_intake_summarize_rejects_unsafe_sidecar_state(tmp_path: Path) -> None:
    module = _load_module()
    state_root = tmp_path / "targets" / "demo"
    request = module.create_draft(state_root=state_root, target_id="demo", packet_id="task-demo")
    request.write_text(_safe_request(), encoding="utf-8")
    packet_path = state_root / "backlog" / "drafts" / "task-demo" / "task-packet.json"
    packet = module.load_packet(state_root, "task-demo")
    packet["queued_backlog_path"] = "../escape.md"
    packet_path.write_text(module.json.dumps(packet, ensure_ascii=False, indent=2), encoding="utf-8")

    with pytest.raises(module.TaskIntakeError, match="unsafe"):
        module.summarize_packets(state_root, target_id="demo")

    packet_path.write_text(module.json.dumps({**packet, "queued_backlog_path": ""}), encoding="utf-8")
    link_root = state_root / "backlog" / "drafts" / "task-link"
    outside = tmp_path / "outside-packet"
    outside.mkdir()
    (outside / "task-packet.json").write_text("{}", encoding="utf-8")
    link_root.symlink_to(outside)

    with pytest.raises(module.TaskIntakeError, match="symlink"):
        module.summarize_packets(state_root, target_id="demo")


def test_task_intake_rejects_secret_files_and_symlinks(tmp_path: Path) -> None:
    module = _load_module()
    state_root = tmp_path / "targets" / "demo"
    secret = tmp_path / ".env"
    secret.write_text("TOKEN=secret\n", encoding="utf-8")

    with pytest.raises(module.TaskIntakeError, match="secret"):
        module.create_from_file(state_root=state_root, target_id="demo", source=secret)

    source = tmp_path / "request.md"
    source.write_text(_safe_request(), encoding="utf-8")
    link = tmp_path / "request-link.md"
    link.symlink_to(source)
    with pytest.raises(module.TaskIntakeError, match="symlink"):
        module.create_from_file(state_root=state_root, target_id="demo", source=link)


def test_task_intake_rejects_sidecar_symlink_files(tmp_path: Path) -> None:
    module = _load_module()
    state_root = tmp_path / "targets" / "demo"
    request = module.create_draft(state_root=state_root, target_id="demo", packet_id="task-demo")
    request.unlink()
    outside = tmp_path / "outside.md"
    outside.write_text(_safe_request(), encoding="utf-8")
    request.symlink_to(outside)

    with pytest.raises(module.TaskIntakeError, match="symlink"):
        module.review_packet(state_root=state_root, packet_id="task-demo")

    (tmp_path / "task-packet.json").write_text("{}", encoding="utf-8")
    packet_link_root = state_root / "backlog" / "drafts" / "task-link"
    packet_link_root.symlink_to(tmp_path)
    with pytest.raises(module.TaskIntakeError, match="symlink"):
        module.latest_packet_id(state_root)


def test_task_intake_rejects_secret_like_request_content(tmp_path: Path) -> None:
    module = _load_module()
    state_root = tmp_path / "targets" / "demo"
    request = tmp_path / "request.md"
    request.write_text("# Task\n\n## Summary\n\n- API_KEY=sk_test_12345678901234567890\n", encoding="utf-8")

    with pytest.raises(module.TaskIntakeError, match="secret-like"):
        module.create_from_file(state_root=state_root, target_id="demo", source=request)
    drafts_root = state_root / "backlog" / "drafts"
    assert not drafts_root.exists() or not tuple(drafts_root.iterdir())

    draft = module.create_draft(state_root=state_root, target_id="demo", packet_id="task-secret")
    draft.write_text("# Task\n\n## Summary\n\n- bearer abcdefghijklmnopqrstuvwxyz123456\n", encoding="utf-8")
    with pytest.raises(module.TaskIntakeError, match="secret-like"):
        module.review_packet(state_root=state_root, packet_id="task-secret")


def test_task_intake_records_image_metadata_without_base64(tmp_path: Path) -> None:
    module = _load_module()
    state_root = tmp_path / "targets" / "demo"
    request = tmp_path / "request.md"
    request.write_text("# Visual task\n\n## Summary\n\n- Use the attached mock.\n", encoding="utf-8")
    image = tmp_path / "mock.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\nfake")

    created = module.create_from_file(
        state_root=state_root,
        target_id="demo",
        source=request,
        images=(image,),
        image_captions=("Reference mock",),
        packet_id="task-visual",
    )
    review = module.review_packet(state_root=state_root, packet_id="task-visual")
    packet = module.load_packet(state_root, "task-visual")

    assert created.read_text(encoding="utf-8").startswith("# Visual task")
    assert review.auto_eligible is False
    assert "완료 조건이 없습니다." in review.open_questions
    assert packet["attachments"][0]["media_type"] == "image/png"
    assert packet["attachments"][0]["caption"] == "Reference mock"
    assert packet["attachments"][0]["path"] == "backlog/drafts/task-visual/attachments/mock.png"
    assert (state_root / packet["attachments"][0]["path"]).exists()
    assert "caption: Reference mock" in review.preview_path.read_text(encoding="utf-8")
    assert "base64" not in (state_root / "backlog" / "drafts" / "task-visual" / "task-packet.json").read_text(
        encoding="utf-8"
    )

    queued = module.queue_packet(state_root=state_root, packet_id="task-visual")
    assert queued.autonomy_execute == "manual-review"
    assert "Autonomy-Execute: manual-review" in queued.backlog_path.read_text(encoding="utf-8")


def test_task_interview_records_captioned_image_metadata(tmp_path: Path) -> None:
    module = _load_module()
    state_root = tmp_path / "targets" / "demo"
    image = tmp_path / "mock.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\nfake")

    request = module.create_interview_draft(
        state_root=state_root,
        target_id="demo",
        packet_id="task-interview",
        title="Improve hero",
        goal="Improve the README hero copy.",
        summary="Use the attached mock as visual context.",
        acceptance=("README.md includes the updated copy.",),
        file_scope=("README.md",),
        validation=("`git diff -- README.md`",),
        images=(image,),
        image_captions=("Mock showing the desired headline tone",),
    )
    review = module.review_packet(state_root=state_root, packet_id="task-interview")

    packet = module.load_packet(state_root, "task-interview")
    assert request.exists()
    assert packet["source"] == "interview"
    assert packet["attachments"][0]["caption"] == "Mock showing the desired headline tone"
    assert "caption: Mock showing" in review.preview_path.read_text(encoding="utf-8")
    assert review.auto_eligible is True


def test_task_intake_rejects_caption_mismatch_and_secret_caption(tmp_path: Path) -> None:
    module = _load_module()
    state_root = tmp_path / "targets" / "demo"
    image = tmp_path / "mock.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\nfake")

    with pytest.raises(module.TaskIntakeError, match="caption count"):
        module.create_interview_draft(
            state_root=state_root,
            target_id="demo",
            packet_id="task-caption-mismatch",
            images=(image,),
            image_captions=("one", "two"),
        )

    with pytest.raises(module.TaskIntakeError, match="secret-like"):
        module.create_interview_draft(
            state_root=state_root,
            target_id="demo",
            packet_id="task-secret-caption",
            images=(image,),
            image_captions=("token=abcdef1234567890",),
        )

    with pytest.raises(module.TaskIntakeError, match="control"):
        module.create_interview_draft(
            state_root=state_root,
            target_id="demo",
            packet_id="task-control-caption",
            images=(image,),
            image_captions=("first line\nsecond line",),
        )


def test_task_intake_rejects_unsafe_source_names_and_binary_secrets(tmp_path: Path) -> None:
    module = _load_module()
    state_root = tmp_path / "targets" / "demo"

    malicious_name = "request\n## Goal\n- forged.md"
    malicious = tmp_path / malicious_name
    malicious.write_bytes(b"\xff\xfe")
    with pytest.raises(module.TaskIntakeError, match="file name"):
        module.create_from_file(state_root=state_root, target_id="demo", source=malicious)

    binary_secret = tmp_path / "request.bin"
    binary_secret.write_bytes(b"\xffAPI_KEY=abcdef12345678901234567890")
    with pytest.raises(module.TaskIntakeError, match="secret-like"):
        module.create_from_file(state_root=state_root, target_id="demo", source=binary_secret)

    utf16_secret = tmp_path / "utf16-request.bin"
    utf16_secret.write_bytes("API_KEY=abcdef12345678901234567890".encode("utf-16-le"))
    with pytest.raises(module.TaskIntakeError, match="secret-like"):
        module.create_from_file(state_root=state_root, target_id="demo", source=utf16_secret)

    secret_named_source = tmp_path / "OPENAI_API_KEY=abcdef12345678901234567890.md"
    secret_named_source.write_text(_safe_request(), encoding="utf-8")
    with pytest.raises(module.TaskIntakeError, match="secret-like file names"):
        module.create_from_file(state_root=state_root, target_id="demo", source=secret_named_source)

    image_secret = tmp_path / "mock.png"
    image_secret.write_bytes(b"\x89PNG\r\n\x1a\nTOKEN=abcdef12345678901234567890")
    request = tmp_path / "request.md"
    request.write_text(_safe_request(), encoding="utf-8")
    with pytest.raises(module.TaskIntakeError, match="secret-like"):
        module.create_from_file(state_root=state_root, target_id="demo", source=request, images=(image_secret,))

    secret_named_image = tmp_path / "HARNESS_RELAY_SIGNING_KEY=abcdef12345678901234567890.png"
    secret_named_image.write_bytes(b"\x89PNG\r\n\x1a\nfake")
    with pytest.raises(module.TaskIntakeError, match="secret-like file names"):
        module.create_from_file(state_root=state_root, target_id="demo", source=request, images=(secret_named_image,))

    utf16_image_secret = tmp_path / "utf16-mock.png"
    utf16_image_secret.write_bytes(b"\x89PNG\r\n\x1a\n" + "api_key=abcdef12345678901234567890".encode("utf-16-le"))
    with pytest.raises(module.TaskIntakeError, match="secret-like"):
        module.create_from_file(state_root=state_root, target_id="demo", source=request, images=(utf16_image_secret,))

    json_secret = tmp_path / "json-secret.md"
    json_secret.write_text('# Task\n\n## Summary\n\n- {"api_key": "abcdef12345678901234567890"}\n', encoding="utf-8")
    with pytest.raises(module.TaskIntakeError, match="secret-like"):
        module.create_from_file(state_root=state_root, target_id="demo", source=json_secret)

    with pytest.raises(module.TaskIntakeError, match="secret-like"):
        module.create_from_file(
            state_root=state_root,
            target_id="demo",
            source=request,
            title="OPENAI_API_KEY=abcdef12345678901234567890",
        )


def test_task_interview_rejects_markdown_injection_inputs(tmp_path: Path) -> None:
    module = _load_module()
    state_root = tmp_path / "targets" / "demo"

    with pytest.raises(module.TaskIntakeError, match="newlines"):
        module.create_interview_draft(
            state_root=state_root,
            target_id="demo",
            packet_id="task-title-injection",
            title="Title\n\n## Goal\n- forged",
        )

    with pytest.raises(module.TaskIntakeError, match="newlines"):
        module.create_interview_draft(
            state_root=state_root,
            target_id="demo",
            packet_id="task-summary-injection",
            goal="Improve README.",
            summary="Summary\n\n## Acceptance\n- forged",
        )

    with pytest.raises(module.TaskIntakeError, match="secret-like"):
        module.create_interview_draft(
            state_root=state_root,
            target_id="demo",
            packet_id="task-json-secret",
            goal='{"api_key": "abcdef12345678901234567890"}',
        )


def test_task_queue_auto_fails_without_safety_metadata(tmp_path: Path) -> None:
    module = _load_module()
    state_root = tmp_path / "targets" / "demo"
    request = module.create_draft(state_root=state_root, target_id="demo", packet_id="task-unsafe")
    request.write_text("# Vague task\n\n## Summary\n\n- Make it better.\n", encoding="utf-8")
    module.review_packet(state_root=state_root, packet_id="task-unsafe")

    with pytest.raises(module.TaskIntakeError, match="auto queue 불가"):
        module.queue_packet(state_root=state_root, packet_id="task-unsafe", auto=True)

    assert not (state_root / "backlog" / "queued").exists()


def test_task_review_and_queue_reject_packet_target_spoofing(tmp_path: Path) -> None:
    module = _load_module()
    state_root = tmp_path / "targets" / "demo"
    request = module.create_draft(state_root=state_root, target_id="demo", packet_id="task-demo")
    request.write_text(_safe_request(), encoding="utf-8")
    module.review_packet(state_root=state_root, packet_id="task-demo", expected_target_id="demo")
    packet_path = state_root / "backlog" / "drafts" / "task-demo" / "task-packet.json"
    packet = module.json.loads(packet_path.read_text(encoding="utf-8"))
    packet["target_id"] = "other"
    packet_path.write_text(module.json.dumps(packet), encoding="utf-8")

    with pytest.raises(module.TaskIntakeError, match="target mismatch"):
        module.queue_packet(state_root=state_root, packet_id="task-demo", auto=True, expected_target_id="demo")

    assert not (state_root / "backlog" / "queued").exists()


def test_task_queue_removes_backlog_when_parser_proof_fails(monkeypatch, tmp_path: Path) -> None:
    module = _load_module()
    state_root = tmp_path / "targets" / "demo"
    request = module.create_draft(state_root=state_root, target_id="demo", packet_id="task-demo")
    request.write_text(_safe_request(), encoding="utf-8")
    module.review_packet(state_root=state_root, packet_id="task-demo")

    def fail_discovery(root: Path):
        raise module.harness_loop.LoopError("synthetic parser failure")

    monkeypatch.setattr(module.harness_loop, "discover_backlog_items", fail_discovery)
    with pytest.raises(module.harness_loop.LoopError, match="synthetic parser failure"):
        module.queue_packet(state_root=state_root, packet_id="task-demo", auto=True)

    queued_dir = state_root / "backlog" / "queued"
    assert not queued_dir.exists() or not tuple(queued_dir.glob("*.md"))


def test_task_auto_requires_backtick_validation_command(tmp_path: Path) -> None:
    module = _load_module()
    state_root = tmp_path / "targets" / "demo"
    request = module.create_draft(state_root=state_root, target_id="demo", packet_id="task-demo")
    request.write_text(_safe_request().replace("`git diff -- README.md`", "Run `git diff -- README.md`"), encoding="utf-8")

    review = module.review_packet(state_root=state_root, packet_id="task-demo")

    assert review.auto_eligible is False
    assert "검증 명령은 backtick" in " ".join(review.open_questions)

    blank = module.create_draft(state_root=state_root, target_id="demo", packet_id="task-blank-validation")
    blank.write_text(_safe_request().replace("`git diff -- README.md`", "` `"), encoding="utf-8")
    blank_review = module.review_packet(state_root=state_root, packet_id="task-blank-validation")
    assert blank_review.auto_eligible is False


def test_task_auto_requires_canonical_validation_command(tmp_path: Path) -> None:
    module = _load_module()
    state_root = tmp_path / "targets" / "demo"
    request = module.create_draft(state_root=state_root, target_id="demo", packet_id="task-manual-validation")
    request.write_text(
        _safe_request().replace("`git diff -- README.md`", "`Manual: inspect README.md`"),
        encoding="utf-8",
    )

    review = module.review_packet(state_root=state_root, packet_id="task-manual-validation")

    assert review.auto_eligible is False
    assert "canonical parser" in " ".join(review.open_questions)
    assert module.json.loads(review.review_path.read_text(encoding="utf-8"))["validation_commands"] == []


def test_task_auto_requires_machine_readable_file_scope(tmp_path: Path) -> None:
    module = _load_module()
    state_root = tmp_path / "targets" / "demo"
    request = module.create_draft(state_root=state_root, target_id="demo", packet_id="task-scope")
    request.write_text(_safe_request().replace("## File Scope\n- README.md", "## File Scope\n- README and docs"), encoding="utf-8")

    review = module.review_packet(state_root=state_root, packet_id="task-scope")

    assert review.auto_eligible is False
    assert "machine-readable scope" in " ".join(review.open_questions)


def test_task_auto_rejects_file_scope_overlapping_mandatory_forbidden_scope(tmp_path: Path) -> None:
    module = _load_module()
    state_root = tmp_path / "targets" / "demo"
    request = module.create_draft(state_root=state_root, target_id="demo", packet_id="task-forbidden-scope")
    request.write_text(_safe_request().replace("## File Scope\n- README.md", "## File Scope\n- runs/**"), encoding="utf-8")

    review = module.review_packet(state_root=state_root, packet_id="task-forbidden-scope")

    assert review.auto_eligible is False
    assert "금지 범위와 겹칩니다" in " ".join(review.risk_flags)
    with pytest.raises(module.TaskIntakeError, match="auto queue 불가"):
        module.queue_packet(state_root=state_root, packet_id="task-forbidden-scope", auto=True)


def test_task_queue_idempotency_checks_all_backlog_states(tmp_path: Path) -> None:
    module = _load_module()
    state_root = tmp_path / "targets" / "demo"
    request = module.create_draft(state_root=state_root, target_id="demo", packet_id="task-demo")
    request.write_text(_safe_request(), encoding="utf-8")
    module.review_packet(state_root=state_root, packet_id="task-demo")
    queued = module.queue_packet(state_root=state_root, packet_id="task-demo", auto=True)
    completed = state_root / "backlog" / "completed" / queued.backlog_path.name
    completed.parent.mkdir(parents=True, exist_ok=True)
    queued.backlog_path.rename(completed)
    packet_path = state_root / "backlog" / "drafts" / "task-demo" / "task-packet.json"
    packet = module.json.loads(packet_path.read_text(encoding="utf-8"))
    packet["queued_backlog_path"] = ""
    packet_path.write_text(module.json.dumps(packet), encoding="utf-8")

    with pytest.raises(module.TaskIntakeError, match="already queued"):
        module.queue_packet(state_root=state_root, packet_id="task-demo", auto=True)


def test_task_queue_idempotency_uses_exact_intake_packet_metadata(tmp_path: Path) -> None:
    module = _load_module()
    state_root = tmp_path / "targets" / "demo"
    completed_dir = state_root / "backlog" / "completed"
    completed_dir.mkdir(parents=True)
    completed_dir.joinpath("BL-existing.md").write_text(
        "\n".join(
            [
                "ID: BL-existing",
                "Status: completed",
                "Intake-Packet: task-demo-2",
                "",
                "## Summary",
                "- existing",
            ]
        ),
        encoding="utf-8",
    )
    request = module.create_draft(state_root=state_root, target_id="demo", packet_id="task-demo")
    request.write_text(_safe_request(), encoding="utf-8")
    module.review_packet(state_root=state_root, packet_id="task-demo")

    queued = module.queue_packet(state_root=state_root, packet_id="task-demo", auto=True)

    assert queued.backlog_path.exists()


def test_task_queue_parser_proof_handles_symlinked_state_root(tmp_path: Path) -> None:
    module = _load_module()
    real_root = tmp_path / "real-targets" / "demo"
    real_root.mkdir(parents=True)
    state_root = tmp_path / "linked-demo"
    state_root.symlink_to(real_root, target_is_directory=True)
    request = module.create_draft(state_root=state_root, target_id="demo", packet_id="task-demo")
    request.write_text(_safe_request(), encoding="utf-8")
    module.review_packet(state_root=state_root, packet_id="task-demo")

    queued = module.queue_packet(state_root=state_root, packet_id="task-demo", auto=True)
    packet = module.load_packet(state_root, "task-demo")

    assert queued.backlog_path.exists()
    assert packet["queued_backlog_path"].startswith("backlog/queued/")


def test_task_queue_always_merges_mandatory_forbidden_scope(tmp_path: Path) -> None:
    module = _load_module()
    state_root = tmp_path / "targets" / "demo"
    request = module.create_draft(state_root=state_root, target_id="demo", packet_id="task-demo")
    request.write_text(_safe_request().replace("- .env*\n- runs/**\n- reports/**\n- targets/**", "- build/**"), encoding="utf-8")
    module.review_packet(state_root=state_root, packet_id="task-demo")

    queued = module.queue_packet(state_root=state_root, packet_id="task-demo", auto=True)
    body = queued.backlog_path.read_text(encoding="utf-8")

    assert "- .env*" not in body
    assert "- .env" in body
    assert "- .env.local" in body
    assert "- .env.production" in body
    assert "- .env.development" in body
    assert "- .env.test" in body
    assert "- .envrc" in body
    assert "- runs/**" in body
    assert "- reports/**" in body
    assert "- targets/**" in body
    assert "- build/**" in body


def test_ai_review_writes_advisory_artifacts_without_changing_queue_gate(tmp_path: Path) -> None:
    module = _load_module()
    state_root = tmp_path / "targets" / "demo"
    request = module.create_draft(state_root=state_root, target_id="demo", packet_id="task-unsafe")
    request.write_text("# Vague task\n\n## Summary\n\n- Make it better.\n", encoding="utf-8")
    deterministic = module.review_packet(state_root=state_root, packet_id="task-unsafe")
    before_review = deterministic.review_path.read_text(encoding="utf-8")
    response = tmp_path / "ai-response.json"
    response.write_text(
        module.json.dumps(
            {
                "summary": "Looks ready.",
                "open_questions": [],
                "risk_notes": [],
                "suggested_acceptance": ["Everything is done."],
                "suggested_validation": ["`true`"],
            }
        ),
        encoding="utf-8",
    )

    ai_review = module.prepare_ai_review(state_root=state_root, packet_id="task-unsafe", response=response)

    assert ai_review.prompt_path.exists()
    assert ai_review.schema_path.exists()
    assert ai_review.result_path is not None and ai_review.result_path.exists()
    assert deterministic.review_path.read_text(encoding="utf-8") == before_review
    assert module.json.loads(deterministic.review_path.read_text(encoding="utf-8"))["auto_eligible"] is False
    with pytest.raises(module.TaskIntakeError, match="auto queue 불가"):
        module.queue_packet(state_root=state_root, packet_id="task-unsafe", auto=True)
    assert not (state_root / "backlog" / "queued").exists()


def test_ai_review_malformed_response_fails_closed_with_packet_local_error(tmp_path: Path) -> None:
    module = _load_module()
    state_root = tmp_path / "targets" / "demo"
    request = module.create_draft(state_root=state_root, target_id="demo", packet_id="task-demo")
    request.write_text(_safe_request(), encoding="utf-8")
    module.review_packet(state_root=state_root, packet_id="task-demo")
    bad_response = tmp_path / "bad-ai-response.json"
    bad_response.write_text("{not json", encoding="utf-8")

    with pytest.raises(module.TaskIntakeError, match="not valid JSON"):
        module.prepare_ai_review(state_root=state_root, packet_id="task-demo", response=bad_response)

    packet_dir = state_root / "backlog" / "drafts" / "task-demo"
    assert not (packet_dir / "ai-review-response.json").exists()
    assert (packet_dir / "ai-review-error.json").exists()
    assert not (state_root / "backlog" / "queued").exists()


def test_ai_review_schema_invalid_response_fails_closed(tmp_path: Path) -> None:
    module = _load_module()
    state_root = tmp_path / "targets" / "demo"
    request = module.create_draft(state_root=state_root, target_id="demo", packet_id="task-demo")
    request.write_text(_safe_request(), encoding="utf-8")
    module.review_packet(state_root=state_root, packet_id="task-demo")

    missing_required = tmp_path / "missing-required.json"
    missing_required.write_text(module.json.dumps({"summary": "ok"}), encoding="utf-8")
    with pytest.raises(module.TaskIntakeError, match="missing required"):
        module.prepare_ai_review(state_root=state_root, packet_id="task-demo", response=missing_required)

    packet_dir = state_root / "backlog" / "drafts" / "task-demo"
    assert not (packet_dir / "ai-review-response.json").exists()
    assert (packet_dir / "ai-review-error.json").exists()

    bad_type = tmp_path / "bad-type.json"
    bad_type.write_text(
        module.json.dumps({"summary": "ok", "open_questions": ["one"], "risk_notes": [123]}),
        encoding="utf-8",
    )
    with pytest.raises(module.TaskIntakeError, match="items must be strings"):
        module.prepare_ai_review(state_root=state_root, packet_id="task-demo", response=bad_type)


def test_ai_review_invalid_response_clears_stale_success_artifacts(tmp_path: Path) -> None:
    module = _load_module()
    state_root = tmp_path / "targets" / "demo"
    request = module.create_draft(state_root=state_root, target_id="demo", packet_id="task-demo")
    request.write_text(_safe_request(), encoding="utf-8")
    module.review_packet(state_root=state_root, packet_id="task-demo")

    valid = tmp_path / "valid.json"
    valid.write_text(
        module.json.dumps({"summary": "ok", "open_questions": [], "risk_notes": []}),
        encoding="utf-8",
    )
    module.prepare_ai_review(state_root=state_root, packet_id="task-demo", response=valid)
    packet_dir = state_root / "backlog" / "drafts" / "task-demo"
    assert (packet_dir / "ai-review.json").exists()
    assert (packet_dir / "ai-review-response.json").exists()

    invalid = tmp_path / "invalid.json"
    invalid.write_text(
        module.json.dumps(
            {
                "summary": '{"api_key": "abcdef12345678901234567890"}',
                "open_questions": [],
                "risk_notes": [],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(module.TaskIntakeError, match="secret-like"):
        module.prepare_ai_review(state_root=state_root, packet_id="task-demo", response=invalid)

    assert not (packet_dir / "ai-review.json").exists()
    assert not (packet_dir / "ai-review-response.json").exists()
    assert (packet_dir / "ai-review-error.json").exists()


def test_ai_review_rejects_prefixed_secret_and_non_utf8_response(tmp_path: Path) -> None:
    module = _load_module()
    state_root = tmp_path / "targets" / "demo"
    request = module.create_draft(state_root=state_root, target_id="demo", packet_id="task-demo")
    request.write_text(_safe_request(), encoding="utf-8")
    module.review_packet(state_root=state_root, packet_id="task-demo")

    prefixed_secret = tmp_path / "prefixed.json"
    prefixed_secret.write_text(
        module.json.dumps(
            {
                "summary": "ok",
                "open_questions": ['{"access_token": "abcdef12345678901234567890"}'],
                "risk_notes": [],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(module.TaskIntakeError, match="secret-like"):
        module.prepare_ai_review(state_root=state_root, packet_id="task-demo", response=prefixed_secret)

    non_utf8 = tmp_path / "non-utf8.json"
    non_utf8.write_bytes(b"\xff\xfe{")
    with pytest.raises(module.TaskIntakeError, match="UTF-8"):
        module.prepare_ai_review(state_root=state_root, packet_id="task-demo", response=non_utf8)

    packet_dir = state_root / "backlog" / "drafts" / "task-demo"
    assert not (packet_dir / "ai-review-response.json").exists()
    assert (packet_dir / "ai-review-error.json").exists()
