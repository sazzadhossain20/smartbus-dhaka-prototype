"""
Illustrative corridor simulation: roadside stopping (baseline) versus the proposed
framework (stops only in off-lane bays, passengers pre-assigned to designated stops).

One kerb lane, 6 km corridor, 9 designated stops every 600 m, time step 1 s.
Bay buses leave in the order they entered (single file, no reversing).
Both scenarios use the SAME buses and the SAME passengers in each replication
(common random numbers). Passengers who would have hailed a bus at an informal roadside
point in the baseline are moved to the nearest designated stop in the framework, so total
demand is conserved.

Everything here is a modelling assumption, not Dhaka field data.
"""
import json, sys, math
import numpy as np
from multiprocessing import Pool

L = 6000.0
VMAX = 30 / 3.6          # 30 km/h urban limit
ACC = 1.0                # m/s^2
MIN_GAP = 12.0           # bumper-to-bumper spacing between buses in the lane (m)
DESIGNATED = [600.0 * k for k in range(1, 10)]
T0 = 8.0                 # fixed dwell: doors, merge into stream (s)
TP = 2.5                 # seconds per boarding or alighting passenger
BAY_OVERHEAD = 6.0       # extra seconds to pull into and merge out of a bay
ARRIVAL_WINDOW = 1800.0  # buses arrive during the first 30 minutes

DEFAULTS = dict(headway=30.0, informal_rate=2.0, bay_cap=2, board_mean=4.0, alight_mean=3.0)


def make_demand(rng, p):
    """Buses with arrival times and passenger demand; identical for both scenarios."""
    t, arrivals = 0.0, []
    while True:
        t += rng.exponential(p["headway"])
        if t > ARRIVAL_WINDOW:
            break
        arrivals.append(t)
    buses = []
    for ta in arrivals:
        base = [int(rng.poisson(p["board_mean"]) + rng.poisson(p["alight_mean"])) for _ in DESIGNATED]
        k = int(rng.poisson(p["informal_rate"] * L / 1000.0))
        informal = [(float(rng.uniform(50, L - 50)), 1 + int(rng.poisson(1.0))) for _ in range(k)]
        buses.append(dict(t_arr=ta, base=base, informal=sorted(informal)))
    return buses


def build_plan(bus, framework):
    """List of (position, n_passengers, is_designated_index or None) in travel order."""
    n = list(bus["base"])
    if framework:
        # move informal passengers to the nearest designated stop
        for x, m in bus["informal"]:
            j = min(range(len(DESIGNATED)), key=lambda i: abs(DESIGNATED[i] - x))
            n[j] += m
        return [(DESIGNATED[j], n[j], j) for j in range(len(DESIGNATED)) if n[j] > 0]
    plan = [(DESIGNATED[j], n[j], j) for j in range(len(DESIGNATED)) if n[j] > 0]
    plan += [(x, m, None) for x, m in bus["informal"]]
    return sorted(plan)


def simulate(buses, framework, overtake, bay_cap):
    plans = [build_plan(b, framework) for b in buses]
    state = [None] * len(buses)           # None until entered
    x = [0.0] * len(buses); v = [0.0] * len(buses)
    nxt = [0] * len(buses)
    rem = [0.0] * len(buses)
    mode = ['wait'] * len(buses)          # wait(not entered) run dwell_lane wait_bay dwell_bay done
    t_exit = [None] * len(buses)
    obstruct = [0.0] * len(buses)         # seconds stopped in the lane for dwelling or waiting for a bay
    stuck = [0] * len(buses)
    bay_used = [0] * len(DESIGNATED)
    bay_queue = [[] for _ in DESIGNATED]   # entry order; the front bus must leave first
    t = 0.0
    enter_ptr = 0
    active = []
    while True:
        # entry: next bus enters when the lane at x=0 is clear
        while enter_ptr < len(buses) and buses[enter_ptr]["t_arr"] <= t:
            i = enter_ptr
            clear = all(not (mode[j] in ('run', 'dwell_lane', 'wait_bay') and x[j] < MIN_GAP) for j in active)
            if not clear:
                break
            mode[i] = 'run'; x[i] = 0.0; v[i] = 0.0; active.append(i); enter_ptr += 1
        if enter_ptr >= len(buses) and not active:
            break
        in_lane = [j for j in active if mode[j] in ('run', 'dwell_lane', 'wait_bay')]
        in_lane.sort(key=lambda j: -x[j])
        # leader for each lane bus
        for idx, i in enumerate(in_lane):
            m = mode[i]
            if m == 'dwell_lane':
                rem[i] -= 1.0; obstruct[i] += 1.0
                if rem[i] <= 0: mode[i] = 'run'; nxt[i] += 1
                continue
            if m == 'wait_bay':
                obstruct[i] += 1.0
                s = plans[i][nxt[i]]; j = s[2]
                if bay_used[j] < bay_cap:
                    bay_used[j] += 1; bay_queue[j].append(i); mode[i] = 'dwell_bay'; rem[i] = T0 + TP * s[1] + BAY_OVERHEAD
                continue
            # running: follow the nearest leader in the lane
            vdes = min(VMAX, v[i] + ACC)
            gap = float('inf')
            for k in range(idx - 1, -1, -1):
                lead = in_lane[k]
                if overtake and mode[lead] in ('dwell_lane', 'wait_bay'):
                    continue            # stopped buses can be passed
                gap = x[lead] - x[i] - MIN_GAP
                break
            if gap < vdes:
                vdes = max(0.0, gap)
            tgt = plans[i][nxt[i]][0] if nxt[i] < len(plans[i]) else L
            if x[i] + vdes >= tgt:
                x[i] = tgt; v[i] = 0.0
                if nxt[i] >= len(plans[i]):
                    mode[i] = 'done'; t_exit[i] = t + 1.0
                else:
                    pos, n_p, jj = plans[i][nxt[i]]
                    dwell = T0 + TP * n_p
                    if framework and jj is not None:
                        if bay_used[jj] < bay_cap:
                            bay_used[jj] += 1; bay_queue[jj].append(i); mode[i] = 'dwell_bay'; rem[i] = dwell + BAY_OVERHEAD
                        else:
                            mode[i] = 'wait_bay'
                    else:
                        mode[i] = 'dwell_lane'; rem[i] = dwell
            else:
                x[i] += vdes; v[i] = vdes
        # buses dwelling in a bay
        for i in list(active):
            if mode[i] == 'dwell_bay':
                rem[i] -= 1.0
                if rem[i] <= 0:
                    # merge out when no moving bus is within a gap of the merge point; buses already
                    # stopped in the lane are treated as being behind the merging bus
                    jb = plans[i][nxt[i]][2]
                    if bay_queue[jb][0] != i:
                        rem[i] = 0.0            # a bus ahead in the bay has not left yet
                        continue
                    clear = all(not (mode[j] == 'run' and abs(x[j] - x[i]) < MIN_GAP)
                                for j in active if j != i)
                    stuck[i] += 1
                    if clear or overtake or stuck[i] > 30:   # 30 s fail-safe against deadlock
                        bay_used[jb] -= 1; bay_queue[jb].pop(0)
                        mode[i] = 'run'; nxt[i] += 1; rem[i] = 0.0; stuck[i] = 0
                    else:
                        rem[i] = 0.0   # keep waiting (occupies bay) until the lane is clear
        active = [j for j in active if mode[j] != 'done']
        t += 1.0
        if t > 20000:
            break
    tt = [t_exit[i] - buses[i]["t_arr"] for i in range(len(buses)) if t_exit[i] is not None]
    ob = [obstruct[i] for i in range(len(buses)) if t_exit[i] is not None]
    return float(np.mean(tt)), float(np.percentile(tt, 90)), float(np.mean(ob))


def one_rep(args):
    seed, p, bay_cap_override = args
    rng = np.random.default_rng(seed)
    buses = make_demand(rng, p)
    cap = p["bay_cap"] if bay_cap_override is None else bay_cap_override
    out = {}
    for ot in (False, True):
        for fw in (False, True):
            out[(ot, fw)] = simulate(buses, fw, ot, cap)
    return out


def run_setting(p, reps, seed0=1000):
    with Pool() as pool:
        res = pool.map(one_rep, [(seed0 + r, p, None) for r in range(reps)])
    summary = {}
    for ot in (False, True):
        for metric, name in enumerate(("mean_tt", "p90_tt", "obstruct")):
            base = np.array([r[(ot, False)][metric] for r in res])
            fram = np.array([r[(ot, True)][metric] for r in res])
            d = base - fram
            se = d.std(ddof=1) / math.sqrt(len(d))
            summary[f"{'overtake' if ot else 'noovertake'}_{name}"] = dict(
                base=float(base.mean()), fw=float(fram.mean()), diff=float(d.mean()), ci=float(1.96 * se),
                base_sd=float(base.std(ddof=1)), fw_sd=float(fram.std(ddof=1)))
    return summary


if __name__ == "__main__":
    reps_main = int(sys.argv[1]) if len(sys.argv) > 1 else 30
    reps_sens = int(sys.argv[2]) if len(sys.argv) > 2 else 12
    out = {"params": DEFAULTS, "reps_main": reps_main, "reps_sens": reps_sens}
    out["main"] = run_setting(DEFAULTS, reps_main)
    print("main done", flush=True)
    sens = {}
    for h in (15, 20, 30, 45, 60, 90):
        p = dict(DEFAULTS, headway=float(h)); sens[f"headway={h}"] = run_setting(p, reps_sens)
        print("headway", h, flush=True)
    for r in (0, 1, 2, 4):
        p = dict(DEFAULTS, informal_rate=float(r)); sens[f"informal={r}"] = run_setting(p, reps_sens)
        print("informal", r, flush=True)
    for c in (1, 2, 3):
        p = dict(DEFAULTS, bay_cap=c); sens[f"bay={c}"] = run_setting(p, reps_sens)
        print("bay", c, flush=True)
    out["sens"] = sens
    json.dump(out, open("sim_results.json", "w"), indent=2)
    print("saved sim_results.json")
