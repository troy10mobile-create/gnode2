from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from typing import List, Optional
import asyncio

from app.blockchain.models import Block, Transaction
from app.blockchain.chain import Blockchain
from app.wallet.wallet import Wallet
from app.network.p2p import PeerManager
from app.network.discovery import DiscoveryClient
from app.config import PRUNE_INTERVAL

router = APIRouter()

# These will be injected from main
blockchain: Blockchain = None
wallet: Wallet = None
peer_manager: PeerManager = None
discovery: DiscoveryClient = None

# Continuous mining state
_mining_task: Optional[asyncio.Task] = None
_mining_active: bool = False


def init_routes(bc: Blockchain, w: Wallet, pm: PeerManager, disc: DiscoveryClient):
    global blockchain, wallet, peer_manager, discovery
    blockchain = bc
    wallet = w
    peer_manager = pm
    discovery = disc


class SendTxRequest(BaseModel):
    recipient: str
    amount: float


@router.get("/api/status")
async def get_status():
    next_height = blockchain.height + 1 if blockchain else 1
    current_diff = blockchain.get_current_difficulty() if blockchain else 4
    next_diff = blockchain.calculate_next_difficulty() if blockchain else 4
    return {
        "service": "Blockchain Node",
        "version": "0.3.0",
        "address": wallet.address if wallet else None,
        "balance": blockchain.get_balance(wallet.address) if wallet and blockchain else 0,
        "height": blockchain.height if blockchain else 0,
        "peers": len(peer_manager.peers) if peer_manager else 0,
        "pending_transactions": len(blockchain.pending_transactions) if blockchain else 0,
        "current_reward": blockchain.current_block_reward(next_height) if blockchain else 50,
        "difficulty": current_diff,
        "next_difficulty": next_diff,
        "next_prune_in": PRUNE_INTERVAL - (blockchain.height % PRUNE_INTERVAL) if blockchain else PRUNE_INTERVAL,
        "is_pruning_height_next": blockchain.is_pruning_height(next_height) if blockchain else False,
        "mining_active": _mining_active,
        "chain_length": len(blockchain.chain) if blockchain else 0,
    }


@router.get("/api/mempool")
async def get_mempool():
    return {
        "count": len(blockchain.pending_transactions),
        "transactions": [tx.to_dict() for tx in blockchain.pending_transactions],
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

        if blockchain.apply_block(block):
            print(f"[Node] Accepted block #{block.index} from peer")
            return {"status": "accepted"}
        else:
            # Maybe we are behind — try a sync
            await peer_manager.sync_with_peers()
            return {"status": "ignored_or_synced"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/api/mine")
async def mine_once():
    """Mine a single block (kept for compatibility)."""
    if not blockchain:
        raise HTTPException(status_code=500, detail="Blockchain not ready")
    block = blockchain.mine_block(wallet.address)
    if block:
        await peer_manager.broadcast_block(block)
        return {"status": "mined", "block": block.to_dict()}
    raise HTTPException(status_code=400, detail="Nothing to mine")


async def _continuous_mine_loop():
    global _mining_active
    print("[Mining] Continuous mining started")
    while _mining_active:
        try:
            block = blockchain.mine_block(wallet.address)
            if block:
                await peer_manager.broadcast_block(block)
            # Small yield so the event loop stays responsive
            await asyncio.sleep(0.05)
        except asyncio.CancelledError:
            break
        except Exception as e:
            print(f"[Mining] Error: {e}")
            await asyncio.sleep(1)
    print("[Mining] Continuous mining stopped")


@router.post("/api/mining/start")
async def start_mining():
    global _mining_task, _mining_active
    if _mining_active:
        return {"status": "already_mining"}
    _mining_active = True
    _mining_task = asyncio.create_task(_continuous_mine_loop())
    return {"status": "started"}


@router.post("/api/mining/stop")
async def stop_mining():
    global _mining_task, _mining_active
    if not _mining_active:
        return {"status": "not_mining"}
    _mining_active = False
    if _mining_task:
        _mining_task.cancel()
        try:
            await _mining_task
        except asyncio.CancelledError:
            pass
        _mining_task = None
    return {"status": "stopped"}


@router.get("/api/peers")
async def get_peers():
    return {"peers": peer_manager.peers}
