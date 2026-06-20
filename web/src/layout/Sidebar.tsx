import { Link, useNavigate } from "react-router-dom";
import { Plus, Search, Settings, Star } from "lucide-react";
import { useMemo, useState } from "react";

import type { ConversationGroup } from "../api/types";

interface SidebarProps {
  activeId?: string;
  groups: ConversationGroup[];
}

function formatTime(value: string) {
  const date = new Date(value);
  return date.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" });
}

export default function Sidebar({ activeId, groups }: SidebarProps) {
  const [query, setQuery] = useState("");
  const navigate = useNavigate();
  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) {
      return groups;
    }
    return groups
      .map((group) => ({
        ...group,
        conversations: group.conversations.filter((item) =>
          `${item.title} ${item.file_name ?? ""}`.toLowerCase().includes(q)
        )
      }))
      .filter((group) => group.conversations.length > 0);
  }, [groups, query]);

  return (
    <aside className="sidebar">
      <div className="brand">
        <div className="brand-mark" />
        <div>
          <div className="brand-name">
            Chat<em>Excel</em>
          </div>
          <div className="brand-meta">Web Analyst</div>
        </div>
      </div>

      <button className="compose-new" onClick={() => navigate("/")}>
        <Plus size={16} />
        <span>新建分析</span>
        <kbd>N</kbd>
      </button>

      <label className="search">
        <span className="sr-only">搜索会话</span>
        <Search size={14} style={{ position: "absolute", opacity: 0 }} />
        <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索会话..." />
      </label>

      <div className="chat-list">
        {filtered.map((group) => (
          <div key={group.label}>
            <div className="nav-section">
              <span>{group.label}</span>
              <span className="rule" />
              <span>{group.conversations.length}</span>
            </div>
            {group.conversations.map((conversation) => (
              <Link
                key={conversation.id}
                to={`/c/${conversation.id}`}
                className={`chat-item ${conversation.id === activeId ? "active" : ""}`}
              >
                <div className="title">{conversation.title}</div>
                <div className="meta">
                  {conversation.file_name ? <span className="file-chip">{conversation.file_name}</span> : null}
                  <span>{formatTime(conversation.updated_at)}</span>
                  {conversation.starred ? <Star className="star" size={12} fill="currentColor" /> : null}
                </div>
              </Link>
            ))}
          </div>
        ))}
        {filtered.length === 0 ? (
          <div className="nav-section">
            <span>无匹配</span>
            <span className="rule" />
          </div>
        ) : null}
      </div>

      <div className="user-card">
        <div className="avatar">NX</div>
        <div className="user-meta">
          <span className="name">Natalia X.</span>
          <span className="plan">Local · API</span>
        </div>
        <button className="gear" title="设置">
          <Settings size={15} />
        </button>
      </div>
    </aside>
  );
}
