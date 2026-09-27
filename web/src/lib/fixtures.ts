// Synthetic 48-slot (half-hourly) price shape behind the screens' sample data.

export const gaussian = (t: number, c: number, w: number) => Math.exp(-((t - c) * (t - c)) / w)

/** One value per half-hour slot: `f(slot index, hour of day)`. */
export const slots = (f: (i: number, t: number) => number): number[] =>
  Array.from({ length: 48 }, (_, i) => f(i, i / 2))

export const today: number[] = slots(
  (i, t) =>
    9.6 +
    3.1 * gaussian(t, 8.1, 2.4) -
    4.2 * gaussian(t, 12.6, 7.5) +
    12.1 * gaussian(t, 18.7, 2.9) +
    0.38 * Math.sin(i * 1.63) +
    0.24 * Math.sin(i * 0.71 + 2.1),
)
