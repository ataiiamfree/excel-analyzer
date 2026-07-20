import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

interface ReportArticleProps {
  markdown: string;
}

function splitLeadSection(markdown: string) {
  const match = /(^|\n)#{2,3}\s+(最终答案|简要结论|分析结论|关键发现|排名结果(?:（从高到低）)?)\s*\n([\s\S]*?)(?=\n#{2,3}\s+|\s*$)/.exec(markdown);
  if (!match || match.index === undefined) {
    return { lead: "", body: markdown };
  }

  const body = `${markdown.slice(0, match.index)}${match[1]}${markdown.slice(match.index + match[0].length)}`.trim();
  return { lead: match[3].trim(), body };
}

export default function ReportArticle({ markdown }: ReportArticleProps) {
  const { lead, body } = splitLeadSection(markdown);
  return (
    <article className="report">
      <div className="kicker">分析报告 · ChatExcel</div>
      {lead ? (
        <section className="result-highlight">
          <div className="result-highlight-label">结论先行</div>
          <ReactMarkdown remarkPlugins={[remarkGfm]}>{lead}</ReactMarkdown>
        </section>
      ) : null}
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{body}</ReactMarkdown>
    </article>
  );
}
