import { Routes, Route, useLocation } from 'react-router-dom';
import TopBar from './components/TopBar';
import OfflineBanner from './components/OfflineBanner';
import ClinicianReviewScreen from './screens/ClinicianReviewScreen';
import PatientMealPlanScreen from './screens/PatientMealPlanScreen';
import ChatScreen from './screens/ChatScreen';
import AdherenceScreen from './screens/AdherenceScreen';

function AppContent() {
  const location = useLocation();
  const role =
    location.pathname === '/plan'
      ? 'patient'
      : location.pathname === '/chat'
      ? 'chat'
      : location.pathname === '/adherence'
      ? 'adherence'
      : 'clinician';

  return (
    <div className="min-h-screen bg-slate-50">
      <TopBar role={role} />
      <OfflineBanner />
      <Routes>
        <Route path="/" element={<ClinicianReviewScreen />} />
        <Route path="/plan" element={<PatientMealPlanScreen />} />
        <Route path="/chat" element={<ChatScreen />} />
        <Route path="/adherence" element={<AdherenceScreen />} />
      </Routes>
    </div>
  );
}

function App() {
  return <AppContent />;
}

export default App;
