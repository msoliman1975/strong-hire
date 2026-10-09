import { useState, type ChangeEvent, type FormEvent } from "react";

import type { Level, Profile, ProfileIn } from "../api/types";
import { levelLabel } from "../labels";
import { ErrorNotice } from "./ui";

const LEVELS = Object.keys(levelLabel) as Level[];

/** The browser's time zone, the default for a new profile. */
export function browserTimeZone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || "";
  } catch {
    return "";
  }
}

function timeZones(current: string): string[] {
  let zones: string[];
  try {
    zones = Intl.supportedValuesOf("timeZone");
  } catch {
    zones = [];
  }
  return current && !zones.includes(current) ? [current, ...zones] : zones;
}

interface Draft {
  full_name: string;
  current_title: string;
  years_experience: string;
  target_level: Level | "";
  country: string;
  time_zone: string;
  linkedin_url: string;
}

type Errors = Partial<Record<keyof Draft, string>>;

export function toDraft(profile: Profile | undefined): Draft {
  return {
    full_name: profile?.full_name ?? "",
    current_title: profile?.current_title ?? "",
    years_experience: profile?.years_experience != null ? String(profile.years_experience) : "",
    target_level: profile?.target_level ?? "",
    country: profile?.country ?? "",
    time_zone: profile?.time_zone ?? browserTimeZone(),
    linkedin_url: profile?.linkedin_url ?? "",
  };
}

/** AC-3 form validation only. The API checks the same rules. */
export function validateProfile(d: Draft): Errors {
  const errors: Errors = {};
  if (!d.full_name.trim()) errors.full_name = "Enter your name.";
  else if (d.full_name.trim().length > 120) errors.full_name = "Use at most 120 characters.";
  const years = Number(d.years_experience);
  if (d.years_experience.trim() === "" || !Number.isInteger(years) || years < 0 || years > 50) {
    errors.years_experience = "Enter a whole number from 0 to 50.";
  }
  if (!d.target_level) errors.target_level = "Choose the level you are interviewing for.";
  const link = d.linkedin_url.trim().toLowerCase();
  if (link && !/^(https?:\/\/)?([a-z0-9-]+\.)*linkedin\.com(\/|$)/.test(link)) {
    errors.linkedin_url = "Use a linkedin.com address, or leave it empty.";
  }
  return errors;
}

function toBody(d: Draft): ProfileIn {
  const value = (s: string) => s.trim() || null;
  return {
    full_name: d.full_name.trim(),
    years_experience: Number(d.years_experience),
    target_level: d.target_level as Level,
    current_title: value(d.current_title),
    country: value(d.country),
    time_zone: value(d.time_zone),
    linkedin_url: value(d.linkedin_url),
  };
}

interface Props {
  initial: Profile | undefined;
  submitLabel: string;
  saving: boolean;
  error: unknown;
  onSave: (body: ProfileIn) => void;
}

/** AC-3: name, experience and target level are required; the rest is optional. No payment details. */
export function ProfileForm({ initial, submitLabel, saving, error, onSave }: Props) {
  const [draft, setDraft] = useState<Draft>(() => toDraft(initial));
  const [errors, setErrors] = useState<Errors>({});
  const set = (key: keyof Draft) => (e: ChangeEvent<HTMLInputElement | HTMLSelectElement>) =>
    setDraft((d) => ({ ...d, [key]: e.target.value }));

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    const found = validateProfile(draft);
    setErrors(found);
    if (Object.keys(found).length === 0) onSave(toBody(draft));
  };

  const fieldError = (key: keyof Draft) =>
    errors[key] ? (
      <p id={`${key}-error`} className="field-error">
        {errors[key]}
      </p>
    ) : null;
  const invalid = (key: keyof Draft) =>
    errors[key] ? { "aria-invalid": true as const, "aria-describedby": `${key}-error` } : {};

  return (
    <form className="panel" onSubmit={onSubmit} noValidate aria-label="Profile">
      <div className="field">
        <label htmlFor="full_name">Full name</label>
        <input
          id="full_name"
          type="text"
          autoComplete="name"
          maxLength={140}
          value={draft.full_name}
          onChange={set("full_name")}
          {...invalid("full_name")}
        />
        {fieldError("full_name")}
      </div>
      <div className="grid-2">
        <div className="field">
          <label htmlFor="years_experience">Years of experience</label>
          <input
            id="years_experience"
            type="number"
            inputMode="numeric"
            min={0}
            max={50}
            value={draft.years_experience}
            onChange={set("years_experience")}
            {...invalid("years_experience")}
          />
          {fieldError("years_experience")}
        </div>
        <div className="field">
          <label htmlFor="target_level">Level you are interviewing for</label>
          <select
            id="target_level"
            value={draft.target_level}
            onChange={set("target_level")}
            {...invalid("target_level")}
          >
            <option value="">Choose a level</option>
            {LEVELS.map((l) => (
              <option key={l} value={l}>
                {levelLabel[l]}
              </option>
            ))}
          </select>
          {fieldError("target_level")}
        </div>
      </div>
      <div className="field">
        <label htmlFor="current_title">Current job title (optional)</label>
        <input
          id="current_title"
          type="text"
          autoComplete="organization-title"
          maxLength={140}
          value={draft.current_title}
          onChange={set("current_title")}
        />
      </div>
      <div className="grid-2">
        <div className="field">
          <label htmlFor="country">Country (optional)</label>
          <input
            id="country"
            type="text"
            autoComplete="country-name"
            maxLength={100}
            value={draft.country}
            onChange={set("country")}
          />
        </div>
        <div className="field">
          <label htmlFor="time_zone">Time zone (optional)</label>
          <select id="time_zone" value={draft.time_zone} onChange={set("time_zone")}>
            <option value="">Not set</option>
            {timeZones(draft.time_zone).map((z) => (
              <option key={z} value={z}>
                {z.replaceAll("_", " ")}
              </option>
            ))}
          </select>
        </div>
      </div>
      <div className="field">
        <label htmlFor="linkedin_url">LinkedIn profile (optional)</label>
        <input
          id="linkedin_url"
          type="url"
          inputMode="url"
          placeholder="https://www.linkedin.com/in/your-name"
          maxLength={300}
          value={draft.linkedin_url}
          onChange={set("linkedin_url")}
          {...invalid("linkedin_url")}
        />
        {fieldError("linkedin_url")}
      </div>
      {error ? <ErrorNotice error={error} title="We could not save your profile." /> : null}
      <button type="submit" className="btn" disabled={saving}>
        {submitLabel}
      </button>
    </form>
  );
}
