import { useState } from "react";
import Button from "../../ui/Button";
import { formatDate } from "../../ui/format";
import { useTheme } from "../../ui/theme";
import { WORKOUT_COLORS, WORKOUT_TYPE_GROUPS } from "./constants";
import type { Prefs, Race } from "./types";

interface Props {
  prefs: Prefs;
  onGenerate: () => void;
  onAddRace: (race: Race) => void;
  removeRace: (date: string) => void;
}

/** Left rail: generate a block, races, and the colour legend. */
export default function Sidebar({ prefs, onGenerate, onAddRace, removeRace }: Props) {
  const theme = useTheme();
  const [showDetails, setShowDetails] = useState(false);
  const [showRaceForm, setShowRaceForm] = useState(false);
  const [raceForm, setRaceForm] = useState({ date: "", name: "", target_time: "" });

  const addRace = () => {
    if (!raceForm.date || !raceForm.name) return;
    const race: Race = { date: raceForm.date, name: raceForm.name };
    if (raceForm.target_time) race.target_time = raceForm.target_time;
    onAddRace(race);
    setRaceForm({ date: "", name: "", target_time: "" });
    setShowRaceForm(false);
  };

  return (
  <aside className="md:w-56 flex-shrink-0 border-b md:border-b-0 md:border-r border-gray-800 md:overflow-y-auto p-3 md:p-4 space-y-3 md:space-y-6">

    <div className="flex gap-2">
      <button
        onClick={onGenerate}
        className={`flex-1 text-left text-white rounded-lg px-3 py-2.5 flex items-center gap-2.5 transition-colors ${theme.accentButton}`}
      >
        <span className="text-lg leading-none" aria-hidden="true">✨</span>
        <span className="min-w-0">
          <div className="text-sm font-semibold leading-tight">Generate Training Block</div>
          <div className="text-[11px] text-white/75 leading-tight">AI-suggested plan for a date range</div>
        </span>
      </button>
      {/* Phones: races and the legend fold away so the grid gets the screen. */}
      <button
        onClick={() => setShowDetails(open => !open)}
        aria-expanded={showDetails}
        className="md:hidden rounded-lg border border-gray-700 px-3 text-xs text-gray-300"
      >
        {showDetails ? "Hide" : "Races & legend"}
      </button>
    </div>

    <div className={`${showDetails ? "" : "hidden"} md:block space-y-6`}>
    <div>
      <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2">Races</h3>
      <div className="space-y-2 mb-2">
        {prefs.races.map(race => (
          <div key={race.date} className="flex items-start justify-between gap-1">
            <div className="text-xs">
              <div className="text-amber-300 font-medium">{race.name}</div>
              <div className="text-gray-500">
                {formatDate(race.date)}{race.target_time ? ` · ${race.target_time}` : ""}
              </div>
            </div>
            <button
              onClick={() => removeRace(race.date)}
              aria-label={`Remove ${race.name}`}
              className="text-gray-600 hover:text-gray-300 text-xs mt-0.5 leading-none"
            >✕</button>
          </div>
        ))}
      </div>
      {showRaceForm ? (
        <div className="space-y-1">
          <input
            type="date" value={raceForm.date}
            onChange={e => setRaceForm(f => ({ ...f, date: e.target.value }))}
            className="w-full text-xs bg-gray-800 border border-gray-700 rounded px-2 py-1 text-gray-200"
          />
          <input
            type="text" placeholder="Race name" value={raceForm.name}
            onChange={e => setRaceForm(f => ({ ...f, name: e.target.value }))}
            className="w-full text-xs bg-gray-800 border border-gray-700 rounded px-2 py-1 text-gray-200"
          />
          <input
            type="text" placeholder="Target time (optional)" value={raceForm.target_time}
            onChange={e => setRaceForm(f => ({ ...f, target_time: e.target.value }))}
            className="w-full text-xs bg-gray-800 border border-gray-700 rounded px-2 py-1 text-gray-200"
          />
          <div className="flex gap-1">
            <Button size="sm" className="flex-1" onClick={addRace}>Add</Button>
            <Button size="sm" variant="secondary" className="flex-1" onClick={() => setShowRaceForm(false)}>Cancel</Button>
          </div>
        </div>
      ) : (
        <button onClick={() => setShowRaceForm(true)} className="text-xs text-gray-500 hover:text-gray-300">
          + Add race
        </button>
      )}
    </div>

    <div>
      <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2">Legend</h3>
      <div className="space-y-2 mb-3">
        {WORKOUT_TYPE_GROUPS.map(group => (
          <div key={group.label}>
            <div className="text-[10px] text-gray-600 uppercase tracking-wider mb-0.5">{group.label}</div>
            <div className="space-y-1">
              {group.types.map(type => (
                <div key={type} className="flex items-center gap-2">
                  <span className={`w-2 h-2 rounded-full ${WORKOUT_COLORS[type].split(" ")[0]}`} />
                  <span className="text-xs text-gray-400">{type}</span>
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
      <div className="flex items-center gap-2">
        <span className="w-2 h-2 rounded-full bg-gray-500" />
        <span className="text-xs text-gray-400">Strava activity</span>
      </div>
      <div className="mt-3 pt-3 border-t border-gray-800 space-y-1">
        <div className="text-[10px] text-gray-600 uppercase tracking-wider mb-0.5">Plan compliance</div>
        <div className="flex items-center gap-2">
          <span className="w-1.5 h-1.5 rounded-full bg-green-400" />
          <span className="text-xs text-gray-400">Completed as planned</span>
        </div>
        <div className="flex items-center gap-2">
          <span className="w-1.5 h-1.5 rounded-full bg-amber-400" />
          <span className="text-xs text-gray-400">Shortened (fell short of target)</span>
        </div>
        <div className="flex items-center gap-2">
          <span className="w-1.5 h-1.5 rounded-full bg-red-400" />
          <span className="text-xs text-gray-400">Missed</span>
        </div>
        <div className="text-[10px] text-gray-600">No dot = upcoming or not scorable (rest/yoga)</div>
      </div>
    </div>
    </div>
  </aside>
  );
}
