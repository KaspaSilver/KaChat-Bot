# KaChat Bot v2

Small bots you talk to in **KaChat**. Each bot has its own Kaspa wallet, belongs to the one person who
pairs with it, asks a few setup questions in the chat, and then messages you when something happens:

| Bot | Tells you |
|---|---|
| **Mining** | every block reward paid to your mining address (reward, balance, pool hashrate), and optionally when the hashrate drops |
| **Price** | when KAS crosses a price you chose (once per crossing), a daily summary, and big moves within 24 h |
| **Wallet** | when a watched address receives or sends KAS (amount, balance, transaction id) |

Messages are ordinary KaChat 1:1 messages: end-to-end encrypted (ephemeral secp256k1 ECDH, HKDF-SHA256,
ChaCha20-Poly1305) and sent as a self-spend, so a message only costs the network fee (about 0.002 KAS).
Nothing is ever paid to anyone.

One container runs any number of bots. It is normally deployed and driven by the
**Kaspa Quick Start** panel.

---

## With the Kaspa Quick Start panel

1. **Set up a bot.** Click a bot square (Mining, Price or Wallet). The panel creates a wallet for it and
   shows the bot's address and a 6-digit pairing code.
2. **Fund the address.** Send the bot a little KAS (1 KAS is hundreds of messages). The square shows when it
   is funded.
3. **Message it in KaChat** with the pairing code. The first person to send the code becomes its owner; from
   then on it only ever talks to you.
4. **Answer its questions.** One at a time; send `skip` to keep a default. It confirms your settings and starts.

To hand a bot to someone else (or start over), use *Reset owner* in the panel; the bot forgets its owner,
settings and conversation and waits for the pairing code again.

### Commands (send them in the chat, any time)

| Command | |
|---|---|
| `help` | the list of commands |
| `status` | what the bot is doing, and its wallet balance |
| `settings` | its current settings |
| `change` | answer the setup questions again (`skip` keeps the current value) |
| `reset` | forget the settings and start setup over from the defaults (you stay paired) |
| `pause` / `resume` | stop / restart notifications |
| `test` | send a sample notification |

### Setup questions

- **Mining**: the mining address to watch; the smallest reward to report (KAS, 0 = every block); alert on a
  hashrate drop of how many % (or `no`; needs the stratum bridge).
- **Price** (USD): alert above which price; alert below which price; daily summary time (e.g. `09:00`, container
  time zone); alert on a move of how many % within 24 h. Answer `no` to any of them.
- **Wallet**: one or more addresses (separated by spaces); the smallest amount to report.

Addresses are checked (right network, valid checksum) before they are accepted.

### Safety

- Only the owner can make a bot spend. Before pairing, a stranger gets at most one "This bot is private."
  a day; after pairing, everyone else is ignored.
- A bot sends at most 30 messages an hour (`BOT_MAX_OUT_PER_HOUR`), so nothing can drain its wallet.
- A bot never sends KAS anywhere but back to itself; keep only a small amount in it.

---

## How it works

- **Receiving.** KaChat messages never touch the recipient's address, so the daemon follows the chain
  (`GetVirtualChainFromBlockV2`, high verbosity, from a checkpoint in `/state/botd/chain.json`) and looks at
  every accepted transaction with a `kchat:1:comm:` / `kchat:1:dm:` payload (and legacy `ciph_msg:1:comm:`).
  The sender is the address input 0 spent from (output 0 must pay it back). A message is for a bot when its
  alias is the deterministic alias for that sender and bot (or a first-contact `dm` carries the bot's inbox
  tag) and it decrypts with the bot's key. With `KACHAT_INDEXER_URL` set, the chat indexer is polled as well
  to catch up after downtime. Every transaction is handled once.
- **Replying.** `kchat:1:comm:<alias>:<base64>` on the owner's deterministic alias; one input, one output back
  to the bot (no change output, so no dust); fee = iOS minimum standard fee. Back-to-back messages chain on the
  previous message's output instead of double-spending.
- **Notifications.** Mining and wallet bots use a `UtxosChanged` subscription; the price bot polls
  `api.kaspa.org` (CoinGecko as fallback) every minute.

### Files

| Path | |
|---|---|
| `/conf/bots.json` | the bots (written by the panel, re-read when it changes) |
| `/state/bots/<id>.json` | each bot's status for the panel |
| `/state/bots/<id>.history.jsonl` | the conversation, last 500 messages |
| `/state/botd/` | the daemon's own state (owners, settings, chain checkpoint) |

`/conf/bots.json`:

```json
{
  "version": 1,
  "bots": [
    { "id": "mining-3f9a", "type": "mining", "enabled": true,
      "privateKeyHex": "<64 hex>", "address": "kaspa:q...", "pairingCode": "482915",
      "resetOwner": "optional nonce; changing it resets the owner" }
  ]
}
```

### Environment

| Variable | Default | |
|---|---|---|
| `NODE_GRPC` | `kaspad:16110` | kaspad gRPC (node needs `--utxoindex`) |
| `NODE_WRPC` | `ws://kaspad:17110` | kaspad wRPC (Borsh), used to sign and submit |
| `KASPA_NETWORK` | `mainnet` | `mainnet` or `testnet-10` |
| `KACHAT_INDEXER_URL` | empty | optional chat indexer for catching up |
| `BRIDGE_STATS_URL` | empty | optional stratum bridge stats (hashrate) |
| `BOT_MAX_OUT_PER_HOUR` | `30` | messages one bot may send per hour |
| `BOTS_CONF` / `STATE_DIR` | `/conf/bots.json` / `/state` | file locations |

### Command line

```
python botd.py                          # run the daemon (the container's default)
python botd.py --send <botId> "<text>"  # one message to that bot's owner; prints {"ok","txid","error"}
python gen_wallet.py --network mainnet  # new wallet: {"privateKeyHex","address","network"}
python gen_wallet.py --network mainnet --from-key <64 hex>   # address of an existing key
```

`--send` hands the message to the running daemon (so its coins stay in order), or sends it directly when no
daemon is running.

### Emptying a bot wallet (`--sweep`)

```
python botd.py --sweep <botId> <toAddress>
{"ok": true, "txid": "<last txid>", "txids": ["..."], "amountSompi": 986837597, "feeSompi": 162403, "error": null}
```

Sends **all** of the bot's spendable KAS to `toAddress` (the panel's "Send to wallet" button): every coin as
an input, the payee as the only output, no change, no payload, the fee taken from the amount. A wallet with
more than 80 coins is swept in several transactions of at most 80 inputs each, every one paying the payee
directly. The address must be on the bot's network with a valid checksum and must not be the bot's own.
No owner is needed and it does not count toward the hourly message limit; it shows up in the bot's history.
Like `--send`, it goes through the running daemon (which pauses that wallet's messages meanwhile, up to
120 s) or runs directly when no daemon is running. Exit code 1 on failure, with `error` saying why
(e.g. "Nothing to send: the bot's wallet holds 0 KAS").

---

## Without the panel

```
git clone https://github.com/KaspaSilver/KaChat-Bot.git && cd KaChat-Bot
docker compose run --rm kachat-bot python gen_wallet.py --network mainnet   # keep the key safe
mkdir -p conf state && nano conf/bots.json                                   # see the example above
nano .env                                                                    # node addresses, network
docker compose up -d --build
docker logs -f kachat-bot
```

Then fund the bot's address and message it in KaChat with its pairing code.

## Tests

```
pip install -r requirements-dev.txt
python -m pytest
```

The tests need no node, no network and no Kaspa SDK (sending is faked).
