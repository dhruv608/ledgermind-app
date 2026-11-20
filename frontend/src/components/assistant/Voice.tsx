"use client";

// Speak a question: the mic is checked first (is there one, is it allowed), the voice recorded with a live sound bar
// and a timer (up to 2 minutes), then written out by AWS Transcribe in London and put in the box to check before
// sending. Written out in English (Indian English, one stream: one charge a question).
import { useEffect, useRef, useState } from "react";
import { Loader2, Mic, Square } from "lucide-react";
import { assistantApi } from "@/lib/api/assistant";

const RATE = 16000;
const MAX_SECONDS = 120;

type State = "idle" | "starting" | "recording" | "writing";

// Why the mic cannot be used, in plain words (the browser's own error names)
function micProblem(e: unknown): string {
  const name = (e as { name?: string })?.name || "";
  if (name === "NotAllowedError" || name === "SecurityError") {
    return "The microphone is blocked. Click the lock icon in the address bar, allow the microphone, then try again.";
  }
  if (name === "NotFoundError" || name === "OverconstrainedError") return "No microphone found. Plug one in, then try again.";
  if (name === "NotReadableError") return "The microphone is in use by another app. Close it, then try again.";
  return "The microphone could not be started.";
}

/** Float samples at the mic's rate to 16 kHz 16-bit PCM */
function toPcm16(chunks: Float32Array[], fromRate: number): ArrayBuffer {
  const total = chunks.reduce((n, c) => n + c.length, 0);
  const all = new Float32Array(total);
  let at = 0;
  for (const c of chunks) { all.set(c, at); at += c.length; }
  const step = fromRate / RATE;
  const out = new Int16Array(Math.floor(total / step));
  for (let i = 0; i < out.length; i++) {
    const s = Math.max(-1, Math.min(1, all[Math.floor(i * step)]));
    out[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
  }
  return out.buffer;
}

export function VoiceButton({ onText, onProblem, disabled }: {
  onText: (text: string) => void; onProblem: (text: string | null) => void; disabled?: boolean;
}) {
  const [state, setState] = useState<State>("idle");
  const [level, setLevel] = useState(0);
  const [secs, setSecs] = useState(0);
  const rec = useRef<{ ctx: AudioContext; stream: MediaStream; node: ScriptProcessorNode; chunks: Float32Array[]; started: number } | null>(null);

  useEffect(() => () => { rec.current?.stream.getTracks().forEach((t) => t.stop()); rec.current?.ctx.close(); }, []);

  const start = async () => {
    onProblem(null);
    // 1 the browser can record at all (it needs a secure page)
    if (!navigator.mediaDevices?.getUserMedia) {
      onProblem("Voice needs a secure (https) page in Chrome, Edge, Safari or Firefox.");
      return;
    }
    setState("starting");
    try {
      // 2 a microphone is there; 3 it is allowed (the browser asks when not decided yet)
      const devices = await navigator.mediaDevices.enumerateDevices();
      if (!devices.some((d) => d.kind === "audioinput")) throw Object.assign(new Error(), { name: "NotFoundError" });
      try {
        const perm = await navigator.permissions?.query({ name: "microphone" as PermissionName });
        if (perm?.state === "denied") throw Object.assign(new Error(), { name: "NotAllowedError" });
      } catch (e) {
        if ((e as { name?: string }).name === "NotAllowedError") throw e;   // the query itself is not in every browser
      }
      const stream = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true } });
      const ctx = new AudioContext();
      const source = ctx.createMediaStreamSource(stream);
      const node = ctx.createScriptProcessor(4096, 1, 1);
      const chunks: Float32Array[] = [];
      node.onaudioprocess = (e) => {
        const data = e.inputBuffer.getChannelData(0);
        chunks.push(new Float32Array(data));
        let sum = 0;
        for (let i = 0; i < data.length; i += 16) sum += data[i] * data[i];
        setLevel(Math.min(1, Math.sqrt(sum / (data.length / 16)) * 6));
      };
      source.connect(node);
      node.connect(ctx.destination);
      rec.current = { ctx, stream, node, chunks, started: Date.now() };
      setSecs(0);
      setState("recording");
    } catch (e) {
      setState("idle");
      onProblem(micProblem(e));
    }
  };

  const stop = async () => {
    const r = rec.current;
    if (!r) return;
    rec.current = null;
    r.node.disconnect();
    r.stream.getTracks().forEach((t) => t.stop());
    const pcm = toPcm16(r.chunks, r.ctx.sampleRate);
    r.ctx.close();
    setLevel(0);
    if (pcm.byteLength < RATE * 2 * 0.5) {
      setState("idle");
      onProblem("That was too short. Hold the mic a little longer.");
      return;
    }
    setState("writing");
    try {
      const text = await assistantApi.voice(pcm);
      if (text) onText(text);
      else onProblem("No words were heard. Check the microphone and try again.");
    } catch (e) {
      onProblem((e as Error).message);
    } finally {
      setState("idle");
    }
  };

  // The timer, and the stop at 2 minutes
  useEffect(() => {
    if (state !== "recording") return;
    const t = setInterval(() => {
      const s = rec.current ? Math.floor((Date.now() - rec.current.started) / 1000) : 0;
      setSecs(s);
      if (s >= MAX_SECONDS) stop();
    }, 250);
    return () => clearInterval(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- runs per recording state: stop is recreated each render and only reads the rec ref
  }, [state]);

  if (state === "recording") {
    return (
      <div className="flex items-center gap-2 rounded-full bg-rose-50 py-0.5 pl-2.5 pr-0.5">
        <span className="h-2 w-2 animate-pulse rounded-full bg-rose-600" />
        <span className="text-[11px] tabular-nums text-rose-700">{Math.floor(secs / 60)}:{String(secs % 60).padStart(2, "0")}</span>
        <span className="flex h-3 w-14 items-center overflow-hidden rounded-full bg-rose-100" aria-label="Sound level">
          <span className="h-full rounded-full bg-rose-500 transition-[width] duration-100" style={{ width: `${Math.round(level * 100)}%` }} />
        </span>
        <button type="button" onClick={stop} title="Stop and write it out"
                className="flex h-6 w-6 items-center justify-center rounded-full bg-rose-600 text-white transition hover:bg-rose-700 cursor-pointer">
          <Square className="h-2.5 w-2.5 fill-current" />
        </button>
      </div>
    );
  }
  return (
    <div className="flex items-center">
      <button type="button" onClick={start} disabled={disabled || state !== "idle"} title="Speak your question"
              className="rounded-md p-1.5 text-slate-500 transition hover:bg-slate-100 hover:text-teal-700 disabled:opacity-50 cursor-pointer">
        {state === "idle" ? <Mic className="h-4 w-4" /> : <Loader2 className="h-4 w-4 animate-spin" />}
      </button>
      {state === "writing" && <span className="pl-1 text-[10.5px] text-slate-500">Writing it out…</span>}
    </div>
  );
}
