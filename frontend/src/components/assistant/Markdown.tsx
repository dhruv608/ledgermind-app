"use client";

import { Fragment, type ReactNode } from "react";

/** The assistant's answers: a small Markdown reader (headings, bold, italics, code, lists, tables, paragraphs),
 * built as React elements so nothing in the text is ever run as HTML. */

function inline(text: string, key = 0): ReactNode[] {
  const out: ReactNode[] = [];
  const re = /(\[[^\]]+\]\(https?:\/\/[^)\s]+\)|\*\*[^*]+\*\*|`[^`]+`|\*[^*\s][^*]*\*)/g;
  let last = 0;
  let m: RegExpExecArray | null;
  let i = key;
  while ((m = re.exec(text))) {
    if (m.index > last) out.push(text.slice(last, m.index));
    const t = m[0];
    const link = t.startsWith("[") ? /^\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)$/.exec(t) : null;
    if (link) {
      // A source the answer cites ([CTM61505](https://www.gov.uk/...)): opens in a new tab; only web links
      out.push(<a key={i++} href={link[2]} target="_blank" rel="noopener noreferrer"
                  className="font-medium text-teal-700 underline decoration-teal-300 underline-offset-2 hover:text-teal-900">{link[1]}</a>);
    } else if (t.startsWith("**")) out.push(<strong key={i++} className="font-semibold text-slate-900">{t.slice(2, -2)}</strong>);
    else if (t.startsWith("`")) out.push(<code key={i++} className="rounded bg-slate-100 px-1 py-0.5 text-[0.85em]">{t.slice(1, -1)}</code>);
    else out.push(<em key={i++}>{t.slice(1, -1)}</em>);
    last = m.index + t.length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

const cells = (row: string) => row.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map((c) => c.trim());
const isRule = (row: string) => /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/.test(row);
const numeric = (c: string) => /^[-(£$]*[\d,.]+%?\)?$/.test(c.replace(/\*\*/g, ""));

const ITEM = /^(\s*)([-*•]|\d+[.)])\s+/;

interface ListItem {
  indent: number;
  ordered: boolean;
  start: number;
  text: string;
  children: ListItem[];
}

/** Items in reading order into a tree: an item indented more than the one before it goes under it. */
function nest(items: ListItem[]): ListItem[] {
  const top: ListItem[] = [];
  const stack: ListItem[] = [];
  for (const it of items) {
    while (stack.length && stack[stack.length - 1].indent >= it.indent) stack.pop();
    (stack.length ? stack[stack.length - 1].children : top).push(it);
    stack.push(it);
  }
  return top;
}

function renderList(items: ListItem[], depth = 0): ReactNode {
  const ordered = items[0]?.ordered;
  const List = ordered ? "ol" : "ul";
  const marker = ordered ? "list-decimal" : depth > 0 ? "list-[circle]" : "list-disc";
  return (
    <List start={ordered && items[0].start > 1 ? items[0].start : undefined}
          className={`${depth ? "mt-1" : "my-1.5"} space-y-1 pl-5 ${marker} marker:text-slate-400`}>
      {items.map((it, j) => (
        <li key={j}>
          {inline(it.text)}
          {it.children.length > 0 && renderList(it.children, depth + 1)}
        </li>
      ))}
    </List>
  );
}

export function Markdown({ text }: { text: string }) {
  const lines = text.replace(/\r/g, "").split("\n");
  const blocks: ReactNode[] = [];
  let i = 0;
  let k = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (!line.trim()) {
      i++;
      continue;
    }
    // A table: a row of cells, a rule row, then rows
    if (line.includes("|") && i + 1 < lines.length && isRule(lines[i + 1])) {
      const head = cells(line);
      const rows: string[][] = [];
      i += 2;
      while (i < lines.length && lines[i].includes("|") && lines[i].trim()) rows.push(cells(lines[i++]));
      blocks.push(
        <div key={k++} className="my-2 overflow-x-auto rounded-lg border border-slate-200">
          <table className="w-full text-[12.5px]">
            <thead className="bg-slate-50">
              <tr>{head.map((h, j) => <th key={j} className="px-2.5 py-1.5 text-left font-semibold text-slate-700">{inline(h)}</th>)}</tr>
            </thead>
            <tbody>
              {rows.map((r, ri) => (
                <tr key={ri} className="border-t border-slate-100">
                  {r.map((c, j) => (
                    <td key={j} className={`px-2.5 py-1.5 align-top ${numeric(c) ? "whitespace-nowrap text-right tabular-nums" : ""}`}>{inline(c)}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>,
      );
      continue;
    }
    const h = /^(#{1,4})\s+(.*)$/.exec(line);
    if (h) {
      blocks.push(<p key={k++} className="mt-3 mb-1 font-semibold text-slate-900">{inline(h[2])}</p>);
      i++;
      continue;
    }
    // A list: '-', '*' or '1.' items; an indented item is a sub-point of the one above (its own list, so the
    // numbers of the outer list carry on), and an indented plain line continues the item above
    if (ITEM.test(line)) {
      const items: ListItem[] = [];
      while (i < lines.length) {
        if (!lines[i].trim()) {
          // A blank line between items keeps the list going (1. ... blank ... 2. stays one list)
          let next = i + 1;
          while (next < lines.length && !lines[next].trim()) next++;
          if (next < lines.length && ITEM.test(lines[next])) {
            i = next;
            continue;
          }
          break;
        }
        const m = ITEM.exec(lines[i]);
        if (m) items.push({ indent: m[1].length, ordered: /\d/.test(m[2]), start: parseInt(m[2], 10) || 1, text: lines[i].slice(m[0].length), children: [] });
        else if (/^\s{2,}\S/.test(lines[i]) && items.length) items[items.length - 1].text += " " + lines[i].trim();
        else break;
        i++;
      }
      blocks.push(<Fragment key={k++}>{renderList(nest(items))}</Fragment>);
      continue;
    }
    // A paragraph: lines up to the next blank line or block
    const para: string[] = [];
    while (i < lines.length && lines[i].trim() && !/^(#{1,4})\s/.test(lines[i]) && !/^\s*([-*•]|\d+[.)])\s+/.test(lines[i])
           && !(lines[i].includes("|") && i + 1 < lines.length && isRule(lines[i + 1]))) {
      para.push(lines[i++]);
    }
    blocks.push(
      <p key={k++} className="my-1.5">
        {para.map((p, j) => <Fragment key={j}>{j > 0 && <br />}{inline(p, j * 100)}</Fragment>)}
      </p>,
    );
  }
  return <div className="text-[13.5px] leading-relaxed text-slate-700">{blocks}</div>;
}
