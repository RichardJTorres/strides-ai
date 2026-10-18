import type { ThemeConfig } from "../../App";

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export type Doc = Record<string, any>;

export type SectionName = "shared" | "running" | "cycling" | "lifting";
export type Discipline = Exclude<SectionName, "shared">;

export interface Race {
  date: string;
  name: string;
  target_time?: string;
}

export interface ProfileResponse {
  fields: Doc;
  mode: string;
  mode_sections: { active: Discipline[]; other: Discipline[] };
  completeness: { percent: number; missing: { path: string; label: string; weight: number }[] };
  updated: Record<SectionName, string | null>;
  races: Race[];
}

/** Props every editor card receives. */
export interface CardContext {
  fields: Doc;
  setPath: (path: string[], value: unknown) => void;
  theme: ThemeConfig;
  focusClass: string;
}

export const DISCIPLINE_MODES: Record<Discipline, string> = {
  running: "Running · Hybrid",
  cycling: "Cycling · Hybrid",
  lifting: "Lifting",
};

export interface DisciplineSpec {
  title: string;
  sinceLabel: string;
  sincePlaceholder: string;
  volumeLabel: string;
  volumePlaceholder: (system: "metric" | "imperial") => string;
  focusLabel: string;
  focusOptions: [string, string][];
  bests: { key: string; label: string; placeholder: string }[];
  gearLabel: string;
  gearPlaceholder: (system: "metric" | "imperial") => string;
  backgroundPlaceholder: string;
}

// Keep the focus options and best keys in sync with strides_ai/profile.py DISCIPLINES.
export const DISCIPLINE_SPECS: Record<Discipline, DisciplineSpec> = {
  running: {
    title: "Running",
    sinceLabel: "Running since",
    sincePlaceholder: "e.g. 2018",
    volumeLabel: "Typical weekly volume",
    volumePlaceholder: (s) => (s === "imperial" ? "e.g. 30 mi/week" : "e.g. 50 km/week"),
    focusLabel: "Running focus",
    focusOptions: [
      ["fitness", "Fitness & General Health"],
      ["road_racing", "Road Racing (5K – Marathon)"],
      ["marathon", "Marathon Training"],
      ["trail", "Trail Running"],
      ["ultra", "Ultra Running"],
      ["track", "Track & Speed"],
      ["beginner", "Beginner / Return to Running"],
      ["multi_sport", "Multi-Sport / Triathlon"],
    ],
    bests: [
      { key: "5k", label: "5K", placeholder: "e.g. 22:30" },
      { key: "10k", label: "10K", placeholder: "e.g. 47:00" },
      { key: "half_marathon", label: "Half marathon", placeholder: "e.g. 1:45:00" },
      { key: "marathon", label: "Marathon", placeholder: "e.g. 3:45:00" },
    ],
    gearLabel: "Shoes, watch, other kit",
    gearPlaceholder: (s) =>
      s === "imperial"
        ? "e.g. Nike Vaporfly (~250 mi), Garmin Forerunner 955…"
        : "e.g. Nike Vaporfly (~400 km), Garmin Forerunner 955…",
    backgroundPlaceholder: "Athletic history, how you got into running, previous race experience…",
  },
  cycling: {
    title: "Cycling",
    sinceLabel: "Cycling since",
    sincePlaceholder: "e.g. 2020",
    volumeLabel: "Typical weekly distance",
    volumePlaceholder: (s) => (s === "imperial" ? "e.g. 90 mi/week" : "e.g. 150 km/week"),
    focusLabel: "Cycling focus",
    focusOptions: [
      ["fitness", "Fitness & General Health"],
      ["road_racing", "Road Racing / Criteriums"],
      ["gran_fondo", "Gran Fondo / Sportive"],
      ["time_trial", "Time Trial"],
      ["mountain_biking", "Mountain Biking"],
      ["gravel", "Gravel & Adventure"],
      ["triathlon", "Triathlon / Multi-Sport"],
      ["beginner", "Beginner / Return to Cycling"],
    ],
    bests: [
      { key: "ftp", label: "FTP (watts)", placeholder: "e.g. 250 W" },
      { key: "fastest_century", label: "Fastest century", placeholder: "e.g. 3:45:00" },
      { key: "fastest_gran_fondo", label: "Fastest gran fondo", placeholder: "e.g. 5:30:00" },
      { key: "other", label: "Other", placeholder: "e.g. KOM on local climb" },
    ],
    gearLabel: "Bikes, power meter, other kit",
    gearPlaceholder: () => "e.g. Canyon Endurace, Garmin Edge 840, Quarq power meter…",
    backgroundPlaceholder: "How you got into cycling, race experience, riding style…",
  },
  lifting: {
    title: "Lifting",
    sinceLabel: "Lifting since",
    sincePlaceholder: "e.g. 2019",
    volumeLabel: "Sessions per week",
    volumePlaceholder: () => "e.g. 4",
    focusLabel: "Training style",
    focusOptions: [
      ["general_strength", "General Strength"],
      ["powerlifting", "Powerlifting"],
      ["bodybuilding", "Bodybuilding / Hypertrophy"],
      ["olympic", "Olympic Weightlifting"],
      ["crossfit", "CrossFit / Functional Fitness"],
      ["calisthenics", "Calisthenics / Bodyweight"],
      ["athletic", "Athletic Performance"],
      ["beginner", "Beginner / Getting Started"],
    ],
    bests: [
      { key: "squat_1rm", label: "Squat 1RM", placeholder: "e.g. 140 kg" },
      { key: "deadlift_1rm", label: "Deadlift 1RM", placeholder: "e.g. 180 kg" },
      { key: "bench_press_1rm", label: "Bench press 1RM", placeholder: "e.g. 100 kg" },
      { key: "overhead_press_1rm", label: "Overhead press 1RM", placeholder: "e.g. 65 kg" },
      { key: "other", label: "Other", placeholder: "e.g. 20 strict pull-ups" },
    ],
    gearLabel: "Equipment",
    gearPlaceholder: () => "e.g. Home gym with rack, barbell, dumbbells up to 40 kg…",
    backgroundPlaceholder: "How you got into lifting, programs you've run, gym setup…",
  },
};
