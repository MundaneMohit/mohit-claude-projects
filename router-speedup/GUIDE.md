# Router speedup: guided Wi-Fi check (for Claude)

Goal: find out why the home internet feels slow or laggy, fix what can be fixed safely, and prove it with
before/after numbers. Written for a Windows PC; adapt the commands on Mac/Linux.

## Rules

- **Measure before you change anything**, and measure again after. One run proves little: repeat tests and
  say how sure you are.
- **Never change router settings yourself.** Tell the person exactly what to click; they apply it. Every change
  drops Wi-Fi briefly, including your own connection.
- **Never type passwords** (router or provider account). The person logs in.
- **Do not save or share** network names, addresses, contract details or the router password.
- A VPN changes every result. Ask whether one is on, and test without it if allowed.

## 1. Baseline (no changes)

Run on the PC and record the numbers:

| Check | Command (PowerShell) | Look at |
|---|---|---|
| Wi-Fi link | `netsh wlan show interfaces` | band, channel, signal %, receive/transmit rate |
| Neighbours | `netsh wlan show networks mode=bssid` | which channels nearby networks use, and their signal |
| Router ping | `ping -n 100 <router IP>` (router IP = "Default Gateway" in `ipconfig`) | average and worst; spikes over ~100 ms on the first hop point to Wi-Fi |
| Internet ping | `ping -n 100 1.1.1.1` | average and worst |
| DNS speed | `Measure-Command { Resolve-DnsName example.org -Server <router IP> -DnsOnly }` vs `-Server 1.1.1.1` (use a new domain each run) | the router's DNS is often several times slower |
| Speed | a speed test in the browser (speed.cloudflare.com or fast.com), 3 runs | download / upload; compare with the contract speed |

## 2. Read the router (browser tool, read only)

The person opens the router page (usually http://192.168.0.1 or http://192.168.178.1) and logs in. Then read:

- Wi-Fi settings per band: mode, **channel** (Auto or fixed), **bandwidth**, band steering, split network names.
- Channel analysis / scan pages for 2.4 GHz and 5 GHz. Running a scan may drop Wi-Fi for a moment: let the
  person click it.
- Cable lines only: Status → **DOCSIS** signal levels and error counts. Bad levels or many errors are a line
  problem only the provider can fix.

## 3. Decide

| Finding | Suggest |
|---|---|
| 5 GHz on a DFS channel (52–144) with ping spikes | fixed non-DFS channel **36, 40, 44 or 48**, keep 80 MHz |
| A strong neighbour (signal better than about -60 dBm) on your channel block | move to the block where neighbours are weakest |
| 2.4 GHz crowded | channel **1, 6 or 11**, whichever has the weakest strong neighbours (a few strong ones hurt more than many weak ones); bandwidth **20 MHz** |
| Router DNS much slower than 1.1.1.1 | set DNS to 1.1.1.1 / 1.0.0.1 on the PC (needs admin), phone (Android: Private DNS `one.one.one.one`) or browser (Chrome/Edge: Use secure DNS → Cloudflare) |
| Speed fine on cable but not Wi-Fi | Wi-Fi problem: channel, router placement, mesh points for far rooms |
| Speed low on cable too | line or provider: check DOCSIS, then contact the provider with the numbers |
| Router's own "channel busy %" figure | do not trust it alone; some routers show the same number on every channel |

Also worth saying: plug stationary devices (TV, console, desktop) in by cable; place the router central and
high, not in a cabinet; keep smart-home gadgets on 2.4 GHz and everything else on 5 GHz; band steering only
works when both bands share one network name.

## 4. Change and re-measure

1. The person applies one change at a time in the router and waits for devices to reconnect.
2. Rerun section 1 exactly as before.
3. Show a before/after table (ping average and worst, internet ping, download, upload, link rate) and say
   which differences are solid (ping over many packets) and which are noisy (single speed tests).
4. If it got worse, the person sets the setting back.

## 5. Wrap up

Give a short list: what changed, the before/after numbers, what to retest later (morning and evening), and
anything only the provider can fix.
