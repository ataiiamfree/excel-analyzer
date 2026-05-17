from app.agent.plan import ExecutionPlan, PlanAdjustment, Step


def test_next_runnable_step_respects_dependencies_and_insertions():
    plan = ExecutionPlan(
        steps=[
            Step(id="s1", tool="python", description="load", instruction="load"),
            Step(id="s2", tool="python", description="analyze", instruction="analyze", depends_on=["s1"]),
        ]
    )

    step = plan.next_runnable_step()
    assert step is not None
    assert step.id == "s1"

    plan.mark_done("s1")
    plan.apply_adjustment(
        PlanAdjustment(insert_steps=[Step(id="s1b", tool="python", description="extra", instruction="extra")]),
        current_step_id="s1",
    )

    step = plan.next_runnable_step()
    assert step is not None
    assert step.id == "s1b"


def test_failed_step_is_not_done():
    plan = ExecutionPlan([Step(id="s1", tool="python", description="x", instruction="x")])
    plan.mark_running("s1")
    plan.mark_failed("s1", "boom", check="failed")

    step = plan.get_step("s1")
    assert step.status == "failed"
    assert step.error == "boom"
    assert step.check_status == "failed"


def test_all_done_returns_none():
    plan = ExecutionPlan([
        Step(id="s1", tool="python", description="a", instruction="a"),
        Step(id="s2", tool="python", description="b", instruction="b"),
    ])
    plan.mark_done("s1")
    plan.mark_done("s2")
    assert plan.next_runnable_step() is None
    assert plan.remaining_steps() == []


def test_skip_step():
    plan = ExecutionPlan([
        Step(id="s1", tool="python", description="a", instruction="a"),
        Step(id="s2", tool="python", description="b", instruction="b"),
    ])
    plan.skip_step("s1")
    assert plan.get_step("s1").status == "skipped"
    step = plan.next_runnable_step()
    assert step is not None
    assert step.id == "s2"


def test_to_dict_round_trip():
    plan = ExecutionPlan([
        Step(id="s1", tool="python", description="a", instruction="a"),
    ])
    plan.mark_done("s1")
    d = plan.to_dict()
    assert d["steps"][0]["status"] == "done"
    assert isinstance(d["report_outline"], list)
