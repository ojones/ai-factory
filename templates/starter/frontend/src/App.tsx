import { useEffect, useState } from "react";

/**
 * Trivial example component, present only to prove the frontend shape works
 * end to end: it builds, renders, and can call the backend's API. Real
 * Managed Apps replace this with actual product UI.
 */
export function App() {
  const [status, setStatus] = useState<string>("loading...");

  useEffect(() => {
    fetch("/api/health")
      .then((res) => res.json())
      .then((data: { status: string }) => setStatus(data.status))
      .catch(() => setStatus("unreachable"));
  }, []);

  return (
    <main>
      <h1>Starter Template</h1>
      <p>Backend health status: {status}</p>
    </main>
  );
}
