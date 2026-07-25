import os

# Optimized for Render Free Tier (512MB RAM limit & dynamic PORT)
port = os.getenv("PORT", "10000")
bind = f"0.0.0.0:{port}"
workers = 1
threads = 2
timeout = 120
loglevel = "info"
