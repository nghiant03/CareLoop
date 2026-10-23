import { useState } from 'react';
import {
  NavLink,
  Navigate,
  Route,
  Routes,
  useLocation,
  useNavigate,
} from 'react-router-dom';
import WorkspaceHeader from './components/WorkspaceHeader';
import PageHeader from './components/PageHeader';
import { type Actor, type Patient, type Role } from './api';
import { Feedback } from './components/shared';
import { Session, useResource } from './state';
import Patients from './screens/Patients';
import Foods from './screens/Foods';
import Plans from './screens/Plans';
import Logging from './screens/Logging';
import Evidence from './screens/Evidence';
import Chat from './screens/Chat';
import { workspaces, workspaceDescriptions } from './navigation';

const screens = {
  patients: Patients,
  plans: Plans,
  logging: Logging,
  chat: Chat,
  foods: Foods,
  evidence: Evidence,
};

export default function App() {
  const [actor, setActor] = useState<Actor>({
    name: 'Demo clinician',
    role: 'clinician',
  });
  const [patientId, setPatientId] = useState('');
  const [version, setVersion] = useState(0);
  const [page, setPage] = useState(0);
  const patients = useResource<Patient[]>(
    actor.role === 'reviewer'
      ? null
      : `/patients?limit=100&offset=${page * 100}`,
    version,
  );
  const health = useResource<{ status: string }>('/health', version);
  const navigate = useNavigate();
  const location = useLocation();
  const navigation = workspaces[actor.role];
  const home = navigation[0].to;
  const heading =
    navigation.find((item) => item.to === location.pathname)?.label ??
    'CareLoop';
  return (
    <Session.Provider
      value={{
        actor,
        patientId,
        refreshPatients: () => setVersion((v) => v + 1),
      }}
    >
      <div className="min-h-screen bg-paper">
        <a
          className="sr-only focus:not-sr-only focus:absolute focus:p-3 focus:bg-card focus:z-50"
          href="#main"
        >
          Skip to content
        </a>
        <WorkspaceHeader label="Reviewed nutrition">
          <nav className="workspace-navigation" aria-label="Main navigation">
            {navigation.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end
                className={({ isActive }) =>
                  `workspace-nav-link ${isActive ? 'is-active' : ''}`
                }
              >
                {item.label}
              </NavLink>
            ))}
          </nav>
        </WorkspaceHeader>
        <section
          className="border-b border-rule bg-panel px-4 py-3 sm:px-6"
          aria-label="Demo role and patient"
        >
          <div className="max-w-7xl mx-auto flex flex-wrap items-end gap-4">
            <label>
              <span className="micro-label block mb-1">Demo role</span>
              <select
                className="field"
                value={actor.role}
                onChange={(e) => {
                  const role = e.target.value as Role;
                  setActor({ name: `Demo ${role}`, role });
                  navigate(workspaces[role][0].to);
                }}
              >
                <option value="clinician">Clinician</option>
                <option value="patient">Patient</option>
                <option value="reviewer">Reviewer</option>
              </select>
            </label>
            <label>
              <span className="micro-label block mb-1">
                Recorded actor label
              </span>
              <input
                className="field"
                maxLength={120}
                value={actor.name}
                onChange={(e) =>
                  setActor((a) => ({ ...a, name: e.target.value }))
                }
              />
            </label>
            {actor.role !== 'reviewer' && (
              <>
                <label className="flex-1 min-w-48">
                  <span className="micro-label block mb-1">Patient</span>
                  <select
                    className="field"
                    value={patientId}
                    onChange={(e) => setPatientId(e.target.value)}
                  >
                    <option value="">Select patient</option>
                    {patientId &&
                      !patients.data?.some((p) => p.id === patientId) && (
                        <option value={patientId}>
                          Selected patient · {patientId.slice(0, 8)}
                        </option>
                      )}
                    {patients.data?.map((p) => (
                      <option key={p.id} value={p.id}>
                        {p.body.display_name}
                      </option>
                    ))}
                  </select>
                </label>
                <div className="flex gap-2">
                  <button
                    className="btn-ghost"
                    disabled={!page || patients.loading}
                    onClick={() => setPage((p) => p - 1)}
                  >
                    Previous patients
                  </button>
                  <button
                    className="btn-ghost"
                    disabled={patients.data?.length !== 100 || patients.loading}
                    onClick={() => setPage((p) => p + 1)}
                  >
                    More patients
                  </button>
                </div>
              </>
            )}
            <p className="text-sm text-ink-3 basis-full">
              Demo roles label audit events; they are not authenticated
              identities. Approval is always explicit.
            </p>
          </div>
        </section>
        <main
          id="main"
          className="mx-auto max-w-7xl px-4 py-6 sm:px-6 lg:px-8 pb-12"
        >
          <PageHeader code="WORK" title={heading}>
            {workspaceDescriptions[actor.role]}
          </PageHeader>
          <Feedback error={patients.error || health.error} />
          {(patients.error || health.error) && (
            <button
              className="btn-ghost mb-4"
              onClick={() => setVersion((v) => v + 1)}
            >
              Retry API connection
            </button>
          )}
          <div key={`${patientId}-${actor.role}-${location.pathname}`}>
            <Routes>
              {navigation.map((item) => {
                const Screen = screens[item.screen];
                return (
                  <Route key={item.to} path={item.to} element={<Screen />} />
                );
              })}
              <Route path="*" element={<Navigate to={home} replace />} />
            </Routes>
          </div>
        </main>
      </div>
    </Session.Provider>
  );
}
