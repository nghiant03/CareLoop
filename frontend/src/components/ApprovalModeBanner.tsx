import { useEffect, useState } from 'react';
import { getApprovalMode } from '../api';

export default function ApprovalModeBanner() {
  const [mode, setMode] = useState<'auto' | 'clinician' | 'loading' | 'unknown'>('loading');

  useEffect(() => {
    let mounted = true;
    const check = async () => {
      try {
        const selected = await getApprovalMode();
        if (mounted) setMode(selected);
      } catch {
        if (mounted) setMode('unknown');
      }
    };
    void check();
    const interval = setInterval(check, 10000);
    return () => {
      mounted = false;
      clearInterval(interval);
    };
  }, []);

  if (mode === 'clinician') return null;

  return (
    <aside aria-label="Approval policy" role="status" className="bg-amber-50 px-4 py-3 text-sm text-amber-900">
      <p className="mx-auto max-w-7xl">
        {mode === 'auto'
          ? 'Demo mode — new targets are auto-approved, not clinically reviewed. Clinician review and the review queue simulate a clinician role. Edits require manual re-approval.'
          : mode === 'loading'
            ? 'Checking approval mode… Do not assume targets have been clinically reviewed.'
            : 'Approval mode unavailable. Do not assume clinical review; checking again automatically.'}
      </p>
    </aside>
  );
}
