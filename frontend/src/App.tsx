import AuthGate from "./components/AuthGate";
import DashboardLayout from "./components/DashboardLayout";
import MemoryCard from "./components/MemoryCard";
import UpcomingEventsCard from "./components/UpcomingEventsCard";
import EmailSummariesCard from "./components/EmailSummariesCard";
import SourcesStatusCard from "./components/SourcesStatusCard";
import TriageCard from "./components/TriageCard";
import QuickChatCard from "./components/QuickChatCard";
import AdminCard from "./components/AdminCard";
import RecentNotesCard from "./components/RecentNotesCard";
import ErrorBoundary from "./components/ErrorBoundary";

export default function App() {
  return (
    <AuthGate>
      <DashboardLayout>
        <ErrorBoundary><UpcomingEventsCard /></ErrorBoundary>
        <ErrorBoundary><EmailSummariesCard /></ErrorBoundary>
        <ErrorBoundary><RecentNotesCard /></ErrorBoundary>
        <ErrorBoundary><SourcesStatusCard /></ErrorBoundary>
        <ErrorBoundary><TriageCard /></ErrorBoundary>
        <ErrorBoundary><QuickChatCard /></ErrorBoundary>
        <ErrorBoundary><MemoryCard /></ErrorBoundary>
        <ErrorBoundary><AdminCard /></ErrorBoundary>
      </DashboardLayout>
    </AuthGate>
  );
}
