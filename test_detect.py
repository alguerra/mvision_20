import cv2
import numpy as np
from ultralytics import YOLO
import time

try:
    from picamera2 import Picamera2
    cam = Picamera2()
    config = cam.create_still_configuration(main={"size": (640, 480), "format": "RGB888"})
    cam.configure(config)
    cam.start()
    time.sleep(2)
    frame = cam.capture_array()
    frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
    cam.stop()
    cam.close()
    print("Camera: Picamera2")
except Exception:
    cap = cv2.VideoCapture(0)
    time.sleep(1)
    ret, frame = cap.read()
    cap.release()
    if not ret:
        print("FALHA na camera")
        exit()
    print("Camera: OpenCV")

cv2.imwrite("frame_original.jpg", frame)
model = YOLO("yolov8l.pt")

print("=== ORIGINAL ===")
r1 = model.predict(frame, conf=0.05, verbose=False)
for b in r1[0].boxes:
    print(f"  {model.names[int(b.cls)]}: {float(b.conf):.3f}")
if len(r1[0].boxes) == 0:
    print("  Nenhuma")

result = frame.copy()
avg = result.mean(axis=(0, 1))
ga = avg.mean()
for i in range(3):
    if avg[i] > 0:
        result[:, :, i] = np.clip(result[:, :, i] * (ga / avg[i]), 0, 255).astype(np.uint8)

cv2.imwrite("frame_normalizado.jpg", result)

print("=== NORMALIZADO ===")
r2 = model.predict(result, conf=0.05, verbose=False)
for b in r2[0].boxes:
    print(f"  {model.names[int(b.cls)]}: {float(b.conf):.3f}")
if len(r2[0].boxes) == 0:
    print("  Nenhuma")

gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
gray3 = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
cv2.imwrite("frame_gray.jpg", gray3)

print("=== GRAYSCALE ===")
r3 = model.predict(gray3, conf=0.05, verbose=False)
for b in r3[0].boxes:
    print(f"  {model.names[int(b.cls)]}: {float(b.conf):.3f}")
if len(r3[0].boxes) == 0:
    print("  Nenhuma")
