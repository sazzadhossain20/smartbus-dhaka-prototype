// Headless tests for the SmartBus prototype logic (index.html).
// Run: node test_prototype.js [path-to-index.html]
const fs = require("fs");
const file = process.argv[2] || "index.html";
const html = fs.readFileSync(file, "utf8");
const script = html.split("<script>")[1].split("</script>")[0];

// deterministic RNG so results are reproducible
function mulberry32(a) { return function () { a |= 0; a = (a + 0x6D2B79F5) | 0; let t = Math.imul(a ^ (a >>> 15), 1 | a); t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t; return ((t ^ (t >>> 14)) >>> 0) / 4294967296; }; }
const rng = mulberry32(12345);
Math.random = rng;

const stubEl = () => ({ style: {}, innerHTML: "", textContent: "", querySelectorAll: () => [], set onclick(f) {}, set onchange(f) {} });
const document = { getElementById: () => stubEl(), querySelectorAll: () => [] };
const win = {};
let tickFn = null;
const setIntervalStub = (fn) => { tickFn = fn; return 1; };
const noop = () => {};
const toasts = [];

const factory = new Function("document", "window", "setInterval", "setTimeout", "clearTimeout",
  script + "\nreturn {state, bookSeat, releaseSeat, toggleBusFault, reportPassenger, seatLabel, fareFor, stopsOf, routeOf, renderControl, SPEED_LIMIT, SEATS_PER_BUS, FARE_PER_STOP, ROUTES};");
const api = factory(document, win, setIntervalStub, noop, noop);
const { state, bookSeat, releaseSeat, toggleBusFault, reportPassenger, seatLabel, fareFor, stopsOf, renderControl, SPEED_LIMIT, SEATS_PER_BUS } = api;

let pass = 0, fail = 0;
const results = [];
function check(name, ok, detail) {
  if (ok) pass++; else fail++;
  results.push({ name, ok, detail });
  console.log((ok ? "PASS  " : "FAIL  ") + name + (detail ? "  (" + detail + ")" : ""));
}
const bus = (id) => state.buses.find((b) => b.id === id);
const booked = (b) => b.seats.filter((s) => s.status === "booked").length;

// ---- T1: seat uniqueness and capacity under many random bookings ----
state.wallet = 1e6;
let attempts = 0, ok = 0, sumFare = 0, dup = false, overCap = false;
const w0 = state.wallet;
for (let i = 0; i < 400; i++) {
  const b = state.buses[Math.floor(rng() * state.buses.length)];
  const n = stopsOf(b).length;
  const from = Math.floor(rng() * n); let to = Math.floor(rng() * n); if (to === from) to = (from + 1) % n;
  const before = state.tickets.length; const wBefore = state.wallet;
  bookSeat(b.id, from, to); attempts++;
  if (state.tickets.length === before + 1) { ok++; sumFare += wBefore - state.wallet; }
  state.tickets.length = 0;   // emulate many different accounts: the 2-ticket rule is per account, tested in T4
  const ids = b.seats.filter((s) => s.ticketId).map((s) => s.ticketId);
  if (new Set(ids).size !== ids.length) dup = true;
  if (booked(b) > SEATS_PER_BUS) overCap = true;
}
check("T1a no seat is assigned to two tickets", !dup, attempts + " booking attempts");
check("T1b booked seats never exceed bus capacity", !overCap, "capacity " + SEATS_PER_BUS);
check("T1c wallet debited exactly the sum of fares", Math.abs((w0 - state.wallet) - sumFare) < 1e-9, "debited " + (w0 - state.wallet) + ", expected " + sumFare);
check("T1d every bus can be filled to capacity by bookings", state.buses.every((b) => booked(b) === SEATS_PER_BUS), ok + " successful bookings out of " + attempts + " attempts");
// a full bus must reject the next booking
{ const wb = state.wallet; const nb = booked(bus(2)); bookSeat(2, 0, 3);
  check("T1e a full bus rejects further bookings and charges nothing", booked(bus(2)) === nb && state.wallet === wb); }

// reset state for next tests
function resetBus(b) { b.seats.forEach((s) => { s.status = "empty"; s.toIdx = null; s.ticketId = null; }); }
state.buses.forEach(resetBus); state.tickets.length = 0;

// ---- T2: insufficient balance ----
state.wallet = 3;
let tb = state.tickets.length, bb = booked(bus(1));
bookSeat(1, 0, 3);   // fare 15 > 3
check("T2 insufficient wallet balance rejects booking", state.tickets.length === tb && booked(bus(1)) === bb && state.wallet === 3);

// ---- T3: same-stop booking must be rejected by the booking logic itself ----
state.wallet = 500; tb = state.tickets.length;
bookSeat(1, 2, 2);
check("T3 booking with identical origin and destination is rejected", state.tickets.length === tb, "tickets before " + tb + ", after " + state.tickets.length);
if (state.tickets.length > tb) { const t = state.tickets[state.tickets.length - 1]; releaseSeat(t.busId, t.seatId, true); }

// ---- T4: two-ticket limit per account per bus (design rule in Section 4.3) ----
state.buses.forEach(resetBus); state.tickets.length = 0; state.wallet = 500;
for (let i = 0; i < 3; i++) bookSeat(1, 0, 3);
const mine = state.tickets.filter((t) => t.busId === 1).length;
check("T4 account holds at most 2 tickets on one bus", mine <= 2, mine + " tickets accepted");

// ---- T5: manual seat release frees the seat and removes the ticket ----
state.buses.forEach(resetBus); state.tickets.length = 0; state.wallet = 500;
bookSeat(1, 0, 4);
const t5 = state.tickets[0];
releaseSeat(1, t5.seatId, false);
const s5 = bus(1).seats.find((s) => s.id === t5.seatId);
check("T5 manual release empties the seat and removes the ticket", s5.status === "empty" && !state.tickets.find((t) => t.id === t5.id));

// ---- T6: destination alert one stop before, release on arrival ----
state.buses.forEach(resetBus); state.tickets.length = 0; state.wallet = 500;
const b1 = bus(1); b1.posIdx = 0; b1.dir = 1;
bookSeat(1, 0, 4);
const tk = state.tickets[0];
let notifyTick = null, releaseTick = null, arriveTick = null;
for (let k = 1; k <= 40; k++) {
  tickFn();
  if (arriveTick === null && b1.posIdx === 4) arriveTick = k;
  if (notifyTick === null && tk.notified) notifyTick = k;
  if (releaseTick === null && !state.tickets.find((t) => t.id === tk.id)) releaseTick = k;
}
check("T6a passenger alerted when the bus is one stop before the destination", notifyTick !== null && arriveTick !== null && notifyTick === arriveTick - 1, "alert tick " + notifyTick + ", arrival tick " + arriveTick);
check("T6b seat released when the bus reaches the destination", releaseTick !== null && arriveTick !== null && releaseTick === arriveTick, "release tick " + releaseTick + ", arrival tick " + arriveTick);

// ---- T7: overspeed alerts ----
state.buses.forEach((b) => { b.routeStatus = "on-route"; });
const speeds = [29, 30, 31, 45];
state.buses.forEach((b, i) => { b.speed = speeds[i]; });
const sect = (htmlStr, a, z) => htmlStr.split(a)[1].split(z)[0];
let ctl = renderControl();
let over = sect(ctl, "OVERSPEED ALERTS", "PASSENGER REPORTS");
const flagged = state.buses.filter((b) => over.includes("Bus " + b.number + " ")).map((b) => b.speed);
check("T7a only buses above the limit appear in the overspeed list (29 and 30 km/h excluded)", JSON.stringify(flagged) === JSON.stringify([31, 45]), "flagged speeds " + JSON.stringify(flagged));

// ---- T8: a bus that is both off-route and speeding appears in both alert lists ----
toggleBusFault(4);  // bus 877, speed 45, now off-route
ctl = renderControl();
const routeSec = sect(ctl, "ROUTE ALERTS", "OVERSPEED ALERTS");
over = sect(ctl, "OVERSPEED ALERTS", "PASSENGER REPORTS");
check("T8a off-route bus appears in route alerts", routeSec.includes("Bus 877"));
check("T8b same bus, still speeding, also appears in overspeed alerts", over.includes("Bus 877"));
toggleBusFault(4);
check("T8c clearing the deviation removes the route alert", !sect(renderControl(), "ROUTE ALERTS", "OVERSPEED ALERTS").includes("Bus 877"));

// ---- T9: passenger report reaches the control room ----
reportPassenger(2);
check("T9 driver report appears in the control room queue", sect(renderControl(), "PASSENGER REPORTS", "SELECTED BUS").includes("Bus 341"));

// ---- T10: seat label convention ----
const labels = Array.from({ length: 16 }, (_, i) => seatLabel(i + 1)).join(",");
check("T10 seat labels follow the A1-D4 convention", labels === "A1,A2,A3,A4,B1,B2,B3,B4,C1,C2,C3,C4,D1,D2,D3,D4", labels);

console.log("\n" + pass + " passed, " + fail + " failed");
fs.writeFileSync("test_results.json", JSON.stringify({ file, pass, fail, results }, null, 2));
process.exit(fail ? 1 : 0);
