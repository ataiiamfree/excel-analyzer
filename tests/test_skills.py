from app.skills.registry import IntentRouter, build_default_skill_registry


def test_router_selects_spreadsheet_for_initial_chart_request_with_only_normalized_artifacts():
    registry = build_default_skill_registry()
    router = IntentRouter(registry)

    skill = router.route(
        "生成趋势图",
        artifacts=[{"kind": "normalized_table", "name": "巡检记录_t1.parquet"}],
    )

    assert skill.name == "spreadsheet_analysis"


def test_router_selects_artifact_qa_for_exact_artifact_name():
    registry = build_default_skill_registry()
    router = IntentRouter(registry)

    skill = router.route(
        "解释 trend_ma_anomaly_chart.png 的含义",
        artifacts=[{"kind": "chart", "name": "trend_ma_anomaly_chart.png"}],
    )

    assert skill.name == "artifact_qa"


def test_router_selects_report_generation_when_report_requested():
    registry = build_default_skill_registry()
    router = IntentRouter(registry)

    skill = router.route("请生成一份完整分析报告", artifacts=[])

    assert skill.name == "report_generation"
