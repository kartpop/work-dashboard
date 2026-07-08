import { SignInPage } from "./auth/SignInPage";
import { useAuth } from "./auth/useAuth";
import { DashboardPage } from "./DashboardPage";

export function App() {
  const auth = useAuth();
  if (auth.status === "loading") {
    return <div className="app-loading">Loading…</div>;
  }
  if (auth.status === "signedOut" || !auth.user) {
    return <SignInPage />;
  }
  return <DashboardPage user={auth.user} onSignOut={auth.signOut} />;
}
