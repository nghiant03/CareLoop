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
    max: 'flag-bad',
    min: 'flag-warn',
    target: 'flag-info',
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-ink/50 p-4 sm:items-center"
      onClick={handleBackdropClick}
      aria-labelledby="edit-envelope-title"
      aria-describedby="edit-envelope-desc"
      role="dialog"
      aria-modal="true"
    >
      <div
        ref={modalRef}
        className="w-full max-w-2xl overflow-hidden border border-rule-2 bg-card"
      >
        <div className="border-b border-rule-2 p-5">
          <p className="micro-label mb-1">Amendment · invalidates approval</p>
          <h2 id="edit-envelope-title" className="text-lg font-bold tracking-tight text-ink">
            Edit nutrient constraints
          </h2>
          <p id="edit-envelope-desc" className="mt-1 text-sm text-ink-3">
            Adjust the values below. Saving marks the envelope as{' '}
            <span className="font-medium text-line">EDITED</span> and requires
            re-approval.
          </p>
        </div>

        <form onSubmit={handleSubmit} className="p-5">
          {saveError && (
            <div className="notice notice-error mb-4">
              {saveError}
              <button
                type="button"
                onClick={() => setSaveError(null)}
                className="ml-2 font-semibold underline hover:opacity-80"
              >
                Dismiss
              </button>
            </div>
          )}

          <div className="max-h-[50vh] overflow-y-auto border border-rule">
            {envelope.constraints.length === 0 ? (
              <p className="p-4 text-sm text-ink-3">
                No nutrient constraints are available to edit.
              </p>
            ) : (
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Nutrient</th>
                    <th>Kind</th>
                    <th>Value</th>
                    <th>Unit</th>
                    <th>Original</th>
                    <th>Status</th>
                  </tr>
                </thead>
                <tbody>
                  {envelope.constraints.map((c, idx) => {
                    const key = `${c.nutrient}-${c.kind}-${idx}`;
                    const changed = isChanged(c, idx);
                    return (
                      <tr
                        key={key}
                        className={changed ? 'bg-line-bg' : ''}
                      >
                        <td className="font-medium text-ink">
                          {NUTRIENT_LABELS[c.nutrient] || c.nutrient}
                        </td>
                        <td>
                          <span className={`flag ${kindClasses[c.kind]}`}>
                            {c.kind}
                          </span>
                        </td>
                        <td>
                          <input
                            type="number"
                            min="0"
                            step="any"
                            required
                            value={values[key] ?? ''}
                            onChange={(e) => handleChange(key, e.target.value)}
                            className="field num block w-full sm:w-28"
                            aria-label={`${NUTRIENT_LABELS[c.nutrient] || c.nutrient} ${c.kind} value`}
                          />
                        </td>
                        <td className="text-ink-3">{c.unit}</td>
                        <td className="num text-ink-3">
                          {c.value}
                        </td>
                        <td>
                          {changed ? (
                            <span className="flag flag-info">Modified</span>
                          ) : (
                            <span className="text-xs text-ink-3">—</span>
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
            <label htmlFor="edit-note" className="block text-sm font-medium text-ink-2">
              Edit note <span className="font-normal text-ink-3">(optional)</span>
            </label>
            <textarea
              id="edit-note"
              rows={2}
              value={note}
              onChange={(e) => setNote(e.target.value)}
              className="field mt-1"
              placeholder="Reason for edit"
            />
          </div>

          <div className="mt-6 flex flex-col-reverse gap-3 border-t border-rule pt-4 sm:flex-row sm:justify-end">
            <button
              type="button"
              onClick={onClose}
              disabled={isSaving}
              className="btn-ghost"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={isSaving}
              className="btn-primary"
            >
              {isSaving ? 'Saving…' : 'Save changes'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
