import { Link } from 'react-router-dom';

interface TopBarProps {
  role: 'clinician' | 'patient' | 'chat' | 'adherence';
}

const roleLabel: Record<TopBarProps['role'], string> = {
  clinician: 'Clinician',
  patient: 'Meal Plan',
  chat: 'Chat',
  adherence: 'Adherence',
};

const roleClass: Record<TopBarProps['role'], string> = {
  clinician: 'bg-sky-100 text-sky-800',
  patient: 'bg-emerald-100 text-emerald-800',
  chat: 'bg-violet-100 text-violet-800',
  adherence: 'bg-amber-100 text-amber-800',
};

export default function TopBar({ role }: TopBarProps) {
  return (
    <header className="sticky top-0 z-50 border-b border-slate-200 bg-white/90 backdrop-blur">
      <div className="mx-auto flex h-14 max-w-7xl items-center justify-between px-4 sm:px-6 lg:px-8">
        <div className="flex items-center gap-3">
          <Link to="/" className="flex items-center gap-2">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-sky-600 text-white font-semibold">
              CL
            </div>
            <span className="text-lg font-semibold tracking-tight text-slate-900">CareLoop</span>
          </Link>
          <span
            className={`hidden sm:inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${roleClass[role]}`}
          >
            {roleLabel[role]}
          </span>
        </div>
        <nav className="flex items-center gap-1 sm:gap-2">
          <NavLink to="/" label="Review" />
          <NavLink to="/plan" label="Meal Plan" />
          <NavLink to="/chat" label="Chat" />
          <NavLink to="/adherence" label="Adherence" />
        </nav>
      </div>
    </header>
  );
}

function NavLink({ to, label }: { to: string; label: string }) {
  return (
    <Link
      to={to}
      className="rounded-md px-3 py-1.5 text-sm font-medium text-slate-600 hover:bg-slate-100 hover:text-slate-900 transition-colors"
    >
      {label}
    </Link>
  );
}
