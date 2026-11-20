"use client";

import { LedgeMark } from "@/components/assistant/LedgeMark";
import {
  ArrowRight, ArrowUp, History, Maximize2, MessageSquarePlus, Minimize2, PanelLeftClose, PanelLeftOpen,
  Paperclip, Square, X,
} from "lucide-react";
import { Markdown } from "./Markdown";
import { ChartCard, FileCard } from "./Outputs";
import { PendingTile, UploadPreview } from "./Attachments";
import { VoiceButton } from "./Voice";
import { CostMeter } from "./CostMeter";
import { CAN_CLIENT, CAN_NONE, FILE_TYPES, MAX_FILES, STARTERS_CLIENT, STARTERS_NONE } from "./assistant-panel/constants";
import { dayLabel } from "./assistant-panel/time";
import { Message, Sources } from "./assistant-panel/Message";
import { HistoryList } from "./assistant-panel/HistoryList";
import { useAssistantPanel } from "./assistant-panel/useAssistantPanel";

/** The assistant: a round button bottom-right (or Ctrl+K) opens a panel on the right; the page shrinks beside it.
 * It knows the client open on the page, keeps old chats per client, shows each step it takes, and suggests the
 * next questions. */

/** standalone: the test chat page (/chat), opened with a code instead of a sign-in. Always open and full screen (no
 * close, full-screen or client buttons), never about a client, with the cost meter at the foot of the sidebar. */
export function AssistantPanel({ standalone = false }: { standalone?: boolean } = {}) {
  const {
    signedIn, open, setOpen, meterTick, name, width, over, view, setView, full, side, setSide, client, clientId,
    chatId, messages, setMessages, draft, setDraft, busy, elapsed, liveFiles, liveCharts, liveSources, streamText,
    liveSteps, error, pending, previewing, setPreviewing, dragging, setDragging, fileNote, setFileNote, fileInput,
    scroller, input, toggleFull, toggleSide, addFiles, removePending, send, stop, newChat, openChat, startResize,
  } = useAssistantPanel(standalone);

  if (!signedIn) return null;

  const last = messages[messages.length - 1];
  // The client comes from the page address; its name is only for the labels (it may not have loaded)
  const clientName = client?.name ?? (clientId ? "this client" : null);
  const shownStream = streamText.replace(/<(followups|options)>[\s\S]*$/, "").replace(/<\s*[｜|]\s*DSML[\s\S]*$/, "").trim();

  // The messages and the box to type in: the panel's body, or the main column in full screen. Answers are plain text
  // on white, the accountant's questions in a soft bubble on the right.
  const col = full ? "mx-auto w-full max-w-3xl" : "";
  const chatArea = (
    <>
      <div ref={scroller} className="lm-scroll flex-1 overflow-y-auto">
        <div className={`px-5 py-6 ${col}`}>
          {messages.length === 0 && !busy && (
            <div className="flex min-h-[40vh] flex-col items-center justify-center text-center">
              <span className="flex h-12 w-12 items-center justify-center rounded-2xl bg-teal-700 text-white shadow-sm">
                <LedgeMark className="h-7 w-7" />
              </span>
              <p className="mt-4 text-[22px] font-semibold tracking-tight text-slate-900">
                {standalone ? "Hi. Here's what I can do" : clientName ? `Hi, I'm Ledge. Ask me about ${clientName}` : "Hi, I'm Ledge. Here's what I can do"}
              </p>
              {/* What Ledge can do, every time a chat starts empty */}
              <div className={`mt-5 grid w-full gap-2 text-left ${full ? "sm:grid-cols-2" : ""}`}>
                {(clientId ? CAN_CLIENT : CAN_NONE).map(({ icon: Icon, title, sub }) => (
                  <div key={title} className="flex items-start gap-3 rounded-xl border border-slate-200 bg-slate-50/60 px-3.5 py-2.5">
                    <Icon className="mt-0.5 h-[18px] w-[18px] shrink-0 text-teal-700" />
                    <span>
                      <span className="block text-[13px] font-medium text-slate-800">{title}</span>
                      <span className="block text-[12px] text-slate-500">{sub}</span>
                    </span>
                  </div>
                ))}
              </div>
              <p className="mt-5 text-[12px] text-slate-400">Try one of these</p>
              <div className={`mt-2 grid w-full gap-2 ${full ? "sm:grid-cols-2" : ""}`}>
                {(clientId ? STARTERS_CLIENT : STARTERS_NONE).map((q) => (
                  <button key={q} type="button" onClick={() => send(q)}
                          className="rounded-xl border border-slate-200 px-3.5 py-2.5 text-left text-[13px] text-slate-700 transition hover:border-teal-300 hover:bg-teal-50/50 cursor-pointer">
                    {q}
                  </button>
                ))}
              </div>
              <p className="mt-4 text-[11.5px] text-slate-400">
                {standalone ? "Answers come from UK tax law and HMRC guidance. No client files here."
                  : "Ledge reads and explains. It does not change figures in a client file."}
              </p>
            </div>
          )}

          <div className="space-y-7">
            {messages.map((m, i) => {
              const day = m.created_at ? dayLabel(m.created_at) : null;
              const before = i > 0 ? messages[i - 1].created_at : null;
              const newDay = day && (before ? dayLabel(before) !== day : day !== "Today");
              return (
                <div key={m.id}>
                  {newDay && (
                    <div className="mb-6 flex items-center gap-3 text-[11px] font-medium text-slate-400">
                      <span className="h-px flex-1 bg-slate-100" />{day}<span className="h-px flex-1 bg-slate-100" />
                    </div>
                  )}
                  <Message m={m} onOpenFile={setPreviewing} showCost={standalone}
                           onUpdated={(n) => setMessages((all) => all.map((x) => (x.id === n.id ? n : x)))} />
                </div>
              );
            })}
            {busy && (
              <div>
                <p className="mb-2 flex items-center gap-2 text-[12.5px] text-slate-500">
                  <span className="lm-shimmer font-medium">
                    {shownStream ? "Writing" : liveSteps.length ? liveSteps[liveSteps.length - 1] : "Thinking"}
                  </span>
                  <span className="tabular-nums text-slate-400">{elapsed}s</span>
                </p>
                {liveCharts.map((c, i) => <ChartCard key={i} chart={c} />)}
                {liveFiles.map((f) => <FileCard key={f.id} file={f} />)}
                {shownStream && <div className="text-[14px]"><Markdown text={shownStream} /></div>}
                <Sources sources={liveSources} />
              </div>
            )}
            {error && <p className="rounded-xl bg-rose-50 px-3.5 py-2.5 text-[13px] text-rose-700">{error}</p>}
          </div>

          {/* A question for a missing fact, and what to ask next, under the last answer */}
          {!busy && last?.role === "assistant" && (
            <div className="mt-5 space-y-3">
              {last.suggestions?.options && (
                <div>
                  <p className="mb-2 text-[13px] text-slate-700">{last.suggestions.options.question}</p>
                  <div className="flex flex-wrap gap-2">
                    {last.suggestions.options.choices.map((c) => (
                      <button key={c} type="button" onClick={() => send(c)}
                              className="rounded-full border border-teal-300 bg-teal-50 px-3.5 py-1.5 text-[12.5px] font-medium text-teal-800 transition hover:bg-teal-100 cursor-pointer">
                        {c}
                      </button>
                    ))}
                  </div>
                </div>
              )}
              {(last.suggestions?.followups || []).length > 0 && (
                <div className="flex flex-col items-start gap-1.5">
                  {(last.suggestions?.followups || []).map((q) => (
                    <button key={q} type="button" onClick={() => send(q)}
                            className="group inline-flex max-w-full items-center gap-1.5 rounded-full border border-slate-200 px-3 py-1.5 text-left text-[12.5px] text-slate-600 transition hover:border-slate-300 hover:bg-slate-50 hover:text-slate-900 cursor-pointer">
                      <ArrowRight className="h-3.5 w-3.5 shrink-0 text-slate-400 group-hover:text-teal-600" />
                      <span className="truncate">{q}</span>
                    </button>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      </div>

      {/* The box to type in: attached files, the text, then attach, speak and send */}
      <div className={`px-4 pb-3 pt-1 ${col}`}>
        <div className="rounded-3xl border border-slate-200 bg-white shadow-[0_2px_12px_rgba(15,23,42,0.06)] transition focus-within:border-slate-300 focus-within:shadow-[0_2px_16px_rgba(15,23,42,0.10)]">
          {pending.length > 0 && (
            <div className="flex gap-2 overflow-x-auto px-3 pt-3">
              {pending.map((p) => (
                <PendingTile key={p.key} p={p} onRemove={() => removePending(p.key)}
                             onOpen={() => p.upload && setPreviewing(p.upload)} />
              ))}
            </div>
          )}
          <textarea
            ref={input}
            value={draft}
            rows={1}
            onChange={(e) => {
              setDraft(e.target.value);
              e.target.style.height = "auto";
              e.target.style.height = `${Math.min(e.target.scrollHeight, 200)}px`;
            }}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                send(draft);
              }
            }}
            onPaste={(e) => {
              // A screenshot pasted in is attached like a file
              if (e.clipboardData.files.length) {
                e.preventDefault();
                addFiles(e.clipboardData.files);
              }
            }}
            placeholder={clientName ? `Ask about ${clientName}` : "Ask anything"}
            className="block max-h-[200px] min-h-[44px] w-full resize-none bg-transparent px-4 pt-3 text-[14px] leading-relaxed text-slate-800 outline-none placeholder:text-slate-400 focus-in-parent"
          />
          <div className="flex items-center justify-between px-2.5 pb-2.5">
            <div className="flex min-w-0 items-center gap-0.5">
              <button type="button" onClick={() => fileInput.current?.click()} title={`Attach PDFs or pictures (up to ${MAX_FILES})`}
                      className="rounded-full p-2 text-slate-500 transition hover:bg-slate-100 hover:text-slate-800 cursor-pointer">
                <Paperclip className="h-4 w-4" />
              </button>
              <input ref={fileInput} type="file" multiple accept={FILE_TYPES.join(",")} className="hidden"
                     onChange={(e) => { if (e.target.files) addFiles(e.target.files); e.target.value = ""; }} />

              {(fileNote || pending.length > 0) && (
                <span className={`truncate pl-1 text-[11px] ${fileNote ? "text-rose-600" : "text-slate-400"}`}>
                  {fileNote || `${pending.length} of ${MAX_FILES} files`}
                </span>
              )}
            </div>
            <div className="flex shrink-0 items-center gap-1">
                <VoiceButton disabled={busy} onProblem={setFileNote}
                             onText={(t) => {
                               // What was said goes in the box (after anything typed), to check before sending
                               setDraft((d) => (d.trim() ? `${d.trimEnd()} ${t}` : t));
                               setTimeout(() => {
                                 const el = input.current;
                                 if (!el) return;
                                 el.focus();
                                 el.style.height = "auto";
                                 el.style.height = `${Math.min(el.scrollHeight, 200)}px`;
                               }, 0);
                             }} />
            {busy ? (
              <button type="button" onClick={stop} title="Stop" className="flex h-8 w-8 items-center justify-center rounded-full bg-slate-900 text-white transition hover:bg-slate-700 cursor-pointer">
                <Square className="h-3 w-3 fill-current" />
              </button>
            ) : (
              <button type="button" onClick={() => send(draft)} disabled={!draft.trim() && !pending.some((p) => p.status === "ready")} title="Send (Enter)"
                      className="flex h-8 w-8 items-center justify-center rounded-full bg-slate-900 text-white transition hover:bg-slate-700 disabled:bg-slate-200 disabled:text-slate-400 cursor-pointer disabled:cursor-default">
                <ArrowUp className="h-4 w-4" />
              </button>
            )}
            </div>
          </div>
        </div>
        <p className="mt-2 text-center text-[11px] text-slate-400">Answers use the app&apos;s figures. Check before relying on them.</p>
      </div>
    </>
  );

  const iconBtn = "rounded-lg p-2 text-slate-500 transition hover:bg-slate-100 hover:text-slate-800 cursor-pointer";
  const title = (
    <div className="min-w-0 flex-1">
      <p className="flex items-center gap-1.5 text-[14px] font-semibold text-slate-900">
        <LedgeMark className="h-[18px] w-[18px] text-teal-700" /> Ledge
      </p>
      <p className="truncate text-[11.5px] text-slate-500" title={client ? `${client.name} · year end ${client.ye}` : undefined}>
        {client ? <>{client.name} · YE {client.ye}</> : clientId ? "This client" : "General questions"}
      </p>
    </div>
  );

  return (
    <>
      {!open && !standalone && (
        <button
          type="button"
          onClick={() => setOpen(true)}
          title="Ask Ledge (Ctrl+K)"
          aria-label="Open Ledge, the assistant"
          className="fixed bottom-5 right-5 z-50 flex h-13 w-13 items-center justify-center rounded-full bg-teal-700 text-white shadow-lg shadow-teal-900/20 transition hover:scale-105 hover:bg-teal-800"
          style={{ height: 52, width: 52 }}
        >
          <LedgeMark className="h-6 w-6" />
        </button>
      )}

      {open && over && !full && (
        <div aria-hidden="true" onClick={() => setOpen(false)}
             className="fixed inset-0 z-40 bg-slate-900/20 backdrop-blur-[1px] transition-opacity" />
      )}
      <aside
        aria-label="Ledge, the assistant"
        aria-hidden={!open}
        className={`fixed right-0 top-0 flex h-full max-w-full flex-col border-l border-slate-200 bg-white transition-transform duration-200 ease-out ${full ? "z-[60]" : "z-50"} ${open ? "translate-x-0" : "pointer-events-none translate-x-full"} ${open && over && !full ? "shadow-2xl shadow-slate-900/20" : ""}`}
        style={{ width: full ? "100vw" : width }}
        onDragOver={(e) => { if (e.dataTransfer.types.includes("Files")) { e.preventDefault(); setDragging(true); } }}
        onDragLeave={(e) => { if (e.currentTarget === e.target) setDragging(false); }}
        onDrop={(e) => { if (e.dataTransfer.files.length) { e.preventDefault(); addFiles(e.dataTransfer.files); } setDragging(false); }}
      >
        {dragging && (
          <div className="pointer-events-none absolute inset-2 z-20 flex items-center justify-center rounded-2xl border-2 border-dashed border-teal-400 bg-teal-50/80 text-sm font-semibold text-teal-800">
            Drop PDFs or pictures to attach (up to {MAX_FILES})
          </div>
        )}
        {!full && <div onMouseDown={startResize} title="Drag to resize"
             className="absolute left-0 top-0 hidden h-full w-1.5 -translate-x-1/2 cursor-col-resize transition hover:bg-teal-300 lg:block" />}

        {full ? (
          <div className="relative flex min-h-0 flex-1">
            {side && (
              <nav className={`flex w-64 shrink-0 flex-col border-r border-slate-100 bg-[#f9fafb] ${standalone ? "max-md:absolute max-md:inset-y-0 max-md:left-0 max-md:z-10 max-md:shadow-xl" : ""}`}>
                <div className="flex h-14 shrink-0 items-center gap-1 px-2">
                  <button type="button" onClick={newChat} title="New chat" className={iconBtn}>
                    <MessageSquarePlus className="h-[18px] w-[18px]" />
                  </button>
                  <p className="flex flex-1 items-center gap-1.5 text-[14px] font-semibold text-slate-900">
                    <LedgeMark className="h-[18px] w-[18px] text-teal-700" /> {name}
                  </p>
                  <button type="button" onClick={toggleSide} title="Close sidebar" className={iconBtn}>
                    <PanelLeftClose className="h-[18px] w-[18px]" />
                  </button>
                </div>
                <HistoryList clientId={clientId} clientName={client?.name ?? null} currentId={chatId}
                             onOpen={(id) => { openChat(id); if (standalone && window.innerWidth < 768) setSide(false); }}
                             onDeleted={(id) => { if (id === chatId) newChat(); }} sidebar
                             footer={standalone ? <CostMeter chatId={chatId} tick={meterTick} /> : undefined} tick={meterTick} />
              </nav>
            )}
            <div className="flex min-w-0 flex-1 flex-col">
              <div className="flex h-14 shrink-0 items-center gap-2 px-3">
                {!side && (
                  <>
                    <button type="button" onClick={newChat} title="New chat" className={iconBtn}>
                      <MessageSquarePlus className="h-[18px] w-[18px]" />
                    </button>
                    <p className="flex items-center gap-1.5 text-[14px] font-semibold text-slate-900">
                      <LedgeMark className="h-[18px] w-[18px] text-teal-700" /> {name}
                    </p>
                    <button type="button" onClick={toggleSide} title="Open sidebar" className={iconBtn}>
                      <PanelLeftOpen className="h-[18px] w-[18px]" />
                    </button>
                  </>
                )}
                <p className="min-w-0 flex-1 truncate px-2 text-[12.5px] text-slate-500" title={client ? `${client.name} · year end ${client.ye}` : undefined}>
                  {client ? <><span className="font-medium text-slate-800">{client.name}</span> · YE {client.ye}</> : clientId ? "This client" : standalone ? "UK tax and accounts questions" : "General questions"}
                </p>
                {!standalone && (
                  <>
                    <button type="button" onClick={toggleFull} title="Exit full screen (Esc)" className={iconBtn}>
                      <Minimize2 className="h-4 w-4" />
                    </button>
                    <button type="button" onClick={() => setOpen(false)} title="Close" className={iconBtn}>
                      <X className="h-4 w-4" />
                    </button>
                  </>
                )}
              </div>
              {chatArea}
            </div>
          </div>
        ) : (
          <>
            <div className="flex h-14 shrink-0 items-center gap-1 border-b border-slate-100 px-3">
              {title}
              <button type="button" onClick={() => setView(view === "history" ? "chat" : "history")} title="Chats"
                      className={`${iconBtn} ${view === "history" ? "bg-slate-100 text-slate-900" : ""}`}>
                <History className="h-4 w-4" />
              </button>
              <button type="button" onClick={newChat} title="New chat" className={iconBtn}>
                <MessageSquarePlus className="h-4 w-4" />
              </button>
              <button type="button" onClick={toggleFull} title="Full screen" className={iconBtn}>
                <Maximize2 className="h-4 w-4" />
              </button>
              <button type="button" onClick={() => setOpen(false)} title="Close" className={iconBtn}>
                <X className="h-4 w-4" />
              </button>
            </div>
            {view === "history" ? (
              <HistoryList clientId={clientId} clientName={client?.name ?? null} currentId={chatId} onOpen={openChat}
                           onDeleted={(id) => { if (id === chatId) newChat(); }} />
            ) : chatArea}
          </>
        )}
      </aside>
      <UploadPreview upload={previewing} onClose={() => setPreviewing(null)} />
    </>
  );
}
