import { Routes, Route, useLocation } from 'react-router-dom';
import TopBar from './components/TopBar';
import OfflineBanner from './components/OfflineBanner';
import ApprovalModeBanner from './components/ApprovalModeBanner';
import ClinicianReviewScreen from './screens/ClinicianReviewScreen';
import PatientMealPlanScreen from './screens/PatientMealPlanScreen';
import ChatScreen from './screens/ChatScreen';
import AdherenceScreen from './screens/AdherenceScreen';
import ReviewQueueScreen from './screens/ReviewQueueScreen';
import SimulationScreen from './screens/SimulationScreen';

function AppContent() {
  const location = useLocation();
  const activeScreen =
    location.pathname === '/plan'
      ? 'patient'
      : location.pathname === '/chat'
      ? 'chat'
      : location.pathname === '/adherence'
      ? 'adherence'
      : location.pathname === '/review-queue'
      ? 'review'
      : location.pathname === '/simulations'
      ? 'simulation'
      : 'clinician';

  return (
    <div className="min-h-screen bg-slate-50">
      <TopBar activeScreen={activeScreen} />
      <OfflineBanner />
      <ApprovalModeBanner />
      <Routes>
        <Route path="/" element={<ClinicianReviewScreen />} />
        <Route path="/plan" element={<PatientMealPlanScreen />} />
        <Route path="/chat" element={<ChatScreen />} />
        <Route path="/adherence" element={<AdherenceScreen />} />
        <Route path="/review-queue" element={<ReviewQueueScreen />} />
        <Route path="/simulations" element={<SimulationScreen />} />
      </Routes>
    </div>
  );
}

function App() {
  return <AppContent />;
}

export default App;
