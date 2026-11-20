// The assistant panel's state: open, size and full screen, the client on the page, the chat and its messages,
// attached files, and sending a question with the live answer as it streams in.

import { useCallback, useEffect, useRef, useState } from "react";
import { usePathname } from "next/navigation";
import { api } from "@/lib/api";
import { assistantApi, type ChatEvent, type ChatMessage } from "@/lib/api/assistant";
import { signedInEmail } from "@/lib/auth";
import type { PendingFile } from "../Attachments";
import type { ChatChart, ChatFileRef, ChatSource, ChatUpload } from "@/lib/api/assistant";
import {
  DEFAULT_W, FILE_TYPES, FULL_KEY, MAX_FILES, MAX_MB, MIN_W, PAGE_ROOM, SIDE_KEY, WIDTH_KEY, clientIdOf, readFlag,
  readWidth, saveFlag,
} from "./constants";
import { fmtYE } from "./time";

export function useAssistantPanel(standalone: boolean) {
  const pathname = usePathname();
  const clientId = standalone ? null : clientIdOf(pathname);
  const [signedIn, setSignedIn] = useState(standalone);
  const [open, setOpen] = useState(standalone);
  // Bumped after each answer, so the cost meter reads the new totals
  const [meterTick, setMeterTick] = useState(0);
  const name = standalone ? "LedgerMind Chat" : "Ledge";
  const [width, setWidth] = useState(DEFAULT_W);
  // Over the page (narrow screens) or beside it (wide ones); worked out again when the window is resized
  const [over, setOver] = useState(false);
  const [view, setView] = useState<"chat" | "history">("chat");
  // Full screen (like a video's full-screen button): the chats in a left sidebar that folds away
  const [full, setFull] = useState(standalone);
  const [side, setSide] = useState(true);
  const [client, setClient] = useState<{ name: string; ye: string } | null>(null);

  const [chatId, setChatId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [liveFiles, setLiveFiles] = useState<ChatFileRef[]>([]);
  const [liveCharts, setLiveCharts] = useState<ChatChart[]>([]);
  const [liveSources, setLiveSources] = useState<ChatSource[]>([]);
  const [streamText, setStreamText] = useState("");
  const [liveSteps, setLiveSteps] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState<PendingFile[]>([]);
  const [previewing, setPreviewing] = useState<ChatUpload | null>(null);
  const [dragging, setDragging] = useState(false);
  const [fileNote, setFileNote] = useState<string | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const abort = useRef<AbortController | null>(null);
  const scroller = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    // The test chat page has its own panel (opened with the code): the app's one stays off there
    // eslint-disable-next-line react-hooks/set-state-in-effect -- the sign-in is only readable in the browser, after mount
    setSignedIn(standalone || (!!signedInEmail() && pathname !== "/login" && !(pathname || "").startsWith("/chat")));
  }, [pathname, standalone]);
  useEffect(() => {
    // Saved sizes live in the browser's storage, so they are read after mount (the server render has none)
    // eslint-disable-next-line react-hooks/set-state-in-effect -- browser-only values, read once after mount
    setWidth(readWidth());
    setFull(standalone || readFlag(FULL_KEY, false));
    // On a phone the chat page starts with the chats folded away
    setSide(standalone && window.innerWidth < 768 ? false : readFlag(SIDE_KEY, true));
  }, [standalone]);
  const toggleFull = () => { if (!standalone) setFull((v) => { saveFlag(FULL_KEY, !v); return !v; }); };
  const toggleSide = () => setSide((v) => { saveFlag(SIDE_KEY, !v); return !v; });

  // Seconds since the question was sent, so a long answer never looks stuck
  useEffect(() => {
    if (!busy) return;
    const start = Date.now();
    const t = setInterval(() => setElapsed(Math.floor((Date.now() - start) / 1000)), 1000);
    return () => clearInterval(t);
  }, [busy]);

  // Ctrl+K / Cmd+K opens and closes; Esc closes
  useEffect(() => {
    if (standalone) return;                   // the chat page is the page: nothing to open or close
    const key = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setOpen((v) => !v);
      } else if (e.key === "Escape" && open) {
        // Out of full screen first, then closed
        if (full) {
          setFull(false);
          saveFlag(FULL_KEY, false);
        } else setOpen(false);
      }
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [open, full, standalone]);

  // The whole page (top bar included) moves aside for the panel only when it keeps enough room; otherwise the panel
  // opens over it (on a laptop the page would squeeze to a word a line)
  useEffect(() => {
    const place = () => {
      const beside = window.innerWidth - width >= PAGE_ROOM;
      setOver(!beside);
      document.body.style.paddingRight = open && signedIn && beside && !full ? `${width}px` : "";
    };
    document.body.style.transition = "padding-right 200ms ease";
    place();
    window.addEventListener("resize", place);
    return () => {
      window.removeEventListener("resize", place);
      document.body.style.paddingRight = "";
    };
  }, [open, width, signedIn, full]);

  // The client open on the page: its name and year end for the chip; a new chat when it changes
  const [prevClient, setPrevClient] = useState({ clientId, signedIn });
  if (prevClient.clientId !== clientId || prevClient.signedIn !== signedIn) {
    setPrevClient({ clientId, signedIn });
    setChatId(null);
    setMessages([]);
    setError(null);
    setView("chat");
    setClient(null);
  }
  useEffect(() => {
    let alive = true;
    if (!clientId || !signedIn) return;
    const load = (retry: boolean) => api.listClients().then((list) => {
      const c = list.find((x) => x.engagement_id === clientId);
      if (!alive) return;
      if (c) setClient({ name: c.client_name, ye: fmtYE(c.period_end_date) });
      else if (retry) setTimeout(() => load(false), 3000);
    });
    load(true);
    return () => {
      alive = false;
    };
  }, [clientId, signedIn]);

  useEffect(() => {
    if (open && view === "chat") setTimeout(() => input.current?.focus(), 50);
  }, [open, view, chatId]);

  useEffect(() => {
    const el = scroller.current;
    if (el && el.scrollHeight - el.scrollTop - el.clientHeight < 160) el.scrollTop = el.scrollHeight;
  }, [messages, streamText, liveSteps]);

  // Attach files: each is read straight away (its tile says Reading…, then what was read)
  const pendingRef = useRef<PendingFile[]>([]);
  useEffect(() => { pendingRef.current = pending; }, [pending]);
  const addFiles = useCallback((list: FileList | File[]) => {
    const files = Array.from(list);
    if (!files.length) return;
    const room = MAX_FILES - pendingRef.current.length;
    setFileNote(files.length > room ? `Up to ${MAX_FILES} files with a question.` : null);
    const added: PendingFile[] = files.slice(0, Math.max(room, 0)).map((file) => {
      const bad = !FILE_TYPES.includes(file.type) ? "PDF or picture only"
        : file.size > MAX_MB * 1024 * 1024 ? `Over ${MAX_MB} MB` : null;
      return { key: `${Date.now()}-${Math.random()}`, file, status: bad ? "error" : "reading", error: bad || undefined,
               preview: file.type.startsWith("image/") ? URL.createObjectURL(file) : undefined };
    });
    if (!added.length) return;
    setPending((cur) => [...cur, ...added]);
    // Read on the server now, outside the state update (React may run an updater twice)
    for (const p of added.filter((x) => x.status === "reading")) {
      assistantApi.upload(p.file)
        .then((u) => setPending((all) => all.map((x) => (x.key === p.key ? { ...x, status: "ready", upload: u } : x))))
        .catch((e) => setPending((all) => all.map((x) => (x.key === p.key ? { ...x, status: "error", error: (e as Error).message } : x))));
    }
  }, []);

  const removePending = (key: string) => {
    setPending((all) => {
      const p = all.find((x) => x.key === key);
      if (p?.upload) assistantApi.removeUpload(p.upload.id).catch(() => undefined);
      if (p?.preview) URL.revokeObjectURL(p.preview);
      return all.filter((x) => x.key !== key);
    });
    setFileNote(null);
  };

  const send = useCallback(async (text: string) => {
    const ready = pending.filter((p) => p.status === "ready" && p.upload).map((p) => p.upload as ChatUpload);
    const q = text.trim() || (ready.length ? "Please read the attached file(s) and tell me what they show." : "");
    if (!q || busy) return;
    if (pending.some((p) => p.status === "reading")) {
      setFileNote("Wait until the files are read.");
      return;
    }
    setError(null);
    setFileNote(null);
    setDraft("");
    if (input.current) input.current.style.height = "";
    setBusy(true);
    setElapsed(0);
    setStreamText("");
    setLiveSteps([]);
    setLiveFiles([]);
    setLiveCharts([]);
    setLiveSources([]);
    setMessages((m) => [...m, { id: `u${Date.now()}`, role: "user", content: q, steps: [], created_at: new Date().toISOString(),
                                suggestions: ready.length ? { attachments: ready } : {} }]);
    pending.forEach((p) => p.preview && URL.revokeObjectURL(p.preview));
    setPending([]);
    setTimeout(() => { if (scroller.current) scroller.current.scrollTop = scroller.current.scrollHeight; }, 0);
    const ctrl = new AbortController();
    abort.current = ctrl;
    try {
      let id = chatId;
      if (!id) {
        id = (await assistantApi.newChat(clientId)).id;
        setChatId(id);
      }
      let text = "";
      // The page open now (?tab=area&area=vat), read when the message is sent
      const params = new URLSearchParams(window.location.search);
      const context = { tab: params.get("tab"), area: params.get("area") };
      await assistantApi.send(id, q, (e: ChatEvent) => {
        if (e.type === "delta") {
          text += e.text;
          setStreamText(text);
        } else if (e.type === "reset") {
          text = "";
          setStreamText("");
        } else if (e.type === "status") {
          setLiveSteps((s) => [...s, e.text]);
        } else if (e.type === "file") {
          setLiveFiles((f) => [...f, e.file]);
        } else if (e.type === "chart") {
          setLiveCharts((c) => [...c, e.chart]);
        } else if (e.type === "sources") {
          setLiveSources((x) => [...x, ...e.sources]);
        } else if (e.type === "done") {
          setMessages((m) => [...m, e.message]);
          setStreamText("");
          setLiveSteps([]);
          setLiveFiles([]);
          setLiveCharts([]);
          setLiveSources([]);
        } else if (e.type === "error") {
          setError(e.text);
        }
      }, ctrl.signal, context, ready.map((u) => u.id));
    } catch (err) {
      if ((err as Error).name !== "AbortError") setError((err as Error).message);
    } finally {
      setBusy(false);
      setStreamText("");
      setLiveSteps([]);
      setLiveFiles([]);
      setLiveCharts([]);
      setLiveSources([]);
      abort.current = null;
      setMeterTick((n) => n + 1);
    }
  }, [busy, chatId, clientId, pending]);

  // "Explain" on a point card: the panel opens and asks it
  const sendRef = useRef(send);
  useEffect(() => { sendRef.current = send; }, [send]);
  useEffect(() => {
    const ask = (e: Event) => {
      const text = (e as CustomEvent<string>).detail;
      if (!text) return;
      setOpen(true);
      setView("chat");
      sendRef.current(text);
    };
    window.addEventListener("assistant-ask", ask);
    return () => window.removeEventListener("assistant-ask", ask);
  }, []);

  const stop = () => abort.current?.abort();

  const newChat = () => {
    if (busy) stop();
    setChatId(null);
    setMessages([]);
    setError(null);
    setView("chat");
  };

  const openChat = async (id: string) => {
    setView("chat");
    setError(null);
    try {
      const c = await assistantApi.getChat(id);
      setChatId(c.id);
      setMessages(c.messages);
    } catch (err) {
      setError((err as Error).message);
    }
  };

  // Drag the left edge to resize
  const startResize = (e: React.MouseEvent) => {
    e.preventDefault();
    const move = (ev: MouseEvent) => {
      const w = Math.min(Math.max(window.innerWidth - ev.clientX, MIN_W), Math.round(window.innerWidth * 0.6));
      setWidth(w);
    };
    const up = () => {
      document.removeEventListener("mousemove", move);
      document.removeEventListener("mouseup", up);
      document.body.style.userSelect = "";
      setWidth((w) => {
        try { window.localStorage.setItem(WIDTH_KEY, String(w)); } catch { /* not saved */ }
        return w;
      });
    };
    document.body.style.userSelect = "none";
    document.addEventListener("mousemove", move);
    document.addEventListener("mouseup", up);
  };

  return {
    signedIn, open, setOpen, meterTick, name, width, over, view, setView, full, side, setSide, client, clientId,
    chatId, messages, setMessages, draft, setDraft, busy, elapsed, liveFiles, liveCharts, liveSources, streamText,
    liveSteps, error, pending, previewing, setPreviewing, dragging, setDragging, fileNote, setFileNote, fileInput,
    scroller, input, toggleFull, toggleSide, addFiles, removePending, send, stop, newChat, openChat, startResize,
  };
}
