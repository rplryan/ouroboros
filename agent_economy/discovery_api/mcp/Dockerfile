FROM python:3.11-slim

LABEL org.opencontainers.image.title="x402 Discovery MCP Server"
LABEL org.opencontainers.image.description="MCP server exposing the x402 Service Discovery API as native tools"
LABEL org.opencontainers.image.url="https://github.com/rplryan/ouroboros"

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY server.py .

CMD ["python", "server.py"]
