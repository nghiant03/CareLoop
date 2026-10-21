import { useEffect, useState } from 'react';

class RequestScope {
  private generation = 0;
  private requests = new Map<string, symbol>();

  reset = () => {
    this.generation += 1;
    this.requests.clear();
  };

  start = (resource: string) => {
    const generation = this.generation;
    const token = Symbol(resource);
    this.requests.set(resource, token);
    return () => generation === this.generation && this.requests.get(resource) === token;
  };

  capture = () => {
    const generation = this.generation;
    return () => generation === this.generation;
  };
}

export function useRequestScope() {
  const [scope] = useState(() => new RequestScope());
  useEffect(() => () => scope.reset(), [scope]);
  return scope;
}
