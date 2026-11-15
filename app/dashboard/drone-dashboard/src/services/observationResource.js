/** One cancellable observation owner. Never submits or replays commands. */
const EMPTY = Object.freeze({ response: null, error: null, loading: true, consecutiveFailures: 0, receivedAtMs: null, transport: 'connecting' });

export default class ObservationResource {
  constructor(load, { intervalMs = 1000, streamUrl = null, socketFactory = url => new WebSocket(url), idleMs = 5000 } = {}) {
    Object.assign(this, { load, intervalMs, streamUrl, socketFactory, idleMs });
    this.snapshot = EMPTY;
    this.listeners = new Set();
    this.generation = 0;
    this.running = false;
    this.cursor = null;
    this.wsRevision = 0;
    this.retiredEpochs = new Set();
    this.refresh = () => { if (this.running) this.poll(); };
  }

  getSnapshot = () => this.snapshot;
  subscribe = listener => {
    this.listeners.add(listener);
    if (!this.running) this.start();
    return () => { this.listeners.delete(listener); if (!this.listeners.size) this.stop(); };
  };
  emit(patch) {
    this.snapshot = { ...this.snapshot, ...patch };
    this.listeners.forEach(listener => listener());
  }
  start() {
    this.running = true;
    this.streamDenied = false;
    this.backoff = 1000;
    this.visibility = () => {
      clearTimeout(this.pollTimer);
      if (document.hidden) this.closeSocket();
      else this.connect();
      this.poll();
    };
    document.addEventListener('visibilitychange', this.visibility);
    window.addEventListener('focus', this.visibility);
    this.poll();
    this.connect();
  }
  stop() {
    this.running = false;
    this.generation += 1;
    clearTimeout(this.pollTimer);
    clearTimeout(this.reconnectTimer);
    this.controller?.abort();
    this.controller = null;
    this.inFlight = false;
    this.closeSocket();
    document.removeEventListener('visibilitychange', this.visibility);
    window.removeEventListener('focus', this.visibility);
    // An unmounted auth/runtime context must not retain protected observations.
    this.snapshot = EMPTY;
    this.cursor = null;
    this.retiredEpochs.clear();
  }
  schedulePoll() {
    clearTimeout(this.pollTimer);
    if (this.running) this.pollTimer = setTimeout(() => this.poll(), document.hidden ? Math.max(5000, this.intervalMs) : this.intervalMs);
  }
  async poll() {
    if (!this.running || this.inFlight) return;
    if (this.wsHealthy) { this.schedulePoll(); return; }
    this.inFlight = true;
    const generation = this.generation;
    const wsRevision = this.wsRevision;
    const controller = new AbortController();
    this.controller = controller;
    const timeout = setTimeout(() => controller.abort(), 10000);
    try {
      const response = await this.load({ signal: controller.signal, timeout: 10000 });
      if (this.running && this.generation === generation && !this.wsHealthy && this.wsRevision === wsRevision) this.install(response, 'http');
    } catch (error) {
      if (this.running && this.generation === generation && !this.wsHealthy && this.wsRevision === wsRevision) {
        if (error?.response?.status === 401) window.dispatchEvent(new Event('mds:auth-required'));
        this.emit({ error, loading: false, consecutiveFailures: Math.min(1000000, this.snapshot.consecutiveFailures + 1),
          transport: [401, 403].includes(error?.response?.status) ? 'auth-required' : 'reconnecting' });
      }
    } finally {
      clearTimeout(timeout);
      if (this.controller === controller) { this.controller = null; this.inFlight = false; this.schedulePoll(); }
    }
  }
  install(response, transport) {
    const data = response?.data;
    if (!data || typeof data !== 'object') throw new Error('Observation snapshot is invalid');
    if (data.protocol_version !== undefined) {
      if (data.protocol_version !== 1 || typeof data.stream_id !== 'string' || !data.stream_id
          || !Number.isSafeInteger(data.sequence) || data.sequence < 1) throw new Error('Unsupported observation stream');
      if (this.retiredEpochs.has(data.stream_id)) return false;
      if (this.cursor?.id === data.stream_id && data.sequence <= this.cursor.sequence) return false;
      if (this.cursor && this.cursor.id !== data.stream_id) {
        this.retiredEpochs.add(this.cursor.id);
        if (this.retiredEpochs.size > 16) this.retiredEpochs.delete(this.retiredEpochs.values().next().value);
      }
      this.cursor = { id: data.stream_id, sequence: data.sequence };
    }
    this.emit({ response, error: null, loading: false, receivedAtMs: Date.now(), receivedAtMonotonicMs: performance.now(), consecutiveFailures: 0, transport });
    return true;
  }
  closeSocket() {
    this.wsHealthy = false;
    clearTimeout(this.idleTimer);
    const socket = this.socket;
    this.socket = null;
    if (socket) { socket.onopen = socket.onmessage = socket.onerror = socket.onclose = null; socket.close(); }
  }
  connect() {
    if (!this.running || !this.streamUrl || this.socket || this.streamDenied || document.hidden) return;
    clearTimeout(this.reconnectTimer);
    const generation = this.generation;
    let socket;
    const current = () => this.running && generation === this.generation && this.socket === socket;
    const failed = event => {
      if (!current()) return;
      this.closeSocket();
      if (event?.code === 1008) {
        const error = new Error(event.reason || 'Stream authorization required');
        this.emit({ error, loading: false, transport: 'auth-required' });
        if (event.reason === 'authentication_required') window.dispatchEvent(new Event('mds:auth-required'));
        // Policy denial is not radio loss. HTTP remains available with its
        // independent permissions; reconnect needs renewed operator context.
        this.streamDenied = true;
        this.poll();
        return;
      }
      this.poll();
      const delay = this.backoff * (0.8 + Math.random() * 0.4);
      this.backoff = Math.min(15000, this.backoff * 2);
      this.reconnectTimer = setTimeout(() => this.connect(), delay);
    };
    const armIdle = () => { clearTimeout(this.idleTimer); this.idleTimer = setTimeout(failed, this.idleMs); };
    try {
      socket = this.socketFactory(this.streamUrl());
      this.socket = socket;
      // Opening a TCP socket is not evidence of valid application data.
      armIdle();
      socket.onopen = () => { if (current()) armIdle(); };
      socket.onmessage = event => {
        if (!current()) return;
        try {
          if (typeof event.data !== 'string' || event.data.length > 8 * 1024 * 1024) throw new Error('Oversized fleet stream');
          const message = JSON.parse(event.data);
          if (message.type !== 'telemetry' || !message.data || typeof message.data !== 'object' || Array.isArray(message.data)) throw new Error('Invalid fleet stream');
          const response = { data: { ...message, telemetry: message.data },
            headers: { 'x-mds-server-time': message.timestamp } };
          if (this.install(response, 'ws')) {
            this.wsRevision += 1;
            this.wsHealthy = true;
            this.backoff = 1000;
            armIdle();
          }
        } catch (_) { /* Invalid frames do not renew application liveness. */ }
      };
      socket.onerror = socket.onclose = failed;
    } catch (_) {
      this.socket = null;
      this.reconnectTimer = setTimeout(() => this.connect(), Math.min(15000, this.backoff));
      this.backoff = Math.min(15000, this.backoff * 2);
    }
  }
}
