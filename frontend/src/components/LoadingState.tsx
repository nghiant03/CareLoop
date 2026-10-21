export default function LoadingState({ text = 'Loading…' }: { text?: string }) {
  return (
    <div className="flex flex-col items-center justify-center py-16" role="status">
      <div className="scan-bar w-40" />
      <p className="micro-label mt-3">{text}</p>
    </div>
  );
}
