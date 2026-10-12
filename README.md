# KaChat Bot v2

Small bots you talk to in **KaChat**. Each bot has its own Kaspa wallet and is **public**: there are no pairing
codes, anyone who messages it gets their own private conversation with it. It asks each person a few setup
questions in the chat, then messages them when something happens:

| Bot | Tells you |
|---|---|
| **Mining** | every block reward paid to your mining address (reward and balance) |
| **Price** | when KAS crosses a price you chose (once per crossing), a daily summary, and big moves within 24 h |
| **Wallet** | when a watched address receives or sends KAS: the amount and its new balance, by nickname |
| **Kaspa answers** | answers common Kaspa questions for *anyone* who messages it, from a fixed hand-checked list ([kachat/faq/kaspa.md](kachat/faq/kaspa.md)) |

Messages are ordinary KaChat 1:1 messages: end-to-end encrypted (ephemeral secp256k1 ECDH, HKDF-SHA256,
ChaCha20-Poly1305) and sent as a self-spend, so a message only costs the network fee (about 0.002 KAS).
Nothing is ever paid to anyone.

One container runs any number of bots. It is normally deployed and driven by the
**Kaspa Quick Start** panel.

---

## With the Kaspa Quick Start panel

1. **Set up a bot.** Click a bot square (Mining, Price, Wallet or Kaspa answers). The panel creates a wallet for it and
   shows the bot's address.
2. **Fund the address.** Send the bot a few KAS (1 KAS is hundreds of messages). It pays for every message it
   sends to everyone, so keep an eye on its balance. The square shows when it is funded.
3. **Share its address.** Anyone who messages it in KaChat (you too) gets a greeting and its setup questions,
   one at a time; send `skip` to keep a default. Each person's settings are their own.

*Reset* in the panel forgets everyone's setup (each person starts over the next time they message); the
wallet and its KAS stay. A bot that was paired before bots went public keeps its owner's setup: that person
simply carries on as one of its people.

### Commands (send them in the chat, any time)

| Command | |
|---|---|
| `help` | the list of commands |
| `status` | what the bot is doing, and its wallet balance |
| `settings` | its current settings |
| `change` | answer the setup questions again (`skip` keeps the current value) |
| `reset` | forget the settings and start setup over from the defaults (you stay paired) |
| `add` | mining and wallet bots: watch another address (it asks for the address, and a nickname on wallet bots; `add kaspa:…` works in one go; up to 10; `cancel` stops it) |
| `pause` / `resume` | stop / restart notifications |
| `test` | send a sample notification |

### Setup questions

- **Mining**: the mining address to watch; the smallest reward to report (KAS, 0 = every block). (The pool
  hashrate questions are gone: the panel's stratum bridge is the panel owner's, not everyone's.)
- **Price** (USD): alert above which price; alert below which price; daily summary time (`9 AM`, `8:30 PM`,
  `noon`, or 24-hour `21:30`) and then your time zone (a city like `New York` or `London`, an abbreviation like
  `EST`, or `UTC`; only asked when you want the summary); alert on a move of how many % within 24 h. Answer `no` to
  any of them.
- **Wallet**: one or more addresses (separated by spaces, up to 10); a nickname for each, or none; the smallest amount to report.
- **Kaspa answers**: none. It has no owner and no setup (see below).

### The Kaspa answers bot

It is public: no pairing code, no owner, no setup chat. Set it up in the panel, fund it, and it is live;
share its address and anyone in KaChat can message it. A question gets the topic in
[kachat/faq/kaspa.md](kachat/faq/kaspa.md) whose keys it contains most of, word for word; `topics` (or `hi`)
lists them and a number picks one. Nothing is generated. Each person gets 30 answers a day, then one "that's
all for today" note. It has no hourly limit (anyone may ask), so its wallet balance is the only cap on how many
people it answers: fund it with that in mind. Its panel square shows how many it has answered, how many people
asked today, every conversation, and recent questions it had no answer for, so you know what to add. Edit the
file and rebuild to change the answers. The on/off switch stops it; Reset starts its counts over.

### Safety

- Every bot answers anyone while it is switched on. Each person gets at most 30 messages a day from a bot
  (setup replies and notifications together, then one "that's my limit for today" note), and at most 1,000
  people can use one bot. There is no hourly limit, so a bot's wallet balance is what caps its spending:
  keep only a few KAS in it.
- A bot never sends KAS anywhere but back to itself, except when the panel's *Send to wallet* empties it.
- `botd.py --send <bot> "<text>" --to <address>` sends one message to an address (the panel's alerts; bots
  have no owner to send to any more).

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
| `/state/botd/` | the daemon's own state (chain checkpoint; each bot's people in `<id>.json`, each person's settings in `<id>/<key>.json`) |

`/conf/bots.json`:

```json
{
  "version": 1,
  "bots": [
    { "id": "mining-3f9a", "type": "mining", "enabled": true,
      "privateKeyHex": "<64 hex>", "address": "kaspa:q...", "pairingCode": "482915 (still required, no longer used)",
      "resetOwner": "optional nonce; changing it forgets everyone's setup (as resetSettings)",
      "resetSettings": "optional nonce; changing it forgets everyone's setup; the wallet and its funds stay" }
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
| `BOTS_CONF` / `STATE_DIR` | `/conf/bots.json` / `/state` | file locations |

### Command line

```
python botd.py                          # run the daemon (the container's default)
python botd.py --send <botId> "<text>" --to <address>  # one message to that address; prints {"ok","txid","error"}
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
It does not count toward anyone's daily messages; it shows up in the bot's history.
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

Then fund the bot's address and message it in KaChat.

## Tests

```
pip install -r requirements-dev.txt
python -m pytest
```

The tests need no node, no network and no Kaspa SDK (sending is faked).
