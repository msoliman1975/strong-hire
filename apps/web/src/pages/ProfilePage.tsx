import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Link, useLocation, useNavigate } from "react-router";

import { accountApi } from "../api/account";
import { keys, useProfile } from "../api/hooks";
import type { AuthState, Profile } from "../api/types";
import { ProfileForm } from "../components/ProfileForm";
import { ErrorNotice, Loading, PageHead } from "../components/ui";

/** Save the profile and update the cached sign-in state, so the first sign-in gate opens at once. */
function useSaveProfile(onSaved: (profile: Profile) => void) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: accountApi.saveProfile,
    onSuccess: (profile) => {
      queryClient.setQueryData<Profile>(keys.profile, profile);
      queryClient.setQueryData<AuthState>(keys.me, (prev) =>
        prev?.user ? { ...prev, user: { ...prev.user, full_name: profile.full_name, profile_complete: true } } : prev,
      );
      onSaved(profile);
    },
  });
}

/** AC-3: asked once, right after the first sign-in. The app opens after the first save. */
export function WelcomePage() {
  const profile = useProfile();
  const navigate = useNavigate();
  const location = useLocation();
  const from = (location.state as { from?: string } | null)?.from;
  const save = useSaveProfile(() => navigate(from && from !== "/welcome" ? from : "/", { replace: true }));

  return (
    <div className="page--narrow">
      <PageHead title="Tell us about yourself">
        <p>
          This takes one minute. We use it to set the level of your interviews. We never ask for payment details
          here.
        </p>
      </PageHead>
      {profile.isPending && <Loading />}
      {profile.isError && <ErrorNotice error={profile.error} />}
      {profile.data && (
        <ProfileForm
          initial={profile.data}
          submitLabel="Save and continue"
          saving={save.isPending}
          error={save.error}
          onSave={(body) => save.mutate(body)}
        />
      )}
    </div>
  );
}

/** AC-3: edit the profile under Account, Profile. */
export function EditProfilePage() {
  const profile = useProfile();
  const save = useSaveProfile(() => undefined);

  return (
    <div className="page--narrow">
      <p>
        <Link to="/account">Back to Account</Link>
      </p>
      <PageHead title="Your profile" />
      {profile.isPending && <Loading />}
      {profile.isError && <ErrorNotice error={profile.error} />}
      {profile.data && (
        <ProfileForm
          initial={profile.data}
          submitLabel="Save profile"
          saving={save.isPending}
          error={save.error}
          onSave={(body) => save.mutate(body)}
        />
      )}
      <p role="status" className="muted">
        {save.isSuccess && "Saved. Your profile is up to date."}
      </p>
    </div>
  );
}
