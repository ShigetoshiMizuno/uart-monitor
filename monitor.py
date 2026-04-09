"""
uart_monitor — UART共有モニタリングツール

M5Stack AtomS3R (ESP32-S3) のシリアルポートをリアルタイム監視し、
受信データをターミナルとログファイルに同時出力する。
"""

import argparse
import msvcrt
import re
import socket
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

_CTRL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

import serial

__version__ = "1.2.0"

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


def read_thread(
    ser: serial.Serial,
    log_file_holder,
    stop_event: threading.Event,
    udp_sock=None,
    last_udp_sender=None,
    magic_word="",
    log_format="",
) -> None:
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
                line_text = _CTRL_CHARS.sub("", line.decode("utf-8", errors="replace").rstrip("\r"))
            else:
                line_text = _CTRL_CHARS.sub("", buffer.decode("utf-8", errors="replace").rstrip("\r\n"))
                buffer = b""

            # マジックワード検知
            if magic_word and magic_word in line_text:
                # 1. 現在のログにマジックワード行を書き込む
                timestamp = datetime.now().strftime("%H:%M:%S")
                log_file_holder[0].write(f"[{timestamp}] {line_text}\n")
                log_file_holder[0].flush()
                log_file_holder[0].close()

                # 2. 新しいログファイルを開く
                new_path = new_log_path(log_format)
                new_file = open(new_path, "a", encoding="utf-8")
                session_start = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                new_file.write(f"========== Session Start: {session_start} ==========\n")
                new_file.flush()
                log_file_holder[0] = new_file

                # 3. ターミナルに通知
                print(f"\r[uart_monitor] Magic word detected. Rotating log -> {new_path}", flush=True)

                # 4. stdout にも行を表示して次のループへ
                sys.stdout.write(line_text + "\n")
                sys.stdout.flush()
                continue  # 通常の stdout/log 書き込みをスキップ

            # ターミナルにタイムスタンプなしで出力
            sys.stdout.write(line_text + "\n")
            sys.stdout.flush()

            # ログファイルにタイムスタンプ付きで出力
            timestamp = datetime.now().strftime("%H:%M:%S")
            log_file_holder[0].write(f"[{timestamp}] {line_text}\n")
            log_file_holder[0].flush()

            # 最後に UDP コマンドを送ってきたアドレスに返送する
            if udp_sock is not None and last_udp_sender is not None and last_udp_sender[0] is not None:
                try:
                    udp_sock.sendto((line_text + "\n").encode("utf-8"), last_udp_sender[0])
                except Exception:
                    pass  # UDP 送信失敗は無視

    # バッファ残りを処理
    if buffer:
        line_text = buffer.decode("utf-8", errors="replace").rstrip("\r\n")
        sys.stdout.write(line_text + "\n")
        sys.stdout.flush()
        timestamp = datetime.now().strftime("%H:%M:%S")
        log_file_holder[0].write(f"[{timestamp}] {line_text}\n")
        log_file_holder[0].flush()


def udp_thread(
    ser: serial.Serial,
    log_file_holder,
    stop_event: threading.Event,
    udp_port: int,
    udp_sock,
    last_udp_sender,
) -> None:
    """UDP コマンドサーバースレッド: 受信したペイロードをそのまま UART に転送する。"""
    udp_sock.bind(("127.0.0.1", udp_port))
    udp_sock.settimeout(0.5)

    try:
        while not stop_event.is_set():
            try:
                data, addr = udp_sock.recvfrom(4096)
            except socket.timeout:
                continue

            last_udp_sender[0] = addr

            ser.write(data)

            printable = data.decode("utf-8", errors="replace")
            print(f"[UDP->] {printable.rstrip()}", flush=True)

            timestamp = datetime.now().strftime("%H:%M:%S")
            log_file_holder[0].write(f"[{timestamp}] [UDP->] {printable.rstrip()}\n")
            log_file_holder[0].flush()
    finally:
        pass  # ソケットのクローズは main() で行う


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
        elif ch in ("\x00", "\xe0"):
            # Windows 特殊キー: 次の1バイトを読んで VT100 に変換して送信
            ch2 = msvcrt.getwch()
            vt100 = {
                "\x48": b"\x1b[A",  # ↑ Up
                "\x50": b"\x1b[B",  # ↓ Down
                "\x4d": b"\x1b[C",  # → Right
                "\x4b": b"\x1b[D",  # ← Left
                "\x47": b"\x1b[H",  # Home
                "\x4f": b"\x1b[F",  # End
            }.get(ch2)
            if vt100:
                ser.write(vt100)
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
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

    parser = argparse.ArgumentParser(description="UART共有モニタリングツール")
    parser.add_argument("--version", action="version", version=f"uart_monitor {__version__}")
    parser.add_argument("--port", default="COM3", help="シリアルポート (default: COM3)")
    parser.add_argument("--baud", type=int, default=115200, help="ボーレート (default: 115200)")
    parser.add_argument(
        "--log-format",
        default="%Y-%m-%d_%H%M%S.log",
        help="ログファイル名のフォーマット（strftime形式, default: %%Y-%%m-%%d_%%H%%M%%S.log）",
    )
    parser.add_argument(
        "--udp-port",
        type=int,
        default=5555,
        help="UDP リッスンポート (default: 5555、0 で無効化)",
    )
    parser.add_argument(
        "--magic-word",
        default="",
        help="デバイスがこの文字列を送信したらログファイルを切り替える (default: 無効)",
    )
    args = parser.parse_args()

    print(f"[uart_monitor] Connecting to {args.port} @ {args.baud} baud ...")
    print("[uart_monitor] Press Ctrl+C to exit.")
    if args.magic_word:
        print(f'[uart_monitor] Magic word: "{args.magic_word}" (triggers log rotation)')

    last_udp_sender = [None]  # [addr] or [None]

    while True:
        try:
            ser = connect_with_retry(args.port, args.baud)
        except serial.SerialException as e:
            print(f"[uart_monitor] ポートを開けません: {e}", file=sys.stderr)
            sys.exit(1)

        # 再接続のたびにソケットを作り直す（bind し直しのため）
        if args.udp_port != 0:
            udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        else:
            udp_sock = None

        log_path = new_log_path(args.log_format)

        log_file = open(log_path, "a", encoding="utf-8")
        log_file_holder = [log_file]
        try:
            session_start = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            log_file.write(f"========== Session Start: {session_start} ==========\n")
            log_file.flush()

            print(f"[uart_monitor] Connected to {args.port} @ {args.baud} baud")
            print(f"[uart_monitor] Logging to: {log_path.resolve()}")

            if args.udp_port != 0:
                print(f"[uart_monitor] UDP command server listening on 127.0.0.1:{args.udp_port}")

            stop_event = threading.Event()

            reader = threading.Thread(
                target=read_thread,
                args=(ser, log_file_holder, stop_event, udp_sock, last_udp_sender,
                      args.magic_word, args.log_format),
                daemon=True,
            )
            reader.start()

            udp_worker = None
            if args.udp_port != 0:
                udp_worker = threading.Thread(
                    target=udp_thread,
                    args=(ser, log_file_holder, stop_event, args.udp_port, udp_sock, last_udp_sender),
                    daemon=True,
                )
                udp_worker.start()

            try:
                user_exit = input_loop(ser, stop_event)
            except KeyboardInterrupt:
                stop_event.set()
                user_exit = True
        finally:
            stop_event.set()
            reader.join(timeout=2.0)
            if udp_worker is not None:
                udp_worker.join(timeout=2.0)
            if udp_sock is not None:
                udp_sock.close()
            log_file_holder[0].close()
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
