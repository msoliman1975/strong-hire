/**
 * ST-3 "New story": a manual story. A title and optional skill tags; the parts are written in the
 * workbench, where the new story opens. `?skill=` picks a tag first (the Home coverage map links here).
 */
import "./stories.css";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Link, useNavigate, useSearchParams } from "react-router";

import { COMPETENCIES_BY_TYPE } from "../../api/questions";
import { ErrorNotice, PageHead } from "../../components/ui";
import { storiesApi, storyKeys, type Competency } from "./api";
import { storiesPath, storyPath } from "./paths";
import { SkillPicker } from "./SkillPicker";

const SKILLS = Object.values(COMPETENCIES_BY_TYPE).flat() as Competency[];

export function NewStoryPage() {
  const [params] = useSearchParams();
  const first = SKILLS.find((c) => c === params.get("skill"));
  const [title, setTitle] = useState("");
  const [skills, setSkills] = useState<Competency[]>(first ? [first] : []);
  const [missing, setMissing] = useState(false);
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const create = useMutation({
    mutationFn: () => storiesApi.create({ title: title.trim(), skills, source: "manual" }),
    onSuccess: (story) => {
      void queryClient.invalidateQueries({ queryKey: storyKeys.all });
      navigate(storyPath(story.id), { replace: true });
    },
  });

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (title.trim() === "") {
      setMissing(true);
      return;
    }
    create.mutate();
  };

  return (
    <div className="stories stack">
      <PageHead title="New story" eyebrow="A · Story studio" />
      <form className="card stack" onSubmit={submit} noValidate>
        <div className="field">
          <label htmlFor="new-story-title">Title</label>
          <p className="hint" id="new-story-title-hint">
            A few words you will recognize, like “Checkout migration”.
          </p>
          <input
            id="new-story-title"
            type="text"
            value={title}
            maxLength={200}
            aria-describedby="new-story-title-hint"
            aria-invalid={missing || undefined}
            onChange={(e) => {
              setTitle(e.target.value);
              setMissing(false);
            }}
          />
          {missing && (
            <p className="field-error" role="alert">
              Give the story a title.
            </p>
          )}
        </div>
        <SkillPicker value={skills} onChange={setSkills} />
        {create.isError && <ErrorNotice error={create.error} />}
        <div className="stories__actions">
          <button className="btn" type="submit" disabled={create.isPending}>
            {create.isPending ? "Creating" : "Create story"}
          </button>
          <Link className="btn btn--secondary" to={storiesPath}>
            Cancel
          </Link>
        </div>
      </form>
    </div>
  );
}
