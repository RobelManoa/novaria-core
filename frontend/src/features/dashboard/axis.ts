// Graduations des axes, partagées par les graphiques du tableau de bord et des prévisions.

/** Nombre de pas entre zéro et le haut de l'axe : cinq graduations. */
export const TICK_COUNT = 4;

/** Mantisses des pas de graduation : l'axe avance par pas « ronds » (0,5 ; 1,5 ; 20 ; 25…). */
const STEPS = [1, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10];

/** Plus petit pas rond tel que `TICK_COUNT` pas depuis zéro contiennent `max`. */
export function niceStep(max: number): number {
  if (max <= 0) return 0.25;
  const raw = max / TICK_COUNT;
  const magnitude = 10 ** Math.floor(Math.log10(raw));
  const mantissa = STEPS.find((step) => step >= raw / magnitude - 1e-9) ?? 10;
  return mantissa * magnitude;
}

/** Nombre de décimales qu'il faut pour écrire les multiples de `step` sans les arrondir (au plus 2). */
export function tickDigits(step: number): number {
  for (let digits = 0; digits < 2; digits += 1) {
    const scaled = step * 10 ** digits;
    if (Math.abs(scaled - Math.round(scaled)) < 1e-9) return digits;
  }
  return 2;
}
