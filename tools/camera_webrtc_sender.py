"""
tools/camera_webrtc_sender.py
-----------------------------
Minimal desktop webcam WebRTC sender for the Galaxy Gateway.

Captures video from a local webcam using OpenCV, wraps it in an aiortc
MediaStreamTrack, and performs a WebRTC offer/answer + ICE exchange over the
Gateway signaling WebSocket endpoint::

    ws://GATEWAY_HOST/ws/webrtc/{device_id}

Usage
-----
Install dependencies first (see tools/requirements.txt)::

    pip install -r tools/requirements.txt

Run the sender::

    python tools/camera_webrtc_sender.py \
        --device-id desktop_cam_1 \
        --gateway-ws-url ws://localhost:8765/ws/webrtc \
        --camera-index 0 \
        --frame-rate 15 \
        --resolution 1280x720

Environment variables (override any CLI argument)
--------------------------------------------------
DEVICE_ID         Unique device identifier sent in signaling (default: desktop_cam_1)
GATEWAY_WS_URL    Base WebSocket URL of the Gateway, without trailing device_id
                  (default: ws://localhost:8765/ws/webrtc)
CAMERA_INDEX      OpenCV camera index to open (default: 0)
FRAME_RATE        Target frames-per-second for the video track (default: 15)
RESOLUTION        WxH resolution string, e.g. 1280x720 (default: 1280x720)
"""

import argparse
import asyncio
import json
import logging
import os
import sys
import time

import av
import cv2
import websockets
from aiortc import RTCIceCandidate, RTCPeerConnection, RTCSessionDescription, VideoStreamTrack
from aiortc.contrib.media import MediaBlackhole

logger = logging.getLogger("camera_webrtc_sender")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

# ---------------------------------------------------------------------------
# Custom video track backed by OpenCV
# ---------------------------------------------------------------------------

class WebcamVideoTrack(VideoStreamTrack):
    """A VideoStreamTrack that reads frames from a local webcam via OpenCV."""

    kind = "video"

    def __init__(self, camera_index: int = 0, width: int = 1280, height: int = 720, fps: int = 15):
        super().__init__()
        self._camera_index = camera_index
        self._width = width
        self._height = height
        self._fps = fps
        self._cap = None
        self._frame_interval = 1.0 / fps
        self._last_frame_time = 0.0

    def _open_capture(self) -> None:
        self._cap = cv2.VideoCapture(self._camera_index)
        if not self._cap.isOpened():
            raise RuntimeError(
                f"Cannot open camera at index {self._camera_index}. "
                "Check that the webcam is connected and CAMERA_INDEX is correct."
            )
        self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, self._width)
        self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self._height)
        self._cap.set(cv2.CAP_PROP_FPS, self._fps)
        logger.info(
            "Opened webcam %d at %dx%d @ %dfps",
            self._camera_index, self._width, self._height, self._fps,
        )

    async def recv(self):  # noqa: D102
        if self._cap is None:
            self._open_capture()

        # Throttle to requested frame rate
        now = time.monotonic()
        wait = self._frame_interval - (now - self._last_frame_time)
        if wait > 0:
            await asyncio.sleep(wait)
        self._last_frame_time = time.monotonic()

        ret, frame_bgr = self._cap.read()
        if not ret:
            logger.warning("Webcam read failed; retrying…")
            ret, frame_bgr = self._cap.read()
            if not ret:
                raise RuntimeError("Webcam stopped producing frames.")

        # Convert BGR (OpenCV) → RGB (av/aiortc expected format)
        frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)

        video_frame = av.VideoFrame.from_ndarray(frame_rgb, format="rgb24")
        video_frame.pts, video_frame.time_base = await self.next_timestamp()
        return video_frame

    def stop(self) -> None:
        super().stop()
        if self._cap is not None:
            self._cap.release()
            self._cap = None


# ---------------------------------------------------------------------------
# Signaling helpers
# ---------------------------------------------------------------------------

def _parse_ice_candidate(candidate_dict: dict) -> RTCIceCandidate | None:
    """Parse a Gateway ice_candidate message into an aiortc RTCIceCandidate."""
    candidate_str = candidate_dict.get("candidate", "")
    sdp_mid = candidate_dict.get("sdpMid", "0")
    sdp_mline_index = candidate_dict.get("sdpMLineIndex", 0)

    if not candidate_str:
        return None

    # aiortc expects the raw SDP candidate line (without "candidate:" prefix
    # stripped — it handles both forms).
    from aiortc.sdp import candidate_from_sdp

    try:
        candidate = candidate_from_sdp(candidate_str.split(":", 1)[-1])
        candidate.sdpMid = sdp_mid
        candidate.sdpMLineIndex = int(sdp_mline_index)
        return candidate
    except (ValueError, IndexError, AttributeError, KeyError) as exc:
        logger.debug("Failed to parse ICE candidate: %s — %s", candidate_str, exc)
        return None


# ---------------------------------------------------------------------------
# Main sender logic
# ---------------------------------------------------------------------------

async def run_sender(
    device_id: str,
    gateway_ws_url: str,
    camera_index: int,
    frame_rate: int,
    width: int,
    height: int,
) -> None:
    """Connect to the Gateway, negotiate WebRTC, and stream webcam video."""

    # Build the full signaling WebSocket URL
    ws_url = f"{gateway_ws_url.rstrip('/')}/{device_id}"
    logger.info("Connecting to Gateway signaling: %s", ws_url)

    pc = RTCPeerConnection()
    sink = MediaBlackhole()  # discard any incoming media from the remote peer

    video_track = WebcamVideoTrack(
        camera_index=camera_index,
        width=width,
        height=height,
        fps=frame_rate,
    )
    pc.addTrack(video_track)

    @pc.on("track")
    def on_track(track):
        logger.info("Received remote track: %s (discarding)", track.kind)
        sink.addTrack(track)

    @pc.on("connectionstatechange")
    async def on_connection_state_change():
        logger.info("PeerConnection state → %s", pc.connectionState)
        if pc.connectionState in ("failed", "closed"):
            await pc.close()

    try:
        async with websockets.connect(ws_url) as ws:
            logger.info("WebSocket connected to Gateway")

            # Register ICE candidate handler here so `ws` is in scope.
            @pc.on("icecandidate")
            async def on_ice_candidate(candidate):
                if candidate is None:
                    return
                msg = {
                    "type": "ice_candidate",
                    "candidate": f"candidate:{candidate.to_sdp()}",
                    "sdpMid": candidate.sdpMid or "0",
                    "sdpMLineIndex": candidate.sdpMLineIndex or 0,
                }
                logger.debug("Sending ICE candidate: %s", msg["candidate"])
                await ws.send(json.dumps(msg))

            # Create and send the SDP offer
            offer = await pc.createOffer()
            await pc.setLocalDescription(offer)
            offer_msg = {
                "type": "offer",
                "sdp": pc.localDescription.sdp,
            }
            logger.info("Sending SDP offer for device_id=%s", device_id)
            await ws.send(json.dumps(offer_msg))

            # Process incoming signaling messages
            async for raw_msg in ws:
                try:
                    msg = json.loads(raw_msg)
                except json.JSONDecodeError:
                    logger.warning("Non-JSON message received; ignoring: %r", raw_msg)
                    continue

                msg_type = msg.get("type")

                if msg_type == "answer":
                    logger.info("Received SDP answer")
                    await pc.setRemoteDescription(
                        RTCSessionDescription(sdp=msg["sdp"], type="answer")
                    )

                elif msg_type == "ice_candidate":
                    candidate = _parse_ice_candidate(msg)
                    if candidate is not None:
                        logger.debug("Adding remote ICE candidate")
                        await pc.addIceCandidate(candidate)

                elif msg_type == "ice_servers":
                    # Gateway pushes STUN/TURN config on connect (Round 6).
                    # We log it but do not reconfigure after the offer is
                    # already sent — for a production client you would apply
                    # these before createOffer().
                    logger.info(
                        "Received ice_servers hint from Gateway: %s",
                        msg.get("ice_servers"),
                    )

                elif msg_type in ("error", "close"):
                    logger.error("Gateway signaling error/close: %s", msg)
                    break

                else:
                    logger.debug("Unknown signaling message type=%s; ignoring", msg_type)

    except websockets.exceptions.ConnectionClosedOK:
        logger.info("Signaling WebSocket closed normally")
    except websockets.exceptions.ConnectionClosedError as exc:
        logger.error("Signaling WebSocket closed with error: %s", exc)
    finally:
        video_track.stop()
        await sink.stop()
        await pc.close()
        logger.info("Sender shut down")


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def _parse_resolution(res: str) -> tuple[int, int]:
    parts = res.lower().split("x")
    if len(parts) != 2:
        raise argparse.ArgumentTypeError(
            f"Invalid resolution '{res}'. Expected format: WxH (e.g. 1280x720)"
        )
    return int(parts[0]), int(parts[1])


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Desktop webcam WebRTC sender for Galaxy Gateway",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--device-id",
        default=os.environ.get("DEVICE_ID", "desktop_cam_1"),
        help="Unique device ID (env: DEVICE_ID)",
    )
    parser.add_argument(
        "--gateway-ws-url",
        default=os.environ.get("GATEWAY_WS_URL", "ws://localhost:8765/ws/webrtc"),
        help="Base Gateway WebSocket URL without trailing device_id "
             "(env: GATEWAY_WS_URL)",
    )
    parser.add_argument(
        "--camera-index",
        type=int,
        default=int(os.environ.get("CAMERA_INDEX", "0")),
        help="OpenCV camera index (env: CAMERA_INDEX, default: 0)",
    )
    parser.add_argument(
        "--frame-rate",
        type=int,
        default=int(os.environ.get("FRAME_RATE", "15")),
        help="Target frames per second (env: FRAME_RATE, default: 15)",
    )
    parser.add_argument(
        "--resolution",
        default=os.environ.get("RESOLUTION", "1280x720"),
        help="Video resolution as WxH (env: RESOLUTION, default: 1280x720)",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable debug logging",
    )

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    try:
        width, height = _parse_resolution(args.resolution)
    except argparse.ArgumentTypeError as exc:
        parser.error(str(exc))
        sys.exit(1)

    logger.info(
        "Starting webcam sender — device_id=%s camera=%d resolution=%dx%d fps=%d",
        args.device_id, args.camera_index, width, height, args.frame_rate,
    )

    try:
        asyncio.run(
            run_sender(
                device_id=args.device_id,
                gateway_ws_url=args.gateway_ws_url,
                camera_index=args.camera_index,
                frame_rate=args.frame_rate,
                width=width,
                height=height,
            )
        )
    except KeyboardInterrupt:
        logger.info("Interrupted by user")


if __name__ == "__main__":
    main()
