export const POSTFLOP_RANGE_SOURCE_LABELS: Record<string, string> = {
  preflop_chart_limped_pot: "Preflop chart · limped pot",
  preflop_chart_isolation_raised_pot: "Preflop chart · isolation-raised pot",
  preflop_chart_limp_reraised_pot: "Preflop chart · limp-reraised pot",
  preflop_chart_single_raised_pot: "Preflop chart · single-raised pot",
  preflop_chart_three_bet_pot: "Preflop chart · 3-bet pot",
  preflop_chart_cold_three_bet_pot: "Preflop chart · cold-call 3-bet pot",
  preflop_chart_squeeze_pot: "Preflop chart · squeeze pot",
  preflop_chart_four_bet_pot: "Preflop chart · 4-bet pot",
  preflop_chart_cold_four_bet_pot: "Preflop chart · cold 4-bet pot",
};

export function isContextualPostflopRangeSource(
  value: string | null,
): value is keyof typeof POSTFLOP_RANGE_SOURCE_LABELS {
  return (
    value !== null &&
    Object.prototype.hasOwnProperty.call(POSTFLOP_RANGE_SOURCE_LABELS, value)
  );
}
