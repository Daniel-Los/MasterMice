# mx4-rumble-bridge

A small Windows Python bridge that forwards Xbox/XInput controller rumble into the Logitech MX Master 4 haptic motor through the existing MasterMice service.

## Design

This project does not talk to the Logitech HID device directly. It is intentionally a client of the MasterMice named-pipe service, which is the component that owns the HID++ connection.

Relevant protocol contract from MasterMice:

- JSON-lines on `\\.\pipe\MasterMice`
- request shape: `{"id": 1, "cmd": "haptic_trigger", "params": {"pulse_type": 4}}`
- response shape: `{"id": 1, "ok": true, "data": {...}}`

Valid haptic pulse values are the real MasterMice values:

- `0x01` = nudge
- `0x02` = light
- `0x04` = tick
- `0x08` = strong
- `0x06` = buzz
- `0x0A` = burst
- `0x0C` = triple
- `0x0E` = double-buzz

## Install

```powershell
py -m pip install vgamepad
```

## Run

```powershell
py mx4_rumble_bridge/main.py
```

Verbose sent-event logging:

```powershell
py mx4_rumble_bridge/main.py --verbose
```

Test every supported MasterMice waveform at 50% intensity:

```powershell
py mx4_rumble_bridge/main.py --test-haptics
```

Run mapper tests without a mouse or controller:

```powershell
py -m unittest discover -s tests -v
```

One-off hardware test:

```powershell
py mx4_rumble_bridge/main.py --test-haptics
```

The first version creates a virtual Xbox 360 controller and listens for its
rumble notifications. A game may only send rumble when it receives controller
input from that same virtual controller. Physical-controller passthrough is
intentionally not implemented yet.
