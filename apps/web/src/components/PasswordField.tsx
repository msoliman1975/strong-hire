import { useState } from "react";

/** The password rules the API checks (AC-4): at least 12 characters, not the email name. */
export const PASSWORD_MIN = 12;

export function passwordRules(password: string, email: string) {
  const name = email.split("@")[0]?.trim().toLowerCase() ?? "";
  return {
    length: password.length >= PASSWORD_MIN,
    notEmail: password.length > 0 && !(name.length >= 3 && password.toLowerCase().includes(name)),
  };
}

export function passwordProblem(password: string, email: string): string | null {
  const rules = passwordRules(password, email);
  if (!rules.length) return `Use at least ${PASSWORD_MIN} characters.`;
  if (!rules.notEmail) return "Do not use your email name in the password.";
  return null;
}

/** A password input with a Show button, and for a new password, the rules as the user types. */
export function PasswordField({
  id,
  label,
  value,
  onChange,
  error,
  newPassword = false,
  email = "",
  extra,
}: {
  id: string;
  label: string;
  value: string;
  onChange: (value: string) => void;
  error?: string | null;
  newPassword?: boolean;
  email?: string;
  extra?: React.ReactNode;
}) {
  const [shown, setShown] = useState(false);
  const rules = passwordRules(value, email);
  const describedBy = [newPassword ? `${id}-rules` : null, error ? `${id}-error` : null].filter(Boolean).join(" ");
  return (
    <div className="field">
      <div className="field__row">
        <label htmlFor={id}>{label}</label>
        {extra}
      </div>
      <div className="password-input">
        <input
          id={id}
          type={shown ? "text" : "password"}
          autoComplete={newPassword ? "new-password" : "current-password"}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          aria-invalid={error ? true : undefined}
          aria-describedby={describedBy || undefined}
          maxLength={128}
        />
        <button
          type="button"
          className="password-input__toggle"
          aria-label="Show password"
          aria-pressed={shown}
          aria-controls={id}
          onClick={() => setShown((s) => !s)}
        >
          {shown ? "Hide" : "Show"}
        </button>
      </div>
      {newPassword && (
        <ul id={`${id}-rules`} className="password-rules">
          <li data-met={rules.length}>
            {PASSWORD_MIN}+ characters<span className="visually-hidden">{rules.length ? ", done" : ""}</span>
          </li>
          <li data-met={rules.notEmail}>
            Not your email<span className="visually-hidden">{rules.notEmail ? ", done" : ""}</span>
          </li>
        </ul>
      )}
      {error && (
        <p id={`${id}-error`} className="field-error">
          {error}
        </p>
      )}
    </div>
  );
}
