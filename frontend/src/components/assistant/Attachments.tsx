"use client";

// Files attached to a question, as tiles: a small preview of the page or picture, the name and what
// happened to it (reading, pages read, could not be read), × on hover to take it off, a click to open it with what
// the assistant read from it beside it.
import { useEffect, useState } from "react";
import { AlertTriangle, Check, FileText, ImageIcon, Loader2, X } from "lucide-react";
import { Modal } from "@/components/ui/dialog";
import { assistantApi, type ChatUpload } from "@/lib/api/assistant";

export interface PendingFile {
  key: string;
  file: File;
  status: "reading" | "ready" | "error";
  upload?: ChatUpload;
  preview?: string;          // an object URL for a picture (shown at once, before it is read)
  error?: string;
}

const kb = (n: number) => (n >= 1024 * 1024 ? `${(n / 1024 / 1024).toFixed(1)} MB` : `${Math.max(1, Math.round(n / 1024))} KB`);

export function Tile({ name, thumb, image, line, tone, onRemove, onOpen, small = false }: {
  name: string; thumb?: string | null; image: boolean; line: React.ReactNode; tone: "muted" | "done" | "bad" | "busy";
  onRemove?: () => void; onOpen?: () => void; small?: boolean;
}) {
  const [broken, setBroken] = useState(false);
  const color = { muted: "text-slate-500", done: "text-teal-700", bad: "text-rose-600", busy: "text-slate-500" }[tone];
  return (
    <div className={`group relative shrink-0 overflow-hidden rounded-xl border border-slate-200 bg-white transition hover:border-slate-300 ${small ? "w-[112px]" : "w-[132px]"}`}>
      <button type="button" onClick={onOpen} disabled={!onOpen} title={onOpen ? `Open ${name}` : name}
              className="block w-full text-left disabled:cursor-default enabled:cursor-pointer">
        <div className={`relative overflow-hidden bg-slate-50 ${small ? "h-12" : "h-16"}`}>
          {thumb && !broken ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={thumb} alt="" onError={() => setBroken(true)} className="h-full w-full object-cover object-top" />
          ) : (
            <div className="flex h-full items-center justify-center text-slate-400">
              {image ? <ImageIcon className="h-5 w-5" /> : <FileText className="h-5 w-5" />}
            </div>
          )}
          {tone === "busy" && <div className="absolute inset-0 bg-white/50" />}
        </div>
        <div className="px-2 py-1.5">
          <p className="truncate text-[11px] font-semibold text-slate-800">{name}</p>
          <p className={`flex items-center gap-1 truncate text-[10.5px] ${color}`}>{line}</p>
        </div>
      </button>
      {onRemove && (
        <button type="button" onClick={onRemove} aria-label={`Remove ${name}`} title="Remove"
                className="absolute right-1 top-1 flex h-5 w-5 items-center justify-center rounded-full border border-slate-300 bg-white text-slate-500 opacity-0 shadow-sm transition hover:text-rose-600 group-hover:opacity-100 focus:opacity-100 cursor-pointer">
          <X className="h-3 w-3" />
        </button>
      )}
    </div>
  );
}

/** A file waiting to be sent: being read, read, or not readable */
export function PendingTile({ p, onRemove, onOpen }: { p: PendingFile; onRemove: () => void; onOpen: () => void }) {
  const u = p.upload;
  const thumb = p.preview || (u?.has_thumb ? assistantApi.uploadThumbUrl(u.id) : null);
  const image = p.file.type.startsWith("image/");
  if (p.status === "reading") {
    return <Tile name={p.file.name} thumb={thumb} image={image} tone="busy" onRemove={onRemove}
                 line={<><Loader2 className="h-3 w-3 animate-spin" /> Reading…</>} />;
  }
  if (p.status === "error" || !u) {
    return <Tile name={p.file.name} thumb={thumb} image={image} tone="bad" onRemove={onRemove}
                 line={<><AlertTriangle className="h-3 w-3" /> {p.error || "Not added"}</>} />;
  }
  return <UploadTile u={u} thumb={thumb} onRemove={onRemove} onOpen={onOpen} />;
}

export function UploadTile({ u, thumb, onRemove, onOpen, small }: {
  u: ChatUpload; thumb?: string | null; onRemove?: () => void; onOpen?: () => void; small?: boolean;
}) {
  const read = u.status === "READ";
  const line = read
    ? <><Check className="h-3 w-3" /> {u.pages > 1 ? `${u.pages} pages read` : u.image ? "Picture read" : "Read"}</>
    : <><AlertTriangle className="h-3 w-3" /> Can&apos;t be read</>;
  return <Tile name={u.name} thumb={thumb ?? (u.has_thumb ? assistantApi.uploadThumbUrl(u.id) : null)} image={u.image}
               tone={read ? "done" : "bad"} line={line} onRemove={onRemove} onOpen={onOpen} small={small} />;
}

/** The file itself beside what the assistant read from it, so a figure can be checked against the page */
export function UploadPreview({ upload, onClose }: { upload: ChatUpload | null; onClose: () => void }) {
  // The text read for this upload; null until it arrives (a new upload shows null again)
  const [loaded, setLoaded] = useState<{ upload: ChatUpload; text: string } | null>(null);
  const text = loaded && loaded.upload === upload ? loaded.text : null;
  useEffect(() => {
    if (upload) assistantApi.getUpload(upload.id).then((u) => setLoaded({ upload, text: u.text || "" }))
      .catch(() => setLoaded({ upload, text: "" }));
  }, [upload]);
  if (!upload) return null;
  const url = assistantApi.uploadFileUrl(upload.id);
  return (
    <Modal isOpen onClose={onClose} title={upload.name} className="max-w-6xl"
           description={`${upload.image ? "Picture" : "PDF"} · ${kb(upload.size)}${upload.pages > 1 ? ` · ${upload.pages} pages` : ""}`}>
      <div className="grid gap-4 pt-4 lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
        <div className="h-[65vh] overflow-hidden rounded-xl border border-slate-200 bg-slate-50">
          {upload.image ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={url} alt={upload.name} className="h-full w-full object-contain" />
          ) : (
            <iframe src={url} title={upload.name} className="h-full w-full" />
          )}
        </div>
        <div className="flex h-[65vh] flex-col overflow-hidden rounded-xl border border-slate-200">
          <p className="border-b border-slate-200 bg-slate-50 px-3 py-2 text-xs font-semibold text-slate-700">
            What the assistant read
            {upload.note && <span className="block font-normal text-amber-700">{upload.note}</span>}
          </p>
          <div className="flex-1 overflow-y-auto px-3 py-2">
            {text === null ? <p className="flex items-center gap-2 text-xs text-slate-400"><Loader2 className="h-3.5 w-3.5 animate-spin" /> Loading</p>
              : text ? <pre className="whitespace-pre-wrap font-mono text-[11.5px] leading-relaxed text-slate-700">{text}</pre>
              : <p className="text-xs text-slate-500">Nothing could be read from this file.</p>}
          </div>
        </div>
      </div>
    </Modal>
  );
}
