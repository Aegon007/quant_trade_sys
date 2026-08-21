import { useState } from "react";
import { postApi } from "../api";
import { asDict, text } from "../lib/data";


export function LlmExplanation({
  endpoint,
  payload,
  label = "调用LLM解释",
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
      setResult(text(actionResult.text, "LLM没有返回解释。"));
      if (!Boolean(actionResult.ok)) {
        setError(text(actionResult.text, "LLM解释失败。"));
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
        {loading ? "正在分析..." : label}
      </button>
      {result ? <p>{result}</p> : null}
      {error ? <p className="negative-text">{error}</p> : null}
    </div>
  );
}
