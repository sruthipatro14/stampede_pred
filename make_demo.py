"""Writes demo.mp4: moving blobs in the Concourse; the Stairs fill then STOP moving (stalled crowd)."""
import cv2, numpy as np, random
random.seed(1); W, H, FPS, DUR = 640, 480, 25, 80
vw = cv2.VideoWriter("demo.mp4", cv2.VideoWriter_fourcc(*"mp4v"), FPS, (W, H))
people = []   # [x, y, zone]
for f in range(FPS * DUR):
    t = f / FPS
    img = np.full((H, W, 3), 90, np.uint8)
    if t > 4:
        if len(people) < 150 and random.random() < 0.6: people.append([20 + random.random() * 40, 110 + random.random() * 280, "c"])
        if 45 < t < 60 and sum(p[2] == "s" for p in people) < 100: people.append([390 + random.random() * 220, 110 + random.random() * 280, "s"])
    for p in people:
        if p[2] == "c": p[0] += 55 / FPS; p[0] = 20 + (p[0] - 20) % 270
        elif t < 55: p[1] += (random.random() - .5) * 2; p[0] += 40 / FPS; p[0] = 380 + (p[0] - 380) % 220
        cv2.rectangle(img, (int(p[0]), int(p[1])), (int(p[0]) + 10, int(p[1]) + 20), (230, 230, 230), -1)
    vw.write(img)
vw.release()
