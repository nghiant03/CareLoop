import { Routes, Route } from 'react-router-dom';
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
  return (
    <div className="min-h-screen bg-paper">
      <TopBar />
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
