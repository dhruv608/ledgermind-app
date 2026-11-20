import type { Metadata } from "next";
import { ChatGate } from "@/components/assistant/ChatGate";

export const metadata: Metadata = {
  title: "LedgerMind Chat",
  description: "Ask UK tax and accounts questions, answered from HMRC guidance and the law.",
};

/** The test chat page: a 4-digit code once per device, then the assistant full screen (no client, no sign-in). */
export default function ChatPage() {
  return <ChatGate />;
}
