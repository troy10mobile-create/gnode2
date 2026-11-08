# Blockchain Node (Core v0.2)

Full node for the educational Bitcoin-like network.

This is the **core** that every participant runs. It maintains its own copy of the blockchain, has a wallet, can mine, talks to other peers, and registers itself with the Discovery Service.

## Features (current)

- Genesis block + persistent blockchain
- ECDSA wallet (secp256k1) with address generation
- Transaction creation + signature verification
- Proof-of-Work mining
- Longest-chain rule
- Automatic peer discovery via the Discovery Service
- Basic P2P block & transaction propagation
- REST API for chain, wallet, sending, mining
- Built-in browser dashboard with wallet overview, send form, mining control, recent-block explorer, peer count and mempool

## Quick Start

```bash
python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env
# Edit .env:
#   - Set DISCOVERY_URL to your discovery service
#   - Set NETWORK_SECRET (must match discovery)
#   - On Render, PUBLIC_URL is detected automatically from RENDER_EXTERNAL_URL
#   - On other hosts, set PUBLIC_URL to this node's public HTTPS URL

python -m app.main
```

The node will:

- Detect its public URL automatically on Render using `RENDER_EXTERNAL_URL`
- Refuse to register loopback/private peer URLs such as `127.0.0.1`

1. Create or load wallet + blockchain
2. Register with the discovery service
3. Sync with any existing peers
4. Start the HTTP API on port 8332 (default)

## Important Environment Variables

| Variable         | Description                                      |
|------------------|--------------------------------------------------|
| `DISCOVERY_URL`  | URL of the discovery service                     |
| `NETWORK_SECRET` | Shared secret (must match discovery service)     |
| `PUBLIC_URL`     | Optional public URL override; Render auto-detects `RENDER_EXTERNAL_URL` |
| `HTTP_PORT`      | Port for the API (default 8332)                  |
| `DIFFICULTY`     | Leading zeros required (default 4)               |
| `BLOCK_REWARD`   | Coinbase reward (default 50)                     |

## Browser interface

Open the node's base URL (`/`) in a browser. The node serves its own responsive dashboard; no separate frontend hosting or build step is required.

The dashboard reads the node's API and refreshes automatically every 15 seconds. It includes:

- This node wallet address and confirmed balance
- Send transaction form (the existing node wallet signs the transaction)
- Mine-block control
- Recent blocks with height, hash, transaction count and timestamp
- Peer count and network status
- Pending transaction list

The original JSON API remains available. Node status is now at `/api/status`; pending transactions are at `/api/mempool`.

**Security note:** this is an experimental interface, not a production wallet. The existing `/api/send` endpoint asks the server-side node wallet to sign transactions, and the node API currently has no user authentication. Do not expose a node containing valuable keys or funds to an untrusted public network.

## Main API Endpoints

- `GET  /`                  → Browser dashboard
- `GET  /api/status`        → Node info and status
- `GET  /api/mempool`       → Pending transactions
- `GET  /api/chain`         → Full blockchain
- `GET  /api/wallet`        → This node's address + balance
- `GET  /api/balance/{addr}`→ Balance of any address
- `POST /api/send`          → Create + broadcast a transaction
- `POST /api/mine`          → Mine a block
- `GET  /api/peers`         → Currently known peers
- `POST /api/block`         → Receive a block from a peer
- `POST /api/transaction`   → Receive a transaction from a peer

## Project Structure

```
blockchain-node/
├── app/
│   ├── main.py              # Entry point
│   ├── config.py
│   ├── blockchain/
│   │   ├── models.py        # Block & Transaction
│   │   └── chain.py         # Blockchain logic
│   ├── wallet/
│   │   └── wallet.py        # Keys, signing, addresses
│   ├── network/
│   │   ├── discovery.py     # Talks to discovery service
│   │   └── p2p.py           # Peer management + sync
│   └── api/
│       └── routes.py        # FastAPI routes
├── data/                    # blockchain.json + wallet.json (auto-created)
├── static/                  # Future browser UI assets
├── templates/               # Future Jinja templates
├── requirements.txt
└── .env.example
```

## Next Steps (planned)

- Full transaction/block detail pages and address history
- Dynamic difficulty adjustment
- Cumulative chainwork
- Proper fork handling / reorgs
- Coinbase maturity enforcement
- Authenticated node-to-node communication
```

