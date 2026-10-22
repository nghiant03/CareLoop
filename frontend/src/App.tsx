import { Navigate, Routes, Route, useLocation } from 'react-router-dom';
import KnowledgeWorkspaceScreen from './screens/KnowledgeWorkspaceScreen';
import TopBar from './components/TopBar';
import OfflineBanner from './components/OfflineBanner';
import ApprovalModeBanner from './components/ApprovalModeBanner';
import ClinicianReviewScreen from './screens/ClinicianReviewScreen';
import PatientMealPlanScreen from './screens/PatientMealPlanScreen';
import ChatScreen from './screens/ChatScreen';
import AdherenceScreen from './screens/AdherenceScreen';
import ReviewQueueScreen from './screens/ReviewQueueScreen';
import SimulationScreen from './screens/SimulationScreen';
import DemoProvider from './demo/DemoProvider';
import { PATIENT_ROUTES, useDemo } from './demo/context';

function AppRoutes() {
  const location = useLocation();
  const demo = useDemo();
  if (demo.view === 'patient' && !PATIENT_ROUTES.has(location.pathname)) {
    return <Navigate to="/plan" replace />;
  }
  return (
    <Routes>
      <Route path="/" element={<ClinicianReviewScreen />} />
      <Route path="/plan" element={<PatientMealPlanScreen />} />
      <Route path="/chat" element={<ChatScreen />} />
      <Route path="/adherence" element={<AdherenceScreen />} />
      <Route path="/review-queue" element={<ReviewQueueScreen />} />
      <Route path="/simulations" element={<SimulationScreen />} />
    </Routes>
  );
}

function AppContent() {
  const location = useLocation();
  if (location.pathname === '/knowledge-review') return <KnowledgeWorkspaceScreen />;
  return (
    <DemoProvider>
      <div className="min-h-screen bg-paper">
        <TopBar />
        <OfflineBanner />
        <ApprovalModeBanner />
        <AppRoutes />
      </div>
    </DemoProvider>
  );
}

function App() {
  return <AppContent />;
}

export default App;
