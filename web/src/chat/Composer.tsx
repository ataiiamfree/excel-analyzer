import { Paperclip, SendHorizontal } from "lucide-react";
import { KeyboardEvent, useState } from "react";

interface ComposerProps {
  disabled?: boolean;
  nextActions?: string[];
  onSend: (message: string) => void;
}

export default function Composer({ disabled, nextActions = [], onSend }: ComposerProps) {
  const [value, setValue] = useState("");

  const submit = () => {
    const message = value.trim();
    if (!message || disabled) return;
    onSend(message);
    setValue("");
  };

  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      submit();
    }
  };

  return (
    <div className="composer-wrap">
      {nextActions.length > 0 && !disabled ? (
        <div className="starter-row">
          {nextActions.map((action) => (
            <button className="starter" key={action} onClick={() => setValue(action)}>
              {action}
            </button>
          ))}
        </div>
      ) : null}
      <div className="composer">
        <textarea
          value={value}
          onChange={(event) => setValue(event.target.value)}
          onKeyDown={onKeyDown}
          placeholder="追问、上传新的 Excel，或继续描述需求...   按 Shift Return 换行"
          disabled={disabled}
        />
        <div className="composer-row">
          <button className="tool" title="附件" disabled>
            <Paperclip size={15} />
          </button>
          <span className="hint">Enter 发送 · Shift Enter 换行</span>
          <button className="send" onClick={submit} disabled={disabled || !value.trim()}>
            发送
            <SendHorizontal size={14} />
          </button>
        </div>
      </div>
    </div>
  );
}
