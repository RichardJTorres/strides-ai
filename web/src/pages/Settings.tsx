import type { Dispatch, SetStateAction } from "react";
import type { Mode, ThemeConfig } from "../App";

interface Props {
  mode: Mode;
  setMode: Dispatch<SetStateAction<Mode>>;
  theme: ThemeConfig;
}

const MODE_CARDS: {
  id: Mode;
  label: string;
  description: string;
  accentClass: string;
  borderSelected: string;
  dotClass: string;
}[] = [
  {
    id: "running",
    label: "Running",
    description: "Running activities only. Coaching focused on pace, cadence, and running load.",
    accentClass: "text-green-400",
    borderSelected: "border-green-500",
    dotClass: "bg-green-500",
  },
  {
    id: "cycling",
    label: "Cycling",
    description: "Cycling activities only. Coaching focused on speed, power, and ride load.",
    accentClass: "text-blue-400",
    borderSelected: "border-blue-500",
    dotClass: "bg-blue-500",
  },
  {
    id: "hybrid",
    label: "Hybrid",
    description: "All activities. Cross-training coaching across running and cycling.",
    accentClass: "text-purple-400",
    borderSelected: "border-purple-500",
    dotClass: "bg-purple-500",
  },
];

export default function Settings({ mode, setMode }: Props) {
  async function handleModeChange(newMode: Mode) {
    try {
      await fetch("/api/settings", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mode: newMode }),
      });
    } catch {
      // best-effort; switch mode locally regardless
    }
    setMode(newMode);
    location.hash = "chat";
  }

  return (
    <div className="flex-1 overflow-y-auto">
      <div className="max-w-2xl mx-auto px-6 py-10">
        <h2 className="text-xl font-semibold text-gray-100 mb-1">Settings</h2>
        <p className="text-sm text-gray-500 mb-8">Configure your Strides AI preferences.</p>

        <div className="space-y-6">
          <section>
            <h3 className="text-xs font-semibold uppercase tracking-wider text-gray-500 mb-1">
              Mode
            </h3>
            <p className="text-xs text-gray-600 mb-3">
              Switching mode changes which activities are loaded into context and the coaching
              style. Each mode keeps its own conversation history.
            </p>
            <div className="space-y-3">
              {MODE_CARDS.map((card) => {
                const selected = mode === card.id;
                return (
                  <button
                    key={card.id}
                    onClick={() => handleModeChange(card.id)}
                    className={`w-full text-left p-4 rounded-lg border-2 transition-colors bg-gray-900 ${
                      selected
                        ? card.borderSelected
                        : "border-gray-700 hover:border-gray-500"
                    }`}
                  >
                    <div className="flex items-center gap-3 mb-1">
                      <span className={`w-2 h-2 rounded-full shrink-0 ${card.dotClass}`} />
                      <span className={`font-medium text-sm ${selected ? card.accentClass : "text-gray-200"}`}>
                        {card.label}
                      </span>
                      {selected && (
                        <span className={`ml-auto text-xs ${card.accentClass}`}>Active</span>
                      )}
                    </div>
                    <p className="text-xs text-gray-500 pl-5">{card.description}</p>
                  </button>
                );
              })}
            </div>
          </section>
        </div>
      </div>
    </div>
  );
}
