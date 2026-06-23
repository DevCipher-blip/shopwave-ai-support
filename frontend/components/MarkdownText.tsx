import { Fragment } from "react";
import { cn } from "@/lib/utils";

const INLINE = /(\*\*[^*]+\*\*|`[^`]+`|\bORD-\d+\b)/g;

function renderInline(text: string, inverted: boolean) {
  return text.split(INLINE).map((part, i) => {
    if (part.startsWith("**") && part.endsWith("**") && part.length > 4) {
      return <strong key={i} className="font-semibold">{part.slice(2, -2)}</strong>;
    }
    if (part.startsWith("`") && part.endsWith("`") && part.length > 2) {
      return (
        <code key={i} className={cn("rounded px-1 py-0.5 font-mono text-[0.85em]", inverted ? "bg-white/15" : "bg-paper")}>
          {part.slice(1, -1)}
        </code>
      );
    }
    if (/^ORD-\d+$/.test(part)) {
      return <span key={i} className="font-mono text-[0.92em] font-medium tracking-tight">{part}</span>;
    }
    return <Fragment key={i}>{part}</Fragment>;
  });
}

/** The small subset of Markdown the agent writes: paragraphs, "- " lists, **bold**, `code`. */
export function MarkdownText({ text, inverted = false }: { text: string; inverted?: boolean }) {
  const blocks: { list: boolean; lines: string[] }[] = [];
  for (const line of text.split("\n")) {
    const isItem = /^[-•]\s/.test(line);
    const content = isItem ? line.slice(2) : line;
    const last = blocks.at(-1);
    if (last && last.list === isItem && isItem) last.lines.push(content);
    else if (content.trim() || isItem) blocks.push({ list: isItem, lines: [content] });
  }

  return (
    <div className="space-y-2">
      {blocks.map((block, i) =>
        block.list ? (
          <ul key={i} className="list-disc space-y-0.5 pl-5 marker:text-muted">
            {block.lines.map((line, j) => <li key={j}>{renderInline(line, inverted)}</li>)}
          </ul>
        ) : (
          <p key={i}>{renderInline(block.lines.join(" "), inverted)}</p>
        )
      )}
    </div>
  );
}
