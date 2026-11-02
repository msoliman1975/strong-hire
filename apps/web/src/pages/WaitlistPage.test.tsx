/** L04 step 1: the public waitlist page and the confirm link, against the MSW mock API. */
import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { describe, expect, it } from "vitest";

import { AppRoutes, createQueryClient } from "../App";
import { server } from "../mocks/node";

function renderAt(path: string) {
  const user = userEvent.setup();
  render(
    <QueryClientProvider client={createQueryClient()}>
      <MemoryRouter initialEntries={[path]}>
        <AppRoutes />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return user;
}

function recordBodies(path: string): unknown[] {
  const bodies: unknown[] = [];
  server.events.on("request:start", async ({ request }) => {
    if (request.url.endsWith(path)) bodies.push(await request.clone().json());
  });
  return bodies;
}

describe("waitlist (L04)", () => {
  it("L04: needs an email and the interview timing, then asks to check email", async () => {
    const bodies = recordBodies("/api/public/waitlist");
    const user = renderAt("/waitlist?utm_source=reddit");
    expect(
      await screen.findByRole("heading", { name: "Find out if you'd get the offer, before the interview" }),
    ).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Join the waitlist" }));
    expect(screen.getByText("Enter an email address, for example name@example.com.")).toBeInTheDocument();
    expect(screen.getByText(/Choose one, so we can invite/)).toBeInTheDocument();
    expect(bodies).toHaveLength(0);

    await user.type(screen.getByLabelText("Email"), "ada@example.com");
    await user.click(screen.getByLabelText("In the next two weeks"));
    await user.selectOptions(screen.getByLabelText("Your field (optional)"), "Software engineering");
    await user.click(screen.getByRole("button", { name: "Join the waitlist" }));

    expect(await screen.findByRole("heading", { name: "Check your email" })).toBeInTheDocument();
    expect(bodies).toEqual([
      {
        email: "ada@example.com",
        interview_within: "two_weeks",
        role_family: "swe",
        marketing_consent: false,
        source: "reddit",
        website: null,
      },
    ]);
  });

  it("RF-10: every role family can join, for example finance", async () => {
    const bodies = recordBodies("/api/public/waitlist");
    const user = renderAt("/waitlist");
    const field = await screen.findByLabelText("Your field (optional)");
    expect(within(field).getAllByRole("option")).toHaveLength(13); // "Choose one" and 12 families
    await user.type(screen.getByLabelText("Email"), "fin@example.com");
    await user.click(screen.getByLabelText("In the next two weeks"));
    await user.selectOptions(field, "Finance");
    await user.click(screen.getByRole("button", { name: "Join the waitlist" }));
    expect(await screen.findByRole("heading", { name: "Check your email" })).toBeInTheDocument();
    expect(bodies).toEqual([expect.objectContaining({ email: "fin@example.com", role_family: "finance" })]);
  });

  it("L04: marketing email is a separate box that starts unticked", async () => {
    renderAt("/waitlist");
    const box = await screen.findByLabelText(/Also send me interview tips/);
    expect(box).not.toBeChecked();
  });

  it("L04: the email link confirms the place on the list", async () => {
    renderAt("/waitlist/confirm?token=valid");
    expect(await screen.findByRole("heading", { name: "You're on the list" })).toBeInTheDocument();
  });

  it("L04: a bad or missing link explains how to get a new one", async () => {
    renderAt("/waitlist/confirm?token=nope");
    expect(await screen.findByRole("heading", { name: "This link doesn't work" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Join the waitlist again" })).toHaveAttribute("href", "/waitlist");
  });
});
