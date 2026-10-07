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
      className={`rounded-xl border bg-white p-4 shadow-sm transition-all cursor-pointer hover:shadow-md hover:-translate-y-0.5 ${
        selected ? 'border-sky-500 ring-1 ring-sky-500' : 'border-slate-200'
      }`}
    >
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 className="text-base font-semibold text-slate-900">
            {patient.name || `Patient ${patient.id}`}
          </h3>
          <p className="text-sm text-slate-500">
            {patient.age} yrs · {patient.sex}
          </p>
        </div>
        {action}
      </div>

      <div className="mt-3 flex flex-wrap gap-1.5">
        {patient.diagnoses?.map((d) => (
          <Badge key={d} variant="primary">
            {d}
          </Badge>
        ))}
      </div>

      <div className="mt-3 flex flex-wrap gap-2 text-xs text-slate-600">
        {patient.egfr !== undefined && (
          <span className="rounded-md bg-slate-100 px-2 py-1">eGFR {patient.egfr}</span>
        )}
        {patient.serum_k !== undefined && (
          <span className="rounded-md bg-slate-100 px-2 py-1">K {patient.serum_k}</span>
        )}
        {patient.serum_po4 !== undefined && (
          <span className="rounded-md bg-slate-100 px-2 py-1">PO₄ {patient.serum_po4}</span>
        )}
      </div>
    </div>
  );
}

function Badge({
  children,
  variant = 'default',
}: {
  children: React.ReactNode;
  variant?: 'default' | 'primary';
}) {
  const classes =
    variant === 'primary'
      ? 'bg-sky-50 text-sky-700 ring-1 ring-sky-100'
      : 'bg-slate-100 text-slate-700';
  return (
    <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${classes}`}>
      {children}
    </span>
  );
}
