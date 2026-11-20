import { useEffect, useState } from "react";

/** useState that remembers its value in this browser (a filter left on "To check" is still on it next time).
 *  Falls back to the starting value where the browser keeps nothing (private window, storage blocked). */
export function useRememberedState<T>(key: string, initial: T): [T, (value: T) => void] {
  const [value, setValue] = useState<T>(initial);
  useEffect(() => {
    try {
      const saved = localStorage.getItem(`lm.${key}`);
      // eslint-disable-next-line react-hooks/set-state-in-effect -- browser storage is read after mounting (the server render has none)
      if (saved !== null) setValue(JSON.parse(saved) as T);
    } catch {}
  }, [key]);
  const set = (next: T) => {
    setValue(next);
    try {
      localStorage.setItem(`lm.${key}`, JSON.stringify(next));
    } catch {}
  };
  return [value, set];
}
