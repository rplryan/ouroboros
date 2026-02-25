from setuptools import setup, find_packages

setup(
    name="llama-index-x402-discovery",
    version="1.0.0",
    description="LlamaIndex FunctionTool for x402 Service Discovery — find paid API services at runtime",
    long_description=open("README.md").read() if __import__("os").path.exists("README.md") else "",
    long_description_content_type="text/markdown",
    author="Ouroboros",
    url="https://github.com/IgorBeHolder/Ouroboros",
    packages=find_packages(),
    install_requires=[
        "llama-index-core>=0.10.0",
        "requests>=2.28.0",
    ],
    python_requires=">=3.8",
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "Topic :: Software Development :: Libraries :: Python Modules",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
    ],
    keywords="x402 llama-index llamaindex agent tool discovery micropayment",
    project_urls={
        "API": "https://x402-discovery-api.onrender.com",
    },
)
