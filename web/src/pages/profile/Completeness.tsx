import type { ThemeConfig } from "../../App";
import type { ProfileResponse } from "./types";

/** Percent-complete bar plus the highest-value missing fields, each linking to its card. */
export default function Completeness({
  data, theme,
}: { data: ProfileResponse["completeness"]; theme: ThemeConfig }) {
  const target = (path: string) => {
    const head = path.split(".")[0];
    if (["running", "cycling", "lifting"].includes(head)) return `profile-${head}`;
    if (path.startsWith("availability") || path === "goals") return "profile-goals";
    if (path === "injuries_and_health") return "profile-health";
    return "profile-you";
  };
  return (
    <div className="rounded-lg border border-gray-800 bg-gray-900/40 p-4">
      <div className="flex items-center justify-between mb-2">
        <span className="text-sm font-semibold text-gray-300">Profile completeness</span>
        <span className={`text-sm font-medium ${theme.accentClass}`}>{data.percent}%</span>
      </div>
      <div className="h-1.5 rounded-full bg-gray-800 overflow-hidden" role="progressbar" aria-valuenow={data.percent} aria-valuemin={0} aria-valuemax={100}>
        <div className={`h-full ${theme.accentButton.split(" ")[0]}`} style={{ width: `${data.percent}%` }} />
      </div>
      {data.missing.length > 0 && (
        <p className="text-xs text-gray-500 mt-3">
          Most useful to add next:{" "}
          {data.missing.slice(0, 4).map((m, i) => (
            <span key={m.path}>
              {i > 0 && ", "}
              <a href={`#profile`} onClick={(e) => { e.preventDefault(); document.getElementById(target(m.path))?.scrollIntoView({ behavior: "smooth" }); }} className={`${theme.accentClass} hover:underline`}>
                {m.label}
              </a>
            </span>
          ))}
        </p>
      )}
    </div>
  );
}
