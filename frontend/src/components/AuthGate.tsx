import { useState, useEffect, type ReactNode } from "react";
import { setApiKey, clearApiKey, getApiKey, getMemoryFacts } from "../services/api";

export default function AuthGate({ children }: { children: ReactNode }): ReactNode {
  const [authenticated, setAuthenticated] = useState(false);
  const [checking, setChecking] = useState(true);
  const [token, setToken] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    const handler = () => setAuthenticated(false);
    window.addEventListener("auth-required", handler);
    return () => window.removeEventListener("auth-required", handler);
  }, []);

  useEffect(() => {
    const verify = async () => {
      const key = getApiKey();
      if (key) {
        setApiKey(key);
      }
      try {
        await getMemoryFacts();
        setAuthenticated(true);
      } catch (e) {
        if (e instanceof Error && e.message.includes("401")) {
          clearApiKey();
        }
      } finally {
        setChecking(false);
      }
    };
    verify();
  }, []);

  const handleSubmit = async () => {
    setError("");
    setApiKey(token);
    try {
      await getMemoryFacts();
      setAuthenticated(true);
    } catch (e) {
      if (e instanceof Error && e.message.includes("401")) {
        setError("Invalid API key");
        clearApiKey();
      } else {
        setError("Cannot reach backend. Check that the server is running.");
        clearApiKey();
      }
    }
  };

  if (checking) {
    return (
      <div className="flex items-center justify-center min-h-screen bg-gray-900">
        <p className="text-gray-400">Verifying...</p>
      </div>
    );
  }

  if (!authenticated) {
    return (
      <div className="flex items-center justify-center min-h-screen bg-gray-900">
        <div className="bg-gray-800 p-8 rounded-lg shadow-lg max-w-md w-full">
          <h2 className="text-xl font-bold text-white mb-4">AI Assistant</h2>
          <p className="text-gray-400 mb-6">Enter your API key to continue</p>
          <form onSubmit={(e) => { e.preventDefault(); handleSubmit(); }}>
            <input
              type="password"
              value={token}
              onChange={(e) => setToken(e.target.value)}
              placeholder="API Key"
              className="w-full px-4 py-2 bg-gray-700 text-white rounded border border-gray-600 focus:border-blue-500 focus:outline-none mb-4"
            />
            {error && <p className="text-red-400 text-sm mb-4">{error}</p>}
            <button type="submit" className="w-full py-2 bg-blue-600 text-white rounded hover:bg-blue-700">
              Connect
            </button>
          </form>
        </div>
      </div>
    );
  }

  return <>{children}</>;
}
