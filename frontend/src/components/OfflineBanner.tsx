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
    <div className="bg-amber-50 px-4 py-2 text-sm text-amber-800">
      <div className="mx-auto flex max-w-7xl items-center gap-2">
        <span className="inline-flex h-2 w-2 flex-shrink-0 rounded-full bg-amber-400 animate-pulse" />
        <span className="font-medium">Backend offline</span>
        <span className="text-amber-700">— some features are unavailable until the API is reachable.</span>
      </div>
    </div>
  );
}
