const readCssVariable = (name, fallback) => {
  if (typeof window === 'undefined' || !window.getComputedStyle) {
    return fallback;
  }

  const value = window.getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return value || fallback;
};

export const getPlotThemeColors = () => ({
  background: readCssVariable('--color-bg-primary', 'white'),
  paper: readCssVariable('--color-bg-primary', 'white'),
  surface: readCssVariable('--color-bg-secondary', 'white'),
  text: readCssVariable('--color-text-primary', 'black'),
  textInverse: readCssVariable('--color-primary-text', 'white'),
  textMuted: readCssVariable('--color-text-secondary', 'dimgray'),
  grid: readCssVariable('--color-border-primary', 'gainsboro'),
  primary: readCssVariable('--color-primary', 'royalblue'),
  primaryHover: readCssVariable('--color-primary-hover', 'dodgerblue'),
  success: readCssVariable('--color-success', 'seagreen'),
  warning: readCssVariable('--color-warning', 'darkorange'),
  danger: readCssVariable('--color-danger', 'crimson'),
  muted: readCssVariable('--color-text-tertiary', 'gray'),
  fontFamily: readCssVariable('--font-family-primary', 'sans-serif'),
});
