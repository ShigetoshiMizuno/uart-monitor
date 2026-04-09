# uart_monitor — Shared UART Monitoring Tool for AI + Developer

> **AI と開発者が同時にシリアルポートを監視・操作できるツール**

A Python tool that lets a developer and an AI assistant (like Claude) **simultaneously** watch and interact with a UART device — without fighting over the serial port.

---

## The Problem

Serial ports can only be opened by **one process at a time**.

If the developer opens a serial monitor (e.g. `pio device monitor`), the AI loses access.  
If the AI holds the port, the developer goes blind.

This creates a frustrating back-and-forth when debugging embedded systems together.

---

## The Solution

```
┌──────────────────────────────────────────────────────┐
│                    uart_monitor.py                   │
│                                                      │
│   COM3 (serial port) ──► stdout  (developer sees)   │
│                      └──► uart.log (AI reads)        │
│                                                      │
│   Developer keystrokes ──►  COM3                     │
│   AI writes to COM3    ──►  COM3  (planned)          │
└──────────────────────────────────────────────────────┘
```

`uart_monitor` is the **sole owner** of the serial port.  
It fans out received data to:

1. **stdout** — the developer's terminal (raw, no timestamps)
2. **`uart.log`** — a log file the AI reads in real time (with `[HH:MM:SS]` timestamps, line-flushed)

Both the developer and the AI can send keystrokes/commands to the device.

---

## How It Works

```
Main thread          ┌─────────────────────┐
(input_loop)         │   serial.Serial      │
  msvcrt.kbhit() ──►│       COM3           │◄── Device (ESP32, etc.)
  getwch()      ──►│   timeout=0.1        │
                     └──────────┬──────────┘
                                │ received bytes
                     ┌──────────▼──────────┐
Background thread    │    read_thread       │
(read_thread)        │  buffers until \n   │
                     │  ├─ stdout.write()  │──► Developer terminal
                     │  └─ log_file.write()│──► uart.log (AI reads)
                     └─────────────────────┘
```

- **Two threads**: serial reading (background) + key input (main)
- **Line-buffered log**: every line is flushed immediately so the AI always has fresh data
- **Reconnect logic**: if the device resets, uart_monitor retries up to 5 times (1 s interval)

### AI Workflow

```
Developer & AI
  │
  ├─ Developer: python monitor.py        # opens COM3
  │
  ├─ Device output → uart.log (timestamped, always fresh)
  │
  └─ AI: reads uart.log anytime         # no port conflict
         sends commands via monitor.py  # (planned: AI input pipe)
```

---

## Requirements

- OS: Windows 11 (uses `msvcrt` for keyboard input)
- Python 3.8+
- `pyserial` — `pip install pyserial`

---

## Installation

```bash
pip install pyserial
```

---

## Usage

```bash
# Default: COM3, 115200 baud
python monitor.py

# Custom port / baud rate
python monitor.py --port COM4 --baud 9600
```

### Startup output

```
[uart_monitor] Connected to COM3 @ 115200 baud
[uart_monitor] Logging to: C:\path\to\uart.log
[uart_monitor] Press Ctrl+C to exit.
```

### uart.log format

```
========== Session Start: 2026-04-09 10:00:00 ==========
[10:00:01] Boot message from device
[10:00:02] Sensor reading: temp=24.3
```

### Controls

| Key | Action |
|-----|--------|
| Any character | Send to device + local echo |
| Enter | Send `\r\n` to device |
| Ctrl+C | Disconnect and exit |

---

## File Structure

```
uart_monitor/
├── README.md       # this file
├── monitor.py      # main script
├── start-claude.bat# launch Claude Code in this project
└── uart.log        # generated at runtime (add to .gitignore)
```

---

## .gitignore

```
uart.log
__pycache__/
*.pyc
```

---

## Target Hardware

Developed for **M5Stack AtomS3R (ESP32-S3)**, but works with any UART device on Windows.

---

## License

MIT
