(function () {
  const HISTORY_KEY = "chatExcel.history.v1";
  const ACTIVE_KEY = "chatExcel.activeConversationId";
  const MAX_ITEMS = 30;
  const memoryStore = {};

  function getStoredItem(key) {
    try {
      if (window.localStorage) return window.localStorage.getItem(key);
    } catch {
      // Fall through to memory storage.
    }
    return memoryStore[key] || null;
  }

  function setStoredItem(key, value) {
    memoryStore[key] = value;
    try {
      if (window.localStorage) window.localStorage.setItem(key, value);
    } catch {
      // Memory storage is enough for restricted browser contexts.
    }
  }

  function removeStoredItem(key) {
    delete memoryStore[key];
    try {
      if (window.sessionStorage) window.sessionStorage.removeItem(key);
      if (window.localStorage) window.localStorage.removeItem(key);
    } catch {
      // Ignore storage restrictions.
    }
  }

  function nowId() {
    return `cx-${Date.now()}-${Math.random().toString(16).slice(2)}`;
  }

  function getActiveId() {
    let id = getStoredItem(ACTIVE_KEY);
    if (!id) {
      id = nowId();
      setStoredItem(ACTIVE_KEY, id);
    }
    return id;
  }

  function readHistory() {
    try {
      const raw = getStoredItem(HISTORY_KEY);
      const parsed = raw ? JSON.parse(raw) : [];
      if (!Array.isArray(parsed)) return [];
      return parsed.filter((item) => item && item.fileName);
    } catch {
      return [];
    }
  }

  function writeHistory(items) {
    setStoredItem(HISTORY_KEY, JSON.stringify(items.slice(0, MAX_ITEMS)));
  }

  function visibleText() {
    const root = document.querySelector("#root") || document.body;
    return (root.innerText || "")
      .split("\n")
      .map((line) => line.trim())
      .filter(Boolean)
      .filter((line) => !line.startsWith("ChatExcel"))
      .filter((line) => line !== "新开对话")
      .join("\n");
  }

  function pickTitle(text) {
    const lines = text.split("\n").map((line) => line.trim()).filter(Boolean);
    const preferred = lines.find((line) =>
      /分析|统计|汇总|排名|同比|环比|处理|输出|根据|针对|请/.test(line) &&
      !/正在分析|已上传|开始一次|上传 Excel/.test(line)
    );
    const firstFile = text.match(/([\w\u4e00-\u9fff（）()\-_.]+\.xls[xm])/i);
    const raw = preferred || (firstFile ? `分析 ${firstFile[1]}` : lines[0]) || "未命名分析";
    return raw.length > 32 ? `${raw.slice(0, 32)}...` : raw;
  }

  function pickFileName(text) {
    const match = text.match(/([\w\u4e00-\u9fff（）()\-_.]+\.xls[xm])/i);
    return match ? match[1] : "";
  }

  function saveSnapshot() {
    const text = visibleText();
    if (text.length < 20) return;
    const fileName = pickFileName(text);
    if (!fileName) return;

    const id = getActiveId();
    const items = readHistory().filter((item) => item.id !== id);
    const item = {
      id,
      title: pickTitle(text),
      fileName,
      preview: text.slice(0, 160),
      transcript: text.slice(0, 12000),
      updatedAt: new Date().toISOString(),
    };
    writeHistory([item, ...items]);
    renderHistory();
  }

  function classifyMessages() {
    const assistantMessages = Array.from(document.querySelectorAll(".ai-message"));
    for (const message of assistantMessages) {
      const text = (message.innerText || "").trim();
      message.classList.remove(
        "cx-msg-reasoning",
        "cx-msg-progress",
        "cx-msg-plan",
        "cx-msg-execute",
        "cx-msg-result",
        "cx-msg-artifact",
        "cx-msg-preview"
      );

      if (text.startsWith("DeepSeek 思考")) {
        message.classList.add("cx-msg-reasoning");
      } else if (text.startsWith("正在分析")) {
        message.classList.add("cx-msg-progress");
      } else if (text.startsWith("执行计划")) {
        message.classList.add("cx-msg-plan");
      } else if (text.startsWith("状态：完成") || text.startsWith("状态：失败")) {
        message.classList.add("cx-msg-execute");
      } else if (text.startsWith("分析结果")) {
        message.classList.add("cx-msg-result");
      } else if (text.startsWith("结果表预览")) {
        message.classList.add("cx-msg-preview");
      } else if (text.startsWith("可下载的文件") || text.startsWith("分析完成，可下载的文件")) {
        message.classList.add("cx-msg-artifact");
      }
    }
  }

  function formatTime(iso) {
    try {
      const date = new Date(iso);
      return date.toLocaleString("zh-CN", {
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
      });
    } catch {
      return "";
    }
  }

  function startNewChat() {
    removeStoredItem(ACTIVE_KEY);
    const buttons = Array.from(document.querySelectorAll("button"));
    const native = buttons.find((button) => {
      const label = `${button.innerText || ""} ${button.getAttribute("aria-label") || ""}`;
      return /new chat|新(建|开|增).*对话|新聊天/i.test(label);
    });
    if (native && !native.closest(".cx-sidebar")) {
      native.click();
      return;
    }
    window.location.assign(window.location.origin + window.location.pathname);
  }

  function openHistory(item) {
    const panel = document.querySelector(".cx-history-panel");
    if (!panel) return;
    panel.querySelector(".cx-history-panel-title").textContent = item.title || "历史对话";
    panel.querySelector(".cx-history-panel-body").textContent =
      item.transcript || item.preview || "这个历史记录暂无内容。";
    panel.hidden = false;
  }

  function renderHistory() {
    const list = document.querySelector(".cx-history-list");
    if (!list) return;
    const items = readHistory();
    list.innerHTML = "";
    if (!items.length) {
      const empty = document.createElement("div");
      empty.className = "cx-history-empty";
      empty.textContent = "完成一次分析后，这里会自动保存本浏览器的最近对话。";
      list.appendChild(empty);
      return;
    }
    for (const item of items) {
      const button = document.createElement("button");
      button.className = "cx-history-item";
      button.type = "button";
      button.addEventListener("click", () => openHistory(item));

      const title = document.createElement("div");
      title.className = "cx-history-title";
      title.textContent = item.title || "未命名分析";

      const meta = document.createElement("div");
      meta.className = "cx-history-meta";
      meta.textContent = [formatTime(item.updatedAt), item.fileName].filter(Boolean).join(" · ");

      button.append(title, meta);
      list.appendChild(button);
    }
  }

  function installSidebar() {
    if (document.querySelector(".cx-sidebar")) return;
    document.documentElement.classList.add("cx-enhanced");

    const sidebar = document.createElement("aside");
    sidebar.className = "cx-sidebar";
    sidebar.innerHTML = `
      <div class="cx-brand">
        <div class="cx-brand-mark">CX</div>
        <div>
          <div class="cx-brand-title">ChatExcel</div>
          <div class="cx-brand-subtitle">数据处理与核对工作台</div>
        </div>
      </div>
      <button class="cx-new-chat" type="button">新开对话</button>
      <div class="cx-upload-hint">
        <strong>Excel 分析</strong>
        支持 .xlsx / .xlsm。上传后可继续追问，也可发送新文件切换数据。
      </div>
      <div class="cx-section-label">历史对话</div>
      <div class="cx-history-list"></div>
      <div class="cx-sidebar-footer">本机保存最近 30 条分析记录，用于快速回看问题、文件和结果摘要。</div>
    `;

    const panel = document.createElement("section");
    panel.className = "cx-history-panel";
    panel.hidden = true;
    panel.innerHTML = `
      <div class="cx-history-panel-header">
        <div class="cx-history-panel-title">历史对话</div>
        <button class="cx-close-panel" type="button" aria-label="关闭">×</button>
      </div>
      <div class="cx-history-panel-body"></div>
      <div class="cx-history-panel-actions">
        <button class="cx-secondary-action" type="button">关闭</button>
        <button class="cx-primary-action" type="button">新开对话</button>
      </div>
    `;

    document.body.prepend(sidebar);
    document.body.append(panel);

    sidebar.querySelector(".cx-new-chat").addEventListener("click", startNewChat);
    panel.querySelector(".cx-close-panel").addEventListener("click", () => {
      panel.hidden = true;
    });
    panel.querySelector(".cx-secondary-action").addEventListener("click", () => {
      panel.hidden = true;
    });
    panel.querySelector(".cx-primary-action").addEventListener("click", startNewChat);
    renderHistory();
  }

  function observeMessages() {
    let timer = 0;
    const root = document.querySelector("#root") || document.body;
    const observer = new MutationObserver(() => {
      classifyMessages();
      clearTimeout(timer);
      timer = window.setTimeout(saveSnapshot, 900);
    });
    observer.observe(root, { childList: true, subtree: true, characterData: true });
    classifyMessages();
    window.setTimeout(saveSnapshot, 1400);
  }

  function boot() {
    installSidebar();
    observeMessages();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot, { once: true });
  } else {
    boot();
  }
})();
