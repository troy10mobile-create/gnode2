from __future__ import annotations
import json
import hashlib
from pathlib import Path
from typing import List, Optional, Dict, Set
from datetime import datetime, timezone

from app.blockchain.models import Block, Transaction
from app.config import (
    DATA_DIR, INITIAL_DIFFICULTY, INITIAL_BLOCK_REWARD,
    REWARD_REDUCTION_INTERVAL, REWARD_REDUCTION_FACTOR,
    BLOCK_TIME_TARGET, DIFFICULTY_ADJUST_INTERVAL,
    MIN_DIFFICULTY,
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
            # Re-apply pruning compaction on every load so old history stays gone
            self._compact_to_latest_prune()
            self.recalculate_balances()
        else:
            self.create_genesis_block()

    def _compact_to_latest_prune(self):
        """
        Keep only Genesis + the latest pruning block + everything after it.
        Called on load and after receiving blocks so history cannot reappear.
        """
        if len(self.chain) <= 1:
            return

        latest_prune_pos = None
        for i in range(len(self.chain) - 1, 0, -1):
            if any(tx.sender == "PRUNE" for tx in self.chain[i].transactions):
                latest_prune_pos = i
                break

        if latest_prune_pos is None:
            return

        genesis = self.chain[0]
        kept = [genesis] + self.chain[latest_prune_pos:]
        if len(kept) < len(self.chain):
            removed = len(self.chain) - len(kept)
            self.chain = kept
            print(f"[Blockchain] Compacted chain on load/sync — removed {removed} pre-prune blocks. "
                  f"Now length={len(self.chain)}")
            self.save()

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
            difficulty=INITIAL_DIFFICULTY,
        )
        genesis.compute_hash()
        self.chain = [genesis]
        self.save()
        print(f"[Blockchain] Genesis block created → {genesis.hash[:16]}...")

    def get_current_difficulty(self) -> int:
        """Return the difficulty that should be used for the next block."""
        if len(self.chain) < 2:
            return INITIAL_DIFFICULTY
        return self.last_block.difficulty

    def calculate_next_difficulty(self) -> int:
        """
        Step-based difficulty adjustment.
        Every DIFFICULTY_ADJUST_INTERVAL blocks, compare actual time vs target.
        - Too fast  → difficulty + 1
        - Too slow  → difficulty - 1
        - About right → no change
        No artificial upper cap. Difficulty can rise as high as the network requires.
        """
        height = self.height
        if height < DIFFICULTY_ADJUST_INTERVAL:
            return INITIAL_DIFFICULTY

        # Only adjust on interval boundaries
        if (height + 1) % DIFFICULTY_ADJUST_INTERVAL != 0:
            return self.last_block.difficulty

        lookback = min(DIFFICULTY_ADJUST_INTERVAL, len(self.chain) - 1)
        if lookback < 2:
            return self.last_block.difficulty

        recent = self.chain[-lookback:]
        time_taken = recent[-1].timestamp - recent[0].timestamp
        expected = BLOCK_TIME_TARGET * (lookback - 1)

        old_diff = self.last_block.difficulty

        # Tolerance band: ±20% is considered "about right"
        if time_taken <= 0 or time_taken < expected * 0.8:
            # Blocks too fast → increase difficulty by 1
            new_diff = old_diff + 1
            reason = "too fast"
        elif time_taken > expected * 1.2:
            # Blocks too slow → decrease difficulty by 1
            new_diff = max(MIN_DIFFICULTY, old_diff - 1)
            reason = "too slow"
        else:
            new_diff = old_diff
            reason = "on target"

        if new_diff != old_diff:
            print(f"[Difficulty] {reason}: {old_diff} → {new_diff} "
                  f"(time_taken={time_taken:.1f}s, expected={expected:.1f}s)")
        return new_diff

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
    def _expected_prune_map(self) -> Dict[str, float]:
        """
        Return the exact map of {address: balance} that a valid PRUNE block
        must contain. This is computed from the current (pre-block) state.
        """
        expected = {}
        for address, balance in self.balances.items():
            if balance > 1e-12:
                expected[address] = round(balance, 8)
        return expected

    def _build_prune_transactions(self) -> List[Transaction]:
        """Create one PRUNE self-snapshot tx for every address that currently holds a balance."""
        prune_txs = []
        for address, balance in self._expected_prune_map().items():
            tx = Transaction(
                sender="PRUNE",
                recipient=address,
                amount=balance,
            )
            tx.compute_txid()
            prune_txs.append(tx)
        return prune_txs

    def validate_prune_transactions(self, block: Block) -> bool:
        """
        Strict validation: a pruning block must contain exactly one PRUNE
        transaction for every address that has a positive balance, with the
        exact amount. No extras, no missing, no wrong amounts.
        """
        if not self.is_pruning_height(block.index):
            # Non-prune blocks must not contain any PRUNE txs
            if any(tx.sender == "PRUNE" for tx in block.transactions):
                print(f"[Validate] Block #{block.index} contains illegal PRUNE txs")
                return False
            return True

        expected = self._expected_prune_map()
        found: Dict[str, float] = {}

        for tx in block.transactions:
            if tx.sender != "PRUNE":
                continue
            if tx.recipient in found:
                print(f"[Validate] Duplicate PRUNE for {tx.recipient}")
                return False
            found[tx.recipient] = round(tx.amount, 8)

        if set(found.keys()) != set(expected.keys()):
            missing = set(expected.keys()) - set(found.keys())
            extra = set(found.keys()) - set(expected.keys())
            print(f"[Validate] PRUNE address mismatch. Missing={missing}, Extra={extra}")
            return False

        for addr, amount in expected.items():
            if abs(found[addr] - amount) > 1e-8:
                print(f"[Validate] PRUNE amount mismatch for {addr}: "
                      f"expected {amount}, got {found[addr]}")
                return False

        return True

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

        difficulty = self.calculate_next_difficulty()

        new_block = Block(
            index=next_index,
            timestamp=datetime.now(timezone.utc).timestamp(),
            transactions=transactions,
            previous_hash=self.last_block.hash,
            difficulty=difficulty,
        )

        # Proof of Work
        target = "0" * difficulty
        while True:
            new_block.compute_hash()
            if new_block.hash.startswith(target):
                break
            new_block.nonce += 1

        # Defensive: never accept our own block if PRUNE data is wrong
        if not self.validate_prune_transactions(new_block):
            print(f"[Blockchain] CRITICAL: mined block #{next_index} failed PRUNE validation — discarding")
            return None

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
        Keep only: Genesis + the new pruning block + any blocks after it.
        """
        genesis = self.chain[0]
        # Keep genesis, the prune block, and anything that came after it
        after = [b for b in self.chain if b.index > prune_block.index]
        self.chain = [genesis, prune_block] + after
        print(f"[Blockchain] PRUNE complete. Chain compacted to Genesis + block #{prune_block.index} "
              f"+ {len(after)} newer blocks. Pre-prune history permanently deleted.")

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

        # Strict PRUNE validation — every node independently checks the snapshot
        if not self.validate_prune_transactions(block):
            print(f"[Node] Rejected block #{block.index} — invalid PRUNE transactions")
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
        # Always re-compact after accepting a foreign chain
        self._compact_to_latest_prune()
        self.recalculate_balances()
        self.save()
        print(f"[Blockchain] Chain replaced. New height: {self.height}, length: {len(self.chain)}")
        return True

    def get_chain_dict(self) -> List[dict]:
        return [b.to_dict() for b in self.chain]
