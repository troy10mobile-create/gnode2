from __future__ import annotations
import hashlib
import json
from pathlib import Path
from typing import Optional, Tuple
import ecdsa
import base58

from app.config import DATA_DIR
from app.blockchain.models import Transaction


class Wallet:
    def __init__(self, data_dir: Path = DATA_DIR):
        self.wallet_file = data_dir / "wallet.json"
        self.private_key: Optional[ecdsa.SigningKey] = None
        self.public_key: Optional[ecdsa.VerifyingKey] = None
        self.address: Optional[str] = None
        self.load_or_create()

    def load_or_create(self):
        if self.wallet_file.exists():
            with open(self.wallet_file, "r") as f:
                data = json.load(f)
            sk_hex = data["private_key"]
            self.private_key = ecdsa.SigningKey.from_string(bytes.fromhex(sk_hex), curve=ecdsa.SECP256k1)
            self.public_key = self.private_key.get_verifying_key()
            self.address = data["address"]
            print(f"[Wallet] Loaded address: {self.address}")
        else:
            self.generate_new()

    def generate_new(self):
        self.private_key = ecdsa.SigningKey.generate(curve=ecdsa.SECP256k1)
        self.public_key = self.private_key.get_verifying_key()
        self.address = self.pubkey_to_address(self.public_key)
        self.save()
        print(f"[Wallet] New wallet created → {self.address}")

    def save(self):
        data = {
            "private_key": self.private_key.to_string().hex(),
            "address": self.address,
        }
        with open(self.wallet_file, "w") as f:
            json.dump(data, f, indent=2)

    @staticmethod
    def pubkey_to_address(public_key: ecdsa.VerifyingKey) -> str:
        """Simple address derivation (not full Bitcoin style, but clean)."""
        pub_bytes = public_key.to_string()
        sha = hashlib.sha256(pub_bytes).digest()
        ripe = hashlib.new("ripemd160", sha).digest()
        # Version byte + payload + checksum (simplified)
        versioned = b"\x00" + ripe
        checksum = hashlib.sha256(hashlib.sha256(versioned).digest()).digest()[:4]
        return base58.b58encode(versioned + checksum).decode()

    def sign(self, message: str) -> str:
        signature = self.private_key.sign(message.encode())
        return signature.hex()

    def create_transaction(self, recipient: str, amount: float) -> Transaction:
        tx = Transaction(
            sender=self.address,
            recipient=recipient,
            amount=amount,
            public_key=self.public_key.to_string().hex(),
        )
        tx.compute_txid()
        # Sign the txid
        tx.signature = self.sign(tx.txid)
        return tx

    @staticmethod
    def verify_transaction(tx: Transaction) -> bool:
        if tx.sender == "COINBASE":
            return True
        if not tx.signature or not tx.public_key:
            return False
        try:
            vk = ecdsa.VerifyingKey.from_string(bytes.fromhex(tx.public_key), curve=ecdsa.SECP256k1)
            return vk.verify(bytes.fromhex(tx.signature), tx.txid.encode())
        except Exception:
            return False
