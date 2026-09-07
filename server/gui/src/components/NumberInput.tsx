import { useState } from "react";
import "../styles/number-input.css";
import { LiaMinusSolid, LiaPlusSolid } from "react-icons/lia";

type NumberInputProps = {
  label?: string;
  min?: number;
  max?: number;
  step?: number;
  defaultValue?: number;
  value?: number;
  onChange?: (value: number) => void;
  helperText?: string;
  id?: string;
  disabled?: boolean;
};

export function NumberInput({
  label = "Choose quantity:",
  min = 0,
  max = 99999,
  step = 1,
  defaultValue = 999,
  value,
  onChange,
  helperText,
  id = "quantity-input",
  disabled = false,
}: NumberInputProps) {
  const [internalValue, setInternalValue] = useState<number>(defaultValue);
  const isControlled = value !== undefined;
  const currentValue = isControlled ? value : internalValue;

  const clamp = (next: number) => {
    if (Number.isNaN(next)) return min;
    return Math.min(max, Math.max(min, next));
  };

  const updateValue = (next: number) => {
    if (disabled) return;

    const clamped = clamp(next);

    if (!isControlled) {
      setInternalValue(clamped);
    }

    onChange?.(clamped);
  };

  const handleInputChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    if (disabled) return;

    const raw = event.target.value.replace(/\D/g, "");
    const next = raw === "" ? min : Number(raw);
    updateValue(next);
  };

  const decrement = () => updateValue(currentValue - step);
  const increment = () => updateValue(currentValue + step);
  const helperId = helperText ? `${id}-helper` : undefined;

  return (
    <div className="number-input">
      {label && (
        <label htmlFor={id} className="number-input__label">
          {label}
        </label>
      )}
      <div className="number-input__wrapper">
        <button
          type="button"
          id={`${id}-decrement`}
          className="number-input__button number-input__button--left"
          aria-label="Decrease value"
          onClick={decrement}
          disabled={disabled}
        >
          <LiaMinusSolid />
        </button>

        <input
          type="text"
          id={id}
          inputMode="numeric"
          pattern="[0-9]*"
          value={String(currentValue)}
          onChange={handleInputChange}
          className="number-input__field"
          placeholder={String(defaultValue)}
          aria-describedby={helperId}
          maxLength={5}
          disabled={disabled}
        />

        <button
          type="button"
          id={`${id}-increment`}
          className="number-input__button number-input__button--right"
          aria-label="Increase value"
          onClick={increment}
          disabled={disabled}
        >
          <LiaPlusSolid />
        </button>
      </div>

      {helperText && (
        <p id={helperId} className="number-input__helper">
          {helperText}
        </p>
      )}
    </div>
  );
}

export default NumberInput;
