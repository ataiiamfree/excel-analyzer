import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

interface ReportArticleProps {
  markdown: string;
}

export default function ReportArticle({ markdown }: ReportArticleProps) {
  return (
    <article className="report">
      <div className="kicker">分析报告 · ChatExcel</div>
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{markdown}</ReactMarkdown>
    </article>
  );
}
