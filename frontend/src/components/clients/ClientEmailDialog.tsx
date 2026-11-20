"use client";

import { useState } from "react";
import { Copy, Mail } from "lucide-react";
import { toast } from "@/lib/notify";
import { Button } from "@/components/ui/button";
import { Modal } from "@/components/ui/dialog";
import { formatDate } from "@/lib/formatters";

export interface EmailGroup {
  title: string;
  items: string[];
}

// Web mail compose pages that take a subject and a body in the link; a very long link is cut by the browser or the
// mail service, so a long email is copied and the compose page opens with the subject only (paste the body)
const COMPOSE: Record<"gmail" | "outlook", { name: string; url: (subject: string, body: string) => string }> = {
  gmail: { name: "Gmail", url: (su, b) => `https://mail.google.com/mail/?view=cm&fs=1&su=${encodeURIComponent(su)}${b ? `&body=${encodeURIComponent(b)}` : ""}` },
  outlook: { name: "Outlook", url: (su, b) => `https://outlook.office.com/mail/deeplink/compose?subject=${encodeURIComponent(su)}${b ? `&body=${encodeURIComponent(b)}` : ""}` },
};
const LONGEST_LINK = 7000;

/** A ready email to the client with the open questions, opened in the accountant's Gmail or Outlook (or copied):
 *  they add the address and press Send there; nothing is sent from the app. The text can be edited first. */
export function ClientEmailDialog({ isOpen, onClose, client, yearEnd, groups }: {
  isOpen: boolean;
  onClose: () => void;
  client: string;
  yearEnd: string | null;
  groups: EmailGroup[];
}) {
  const ye = yearEnd ? formatDate(yearEnd, "long") : "";
  const subject = `Year-end accounts${client ? ` - ${client}` : ""}${ye ? ` - year ended ${ye}` : ""}: a few questions`;
  const [body, setBody] = useState("");

  // The text is written again when the dialog opens or its questions change (set while rendering, not in an effect)
  const [builtFor, setBuiltFor] = useState<{ isOpen: boolean; client: string; ye: string; groups: EmailGroup[] } | null>(null);
  if (!builtFor || builtFor.isOpen !== isOpen || builtFor.client !== client || builtFor.ye !== ye || builtFor.groups !== groups) {
    setBuiltFor({ isOpen, client, ye, groups });
    if (isOpen) {
      const lines = [
        "Hi,",
        "",
        `We are preparing the accounts of ${client || "the company"}${ye ? ` for the year ended ${ye}` : ""}. ` +
          "To finish them, could you please help with the points below.",
        "",
      ];
      for (const g of groups) {
        if (!g.items.length) continue;
        lines.push(g.title, ...g.items.map((t, i) => `${i + 1}. ${t}`), "");
      }
      lines.push("You can reply to this email with the answers and attach any documents.", "", "Many thanks,", "");
      setBody(lines.join("\n"));
    }
  }

  const count = groups.reduce((n, g) => n + g.items.length, 0);
  const copy = (text: string, what: string) =>
    navigator.clipboard.writeText(text).then(() => toast.success(`${what} copied`), () => toast.error("Could not copy"));
  const openIn = (where: "gmail" | "outlook") => {
    const { name, url } = COMPOSE[where];
    const full = url(subject, body);
    if (full.length <= LONGEST_LINK) {
      window.open(full, "_blank", "noopener");
      return;
    }
    // Too long for a link: the email goes to the clipboard, the compose page opens with the subject
    navigator.clipboard.writeText(body).then(
      () => toast.success(`The email is long: it is copied. Paste it into the ${name} message.`),
      () => toast.error("Could not copy the email: copy it from the box"),
    );
    window.open(url(subject, ""), "_blank", "noopener");
  };

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      title="Email to the client"
      description={`${count} question${count === 1 ? "" : "s"}. Edit if needed, then open it in Gmail or Outlook, add the client's address and press Send there: the app sends nothing.`}
    >
      <div className="space-y-3 text-xs">
        <div className="flex items-center gap-2">
          <span className="w-14 shrink-0 font-semibold text-slate-500">Subject</span>
          <p className="min-w-0 flex-1 truncate rounded-md border border-slate-200 bg-slate-50 px-2 py-1.5 text-slate-800">{subject}</p>
          <Button size="sm" variant="outline" className="h-7 px-2 text-[11px]" onClick={() => copy(subject, "Subject")}>
            <Copy className="mr-1 h-3.5 w-3.5" /> Copy
          </Button>
        </div>
        <textarea
          value={body}
          onChange={(e) => setBody(e.target.value)}
          rows={18}
          className="w-full resize-y rounded-lg border border-slate-200 p-3 font-mono text-[12px] leading-relaxed text-slate-800 focus:outline-none focus:ring-2 focus:ring-teal-200"
        />
        <div className="flex flex-wrap justify-end gap-2">
          <Button size="sm" variant="ghost" onClick={onClose}>Close</Button>
          <Button size="sm" variant="outline" onClick={() => copy(body, "Email")}>
            <Copy className="mr-1.5 h-3.5 w-3.5" /> Copy
          </Button>
          <Button size="sm" variant="outline" onClick={() => openIn("outlook")}>
            <Mail className="mr-1.5 h-3.5 w-3.5" /> Open in Outlook
          </Button>
          <Button size="sm" variant="primary" onClick={() => openIn("gmail")}>
            <Mail className="mr-1.5 h-3.5 w-3.5" /> Open in Gmail
          </Button>
        </div>
      </div>
    </Modal>
  );
}
