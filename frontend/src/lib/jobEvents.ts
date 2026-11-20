"use client";

import { useEffect, useRef } from "react";
import { SAVED_EVENT } from "@/lib/api/client";

/**
 * One signal for "this client's data changed". Any save that works tells the open client page by itself
 * (lib/api/client.ts sends SAVED_EVENT after every call that is not a read); a screen can also call jobChanged(id)
 * to say more (big: the change redoes most of the job, as an upload or the client details do). The client page
 * listens once and refreshes every count, list and figure, then watches LM's re-check and refreshes again when it
 * ends. So no screen has to know which other counts to reload.
 */
export type JobChange = { id: string; big?: boolean };

const EVENT = "lm:job-changed";

export function jobChanged(id: string, opts: { big?: boolean } = {}) {
  if (typeof window === "undefined" || !id) return;
  window.dispatchEvent(new CustomEvent<JobChange>(EVENT, { detail: { id, ...opts } }));
}

/** Calls fn once for a burst of changes on this client (several saves in a row are one refresh), with big when any
 *  of them was big. Saves made while this client's page is open count as this client's. */
export function useJobChanged(id: string, fn: (change: JobChange) => void, waitMs = 300) {
  const latest = useRef(fn);
  // Kept current after each render (fn only runs later, from a timer after a change)
  useEffect(() => {
    latest.current = fn;
  });
  useEffect(() => {
    let timer: ReturnType<typeof setTimeout> | null = null;
    let big = false;
    const fire = (isBig: boolean) => {
      big = big || isBig;
      if (timer) clearTimeout(timer);
      timer = setTimeout(() => {
        const change = { id, big };
        big = false;
        timer = null;
        latest.current(change);
      }, waitMs);
    };
    const onChange = (e: Event) => {
      const detail = (e as CustomEvent<JobChange>).detail;
      if (detail?.id === id) fire(Boolean(detail.big));
    };
    const onSaved = () => fire(false);
    window.addEventListener(EVENT, onChange);
    window.addEventListener(SAVED_EVENT, onSaved);
    return () => {
      if (timer) clearTimeout(timer);
      window.removeEventListener(EVENT, onChange);
      window.removeEventListener(SAVED_EVENT, onSaved);
    };
  }, [id, waitMs]);
}
