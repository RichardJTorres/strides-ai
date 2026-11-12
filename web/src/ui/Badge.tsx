import type { ReactNode } from "react";

const TONES = {
  neutral: "bg-gray-800 text-gray-300",
  success: "bg-green-500/20 text-green-300",
  warning: "bg-amber-500/20 text-amber-300",
  danger: "bg-red-500/20 text-red-300",
  highlight: "bg-yellow-500/20 text-yellow-300",
} as const;

/** A small inline label: a status, a count, a "new" marker. */
export default function Badge({
  tone = "neutral",
  title,
  children,
}: {
  tone?: keyof typeof TONES;
  title?: string;
  children: ReactNode;
}) {
  return (
    <span
      title={title}
      className={`inline-block rounded px-1.5 py-0.5 text-[10px] font-medium whitespace-nowrap ${TONES[tone]}`}
    >
      {children}
    </span>
  );
}
