export async function extractApiErrorMessage(error, fallbackMessage = 'Request failed') {
  const responseData = error?.response?.data;

  if (responseData instanceof Blob) {
    try {
      const text = await responseData.text();
      const payload = JSON.parse(text);
      return payload.error || payload.detail || payload.message || error?.message || fallbackMessage;
    } catch {
      return error?.message || fallbackMessage;
    }
  }

  if (responseData && typeof responseData === 'object') {
    return responseData.error || responseData.detail || responseData.message || error?.message || fallbackMessage;
  }

  return error?.message || fallbackMessage;
}
