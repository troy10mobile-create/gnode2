from __future__ import annotations
import json
import hashlib
from pathlib import Path
from typing import List, Optional, Dict, Set
from datetime import datetime, timezone

from app.blockchain.models import Block, Transaction
from app.config import (
    DATA_DIR, DIFFICULTY, INITIAL_BLOCK_REWARD,
    REWARD_REDUCTION_INTERVAL, REWARD_REDUCTION_FACTOR,
    GENESIS_TIMESTAMP, GENESIS_PREV_HASH, PRUNE_INTERVAL
)


class Blockchain:
    def __init__(self, data_dir: Path = DATA_DIR):
        self.data_dir = data_dir
        self.chain_file = data_dir / "blockchain.json"
        self.chain: List[Block] = []
        self.pending_transactions: List[Transaction] = []
        self.balances: Dict[str, float] = {}
        self.load()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------
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

    # ------------------------------------------------------------------
    # Properties / helpers
    # ------------------------------------------------------------------
    @property
    def last_block(self) -> Block:
        return self.chain[-1]

    @property
    def height(self) -> int:
        return self.last_block.index

    def get_balance(self, address: str) -> float:
        return self.balances.get(address, 0.0)

    def current_block_reward(self, block_index: int = None) -> float:
        """Calculate the block reward for a given height using 10% reduction every 1M blocks."""
        if block_index is None:
            block_index = self.height + 1
        era = block_index // REWARD_REDUCTION_INTERVAL
        reward = INITIAL_BLOCK_REWARD * (REWARD_REDUCTION_FACTOR ** era)
        # Prevent floating point dust
        return round(reward, 8)

    def is_pruning_height(self, height: int) -> bool:
        return height > 0 and height % PRUNE_INTERVAL == 0

    # ------------------------------------------------------------------
    # Balance calculation (respects pruning snapshots)
    # ------------------------------------------------------------------
    def recalculate_balances(self):
        """
        Rebuild balances.
        Strategy:
        1. Find the latest PRUNE transactions (from the most recent pruning block).
        2. Use those as the starting balances.
        3. Apply only transactions that appear AFTER that pruning block.
        If no pruning block exists yet, replay the entire chain from genesis.
        """
        self.balances = {}

        # Find the latest pruning block (highest index that contains PRUNE txs)
        latest_prune_idx = None
        for i in range(len(self.chain) - 1, -1, -1):
            block = self.chain[i]
            if any(tx.sender == "PRUNE" for tx in block.transactions):
                latest_prune_idx = i
                break

        if latest_prune_idx is not None:
            # Start from the prune snapshot
            prune_block = self.chain[latest_prune_idx]
            for tx in prune_block.transactions:
                if tx.sender == "PRUNE":
                    self.balances[tx.recipient] = self.balances.get(tx.recipient, 0.0) + tx.amount
            # Now apply everything after the prune block
            start = latest_prune_idx + 1
        else:
            start = 0

        for block in self.chain[start:]:
            for tx in block.transactions:
                if tx.sender == "PRUNE":
                    # Already handled above (or shouldn't appear after a prune)
                    continue
                if tx.sender not in ("COINBASE", "PRUNE"):
                    self.balances[tx.sender] = self.balances.get(tx.sender, 0.0) - tx.amount
                self.balances[tx.recipient] = self.balances.get(tx.recipient, 0.0) + tx.amount

        # Clean zero / dust balances
        self.balances = {k: v for k, v in self.balances.items() if abs(v) > 1e-12}

    # ------------------------------------------------------------------
    # Transactions
    # ------------------------------------------------------------------
    def add_transaction(self, tx: Transaction) -> bool:
        if not tx.txid:
            tx.compute_txid()

        if tx.sender not in ("COINBASE", "PRUNE"):
            if self.get_balance(tx.sender) < tx.amount:
                return False
            if tx.amount <= 0:
                return False

        if any(t.txid == tx.txid for t in self.pending_transactions):
            return False

        self.pending_transactions.append(tx)
        return True

    # ------------------------------------------------------------------
    # Mining + Pruning
    # ------------------------------------------------------------------
    def _build_prune_transactions(self) -> List[Transaction]:
        """Create one PRUNE self-snapshot tx for every address that currently holds a balance."""
        prune_txs = []
        # We must use the balances as they stand right before this block
        for address, balance in list(self.balances.items()):
            if balance <= 0:
                continue
            tx = Transaction(
                sender="PRUNE",
                recipient=address,
                amount=round(balance, 8),
            )
            tx.compute_txid()
            prune_txs.append(tx)
        return prune_txs

    def mine_block(self, miner_address: str) -> Optional[Block]:
        next_index = self.height + 1
        reward = self.current_block_reward(next_index)

        # Coinbase
        coinbase = Transaction(
            sender="COINBASE",
            recipient=miner_address,
            amount=reward,
        )
        coinbase.compute_txid()

        transactions = [coinbase] + self.pending_transactions.copy()

        # If this is a pruning height, inject PRUNE transactions
        if self.is_pruning_height(next_index):
            prune_txs = self._build_prune_transactions()
            transactions.extend(prune_txs)
            print(f"[Blockchain] Pruning block #{next_index} — snapshotting {len(prune_txs)} addresses")

        new_block = Block(
            index=next_index,
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

        # If it was a pruning block → aggressively delete history
        if self.is_pruning_height(next_index):
            self._perform_prune(new_block)

        self.recalculate_balances()
        self.save()

        print(f"[Blockchain] Mined block #{new_block.index} → {new_block.hash[:16]}... "
              f"(nonce={new_block.nonce}, reward={reward})")
        return new_block

    def _perform_prune(self, prune_block: Block):
        """
        Mandatory history wipe.
        Keep only: Genesis + the new pruning block (+ any blocks that somehow came after, but normally none).
        """
        genesis = self.chain[0]
        # Everything between genesis and the prune block is discarded
        self.chain = [genesis, prune_block]
        print(f"[Blockchain] PRUNE complete. Chain compacted to Genesis + block #{prune_block.index}. "
              f"History before it has been permanently deleted.")

    # ------------------------------------------------------------------
    # Validation & Sync
    # ------------------------------------------------------------------
    def is_valid_chain(self, chain: List[Block] = None) -> bool:
        chain = chain or self.chain
        if not chain:
            return False

        genesis = chain[0]
        if genesis.index != 0 or genesis.previous_hash != GENESIS_PREV_HASH:
            return False

        for i in range(1, len(chain)):
            current = chain[i]
            previous = chain[i - 1]

            # After a prune the previous_hash of the prune block still points to
            # whatever was before it at mining time. We only enforce the link
            # for non-prune-gap situations. For simplicity we still check the
            # immediate previous block that is present in the compacted chain.
            if current.previous_hash != previous.hash and previous.index != 0:
                # Allow the special case where previous is genesis and current is a prune block
                if not (previous.index == 0 and any(tx.sender == "PRUNE" for tx in current.transactions)):
                    return False

            recalculated = current.compute_hash()
            if current.hash != recalculated:
                return False

            if not current.hash.startswith("0" * current.difficulty):
                return False

        return True

    def apply_block(self, block: Block) -> bool:
        """Apply a block received from the network (including possible prune)."""
        if block.index != self.height + 1:
            return False
        if block.previous_hash != self.last_block.hash and self.height != 0:
            # Allow prune blocks that originally pointed to a now-deleted block
            if not (self.height == 0 and any(tx.sender == "PRUNE" for tx in block.transactions)):
                return False
        if not block.hash.startswith("0" * block.difficulty):
            return False

        self.chain.append(block)
        self.pending_transactions = []

        if self.is_pruning_height(block.index):
            self._perform_prune(block)

        self.recalculate_balances()
        self.save()
        return True

    def replace_chain(self, new_chain: List[Block]) -> bool:
        if len(new_chain) <= len(self.chain):
            return False
        if not self.is_valid_chain(new_chain):
            return False

        self.chain = new_chain
        self.recalculate_balances()
        self.save()
        print(f"[Blockchain] Chain replaced. New height: {self.height}")
        return True

    def get_chain_dict(self) -> List[dict]:
        return [b.to_dict() for b in self.chain]
