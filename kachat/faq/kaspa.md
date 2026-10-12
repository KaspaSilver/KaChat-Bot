# Kaspa answers

The Kaspa answers bot replies with these, word for word. Each topic is:

    ## Title (shown in the topics list)
    keys: words or phrases, separated by commas, that point at this topic
    The answer: one short paragraph or a few lines.
    Source: https://... (optional last line: where the facts come from; sent with the answer)

A question picks the topic whose keys it contains most of (longer phrases weigh more).
Keep answers short: every reply is a small Kaspa transaction the bot pays for.

## What is Kaspa
keys: what is kaspa, what's kaspa, about kaspa, explain kaspa, tell me about kaspa, kaspa coin, what is kas
Kaspa is a programmable P2P digital currency capable of moving value, communications, and verification at the speed of the internet with real time decentralization and censorship resistance.

## What Kaspa is for
keys: purpose, its purpose, use case, use cases, what is it for, what's it for, what is kaspa for, why kaspa, why use kaspa, economically, economic, economics, utility, what problem, point of kaspa, value proposition
Kaspa is meant to be fast, decentralized digital money: you can pay anyone directly, with confirmations in seconds and tiny fees, without a bank or company in between. Like Bitcoin it has a fixed supply and is secured by proof-of-work mining, but it is built to scale to everyday payments. Its fast blocks also make it a base layer for apps and tokens built on top.

## What the name means
keys: name mean, meaning of kaspa, why called kaspa, kaspa mean, word kaspa
"Kaspa" is the Aramaic word for silver, a word that was also used to mean money.

## Who created Kaspa
keys: who created, who made, who built, founder, founders, creator, team, yonatan, sompolinsky, dev team, developers
Kaspa grew out of research by Yonatan Sompolinsky and Aviv Zohar (the GHOSTDAG/PHANTOM papers). It is open source and built by a community of independent developers. No company owns or controls it.

## Fair launch
keys: fair launch, premine, pre mine, ico, presale, pre sale, dev fee, founders reward, vc, investors, allocation
Kaspa launched on November 7, 2021 with no premine, no ICO or presale, and no coins set aside for developers or investors. Every KAS in existence was mined.

## Max supply
keys: max supply, maximum supply, total supply, supply cap, how many kas, how many coins, hard cap, total coins
The maximum supply is about 28.7 billion KAS (28,704,026,601). No more can ever be created.

## Emission and halving
keys: emission, halving, halvening, chromatic, block reward schedule, reward schedule, inflation, reward halve, reduction
Kaspa uses a "chromatic" emission: the block reward halves every year, but smoothly, with a small cut every month (each month's reward is the previous one times (1/2)^(1/12)). There is no single halving day. The last KAS are expected to be mined around 2057.

## Current reward and circulating supply
keys: current reward, current block reward, block reward now, block reward today, block reward right now, what is the block reward, how much is the block reward, circulating supply, current supply, how many mined, mined so far, reward right now, reward per block
The block reward changes every month and the circulating supply grows every second, so I don't keep those numbers. A Kaspa explorer such as explorer.kaspa.org shows both live.

## Blocks per second
keys: blocks per second, bps, block time, how fast are blocks, block speed, 10 bps, 1 bps, block interval
Kaspa makes 10 blocks per second (one every 100 milliseconds). It moved from 1 to 10 blocks per second with the Crescendo hard fork on May 5, 2025.

## Blocks per day
keys: blocks per day, blocks a day, how many blocks, 864000, daily blocks
At 10 blocks per second Kaspa makes 864,000 blocks a day.
Source: https://kaspa.com/learn-kaspa/post/blue-score-and-blue-work

## Confirmation time
keys: confirmation, confirmations, how long, how fast, transaction speed, confirm time, settle
A transaction shows up in a block within about a second and is safely confirmed within seconds. For large amounts, waiting around 10 seconds is plenty. There are no long waits like Bitcoin's 10-minute blocks. (Send finality for the point after which it can never be undone.)

## Finality
keys: finality, final, finality depth, irreversible, reversible, undone, reverse a transaction, reversed, be reversed, reverse, 12 hours, reorg, reorganization, how deep, 432000
A transaction is practically safe within seconds, and after the finality depth it can never be undone: 432,000 blocks, which is 12 hours at 10 blocks per second (it was 24 hours before Crescendo). Unlike Bitcoin, Kaspa nodes flatly reject any block that would rewrite history past that point, even with enormous hashpower.
Source: https://kaspa.com/learn-kaspa/post/finality-depth

## Transactions per second
keys: tps, transactions per second, throughput, scalability, scale, capacity
At 10 blocks per second the network can handle thousands of transactions per second, and the roadmap aims higher. Fees stay low because blocks are rarely full.

## BlockDAG
keys: blockdag, block dag, dag, why dag, directed acyclic graph, orphan, orphans, parallel blocks
In a normal blockchain, two blocks found at once compete and one is thrown away. In Kaspa's blockDAG a new block points to all the latest blocks it knows, so parallel blocks are all kept. That is what lets Kaspa run fast blocks without wasting mining work or hurting security.
Source: https://kaspa.com/learn-kaspa/post/dag-and-kaspa

## The Bitcoin scaling problem
keys: scaling problem, bitcoin scaling, scalability trilemma, why not faster blocks, faster blocks, orphan blocks, orphaned, why 10 minutes, propagation
A blockchain can't simply make blocks faster: blocks found while another is still spreading across the network become orphans, wasting mining work and weakening security. That is why Bitcoin waits 10 minutes per block. Kaspa keeps those parallel blocks instead (a block can point to several parents), so it can make blocks far faster than they spread, without the waste.
Source: https://kaspa.com/learn-kaspa/post/kaspa-and-the-bitcoin-scaling-problem

## GHOSTDAG
keys: ghostdag, ghost dag, phantom, consensus, ordering, blue set, k parameter
GHOSTDAG is Kaspa's consensus protocol. It looks at the blockDAG, picks the well-connected ("blue") blocks, and puts every block into one agreed order. It is a generalization of Bitcoin's longest-chain rule that stays secure at high block rates.
Source: https://kaspa.com/learn-kaspa/post/learn-kaspa-guide

## Blue and red blocks
keys: blue block, blue blocks, red block, red blocks, blue set, colour, color, coloring, colouring
GHOSTDAG colours blocks: blue blocks are well connected to the rest of the network (the honest majority), red blocks are ones that look out of touch. Red blocks are still valid: their transactions count unless they conflict, and the miner who merges them collects their fees. Only blue blocks count toward the chain's accumulated work.
Source: https://kaspa.com/learn-kaspa/post/dag-terminology

## Blue score and blue work
keys: blue score, blue work, block height, height, daa score, chain selection, selected chain, heaviest chain
Blue score is Kaspa's version of block height: how many blue blocks are in a block's past. Blue work is the total proof-of-work of those blue blocks, and the chain with the most blue work wins, like Bitcoin's most-work rule. DAA score is a related counter used for difficulty, the block reward schedule and timelocks.
Source: https://kaspa.com/learn-kaspa/post/blue-score-and-blue-work

## The k parameter
keys: k parameter, k value, what is k, 124, anticone, mergeset, network delay, ghostdag parameter
GHOSTDAG's k is how many parallel blocks it tolerates before a block is considered out of touch (red). It comes from the block rate and a conservative 5-second network delay: k = 124 at 10 blocks per second (it was 18 at 1 per second). A block can merge up to 248 other blocks; normally it merges about 6 to 8.
Source: https://kaspa.com/learn-kaspa/post/kaspa-and-the-bitcoin-scaling-problem

## Virtual block
keys: virtual block, virtual, sink, virtual state, tips, dag tips, current state
The virtual block is not a real block: it is how every node sums up the current tips of the DAG into one view of "now". Its main parent is the tip with the most blue work. Wallet balances, the mempool and miners' block templates all work from this virtual state.
Source: https://kaspa.com/learn-kaspa/post/virtual-block

## DAGKnight
keys: dagknight, dag knight, dk, parameterless
DAGKnight is the planned successor to GHOSTDAG, from the same research. GHOSTDAG uses a fixed worst-case network delay (its k parameter); DAGKnight has no such parameter: it measures how connected the honest blocks actually are, so confirmations speed up when the network is fast and it stays safe when it is slow, as long as honest miners hold over half the hashrate. It is not the live consensus yet.
Source: https://kaspa.com/learn-kaspa/post/dagknight

## Crescendo hard fork
keys: crescendo, hard fork, hardfork, upgrade, kip 14, kip14, may 2025
Crescendo was the hard fork of May 5, 2025. It raised Kaspa from 1 to 10 blocks per second and added new script features (KIP-10 introspection) that lay the groundwork for smart contracts and covenants.

## Toccata hard fork
keys: toccata, covenant hard fork, covenants hard fork, next hard fork, kip 17, kip17
Toccata is the hard fork that brings covenants to Kaspa: richer transaction introspection (KIP-17), consensus-tracked covenant IDs (KIP-20) and room for zero-knowledge proof checks. The newest Kaspa learning material places its activation around DAA score 474 million (mid-2026). Check kaspa.org for the current details.
Source: https://kaspa.com/learn-kaspa/post/dag-and-kaspa

## Mining algorithm
keys: algorithm, kheavyhash, heavyhash, heavy hash, hash function, pow algorithm, proof of work algorithm
Kaspa's proof-of-work algorithm is kHeavyHash: a matrix multiplication between two rounds of Keccak (cSHAKE256) hashing.

## Mining hardware
keys: asic, asics, miner, miners, iceriver, antminer, bitmain, goldshell, ks0, ks3, ks5, mining hardware, what to mine with
Kaspa is mined with ASICs built for kHeavyHash, such as IceRiver KS models and Bitmain's Antminer KS series. Check current profitability with a mining calculator before buying, since rewards drop a little every month.

## GPU mining
keys: gpu, gpus, graphics card, nvidia, amd, rig, gpu mining
GPU mining Kaspa is no longer profitable: ASICs took over the network in 2023 and are many times more efficient.

## How to mine
keys: how to mine, how do i mine, start mining, mining pool, pool, solo mining, solo mine, stratum
Point a kHeavyHash ASIC at a mining pool, or mine solo: run your own Kaspa node plus a stratum bridge (Kaspa Quick Start sets up both) and point your miner at it. Solo mining only pays when you find a block yourself, so it suits bigger hashrates.

## Staking
keys: staking, stake, proof of stake, pos, validator, validators, delegate, earn interest, yield
Kaspa has no staking. It is pure proof-of-work: new KAS go only to miners. Anyone offering "Kaspa staking" is running their own scheme, not the network.

## Sompi
keys: sompi, smallest unit, decimals, satoshi, divisible, unit
The smallest unit of KAS is the sompi. 1 KAS = 100,000,000 sompi, so KAS has 8 decimals like Bitcoin.

## Addresses
keys: address, addresses, kaspa:, address format, kaspa:q, kaspa:p, kaspatest
Mainnet addresses start with "kaspa:" and testnet addresses with "kaspatest:". A normal wallet address starts with kaspa:q; one starting with kaspa:p is a script (P2SH) address. The address includes a checksum, so a typo is caught instead of sending to a wrong address.

## Fees
keys: fee, fees, transaction fee, how much does it cost, cost to send, gas, mass, priority fee
Kaspa fees are tiny, usually a small fraction of a cent. A fee is based on the transaction's "mass" (its size and the outputs it creates). When the network is busy you can add a priority fee to go first.

## Storage mass (KIP-9)
keys: storage mass, kip 9, kip9, kip-9, mass, why is the fee so high, small outputs, tiny amounts, send small amount, dust attack, utxo bloat
Storage mass (KIP-9) makes transactions that create many small coins expensive, so nobody can bloat the set of coins every node stores. Normal payments (above roughly 0.2 KAS) barely notice it, and combining coins is cheap. Sending very small amounts or splitting into many tiny outputs costs more. It was added after a real dust attack.
Source: https://kaspa.com/learn-kaspa/post/storage-mass-kip-0009

## Block mass limit
keys: block size, block limit, mass limit, block mass, how big is a block, 500000
Kaspa limits blocks by "mass" instead of bytes: a combined measure of computing, bandwidth and storage cost. Each block can hold up to 500,000 mass, and at 10 blocks per second that leaves plenty of room.
Source: https://kaspa.com/learn-kaspa/post/anatomy-of-a-block

## UTXOs and compounding
keys: utxo, utxos, compound, compounding, too many inputs, transaction too large, consolidate
Kaspa uses UTXOs like Bitcoin: your balance is a set of separate coins. Many small payments (mining payouts, for example) make a wallet hold lots of coins, so sending can need several transactions. Most wallets "compound" these automatically or with one button, and compounding is cheap (see storage mass).

## Wallets
keys: wallet, wallets, best wallet, which wallet, kaspium, kasware, kastle, kaspa ng, tangem, ledger, kasvault, hardware wallet, store kas
Popular Kaspa wallets: Kaspa NG (desktop and web, by the core developers), Kaspium (mobile), Kasware and Kastle (browser extensions), and hardware wallets such as Tangem and Ledger (through KasVault). Download a wallet only from its official site or app store.

## Seed phrase safety
keys: seed, seed phrase, recovery phrase, mnemonic, private key, 12 words, 24 words, backup, lost wallet, keys
Your seed phrase is your money. Write it down offline, never type it into a website or chat, and never share it with anyone. No real support person, admin or bot will ever ask for it, including me.

## Scams
keys: scam, scams, scammer, giveaway, airdrop, double your, support dm, fake, hacked, phishing, recover my funds
Watch out for "giveaways" that ask you to send KAS first, people in your DMs claiming to be support, fake wallet sites, and "fund recovery" services. Kaspa has no official giveaways, and nobody legitimate will ask for your seed phrase.

## Where to buy KAS
keys: buy, where to buy, purchase, exchange, exchanges, get kas, sell, trade, listing, listed
KAS trades on many centralized exchanges and some decentralized ones. I don't recommend specific exchanges; CoinGecko or CoinMarketCap list where it trades. Move your KAS to your own wallet if you aren't trading.

## Price
keys: price, worth, value, how much is kas, market cap, marketcap, moon, prediction, invest, investment, good investment, buy now, financial advice, pump
I don't give prices or investment advice. For live prices and alerts, set up the Price bot in KaChat Bot.

## Smart contracts
keys: smart contract, smart contracts, contracts, evm, programmability, defi, vprogs, layer 2, layer two, l2, rollup, rollups, igra, kasplex l2
Kaspa programmability comes in layers. Its script language already does multisig, timelocks and escrow, and Crescendo (May 2025) let scripts inspect the transaction (KIP-10). Covenants add rules about where coins can go next (KIP-17/KIP-20, the Toccata hard fork). Layer-2s like Kasplex L2 and Igra bring EVM contracts that settle on Kaspa, and native "vProgs" are in research. Send covenants, KIP-10 or SilverScript for more.
Source: https://kaspa.com/learn-kaspa/post/smart-contracts

## Covenants
keys: covenant, covenants, covenant id, kip 20, kip20, native tokens, native assets, bridge, bridges
A covenant is a coin with rules about where it may go next, checked by every node. Kaspa covenants (Toccata hard fork: KIP-17 introspection and KIP-20 covenant IDs) let coins carry a stable identity across transactions, which enables native tokens enforced by consensus, payment channels, vaults and the building blocks for trustless bridges to layer-2s.
Source: https://kaspa.com/learn-kaspa/post/kip-20

## KIP-10
keys: kip 10, kip10, kip-10, introspection, transaction introspection, 8 byte, 64 bit
KIP-10, live since Crescendo (May 2025), lets a script read the transaction it is in: input and output amounts and scripts, and their counts. It also widened script math to 8-byte numbers. That allows rules like "this coin can only be spent into an output of equal or larger value", useful for mining pool payouts and micropayments.
Source: https://kaspa.com/learn-kaspa/post/kip-10

## KIP-21
keys: kip 21, kip21, kip-21, partitioned sequencing, sequencing commitment, lanes, lane
KIP-21 is a proposal, not yet implemented, to split Kaspa's record of transaction order into separate "lanes", so a zero-knowledge rollup only has to prove its own lane's activity instead of the whole network's. That would make ZK layer-2s much cheaper. It would need a hard fork.
Source: https://kaspa.com/learn-kaspa/post/kip-21

## SilverScript
keys: silverscript, silver script, programming language, write a contract, contract language, cashscript
SilverScript is a high-level language for writing Kaspa contracts, inspired by CashScript with a Solidity-like look. It compiles to Kaspa Script and supports KIP-10 introspection and covenants.
Source: https://kaspa.com/learn-kaspa/post/smart-contracts

## Kaspa Script and opcodes
keys: script, kaspa script, opcode, opcodes, multisig, multi sig, timelock, time lock, escrow, schnorr, ecdsa, p2sh
Kaspa Script is a small stack language like Bitcoin's: every coin has a lock (a script) and spending it needs the matching key. It supports Schnorr and ECDSA signatures, M-of-N multisig, timelocks and script-hash (P2SH) addresses, with limits that keep validation fast. A tip: a timelock branch must still require a signature, or anyone can spend after the time passes.
Source: https://kaspa.com/learn-kaspa/post/opcodes

## KRC-20 tokens
keys: krc20, krc 20, krc-20, token, tokens, kasplex, meme coin, mint, inscription, inscriptions, deploy token
KRC-20 is a token standard on Kaspa, created by Kasplex. Tokens are written into ordinary Kaspa transactions (a commit-reveal "inscription"), deployed and minted openly, and read by indexers: the network itself ignores the token data, the indexers enforce the rules. Covenant-based tokens, which every node enforces, are the newer alternative. Wallets like Kasware and Kastle can hold and trade KRC-20.
Source: https://kaspa.com/learn-kaspa/post/dag-and-kaspa

## NFTs
keys: nft, nfts, krc721, krc 721, krc-721, collectible, collectibles
NFTs on Kaspa use the KRC-721 standard (also by Kasplex), inscribed the same way as KRC-20 tokens. Marketplaces and wallets such as Kasware support them.

## Explorers
keys: explorer, explorers, block explorer, look up transaction, check transaction, txid, track transaction, kas.fyi
Look up any address, block or transaction on a Kaspa explorer such as explorer.kaspa.org or kas.fyi. Paste the address or transaction ID into the search box.

## Running a node
keys: node, run a node, full node, kaspad, rusty kaspa, rusty-kaspa, self host, requirements, hardware for node
Run a node with kaspad from Rusty Kaspa (the Rust implementation), or let Kaspa Quick Start set one up with a click. Plan for a modern 4 to 8 core machine, at least 16 GB of RAM and a fast SSD. A new node doesn't replay history from 2021: it downloads a recent snapshot of all coins, checks it against the commitment in the block headers, and syncs quickly.

## Pruning
keys: pruning, prune, pruned, archival, archive node, history, old blocks, disk space, storage
Kaspa nodes prune: they keep full block data for about the last 30 hours (1,080,000 blocks at 10 blocks per second), plus the current set of coins (UTXOs) and compact proofs of all the work before it, so a node stays small. Pruning is safe because anything that old is already final. Node operators can choose to keep more, and archival nodes keep the full history for explorers and indexers.
Source: https://kaspa.com/learn-kaspa/post/pruning-depth

## How a new node syncs
keys: sync, syncing, initial block download, ibd, how long to sync, to sync, new node, node to sync, take to sync, utxo commitment, muhash, snapshot
Every Kaspa block header commits to the whole set of coins (a MuHash of the UTXO set). A new node downloads a recent snapshot of the coins plus a compact proof of all past work ("mining in log space"), checks both against the headers, and is ready quickly, without replaying everything since 2021.
Source: https://kaspa.com/learn-kaspa/post/kaspa-linking-the-body-to-the-header

## Inside a block
keys: block header, inside a block, anatomy of a block, nonce, merkle root, coinbase, header fields, what is in a block
A Kaspa block is a header plus transactions. The header lists its parents, Merkle roots for its own and its accepted transactions, a commitment to all coins, the timestamp in milliseconds, difficulty, a 64-bit nonce, DAA score, blue score, blue work and the pruning point. The first transaction is the coinbase, which pays the miner.
Source: https://kaspa.com/learn-kaspa/post/anatomy-of-a-block

## Block timestamps
keys: timestamp, timestamps, past median time, block time accuracy, fake time, future timestamp
Each block's timestamp must be later than the median time of earlier blocks (sampled along the chain), and may only be slightly ahead of a node's own clock. That stops miners from faking times, which keeps difficulty adjustment and time-locked payments reliable.
Source: https://kaspa.com/learn-kaspa/post/timestamp-validation

## Rusty Kaspa
keys: rusty, rust, rusty kaspa, golang, go kaspad, implementation, client
Rusty Kaspa is the Rust implementation of Kaspa and the one the network runs today. It replaced the older Go client and is what made 10 blocks per second possible.

## Node ports
keys: port, ports, what ports, which ports, ports does, node ports, open ports, 16111, 16110, 17110, 18110, grpc, wrpc, rpc, p2p port, firewall
Mainnet node ports: 16111 for peers (p2p), 16110 for gRPC, 17110 for wRPC (Borsh) and 18110 for wRPC (JSON). Only 16111 needs to be open to the internet for incoming peers.

## Testnet
keys: testnet, test net, tn10, testnet 10, faucet, test coins, test kas
Kaspa's public testnet is Testnet 10, with "kaspatest:" addresses and free test coins from a faucet. Use it to try things without real KAS.

## Security and 51% attacks
keys: security, secure, 51, 51 percent, attack, attacks, double spend, double spending, safe
Kaspa is secured by proof-of-work, like Bitcoin: an attacker would need more than half of all the mining power. GHOSTDAG keeps that security at 10 blocks per second, where an ordinary blockchain would weaken, and nodes refuse any reorganization deeper than the finality depth (12 hours).
Source: https://kaspa.com/learn-kaspa/post/finality-depth

## Is it a Bitcoin fork
keys: bitcoin fork, fork of bitcoin, based on bitcoin, copy of bitcoin, like bitcoin, vs bitcoin, compared to bitcoin
No. Kaspa shares Bitcoin's core ideas (proof-of-work, UTXOs, a fixed supply) but has its own network, history and consensus (a blockDAG ordered by GHOSTDAG). It never shared a blockchain with Bitcoin.

## Kaspa Improvement Proposals
keys: kip, kips, improvement proposal, proposal, governance, roadmap, who decides
Changes to Kaspa are written up as KIPs (Kaspa Improvement Proposals), discussed in public on GitHub (kaspanet/kips), and adopted when node operators and miners run the new software.

## Official links
keys: website, official, links, discord, telegram, twitter, community, github, docs, documentation
Start at kaspa.org: it links the official community channels, docs and wallets. The code is on github.com/kaspanet. Beware of look-alike sites and accounts.

## Learn more
keys: learn more, learn kaspa, deep dive, technical, how does it work, resources, articles, read more, education
For deeper reading, the "Learn Kaspa" articles on kaspa.com explain the BlockDAG, GHOSTDAG, finality, pruning, KIPs and smart contracts step by step, and kaspa.org links the docs and the research papers.
Source: https://kaspa.com/learn-kaspa

## KaChat
keys: kachat, ka chat, this app, messaging, messenger, chat app, encrypted, messages on chain
KaChat is a messenger built on Kaspa. Every message is a tiny end-to-end encrypted Kaspa transaction, so there is no company server holding your chats. It runs on iPhone, Android and desktop.

## .kachat names
keys: .kachat, kachat name, kachat names, domain, domains, username, register name, name service
.kachat names are short names you register on Kaspa for KaChat, so people can find you by name instead of a long address. Register one in the KaChat app.

## Kaspa Quick Start
keys: quick start, kaspa quick start, kqs, control panel, one click, one-click, install node
Kaspa Quick Start is a control panel that installs and runs a Kaspa node with a click, plus optional apps: a mining bridge, the KaChat indexer, .kachat Domains and KaChat bots.

## About this bot
keys: who are you, what are you, are you a bot, are you ai, this bot, about you, how do you work, are you human
I'm a KaChat bot with fixed answers to common Kaspa questions, written by hand and checked, not generated. Every answer is a small Kaspa transaction paid from my own wallet, so I answer a few questions per person each day. Send topics to see everything I know.
