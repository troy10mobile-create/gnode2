import os
from dotenv import load_dotenv
from pathlib import Path

load_dotenv()

# Paths
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("DATA_DIR", BASE_DIR / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)

# Network
DISCOVERY_URL = os.getenv("DISCOVERY_URL", "").rstrip("/")
NETWORK_SECRET = os.getenv("NETWORK_SECRET", "dev-secret-change-me")
NETWORK_ID = os.getenv("NETWORK_ID", "mainnet")
APP_VERSION = os.getenv("APP_VERSION", "0.2.0")
PUBLIC_URL = os.getenv("PUBLIC_URL", "").rstrip("/")

# Ports
HTTP_PORT = int(os.getenv("HTTP_PORT", 8332))
P2P_PORT = int(os.getenv("P2P_PORT", 8333))

# Consensus / Economics
DIFFICULTY = int(os.getenv("DIFFICULTY", 4))
BLOCK_REWARD = int(os.getenv("BLOCK_REWARD", 50))
BLOCK_TIME_TARGET = int(os.getenv("BLOCK_TIME_TARGET", 30))  # seconds (short for testing)
MINING_ENABLED = os.getenv("MINING_ENABLED", "true").lower() == "true"

# Coinbase maturity (blocks before coinbase can be spent)
COINBASE_MATURITY = 5  # lower than Bitcoin for easier testing

# Genesis
GENESIS_TIMESTAMP = 1231006505
GENESIS_PREV_HASH = "0" * 64
