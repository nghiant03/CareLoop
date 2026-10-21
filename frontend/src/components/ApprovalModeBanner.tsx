import { useEffect, useState } from 'react';
import { getApprovalMode } from '../api';
import { useDemo, type ApprovalModeState } from '../demo/context';

export default function ApprovalModeBanner() {
  const demo = useDemo();
  const [fallbackMode, setFallbackMode] = useState<ApprovalModeState>('loading');

  useEffect(() => {
    if (demo.managed) return;
    let mounted = true;
    const check = async () => {
      try {
        const selected = await getApprovalMode();
        if (mounted) setFallbackMode(selected);
      } catch {
        if (mounted) setFallbackMode('unknown');
      }
    };
    void check();
    const interval = setInterval(check, 10000);
    return () => {
      mounted = false;
      clearInterval(interval);
    };
  }, [demo.managed]);

  const mode = demo.managed ? demo.approvalMode : fallbackMode;

  if (mode === 'clinician') return null;

  return (
    <aside
      aria-label="Approval policy"
      role="status"
      className="border-b border-warn-rule bg-warn-bg px-4 py-2.5 text-sm"
    >
      <div className="mx-auto flex max-w-7xl items-start gap-3">
        <span className="flag flag-warn mt-0.5 shrink-0">Notice</span>
        <p className="text-warn">
          {mode === 'auto'
            ? 'Demo mode — new targets are auto-approved, not clinically reviewed. Clinician review and the review queue simulate a clinician role. Edits require manual re-approval.'
            : mode === 'loading'
              ? 'Checking approval mode… Do not assume targets have been clinically reviewed.'
              : 'Approval mode unavailable. Do not assume clinical review; checking again automatically.'}
        </p>
      </div>
    </aside>
  );
}
