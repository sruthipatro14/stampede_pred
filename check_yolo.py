"""Sample ten evenly spaced video frames and annotate person detections."""
import argparse
import json
from pathlib import Path
import cv2
import numpy as np


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("video", type=Path)
    args = parser.parse_args()
    if not args.video.is_file():
        parser.exit(1, f"Video file does not exist: {args.video}\n")
    cap = cv2.VideoCapture(str(args.video))
    try:
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if not cap.isOpened() or total < 1:
            parser.exit(1, f"Cannot read video or determine frame count: {args.video}\n")
        from ultralytics import YOLO
        cfg = json.loads(Path(__file__).with_name("config.json").read_text())
        model = YOLO(cfg["yolo_model"])
        output = Path("yolo_check") / args.video.stem
        output.mkdir(parents=True, exist_ok=True)
        for index in np.linspace(0, total - 1, 10, dtype=int):
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(index))
            ok, frame = cap.read()
            if not ok:
                parser.exit(1, f"Cannot decode frame {index}: {args.video}\n")
            result = model(frame, classes=[0], conf=cfg["yolo_conf"], verbose=False)[0]
            points = [((float(x1) + float(x2)) / 2, float(y2))
                      for x1, y1, x2, y2 in result.boxes.xyxy.cpu().numpy().astype(int)]
            counts = {z["name"]: sum(cv2.pointPolygonTest(np.array(z["image_polygon"], np.int32), p, False) >= 0
                                      for p in points) for z in cfg["zones"]}
            path = output / f"frame_{index:06d}.jpg"
            if not cv2.imwrite(str(path), result.plot()):
                parser.exit(1, f"Cannot save annotated frame: {path}\n")
            print(f"frame {index}: people={len(result.boxes)}; zones={counts}; saved={path}", flush=True)
    finally:
        cap.release()


if __name__ == "__main__":
    main()
