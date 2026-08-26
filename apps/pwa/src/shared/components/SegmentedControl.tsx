import { ButtonControl } from "./FormControls";

type SegmentedControlOption<Value extends string> = {
  disabled?: boolean;
  label: string;
  value: Value;
};

type SegmentedControlProps<Value extends string> = {
  ariaLabel: string;
  className?: string;
  disabled?: boolean;
  onChange: (value: Value) => void;
  options: readonly SegmentedControlOption<Value>[];
  value: Value | "";
};

export function SegmentedControl<Value extends string>({
  ariaLabel,
  className,
  disabled = false,
  onChange,
  options,
  value,
}: SegmentedControlProps<Value>) {
  return (
    <div className={className} role="group" aria-label={ariaLabel}>
      {options.map((option) => (
        <ButtonControl
          key={option.value}
          variant="unstyled"
          className={value === option.value ? "active" : undefined}
          aria-pressed={value === option.value}
          onClick={() => onChange(option.value)}
          disabled={disabled || option.disabled}
        >
          {option.label}
        </ButtonControl>
      ))}
    </div>
  );
}
