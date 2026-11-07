from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from typing import List, Optional
from pathlib import Path

from app.blockchain.models import Block, Transaction
from app.blockchain.chain import Blockchain
from app.wallet.wallet import Wallet
from app.network.p2p import PeerManager
from app.network.discovery import DiscoveryClient

router = APIRouter()

# These will be injected from main
blockchain: Blockchain = None
wallet: Wallet = None
peer_manager: PeerManager = None
discovery: DiscoveryClient = None

templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent.parent / "templates"))


def init_routes(bc: Blockchain, w: Wallet, pm: PeerManager, disc: DiscoveryClient):
    global blockchain, wallet, peer_manager, discovery
    blockchain = bc
    wallet = w
    peer_manager = pm
    discovery = disc


class SendTxRequest(BaseModel):
    recipient: str
    amount: float


class BlockReceive(BaseModel):
    index: int
    timestamp: float
    transactions: list
    previous_hash: str
    nonce: int
    difficulty: int
    hash: str
    merkle_root: str = ""


@router.get("/", response_class=HTMLResponse)
async def root(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@router.get("/api/status")
async def status():
    return {
        "service": "Blockchain Node",
        "version": "0.2.0",
        "address": wallet.address if wallet else None,
        "balance": blockchain.get_balance(wallet.address) if wallet and blockchain else 0,
        "height": len(blockchain.chain) if blockchain else 0,
        "peers": len(peer_manager.peers) if peer_manager else 0,
        "pending": len(blockchain.pending_transactions) if blockchain else 0,
    }


@router.get("/api/chain")
async def get_chain():
    return blockchain.get_chain_dict()


@router.get("/api/balance/{address}")
async def get_balance(address: str):
    return {"address": address, "balance": blockchain.get_balance(address)}


@router.get("/api/wallet")
async def get_wallet():
    return {
        "address": wallet.address,
        "balance": blockchain.get_balance(wallet.address),
    }


@router.post("/api/transaction")
async def receive_transaction(tx_data: dict):
    try:
        tx = Transaction(**tx_data)
        if not Wallet.verify_transaction(tx):
            raise HTTPException(status_code=400, detail="Invalid signature")
        if blockchain.add_transaction(tx):
            # Optionally re-broadcast (simple version skips to avoid loops)
            return {"status": "accepted", "txid": tx.txid}
        raise HTTPException(status_code=400, detail="Transaction rejected")
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/api/send")
async def send_transaction(req: SendTxRequest):
    if req.amount <= 0:
        raise HTTPException(status_code=400, detail="Amount must be positive")
    if blockchain.get_balance(wallet.address) < req.amount:
        raise HTTPException(status_code=400, detail="Insufficient balance")

    tx = wallet.create_transaction(req.recipient, req.amount)
    if blockchain.add_transaction(tx):
        await peer_manager.broadcast_transaction(tx)
        return {"status": "broadcasted", "txid": tx.txid, "tx": tx.to_dict()}
    raise HTTPException(status_code=400, detail="Could not add transaction")


@router.post("/api/block")
async def receive_block(block_data: dict):
    try:
        # Rebuild transactions
        txs = [Transaction(**t) for t in block_data.get("transactions", [])]
        block = Block(
            index=block_data["index"],
            timestamp=block_data["timestamp"],
            transactions=txs,
            previous_hash=block_data["previous_hash"],
            nonce=block_data["nonce"],
            difficulty=block_data["difficulty"],
            hash=block_data["hash"],
            merkle_root=block_data.get("merkle_root", ""),
        )

        # Basic validation
        if block.previous_hash != blockchain.last_block.hash:
            # Possible fork or we are behind — try sync
            await peer_manager.sync_with_peers()
            return {"status": "ignored_or_synced"}

        if not block.hash.startswith("0" * block.difficulty):
            raise HTTPException(status_code=400, detail="Invalid proof of work")

        # Accept
        blockchain.chain.append(block)
        blockchain.pending_transactions = []  # simple: clear mempool
        blockchain.recalculate_balances()
        blockchain.save()
        print(f"[Node] Accepted block #{block.index} from peer")
        return {"status": "accepted"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/api/mine")
async def mine():
    if not blockchain:
        raise HTTPException(status_code=500, detail="Blockchain not ready")
    block = blockchain.mine_block(wallet.address)
    if block:
        await peer_manager.broadcast_block(block)
        return {"status": "mined", "block": block.to_dict()}
    raise HTTPException(status_code=400, detail="Nothing to mine")


@router.get("/api/peers")
async def get_peers():
    return {"peers": peer_manager.peers}
