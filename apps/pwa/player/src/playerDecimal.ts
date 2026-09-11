const DECIMAL_STRING =
  /^([+-]?)(?:(\d+)(?:\.(\d*))?|\.(\d+))(?:[eE]([+-]?\d+))?$/;
const MAX_EXPANDED_PERCENTAGE_ZEROS = 1_000n;

function formatDecimalPercentage(digits: string, power: bigint): string {
  if (power >= 0n) {
    return power > MAX_EXPANDED_PERCENTAGE_ZEROS
      ? `${digits}e+${power}`
      : digits + "0".repeat(Number(power));
  }

  const decimalIndex = BigInt(digits.length) + power;
  if (decimalIndex > 0n) {
    const index = Number(decimalIndex);
    return digits.slice(0, index) + "." + digits.slice(index);
  }

  const leadingZeros = -decimalIndex;
  return leadingZeros > MAX_EXPANDED_PERCENTAGE_ZEROS
    ? `${digits}e${power}`
    : "0." + "0".repeat(Number(leadingZeros)) + digits;
}

/** Format a backend unit-interval Decimal as an exact percentage, or reject it. */
export function unitIntervalPercentage(value: string): string | null {
  const match = DECIMAL_STRING.exec(value);
  if (!match) return null;

  const fractionalDigits = match[3] ?? match[4] ?? "";
  let digits = ((match[2] ?? "") + fractionalDigits).replace(/^0+/, "");
  if (!digits) return "0";

  let decimalPower: bigint;
  try {
    decimalPower = BigInt(match[5] ?? "0") - BigInt(fractionalDigits.length);
  } catch {
    return null;
  }
  while (digits.endsWith("0")) {
    digits = digits.slice(0, -1);
    decimalPower += 1n;
  }

  const integerDigits = BigInt(digits.length) + decimalPower;
  if (
    match[1] === "-" ||
    (integerDigits === 1n && !(digits === "1" && decimalPower === 0n)) ||
    integerDigits > 1n
  ) {
    return null;
  }
  return formatDecimalPercentage(digits, decimalPower + 2n);
}
