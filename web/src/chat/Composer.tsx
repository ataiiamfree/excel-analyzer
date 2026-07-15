import { LoaderCircle, Paperclip, SendHorizontal, Square } from "lucide-react";
import { ChangeEvent, KeyboardEvent, useRef, useState } from "react";

interface ComposerProps {
  disabled?: boolean;
  running?: boolean;
  attaching?: boolean;
  nextActions?: string[];
  notice?: string;
  onSend: (message: string) => void;
  onCancel?: () => void;
  onAttach?: (file: File) => Promise<unknown>;
  onReconnect?: () => void;
  reconnectAvailable?: boolean;
}

export default function Composer({
  disabled,
  running,
  attaching,
  nextActions = [],
  notice,
  onSend,
  onCancel,
  onAttach,
  onReconnect,
  reconnectAvailable
}: ComposerProps) {
  const [value, setValue] = useState("");
  const inputRef = useRef<HTMLInputElement | null>(null);

  const submit = () => {
    const message = value.trim();
    if (!message || disabled) return;
    onSend(message);
    setValue("");
  };

  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      submit();
    }
  };

  const attachFile = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file || !onAttach) return;
    try {
      await onAttach(file);
    } catch {
      // The parent surfaces the API error in the composer notice.
    }
  };

  return (
    <div className="composer-wrap">
      {nextActions.length > 0 && !disabled && !running ? (
        <div className="starter-row">
          {nextActions.map((action) => (
            <button className="starter" key={action} onClick={() => setValue(action)}>
              {action}
            </button>
          ))}
        </div>
      ) : null}
      {notice ? (
        <div className="composer-notice" role="status">
          <span>{notice}</span>
          {reconnectAvailable && onReconnect ? (
            <button onClick={onReconnect}>重连</button>
          ) : null}
        </div>
      ) : null}
      <div className="composer">
        <textarea
          value={value}
          onChange={(event) => setValue(event.target.value)}
          onKeyDown={onKeyDown}
          placeholder="追问、上传新的 Excel，或继续描述需求...   按 Shift Return 换行"
          disabled={disabled || running || attaching}
        />
        <div className="composer-row">
          <input
            ref={inputRef}
            type="file"
            accept=".xlsx,.xlsm"
            hidden
            onChange={attachFile}
          />
          <button
            className="tool"
            title="替换当前 Excel"
            onClick={() => inputRef.current?.click()}
            disabled={disabled || running || attaching || !onAttach}
          >
            {attaching ? <LoaderCircle className="spin-icon" size={15} /> : <Paperclip size={15} />}
          </button>
          <span className="hint">Enter 发送 · Shift Enter 换行</span>
          {running ? (
            <button className="send stop" onClick={onCancel} disabled={!onCancel}>
              停止
              <Square size={13} fill="currentColor" />
            </button>
          ) : (
            <button className="send" onClick={submit} disabled={disabled || attaching || !value.trim()}>
              发送
              <SendHorizontal size={14} />
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
