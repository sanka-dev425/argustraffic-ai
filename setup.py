from setuptools import setup, find_packages

setup(
    name="argustraffic",
    version="1.0.0",
    description="ArgusTraffic AI: Real-Time Autonomous Incident & Traffic Hazard Vision Intelligence Engine",
    author="ArgusTraffic AI Contributors",
    packages=find_packages(),
    python_requires=">=3.9",
    install_requires=[
        "ultralytics>=8.3.0",
        "torch>=2.0.0",
        "opencv-python>=4.8.0",
        "fastapi>=0.110.0",
        "uvicorn>=0.28.0",
        "pydantic>=2.5.0",
        "pyyaml>=6.0.0",
    ],
    entry_points={
        "console_scripts": [
            "argus=src.cli.main:main",
            "argus-server=src.api.app:start_server",
        ],
    },
)
