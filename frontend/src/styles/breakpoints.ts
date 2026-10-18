/** Points de rupture, mobile d'abord. Les mêmes valeurs figurent dans tokens.css (test de cohérence). */
export const BREAKPOINTS = {
  tablet: "40rem",
  desktop: "64rem",
} as const;

export const TABLET_QUERY = `(min-width: ${BREAKPOINTS.tablet})`;
export const DESKTOP_QUERY = `(min-width: ${BREAKPOINTS.desktop})`;
