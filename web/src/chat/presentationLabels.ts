import type { PlanStep } from "../api/types";

const TOOL_LABELS: Record<string, string> = {
  python: "数据计算",
  spreadsheet: "表格分析",
  knowledge: "知识检索",
  artifact: "产物处理",
  inspect: "结构检查",
  bash: "数据处理"
};

export function toolLabel(tool: string): string {
  return TOOL_LABELS[tool.toLowerCase()] ?? "数据处理";
}

export function stepTitle(step?: PlanStep): string {
  if (!step) return "分析任务";
  const description = step.description?.trim() ?? "";
  if (/pi agent runtime|spreadsheet_analysis/i.test(description)) {
    return "理解表格并完成分析";
  }
  return description || step.instruction?.trim() || "分析任务";
}
