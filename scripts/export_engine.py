"""
ArgusTraffic AI - High-Performance Model Export & Optimization Engine
Exports YOLOv8/v11 models to ONNX Runtime and TensorRT with FP16/INT8 Quantization.
Usage:
    python scripts/export_engine.py --weights yolov8n.pt --format onnx --half
    python scripts/export_engine.py --weights yolov8n.pt --format engine --half
"""

import argparse
import logging
from pathlib import Path
import sys
import time

# Ensure project root in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ultralytics import YOLO

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("argustraffic.export")


def export_model(
    weights_path: str = "yolov8n.pt",
    format_type: str = "onnx",
    img_size: int = 640,
    half: bool = True,
    device: str = "0",
):
    logger.info("=" * 65)
    logger.info("   ARGUSTRAFFIC AI - TENSORRT / ONNX MODEL COMPILER")
    logger.info("=" * 65)
    logger.info(f"Loading checkpoint: {weights_path}...")
    model = YOLO(weights_path)

    logger.info(f"Exporting model to '{format_type.upper()}' (Half/FP16={half}, ImgSz={img_size})...")
    start_time = time.perf_counter()

    try:
        exported_path = model.export(
            format=format_type,
            imgsz=img_size,
            half=half,
            device=device,
            dynamic=True,
            simplify=True,
        )
        elapsed = time.perf_counter() - start_time
        logger.info(f"✓ Model successfully compiled in {elapsed:.2f}s!")
        logger.info(f"Exported artifact location: {exported_path}")
        return exported_path
    except Exception as e:
        logger.error(f"Export failed: {e}")
        return None


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Export YOLO models to ONNX/TensorRT")
    parser.add_argument("--weights", default="yolov8n.pt", help="Path to input weights (.pt)")
    parser.add_argument("--format", default="onnx", choices=["onnx", "engine", "torchscript"], help="Export format")
    parser.add_argument("--imgsz", type=int, default=640, help="Inference resolution")
    parser.add_argument("--half", action="store_true", default=True, help="Enable FP16 half precision")
    parser.add_argument("--device", default="cpu", help="Device to compile on ('cpu' or '0')")
    args = parser.parse_args()

    export_model(
        weights_path=args.weights,
        format_type=args.format,
        img_size=args.imgsz,
        half=args.half,
        device=args.device,
    )
