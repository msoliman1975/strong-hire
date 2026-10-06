/** AC-2: the training-data consent toggle. Used at sign-up and on the account page. */
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
          Use my transcripts to improve Strong Hire
        </label>
        <p id="training-consent-hint" className="muted">
          Off by default. When on, your interview transcripts can train our models after we remove
          names, employers, emails and phone numbers. Audio is never kept. You can change this at any
          time on the account page.
        </p>
      </div>
    </div>
  );
}
