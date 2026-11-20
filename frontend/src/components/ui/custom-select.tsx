"use client";

import React, { useState, useRef, useEffect, useCallback, useMemo } from "react";
import { ChevronDown, Check, Search } from "lucide-react";
import { cn } from "@/lib/utils";

export interface DropdownOption {
  value: string | number;
  label: string;
  count?: number;
  description?: string;
  icon?: React.ReactNode;
  /** A heading shown above the first option of each group ("Common", "Firm chart"). */
  group?: string;
  /** Which of the menu's filter buttons show this option (see `filters`). */
  tags?: string[];
}

export interface DropdownProps {
  value: string | number;
  onChange: (value: any) => void;
  options: DropdownOption[];
  placeholder?: string;
  className?: string;
  buttonClassName?: string;
  menuClassName?: string;
  size?: "sm" | "default" | "lg";
  align?: "left" | "right";
  /** Where the menu opens: "auto" (default) opens above the button when there is no room below it. */
  side?: "auto" | "bottom" | "top";
  /** Stretch to the width of its container (form fields). */
  fullWidth?: boolean;
  disabled?: boolean;
  icon?: React.ReactNode;
  title?: string;
  /** A search box at the top of the menu: typing narrows the options (for long lists such as the chart of accounts). */
  searchable?: boolean;
  searchPlaceholder?: string;
  /** Filter buttons under the search box ("Common", "P&L", "Balance sheet"): each shows the options tagged with its id. */
  filters?: { id: string; label: string }[];
}

/** The app's dropdown: white button, teal focus, rounded menu with a tick on the chosen option. */
export function CustomSelect({
  value,
  onChange,
  options,
  placeholder = "Select…",
  className = "",
  buttonClassName = "",
  menuClassName = "",
  size = "default",
  align = "left",
  side = "auto",
  fullWidth = false,
  disabled = false,
  icon,
  title,
  searchable = false,
  searchPlaceholder = "Type to search",
  filters,
}: DropdownProps) {
  const [isOpen, setIsOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const [focusedIndex, setFocusedIndex] = useState<number>(-1);
  const [openUp, setOpenUp] = useState(side === "top");
  const [query, setQuery] = useState("");
  // Long lists (the chart of accounts) are drawn in pages of 50 as the menu is scrolled; the search looks at all of them
  const PAGE = 30;
  const [limit, setLimit] = useState(PAGE);
  const [filter, setFilter] = useState("all");
  // The options the menu shows: all of them, or those matching every word typed in the search box
  const shown = useMemo(() => {
    const words = query.toLowerCase().split(/\s+/).filter(Boolean);
    const inFilter = filter === "all" ? options : options.filter((o) => o.tags?.includes(filter));
    if (!words.length) return inFilter;
    return inFilter.filter((o) => {
      const text = `${o.label} ${o.description || ""}`.toLowerCase();
      return words.every((w) => text.includes(w));
    });
  }, [options, query, filter]);

  const selectedIndex = options.findIndex((o) => String(o.value) === String(value));
  const selectedOption = selectedIndex >= 0 ? options[selectedIndex] : undefined;
  const close = () => {
    setIsOpen(false);
    setQuery("");
  };

  const open = () => {
    if (side === "auto" && containerRef.current) {
      // Room below the button, inside the nearest box that cuts off its content (a modal, a scrolling list) and the window
      const rect = containerRef.current.getBoundingClientRect();
      let bottom = window.innerHeight;
      let top = 0;
      for (let el = containerRef.current.parentElement; el; el = el.parentElement) {
        const o = getComputedStyle(el).overflowY;
        if (o === "auto" || o === "scroll" || o === "hidden") {
          const r = el.getBoundingClientRect();
          bottom = Math.min(bottom, r.bottom);
          top = Math.max(top, r.top);
          break;
        }
      }
      const menuHeight = Math.min(options.length * 32 + 12, 300) + (searchable ? 44 : 0);
      setOpenUp(bottom - rect.bottom < menuHeight && rect.top - top > bottom - rect.bottom);
    } else {
      setOpenUp(side === "top");
    }
    setIsOpen(true);
    setQuery("");
    setFilter("all");
    setLimit(Math.max(PAGE, selectedIndex + PAGE));     // the chosen option is drawn, so it can be scrolled to
    setFocusedIndex(selectedIndex >= 0 ? selectedIndex : 0);
  };

  // Close when clicking outside
  useEffect(() => {
    if (!isOpen) return;
    const handleClickOutside = (event: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(event.target as Node)) close();
    };
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [isOpen]);

  // Keep the highlighted option in view while using the arrow keys
  useEffect(() => {
    if (!isOpen || focusedIndex < 0) return;
    (listRef.current?.querySelectorAll("[role=option]")[focusedIndex] as HTMLElement | undefined)?.scrollIntoView({ block: "nearest" });
  }, [isOpen, focusedIndex]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (disabled) return;
      const typing = (e.target as HTMLElement).tagName === "INPUT";
      if (!isOpen) {
        if (e.key === "Enter" || e.key === " " || e.key === "ArrowDown" || e.key === "ArrowUp") {
          e.preventDefault();
          open();
        }
        return;
      }
      switch (e.key) {
        case "Escape":
        case "Tab":
          close();
          break;
        case "ArrowDown":
          e.preventDefault();
          setFocusedIndex((prev) => {
            const next = prev < shown.length - 1 ? prev + 1 : 0;
            if (next >= limit - 1) setLimit((l) => l + PAGE);
            return next;
          });
          break;
        case "ArrowUp":
          e.preventDefault();
          setFocusedIndex((prev) => {
            const next = prev > 0 ? prev - 1 : shown.length - 1;
            if (next >= limit) setLimit(next + 1);
            return next;
          });
          break;
        case " ":
          if (typing) break;          // a space typed in the search box
        // falls through
        case "Enter":
          e.preventDefault();
          if (focusedIndex >= 0 && focusedIndex < shown.length) {
            onChange(shown[focusedIndex].value);
            close();
          }
          break;
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [isOpen, disabled, shown, focusedIndex, onChange, selectedIndex, limit]
  );

  const sizeClasses = {
    sm: "h-7 px-2.5 text-[11px]",
    default: "h-8 px-2.5 text-xs",
    lg: "h-9 px-3 text-xs",
  }[size];

  return (
    <div
      className={cn("relative text-left", fullWidth ? "block w-full" : "inline-block", className)}
      ref={containerRef}
      onKeyDown={handleKeyDown}
    >
      <button
        type="button"
        disabled={disabled}
        title={title}
        onClick={() => (isOpen ? close() : open())}
        aria-haspopup="listbox"
        aria-expanded={isOpen}
        className={cn(
          "inline-flex select-none items-center justify-between gap-2 rounded-lg border bg-white text-slate-700 transition",
          sizeClasses,
          fullWidth && "w-full",
          disabled
            ? "cursor-not-allowed bg-slate-50 opacity-50"
            : isOpen
            ? "border-teal-500 ring-2 ring-teal-200"
            : "cursor-pointer border-slate-300 hover:border-slate-400",
          buttonClassName
        )}
      >
        <span className="flex min-w-0 items-center gap-1.5">
          {icon && <span className="shrink-0 text-slate-400">{icon}</span>}
          {selectedOption?.icon && <span className="shrink-0">{selectedOption.icon}</span>}
          <span className={cn("truncate", !selectedOption && "text-slate-400")}>
            {selectedOption ? selectedOption.label : placeholder}
          </span>
        </span>
        <ChevronDown
          className={cn("h-3.5 w-3.5 shrink-0 text-slate-400 transition-transform duration-150", isOpen && "rotate-180 text-teal-700")}
        />
      </button>

      {isOpen && (
        <div
          role="listbox"
          className={cn(
            "absolute z-50 rounded-xl border border-slate-200 bg-white p-1 shadow-lg animate-in fade-in zoom-in-95 duration-100",
            openUp ? "bottom-full mb-1.5" : "top-full mt-1.5",
            fullWidth ? "left-0 right-0" : cn("min-w-full w-max max-w-[min(22rem,calc(100vw-2rem))]", align === "right" ? "right-0" : "left-0"),
            menuClassName
          )}
        >
          {searchable && (
            <div className="relative mb-1">
              <Search className="pointer-events-none absolute left-2.5 top-2 h-3.5 w-3.5 text-slate-400" />
              <input
                autoFocus
                value={query}
                onChange={(e) => {
                  setQuery(e.target.value);
                  setFocusedIndex(0);
                  setLimit(PAGE);
                }}
                placeholder={searchPlaceholder}
                className="h-7 w-full rounded-lg border border-slate-200 bg-slate-50 pl-8 pr-2 text-xs text-slate-800 focus:border-teal-400 focus:bg-white focus:outline-none"
              />
            </div>
          )}
          {filters && filters.length > 0 && (
            <div className="mb-1 flex flex-wrap gap-1 border-b border-slate-100 pb-1.5">
              {[{ id: "all", label: "All" }, ...filters].map((f) => (
                <button
                  key={f.id}
                  type="button"
                  onClick={() => {
                    setFilter(f.id);
                    setFocusedIndex(0);
                    setLimit(PAGE);
                    listRef.current?.scrollTo({ top: 0 });
                  }}
                  className={cn(
                    "rounded-md px-2 py-0.5 text-[11px] font-medium transition",
                    filter === f.id ? "bg-teal-50 text-teal-800" : "text-slate-500 hover:bg-slate-100 hover:text-slate-800"
                  )}
                >
                  {f.label}
                </button>
              ))}
            </div>
          )}
          <div
            ref={listRef}
            className="max-h-72 space-y-0.5 overflow-y-auto"
            onScroll={(e) => {
              const el = e.currentTarget;
              if (limit < shown.length && el.scrollTop + el.clientHeight >= el.scrollHeight - 80) setLimit((l) => l + PAGE);
            }}
          >
            {shown.length === 0 && <p className="px-2.5 py-2 text-xs text-slate-400">Nothing matches</p>}
            {shown.slice(0, limit).map((option, index) => {
              const isSelected = String(option.value) === String(value);
              const heading = option.group && option.group !== shown[index - 1]?.group ? option.group : null;
              return (
                <React.Fragment key={String(option.value)}>
                {heading && (
                  <p className="px-2.5 pb-1 pt-2 text-[10px] font-semibold uppercase tracking-wide text-slate-400">{heading}</p>
                )}
                <button
                  type="button"
                  role="option"
                  aria-selected={isSelected}
                  onClick={() => {
                    onChange(option.value);
                    close();
                  }}
                  onMouseEnter={() => setFocusedIndex(index)}
                  className={cn(
                    "flex w-full cursor-pointer select-none items-start justify-between gap-2 rounded-lg px-2.5 py-1.5 text-left text-xs leading-snug transition-colors",
                    isSelected ? "bg-teal-50 font-semibold text-teal-800" : focusedIndex === index ? "bg-slate-100 text-slate-900" : "text-slate-700"
                  )}
                >
                  <span className="flex min-w-0 items-start gap-2">
                    {option.icon && <span className="mt-0.5 shrink-0">{option.icon}</span>}
                    <span className="min-w-0">
                      <span className="block">
                        {option.label}
                        {option.count !== undefined && <span className="ml-1.5 font-mono text-[11px] text-slate-400">{option.count}</span>}
                      </span>
                      {option.description && <span className="block text-[11px] font-normal leading-snug text-slate-500">{option.description}</span>}
                    </span>
                  </span>
                  {isSelected && <Check className="mt-0.5 h-3.5 w-3.5 shrink-0 text-teal-700" />}
                </button>
                </React.Fragment>
              );
            })}
            {limit < shown.length && <div className="h-6" aria-hidden />}
          </div>
        </div>
      )}
    </div>
  );
}
