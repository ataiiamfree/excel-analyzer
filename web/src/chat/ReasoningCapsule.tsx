interface ReasoningCapsuleProps {
  reasoning?: { text: string; tokens: number } | null;
  active?: boolean;
}

const MAX_VISIBLE_REASONING_CHARS = 12_000;

export default function ReasoningCapsule({ reasoning, active }: ReasoningCapsuleProps) {
  if (!reasoning?.text) {
    return null;
  }
  const truncated = reasoning.text.length > MAX_VISIBLE_REASONING_CHARS;
  const visibleText = truncated
    ? reasoning.text.slice(-MAX_VISIBLE_REASONING_CHARS)
    : reasoning.text;
  return (
    <details className="reasoning">
      <summary>
        <span className="dot" />
        <span className="label">分析过程</span>
        <span className="meta">{active ? "正在更新" : "按需查看"}</span>
        <span className="chev">›</span>
      </summary>
      <div className="stream">
        {truncated ? <div className="reasoning-truncated">内容较长，仅显示最近片段</div> : null}
        <p>
          {visibleText}
          {active ? <span className="caret" /> : null}
        </p>
      </div>
    </details>
  );
}
