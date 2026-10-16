import { useEffect, useState } from "react";
import { getHealth, type Health } from "../services/api";

export default function App() {
  const [health, setHealth] = useState<Health | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getHealth()
      .then(setHealth)
      .catch((e: Error) => setError(e.message));
  }, []);

  return (
    <main className="page">
      <h1>Novaria Core</h1>
      {health && (
        <p role="status">
          API en ligne · version {health.version} · révision {health.revision}
        </p>
      )}
      {error && <p role="alert">{error}</p>}
    </main>
  );
}
