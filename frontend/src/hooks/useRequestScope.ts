import { useEffect, useState } from 'react';

/** Guards let callers discard stale responses without cancelling network requests. */
class RequestScope {
  private generation = 0;
  private requests = new Map<string, symbol>();

  /** Invalidate all guards. Call synchronously when selection changes, before new work. */
  reset = () => {
    this.generation += 1;
    this.requests.clear();
  };

  /** Return a predicate that stays true until reset or another start for this resource.
   * Starting a different resource leaves this guard valid. No request is sent here.
   */
  start = (resource: string) => {
    const generation = this.generation;
    const token = Symbol(resource);
    this.requests.set(resource, token);
    return () => generation === this.generation && this.requests.get(resource) === token;
  };

  /** Return a selection-scope predicate that expires only on reset.
   * New requests do not invalidate it, so independent actions can complete together.
   */
  capture = () => {
    const generation = this.generation;
    return () => generation === this.generation;
  };
}

/** Keep a stable guard scope for this component and reset it on effect cleanup. */
export function useRequestScope() {
  const [scope] = useState(() => new RequestScope());
  useEffect(() => () => scope.reset(), [scope]);
  return scope;
}
