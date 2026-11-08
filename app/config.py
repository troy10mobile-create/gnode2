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
APP_VERSION = os.getenv("APP_VERSION", "0.3.0")
PUBLIC_URL = os.getenv("PUBLIC_URL", "").rstrip("/")

# Ports
HTTP_PORT = int(os.getenv("HTTP_PORT", 8332))
P2P_PORT = int(os.getenv("P2P_PORT", 8333))

# Consensus / Economics
DIFFICULTY = int(os.getenv("DIFFICULTY", 4))
INITIAL_BLOCK_REWARD = float(os.getenv("INITIAL_BLOCK_REWARD", 50))
REWARD_REDUCTION_INTERVAL = int(os.getenv("REWARD_REDUCTION_INTERVAL", 1_000_000))  # blocks
REWARD_REDUCTION_FACTOR = float(os.getenv("REWARD_REDUCTION_FACTOR", 0.9))         # 10% reduction
BLOCK_TIME_TARGET = int(os.getenv("BLOCK_TIME_TARGET", 120))  # 2 minutes
MINING_ENABLED = os.getenv("MINING_ENABLED", "true").lower() == "true"

# Pruning
PRUNE_INTERVAL = int(os.getenv("PRUNE_INTERVAL", 10))  # every Nth block is a pruning block

# Coinbase maturity (blocks before coinbase can be spent)
COINBASE_MATURITY = 5

# Genesis
GENESIS_TIMESTAMP = 1231006505
GENESIS_PREV_HASH = "0" * 64
