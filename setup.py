from setuptools import setup, find_packages

setup(
    name="argustraffic",
    version="2.0.0",
    description="ArgusTraffic AI: Enterprise Autonomous Incident & Traffic Hazard Vision Intelligence Engine",
    author="Saptha Sanka",
    author_email="sapthasanka@gmail.com",
    url="https://github.com/sanka-dev425/argustraffic-ai",
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
