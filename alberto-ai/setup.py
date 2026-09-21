"""
Alberto AI — setup.

Install:
    pip install -e .

After install, the `alberto` command is on PATH:
    alberto banner
    alberto chat "olá"
    alberto serve --port 8741   # starts the 3D web UI
"""
from setuptools import setup, find_packages

setup(
    name="alberto-ai",
    version="1.0.0",
    description="Sandboxed multi-agent coding assistant (NemoClaw + MiMo + Hermes + AIoX)",
    author="Alberto AI Team",
    license="Apache-2.0",
    packages=find_packages(exclude=["tests", "upstream.*", "upstream", "docs"]),
    package_data={
        "": [
            "workflows/*.yaml",
            "personas/*.md",
            "frontend/*.html",
            "frontend/css/*.css",
            "frontend/js/*.js",
        ],
    },
    include_package_data=True,
    entry_points={
        "console_scripts": [
            "alberto=alberto.cli:main",
            "alberto-serve=bin.alberto_serve:main",
        ],
    },
    python_requires=">=3.9",
    install_requires=[
        "pyyaml>=6.0",
        "fastapi>=0.110.0",
        "uvicorn[standard]>=0.27.0",
        "pydantic>=2.0.0",
        "httpx>=0.27.0",
        "openai>=1.0.0",
    ],
    extras_require={
        "dev": ["pytest>=7.0", "pytest-cov>=4.0", "httpx>=0.27.0", "playwright>=1.40"],
    },
)