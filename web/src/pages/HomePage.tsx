import { ChangeEvent, FormEvent, KeyboardEvent, useState } from "react";
import { Menu, SendHorizontal, UploadCloud } from "lucide-react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";

import { createConversation, fetchConversations, validateExcelFile } from "../api/http";
import Sidebar from "../layout/Sidebar";
import { useUiStore } from "../store/uiStore";

export default function HomePage() {
  const navigate = useNavigate();
  const [file, setFile] = useState<File | null>(null);
  const [query, setQuery] = useState("");
  const [fileError, setFileError] = useState("");
  const mobileSidebarOpen = useUiStore((state) => state.mobileSidebarOpen);
  const setMobileSidebarOpen = useUiStore((state) => state.setMobileSidebarOpen);
  const conversations = useQuery({ queryKey: ["conversations"], queryFn: fetchConversations });
  const create = useMutation({
    mutationFn: () => {
      if (!file) throw new Error("请选择 Excel 文件");
      const initialQuery = query.trim();
      if (!initialQuery) throw new Error("请输入分析问题");
      return createConversation(file, initialQuery);
    },
    onSuccess: (conversation) => {
      const initialQuery = query.trim();
      navigate(`/c/${conversation.id}`, {
        state: initialQuery ? { initialQuery } : null
      });
    }
  });

  const onFile = (event: ChangeEvent<HTMLInputElement>) => {
    const nextFile = event.target.files?.[0] ?? null;
    if (!nextFile) {
      setFile(null);
      setFileError("");
      return;
    }
    try {
      validateExcelFile(nextFile);
      setFile(nextFile);
      setFileError("");
    } catch (error) {
      setFile(null);
      setFileError(error instanceof Error ? error.message : "无法上传该文件");
      event.target.value = "";
    }
  };

  const submitForm = () => {
    if (!file || !query.trim() || create.isPending) return;
    create.mutate();
  };

  const submit = (event: FormEvent) => {
    event.preventDefault();
    submitForm();
  };

  const onQueryKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key !== "Enter" || event.shiftKey || event.nativeEvent.isComposing) return;
    event.preventDefault();
    submitForm();
  };

  return (
    <div className="home-shell">
      <Sidebar
        groups={conversations.data?.groups ?? []}
        mobileOpen={mobileSidebarOpen}
        onNavigate={() => setMobileSidebarOpen(false)}
      />
      {mobileSidebarOpen ? (
        <button
          className="mobile-backdrop"
          title="关闭会话列表"
          onClick={() => setMobileSidebarOpen(false)}
        />
      ) : null}
      <main className="home-main">
        <button
          className="icon-button mobile-menu home-menu"
          title="打开会话列表"
          onClick={() => setMobileSidebarOpen(true)}
        >
          <Menu size={18} />
        </button>
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
            onKeyDown={onQueryKeyDown}
            placeholder="例如：按区域汇总 Q3 销售额，找出 TOP5 和 BTM5 城市，输出图表与明细表。"
          />
          <div className="upload-actions">
            <span className="mono" style={{ color: "var(--ink-4)", fontSize: 11 }}>
              {file ? `${Math.ceil(file.size / 1024)} KB` : "支持单个文件 100MB 以内"}
            </span>
            <button className="primary-btn" disabled={!file || !query.trim() || create.isPending}>
              {create.isPending ? "创建中..." : "开始分析"}
              <SendHorizontal size={14} />
            </button>
          </div>
          {fileError ? <p className="form-error" role="alert">{fileError}</p> : null}
          {create.error ? <p className="form-error" role="alert">{create.error.message}</p> : null}
        </form>
      </main>
    </div>
  );
}
