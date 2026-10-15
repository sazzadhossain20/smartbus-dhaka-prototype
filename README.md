# SmartBus Dhaka — Proof-of-Concept Prototype

Proof-of-concept prototype for the paper **"Centralized Digital Ticketing Framework for Mitigating Random Bus Stopping in Dhaka."**

This is a single-page, self-contained demo (`index.html`, no build step, no backend) that simulates the core coordination logic the paper proposes:

- **Passenger view** — pick a route, select origin/destination, browse available buses, choose and book a seat labeled in the row-and-number convention used on Bangladeshi buses (A1, A2, B1, B2, ...), deducted from an in-app wallet balance, and receive a QR-style ticket.
- **Driver view** — route-locked dashboard, next-stop boarding/alighting counts, live speed reading, manual seat release, passenger-violation reporting.
- **Control Room view** — live map showing three separate demo routes as distinct lanes, simulated GPS movement, route-deviation alert simulation, continuous overspeed detection (flagged separately from route-permit alerts, against a 30 km/h demo limit), driver contact lookup, passenger-report queue.

All three views share one in-memory state, so a booking made in the Passenger view is immediately reflected in the Driver and Control Room views.

## What is simulated vs. real

This prototype validates the **booking, seat-locking, and route-coordination logic** described in the paper using synthetic data (4 demo buses on 3 seven-stop routes, no real passengers or real Dhaka traffic data). It does **not** include:
- Real payment gateway integration (bKash/Nagad/Rocket/card) — the wallet is a fixed Tk 500 demo balance with no top-up flow
- Real GPS hardware — bus movement is simulated on a timer
- Real NID verification — not implemented; the QR on a ticket is a decorative pattern, and the SMS confirmation is shown as an on-screen log
- Passenger-side seat release and passenger-to-driver reports (only the driver can release seats or file reports here)

## Running it

Just open `index.html` in a browser. No dependencies, no server required.

## Testing

`test_prototype.js` runs 17 headless checks on the booking, seat-release and alert logic (seat uniqueness, capacity, wallet accounting, destination alert and release timing, overspeed and route-deviation alerts, seat labels). The prototype is single-threaded, so the tests do not cover truly simultaneous requests.

```
node test_prototype.js index.html
```

## Corridor simulation

`simulation/corridor_sim.py` compares roadside stopping with the bay-and-booking design on a simulated 6 km corridor (requires Python 3 and numpy). Parameters are assumptions, not Dhaka field data. `simulation/sim_results.json` holds the results reported in the paper.

```
python3 simulation/corridor_sim.py 30 12
```

## Paper

Md. Sazzad Hossain, Walieu Hossain Chowdhury, Ariful Haque, and Mahdi Hasin Fahim, "Centralized Digital Ticketing Framework for Mitigating Random Bus Stopping in Dhaka" (manuscript in preparation).
