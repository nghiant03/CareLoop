import type { ReactNode } from 'react';

interface WorkspaceHeaderProps {
  label: string;
  children?: ReactNode;
}

export default function WorkspaceHeader({ label, children }: WorkspaceHeaderProps) {
  return (
    <header className="workspace-header">
      <div className="workspace-header-inner">
        <div className="workspace-brand">
          <span className="workspace-wordmark">CareLoop</span>
          <span className="workspace-label">{label}</span>
        </div>
        {children}
      </div>
    </header>
  );
}
