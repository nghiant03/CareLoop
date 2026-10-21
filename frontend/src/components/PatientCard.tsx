import type { Patient } from '../types';

interface PatientCardProps {
  patient: Patient;
  selected?: boolean;
  onClick?: () => void;
  action?: React.ReactNode;
}

export default function PatientCard({ patient, selected, onClick, action }: PatientCardProps) {
  return (
    <div
      onClick={onClick}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          onClick?.();
        }
      }}
      className={`cursor-pointer border bg-card p-4 transition-colors hover:bg-panel ${
        selected ? 'border-ink bg-panel' : 'border-rule'
      }`}
    >
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="micro-label">{patient.id}</p>
          <h3 className="mt-0.5 text-base font-semibold text-ink">
            {patient.name || `Patient ${patient.id}`}
          </h3>
          <p className="text-sm text-ink-3">
            {patient.age} yrs · {patient.sex}
          </p>
        </div>
        <div className="flex items-center gap-2">
          {selected && <span className="flag flag-neutral">Selected</span>}
          {action}
        </div>
      </div>

      <div className="mt-3 flex flex-wrap gap-1.5">
        {patient.diagnoses?.map((d) => (
          <span key={d} className="flag flag-neutral">
            {d}
          </span>
        ))}
      </div>

      <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 border-t border-rule pt-2.5 text-xs">
        {patient.egfr !== undefined && (
          <span className="text-ink-3">
            eGFR <span className="num font-medium text-ink-2">{patient.egfr}</span>
          </span>
        )}
        {patient.serum_k !== undefined && (
          <span className="text-ink-3">
            K <span className="num font-medium text-ink-2">{patient.serum_k}</span>
          </span>
        )}
        {patient.serum_po4 !== undefined && (
          <span className="text-ink-3">
            PO₄ <span className="num font-medium text-ink-2">{patient.serum_po4}</span>
          </span>
        )}
      </div>
    </div>
  );
}
