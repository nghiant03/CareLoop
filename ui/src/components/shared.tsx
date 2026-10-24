import { useId, useState, type ReactNode, type FormEvent } from 'react';
import { label, quantity, type Food } from '../api';
import { useResource, useTask } from '../state';

export function Feedback({
  task,
  error,
}: {
  task?: ReturnType<typeof useTask>;
  error?: string;
}) {
  return (
    <>
      <div role="alert">
        {(task?.error || error) && (
          <p className="notice notice-error mb-4">{task?.error || error}</p>
        )}
      </div>
      <div role="status">
        {task?.busy ? (
          <p className="text-sm text-ink-3 mb-4">Working…</p>
        ) : (
          task?.message && <p className="notice mb-4">{task.message}</p>
        )}
      </div>
    </>
  );
}

export function Field({
  label: title,
  children,
  hint,
}: {
  label: string;
  children: ReactNode;
  hint?: string;
}) {
  return (
    <label className="block min-w-0">
      <span className="micro-label mb-1 block">{title}</span>
      {children}
      {hint && <span className="mt-1 block text-sm text-ink-3">{hint}</span>}
    </label>
  );
}
export function Panel({
  title,
  children,
}: {
  title: string;
  children: ReactNode;
}) {
  return (
    <section className="panel p-5 mb-6">
      <h2 className="text-lg font-bold mb-4">{title}</h2>
      {children}
    </section>
  );
}
export function Empty({ children }: { children: ReactNode }) {
  return <p className="py-5 text-ink-3">{children}</p>;
}
export function ListFilter({
  name,
  query,
  onQuery,
  status,
  onStatus,
  statuses,
  shown,
  total,
  scope = '',
}: {
  name: string;
  query: string;
  onQuery: (value: string) => void;
  status: string;
  onStatus: (value: string) => void;
  statuses: Array<{ value: string; label: string }>;
  shown: number;
  total: number;
  scope?: string;
}) {
  return (
    <div className="mb-4 space-y-3">
      <div className="flex flex-wrap items-end gap-3">
        <div className="flex-1 min-w-48">
          <Field label={`Search ${name}`}>
            <input
              type="search"
              className="field"
              value={query}
              onChange={(e) => onQuery(e.target.value)}
            />
          </Field>
        </div>
        <Field label={`${name} status`}>
          <select
            className="field"
            value={status}
            onChange={(e) => onStatus(e.target.value)}
          >
            <option value="">All statuses</option>
            {statuses.map((s) => (
              <option key={s.value} value={s.value}>
                {s.label}
              </option>
            ))}
          </select>
        </Field>
        <button
          type="button"
          className="btn-ghost"
          disabled={!query && !status}
          onClick={() => {
            onQuery('');
            onStatus('');
          }}
        >
          Clear {name} filters
        </button>
      </div>
      <p role="status" className="text-sm text-ink-3">
        Showing {shown} of {total} {name}
        {scope ? ` · ${scope}` : ''}
      </p>
    </div>
  );
}
export function Details({ title, value }: { title: string; value: unknown }) {
  return (
    <details className="my-3">
      <summary className="cursor-pointer text-sm font-semibold text-line">
        {title}
      </summary>
      <pre className="whitespace-pre-wrap break-words text-sm bg-panel p-3 mt-2 max-h-80 overflow-auto">
        {JSON.stringify(value, null, 2)}
      </pre>
    </details>
  );
}
export function Totals({ values }: { values: Record<string, string | null> }) {
  return (
    <dl className="flex flex-wrap gap-x-6 gap-y-3">
      {['energy', 'protein', 'sodium'].map((key) => (
        <div key={key}>
          <dt className="micro-label capitalize">{label(key)}</dt>
          <dd className="tabular-nums">
            {quantity(values[key])}{' '}
            {values[key] == null
              ? ''
              : key === 'energy'
                ? 'kcal'
                : key === 'sodium'
                  ? 'mg'
                  : 'g'}
          </dd>
        </div>
      ))}
    </dl>
  );
}
export function Form({
  children,
  onSubmit,
  busy,
}: {
  children: ReactNode;
  onSubmit: () => void;
  busy?: boolean;
}) {
  // Synchronize native interaction-based validation with assistive technology.
  const sync = (event: FormEvent<HTMLFormElement>) => {
    const target = event.target;
    if (!(
      target instanceof HTMLInputElement ||
      target instanceof HTMLSelectElement ||
      target instanceof HTMLTextAreaElement
    ))
      return;
    let invalid = false;
    try {
      invalid = target.matches(':user-invalid');
    } catch {
      invalid =
        (event.type === 'invalid' || target.hasAttribute('aria-invalid')) &&
        !target.validity.valid;
    }
    if (invalid) target.setAttribute('aria-invalid', 'true');
    else target.removeAttribute('aria-invalid');
  };
  return (
    <form
      onBlur={sync}
      onInput={sync}
      onInvalid={sync}
      onSubmit={(e) => {
        e.preventDefault();
        if (!busy) onSubmit();
      }}
    >
      <fieldset disabled={busy} className="space-y-4 min-w-0">
        {children}
      </fieldset>
    </form>
  );
}
export function FoodPicker({
  selected,
  onChange,
  multiple = true,
  embedded = false,
}: {
  selected: Food[];
  onChange: (foods: Food[]) => void;
  multiple?: boolean;
  embedded?: boolean;
}) {
  const id = useId();
  const [query, setQuery] = useState('');
  const [search, setSearch] = useState('');
  const SearchContainer = embedded ? 'div' : 'form';
  const foods = useResource<Food[]>(
    `/foods?q=${encodeURIComponent(search)}&limit=100`,
  );
  return (
    <div>
      <SearchContainer
        className="flex gap-2 items-end mb-3"
        onSubmit={(e) => {
          e.preventDefault();
          e.stopPropagation();
          setSearch(query);
        }}
        onKeyDown={
          embedded
            ? (e) => {
                if (
                  e.key === 'Enter' &&
                  e.target instanceof HTMLInputElement &&
                  !e.nativeEvent.isComposing
                ) {
                  e.preventDefault();
                  setSearch(query);
                }
              }
            : undefined
        }
      >
        <div className="flex-1">
          <label htmlFor={id} className="micro-label block mb-1">
            Find foods
          </label>
          <input
            id={id}
            className="field"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </div>
        <button
          type={embedded ? 'button' : 'submit'}
          className="btn-ghost"
          onClick={embedded ? () => setSearch(query) : undefined}
        >
          Search
        </button>
      </SearchContainer>
      <Feedback error={foods.error} />
      {foods.loading ? (
        <p role="status">Loading foods…</p>
      ) : (
        <div className="max-h-64 overflow-y-auto divide-y divide-rule border border-rule rounded-md">
          {!foods.error && !foods.data?.length && (
            <p className="p-3 text-ink-3">
              {search
                ? 'No foods match this search. Clear the search or try another name.'
                : 'No foods found. Import catalogue records first.'}
            </p>
          )}
          {foods.data?.map((food) => (
            <label
              key={food.id}
              className="flex items-start gap-3 p-3 hover:bg-panel cursor-pointer"
            >
              <input
                type={multiple ? 'checkbox' : 'radio'}
                name={id}
                className="mt-1"
                checked={selected.some((f) => f.id === food.id)}
                onChange={(e) =>
                  onChange(
                    multiple
                      ? e.target.checked
                        ? [...selected, food]
                        : selected.filter((f) => f.id !== food.id)
                      : [food],
                  )
                }
              />
              <span className="min-w-0">
                <span className="font-semibold block">{food.body.name}</span>
                <span className="text-sm text-ink-3">
                  {food.body.category} ·{' '}
                  {food.body.portions.length
                    ? `${food.body.portions.length} source portion${food.body.portions.length === 1 ? '' : 's'}`
                    : 'No source portions'}
                </span>
              </span>
            </label>
          ))}
        </div>
      )}
      <p className="text-sm text-ink-3 mt-2">
        Showing up to 100 matches. {selected.length} selected.{' '}
        {
          selected.filter((f) => !foods.data?.some((row) => row.id === f.id))
            .length
        }{' '}
        outside these results.
      </p>
      {(query || search) && (
        <button
          type="button"
          className="btn-ghost mt-2"
          onClick={() => {
            setQuery('');
            setSearch('');
          }}
        >
          Clear food search
        </button>
      )}
      {multiple && selected.length > 0 && (
        <button
          type="button"
          className="btn-ghost mt-2"
          onClick={() => onChange([])}
        >
          Clear food selection
        </button>
      )}
      {!!selected.length && (
        <div className="flex flex-wrap gap-2 mt-2">
          {selected.map((food) => (
            <button
              type="button"
              className="btn-ghost"
              key={food.id}
              onClick={() => onChange(selected.filter((f) => f.id !== food.id))}
            >
              Remove {food.body.name}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
