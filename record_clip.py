"""Record a 45-second webcam clip for local camera calibration."""
from pathlib import Path
import time
import cv2


def main():
    cap = cv2.VideoCapture(0)
    writer = None
    count = 0
    path = Path("scene.mp4").resolve()
    try:
        if not cap.isOpened():
            raise SystemExit("Cannot open webcam 0. On macOS, run this script in Terminal and allow camera access.")
        if path.exists():
            raise SystemExit(f"Refusing to overwrite existing video: {path}")
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        cap.set(cv2.CAP_PROP_FPS, 25)
        start = time.monotonic()
        while time.monotonic() - start < 45:
            ok, frame = cap.read()
            if not ok:
                raise SystemExit(f"Webcam frame read failed after {count} frames.")
            if writer is None:
                writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 25, (640, 480))
                if not writer.isOpened():
                    raise SystemExit(f"Cannot open mp4v video writer: {path}")
            writer.write(cv2.resize(frame, (640, 480)))
            count += 1
            time.sleep(max(0, start + count / 25 - time.monotonic()))
    finally:
        cap.release()
        if writer is not None:
            writer.release()
            print(f"Saved path: {path}; frame count: {count}")


if __name__ == "__main__":
    main()
