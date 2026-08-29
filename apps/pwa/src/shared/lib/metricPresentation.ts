export function benchmarkPercent(value: number): string {
  return `${Math.round(value * 100)}%`;
}

export function benchmarkFieldLabel(field: string): string {
  return field.replace(/_/g, " ");
}
