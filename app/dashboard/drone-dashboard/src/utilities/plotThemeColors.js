const CSS_VAR_REFERENCE_PATTERN = /var\(\s*(--[A-Za-z0-9-_]+)\s*(?:,\s*([^)]+))?\)/;

const readCssVariableRaw = (name) => {
  if (typeof window === 'undefined' || !window.getComputedStyle) {
    return '';
  }

  return window.getComputedStyle(document.documentElement).getPropertyValue(name).trim();
};

const resolveCssVariableReferences = (value, fallback, depth = 0) => {
  if (!value || depth > 6) {
    return fallback;
  }

  const match = String(value).match(CSS_VAR_REFERENCE_PATTERN);
  if (!match) {
    return String(value).trim() || fallback;
  }

  const [, variableName, variableFallback] = match;
  const replacement = readCssVariableRaw(variableName)
    || (variableFallback ? variableFallback.trim() : fallback);

  return resolveCssVariableReferences(
    String(value).replace(match[0], replacement),
    fallback,
    depth + 1
  );
};

const readCssVariable = (name, fallback) => {
  const value = readCssVariableRaw(name);
  return resolveCssVariableReferences(value || fallback, fallback);
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
