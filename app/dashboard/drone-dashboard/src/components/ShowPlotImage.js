import React from 'react';
import { useTheme } from '../contexts/ThemeContext';
import { buildShowPlotUrl } from '../services/gcsApiService';

// One reactive renderer for Operate, Setup and the portalled fullscreen view.
// Never invert evidence: aircraft colors must mean the same in both themes.
export default function ShowPlotImage({ filename, plots = {}, style, alt = '', ...props }) {
  const { theme } = useTheme();
  const selected = plots.variants?.[filename]?.[theme] || filename;
  const url = buildShowPlotUrl(selected);
  const src = plots.revision ? `${url}?revision=${encodeURIComponent(plots.revision)}` : url;
  return <img {...props} alt={alt} data-show-plot={filename} data-plot-theme={theme}
    src={src} style={style} />;
}
