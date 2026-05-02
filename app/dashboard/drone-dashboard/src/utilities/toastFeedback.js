import { toast } from 'react-toastify';

const throttledToastState = new Map();

export function toastThrottled(level, key, message, options = {}) {
  const normalizedLevel = typeof toast[level] === 'function' ? level : 'info';
  const normalizedKey = String(key || 'default');
  const normalizedMessage = String(message || 'Unexpected error');
  const cooldownMs = Number(options.cooldownMs || 12000);
  const now = Date.now();
  const stateKey = `${normalizedLevel}:${normalizedKey}`;
  const previous = throttledToastState.get(stateKey);

  if (previous && previous.message === normalizedMessage && now - previous.timestamp < cooldownMs) {
    return false;
  }

  throttledToastState.set(stateKey, {
    message: normalizedMessage,
    timestamp: now,
  });

  toast[normalizedLevel](normalizedMessage, {
    toastId: options.toastId || stateKey,
    ...options,
  });
  return true;
}

export function toastErrorThrottled(key, message, options = {}) {
  return toastThrottled('error', key, message, options);
}

export function toastWarningThrottled(key, message, options = {}) {
  return toastThrottled('warning', key, message, options);
}

export function toastInfoThrottled(key, message, options = {}) {
  return toastThrottled('info', key, message, options);
}

export function clearThrottledToast(key) {
  const normalizedKey = String(key || 'default');
  ['error', 'warning', 'info', 'success'].forEach((level) => {
    throttledToastState.delete(`${level}:${normalizedKey}`);
  });
}
