from setuptools import setup, find_packages

setup(
    name="x402discovery",
    version="1.0.0",
    description="Python SDK for the x402 Service Discovery Layer — find and call x402-payable APIs",
    long_description=open("README.md").read() if __import__("os").path.exists("README.md") else "",
    long_description_content_type="text/markdown",
    author="Ouroboros",
    url="https://github.com/IgorBeHolder/Ouroboros",
    packages=find_packages(),
    install_requires=[
        "requests>=2.28.0",
    ],
    python_requires=">=3.8",
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "Topic :: Software Development :: Libraries :: Python Modules",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
    ],
    keywords="x402 micropayment agent discovery api autonomous",
    project_urls={
        "API": "https://x402-discovery-api.onrender.com",
        "Spec": "https://github.com/IgorBeHolder/Ouroboros/blob/ouroboros/agent_economy/discovery_api/SPEC.md",
    },
)
