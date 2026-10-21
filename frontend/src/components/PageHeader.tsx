interface PageHeaderProps {
  /** Department code in the report vocabulary, e.g. ENV, QUE, SIM. */
  code: string;
  title: string;
  children?: React.ReactNode;
}

export default function PageHeader({ code, title, children }: PageHeaderProps) {
  return (
    <div className="mb-6 border-b border-rule-2 pb-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h1 className="text-2xl font-bold tracking-tight text-ink">{title}</h1>
        <span className="micro-label">CL·{code}</span>
      </div>
      {children && <div className="mt-1 max-w-2xl text-sm text-ink-3">{children}</div>}
    </div>
  );
}
