import { ChangeEvent, DragEvent, FormEvent, KeyboardEvent, MouseEvent, useRef, useState } from "react";
import { Menu, SendHorizontal, UploadCloud, X } from "lucide-react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";

import { createConversation, fetchConversations, validateExcelFile } from "../api/http";
import Sidebar from "../layout/Sidebar";
import { useUiStore } from "../store/uiStore";

const EXAMPLE_QUERIES = [
  "汇总各部门费用，并找出超预算项目",
  "按月分析销售趋势，并标记异常月份",
  "找出库存不足的商品，并导出补货清单"
];

export default function HomePage() {
  const navigate = useNavigate();
  const [file, setFile] = useState<File | null>(null);
  const [query, setQuery] = useState("");
  const [fileError, setFileError] = useState("");
  const [dragActive, setDragActive] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
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

  // 点击选择与拖拽放下共用同一套校验逻辑；返回是否被接受。
  const acceptFile = (nextFile: File | null): boolean => {
    if (!nextFile) {
      setFile(null);
      setFileError("");
      return false;
    }
    try {
      validateExcelFile(nextFile);
      setFile(nextFile);
      setFileError("");
      return true;
    } catch (error) {
      setFile(null);
      setFileError(error instanceof Error ? error.message : "无法上传该文件");
      return false;
    }
  };

  const onFile = (event: ChangeEvent<HTMLInputElement>) => {
    const accepted = acceptFile(event.target.files?.[0] ?? null);
    // 校验失败时清空 input，便于重新选择同名文件。
    if (!accepted) event.target.value = "";
  };

  const onDragOver = (event: DragEvent<HTMLLabelElement>) => {
    event.preventDefault();
    if (!dragActive) setDragActive(true);
  };

  const onDragLeave = (event: DragEvent<HTMLLabelElement>) => {
    event.preventDefault();
    // 仅在指针真正离开投放区（而非在其子元素间移动）时取消高亮。
    if (event.currentTarget.contains(event.relatedTarget as Node | null)) return;
    setDragActive(false);
  };

  const onDrop = (event: DragEvent<HTMLLabelElement>) => {
    event.preventDefault();
    setDragActive(false);
    acceptFile(event.dataTransfer.files?.[0] ?? null);
  };

  const clearFile = (event: MouseEvent<HTMLButtonElement>) => {
    // 阻止冒泡到 label，否则会顺带打开文件选择器。
    event.preventDefault();
    event.stopPropagation();
    setFile(null);
    setFileError("");
    // 重置隐藏 input，使重新选择同一个文件也能触发 change。
    if (inputRef.current) inputRef.current.value = "";
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
          上传 Excel，用一句话得到分析结论、图表和可下载表格。
        </p>
        <div className="home-capabilities" aria-label="产品能力">
          <span>自动理解表格</span>
          <span>可追问分析</span>
          <span>结果可下载</span>
        </div>
        <form className="upload-panel" onSubmit={submit}>
          <label
            className={`upload-drop ${file ? "file-ready" : ""} ${dragActive ? "drag-active" : ""}`}
            onDragOver={onDragOver}
            onDragEnter={onDragOver}
            onDragLeave={onDragLeave}
            onDrop={onDrop}
          >
            <UploadCloud size={24} />
            <span>
              {dragActive
                ? "松开鼠标即可上传"
                : file
                  ? `已就绪 · ${file.name}`
                  : "点击选择，或将 .xlsx / .xlsm 文件拖到这里"}
            </span>
            {file && !dragActive ? (
              <button type="button" className="upload-clear" title="移除文件" onClick={clearFile}>
                <X size={16} />
              </button>
            ) : null}
            <input
              ref={inputRef}
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
          <div className="example-queries" aria-label="示例问题">
            <span className="example-label">试试这样问</span>
            <div className="example-list">
              {EXAMPLE_QUERIES.map((example) => (
                <button type="button" key={example} onClick={() => setQuery(example)}>
                  {example}
                </button>
              ))}
            </div>
          </div>
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
