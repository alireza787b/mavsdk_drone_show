import { getFleetNetworkStatus as status } from './fleetNetworkStatus';

test('primary Ethernet wins over a connected Wi-Fi radio without displaying its signal', () => {
  expect(status({ primary_link: { type: 'ethernet', interface: 'eth0' },
    wifi: { signal_strength_percent: 83 } }, true)).toEqual({
    type: 'ethernet', label: 'Ethernet', interface: 'eth0', percent: null, current: true, stale: false,
  });
});

test.each(['wifi', 'ethernet', 'cellular', 'usb_modem', 'vpn'])('uses the reported %s transport, not the interface name', type => {
  expect(status({ primary_link: { type, interface: 'platform-specific' } }, true)).toMatchObject({ type, current: true });
});

test('old companion reports work without inventing the primary of two active links', () => {
  expect(status({ ethernet: { interface: 'end0' } }, true)).toMatchObject({ label: 'Ethernet', current: true });
  expect(status({ wifi: { ssid: 'Demo', signal_strength_percent: '0' } }, true)).toMatchObject({ label: 'Wi-Fi', percent: 0 });
  expect(status({ wifi: { ssid: 'Demo' }, ethernet: { interface: 'end0' } }, true))
    .toMatchObject({ label: 'Multiple links', percent: null });
  expect(status({ active_links: [{ type: 'ethernet', interface: 'enp1s0' }] }, true))
    .toMatchObject({ label: 'Ethernet', interface: 'enp1s0' });
});

test.each([null, undefined, '', ' ', false, -1, 101, 'Unknown'])('invalid signal %s never becomes a reading', value => {
  expect(status({ primary_link: { type: 'wifi' }, wifi: { signal_strength_percent: value } }, true).percent).toBeNull();
});

test('stale reports are last-known transport, not a current Wi-Fi signal', () => {
  expect(status({ primary_link: { type: 'wifi' }, wifi: { signal_strength_percent: 83 } }, false))
    .toMatchObject({ label: 'Wi-Fi', current: false, stale: true, percent: null });
});

test.each([null, {}, { primary_link: { type: 'unsupported' }, wifi: { ssid: 'Demo' } }])('missing or unsupported transport stays unknown', info => {
  expect(status(info, true)).toMatchObject({ label: 'Unknown', current: false, stale: false, percent: null });
});
