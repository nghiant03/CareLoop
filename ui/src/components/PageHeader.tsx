interface PageHeaderProps {
  code: string;
  title: string;
  children?: React.ReactNode;
}

export default function PageHeader({ code, title, children }: PageHeaderProps) {
  return (
    <div className="page-header">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h1 className="text-2xl font-bold tracking-tight text-ink">{title}</h1>
        <span className="page-context">{code === 'KNW' ? 'Knowledge governance' : 'Clinical workspace'}</span>
      </div>
      {children && <div className="mt-2 max-w-2xl text-sm leading-relaxed text-ink-3">{children}</div>}
    </div>
  );
}
