import * as React from "react";
import { cn } from "@/lib/utils";

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: "default" | "outline" | "secondary" | "ghost" | "destructive" | "primary";
  size?: "default" | "sm" | "lg" | "icon";
}

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant = "default", size = "default", ...props }, ref) => {
    const base = "inline-flex items-center justify-center rounded-lg font-medium transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-600 disabled:pointer-events-none disabled:opacity-50 select-none shadow-xs";
    
    const variants = {
      default: "bg-teal-700 text-white hover:bg-teal-800 shadow-sm active:scale-[0.99]",
      primary: "bg-teal-700 text-white hover:bg-teal-800 shadow-sm active:scale-[0.99]",
      outline: "border border-slate-300 bg-white hover:bg-slate-50 text-slate-700 shadow-2xs",
      secondary: "bg-slate-100 text-slate-800 hover:bg-slate-200/80 border border-slate-200",
      ghost: "shadow-none hover:bg-slate-100 text-slate-600 hover:text-slate-900",
      destructive: "bg-rose-600 text-white hover:bg-rose-700 shadow-sm",
    };

    const sizes = {
      default: "h-9 px-4 py-2 text-xs",
      sm: "h-8 px-3 text-xs",
      lg: "h-10 px-5 text-sm",
      icon: "h-9 w-9 p-0",
    };

    return (
      <button
        className={cn(base, variants[variant], sizes[size], className)}
        ref={ref}
        {...props}
      />
    );
  }
);
Button.displayName = "Button";

export { Button };
