"use client";

import React, { useEffect, useState } from "react";

export type GuideTab = { id: string; label: string; anchors?: string[]; content: React.ReactNode };

/** The guide in tabs: one part at a time instead of one long page. The tab is in the address (#files), and a
 *  link to a section (#before-upload) opens the tab that holds it. */
export function GuideTabs({ tabs }: { tabs: GuideTab[] }) {
  const [active, setActive] = useState(tabs[0].id);

  useEffect(() => {
    const pick = () => {
      const hash = window.location.hash.replace("#", "");
      const tab = tabs.find((t) => t.id === hash || (t.anchors || []).includes(hash));
      if (tab) {
        setActive(tab.id);
        // A section link: scroll to it once its tab is shown
        if (hash !== tab.id) setTimeout(() => document.getElementById(hash)?.scrollIntoView({ block: "start" }), 50);
      }
    };
    pick();
    window.addEventListener("hashchange", pick);
    return () => window.removeEventListener("hashchange", pick);
  }, [tabs]);

  const open = (id: string) => {
    setActive(id);
    window.history.replaceState(null, "", `#${id}`);
  };

  return (
    <div className="space-y-6">
      <div role="tablist" className="flex gap-1 overflow-x-auto overflow-y-hidden border-b border-slate-200">
        {tabs.map(({ id, label }) => (
          <button
            key={id}
            role="tab"
            type="button"
            aria-selected={active === id}
            onClick={() => open(id)}
            className={`-mb-px shrink-0 border-b-2 px-4 py-2.5 text-sm font-medium transition ${
              active === id ? "border-teal-700 text-teal-800" : "border-transparent text-slate-500 hover:text-slate-800"
            }`}
          >
            {label}
          </button>
        ))}
      </div>
      {tabs.map(({ id, content }) => (
        <div key={id} role="tabpanel" hidden={active !== id} className="space-y-8">
          {content}
        </div>
      ))}
    </div>
  );
}
