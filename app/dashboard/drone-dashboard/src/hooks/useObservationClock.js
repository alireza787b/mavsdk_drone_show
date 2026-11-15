import { useEffect, useState } from 'react';

// One ticking owner per mounted application provider, shared by React consumers.
let listeners = new Set(), timer;
const tick = () => listeners.forEach(listener => listener(Date.now()));
export default function useObservationClock() {
  const [now, setNow] = useState(Date.now);
  useEffect(() => {
    listeners.add(setNow);
    if (!timer) { timer = setInterval(tick, 1000); window.addEventListener('focus', tick); }
    return () => {
      listeners.delete(setNow);
      if (!listeners.size) { clearInterval(timer); timer = null; window.removeEventListener('focus', tick); }
    };
  }, []);
  return now;
}
