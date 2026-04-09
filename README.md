# uart_monitor — Shared UART Monitoring Tool for AI + Developer

> **AI と開発者が同時にシリアルポートを監視・操作できるツール**

A Python tool that lets a developer and an AI assistant (like Claude) **simultaneously** watch and interact with a UART device — without fighting over the serial port.

開発者と AI アシスタント（Claude など）が、シリアルポートを取り合うことなく**同時に** UART デバイスを監視・操作できる Python ツールです。

---

## The Problem / 問題

Serial ports can only be opened by **one process at a time**.

If the developer opens a serial monitor (e.g. `pio device monitor`), the AI loses access.  
If the AI holds the port, the developer goes blind.

This creates a frustrating back-and-forth when debugging embedded systems together.

**シリアルポートは同時に 1 プロセスしかオープンできません。**

開発者がシリアルモニタ（例：`pio device monitor`）を開くと AI がアクセスできなくなり、
AI がポートを占有すると開発者が見えなくなります。

組み込みデバッグを AI と一緒に進めるとき、この「ポートの取り合い」が大きなボトルネックになります。

---

## The Solution / 解決策

```
┌──────────────────────────────────────────────────────────┐
│                     uart_monitor.py                      │
│                                                          │
│   COM3 (serial port) ──► stdout    (developer sees)     │
│                      ├──► uart.log  (AI reads)           │
│                      └──► UDP 5555  (AI receives)        │
│                                                          │
│   Developer keystrokes   ──►  COM3                       │
│   AI: UDP sendto(5555)   ──►  COM3  (bidirectional!)     │
└──────────────────────────────────────────────────────────┘
```

`uart_monitor` is the **sole owner** of the serial port.  
It fans out received data to:

1. **stdout** — the developer's terminal (raw, no timestamps)
2. **timestamped log file** — the AI reads in real time (`[HH:MM:SS]` prefix, line-flushed)
3. **UDP** — responses are sent back to the last UDP sender (bidirectional!)

`uart_monitor` がシリアルポートを**唯一**オープンし、受信データを以下に同時出力します：

1. **stdout** — 開発者のターミナル（タイムスタンプなし、生データ）
2. **タイムスタンプ付きログファイル** — AI がリアルタイムに読む（`[HH:MM:SS]` 付き、1行ごとフラッシュ）
3. **UDP** — 最後にコマンドを送った AI にデバイスの応答を返送（双方向！）

---

## How It Works / 仕組み

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
                     │  ├─ log_file.write()│──► YYYY-MM-DD_HHMMSS.log
                     │  └─ udp_sock.send() │──► AI (last UDP sender)
                     └─────────────────────┘
                     ┌─────────────────────┐
Background thread    │    udp_thread        │
(udp_thread)         │  listens :5555      │◄── AI sends commands
                     │  ser.write(payload) │──► COM3 (UART device)
                     │  remember sender    │    (stores addr for reply)
                     └─────────────────────┘
```

- **3 threads / 3スレッド構成**: キー入力（メイン）＋ シリアル受信 ＋ UDP サーバー
- **Line-buffered log / 行フラッシュ**: 1行ごと即フラッシュ → AI が常に最新データを参照
- **Bidirectional UDP / UDP 双方向**: コマンドを送ると応答が返ってくる
- **Reconnect logic / 再接続**: 切断時は最大5回（1秒間隔）で自動再接続、新ログファイルを生成

### AI Workflow / AI との連携フロー

```python
import socket

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.bind(('127.0.0.1', 9999))   # 返信受信ポート / reply port
sock.settimeout(10)

# コマンド送信 / Send command
sock.sendto(b'status\r\n', ('127.0.0.1', 5555))

# デバイスの応答を受信 / Receive device response
while True:
    data, _ = sock.recvfrom(4096)
    print(data.decode())
```

---

## Requirements / 動作環境

- OS: Windows 11 (uses `msvcrt` for keyboard input)
- Python 3.8+
- `pyserial` — `pip install pyserial`

---

## Installation / インストール

```bash
pip install pyserial
```

---

## Usage / 使い方

```bash
# Default: COM3, 115200 baud, UDP port 5555
python monitor.py

# Custom port / baud rate（ポート・ボーレートを指定）
python monitor.py --port COM4 --baud 9600

# Custom log filename format（ログファイル名フォーマットを変更）
python monitor.py --log-format "uart_%Y%m%d_%H%M%S.log"

# Custom UDP port / Disable UDP（UDP ポート変更・無効化）
python monitor.py --udp-port 6000
python monitor.py --udp-port 0

# Show version / バージョン表示
python monitor.py --version
```

### Startup output / 起動メッセージ

```
[uart_monitor] Connecting to COM3 @ 115200 baud ...
[uart_monitor] Press Ctrl+C to exit.
[uart_monitor] Connected to COM3 @ 115200 baud
[uart_monitor] Logging to: C:\path\to\2026-04-09_100000.log
[uart_monitor] UDP command server listening on 127.0.0.1:5555
```

### Log file format / ログファイル形式

A new file is created on each start and each device restart:

```
========== Session Start: 2026-04-09 10:00:00 ==========
[10:00:01] Boot message from device
[10:00:02] Sensor reading: temp=24.3
[10:00:05] [UDP->] status
[10:00:05] sensor status response...
```

起動時・デバイスリスタートごとに新しいファイルを生成します。

### Controls / キー操作

| Key | Action |
|-----|--------|
| Any character | Send to device + local echo / デバイスに送信＋エコー表示 |
| Enter | Send `\r\n` to device |
| ↑↓←→ | VT100 arrow keys / 矢印キー（VT100 変換） |
| Ctrl+C | Disconnect and exit / 切断して終了 |

---

## File Structure / ファイル構成

```
uart_monitor/
├── README.md                  # this file / 本ファイル
├── monitor.py                 # main script / メインスクリプト
└── 2026-04-09_100000.log      # generated at runtime / 実行時に生成
```

---

## Target Hardware / 対象ハードウェア

Developed for **M5Stack AtomS3R (ESP32-S3)**, but works with any UART device on Windows.

**M5Stack AtomS3R（ESP32-S3）** での使用を想定していますが、Windows 上の UART デバイス全般で動作します。

---

## License

MIT
