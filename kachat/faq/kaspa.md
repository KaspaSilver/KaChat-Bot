# Kaspa answers

The Kaspa answers bot replies with these, word for word. Each topic is:

    ## Title (shown in the topics list)
    keys: words or phrases, separated by commas, that point at this topic
    The answer: one short paragraph or a few lines.

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

## Confirmation time
keys: confirmation, confirmations, how long, how fast, transaction speed, confirm time, settle, finality, final
A transaction shows up in a block within about a second and is safely confirmed within seconds. For large amounts, waiting around 10 seconds is plenty. There are no long waits like Bitcoin's 10-minute blocks.

## Transactions per second
keys: tps, transactions per second, throughput, scalability, scale, capacity
At 10 blocks per second the network can handle thousands of transactions per second, and the roadmap aims higher. Fees stay low because blocks are rarely full.

## BlockDAG
keys: blockdag, block dag, dag, why dag, directed acyclic graph, orphan, orphans, parallel blocks
In a normal blockchain, two blocks found at once compete and one is thrown away. In Kaspa's blockDAG a new block points to all the latest blocks it knows, so parallel blocks are all kept. That is what lets Kaspa run fast blocks without wasting mining work or hurting security.

## GHOSTDAG
keys: ghostdag, ghost dag, phantom, consensus, ordering, blue set, k parameter
GHOSTDAG is Kaspa's consensus protocol. It looks at the blockDAG, picks the well-connected ("blue") blocks, and puts every block into one agreed order. It is a generalization of Bitcoin's longest-chain rule that stays secure at high block rates.

## DAGKnight
keys: dagknight, dag knight, dk, parameterless
DAGKnight is the planned successor to GHOSTDAG, also from Kaspa's research. It adapts to real network delays on its own instead of using a fixed assumption, which makes Kaspa faster and more robust. It is not live yet.

## Crescendo hard fork
keys: crescendo, hard fork, hardfork, upgrade, kip 14, kip14, may 2025
Crescendo was the hard fork of May 5, 2025. It raised Kaspa from 1 to 10 blocks per second and added new script features (KIP-10 introspection) that lay the groundwork for smart contracts and covenants.

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

## UTXOs and compounding
keys: utxo, utxos, compound, compounding, too many inputs, transaction too large, storage mass, consolidate, dust
Kaspa uses UTXOs like Bitcoin: your balance is a set of separate coins. Many small payments (mining payouts, for example) make a wallet hold lots of coins, so sending can need several transactions. Most wallets "compound" these automatically or with one button.

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
Kaspa's base layer doesn't run general smart contracts yet. Crescendo added the first building blocks, layer-2 projects (such as Kasplex L2 and Igra) bring EVM-style contracts that settle on Kaspa, and native "vProgs" programmability is being researched and built.

## KRC-20 tokens
keys: krc20, krc 20, krc-20, token, tokens, kasplex, meme coin, mint, inscription, inscriptions, deploy token
KRC-20 is a token standard on Kaspa, created by Kasplex. Tokens are written into ordinary Kaspa transactions (a commit-reveal "inscription"), deployed and minted openly, and read by indexers. Wallets like Kasware and Kastle can hold and trade them.

## NFTs
keys: nft, nfts, krc721, krc 721, krc-721, collectible, collectibles
NFTs on Kaspa use the KRC-721 standard (also by Kasplex), inscribed the same way as KRC-20 tokens. Marketplaces and wallets such as Kasware support them.

## Explorers
keys: explorer, explorers, block explorer, look up transaction, check transaction, txid, track transaction, kas.fyi
Look up any address, block or transaction on a Kaspa explorer such as explorer.kaspa.org or kas.fyi. Paste the address or transaction ID into the search box.

## Running a node
keys: node, run a node, full node, kaspad, rusty kaspa, rusty-kaspa, self host, requirements, hardware for node
Run a node with kaspad from Rusty Kaspa (the Rust implementation), or let Kaspa Quick Start set one up with a click. Plan for a modern 4 to 8 core machine, at least 16 GB of RAM and a fast SSD; it syncs in hours, not days.

## Pruning
keys: pruning, prune, pruned, archival, archive node, history, old blocks, disk space, storage
Kaspa nodes prune: they keep only recent block data (about the last day or two) plus proofs of everything before, so a node stays small. Archival nodes keep the full history for explorers and indexers.

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
Kaspa is secured by proof-of-work, like Bitcoin: an attacker would need more than half of all the mining power. GHOSTDAG keeps that security at 10 blocks per second, where an ordinary blockchain would weaken.

## Is it a Bitcoin fork
keys: bitcoin fork, fork of bitcoin, based on bitcoin, copy of bitcoin, like bitcoin, vs bitcoin, compared to bitcoin
No. Kaspa shares Bitcoin's core ideas (proof-of-work, UTXOs, a fixed supply) but has its own network, history and consensus (a blockDAG ordered by GHOSTDAG). It never shared a blockchain with Bitcoin.

## Kaspa Improvement Proposals
keys: kip, kips, improvement proposal, proposal, governance, roadmap, who decides
Changes to Kaspa are written up as KIPs (Kaspa Improvement Proposals), discussed in public on GitHub (kaspanet/kips), and adopted when node operators and miners run the new software.

## Official links
keys: website, official, links, discord, telegram, twitter, community, github, docs, documentation, learn more
Start at kaspa.org: it links the official community channels, docs and wallets. The code is on github.com/kaspanet. Beware of look-alike sites and accounts.

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
