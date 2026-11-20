// The workbook's own look for the in-app preview: fills, fonts, borders, column widths, merged cells, the frozen title
// rows and tab colours, read from the file with ExcelJS (the free SheetJS build reads values only). The colours come
// from the file itself (written by the backend's workbook/look code): nothing here picks a colour, except the few
// conditional rules LM writes (applyConditional), which Excel works out on opening and the file does not store.
import type { CSSProperties } from "react";

export interface SheetLook {
  /** CSS per cell, keyed "row,col" (0-based) */
  cells: Map<string, CSSProperties>;
  /** Column widths in px (0-based) */
  widths: number[];
  /** Merged cells: the top-left "row,col" -> its span; covered cells are listed in `covered` */
  spans: Map<string, { rows: number; cols: number }>;
  covered: Set<string>;
  /** Rows frozen at the top (Excel's freeze panes) */
  frozenRows: number;
  tabColor: string | null;
  /** The rules Excel applies on opening, for applyConditional */
  rules: { keys: Set<string>; formula: string; style: CSSProperties }[];
  /** Cells whose number format shows negatives red ('[Red]') */
  redNegative: Set<string>;
}

const hex = (argb?: string): string | undefined => {
  if (!argb || typeof argb !== "string") return undefined;
  const v = argb.length === 8 ? argb.slice(2) : argb;
  return /^[0-9a-f]{6}$/i.test(v) ? `#${v}` : undefined;
};

const borderCss = (b: any): string | undefined => {
  if (!b || !b.style) return undefined;
  const colour = hex(b.color?.argb) || "#94a3b8";
  if (b.style === "double") return `3px double ${colour}`;
  if (b.style === "medium" || b.style === "thick") return `2px solid ${colour}`;
  if (b.style === "dashed" || b.style === "dotted") return `1px ${b.style} ${colour}`;
  return `1px solid ${colour}`;
};

/** A fill / font style as CSS. */
export function styleCss(style: any): CSSProperties {
  const css: CSSProperties = {};
  const fill = style?.fill;
  if (fill?.type === "pattern" && fill.pattern === "solid") {
    const bg = hex(fill.fgColor?.argb) || hex(fill.bgColor?.argb);
    if (bg) css.backgroundColor = bg;
  }
  const font = style?.font;
  if (font) {
    if (font.bold) css.fontWeight = 700;
    if (font.italic) css.fontStyle = "italic";
    if (font.underline) css.textDecoration = "underline";
    const c = hex(font.color?.argb);
    if (c) css.color = c;
    if (font.size) css.fontSize = `${Math.max(9, Math.min(22, Number(font.size)))}px`;
  }
  const a = style?.alignment;
  if (a?.horizontal && ["left", "center", "right"].includes(a.horizontal)) css.textAlign = a.horizontal;
  if (a?.wrapText) css.whiteSpace = "normal";
  const b = style?.border;
  if (b) {
    const t = borderCss(b.top), r = borderCss(b.right), bt = borderCss(b.bottom), l = borderCss(b.left);
    if (t) css.borderTop = t;
    if (r) css.borderRight = r;
    if (bt) css.borderBottom = bt;
    if (l) css.borderLeft = l;
  }
  return css;
}

const colIndex = (letters: string) => letters.split("").reduce((n, ch) => n * 26 + ch.charCodeAt(0) - 64, 0) - 1;
const parseRef = (ref: string): [number, number] | null => {
  const m = /^\$?([A-Z]{1,3})\$?(\d+)$/.exec(ref.trim());
  return m ? [Number(m[2]) - 1, colIndex(m[1])] : null;
};

/** Every cell of a range ('A1', 'B7:C9') as "row,col". */
export function rangeCells(range: string): string[] {
  const out: string[] = [];
  for (const part of range.split(/\s+/)) {
    const [a, b] = part.split(":");
    const p = parseRef(a), q = parseRef(b || a);
    if (!p || !q) continue;
    for (let r = Math.min(p[0], q[0]); r <= Math.max(p[0], q[0]); r++)
      for (let c = Math.min(p[1], q[1]); c <= Math.max(p[1], q[1]); c++) out.push(`${r},${c}`);
  }
  return out;
}

/** The look of one ExcelJS worksheet. */
export function readLook(ws: any): SheetLook {
  const cells = new Map<string, CSSProperties>();
  const redNegative = new Set<string>();
  ws.eachRow({ includeEmpty: true }, (row: any, r: number) => {
    row.eachCell({ includeEmpty: true }, (cell: any, c: number) => {
      const css = styleCss(cell.style);
      if (Object.keys(css).length) cells.set(`${r - 1},${c - 1}`, css);
      if (/\[red\]/i.test(cell.numFmt || "")) redNegative.add(`${r - 1},${c - 1}`);
    });
  });
  const widths: number[] = [];
  const count = Math.max(ws.columnCount || 0, ws.actualColumnCount || 0, 10);
  for (let c = 1; c <= count; c++) {
    const col = ws.getColumn(c);
    if (col.hidden) widths.push(0);
    else widths.push(Math.round(Math.max(4, Math.min(80, col.width || 9)) * 7 + 10));
  }
  const spans = new Map<string, { rows: number; cols: number }>();
  const covered = new Set<string>();
  for (const range of Object.keys(ws._merges || {})) {
    const m = ws._merges[range]?.model || ws._merges[range];
    const top = (m.top ?? 1) - 1, left = (m.left ?? 1) - 1, bottom = (m.bottom ?? 1) - 1, right = (m.right ?? 1) - 1;
    spans.set(`${top},${left}`, { rows: bottom - top + 1, cols: right - left + 1 });
    for (let r = top; r <= bottom; r++) for (let c = left; c <= right; c++) if (r !== top || c !== left) covered.add(`${r},${c}`);
  }
  const view = (ws.views || [])[0];
  const frozenRows = view && view.state === "frozen" ? Math.min(Number(view.ySplit || 0), 12) : 0;
  const rules: SheetLook["rules"] = [];
  for (const cf of ws.conditionalFormattings || []) {
    for (const rule of cf.rules || []) {
      const formula = (rule.formulae || [])[0];
      if (rule.type === "expression" && formula)
        rules.push({ keys: new Set(rangeCells(String(cf.ref))), formula: String(formula), style: styleCss(rule.style) });
    }
  }
  return { cells, widths, spans, covered, frozenRows, tabColor: hex(ws.properties?.tabColor?.argb) || null, rules,
           redNegative };
}

/** The text a cell shows, by its A1 reference (the preview's own rows). */
type TextAt = (ref: string) => string;

const number = (text: string): number | null => {
  const t = text.replace(/[£,\s▲▼]|change/g, "");
  if (!t) return 0;
  const neg = /^\(.*\)$/.test(t) || t.startsWith("-");
  const v = parseFloat(t.replace(/[()%-]/g, ""));
  if (Number.isNaN(v)) return null;
  const pct = t.endsWith("%") ? v / 100 : v;
  return neg ? -pct : pct;
};

/** Whether one of LM's conditional rules holds for the cell. The rules the backend writes (workbook/look): a chip's
 * LEFT(X,1)="✓" / "✗", the cover's LEFT(B7,5)="DRAFT", ISNUMBER(SEARCH("amber",B7)), B7="All checks agree", A0's
 * AND($B$3=0,$B$4=0) / $B$3>0 / AND($B$3=0,$B$4>0), and the variance AND(ISNUMBER($L$6),ABS($L$6)>0.2). Any other
 * rule is left off (the cell keeps its own colour). */
export function ruleHolds(formula: string, textAt: TextAt): boolean {
  const f = formula.replace(/^=/, "").replace(/\$/g, "").trim();
  let m = /^LEFT\(([A-Z]+\d+),(\d+)\)="(.*)"$/.exec(f);
  if (m) return textAt(m[1]).slice(0, Number(m[2])) === m[3];
  m = /^ISNUMBER\(SEARCH\("(.*)",([A-Z]+\d+)\)\)$/i.exec(f);
  if (m) return textAt(m[2]).toLowerCase().includes(m[1].toLowerCase());
  m = /^([A-Z]+\d+)="(.*)"$/.exec(f);
  if (m) return textAt(m[1]) === m[2];
  m = /^AND\(ISNUMBER\(([A-Z]+\d+)\),ABS\(\1\)>([\d.]+)\)$/.exec(f);
  if (m) {
    const v = number(textAt(m[1]));
    return textAt(m[1]).trim() !== "" && v !== null && Math.abs(v) > Number(m[2]);
  }
  const cmp = (expr: string): boolean | null => {
    const c = /^([A-Z]+\d+)([=<>]{1,2})(-?[\d.]+)$/.exec(expr);
    if (!c) return null;
    const v = number(textAt(c[1])) ?? 0, n = Number(c[3]);
    return c[2] === "=" ? v === n : c[2] === ">" ? v > n : c[2] === "<" ? v < n : c[2] === ">=" ? v >= n : c[2] === "<=" ? v <= n : null;
  };
  m = /^AND\((.*)\)$/.exec(f);
  if (m) {
    const parts = m[1].split(",").map(cmp);
    return parts.every((p) => p === true);
  }
  return cmp(f) === true;
}

/** The cell's style with the conditional rules that hold laid over it, and negatives red where the format says so. */
export function cellStyle(look: SheetLook, row: number, col: number, text: string, textAt: TextAt): CSSProperties {
  const key = `${row},${col}`;
  let css: CSSProperties = look.cells.get(key) || {};
  for (const rule of look.rules) {
    if (rule.keys.has(key) && ruleHolds(rule.formula, textAt)) css = { ...css, ...rule.style };
  }
  if (look.redNegative.has(key) && /^\(|^-/.test(text.trim())) css = { ...css, color: "#c00000" };
  return css;
}
