import type { PreflopPosition } from "../../../shared/types/poker";

export const PREFLOP_POSITIONS = [
  { value: "utg", label: "UTG" },
  { value: "hijack", label: "Hijack" },
  { value: "cutoff", label: "Cutoff" },
  { value: "button", label: "Button" },
  { value: "small_blind", label: "Small blind" },
  { value: "big_blind", label: "Big blind" },
] as const;

export const PREFLOP_POSITION_ALIASES: Readonly<
  Record<string, PreflopPosition>
> = {
  utg: "utg",
  "under the gun": "utg",
  ep: "utg",
  "early position": "utg",
  hj: "hijack",
  hijack: "hijack",
  mp: "hijack",
  "middle position": "hijack",
  co: "cutoff",
  cutoff: "cutoff",
  btn: "button",
  button: "button",
  dealer: "button",
  sb: "small_blind",
  "small blind": "small_blind",
  bb: "big_blind",
  "big blind": "big_blind",
};

export function normalizePreflopPosition(
  value: string | null | undefined,
): PreflopPosition | null {
  if (!value) {
    return null;
  }
  const normalized = value
    .toLowerCase()
    .replace(/[_-]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
  return PREFLOP_POSITION_ALIASES[normalized] ?? null;
}
