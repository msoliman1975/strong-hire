/** Radio options that show a name and a one-line hint (session setup). */
export function Choices<T extends string>(props: {
  legend: string;
  name: string;
  options: T[];
  value: T;
  onChange: (v: T) => void;
  label: (v: T) => string;
  hint?: (v: T) => string;
  disabled?: (v: T) => boolean;
  describedBy?: string;
}) {
  return (
    <fieldset aria-describedby={props.describedBy}>
      <legend className="label">{props.legend}</legend>
      <div className="choices">
        {props.options.map((o) => (
          <label key={o} className="choice">
            <input
              type="radio"
              name={props.name}
              value={o}
              checked={props.value === o}
              disabled={props.disabled?.(o)}
              onChange={() => props.onChange(o)}
            />
            <span className="choice__name">{props.label(o)}</span>
            {props.hint && <span className="choice__hint">{props.hint(o)}</span>}
          </label>
        ))}
      </div>
    </fieldset>
  );
}
