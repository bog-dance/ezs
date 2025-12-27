from setuptools import setup, find_packages

with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

setup(
    name="ecs-connect",
    version="0.1.0",
    author="Your Name",
    description="Interactive CLI tool for connecting to ECS containers via SSM",
    long_description=long_description,
    long_description_content_type="text/markdown",
    packages=find_packages(),
    python_requires=">=3.8",
    install_requires=[
        "boto3>=1.34.0",
        "simple-term-menu>=1.6.0",
        "rich>=13.7.0",
    ],
    entry_points={
        "console_scripts": [
            "ecs-connect=ecs_connect.main:main",
        ],
    },
    classifiers=[
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
)
