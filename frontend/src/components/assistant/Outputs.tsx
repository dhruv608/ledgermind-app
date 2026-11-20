"use client";

import { Download, FileSpreadsheet, FileText } from "lucide-react";
import {
  Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { assistantApi, type ChatChart, type ChatFileRef } from "@/lib/api/assistant";

/** What the assistant made in an answer: a chart drawn from its figures, and download cards for its files. */

const COLOURS = ["#226b6a", "#f59e0b", "#6366f1", "#e11d48"];

const money = (v: number) => {
  const a = Math.abs(v);
  const s = a >= 1_000_000 ? `${(a / 1_000_000).toFixed(1)}m` : a >= 10_000 ? `${Math.round(a / 1000)}k` : a.toLocaleString("en-GB", { maximumFractionDigits: 0 });
  return `${v < 0 ? "-" : ""}£${s}`;
};

export function ChartCard({ chart }: { chart: ChatChart }) {
  const data = chart.labels.map((label, i) => {
    const row: Record<string, string | number | null> = { label };
    chart.series.forEach((s, j) => { row[`s${j}`] = s.values[i]; });
    return row;
  });
  const fmt = (v: number) => (chart.unit === "£" ? money(v) : v.toLocaleString("en-GB"));
  const tip = (v: unknown) => (typeof v === "number"
    ? (chart.unit === "£" ? `£${v.toLocaleString("en-GB", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}` : v.toLocaleString("en-GB"))
    : String(v));
  const common = (
    <>
      <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" vertical={false} />
      <XAxis dataKey="label" tick={{ fontSize: 10.5, fill: "#64748b" }} tickLine={false} axisLine={{ stroke: "#cbd5e1" }}
             interval="preserveStartEnd" minTickGap={8} />
      <YAxis tickFormatter={fmt} tick={{ fontSize: 10.5, fill: "#64748b" }} tickLine={false} axisLine={false} width={52} />
      <Tooltip formatter={tip} contentStyle={{ fontSize: 12, borderRadius: 8, border: "1px solid #e2e8f0" }} />
      {chart.series.length > 1 && <Legend wrapperStyle={{ fontSize: 11 }} iconSize={8} />}
    </>
  );
  return (
    <div className="my-2 rounded-lg border border-slate-200 bg-slate-50/60 p-2.5">
      {chart.title && <p className="mb-1.5 px-1 text-xs font-semibold text-slate-700">{chart.title}</p>}
      <div className="h-52 w-full">
        <ResponsiveContainer width="100%" height="100%">
          {chart.type === "line" ? (
            <LineChart data={data} margin={{ top: 6, right: 8, left: 0, bottom: 0 }}>
              {common}
              {chart.series.map((s, j) => (
                <Line key={j} type="monotone" dataKey={`s${j}`} name={s.name} stroke={COLOURS[j % COLOURS.length]}
                      strokeWidth={2} dot={{ r: 2.5 }} activeDot={{ r: 4 }} connectNulls />
              ))}
            </LineChart>
          ) : (
            <BarChart data={data} margin={{ top: 6, right: 8, left: 0, bottom: 0 }}>
              {common}
              {chart.series.map((s, j) => (
                <Bar key={j} dataKey={`s${j}`} name={s.name} fill={COLOURS[j % COLOURS.length]} radius={[3, 3, 0, 0]} maxBarSize={28} />
              ))}
            </BarChart>
          )}
        </ResponsiveContainer>
      </div>
    </div>
  );
}

export function FileCard({ file }: { file: ChatFileRef }) {
  const excel = file.kind === "xlsx";
  const Icon = excel ? FileSpreadsheet : FileText;
  const size = file.size >= 1024 * 1024 ? `${(file.size / 1024 / 1024).toFixed(1)} MB` : `${Math.max(1, Math.round(file.size / 1024))} KB`;
  return (
    <a href={assistantApi.fileUrl(file.id)} download={file.name}
       className="group flex items-center gap-3 rounded-lg border border-slate-200 bg-white px-3 py-2.5 transition hover:border-teal-300 hover:shadow-sm">
      <span className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-lg ${excel ? "bg-emerald-50 text-emerald-700" : "bg-rose-50 text-rose-700"}`}>
        <Icon className="h-4.5 w-4.5" />
      </span>
      <span className="min-w-0 flex-1">
        <span className="block truncate text-[12.5px] font-medium text-slate-800" title={file.name}>{file.name}</span>
        <span className="text-[11px] text-slate-400">{excel ? "Excel" : "PDF"} · {size}</span>
      </span>
      <Download className="h-4 w-4 shrink-0 text-slate-400 transition group-hover:text-teal-700" />
    </a>
  );
}
