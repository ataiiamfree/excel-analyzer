// 报告导出为 PDF：复用页面已渲染的报告 HTML，在独立打印视图里排版，
// 走浏览器"另存为 PDF"。零后端依赖，中文与图表均可正常输出，正文文字
// 保持矢量可选。

interface ChartItem {
  name: string;
  url: string;
}

interface DataItem {
  name: string;
  kindLabel: string;
}

interface ExportReportPdfOptions {
  reportHtml: string;
  query: string;
  statusLabel: string;
  durationMs: number;
  charts: ChartItem[];
  dataArtifacts: DataItem[];
}

function escapeHtml(value: string): string {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

const PRINT_STYLES = `
  @page { margin: 18mm 16mm; }
  * { box-sizing: border-box; }
  body {
    margin: 0;
    color: #161310;
    background: #ffffff;
    font-family: "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", system-ui, sans-serif;
    font-size: 13px;
    line-height: 1.7;
  }
  .doc { max-width: 720px; margin: 0 auto; }
  header { border-bottom: 2px solid #b53b1e; padding-bottom: 14px; margin-bottom: 22px; }
  .brand {
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    font-size: 10.5px; letter-spacing: 0.16em; text-transform: uppercase;
    color: #b53b1e; margin-bottom: 8px;
  }
  h1.doc-title {
    font-family: Georgia, "Songti SC", "Noto Serif SC", serif;
    font-weight: 600; font-size: 22px; line-height: 1.25; margin: 0 0 10px;
  }
  .meta { font-size: 11px; color: #6c6357; display: flex; flex-wrap: wrap; gap: 4px 16px; }
  .meta span::before { content: "· "; color: #b53b1e; }
  .meta span:first-child::before { content: ""; }
  .result-highlight {
    margin: 0 0 20px; padding: 14px 16px 10px;
    border: 1px solid #d8c8a5; border-radius: 10px; background: #fffaf0;
    break-inside: avoid;
  }
  .result-highlight-label {
    font-family: ui-monospace, Menlo, monospace; font-size: 10px;
    letter-spacing: 0.12em; text-transform: uppercase; color: #a7791e; margin-bottom: 8px;
  }
  h1, h2, h3 {
    font-family: Georgia, "Songti SC", "Noto Serif SC", serif;
    color: #161310; break-after: avoid;
  }
  .report-body > h1 { font-size: 20px; margin: 20px 0 10px; }
  .report-body h2 {
    font-size: 16px; margin: 22px 0 9px; padding-left: 11px;
    border-left: 3px solid #b53b1e;
  }
  .report-body h3 { font-size: 14px; margin: 16px 0 7px; }
  p { margin: 0 0 10px; color: #3a332c; }
  ul, ol { margin: 6px 0 12px; padding-left: 22px; color: #3a332c; }
  li { margin-bottom: 4px; }
  strong { color: #161310; }
  table {
    width: 100%; border-collapse: collapse; margin: 12px 0 16px;
    font-size: 12px; break-inside: avoid;
  }
  th, td { border: 1px solid #d6cdbb; padding: 6px 10px; text-align: left; }
  th { background: #f6ebd0; font-weight: 600; }
  code {
    font-family: ui-monospace, Menlo, monospace; font-size: 12px;
    background: #f1ece2; padding: 1px 5px; border-radius: 4px;
  }
  .section-label {
    font-family: ui-monospace, Menlo, monospace; font-size: 10px;
    letter-spacing: 0.14em; text-transform: uppercase; color: #b53b1e;
    margin: 26px 0 12px; padding-bottom: 5px; border-bottom: 1px solid #e5ddce;
  }
  figure { margin: 0 0 18px; break-inside: avoid; text-align: center; }
  figure img { max-width: 100%; height: auto; border: 1px solid #e5ddce; border-radius: 8px; }
  figcaption { font-size: 11px; color: #6c6357; margin-top: 6px; }
  .files { list-style: none; padding: 0; margin: 0; }
  .files li {
    display: flex; justify-content: space-between; gap: 12px;
    padding: 7px 0; border-bottom: 1px solid #f1ece2; font-size: 12px;
  }
  .files .kind { color: #9c9285; font-family: ui-monospace, Menlo, monospace; font-size: 10.5px; }
  footer {
    margin-top: 28px; padding-top: 12px; border-top: 1px solid #e5ddce;
    font-size: 10.5px; color: #9c9285; text-align: center;
  }
`;

export function exportReportPdf(options: ExportReportPdfOptions): boolean {
  const { reportHtml, query, statusLabel, durationMs, charts, dataArtifacts } = options;

  const win = window.open("", "_blank", "noopener,noreferrer,width=820,height=1000");
  if (!win) {
    // 弹窗被拦截：调用方负责提示用户放行。
    return false;
  }

  const exportedAt = new Date().toLocaleString("zh-CN", { hour12: false });
  const metaParts = [`状态：${escapeHtml(statusLabel)}`];
  if (durationMs > 0) {
    metaParts.push(`用时：${(durationMs / 1000).toFixed(1)}s`);
  }
  metaParts.push(`导出：${escapeHtml(exportedAt)}`);

  const chartsHtml = charts.length
    ? `<div class="section-label">图表</div>${charts
        .map(
          (chart) =>
            `<figure><img src="${escapeHtml(chart.url)}" alt="${escapeHtml(chart.name)}" /><figcaption>${escapeHtml(chart.name)}</figcaption></figure>`
        )
        .join("")}`
    : "";

  const filesHtml = dataArtifacts.length
    ? `<div class="section-label">数据产物</div><ul class="files">${dataArtifacts
        .map(
          (item) =>
            `<li><span>${escapeHtml(item.name)}</span><span class="kind">${escapeHtml(item.kindLabel)}</span></li>`
        )
        .join("")}</ul>`
    : "";

  win.document.open();
  win.document.write(`<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8" />
<title>${escapeHtml(query || "ChatExcel 分析报告")}</title>
<style>${PRINT_STYLES}</style>
</head>
<body>
  <div class="doc">
    <header>
      <div class="brand">分析报告 · ChatExcel</div>
      <h1 class="doc-title">${escapeHtml(query || "Excel 分析报告")}</h1>
      <div class="meta">${metaParts.map((part) => `<span>${part}</span>`).join("")}</div>
    </header>
    <div class="report-body">${reportHtml}</div>
    ${chartsHtml}
    ${filesHtml}
    <footer>ChatExcel v0.9 Max · 本报告由自动分析生成，关键数值请对照源表核对</footer>
  </div>
</body>
</html>`);
  win.document.close();

  const triggerPrint = async () => {
    const images = Array.from(win.document.images);
    await Promise.all(
      images.map((img) =>
        img.complete
          ? Promise.resolve()
          : new Promise<void>((resolve) => {
              img.onload = () => resolve();
              img.onerror = () => resolve();
            })
      )
    );
    win.focus();
    win.print();
  };

  // 打印结束（含用户取消）后关闭临时窗口。
  win.onafterprint = () => win.close();

  if (win.document.readyState === "complete") {
    void triggerPrint();
  } else {
    win.onload = () => void triggerPrint();
  }

  return true;
}
