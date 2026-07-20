import subprocess
import sys
from pathlib import Path

from openpyxl import Workbook

from scripts.demo_preflight import (
    EXPECTED_TOTALS,
    check_service,
    check_web_build,
    check_workbook,
)


def write_demo_workbook(path: Path) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "月度销售"
    sheet.append(["门店", "月份", "销售额(万元)"])
    for store, total in EXPECTED_TOTALS.items():
        monthly = round(total / 6, 6)
        values = [monthly] * 5 + [round(total - monthly * 5, 6)]
        for month, value in enumerate(values, start=1):
            sheet.append([store, f"2025-{month:02d}", value])
    workbook.save(path)


def test_service_check_accepts_healthy_v0_9_2():
    def fetcher(url: str, _timeout: float):
        if url.endswith("/api/health"):
            return {"status": "ok"}
        return {"info": {"version": "0.9.2"}}

    results = check_service("http://127.0.0.1:8000/", fetcher)

    assert all(result.ok for result in results)


def test_service_check_reports_connection_failure_without_secret_detail():
    def fetcher(_url: str, _timeout: float):
        raise ConnectionError("request carried super-secret-token")

    results = check_service("http://127.0.0.1:8000", fetcher)

    assert len(results) == 1
    assert not results[0].ok
    assert "super-secret-token" not in results[0].detail


def test_workbook_check_reconciles_expected_demo_totals(tmp_path):
    path = tmp_path / "demo.xlsx"
    write_demo_workbook(path)

    results = check_workbook(path)

    assert all(result.ok for result in results)
    assert results[0].detail == "有效数据 30 行"


def test_workbook_check_rejects_missing_file(tmp_path):
    results = check_workbook(tmp_path / "missing.xlsx")

    assert len(results) == 1
    assert not results[0].ok
    assert "文件不存在" in results[0].detail


def test_web_build_requires_index_javascript_and_css(tmp_path):
    dist = tmp_path / "dist"
    assets = dist / "assets"
    assets.mkdir(parents=True)
    (dist / "index.html").write_text("<main />", encoding="utf-8")
    (assets / "app.js").write_text("", encoding="utf-8")

    assert not check_web_build(dist)[0].ok

    (assets / "app.css").write_text("", encoding="utf-8")
    assert check_web_build(dist)[0].ok


def test_demo_preflight_cli_can_import_application_from_scripts_directory():
    result = subprocess.run(
        [sys.executable, "scripts/demo_preflight.py", "--base-url", "http://127.0.0.1:1"],
        cwd=Path(__file__).resolve().parent.parent,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )

    assert result.returncode == 1
    assert "ModuleNotFoundError" not in result.stderr
    assert "ChatExcel v0.9 Max 演示预检" in result.stdout
