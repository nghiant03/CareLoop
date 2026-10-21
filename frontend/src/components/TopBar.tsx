import { NavLink, Link } from 'react-router-dom';

const SECTIONS: { to: string; code: string; label: string; end?: boolean }[] = [
  { to: '/', code: 'ENV', label: 'Review', end: true },
  { to: '/review-queue', code: 'QUE', label: 'Queue' },
  { to: '/simulations', code: 'SIM', label: 'What-if' },
  { to: '/plan', code: 'PLN', label: 'Meal Plan' },
  { to: '/chat', code: 'CHT', label: 'Chat' },
  { to: '/adherence', code: 'ADH', label: 'Adherence' },
];

export default function TopBar() {
  return (
    <header className="sticky top-0 z-50 border-b border-rule-2 bg-paper">
      <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
        <div className="flex flex-wrap items-end justify-between gap-x-6 gap-y-1 pt-3">
          <Link to="/" className="flex items-baseline gap-3 pb-2">
            <span className="text-xl font-bold tracking-tight text-ink">CareLoop</span>
            <span className="micro-label hidden sm:inline">Clinical nutrition report</span>
          </Link>
          <nav aria-label="Main navigation" className="flex flex-wrap">
            {SECTIONS.map((s) => (
              <NavLink
                key={s.to}
                to={s.to}
                end={s.end}
                className={({ isActive }) =>
                  `group flex items-baseline gap-1.5 border-b-2 px-3 pb-2 pt-1 text-sm font-medium transition-colors ${
                    isActive
                      ? 'border-ink text-ink'
                      : 'border-transparent text-ink-3 hover:border-rule-2 hover:text-ink'
                  }`
                }
              >
                <span className="font-mono text-[10px] font-medium tracking-[0.14em] text-ink-3 group-aria-[current=page]:text-ink">
                  {s.code}
                </span>
                {s.label}
              </NavLink>
            ))}
          </nav>
        </div>
      </div>
    </header>
  );
}
