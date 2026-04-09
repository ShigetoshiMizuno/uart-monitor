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

`uart_monitor` がシリアルポートを**唯一**オープンし、受信データを以下に同時出力します：

1. **stdout** — 開発者のターミナル（タイムスタンプなし、生データ）
2. **`uart.log`** — AI がリアルタイムに読むログファイル（`[HH:MM:SS]` タイムスタンプ付き、1行ごとフラッシュ）

開発者も AI も、どちらからでもデバイスにコマンドを送信できます。

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
                     │  └─ log_file.write()│──► uart.log (AI reads)
                     └─────────────────────┘
```

- **Two threads / 2スレッド構成**: シリアル受信（バックグラウンド）＋ キー入力（メイン）
- **Line-buffered log / 行フラッシュ**: 1行受信するたびに即フラッシュ → AI が常に最新データを参照できる
- **Reconnect logic / 再接続**: デバイスリセット時は最大5回（1秒間隔）で自動再接続

### AI Workflow / AI との連携フロー

```
Developer & AI
  │
  ├─ Developer: python monitor.py        # COM3 をオープン
  │
  ├─ Device output → uart.log（タイムスタンプ付き、常に最新）
  │
  └─ AI: reads uart.log anytime         # ポート競合なし
         sends commands via monitor.py  # （予定: AI 入力パイプ）
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
# Default: COM3, 115200 baud
python monitor.py

# Custom port / baud rate（ポート・ボーレートを指定）
python monitor.py --port COM4 --baud 9600
```

### Startup output / 起動メッセージ

```
[uart_monitor] Connected to COM3 @ 115200 baud
[uart_monitor] Logging to: C:\path\to\uart.log
[uart_monitor] Press Ctrl+C to exit.
```

### uart.log format / ログ形式

```
========== Session Start: 2026-04-09 10:00:00 ==========
[10:00:01] Boot message from device
[10:00:02] Sensor reading: temp=24.3
```

### Controls / キー操作

| Key | Action |
|-----|--------|
| Any character | Send to device + local echo / デバイスに送信＋エコー表示 |
| Enter | Send `\r\n` to device |
| Ctrl+C | Disconnect and exit / 切断して終了 |

---

## File Structure / ファイル構成

```
uart_monitor/
├── README.md       # this file / 本ファイル
├── monitor.py      # main script / メインスクリプト
└── uart.log        # generated at runtime / 実行時に生成（.gitignore 推奨）
```

---

## Target Hardware / 対象ハードウェア

Developed for **M5Stack AtomS3R (ESP32-S3)**, but works with any UART device on Windows.

**M5Stack AtomS3R（ESP32-S3）** での使用を想定していますが、Windows 上の UART デバイス全般で動作します。

---

## License

MIT
