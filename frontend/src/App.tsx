import { FormEvent, useState } from "react";
import { getApiBaseUrl } from "./api/client";

type LoginState =
  | { kind: "idle" }
  | { kind: "loading" }
  | { kind: "error"; message: string };

export default function App() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [state, setState] = useState<LoginState>({ kind: "idle" });

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setState({ kind: "loading" });
    try {
      const response = await fetch(`${getApiBaseUrl()}/auth/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify({ username, password }),
      });
      if (!response.ok) {
        const body = await response.json().catch(() => null);
        throw new Error(
          body?.error?.message ||
            (response.status === 503
              ? "Autentikasi V3 belum dikonfigurasi"
              : "Login gagal"),
        );
      }
      const data = (await response.json()) as { access_token: string };
      localStorage.setItem("epv3_access_token", data.access_token);
      window.location.href = "/production.html";
    } catch (err) {
      setState({
        kind: "error",
        message: err instanceof Error ? err.message : "Login gagal",
      });
    }
  }

  return (
    <div className="shell">
      <header className="shell__header">
        <p className="brand">ETERNAL PRODUCTION V3</p>
        <p className="lede">
          Login V3 terpisah dari ERP V1. Inbox Accurate hanya setelah sesi sah.
        </p>
      </header>
      <main className="shell__main">
        <form className="login" onSubmit={onSubmit}>
          <label>
            Username
            <input
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              autoComplete="username"
              required
            />
          </label>
          <label>
            Password
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="current-password"
              required
            />
          </label>
          <button type="submit" disabled={state.kind === "loading"}>
            {state.kind === "loading" ? "Memverifikasi…" : "Masuk ke Production V49"}
          </button>
          {state.kind === "error" && (
            <p className="status__error" role="alert">
              {state.message}
            </p>
          )}
        </form>
        <p className="meta">API: {getApiBaseUrl()}</p>
      </main>
    </div>
  );
}
