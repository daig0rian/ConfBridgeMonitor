#!/usr/bin/env python3
"""
Phase 1 PoC: ConfBridge Opus frame receiver

WebSocket 2本構成 (Asterisk 公式要件):
  - ARI 制御用 WS  : /ari/events?app=...  (Stasis チャンネルを生かし続ける)
  - Media WS      : /media/<connection_id> (Opus フレームを受信)

Flow:
  1. ARI events WS 接続  (Stasis アプリ登録)
  2. POST /channels/externalMedia  (transport=websocket, connection_type=server)
  3. StasisStart イベント待機
  4. MEETME_ROOMNUM チャンネル変数セット
  5. POST /channels/{id}/continue  → ext-meetme/STARTMEETME/1
  6. Media WS 接続 → Opus フレーム受信 & 保存
  7. 終了時 DELETE /channels/{id}

Usage:
  python receive_opus.py
  python receive_opus.py --bridge 8000 --output out.opus_raw --verbose
"""

import asyncio
import aiohttp
import websockets
import json
import sys
import struct
import argparse
from datetime import datetime

# ---- Defaults ----
ASTERISK_HOST = "192.168.11.31"
ASTERISK_PORT = 8088
ARI_USER      = "confbridge_poc"
ARI_PASS      = "confbridge_poc_pass"
BRIDGE_ID     = "8000"
APP_NAME      = "confbridge_poc"
# ------------------

# Output file: magic(4) + frames [ length(2BE) + opus_data ]
FILE_MAGIC = b"OPSR"


# ── ARI REST helpers ───────────────────────────────────────────────────────────

async def create_external_media(session, base_url, auth):
    url = f"{base_url}/channels/externalMedia"
    params = {
        "app":             APP_NAME,
        "encapsulation":   "none",
        "transport":       "websocket",
        "connection_type": "server",
        "format":          "opus",
        "direction":       "both",
    }
    async with session.post(url, params=params, auth=auth) as resp:
        body = await resp.json()
        if resp.status not in (200, 201):
            raise RuntimeError(
                f"POST /channels/externalMedia failed ({resp.status}):\n"
                + json.dumps(body, indent=2)
            )
        return body


async def set_channel_var(session, base_url, auth, channel_id, variable, value):
    url = f"{base_url}/channels/{channel_id}/variable"
    params = {"variable": variable, "value": value}
    async with session.post(url, params=params, auth=auth) as resp:
        if resp.status not in (200, 204):
            body = await resp.text()
            raise RuntimeError(f"Set variable failed ({resp.status}): {body}")


async def continue_channel(session, base_url, auth, channel_id, context, extension, priority):
    url = f"{base_url}/channels/{channel_id}/continue"
    params = {"context": context, "extension": extension, "priority": priority}
    async with session.post(url, params=params, auth=auth) as resp:
        if resp.status not in (200, 204):
            body = await resp.text()
            raise RuntimeError(f"Continue channel failed ({resp.status}): {body}")


async def delete_channel(session, base_url, auth, channel_id):
    url = f"{base_url}/channels/{channel_id}"
    async with session.delete(url, auth=auth) as resp:
        pass  # best-effort


# ── Media WebSocket receiver ───────────────────────────────────────────────────

async def _do_receive(ws, output_path, verbose):
    frame_count = 0
    byte_count  = 0
    with open(output_path, "wb") as f:
        f.write(FILE_MAGIC)
        async for msg in ws:
            if isinstance(msg, bytes):
                frame_count += 1
                byte_count  += len(msg)
                f.write(struct.pack(">H", len(msg)))
                f.write(msg)
                if verbose or frame_count % 50 == 0:
                    elapsed = frame_count * 0.020
                    print(
                        f"  frames={frame_count:5d}  bytes={byte_count:7,d}"
                        f"  audio={elapsed:.1f}s  last={len(msg)}B",
                        end="\r",
                    )
            else:
                print(f"\n[media] text: {msg}")
    return frame_count, byte_count


async def receive_media_queued(host, port, user, password, connection_id,
                                output_path, verbose, ready_queue):
    """Media WS receiver. Puts True into ready_queue when WS handshake completes."""
    media_url = f"ws://{user}:{password}@{host}:{port}/media/{connection_id}"
    print(f"[media] Connecting: ws://{host}:{port}/media/{connection_id}")
    try:
        async with websockets.connect(media_url, open_timeout=10) as ws:
            print("[media] Connected. Receiving Opus frames -- Ctrl+C to stop.\n")
            await ready_queue.put(True)
            try:
                frame_count, byte_count = await _do_receive(ws, output_path, verbose)
            except asyncio.CancelledError:
                frame_count, byte_count = 0, 0
    except Exception as e:
        print(f"\n[media] Connection error: {e}")
        await ready_queue.put(False)
        return 0

    print(f"\n[media] Done: {frame_count} frames, {byte_count:,} bytes")
    return frame_count


# ── ARI events WebSocket: wait for StasisStart ────────────────────────────────

async def wait_for_stasis_start(ari_ws, channel_id, timeout=5.0, verbose=False):
    print("[ari-ws] Waiting for StasisStart ...")
    deadline = asyncio.get_event_loop().time() + timeout
    while True:
        remaining = deadline - asyncio.get_event_loop().time()
        if remaining <= 0:
            print("[ari-ws] Timeout waiting for StasisStart")
            return False
        try:
            raw = await asyncio.wait_for(ari_ws.recv(), timeout=remaining)
            event = json.loads(raw)
            etype = event.get("type", "")
            if verbose:
                print(f"[ari-ws] {etype}")
            if etype == "StasisStart" and event.get("channel", {}).get("id") == channel_id:
                print("[ari-ws] StasisStart received.")
                return True
        except asyncio.TimeoutError:
            print("[ari-ws] Timeout waiting for StasisStart")
            return False


# ── Main ──────────────────────────────────────────────────────────────────────

async def run(args):
    base_url    = f"http://{args.host}:{args.port}/ari"
    auth        = aiohttp.BasicAuth(args.user, args.password)
    ari_ws_url  = (
        f"ws://{args.user}:{args.password}@{args.host}:{args.port}"
        f"/ari/events?app={APP_NAME}&subscribeAll=true"
    )
    output = args.output or f"confbridge_{datetime.now().strftime('%Y%m%d_%H%M%S')}.opus_raw"

    channel_id    = None
    connection_id = None

    async with aiohttp.ClientSession() as session:
        # 1. ARI events WS (Stasis アプリ登録 -- これがないとチャンネルが即座に破棄される)
        print(f"[ari-ws] Connecting to ARI events WebSocket ...")
        async with websockets.connect(ari_ws_url) as ari_ws:
            print("[ari-ws] Connected.")

            try:
                # 2. externalMedia チャンネル作成
                print("[ari] Creating externalMedia channel ...")
                channel       = await create_external_media(session, base_url, auth)
                channel_id    = channel["id"]
                connection_id = channel["channelvars"]["MEDIA_WEBSOCKET_CONNECTION_ID"]
                print(f"[ari] Channel ID:     {channel_id}")
                print(f"[ari] Connection ID:  {connection_id}")
                if args.verbose:
                    print(json.dumps(channel, indent=2))

                # 3. Media WS 接続 (クライアント接続が channel を answer し StasisStart をトリガーする)
                #    StasisStart 待機と並行して接続を開始する
                media_queue    = asyncio.Queue()
                media_task     = asyncio.create_task(
                    receive_media_queued(
                        args.host, args.port, args.user, args.password,
                        connection_id, output, args.verbose, media_queue,
                    )
                )

                # 4. StasisStart 待機
                ok = await wait_for_stasis_start(ari_ws, channel_id, timeout=10.0,
                                                 verbose=args.verbose)
                if not ok:
                    media_task.cancel()
                    raise RuntimeError("StasisStart not received. Media WS may have failed to connect.")

                # 5. ConfBridge に入るためのチャンネル変数セット
                print(f"[ari] MEETME_ROOMNUM = {args.bridge}")
                await set_channel_var(session, base_url, auth, channel_id,
                                      "MEETME_ROOMNUM", args.bridge)

                # 6. チャンネルをダイヤルプランに送り ConfBridge に参加させる
                print("[ari] Continuing to ext-meetme/STARTMEETME/1 ...")
                await continue_channel(session, base_url, auth, channel_id,
                                       "ext-meetme", "STARTMEETME", 1)
                print(f"[ari] Channel joined ConfBridge '{args.bridge}'.")

                # 7. Media WS タスク完了を待つ (Ctrl+C or WS close)
                frame_count = await media_task

                if frame_count == 0:
                    print("[warn] No frames received. Is there audio activity in the bridge?")
                else:
                    print(f"[ok]  Saved {frame_count} frames to: {output}")
                    print(f"      Decode: python decode_opus_raw.py {output}")

            except (KeyboardInterrupt, asyncio.CancelledError):
                print("\n[info] Stopped by user.")
            finally:
                if channel_id:
                    print(f"[ari] Hanging up channel {channel_id} ...")
                    await delete_channel(session, base_url, auth, channel_id)
                    print("[ari] Done.")


def main():
    parser = argparse.ArgumentParser(
        description="Phase 1 PoC -- ConfBridge Opus receiver via ARI + chan_websocket"
    )
    parser.add_argument("--host",     default=ASTERISK_HOST)
    parser.add_argument("--port",     type=int, default=ASTERISK_PORT)
    parser.add_argument("--user",     default=ARI_USER)
    parser.add_argument("--password", default=ARI_PASS)
    parser.add_argument("--bridge",   default=BRIDGE_ID, help="ConfBridge name (e.g. 8000)")
    parser.add_argument("--output",   default=None, help="Output .opus_raw file path")
    parser.add_argument("--verbose",  action="store_true")
    args = parser.parse_args()

    try:
        asyncio.run(run(args))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
