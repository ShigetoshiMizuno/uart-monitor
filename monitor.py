"""
uart_monitor — UART共有モニタリングツール

M5Stack AtomS3R (ESP32-S3) のシリアルポートをリアルタイム監視し、
受信データをターミナルとログファイルに同時出力する。
"""

import argparse
import msvcrt
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

import serial

__version__ = "1.0.0"

RECONNECT_ATTEMPTS = 5
RECONNECT_INTERVAL = 1.0


def open_serial(port: str, baud: int) -> serial.Serial:
    return serial.Serial(port, baud, timeout=0.1)


def connect_with_retry(port: str, baud: int) -> serial.Serial:
    for attempt in range(1, RECONNECT_ATTEMPTS + 1):
        try:
            ser = open_serial(port, baud)
            return ser
        except serial.SerialException as e:
            if attempt < RECONNECT_ATTEMPTS:
                print(f"\r[uart_monitor] 再接続試行 {attempt}/{RECONNECT_ATTEMPTS}: {e}", flush=True)
                time.sleep(RECONNECT_INTERVAL)
            else:
                raise
    raise serial.SerialException("再接続失敗")


def read_thread(ser: serial.Serial, log_file, stop_event: threading.Event) -> None:
    """シリアル受信スレッド: 受信データをターミナルとログに出力する。"""
    buffer = b""
    while not stop_event.is_set():
        try:
            chunk = ser.read(256)
        except serial.SerialException:
            if not stop_event.is_set():
                print("\r[uart_monitor] シリアルポートが切断されました。", flush=True)
                stop_event.set()
            break

        if not chunk:
            continue

        buffer += chunk

        # 改行単位で処理する
        while b"\n" in buffer or (len(buffer) > 0 and stop_event.is_set()):
            if b"\n" in buffer:
                line, buffer = buffer.split(b"\n", 1)
                line_text = line.decode("utf-8", errors="replace").rstrip("\r")
            else:
                line_text = buffer.decode("utf-8", errors="replace").rstrip("\r\n")
                buffer = b""

            # ターミナルにタイムスタンプなしで出力
            sys.stdout.write(line_text + "\n")
            sys.stdout.flush()

            # ログファイルにタイムスタンプ付きで出力
            timestamp = datetime.now().strftime("%H:%M:%S")
            log_file.write(f"[{timestamp}] {line_text}\n")
            log_file.flush()

    # バッファ残りを処理
    if buffer:
        line_text = buffer.decode("utf-8", errors="replace").rstrip("\r\n")
        sys.stdout.write(line_text + "\n")
        sys.stdout.flush()
        timestamp = datetime.now().strftime("%H:%M:%S")
        log_file.write(f"[{timestamp}] {line_text}\n")
        log_file.flush()


def input_loop(ser: serial.Serial, stop_event: threading.Event) -> bool:
    """メインスレッドのキー入力ループ: 入力をデバイスに送信する。

    Returns:
        True  — Ctrl+C によるユーザー終了
        False — stop_event が外部（切断検知）によってセットされた
    """
    while not stop_event.is_set():
        if not msvcrt.kbhit():
            time.sleep(0.01)
            continue

        ch = msvcrt.getwch()

        if ch == "\x03":
            # Ctrl+C
            stop_event.set()
            return True

        if ch in ("\r", "\n"):
            # Enter キー: デバイスに \r\n を送信、ターミナルに改行をエコー
            ser.write(b"\r\n")
            sys.stdout.write("\n")
            sys.stdout.flush()
        else:
            encoded = ch.encode("utf-8", errors="replace")
            ser.write(encoded)
            # ローカルエコー
            sys.stdout.write(ch)
            sys.stdout.flush()

    # stop_event が外部によってセットされた（切断検知）
    return False


def new_log_path(log_format: str) -> Path:
    return Path(datetime.now().strftime(log_format))


def main() -> None:
    parser = argparse.ArgumentParser(description="UART共有モニタリングツール")
    parser.add_argument("--version", action="version", version=f"uart_monitor {__version__}")
    parser.add_argument("--port", default="COM3", help="シリアルポート (default: COM3)")
    parser.add_argument("--baud", type=int, default=115200, help="ボーレート (default: 115200)")
    parser.add_argument(
        "--log-format",
        default="%Y-%m-%d_%H%M%S.log",
        help="ログファイル名のフォーマット（strftime形式, default: %%Y-%%m-%%d_%%H%%M%%S.log）",
    )
    args = parser.parse_args()

    print(f"[uart_monitor] Connecting to {args.port} @ {args.baud} baud ...")
    print("[uart_monitor] Press Ctrl+C to exit.")

    while True:
        try:
            ser = connect_with_retry(args.port, args.baud)
        except serial.SerialException as e:
            print(f"[uart_monitor] ポートを開けません: {e}", file=sys.stderr)
            sys.exit(1)

        log_path = new_log_path(args.log_format)

        with open(log_path, "a", encoding="utf-8") as log_file:
            session_start = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            log_file.write(f"========== Session Start: {session_start} ==========\n")
            log_file.flush()

            print(f"[uart_monitor] Connected to {args.port} @ {args.baud} baud")
            print(f"[uart_monitor] Logging to: {log_path.resolve()}")

            stop_event = threading.Event()

            reader = threading.Thread(
                target=read_thread,
                args=(ser, log_file, stop_event),
                daemon=True,
            )
            reader.start()

            try:
                user_exit = input_loop(ser, stop_event)
            except KeyboardInterrupt:
                stop_event.set()
                user_exit = True
            finally:
                stop_event.set()
                reader.join(timeout=2.0)
                if ser.is_open:
                    ser.close()

        if user_exit:
            print("\r[uart_monitor] Disconnected.")
            break

        # デバイス切断による再接続
        print("[uart_monitor] デバイスの再接続を待機しています...")
        time.sleep(RECONNECT_INTERVAL)


if __name__ == "__main__":
    main()
