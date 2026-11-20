"use client";

import { toast as sonner } from "sonner";

/**
 * The app's messages: good news fades by itself after a few seconds (with Undo or a next step when there is one);
 * an error stays until it is closed, so it is never missed, and says what to do. Every screen imports `toast` from
 * here instead of from sonner.
 */
type Options = Parameters<typeof sonner.error>[1];

const plain = (message: unknown): string => {
  const text = message instanceof Error ? message.message : typeof message === "string" ? message : "";
  // Never a raw technical message on the screen
  if (!text || /failed to fetch|networkerror|load failed/i.test(text)) return "The server could not be reached. Check your connection and try again.";
  if (text === "[object Object]") return "Something went wrong on our side. Try again.";
  return text;
};

function error(message: unknown, options?: Options) {
  return sonner.error(plain(message), { duration: Infinity, closeButton: true, ...options });
}

export const toast = Object.assign((...args: Parameters<typeof sonner>) => sonner(...args), {
  ...sonner,
  error,
  success: (message: Parameters<typeof sonner.success>[0], options?: Options) => sonner.success(message, { duration: 4000, ...options }),
});
