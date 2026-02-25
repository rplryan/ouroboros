from setuptools import setup, find_packages

setup(
    name="crewai-x402-discovery",
    version="1.0.0",
    description="CrewAI tool for discovering x402-payable services at runtime",
    long_description=open("README.md").read() if __import__("os").path.exists("README.md") else "",
    long_description_content_type="text/markdown",
    author="Ouroboros",
    url="https://github.com/IgorBeHolder/Ouroboros",
    packages=find_packages(),
    install_requires=["crewai>=0.28.0", "requests>=2.28.0", "pydantic>=2.0.0"],
    python_requires=">=3.9",
    keywords="x402 micropayment crewai agent discovery autonomous",
)
