from __future__ import annotations
import httpx
import ipaddress
from urllib.parse import urlsplit, urlunsplit
from typing import List, Dict, Optional
from app.blockchain.models import Block, Transaction
from app.blockchain.chain import Blockchain


def normalize_public_url(value: str) -> Optional[str]:
    """Return a safe absolute HTTP(S) base URL, rejecting local/private endpoints."""
    if not value or not isinstance(value, str):
        return None
    value = value.strip().rstrip("/")
    try:
        parsed = urlsplit(value)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            return None
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            return None
        host = parsed.hostname.lower().rstrip(".")
        if host == "localhost" or host.endswith((".localhost", ".local", ".internal")):
            return None
        try:
            ip = ipaddress.ip_address(host)
            if not ip.is_global:
                return None
        except ValueError:
            # Public DNS names are accepted; reject obvious single-label hosts.
            if "." not in host:
                return None
        netloc = parsed.netloc
        return urlunsplit((parsed.scheme, netloc, parsed.path.rstrip("/"), "", ""))
    except Exception:
        return None


class PeerManager:
    def __init__(self, blockchain: Blockchain):
        self.blockchain = blockchain
        self.peers: Dict[str, str] = {}  # node_id → public_url
        self.self_url: Optional[str] = None

    def set_self_url(self, public_url: Optional[str]):
        self.self_url = normalize_public_url(public_url) if public_url else None

    def update_peers(self, peer_list: List[Dict]):
        for p in peer_list:
            node_id = p.get("node_id")
            url = normalize_public_url(p.get("public_url", ""))
            if not node_id or not url:
                if p.get("public_url"):
                    print(f"[P2P] Ignoring invalid/non-public peer URL: {p.get('public_url')}")
                continue
            if self.self_url and url == self.self_url:
                continue
            self.peers[node_id] = url

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
