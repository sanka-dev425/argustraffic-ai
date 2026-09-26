"""
ArgusTraffic AI - Synthetic Traffic Video Generator
Creates an MP4 video file depicting multi-lane highway traffic,
pedestrian crosswalks, wrong-way drivers, and stalled vehicles.
"""

import argparse
from pathlib import Path
import sys
import cv2
from tqdm import tqdm

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.utils.video_stream import SyntheticTrafficSimulator


def generate_demo_video(output_path: str = "demo_traffic.mp4", num_frames: int = 300, fps: int = 30):
    sim = SyntheticTrafficSimulator(width=1280, height=720)
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    out = cv2.VideoWriter(output_path, fourcc, fps, (1280, 720))

    print(f"Generating {num_frames} frames of traffic simulation into '{output_path}'...")
    for _ in tqdm(range(num_frames)):
        frame = sim.next_frame()
        out.write(frame)

    out.release()
    print(f"Successfully created demo video: {output_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="demo_traffic.mp4", help="Output file path")
    parser.add_argument("--frames", type=int, default=300, help="Number of frames to generate")
    parser.add_argument("--fps", type=int, default=30, help="Frames per second")
    args = parser.parse_args()

    generate_demo_video(args.output, args.frames, args.fps)
