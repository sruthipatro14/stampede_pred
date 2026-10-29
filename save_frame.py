"""Save the first decoded video frame to frame.png."""
import argparse
from pathlib import Path
import cv2


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("video", help="Path to an existing video")
    parser.add_argument("--frame", type=int, default=0, help="zero-based frame index")
    args = parser.parse_args()
    if args.frame < 0: parser.error("frame must be >=0")
    cap = cv2.VideoCapture(args.video)
    try:
        ok, frame = False, None
        for _ in range(args.frame + 1):
            ok, frame = cap.read()
            if not ok: break
        if not ok:
            raise SystemExit(f"Cannot read selected frame: {args.video}")
        path = Path("frame.png").resolve()
        if not cv2.imwrite(str(path), frame):
            raise SystemExit(f"Cannot save image: {path}")
        height, width = frame.shape[:2]
        print(f"Saved: {path}; width: {width}; height: {height}")
    finally:
        cap.release()


if __name__ == "__main__":
    main()
