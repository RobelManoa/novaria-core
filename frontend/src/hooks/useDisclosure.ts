import { useCallback, useMemo, useState } from "react";

export interface Disclosure {
  isOpen: boolean;
  open: () => void;
  close: () => void;
  toggle: () => void;
}

/** État ouvert/fermé d'un élément repliable (menu, tiroir). */
export function useDisclosure(initiallyOpen = false): Disclosure {
  const [isOpen, setIsOpen] = useState(initiallyOpen);
  const open = useCallback(() => setIsOpen(true), []);
  const close = useCallback(() => setIsOpen(false), []);
  const toggle = useCallback(() => setIsOpen((value) => !value), []);
  return useMemo(() => ({ isOpen, open, close, toggle }), [isOpen, open, close, toggle]);
}
