import { useEffect, useState } from 'react';
import { NavLink, useNavigate } from 'react-router-dom';
import WorkspaceHeader from './WorkspaceHeader';
import { listPatients } from '../api';
import type { Patient } from '../types';
import { DEFAULT_REVIEWER, VIEW_HOME, useDemo, type DemoView } from '../demo/context';

interface Section { to: string; code: string; label: string; end?: boolean }

const CLINICIAN_SECTIONS: Section[] = [
  { to: '/', code: 'ENV', label: 'Review', end: true },
  { to: '/review-queue', code: 'QUE', label: 'Queue' },
  { to: '/simulations', code: 'SIM', label: 'What-if' },
  { to: '/plan', code: 'PLN', label: 'Meal Plan' },
  { to: '/chat', code: 'CHT', label: 'Chat' },
  { to: '/adherence', code: 'ADH', label: 'Adherence' },
];

const PATIENT_SECTIONS: Section[] = [
  { to: '/plan', code: 'PLN', label: 'My meal plan' },
  { to: '/adherence', code: 'ADH', label: 'Log meals' },
  { to: '/chat', code: 'CHT', label: 'Ask a question' },
];

export default function TopBar() {
  const demo = useDemo();
  const navigate = useNavigate();
  const sections = demo.view === 'patient' ? PATIENT_SECTIONS : CLINICIAN_SECTIONS;

  const switchView = (view: DemoView) => {
    if (view === demo.view) return;
    demo.setView(view);
    navigate(VIEW_HOME[view]);
  };

  return (
    <>
      <WorkspaceHeader label={demo.view === 'patient' ? 'Patient app' : 'Clinical nutrition'}>
        <nav aria-label="Main navigation" className="workspace-navigation">
          {sections.map((s) => (
            <NavLink
              key={s.to}
              to={s.to}
              end={s.end}
              className={({ isActive }) =>
                `workspace-nav-link ${isActive ? 'is-active' : ''}`
              }
            >
              {s.label}
            </NavLink>
          ))}
        </nav>
      </WorkspaceHeader>
      <DemoControls onSwitchView={switchView} />
    </>
  );
}

function Segmented<T extends string>({ label, value, options, onChange, disabled }: {
  label: string;
  value: T | null;
  options: { value: T; label: string }[];
  onChange: (value: T) => void;
  disabled?: boolean;
}) {
  return (
    <div role="group" aria-label={label} className="inline-flex overflow-hidden rounded-md border border-rule-2 bg-card">
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          aria-pressed={value === o.value}
          disabled={disabled}
          onClick={() => onChange(o.value)}
          className={`px-3 py-1.5 text-sm font-semibold transition-colors disabled:opacity-50 ${
            value === o.value ? 'bg-line text-white' : 'text-ink-2 hover:bg-panel'
          }`}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

function DemoControls({ onSwitchView }: { onSwitchView: (view: DemoView) => void }) {
  const demo = useDemo();
  const [patients, setPatients] = useState<Patient[]>([]);

  useEffect(() => {
    if (demo.view !== 'patient' || patients.length > 0) return;
    let active = true;
    listPatients()
      .then((data) => { if (active) setPatients(data || []); })
      .catch(() => { if (active) setPatients([]); });
    return () => { active = false; };
  }, [demo.view, patients.length]);

  const mode = demo.approvalMode === 'auto' || demo.approvalMode === 'clinician' ? demo.approvalMode : null;

  return (
    <section aria-label="Demo controls" className="border-b border-rule bg-panel px-4 py-2 text-sm sm:px-6 lg:px-8">
      <div className="mx-auto flex max-w-7xl flex-wrap items-center gap-x-6 gap-y-2">
        <div className="flex items-center gap-2">
          <span className="micro-label">View</span>
          <Segmented
            label="Demo view"
            value={demo.view}
            onChange={onSwitchView}
            options={[{ value: 'clinician', label: 'Clinician' }, { value: 'patient', label: 'Patient' }]}
          />
        </div>

        {demo.view === 'patient' ? (
          <div className="flex items-center gap-2">
            <label htmlFor="demo-acting-as" className="micro-label">Acting as</label>
            <select
              id="demo-acting-as"
              value={demo.patientId || ''}
              onChange={(e) => demo.setPatientId(e.target.value || null)}
              className="field w-auto min-h-0 py-1.5"
            >
              <option value="">Select a patient</option>
              {patients.map((p) => (
                <option key={p.id} value={p.id}>{p.name || p.id}</option>
              ))}
            </select>
          </div>
        ) : (
          <>
            <div className="flex items-center gap-2">
              <label htmlFor="demo-reviewer" className="micro-label">Reviewer name</label>
              <input
                id="demo-reviewer"
                type="text"
                value={demo.reviewerName}
                placeholder={DEFAULT_REVIEWER}
                onChange={(e) => demo.setReviewerName(e.target.value)}
                className="field w-44 min-h-0 py-1.5"
              />
            </div>
            <div className="flex items-center gap-2">
              <span className="micro-label">Approval</span>
              <Segmented
                label="Approval mode"
                value={mode}
                disabled={demo.approvalModeSwitching || demo.approvalMode === 'loading'}
                onChange={(next) => { if (next !== mode) void demo.changeApprovalMode(next); }}
                options={[{ value: 'auto', label: 'Auto (demo)' }, { value: 'clinician', label: 'Manual review' }]}
              />
              {demo.approvalModeError && (
                <span role="alert" className="text-flag">{demo.approvalModeError}</span>
              )}
            </div>
          </>
        )}

        <p className="text-xs text-ink-3 sm:ml-auto">
          Demo switches only — not sign-in or access control.
        </p>
      </div>
    </section>
  );
}
