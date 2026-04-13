import { toast } from 'react-toastify';

const throttledErrorState = new Map();

export function toastErrorThrottled(key, message, options = {}) {
  const normalizedKey = String(key || 'default');
  const normalizedMessage = String(message || 'Unexpected error');
  const cooldownMs = Number(options.cooldownMs || 12000);
  const now = Date.now();
  const previous = throttledErrorState.get(normalizedKey);

  if (previous && previous.message === normalizedMessage && now - previous.timestamp < cooldownMs) {
    return false;
  }

  throttledErrorState.set(normalizedKey, {
    message: normalizedMessage,
    timestamp: now,
  });

  toast.error(normalizedMessage, {
    toastId: options.toastId || normalizedKey,
    ...options,
  });
  return true;
}

export function clearThrottledToast(key) {
  throttledErrorState.delete(String(key || 'default'));
}
