import { API_BASE_URL } from "../api";

const AUTH_ERRORS: Record<string, string> = {
  not_invited:
    "That Google account isn't on the invite list yet. Ask the owner to add your email.",
  denied: "Sign-in was cancelled.",
  state_mismatch: "Sign-in expired — please try again.",
  exchange_failed: "Google sign-in failed — please try again.",
  scope: "The granted permissions didn't match what the app needs. Try again.",
};

export function SignInPage() {
  const params = new URLSearchParams(window.location.search);
  const errorCode = params.get("auth_error");
  const errorMessage = errorCode
    ? (AUTH_ERRORS[errorCode] ?? "Sign-in failed — please try again.")
    : null;

  return (
    <main className="signin">
      <div className="signin-card">
        <h1>Dashboard</h1>
        <p className="signin-sub">
          Your tasks, calendar, and notes in one place.
        </p>
        {errorMessage && <p className="signin-error">{errorMessage}</p>}
        <a className="signin-btn" href={`${API_BASE_URL}/auth/login`}>
          Sign in with Google
        </a>
        <p className="signin-fine">
          You'll grant access to Google Tasks, Calendar (read-only), and a
          single app-created notes doc.
        </p>
      </div>
    </main>
  );
}
