# LED Status Guide

This guide explains the LED color meanings for MDS drones during boot and runtime.

## Boot Sequence

When a drone powers on, the LED progresses through these states:

| Phase | LED Color | Pattern | Meaning |
|-------|-----------|---------|---------|
| 1 | **RED** | Solid | Boot has started |
| 2 | **BLUE** | Slow pulse | Network initializing (WiFi connecting) |
| 3 | **BLUE** | Solid | Network established |
| 4 | **CYAN** | Fast pulse | Git sync in progress |
| 5a | **GREEN** | 3x flash | Git sync successful |
| 5b | **YELLOW** | Solid | Git sync failed (using cached code) |
| 6 | **ORANGE** | Pulse | Updating services/requirements |
| 7 | **WHITE** | 1x flash | Startup complete |

## Runtime States

After boot completes, the LED indicates the drone's operational state:

| State | LED Color | Pattern | Meaning |
|-------|-----------|---------|---------|
| Ready (Connected) | **GREEN** | Solid | GCS connected, ready for commands |
| Ready (Offline) | **PURPLE** | Solid | GCS not reachable, but drone ready |
| Mission Armed | **ORANGE** | Solid | Mission loaded, awaiting start |
| Mission Active | **CYAN** | Pulse | Mission executing |
| Mission Complete | **GREEN** | Slow pulse | Mission finished |
| Mission Paused | **YELLOW** | Slow blink | Mission paused |

## Error States

| State | LED Color | Pattern | Meaning |
|-------|-----------|---------|---------|
| Recoverable Error | **RED** | Slow blink | Error occurred, will retry |
| Critical Error | **RED** | Fast blink | Critical error, needs attention |
| Hardware Failure | **MAGENTA** | Fast blink | Hardware issue detected |
| Communication Error | **ORANGE-RED** | Fast blink | MAVLink or network issue |

## RGB Values Reference

For developers implementing LED feedback:

```python
from src.led_colors import LEDColors, LEDState

# Boot phases
LEDColors.BOOT_STARTED       # (255, 0, 0)     Red
LEDColors.NETWORK_INIT       # (0, 0, 255)     Blue
LEDColors.GIT_SYNCING        # (0, 255, 255)   Cyan
LEDColors.GIT_SUCCESS        # (0, 255, 0)     Green
LEDColors.GIT_FAILED         # (255, 255, 0)   Yellow
LEDColors.STARTUP_COMPLETE   # (255, 255, 255) White

# Runtime
LEDColors.IDLE_CONNECTED     # (0, 255, 0)     Green
LEDColors.IDLE_DISCONNECTED  # (128, 0, 128)   Purple
LEDColors.MISSION_ARMED      # (255, 165, 0)   Orange
LEDColors.MISSION_ACTIVE     # (0, 255, 255)   Cyan
LEDColors.ERROR              # (255, 0, 0)     Red
```

## Testing LED Colors

Use the `led_indicator.py` script to test LED states:

```bash
# Test by state name (preferred)
python led_indicator.py --state BOOT_STARTED
python led_indicator.py --state GIT_SYNCING
python led_indicator.py --state IDLE_CONNECTED

# Test by color name
python led_indicator.py --color red
python led_indicator.py --color green

# List all available states
python led_indicator.py --list-states
```

Or use the recovery tool:
```bash
./tools/recovery.sh led-test
```

## Troubleshooting

### LED stays RED after boot
- If this node uses `smart-wifi-manager`, check `journalctl -u smart-wifi-manager`
- Check `journalctl -u git_sync_mds` for git sync issues

### LED is YELLOW (not green)
- Git sync failed - drone is running cached code
- Check network connectivity
- Run `./tools/recovery.sh force-sync` to retry

### LED is PURPLE during operation
- GCS server is not reachable
- Check network connection to GCS IP
- Verify GCS server is running

### LED is blinking RED
- Critical error occurred
- Check `journalctl -u coordinator` for details
- Run `./tools/recovery.sh health` for diagnostics
