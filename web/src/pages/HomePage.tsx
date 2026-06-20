import { ChangeEvent, FormEvent, useState } from "react";
import { FileSpreadsheet, SendHorizontal, UploadCloud } from "lucide-react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";

import { createConversation, fetchConversations } from "../api/http";
import Sidebar from "../layout/Sidebar";

export default function HomePage() {
  const navigate = useNavigate();
  const [file, setFile] = useState<File | null>(null);
  const [query, setQuery] = useState("");
  const conversations = useQuery({ queryKey: ["conversations"], queryFn: fetchConversations });
  const create = useMutation({
    mutationFn: () => {
      if (!file) throw new Error("请选择 Excel 文件");
      return createConversation(file, query);
    },
    onSuccess: (conversation) => {
      navigate(`/c/${conversation.id}`, { state: { initialQuery: query.trim() } });
    }
  });

  const onFile = (event: ChangeEvent<HTMLInputElement>) => {
    setFile(event.target.files?.[0] ?? null);
  };

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (!file || create.isPending) return;
    create.mutate();
  };

  return (
    <div className="home-shell">
      <Sidebar groups={conversations.data?.groups ?? []} />
      <main className="home-main">
        <h1 className="home-title">
          Chat<em>Excel</em>
        </h1>
        <p className="home-copy">
          上传 Excel 后直接描述分析目标，系统会生成计划、执行 Python 分析、输出报告和可下载产物。
        </p>
        <form className="upload-panel" onSubmit={submit}>
          <label className="upload-drop">
            <UploadCloud size={24} />
            <span>{file ? file.name : "选择 .xlsx / .xlsm 文件"}</span>
            <input
              type="file"
              accept=".xlsx,.xlsm"
              onChange={onFile}
              style={{ position: "absolute", opacity: 0, pointerEvents: "none" }}
            />
          </label>
          <textarea
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="例如：按区域汇总 Q3 销售额，找出 TOP5 和 BTM5 城市，输出图表与明细表。"
          />
          <div className="upload-actions">
            <span className="mono" style={{ color: "var(--ink-4)", fontSize: 11 }}>
              {file ? `${Math.ceil(file.size / 1024)} KB` : "支持单个文件 100MB 以内"}
            </span>
            <button className="primary-btn" disabled={!file || create.isPending}>
              {create.isPending ? "创建中..." : "开始分析"}
              <SendHorizontal size={14} />
            </button>
          </div>
          {create.error ? <p style={{ color: "var(--accent)" }}>{String(create.error.message)}</p> : null}
        </form>
      </main>
      <aside className="home-art">
        <div className="prototype-card">
          <div className="assistant-head">
            <span className="glyph" />
            <span className="name">ChatExcel</span>
            <span className="role">分析师 · API</span>
            <span className="ts">ready</span>
          </div>
          <div className="plan">
            <h4>
              <span>执行计划</span>
              <span className="scope">3 步 · python</span>
            </h4>
            {["读取并识别表结构", "生成分析脚本", "输出报告与产物"].map((label, index) => (
              <div className={`step ${index === 0 ? "done" : index === 1 ? "running" : "pending"}`} key={label}>
                <div className="marker">{String(index + 1).padStart(2, "0")}</div>
                <div className="body">
                  <div className="label">{label}</div>
                  <div className="desc">数据留在沙箱中流转，LLM 只读取摘要和执行反馈。</div>
                  <div className="tags">
                    <span className="tag python">python</span>
                    <span className="tag">manifest</span>
                  </div>
                </div>
                <div className="timing">{index === 1 ? <span className="pulse">执行中</span> : <span>ready</span>}</div>
              </div>
            ))}
          </div>
          <div className="artifact-chips">
            <span className="chip">
              <span className="ico xlsx">XL</span>
              <span className="info">
                <span className="n">result.xlsx</span>
                <span className="s">可下载明细</span>
              </span>
            </span>
            <span className="chip">
              <span className="ico png">IMG</span>
              <span className="info">
                <span className="n">chart.png</span>
                <span className="s">图表预览</span>
              </span>
            </span>
          </div>
        </div>
      </aside>
    </div>
  );
}
