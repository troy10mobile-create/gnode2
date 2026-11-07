from __future__ import annotations
import httpx
import uuid
from typing import List, Dict, Optional
from app.config import DISCOVERY_URL, NETWORK_SECRET, NETWORK_ID, APP_VERSION, PUBLIC_URL


class DiscoveryClient:
    def __init__(self):
        self.node_id = str(uuid.uuid4())
        self.discovery_url = DISCOVERY_URL
        self.headers = {}
        if NETWORK_SECRET and NETWORK_SECRET != "dev-secret-change-me":
            self.headers["X-Network-Secret"] = NETWORK_SECRET

    async def register(self, public_url: str) -> List[Dict]:
        """Register this node and receive current peers."""
        if not self.discovery_url:
            print("[Discovery] No DISCOVERY_URL configured — running in offline/local mode")
            return []

        payload = {
            "node_id": self.node_id,
            "public_url": public_url,
            "network_id": NETWORK_ID,
            "version": APP_VERSION,
        }

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    f"{self.discovery_url}/register",
                    json=payload,
                    headers=self.headers,
                )
                resp.raise_for_status()
                data = resp.json()
                peers = data.get("peers", [])
                print(f"[Discovery] Registered. Known peers: {len(peers)}")
                return peers
        except Exception as e:
            print(f"[Discovery] Failed to register: {e}")
            return []

    async def get_peers(self) -> List[Dict]:
        if not self.discovery_url:
            return []
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    f"{self.discovery_url}/peers",
                    params={"network_id": NETWORK_ID},
                    headers=self.headers,
                )
                resp.raise_for_status()
                return resp.json().get("peers", [])
        except Exception as e:
            print(f"[Discovery] Failed to fetch peers: {e}")
            return []
