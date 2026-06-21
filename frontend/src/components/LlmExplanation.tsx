import { useState } from "react";
import { postApi } from "../api";
import { asDict, text } from "../lib/data";


export function LlmExplanation({
  endpoint,
  payload,
  label = "Explain with LLM",
}: {
  endpoint: string;
  payload?: unknown;
  label?: string;
}) {
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState("");
  const [error, setError] = useState("");

  async function run() {
    setLoading(true);
    setError("");
    try {
      const response = asDict(await postApi(endpoint, payload));
      const actionResult = asDict(response.result);
      setResult(text(actionResult.text, "No explanation returned."));
      if (!Boolean(actionResult.ok)) {
        setError(text(actionResult.text, "LLM explanation failed."));
      }
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="llm-explanation">
      <button className="quiet-button" disabled={loading} onClick={run}>
        {loading ? "Analyzing..." : label}
      </button>
      {result ? <p>{result}</p> : null}
      {error ? <p className="negative-text">{error}</p> : null}
    </div>
  );
}
