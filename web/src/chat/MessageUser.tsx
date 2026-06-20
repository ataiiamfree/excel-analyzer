import type { UserMessagePayload } from "../api/types";

interface MessageUserProps {
  payload: UserMessagePayload;
}

function formatSize(size?: number | null) {
  if (!size) return "";
  if (size > 1024 * 1024) return `${(size / 1024 / 1024).toFixed(1)} MB`;
  return `${Math.ceil(size / 1024)} KB`;
}

export default function MessageUser({ payload }: MessageUserProps) {
  return (
    <div className="msg user">
      <div className="bubble">
        {payload.attached_file?.name ? (
          <div className="attach">
            <span className="icon">X</span>
            <span>{payload.attached_file.name}</span>
            <span className="size">{formatSize(payload.attached_file.size)}</span>
          </div>
        ) : null}
        {payload.text}
      </div>
    </div>
  );
}
