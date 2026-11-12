// Presentation of companion-reported transport, not a claim about VPN routing
// or Internet latency. Do not guess a radio from the aircraft's IP address.
const LABELS = { wifi: 'Wi-Fi', ethernet: 'Ethernet', usb_modem: 'USB network', cellular: 'Cellular', vpn: 'VPN' };
const PHYSICAL = ['wifi', 'ethernet', 'usb_modem', 'cellular'];
const text = value => typeof value === 'string' ? value.trim() : '';

export function getFleetNetworkStatus(info, fresh = false) {
  const report = info && typeof info === 'object' ? info : {};
  const primary = report.primary_link;
  let type = 'unknown';
  let device = '';
  if (primary && typeof primary === 'object' && text(primary.type)) {
    // A reported primary link wins even while another interface is connected.
    type = Object.prototype.hasOwnProperty.call(LABELS, primary.type) ? primary.type : 'unknown';
    device = text(primary.interface);
  } else {
    // Older companions have no primary_link. Only infer an unambiguous single
    // connected transport; never prefer Wi-Fi merely because it has a signal.
    const links = new Map();
    (Array.isArray(report.active_links) ? report.active_links : []).forEach(link => {
      if (PHYSICAL.includes(link?.type)) links.set(link.type, link);
    });
    PHYSICAL.forEach(kind => {
      const link = report[kind];
      if (link && typeof link === 'object' && (text(link.interface) || (kind === 'wifi' &&
        (text(link.ssid) || validSignal(link.signal_strength_percent) !== null)))) links.set(kind, link);
    });
    if (links.size === 1) {
      [type] = links.keys();
      device = text(links.get(type).interface);
    } else if (links.size > 1) type = 'multiple';
  }
  const known = type !== 'unknown';
  const percent = fresh && type === 'wifi'
    ? validSignal(primary?.signal_strength_percent ?? report.wifi?.signal_strength_percent) : null;
  return { type, label: LABELS[type] || (type === 'multiple' ? 'Multiple links' : 'Unknown'),
    interface: device, percent, current: fresh && known, stale: !fresh && known };
}

function validSignal(value) {
  if ((typeof value !== 'number' && typeof value !== 'string') || String(value).trim() === '') return null;
  const number = Number(value);
  return Number.isFinite(number) && number >= 0 && number <= 100 ? number : null;
}
