from __future__ import annotations
import json
import hashlib
from pathlib import Path
from typing import List, Optional, Dict
from datetime import datetime, timezone

from app.blockchain.models import Block, Transaction
from app.config import (
    DATA_DIR, DIFFICULTY, BLOCK_REWARD, GENESIS_TIMESTAMP,
    GENESIS_PREV_HASH, COINBASE_MATURITY
)


class Blockchain:
    def __init__(self, data_dir: Path = DATA_DIR):
        self.data_dir = data_dir
        self.chain_file = data_dir / "blockchain.json"
        self.chain: List[Block] = []
        self.pending_transactions: List[Transaction] = []
        self.balances: Dict[str, float] = {}
        self.load()

    def load(self):
        if self.chain_file.exists():
            with open(self.chain_file, "r") as f:
                data = json.load(f)
            self.chain = [Block(**b) for b in data]
            self.recalculate_balances()
        else:
            self.create_genesis_block()

    def save(self):
        with open(self.chain_file, "w") as f:
            json.dump([b.to_dict() for b in self.chain], f, indent=2)

    def create_genesis_block(self):
        genesis = Block(
            index=0,
            timestamp=GENESIS_TIMESTAMP,
            transactions=[],
            previous_hash=GENESIS_PREV_HASH,
            nonce=0,
            difficulty=DIFFICULTY,
        )
        genesis.compute_hash()
        self.chain = [genesis]
        self.save()
        print(f"[Blockchain] Genesis block created → {genesis.hash[:16]}...")

    @property
    def last_block(self) -> Block:
        return self.chain[-1]

    def get_balance(self, address: str) -> float:
        return self.balances.get(address, 0.0)

    def recalculate_balances(self):
        """Rebuild balances from the chain (simple UTXO-less model for clarity)."""
        self.balances = {}
        for block in self.chain:
            for tx in block.transactions:
                if tx.sender != "COINBASE":
                    self.balances[tx.sender] = self.balances.get(tx.sender, 0.0) - tx.amount
                self.balances[tx.recipient] = self.balances.get(tx.recipient, 0.0) + tx.amount

    def add_transaction(self, tx: Transaction) -> bool:
        """Add a transaction to the mempool after basic validation."""
        if not tx.txid:
            tx.compute_txid()

        # Basic checks
        if tx.sender != "COINBASE":
            if self.get_balance(tx.sender) < tx.amount:
                return False
            if tx.amount <= 0:
                return False

        # Avoid duplicates
        if any(t.txid == tx.txid for t in self.pending_transactions):
            return False

        self.pending_transactions.append(tx)
        return True

    def mine_block(self, miner_address: str) -> Optional[Block]:
        """Mine a new block with current pending transactions + coinbase."""
        if not self.pending_transactions and not miner_address:
            return None

        # Coinbase transaction
        coinbase = Transaction(
            sender="COINBASE",
            recipient=miner_address,
            amount=BLOCK_REWARD,
        )
        coinbase.compute_txid()

        transactions = [coinbase] + self.pending_transactions.copy()

        new_block = Block(
            index=len(self.chain),
            timestamp=datetime.now(timezone.utc).timestamp(),
            transactions=transactions,
            previous_hash=self.last_block.hash,
            difficulty=DIFFICULTY,
        )

        # Proof of Work
        target = "0" * DIFFICULTY
        while True:
            new_block.compute_hash()
            if new_block.hash.startswith(target):
                break
            new_block.nonce += 1

        # Accept the block
        self.chain.append(new_block)
        self.pending_transactions = []
        self.recalculate_balances()
        self.save()

        print(f"[Blockchain] Mined block #{new_block.index} → {new_block.hash[:16]}... (nonce={new_block.nonce})")
        return new_block

    def is_valid_chain(self, chain: List[Block] = None) -> bool:
        chain = chain or self.chain
        if not chain:
            return False

        # Genesis check
        genesis = chain[0]
        if genesis.index != 0 or genesis.previous_hash != GENESIS_PREV_HASH:
            return False

        for i in range(1, len(chain)):
            current = chain[i]
            previous = chain[i - 1]

            # Hash integrity
            recalculated = current.compute_hash()
            if current.hash != recalculated:
                return False

            # Link integrity
            if current.previous_hash != previous.hash:
                return False

            # PoW
            if not current.hash.startswith("0" * current.difficulty):
                return False

        return True

    def replace_chain(self, new_chain: List[Block]) -> bool:
        """Replace local chain if the new one is longer and valid (simple longest-chain rule)."""
        if len(new_chain) <= len(self.chain):
            return False
        if not self.is_valid_chain(new_chain):
            return False

        self.chain = new_chain
        self.recalculate_balances()
        self.save()
        print(f"[Blockchain] Chain replaced. New height: {len(self.chain)}")
        return True

    def get_chain_dict(self) -> List[dict]:
        return [b.to_dict() for b in self.chain]
