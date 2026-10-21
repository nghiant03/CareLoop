interface RangeBarProps {
  /** Measured value to plot; null renders the limit marker alone (limit mode). */
  value: number | null;
  /** Reference limit the value is read against. */
  limit: number;
  /** max = hard ceiling, min = soft floor, target = soft aim. */
  kind: 'max' | 'min' | 'target';
  /** ok | over | under drive the state hue; none stays neutral ink. */
  state: 'ok' | 'over' | 'under' | 'none';
}

const STATE_BAR: Record<RangeBarProps['state'], string> = {
  ok: 'bg-ok',
  over: 'bg-flag',
  under: 'bg-warn',
  none: 'bg-ink-3',
};

/**
 * The report's signature mark: a measured value plotted on its reference
 * range. The limit is a solid rule for hard ceilings and a hollow marker for
 * soft aims; overflow beyond a ceiling reads as a hatched region.
 */
export default function RangeBar({ value, limit, kind, state }: RangeBarProps) {
  const scale = Math.max(limit, value ?? 0) * 1.12 || 1;
  const valuePct = value === null ? null : Math.min((value / scale) * 100, 100);
  const limitPct = Math.min((limit / scale) * 100, 100);
  const overflow = value !== null && kind === 'max' && value > limit;
  // Limit mode hatches the forbidden side of the rule: beyond a ceiling, below a floor.
  const forbidAbove = value === null && kind === 'max';
  const forbidBelow = value === null && kind === 'min';

  return (
    <div
      className="relative h-3 w-full border border-rule bg-panel"
      role="img"
      aria-label={value === null ? `${kind} limit ${limit}` : `${value} against ${kind} limit ${limit}`}
    >
      {/* quartile ticks */}
      {[25, 50, 75].map((t) => (
        <span
          key={t}
          className="absolute top-0 bottom-0 w-px bg-rule"
          style={{ left: `${t}%` }}
          aria-hidden="true"
        />
      ))}
      {/* measured value */}
      {valuePct !== null && (
        <div
          className={`range-fill absolute top-0 bottom-0 left-0 transition-[width] duration-500 ease-out ${STATE_BAR[state]}`}
          style={{ width: `${valuePct}%` }}
        />
      )}
      {/* hatched overrun beyond a hard ceiling, or the forbidden side of a bare limit */}
      {(overflow || forbidAbove) && (
        <div
          className="hatch-flag absolute top-0 bottom-0 opacity-70"
          style={forbidAbove
            ? { left: `${limitPct}%`, width: `${100 - limitPct}%` }
            : { left: `${limitPct}%`, width: `${Math.max((valuePct ?? 0) - limitPct, 0.5)}%` }}
          aria-hidden="true"
        />
      )}
      {forbidBelow && (
        <div
          className="hatch-warn absolute top-0 bottom-0 left-0 opacity-70"
          style={{ width: `${limitPct}%` }}
          aria-hidden="true"
        />
      )}
      {/* the limit itself */}
      {kind === 'max' ? (
        <span
          className="absolute -top-0.5 -bottom-0.5 w-0.5 bg-flag"
          style={{ left: `${limitPct}%` }}
          aria-hidden="true"
        />
      ) : (
        <span
          className="absolute -top-0.5 -bottom-0.5 w-0.5 border border-ink-2 bg-card"
          style={{ left: `${limitPct}%` }}
          aria-hidden="true"
        />
      )}
    </div>
  );
}
