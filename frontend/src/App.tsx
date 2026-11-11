import { useEffect, useState } from "react";
import {
  ApiClientError,
  fetchHealth,
  fetchReady,
  getApiBaseUrl,
  type HealthPayload,
  type ReadyPayload,
} from "./api/client";

type LoadState =
  | { kind: "loading" }
  | { kind: "ok"; health: HealthPayload; ready: ReadyPayload | null; readyError: string | null }
  | { kind: "error"; message: string };

export default function App() {
  const [state, setState] = useState<LoadState>({ kind: "loading" });

  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        const health = await fetchHealth();
        let ready: ReadyPayload | null = null;
        let readyError: string | null = null;
        try {
          ready = await fetchReady();
        } catch (err) {
          readyError =
            err instanceof ApiClientError
              ? `${err.code}: ${err.message}`
              : "Ready check failed";
        }
        if (!cancelled) {
          setState({ kind: "ok", health, ready, readyError });
        }
      } catch (err) {
        if (!cancelled) {
          const message =
            err instanceof ApiClientError
              ? `${err.code}: ${err.message}`
              : "Unable to reach backend health endpoint";
          setState({ kind: "error", message });
        }
      }
    }

    void load();
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className="shell">
      <header className="shell__header">
        <p className="brand">ETERNAL PRODUCTION V3</p>
        <p className="lede">Infrastructure status shell — no operational workflows yet.</p>
      </header>

      <main className="shell__main">
        <section className="status" aria-live="polite">
          <h1>Service status</h1>
          <p className="meta">API base: {getApiBaseUrl()}</p>

          {state.kind === "loading" && <p>Checking backend…</p>}

          {state.kind === "error" && (
            <p className="status__error" role="alert">
              {state.message}
            </p>
          )}

          {state.kind === "ok" && (
            <dl className="status__grid">
              <div>
                <dt>Health</dt>
                <dd>{state.health.status}</dd>
              </div>
              <div>
                <dt>Service</dt>
                <dd>{state.health.service}</dd>
              </div>
              <div>
                <dt>Version</dt>
                <dd>{state.health.version}</dd>
              </div>
              <div>
                <dt>Environment</dt>
                <dd>{state.health.environment}</dd>
              </div>
              <div>
                <dt>Database</dt>
                <dd>
                  {state.ready?.database ?? state.readyError ?? "unknown"}
                </dd>
              </div>
            </dl>
          )}
        </section>
      </main>
    </div>
  );
}
