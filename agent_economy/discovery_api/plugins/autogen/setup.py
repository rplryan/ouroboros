from setuptools import setup, find_packages

setup(
    name="autogen-x402-discovery",
    version="1.0.0",
    description="AutoGen function and tool schema for discovering x402-payable services",
    long_description=open("README.md").read() if __import__("os").path.exists("README.md") else "",
    long_description_content_type="text/markdown",
    author="Ouroboros",
    url="https://github.com/IgorBeHolder/Ouroboros",
    packages=find_packages(),
    install_requires=["requests>=2.28.0"],
    python_requires=">=3.8",
    keywords="x402 micropayment autogen agent discovery autonomous",
)
