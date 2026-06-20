interface ReasoningCapsuleProps {
  reasoning?: { text: string; tokens: number } | null;
  open?: boolean;
}

export default function ReasoningCapsule({ reasoning, open }: ReasoningCapsuleProps) {
  if (!reasoning?.text) {
    return null;
  }
  return (
    <details className="reasoning" open={open}>
      <summary>
        <span className="dot" />
        <span className="label">思考过程</span>
        <span className="meta">{reasoning.tokens.toLocaleString("zh-CN")} tokens</span>
        <span className="chev">›</span>
      </summary>
      <div className="stream">
        <p>
          {reasoning.text}
          {open ? <span className="caret" /> : null}
        </p>
      </div>
    </details>
  );
}
