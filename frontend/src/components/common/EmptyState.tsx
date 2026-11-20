import { LucideIcon } from "lucide-react";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";

/** The four empty-screen pictures (frontend/public/illustrations, unDraw in the app's teal): all clear, nothing yet,
 *  waiting for a document, nothing found */
export type EmptyArt = "done" | "start" | "upload" | "search";

export interface EmptyStateProps {
  /** A small icon, when the screen has no picture */
  icon?: LucideIcon;
  /** A picture instead of the icon (whole-area empty screens only; table rows stay text) */
  art?: EmptyArt;
  title: string;
  description: string;
  action?: {
    label: string;
    onClick: () => void;
    icon?: LucideIcon;
    variant?: "default" | "primary" | "outline";
  };
  className?: string;
}

/**
 * The app's empty screen, centred: a picture (or an icon), the title, one line and the button when there is one.
 */
export function EmptyState({
  icon: Icon,
  art,
  title,
  description,
  action,
  className = "",
}: EmptyStateProps) {
  const ActionIcon = action?.icon;

  return (
    <Card className={`flex flex-col items-center px-6 py-10 text-center border-slate-200 bg-white ${className}`}>
      {art ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img src={`/illustrations/${art}.svg`} alt="" aria-hidden="true" className="mb-4 h-28 w-auto select-none" />
      ) : Icon ? <Icon className="w-12 h-12 text-slate-300 mx-auto mb-3" /> : null}
      <h3 className="text-base font-semibold text-slate-800">{title}</h3>
      <p className="text-xs text-slate-500 mt-1 max-w-sm mx-auto">{description}</p>
      {action && (
        <div className="mt-5">
          <Button
            onClick={action.onClick}
            variant={action.variant || "primary"}
            size="default"
          >
            {ActionIcon && <ActionIcon className="w-4 h-4 mr-1.5" />}
            <span>{action.label}</span>
          </Button>
        </div>
      )}
    </Card>
  );
}
