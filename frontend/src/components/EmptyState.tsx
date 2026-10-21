export default function EmptyState({ title, description }: { title: string; description?: string }) {
  return (
    <div className="border border-dashed border-rule-2 bg-panel/60 px-4 py-12 text-center">
      <p className="text-sm font-semibold text-ink">{title}</p>
      {description && <p className="mx-auto mt-1 max-w-md text-sm text-ink-3">{description}</p>}
    </div>
  );
}
