"""
ArgusTraffic AI - Model Weights Downloader & Checkpoint Verifier
Downloads and validates YOLOv8, YOLOv11, or RT-DETR pretrained checkpoints.
"""

import argparse
from pathlib import Path
from ultralytics import YOLO

CHECKPOINTS = {
    "yolov8n.pt": "YOLOv8 Nano (Fastest, Edge/CPU optimized, 3.2M params)",
    "yolov8s.pt": "YOLOv8 Small (Balanced latency/accuracy, 11.2M params)",
    "yolov8m.pt": "YOLOv8 Medium (High accuracy, 25.9M params)",
    "yolov8x.pt": "YOLOv8 XLarge (Maximum mAP benchmark, 68.2M params)",
}


def download_and_verify(model_names):
    print("=" * 60)
    print("   ARGUSTRAFFIC AI - WEIGHTS DOWNLOADER & VERIFIER   ")
    print("=" * 60)

    for name in model_names:
        desc = CHECKPOINTS.get(name, "Custom / Community Checkpoint")
        print(f"\n[+] Verifying checkpoint: '{name}' ({desc})...")
        try:
            model = YOLO(name)
            print(f"    ✓ Successfully loaded '{name}' (Classes: {len(model.names)})")
        except Exception as e:
            print(f"    ✗ Failed to download '{name}': {e}")

    print("\nCheckpoint verification complete!")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Download model weights")
    parser.add_argument(
        "--models",
        nargs="+",
        default=["yolov8n.pt", "yolov8s.pt"],
        help="List of model weights to download and cache",
    )
    args = parser.parse_args()
    download_and_verify(args.models)
