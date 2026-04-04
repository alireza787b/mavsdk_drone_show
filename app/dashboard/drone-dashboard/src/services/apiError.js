export async function extractApiErrorMessage(error, fallbackMessage = 'Request failed') {
  const normalizeMessage = (payload) => {
    if (!payload || typeof payload !== 'object') {
      return null;
    }

    if (typeof payload.error === 'string' && payload.error.trim()) {
      return payload.error;
    }

    if (typeof payload.detail === 'string' && payload.detail.trim()) {
      return payload.detail;
    }

    if (Array.isArray(payload.detail) && payload.detail.length > 0) {
      const firstDetail = payload.detail[0];
      if (typeof firstDetail === 'string' && firstDetail.trim()) {
        return firstDetail;
      }
      if (firstDetail && typeof firstDetail.msg === 'string' && firstDetail.msg.trim()) {
        return firstDetail.msg;
      }
    }

    if (typeof payload.message === 'string' && payload.message.trim()) {
      return payload.message;
    }

    return null;
  };

  const responseData = error?.response?.data;

  if (responseData instanceof Blob) {
    try {
      const text = await responseData.text();
      const payload = JSON.parse(text);
      return normalizeMessage(payload) || error?.message || fallbackMessage;
    } catch {
      return error?.message || fallbackMessage;
    }
  }

  if (responseData && typeof responseData === 'object') {
    return normalizeMessage(responseData) || error?.message || fallbackMessage;
  }

  return error?.message || fallbackMessage;
}
