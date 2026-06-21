from types import SimpleNamespace

from app.agent.artifact_qa import ArtifactExplainer


class FakeWorkspace:
    path = "/tmp/workspace"

    def read_text(self, path):
        return """
import matplotlib.pyplot as plt
plt.plot([1, 2], [3, 4], label="温度")
plt.title("设备温度趋势")
plt.xlabel("巡检日期")
plt.ylabel("温度")
plt.savefig("output/trend_ma_anomaly_chart.png")
"""


def test_artifact_explainer_resolves_by_exact_name():
    explainer = ArtifactExplainer()
    artifacts = [
        {"name": "summary.xlsx", "path": "output/summary.xlsx"},
        {"name": "trend_ma_anomaly_chart.png", "path": "output/trend_ma_anomaly_chart.png"},
    ]

    artifact = explainer.resolve_by_name("解释 trend_ma_anomaly_chart.png", artifacts)

    assert artifact["name"] == "trend_ma_anomaly_chart.png"


def test_artifact_explainer_uses_lineage_and_script_hints():
    explainer = ArtifactExplainer()
    workspace = FakeWorkspace()
    artifacts = [
        {
            "name": "trend_ma_anomaly_chart.png",
            "path": "output/trend_ma_anomaly_chart.png",
            "kind": "chart",
            "producer_step_id": "s1",
            "producer_tool": "python",
            "source_tables": ["设备巡检记录"],
            "script_path": "scripts/s1_attempt_0.py",
            "stdout_summary": "温度异常 6 点，首次出现在 2025-01-01。",
        }
    ]

    text = explainer.explain("这个图是什么意思", workspace, artifacts)

    assert "trend_ma_anomaly_chart.png" in text
    assert "设备巡检记录" in text
    assert "设备温度趋势" in text
    assert "温度异常 6 点" in text
