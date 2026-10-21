import { useEffect, useState } from 'react';
import { healthz } from '../api';

export default function OfflineBanner() {
  const [online, setOnline] = useState<boolean | null>(null);

  useEffect(() => {
    let mounted = true;
    const check = async () => {
      try {
        await healthz();
        if (mounted) setOnline(true);
      } catch {
        if (mounted) setOnline(false);
      }
    };

    check();
    const id = setInterval(check, 10000);
    return () => {
      mounted = false;
      clearInterval(id);
    };
  }, []);

  if (online === true || online === null) return null;

  return (
    <div className="border-b border-flag-rule bg-flag-bg px-4 py-2 text-sm">
      <div className="mx-auto flex max-w-7xl items-center gap-3">
        <span className="flag flag-bad">Offline</span>
        <span className="text-flag">
          <span className="font-semibold">Backend offline</span> — some features are unavailable
          until the API is reachable.
        </span>
      </div>
    </div>
  );
}
