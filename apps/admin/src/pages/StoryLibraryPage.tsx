import { useState } from "react";

import { STORY_SOURCES, STORY_SOURCE_LABEL, usePart2Stories } from "../api/part2";
import { Kpi } from "../components/metrics";
import { ErrorNotice, Loading, PageHead } from "../components/ui";

const WEEK_CHOICES = [4, 8, 12] as const;

function num(value: number | null | undefined, digits = 1): string {
  return value === null || value === undefined ? "–" : value.toFixed(digits);
}

/**
 * AD-4: whether the story library is working. Counts, rates and delivery trends (DM-1) only;
 * the API never sends a story's title or text, so this page cannot show one.
 */
export function StoryLibraryPage() {
  const [weeks, setWeeks] = useState<number>(8);
  const stories = usePart2Stories(weeks);
  const data = stories.data;

  return (
    <>
      <PageHead title="Story library">
        <p>
          Whether candidates save and use stories, and how answers are delivered. Aggregate only: story text is never shown
          here. Weeks start Monday, UTC.
        </p>
      </PageHead>
      <div className="segmented" role="group" aria-label="Weeks">
        {WEEK_CHOICES.map((n) => (
          <button key={n} type="button" className="btn btn--small" aria-pressed={weeks === n} onClick={() => setWeeks(n)}>
            {n} weeks
          </button>
        ))}
      </div>

      {stories.isPending && <Loading label="Loading story metrics" />}
      {stories.isError && <ErrorNotice error={stories.error} />}
      {data && (
        <>
          <section className="section" aria-labelledby="story-kpis">
            <h2 id="story-kpis">Stories</h2>
            <div className="kpis">
              <Kpi label="Story save rate (30 days)" metric={data.story_save_rate} />
              <Kpi label="Stories per user" metric={data.stories_per_user} />
              <Kpi label="Draft to Proven rate" metric={data.draft_to_proven_rate} />
            </div>
            <p className="muted">
              Save rate cohort: {data.save_cohort.saved} of {data.save_cohort.users} users. {data.counts.total} stories (
              {data.counts.draft} draft, {data.counts.proven} proven) from {data.counts.users_with_stories} users.
            </p>
            <div className="kpis">
              {STORY_SOURCES.map((s) => (
                <div className="kpi" key={s}>
                  <p className="kpi__label">{STORY_SOURCE_LABEL[s]}</p>
                  <p className="kpi__value">{data.counts.by_source[s] ?? 0}</p>
                </div>
              ))}
            </div>
          </section>

          <section className="section" aria-labelledby="story-weeks">
            <h2 id="story-weeks">By week</h2>
            <div className="table-wrap">
              <table aria-label="Stories and delivery by week">
                <thead>
                  <tr>
                    <th scope="col">Week of</th>
                    <th scope="col">Stories saved</th>
                    <th scope="col">Answers measured</th>
                    <th scope="col">Words per minute</th>
                    <th scope="col">Fillers per minute</th>
                    <th scope="col">Answer length (s)</th>
                  </tr>
                </thead>
                <tbody>
                  {[...data.delivery].reverse().map((w) => {
                    const saved = data.stories_by_week.find((s) => s.week_start === w.week_start)?.saved ?? 0;
                    return (
                      <tr key={w.week_start}>
                        <td>{w.week_start.slice(0, 10)}</td>
                        <td className="num">{saved}</td>
                        <td className="num">{w.answers}</td>
                        <td className="num">{num(w.words_per_minute, 0)}</td>
                        <td className="num">{num(w.fillers_per_minute)}</td>
                        <td className="num">{num(w.duration_seconds, 0)}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </section>
        </>
      )}
    </>
  );
}
