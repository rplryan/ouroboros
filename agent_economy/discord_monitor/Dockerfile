FROM python:3.11-slim

WORKDIR /app

# Copy only what's needed
COPY agent_economy/discord_monitor/requirements.txt .
RUN pip install --no-cache-dir "discord.py-self>=2.1.0" aiohttp>=3.9.0

COPY agent_economy/ agent_economy/
COPY discord_monitor_main.py .

# Create empty __init__ for package resolution
RUN touch agent_economy/__init__.py 2>/dev/null || true

CMD ["python", "discord_monitor_main.py"]
