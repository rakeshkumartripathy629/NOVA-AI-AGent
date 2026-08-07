import { Fragment, type ReactNode } from "react";

function safeUrl(url: string): string | undefined {
  try {
    const parsed = new URL(url, window.location.origin);
    if (
      parsed.protocol === "http:" ||
      parsed.protocol === "https:" ||
      parsed.protocol === "mailto:"
    ) {
      return parsed.href;
    }
  } catch {
    /* invalid url */
  }
  return undefined;
}

function parseInline(src: string, keyPrefix: string): ReactNode[] {
  const nodes: ReactNode[] = [];
  const pattern =
    /(\*\*([^*]+)\*\*)|(\*([^*]+)\*)|(`([^`]+)`)|(\[([^\]]+)\]\(([^)\s]+)\))/g;
  let last = 0;
  let i = 0;
  let m: RegExpExecArray | null;
  while ((m = pattern.exec(src)) !== null) {
    if (m.index > last) {
      nodes.push(
        <Fragment key={`${keyPrefix}-t${i}`}>{src.slice(last, m.index)}</Fragment>,
      );
    }
    if (m[2] !== undefined) {
      nodes.push(<strong key={`${keyPrefix}-b${i}`}>{m[2]}</strong>);
    } else if (m[4] !== undefined) {
      nodes.push(<em key={`${keyPrefix}-i${i}`}>{m[4]}</em>);
    } else if (m[6] !== undefined) {
      nodes.push(
        <code key={`${keyPrefix}-c${i}`} className="inline-code">
          {m[6]}
        </code>,
      );
    } else if (m[8] !== undefined && m[9] !== undefined) {
      const href = safeUrl(m[9]);
      nodes.push(
        <a
          key={`${keyPrefix}-l${i}`}
          href={href ?? m[9]}
          target="_blank"
          rel="noreferrer"
        >
          {m[8]}
        </a>,
      );
    }
    i += 1;
    last = pattern.lastIndex;
  }
  if (last < src.length) {
    nodes.push(
      <Fragment key={`${keyPrefix}-t${i}`}>{src.slice(last)}</Fragment>,
    );
  }
  return nodes;
}

function Heading({ level, children }: { level: number; children: ReactNode }) {
  switch (level) {
    case 1:
      return <h1>{children}</h1>;
    case 2:
      return <h2>{children}</h2>;
    case 3:
      return <h3>{children}</h3>;
    case 4:
      return <h4>{children}</h4>;
    case 5:
      return <h5>{children}</h5>;
    default:
      return <h6>{children}</h6>;
  }
}

function parseBlocks(src: string): ReactNode[] {
  const lines = src.replace(/\r\n/g, "\n").split("\n");
  const out: ReactNode[] = [];
  let i = 0;
  let key = 0;

  while (i < lines.length) {
    const line = lines[i];

    const fenceMatch = line.match(/^```(\w*)\s*$/);
    if (fenceMatch) {
      const buf: string[] = [];
      i += 1;
      while (i < lines.length && !/^```\s*$/.test(lines[i])) {
        buf.push(lines[i]);
        i += 1;
      }
      i += 1;
      out.push(
        <pre key={key++} className="code-block">
          <code>{buf.join("\n")}</code>
        </pre>,
      );
      continue;
    }

    if (/^\s*(---|\*\*\*)\s*$/.test(line)) {
      out.push(<hr key={key++} />);
      i += 1;
      continue;
    }

    const h = line.match(/^(#{1,6})\s+(.*)$/);
    if (h) {
      out.push(
        <Heading key={key++} level={h[1].length}>
          {parseInline(h[2], `h${key}`)}
        </Heading>,
      );
      i += 1;
      continue;
    }

    if (line.trimStart().startsWith(">")) {
      const buf: string[] = [];
      while (i < lines.length && lines[i].trimStart().startsWith(">")) {
        buf.push(lines[i].trimStart().replace(/^>\s?/, ""));
        i += 1;
      }
      out.push(<blockquote key={key++}>{parseBlocks(buf.join("\n"))}</blockquote>);
      continue;
    }

    if (/^\s*[-*+]\s+/.test(line)) {
      const items: string[] = [];
      while (i < lines.length && /^\s*[-*+]\s+/.test(lines[i])) {
        items.push(lines[i].replace(/^\s*[-*+]\s+/, ""));
        i += 1;
      }
      out.push(
        <ul key={key++}>
          {items.map((it, idx) => (
            <li key={idx}>{parseInline(it, `ul${key}-${idx}`)}</li>
          ))}
        </ul>,
      );
      continue;
    }

    if (/^\s*\d+\.\s+/.test(line)) {
      const items: string[] = [];
      while (i < lines.length && /^\s*\d+\.\s+/.test(lines[i])) {
        items.push(lines[i].replace(/^\s*\d+\.\s+/, ""));
        i += 1;
      }
      out.push(
        <ol key={key++}>
          {items.map((it, idx) => (
            <li key={idx}>{parseInline(it, `ol${key}-${idx}`)}</li>
          ))}
        </ol>,
      );
      continue;
    }

    const buf: string[] = [];
    while (
      i < lines.length &&
      lines[i].trim() !== "" &&
      !/^#{1,6}\s+/.test(lines[i]) &&
      !/^```/.test(lines[i]) &&
      !/^\s*[-*+]\s+/.test(lines[i]) &&
      !/^\s*\d+\.\s+/.test(lines[i]) &&
      !lines[i].trimStart().startsWith(">") &&
      !/^\s*(---|\*\*\*)\s*$/.test(lines[i])
    ) {
      buf.push(lines[i]);
      i += 1;
    }
    if (buf.length > 0) {
      const joined = buf.join("\n").replace(/\n/g, " ");
      if (joined.trim() !== "") {
        out.push(<p key={key++}>{parseInline(joined, `p${key}`)}</p>);
      }
    } else {
      i += 1;
    }
  }
  return out;
}

export default function Markdown({ text }: { text: string }) {
  return <>{parseBlocks(text)}</>;
}
