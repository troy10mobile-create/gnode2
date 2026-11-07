import asyncio
import uvicorn
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pathlib import Path

from app.config import HTTP_PORT, PUBLIC_URL, MINING_ENABLED, DATA_DIR
from app.blockchain.chain import Blockchain
from app.wallet.wallet import Wallet
from app.network.discovery import DiscoveryClient
from app.network.p2p import PeerManager
from app.api.routes import router, init_routes


# Global instances
blockchain = Blockchain(DATA_DIR)
wallet = Wallet(DATA_DIR)
discovery = DiscoveryClient()
peer_manager = PeerManager(blockchain)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    print("=" * 50)
    print("  Blockchain Node starting...")
    print(f"  Address : {wallet.address}")
    print(f"  Height  : {len(blockchain.chain)}")
    print("=" * 50)

    # Determine public URL
    public_url = PUBLIC_URL
    if not public_url:
        public_url = f"http://127.0.0.1:{HTTP_PORT}"

    # Register with discovery and get peers
    peers = await discovery.register(public_url)
    peer_manager.update_peers(peers)

    # Try to sync with existing peers
    if peers:
        await peer_manager.sync_with_peers()

    # Background heartbeat + peer refresh
    async def heartbeat_loop():
        while True:
            await asyncio.sleep(60)
            try:
                peers = await discovery.register(public_url)
                peer_manager.update_peers(peers)
            except Exception as e:
                print(f"[Heartbeat] Error: {e}")

    heartbeat_task = asyncio.create_task(heartbeat_loop())

    yield

    # Shutdown
    heartbeat_task.cancel()
    print("[Node] Shutting down...")


app = FastAPI(title="Blockchain Node", version="0.2.0", lifespan=lifespan)

# Mount static & templates (for future wallet/explorer UI)
static_dir = Path(__file__).parent.parent / "static"
templates_dir = Path(__file__).parent.parent / "templates"
static_dir.mkdir(exist_ok=True)
templates_dir.mkdir(exist_ok=True)

app.mount("/static", StaticFiles(directory=static_dir), name="static")
templates = Jinja2Templates(directory=templates_dir)

# Init routes with our instances
init_routes(blockchain, wallet, peer_manager, discovery)
app.include_router(router)


def start():
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=HTTP_PORT,
        reload=False,
        log_level="info",
    )


if __name__ == "__main__":
    start()
