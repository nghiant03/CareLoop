import { useEffect, useRef, useState } from 'react';
import type { Envelope, NutrientConstraint } from '../types';

interface EditEnvelopeModalProps {
  envelope: Envelope;
  onClose: () => void;
  onSave: (targets: NutrientConstraint[], notes?: string) => Promise<void>;
  isSaving?: boolean;
}

const NUTRIENT_LABELS: Record<string, string> = {
  energy_kcal: 'Energy',
  protein_g: 'Protein',
  sodium_mg: 'Sodium',
  potassium_mg: 'Potassium',
  phosphorus_mg: 'Phosphorus',
  carbs_g: 'Carbohydrates',
  fat_g: 'Fat',
  sat_fat_g: 'Saturated fat',
  fiber_g: 'Fiber',
  sugar_g: 'Sugar',
};

export default function EditEnvelopeModal({
  envelope,
  onClose,
  onSave,
  isSaving = false,
}: EditEnvelopeModalProps) {
  const [values, setValues] = useState<Record<string, string>>(() => {
    const initial: Record<string, string> = {};
    envelope.constraints.forEach((c, idx) => {
      initial[`${c.nutrient}-${c.kind}-${idx}`] = String(c.value);
    });
    return initial;
  });
  const [note, setNote] = useState('');
  const [saveError, setSaveError] = useState<string | null>(null);
  const modalRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const firstInput = modalRef.current?.querySelector('input, textarea, button');
    if (firstInput instanceof HTMLElement) {
      firstInput.focus();
    }

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        if (!isSaving) onClose();
        return;
      }

      if (e.key !== 'Tab') return;

      const container = modalRef.current;
      if (!container) return;
      const focusable = container.querySelectorAll<HTMLElement>(
        'a[href], button, input, textarea, select, [tabindex]:not([tabindex="-1"])'
      );
      const nodes = Array.from(focusable).filter((el) => !el.hasAttribute('disabled'));
      if (nodes.length === 0) return;

      const currentIndex = nodes.indexOf(document.activeElement as HTMLElement);
      if (e.shiftKey) {
        if (currentIndex <= 0) {
          e.preventDefault();
          nodes[nodes.length - 1].focus();
        }
      } else {
        if (currentIndex === -1 || currentIndex === nodes.length - 1) {
          e.preventDefault();
          nodes[0].focus();
        }
      }
    };

    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [onClose, isSaving]);

  const handleBackdropClick = (e: React.MouseEvent) => {
    if (isSaving) return;
    if (e.target === e.currentTarget) {
      onClose();
    }
  };

  const handleChange = (key: string, value: string) => {
    setValues((prev) => ({ ...prev, [key]: value }));
  };

  const isChanged = (c: NutrientConstraint, idx: number) => {
    const key = `${c.nutrient}-${c.kind}-${idx}`;
    const raw = values[key];
    if (raw === undefined) return false;
    const parsed = parseFloat(raw);
    return Number.isFinite(parsed) ? parsed !== c.value : true;
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaveError(null);

    const targets: NutrientConstraint[] = envelope.constraints.map((c, idx) => ({
      nutrient: c.nutrient,
      kind: c.kind,
      value: (() => {
        const key = `${c.nutrient}-${c.kind}-${idx}`;
        const raw = values[key];
        if (raw === undefined || raw.trim() === '') return 0;
        const parsed = parseFloat(raw);
        return Number.isFinite(parsed) && parsed >= 0 ? parsed : 0;
      })(),
      unit: c.unit,
    }));

    try {
      await onSave(targets, note.trim() || undefined);
      onClose();
    } catch (err: any) {
      setSaveError(err.message || 'Failed to save changes. Please try again.');
    }
  };

  const kindClasses: Record<NutrientConstraint['kind'], string> = {
    max: 'bg-rose-50 text-rose-700',
    min: 'bg-emerald-50 text-emerald-700',
    target: 'bg-sky-50 text-sky-700',
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-slate-900/40 p-4 backdrop-blur-sm sm:items-center"
      onClick={handleBackdropClick}
      aria-labelledby="edit-envelope-title"
      aria-describedby="edit-envelope-desc"
      role="dialog"
      aria-modal="true"
    >
      <div
        ref={modalRef}
        className="w-full max-w-2xl overflow-hidden rounded-xl bg-white shadow-2xl ring-1 ring-slate-900/10"
      >
        <div className="border-b border-slate-100 p-5">
          <h2 id="edit-envelope-title" className="text-lg font-semibold text-slate-900">
            Edit nutrient constraints
          </h2>
          <p id="edit-envelope-desc" className="mt-1 text-sm text-slate-500">
            Adjust the values below. Saving marks the envelope as{' '}
            <span className="font-medium text-sky-700">EDITED</span> and requires
            re-approval.
          </p>
        </div>

        <form onSubmit={handleSubmit} className="p-5">
          {saveError && (
            <div className="mb-4 rounded-lg border border-rose-200 bg-rose-50 p-3 text-sm text-rose-800">
              {saveError}
              <button
                type="button"
                onClick={() => setSaveError(null)}
                className="ml-2 font-medium underline hover:text-rose-900"
              >
                Dismiss
              </button>
            </div>
          )}

          <div className="max-h-[50vh] overflow-y-auto rounded-lg border border-slate-200">
            {envelope.constraints.length === 0 ? (
              <p className="p-4 text-sm text-slate-500">
                No nutrient constraints are available to edit.
              </p>
            ) : (
              <table className="min-w-full text-left text-sm">
                <thead className="bg-slate-50 text-slate-700">
                  <tr>
                    <th className="px-4 py-3 font-semibold">Nutrient</th>
                    <th className="px-4 py-3 font-semibold">Kind</th>
                    <th className="px-4 py-3 font-semibold">Value</th>
                    <th className="px-4 py-3 font-semibold">Unit</th>
                    <th className="px-4 py-3 font-semibold">Original</th>
                    <th className="px-4 py-3 font-semibold">Status</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {envelope.constraints.map((c, idx) => {
                    const key = `${c.nutrient}-${c.kind}-${idx}`;
                    const changed = isChanged(c, idx);
                    return (
                      <tr
                        key={key}
                        className={changed ? 'bg-sky-50/50' : 'hover:bg-slate-50/60'}
                      >
                        <td className="px-4 py-3 font-medium text-slate-900">
                          {NUTRIENT_LABELS[c.nutrient] || c.nutrient}
                        </td>
                        <td className="px-4 py-3">
                          <span
                            className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${kindClasses[c.kind]}`}
                          >
                            {c.kind}
                          </span>
                        </td>
                        <td className="px-4 py-3">
                          <input
                            type="number"
                            min="0"
                            step="any"
                            required
                            value={values[key] ?? ''}
                            onChange={(e) => handleChange(key, e.target.value)}
                            className="block w-full rounded-lg border-slate-300 px-3 py-2 text-sm text-slate-900 shadow-sm focus:border-sky-500 focus:ring-sky-500 sm:w-28"
                            aria-label={`${NUTRIENT_LABELS[c.nutrient] || c.nutrient} ${c.kind} value`}
                          />
                        </td>
                        <td className="px-4 py-3 text-slate-500">{c.unit}</td>
                        <td className="px-4 py-3 tabular-nums text-slate-500">
                          {c.value}
                        </td>
                        <td className="px-4 py-3">
                          {changed ? (
                            <span className="inline-flex items-center rounded-full bg-sky-100 px-2 py-0.5 text-xs font-medium text-sky-700">
                              Modified
                            </span>
                          ) : (
                            <span className="text-xs text-slate-400">—</span>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            )}
          </div>

          <div className="mt-4">
            <label htmlFor="edit-note" className="block text-sm font-medium text-slate-700">
              Edit note <span className="font-normal text-slate-500">(optional)</span>
            </label>
            <textarea
              id="edit-note"
              rows={2}
              value={note}
              onChange={(e) => setNote(e.target.value)}
              className="mt-1 block w-full rounded-lg border-slate-300 px-3 py-2 text-sm text-slate-900 shadow-sm focus:border-sky-500 focus:ring-sky-500"
              placeholder="Reason for edit"
            />
          </div>

          <div className="mt-6 flex flex-col-reverse gap-3 sm:flex-row sm:justify-end">
            <button
              type="button"
              onClick={onClose}
              disabled={isSaving}
              className="inline-flex items-center justify-center rounded-lg bg-white px-4 py-2 text-sm font-semibold text-slate-700 ring-1 ring-slate-300 hover:bg-slate-50 disabled:opacity-60"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={isSaving}
              className="inline-flex items-center justify-center rounded-lg bg-sky-600 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-sky-700 focus:outline-none focus:ring-2 focus:ring-sky-500 focus:ring-offset-2 disabled:bg-sky-300"
            >
              {isSaving ? 'Saving…' : 'Save changes'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
