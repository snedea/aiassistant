import { clearApiKey } from "../services/api";

function handleLogout(): void {
  clearApiKey();
  window.dispatchEvent(new CustomEvent("auth-required"));
}

export default function DashboardLayout({ children }: { children: React.ReactNode }): React.ReactElement {
  return (
    <div className="min-h-screen bg-gray-950 text-gray-100">
      <header className="border-b border-gray-800 bg-gray-900 px-6 py-4 flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold">AI Assistant</h1>
          <p className="text-sm text-gray-400">Dashboard</p>
        </div>
        <button
          onClick={handleLogout}
          className="px-3 py-1.5 text-sm text-gray-400 hover:text-white border border-gray-700 hover:border-gray-500 rounded transition-colors"
        >
          Logout
        </button>
      </header>
      <main className="mx-auto max-w-7xl p-6">
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-2 xl:grid-cols-3">
          {children}
        </div>
      </main>
    </div>
  );
}
