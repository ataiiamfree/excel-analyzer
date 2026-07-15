from pathlib import Path
from types import SimpleNamespace

from app.agent.types import StepResult
from app.tools.result_checker import ResultChecker


def _make_step(step_id="s1", expected_outputs=None, instruction="分析数据"):
    return SimpleNamespace(
        id=step_id,
        expected_outputs=expected_outputs or [],
        instruction=instruction,
    )


def _make_result(success=True, stdout="结果正常", stderr="", output_files=None, script_path=None):
    return SimpleNamespace(
        success=success,
        stdout=stdout,
        stderr=stderr,
        output_files=output_files or [],
        script_path=script_path,
    )


def _make_workspace(tmp_path):
    return SimpleNamespace(
        path=str(tmp_path),
        list_files=lambda: [],
    )


def _make_context():
    return SimpleNamespace(step_summaries={}, user_query="")


def _make_profile_context(profile, user_query=""):
    return SimpleNamespace(step_summaries={}, user_query=user_query, data_profile=profile)


def test_all_pass(tmp_path):
    checker = ResultChecker()
    result = checker.validate(
        _make_step(), _make_result(), _make_context(), _make_workspace(tmp_path)
    )
    assert result.status == "passed"
    assert not result.failed


def test_step_result_contract_passes(tmp_path):
    checker = ResultChecker()
    result = checker.validate(
        _make_step(),
        StepResult(stdout="分析完成: 总计 100 行", files=[]),
        _make_context(),
        _make_workspace(tmp_path),
    )
    assert result.status == "passed"


def test_process_failure(tmp_path):
    checker = ResultChecker()
    result = checker.validate(
        _make_step(),
        _make_result(success=False, stderr="ImportError"),
        _make_context(),
        _make_workspace(tmp_path),
    )
    assert result.status == "failed"
    assert any(c.name == "process_success" and c.status == "failed" for c in result.checks)


def test_empty_stdout_warning(tmp_path):
    checker = ResultChecker()
    step = _make_step(expected_outputs=[{"path": "output/data.xlsx"}])
    result = checker.validate(
        step, _make_result(stdout=""), _make_context(), _make_workspace(tmp_path)
    )
    assert any(c.name == "stdout_not_empty" and c.status == "warning" for c in result.checks)


def test_output_files_readable(tmp_path):
    # 创建一个空文件（应触发警告）
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    (output_dir / "empty.csv").write_text("")
    (output_dir / "good.csv").write_text("a,b\n1,2\n")

    checker = ResultChecker()
    exec_result = _make_result(output_files=["output/empty.csv", "output/good.csv"])
    result = checker.validate(
        _make_step(), exec_result, _make_context(),
        SimpleNamespace(path=str(tmp_path), list_files=lambda: []),
    )
    assert any(c.name == "output_files_readable" and c.status == "failed" for c in result.checks)


def test_basic_invariants_export_warning(tmp_path):
    """导出指令但本步骤无 output 产物时应失败，触发自动修复。"""
    output_dir = tmp_path / "output"
    output_dir.mkdir()

    checker = ResultChecker()
    result = checker.validate(
        _make_step(instruction="导出明细数据到 Excel"),
        _make_result(),
        _make_context(),
        SimpleNamespace(path=str(tmp_path), list_files=lambda: []),
    )
    failures = [c for c in result.checks if c.name == "export_has_output"]
    assert len(failures) == 1
    assert failures[0].status == "failed"
    assert result.status == "failed"


def test_basic_invariants_export_passes_with_current_step_output(tmp_path):
    """导出指令存在当前步骤产物时不应误报。"""
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    (output_dir / "data.csv").write_text("a,b\n1,2\n")

    checker = ResultChecker()
    result = checker.validate(
        _make_step(instruction="导出明细数据到 Excel"),
        _make_result(output_files=["output/data.csv"]),
        _make_context(),
        SimpleNamespace(path=str(tmp_path), list_files=lambda: []),
    )
    assert not any(c.name == "export_has_output" for c in result.checks)
    assert result.status == "passed"


def test_basic_invariants_final_answer_output_does_not_require_file(tmp_path):
    checker = ResultChecker()
    result = checker.validate(
        _make_step(instruction="统计超过阈值的年份数，并输出最终答案"),
        _make_result(stdout="Final Answer: 4"),
        _make_context(),
        _make_workspace(tmp_path),
    )

    assert not any(c.name == "export_has_output" for c in result.checks)
    assert result.status == "passed"


def test_question_task_requires_marked_final_answer(tmp_path):
    checker = ResultChecker()
    result = checker.validate(
        _make_step(instruction="What is the total sales?"),
        _make_result(stdout="The total sales are 100."),
        _make_context(),
        _make_workspace(tmp_path),
    )

    final_answer_checks = [c for c in result.checks if c.name == "final_answer_contract"]
    assert final_answer_checks[0].status == "failed"
    assert result.status == "failed"


def test_question_task_accepts_marked_final_answer(tmp_path):
    checker = ResultChecker()
    result = checker.validate(
        _make_step(instruction="What is the total sales?"),
        _make_result(stdout="Checked rows\nFinal Answer: 100"),
        _make_context(),
        _make_workspace(tmp_path),
    )

    assert result.status == "passed"


def test_non_question_task_does_not_require_final_answer(tmp_path):
    checker = ResultChecker()
    result = checker.validate(
        _make_step(instruction="分析数据并说明发现"),
        _make_result(stdout="分析完成，图表已保存。"),
        _make_context(),
        _make_workspace(tmp_path),
    )

    assert result.status == "passed"


def test_no_data_answer_fails_when_year_exists_in_column_names(tmp_path):
    checker = ResultChecker()
    context = _make_profile_context(
        {
            "tables": [
                {
                    "columns_detail": [
                        {"name": "Month"},
                        {"name": "Year 2020_Total Profit"},
                    ]
                }
            ]
        },
        user_query="What was the 2020 profit?",
    )

    result = checker.validate(
        _make_step(instruction="What was the 2020 profit?"),
        _make_result(stdout="Rows for 2020: 0\nFinal Answer: No 2020 data available."),
        context,
        _make_workspace(tmp_path),
    )

    check = [c for c in result.checks if c.name == "no_data_answer_column_check"][0]
    assert check.status == "failed"
    assert result.status == "failed"


def test_no_data_answer_year_check_ignores_year_in_notes_column(tmp_path):
    checker = ResultChecker()
    context = _make_profile_context(
        {
            "tables": [
                {
                    "columns_detail": [
                        {"name": "Product"},
                        {"name": "Notes2020"},
                    ]
                }
            ]
        },
        user_query="What was the 2020 profit?",
    )

    result = checker.validate(
        _make_step(instruction="What was the 2020 profit?"),
        _make_result(stdout="Rows for 2020: 0\nFinal Answer: No 2020 data available."),
        context,
        _make_workspace(tmp_path),
    )

    check = [c for c in result.checks if c.name == "no_data_answer_column_check"][0]
    assert check.status == "passed"
    assert result.status == "passed"


def test_no_data_answer_check_allows_none_increased_answer(tmp_path):
    checker = ResultChecker()
    context = _make_profile_context(
        {
            "tables": [
                {
                    "columns_detail": [
                        {"name": "Year 2020_Total Profit"},
                        {"name": "Year 2020_Cost Expenses"},
                    ]
                }
            ]
        },
        user_query="In 2020, which quarter's profit MoM growth rate increased?",
    )

    result = checker.validate(
        _make_step(instruction="Which quarter's profit MoM growth rate increased in 2020?"),
        _make_result(
            stdout=(
                "Q1: -22.7%, Q2: -67.7%, Q3: -143.7%, Q4: -1001.2%\n"
                "Final Answer: No quarter increased; none increased."
            )
        ),
        context,
        _make_workspace(tmp_path),
    )

    check = [c for c in result.checks if c.name == "no_data_answer_column_check"][0]
    assert check.status == "passed"
    assert result.status == "passed"


def test_zero_answer_fails_when_lookup_printed_nonempty_candidates(tmp_path):
    checker = ResultChecker()
    context = _make_profile_context(
        {
            "tables": [
                {
                    "columns_detail": [
                        {"name": "Project Name"},
                        {"name": "Unit"},
                        {"name": "Quantity"},
                    ]
                }
            ]
        },
        user_query='What is the quantity of "Floor Tiles (1000×1000)" on the first floor?',
    )

    result = checker.validate(
        _make_step(
            instruction='Find the quantity of "Floor Tiles (1000×1000)" on the first floor.'
        ),
        _make_result(
            stdout=(
                "Exact match found 0 rows. Trying case-insensitive exact match...\n"
                "Contains match also 0 rows. Printing candidate project names near target:\n"
                "  Fuzzy candidates for Project Name: ['Floor Tiles (1000×1000)']\n"
                "  Fuzzy candidates for Unit: ['First Floor']\n"
                "No matching rows found after all attempts.\n"
                "Filter conditions: Project Name = 'Floor Tiles (1000×1000)', Unit = 'First Floor'\n"
                "Final Answer: 0"
            )
        ),
        context,
        _make_workspace(tmp_path),
    )

    check = [c for c in result.checks if c.name == "no_data_answer_column_check"][0]
    assert check.status == "failed"
    assert "父级/楼层/分组行" in check.message
    assert result.status == "failed"


def test_none_answer_fails_when_failed_lookup_output_contains_task_entity(tmp_path):
    checker = ResultChecker()
    context = _make_profile_context(
        {"tables": [{"columns_detail": [{"name": "Project Name"}, {"name": "Quantity"}]}]},
        user_query='What is the quantity of "Floor Tiles (1000×1000)" on the first floor?',
    )

    result = checker.validate(
        _make_step(
            instruction='Find the quantity of "Floor Tiles (1000×1000)" on the first floor.'
        ),
        _make_result(
            stdout=(
                "Rows where Project Name == 'Floor Tiles (1000x1000)': 0 rows\n"
                "Value counts for Project Name:\n"
                "Floor Tiles (1000×1000)                    3\n"
                "Column 'Project Name' also contains value 'First Floor'\n"
                "No matching row found. Returning None.\n"
                "Final Answer: None"
            )
        ),
        context,
        _make_workspace(tmp_path),
    )

    check = [c for c in result.checks if c.name == "no_data_answer_column_check"][0]
    assert check.status == "failed"
    assert "目标实体" in check.message
    assert result.status == "failed"


def test_column_family_question_requires_selection_basis(tmp_path):
    checker = ResultChecker()
    context = _make_profile_context(
        {
            "tables": [
                {
                    "column_families": [
                        {
                            "base": "press",
                            "columns": ["press", "press_2", "press_3"],
                        }
                    ]
                }
            ]
        },
        user_query="How much did the athlete press?",
    )

    result = checker.validate(
        _make_step(instruction="How much did the athlete press?"),
        _make_result(stdout="Columns: press, press_2, press_3\nFinal Answer: 115 kg"),
        context,
        _make_workspace(tmp_path),
    )

    check = [c for c in result.checks if c.name == "column_family_selection_basis"][0]
    assert check.status == "passed"
    assert result.status == "passed"


def test_column_family_question_passes_with_selection_basis(tmp_path):
    checker = ResultChecker()
    context = _make_profile_context(
        {
            "tables": [
                {
                    "column_families": [
                        {
                            "base": "press",
                            "columns": ["press", "press_2", "press_3"],
                        }
                    ]
                }
            ]
        },
        user_query="How much did the athlete press?",
    )

    result = checker.validate(
        _make_step(instruction="How much did the athlete press?"),
        _make_result(
            stdout=(
                "Attempt values across column family press: [115, 120, 125]\n"
                "Selection basis: best valid value.\n"
                "Final Answer: 125 kg"
            )
        ),
        context,
        _make_workspace(tmp_path),
    )

    assert result.status == "passed"


def test_column_family_question_rejects_primary_column_basis(tmp_path):
    checker = ResultChecker()
    context = _make_profile_context(
        {
            "tables": [
                {
                    "column_families": [
                        {
                            "base": "press",
                            "columns": ["press", "press_2", "press_3"],
                        }
                    ]
                }
            ]
        },
        user_query="How much did the athlete press?",
    )

    result = checker.validate(
        _make_step(instruction="How much did the athlete press?"),
        _make_result(
            stdout=(
                "Press column family values: press=115, press_2=120, press_3=125.\n"
                "Selection basis: press is the primary column, so it is the main result value.\n"
                "Final Answer: 115 kg"
            )
        ),
        context,
        _make_workspace(tmp_path),
    )

    check = [c for c in result.checks if c.name == "column_family_selection_basis"][0]
    assert check.status == "warning"
    assert result.status == "passed"


def test_column_family_does_not_enforce_benchmark_best_value(tmp_path):
    checker = ResultChecker()
    context = _make_profile_context(
        {
            "tables": [
                {
                    "columns_detail": [
                        {"name": "press"},
                        {"name": "press_2"},
                        {"name": "press_3"},
                    ]
                }
            ]
        },
        user_query="How much did the athlete press?",
    )

    result = checker.validate(
        _make_step(instruction="How much did the athlete press?"),
        _make_result(
            stdout=(
                "  press: 115.0\n"
                "  press_2: 120\n"
                "  press_3: 125\n"
                "Final Answer: 115 kg"
            )
        ),
        context,
        _make_workspace(tmp_path),
    )

    check = [c for c in result.checks if c.name == "column_family_selection_basis"][0]
    assert check.status == "passed"
    assert result.status == "passed"


def test_pairwise_metric_question_rejects_cost_based_rederivation_when_direct_pair_exists(tmp_path):
    checker = ResultChecker()
    context = _make_profile_context(
        {
            "tables": [
                {
                    "columns_detail": [
                        {"name": "Product Information_Product Name"},
                        {"name": "Cost / Linear Foot_Galvalume"},
                        {"name": "Cost / Linear Foot_Painted"},
                        {"name": "Price_Galvalume"},
                        {"name": "Price_Painted"},
                        {"name": "CostMaterial + CostLabor_Galvalume"},
                        {"name": "CostMaterial + CostLabor_Painted"},
                    ]
                }
            ]
        },
        user_query=(
            'What is the difference in "Mark Up Price" between "Painted" and '
            '"Galvalume" materials for the product "17.25 Cap"?'
        ),
    )

    result = checker.validate(
        _make_step(
            instruction=(
                "Filter product '17.25 Cap', calculate Mark Up Price for "
                "Galvalume and Painted, compute difference."
            )
        ),
        _make_result(
            stdout=(
                "Galvalume: Price = 27.61, CostMaterial+CostLabor = 15.78, "
                "Mark Up = 11.83\n"
                "Painted: Price = 31.66, CostMaterial+CostLabor = 18.09, "
                "Mark Up = 13.57\n"
                "Final Answer: 1.73"
            )
        ),
        context,
        _make_workspace(tmp_path),
    )

    check = [c for c in result.checks if c.name == "direct_pair_metric_selection"][0]
    assert check.status == "warning"
    assert "Price_Galvalume" in check.message
    assert result.status == "passed"


def test_pairwise_price_question_rejects_cost_pair_substitution(tmp_path):
    script = tmp_path / "scripts" / "s1.py"
    script.parent.mkdir()
    script.write_text(
        "diff = row['CostMaterial_Painted'] - row['CostMaterial_Galvalume']\n"
        "print(f'Final Answer: {diff}')\n",
        encoding="utf-8",
    )
    checker = ResultChecker()
    context = _make_profile_context(
        {
            "tables": [
                {
                    "columns_detail": [
                        {"name": "Price_Galvalume"},
                        {"name": "Price_Painted"},
                        {"name": "CostMaterial_Galvalume"},
                        {"name": "CostMaterial_Painted"},
                    ]
                }
            ]
        },
        user_query="What is the difference in Mark Up Price between Painted and Galvalume?",
    )

    result = checker.validate(
        _make_step(instruction="compare Mark Up Price between Painted and Galvalume"),
        _make_result(stdout="Final Answer: 2.31", script_path=str(script)),
        context,
        _make_workspace(tmp_path),
    )

    check = [c for c in result.checks if c.name == "direct_pair_metric_selection"][0]
    assert check.status == "warning"
    assert result.status == "passed"


def test_pairwise_metric_question_allows_direct_pair_usage(tmp_path):
    checker = ResultChecker()
    context = _make_profile_context(
        {
            "tables": [
                {
                    "columns_detail": [
                        {"name": "Price_Galvalume"},
                        {"name": "Price_Painted"},
                    ]
                }
            ]
        },
        user_query="What is the difference in price between Painted and Galvalume?",
    )

    result = checker.validate(
        _make_step(instruction="compare price between Painted and Galvalume"),
        _make_result(
            stdout=(
                "Using direct paired columns Price_Galvalume and Price_Painted.\n"
                "Final Answer: 4.05"
            )
        ),
        context,
        _make_workspace(tmp_path),
    )

    check = [c for c in result.checks if c.name == "direct_pair_metric_selection"][0]
    assert check.status == "passed"
    assert result.status == "passed"


def test_pairwise_metric_question_checks_script_when_stdout_hides_derivation(tmp_path):
    script = tmp_path / "scripts" / "s1.py"
    script.parent.mkdir()
    script.write_text(
        "gal_markup = row['Price_Galvalume'] - row['CostMaterial + CostLabor_Galvalume']\n"
        "paint_markup = row['Price_Painted'] - row['CostMaterial + CostLabor_Painted']\n"
        "diff = paint_markup - gal_markup\n",
        encoding="utf-8",
    )
    checker = ResultChecker()
    context = _make_profile_context(
        {
            "tables": [
                {
                    "columns_detail": [
                        {"name": "Price_Galvalume"},
                        {"name": "Price_Painted"},
                        {"name": "CostMaterial + CostLabor_Galvalume"},
                        {"name": "CostMaterial + CostLabor_Painted"},
                    ]
                }
            ]
        },
        user_query="What is the difference in Mark Up Price between Painted and Galvalume?",
    )

    result = checker.validate(
        _make_step(instruction="compare Mark Up Price between Painted and Galvalume"),
        _make_result(stdout="Final Answer: 1.73", script_path=str(script)),
        context,
        _make_workspace(tmp_path),
    )

    check = [c for c in result.checks if c.name == "direct_pair_metric_selection"][0]
    assert check.status == "warning"
    assert result.status == "passed"


def test_single_item_query_rejects_unrequested_sum_aggregation(tmp_path):
    script = tmp_path / "scripts" / "s1.py"
    script.parent.mkdir()
    script.write_text(
        "quantities = pd.to_numeric(matches['Quantity'], errors='coerce')\n"
        "answer = quantities.sum()\n",
        encoding="utf-8",
    )
    checker = ResultChecker()
    context = _make_profile_context(
        {"tables": [{"columns_detail": [{"name": "Project Name"}, {"name": "Quantity"}]}]},
        user_query="What is the quantity of Floor Tiles on the first floor?",
    )

    result = checker.validate(
        _make_step(instruction="find the quantity of Floor Tiles on the first floor"),
        _make_result(
            stdout="Number of rows matching project and first floor: 3\nFinal Answer: 264.8",
            script_path=str(script),
        ),
        context,
        _make_workspace(tmp_path),
    )

    check = [c for c in result.checks if c.name == "single_item_not_aggregated"][0]
    assert check.status == "warning"
    assert result.status == "passed"


def test_single_item_query_allows_explicit_total(tmp_path):
    checker = ResultChecker()
    context = _make_profile_context(
        {"tables": [{"columns_detail": [{"name": "Project Name"}, {"name": "Quantity"}]}]},
        user_query="What is the total quantity of Floor Tiles?",
    )

    result = checker.validate(
        _make_step(instruction="calculate total quantity of Floor Tiles"),
        _make_result(stdout="Exact matches count: 3\nSum of Quantity: 264.8\nFinal Answer: 264.8"),
        context,
        _make_workspace(tmp_path),
    )

    check = [c for c in result.checks if c.name == "single_item_not_aggregated"][0]
    assert check.status == "passed"
    assert result.status == "passed"
