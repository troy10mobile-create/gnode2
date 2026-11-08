import asyncio
import os
import uvicorn
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pathlib import Path

from app.config import HTTP_PORT, PUBLIC_URL, MINING_ENABLED, DATA_DIR
from app.blockchain.chain import Blockchain
from app.wallet.wallet import Wallet
from app.network.discovery import DiscoveryClient
from app.network.p2p import PeerManager, normalize_public_url
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

    # Determine this node's externally reachable URL.
    # Render supplies RENDER_EXTERNAL_URL automatically for web services.
    # PUBLIC_URL remains an explicit override for other hosting providers.
    configured_url = PUBLIC_URL or os.getenv("RENDER_EXTERNAL_URL", "")
    public_url = normalize_public_url(configured_url)
    peer_manager.set_self_url(public_url)

    if public_url:
        print(f"  Public URL: {public_url}")
        peers = await discovery.register(public_url)
        peer_manager.update_peers(peers)

        # Try to sync with existing peers.
        if peers:
            await peer_manager.sync_with_peers()
    else:
        print("[Discovery] No valid public URL detected; not registering this node.")
        print("[Discovery] On Render, RENDER_EXTERNAL_URL should be supplied automatically.")

    # Background heartbeat + peer refresh
    async def heartbeat_loop():
        while True:
            await asyncio.sleep(60)
            try:
                if not public_url:
                    continue
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

# Mount static assets and browser interface
static_dir = Path(__file__).parent.parent / "static"
templates_dir = Path(__file__).parent.parent / "templates"
static_dir.mkdir(exist_ok=True)
templates_dir.mkdir(exist_ok=True)

app.mount("/static", StaticFiles(directory=static_dir), name="static")
templates = Jinja2Templates(directory=templates_dir)

@app.get("/", include_in_schema=False)
async def dashboard(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"request": request},
    )

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
