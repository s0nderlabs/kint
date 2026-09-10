import type { CSSProperties } from "react";

/* The mock carries per-cell custom properties inline (--i staggers a row, --d delays a lift).
   React's CSSProperties does not type custom properties, so this is the one cast that keeps the markup faithful. */
export function cvar(o: Record<string, string | number>): CSSProperties {
  return o as CSSProperties;
}

export default cvar;
