import type { ReactNode } from "react";

interface ScrollRegionProps {
  /** Nom de la zone, annoncé par les lecteurs d'écran (reprendre la légende du tableau qu'elle contient). */
  label: string;
  className?: string;
  children: ReactNode;
}

/**
 * Zone qui défile (un tableau plus large que l'écran). Sans focus, une personne qui n'utilise que le clavier ne
 * peut pas la faire défiler (WCAG 2.1.1, règle axe `scrollable-region-focusable`) : la zone reçoit donc le focus
 * avec Tab, et les flèches la font défiler. Le rôle `region` et le nom lui donnent un sens quand elle est focalisée.
 */
export default function ScrollRegion({ label, className, children }: Readonly<ScrollRegionProps>) {
  return (
    <div role="region" aria-label={label} tabIndex={0} className={className}>
      {children}
    </div>
  );
}
