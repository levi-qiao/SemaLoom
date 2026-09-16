import { useRef } from "react";

let rowSeq = 0;

export function useRowKeys(length: number, scope: string): string[] {
  const keys = useRef<string[]>([]);
  const previous = useRef(scope);
  if (previous.current !== scope) {
    keys.current = [];
    previous.current = scope;
  }
  if (keys.current.length < length) {
    const extra = Array.from({ length: length - keys.current.length }, () => {
      rowSeq += 1;
      return `row-${rowSeq}`;
    });
    keys.current = [...keys.current, ...extra];
  } else if (keys.current.length > length) {
    keys.current = keys.current.slice(0, length);
  }
  return keys.current;
}
