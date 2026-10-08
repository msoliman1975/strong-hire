/**
 * AC-2: the training-data consent (users.training_consent). Off by default. When it is on, the
 * Strong Hire team may read the user's interview transcripts and the interviewer's reasoning in
 * the admin area (R2). When it is off, the team sees only metadata such as dates and scores.
 */
export const CONSENT_LABEL =
  "Let the Strong Hire team read my interview transcripts and the interviewer's reasoning to improve the product.";
export const CONSENT_HINT =
  "Optional. Off unless you turn it on. When it is off, the team sees only dates, settings and scores. Audio is never kept. You can change this any time in Account.";

/** The sign-up form: a plain, unticked checkbox. */
export function ConsentCheckbox({ checked, onChange }: { checked: boolean; onChange: (value: boolean) => void }) {
  return (
    <div className="check">
      <input
        id="training-consent"
        type="checkbox"
        checked={checked}
        aria-describedby="training-consent-hint"
        onChange={(e) => onChange(e.target.checked)}
      />
      <div>
        <label htmlFor="training-consent">{CONSENT_LABEL}</label>
        <p id="training-consent-hint" className="muted">
          {CONSENT_HINT}
        </p>
      </div>
    </div>
  );
}

/** The account page: a switch that saves at once. */
export function ConsentSwitch({
  checked,
  onChange,
  disabled = false,
}: {
  checked: boolean;
  onChange: (value: boolean) => void;
  disabled?: boolean;
}) {
  return (
    <div className="switch">
      <button
        type="button"
        role="switch"
        id="training-consent"
        aria-checked={checked}
        aria-describedby="training-consent-hint"
        disabled={disabled}
        onClick={() => onChange(!checked)}
      />
      <div>
        <label className="label" htmlFor="training-consent">
          {CONSENT_LABEL}
        </label>
        <p id="training-consent-hint" className="muted">
          {CONSENT_HINT}
        </p>
      </div>
    </div>
  );
}
