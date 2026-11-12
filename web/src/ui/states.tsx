import type { ReactNode } from "react";
import Button from "./Button";
import Spinner from "./Spinner";

/** Whole-area placeholder while data loads. */
export function LoadingState({ label = "Loading…" }: { label?: string }) {
  return (
    <div role="status" className="flex items-center gap-2 py-6 text-sm text-gray-500">
      <Spinner />
      {label}
    </div>
  );
}

/** Whole-area placeholder when a load failed: says so, and offers a retry. */
export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div role="alert" className="rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-3">
      <p className="text-sm text-red-300">{message}</p>
      {onRetry && (
        <Button variant="ghost" size="sm" className="mt-2" onClick={onRetry}>
          Try again
        </Button>
      )}
    </div>
  );
}

/** Whole-area placeholder when there is nothing to show (not an error). */
export function EmptyState({ children }: { children: ReactNode }) {
  return <p className="py-6 text-sm text-gray-500">{children}</p>;
}

const NOTICE_TONES = {
  error: "border-red-500/30 bg-red-500/10 text-red-300",
  warning: "border-amber-500/30 bg-amber-500/10 text-amber-200",
  info: "border-gray-700 bg-gray-800/60 text-gray-300",
  success: "border-green-500/30 bg-green-500/10 text-green-300",
} as const;

/** Inline message next to the thing it is about (a failed save, a warning flag). */
export function Notice({
  tone = "info",
  children,
  className = "",
}: {
  tone?: keyof typeof NOTICE_TONES;
  children: ReactNode;
  className?: string;
}) {
  return (
    <div
      role={tone === "error" ? "alert" : "status"}
      className={`rounded-md border px-3 py-2 text-xs ${NOTICE_TONES[tone]} ${className}`}
    >
      {children}
    </div>
  );
}
