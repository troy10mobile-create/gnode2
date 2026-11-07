from __future__ import annotations
import httpx
from typing import List, Dict, Optional
from app.blockchain.models import Block, Transaction
from app.blockchain.chain import Blockchain


class PeerManager:
    def __init__(self, blockchain: Blockchain):
        self.blockchain = blockchain
        self.peers: Dict[str, str] = {}  # node_id → public_url

    def update_peers(self, peer_list: List[Dict]):
        for p in peer_list:
            self.peers[p["node_id"]] = p["public_url"]

    async def broadcast_block(self, block: Block):
        """Send a newly mined block to all known peers."""
        payload = block.to_dict()
        for node_id, url in list(self.peers.items()):
            try:
                async with httpx.AsyncClient(timeout=8.0) as client:
                    await client.post(f"{url}/api/block", json=payload)
            except Exception as e:
                print(f"[P2P] Failed to send block to {node_id}: {e}")

    async def broadcast_transaction(self, tx: Transaction):
        payload = tx.to_dict()
        for node_id, url in list(self.peers.items()):
            try:
                async with httpx.AsyncClient(timeout=8.0) as client:
                    await client.post(f"{url}/api/transaction", json=payload)
            except Exception as e:
                print(f"[P2P] Failed to send tx to {node_id}: {e}")

    async def request_chain(self, peer_url: str) -> Optional[List[dict]]:
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(f"{peer_url}/api/chain")
                resp.raise_for_status()
                return resp.json()
        except Exception as e:
            print(f"[P2P] Failed to fetch chain from {peer_url}: {e}")
            return None

    async def sync_with_peers(self):
        """Simple longest-chain sync."""
        for node_id, url in list(self.peers.items()):
            remote_chain = await self.request_chain(url)
            if not remote_chain:
                continue
            try:
                from app.blockchain.models import Block
                blocks = [Block(**b) for b in remote_chain]
                if self.blockchain.replace_chain(blocks):
                    print(f"[P2P] Synced longer chain from {node_id}")
                    return True
            except Exception as e:
                print(f"[P2P] Invalid chain from {node_id}: {e}")
        return False
