# NP-Hardness of Constrained EV Routing with Dwell Comfort

## 1. Problem Formulation & Classification

In **Route.ev**, the EV itinerary optimization problem balances two conflicting criteria:
1. **Total Journey Time**: $T = T_{\text{drive}} + T_{\text{charge}}$ (in minutes).
2. **Total Traveler Discomfort**: $D = \sum_{k} D_{\text{dwell}}(t_k, \text{amenities}_k, \text{SoC}_k)$ (in discomfort-minutes).

### 1.1 The Weighted-Sum (Supported Pareto) Problem vs. The Constrained Problem
- **The Scalar Weighted-Sum Problem**:
  $$\min \quad J(\lambda) = T + \lambda \cdot D$$
  subject to battery capacity and safety reserve constraints.
  As proven in `complexity.md`, this problem is **polynomial-time solvable** for any fixed $\lambda \ge 0$ via Dijkstra on the discretized state space $(u_{\text{layer}}, s)$, executing in $\mathcal{O}((|E_c|K + |V_c|K^2)\log(|V_c|K))$ time. It identifies all **supported Pareto-optimal trade-offs** on the convex hull of the objective space.

- **The Constrained (Budgeted) Problem**:
  $$\min \quad T \quad \text{subject to} \quad D \le W_{\max}, \quad \text{SoC}(t) \ge \text{reserve} \quad \forall t$$
  or the equivalent **Decision Problem**:
  Does there exist a feasible trip itinerary such that:
  $$T \le T_{\text{target}} \quad \text{and} \quad D \le D_{\text{target}} \quad \text{and} \quad \text{SoC}(t) \ge \text{reserve} \quad \forall t \text{ ?}$$

**Theorem 1**: The Constrained EV Journey Optimization Problem with Comfort Budget is **NP-hard** (specifically, weakly NP-hard).

---

## 2. Formal Proof of NP-Hardness via Reduction from 0/1 Knapsack

We prove NP-hardness by polynomial-time Karp reduction from the classical **0/1 Knapsack Problem**, a known NP-complete decision problem (Garey & Johnson, 1979).

### 2.1 The 0/1 Knapsack Problem
Given:
- A set of $n$ items $\{1, 2, \dots, n\}$.
- For each item $i$, an integer weight $w_i \in \mathbb{Z}^+$ and an integer value $v_i \in \mathbb{Z}^+$.
- A maximum weight budget $W \in \mathbb{Z}^+$.
- A target total value $V^* \in \mathbb{Z}^+$.

**Question**: Does there exist a subset $S \subseteq \{1, \dots, n\}$ such that:
$$\sum_{i \in S} w_i \le W \quad \text{and} \quad \sum_{i \in S} v_i \ge V^* \text{ ?}$$

---

### 2.2 Gadget Construction: Real Station Parameters on Parallel Branches

Given an arbitrary instance of 0/1 Knapsack, we construct an EV road corridor with $n$ sequential decision stages. At each stage $i \in \{1, \dots, n\}$, the corridor splits into two parallel branches hosting real charging stations:

```
          +---> [Station A_i: Fast DC 60kW, Low Amenity] ---+
          |     (Time offset: 0, Discomfort offset: w_i)     |
--- (u_i) -+                                                 +---> (v_i) --->
          |                                                 |
          +---> [Station B_i: AC 22kW / Detour, High Amenity] +
                (Time offset: v_i, Discomfort offset: 0)
```

1. **Highway Layout and Baseline Offsets**:
   - The corridor connects $n+1$ highway milestones: $u_1 \to u_2 \to \dots \to u_n \to \text{Destination}$.
   - Baseline driving time across all highway segments:
     $$T_0 = (n + 1) \cdot t_{\text{drive}}$$
   - Driving distance between milestones: $d_{\text{leg}} = 60.0$ km.
   - Highway driving energy consumption: $e_{\text{leg}} = 9.0$ kWh per leg.

2. **Vehicle and Spur Parameters**:
   - Usable battery capacity: $E_{\text{usable}} = 30.0$ kWh.
   - Safety reserve: $\text{reserve} = 0.10$ ($3.0$ kWh).
   - Start SoC: $s_0 = 0.50$ ($15.0$ kWh).
   - Stop threshold: $\text{stop\_threshold} = 0.35$ (so arrival at $0.20$ incurs $0$ premature penalty).
   - Highway leg consumption: $e_{\text{hwy}} = 8.8$ kWh.
   - Station spur detour (inbound and outbound): $e_{\text{spur\_in}} = e_{\text{spur\_out}} = 0.2$ kWh.
   - Total energy consumed between stages: $e_{\text{total}} = e_{\text{hwy}} + e_{\text{spur\_in}} = 9.0$ kWh.
   - Target recharge amount at each stage $i$: $\Delta E = 9.0$ kWh.

3. **Scaling the Knapsack Instance**:
   Without loss of generality, we scale the Knapsack instance so that for all items $i$, $w_i \in [0, 20]$ and $v_i \in [0, 20]$ (multiplying budgets $W$ and $V^*$ by the identical scaling factor).

4. **Parallel Branch Realization using Model Formulas**:
   In Route.ev, dwell discomfort and charge time are computed by:
   $$t_{\text{charge}} = \frac{\Delta E}{P_{\text{charger}}} \times 60 \text{ minutes}$$
   $$D_{\text{dwell}} = 5.0 + t_{\text{charge}} \cdot (1.0 - \text{amenity\_score}) + \text{WindowPenalty} + \text{PrematurePenalty}$$
   When $t_{\text{charge}} \in [20, 40]$ minutes, $\text{WindowPenalty} = 0.0$.
   When $\text{SoC}_{\text{arr}} = 0.20 \le \text{stop\_threshold} = 0.35$, $\text{PrematurePenalty} = 0.0$.
   Therefore, for any dwell within $[20, 40]$ min:
   $$D_{\text{dwell}} = 5.0 + t_{\text{charge}} \cdot (1.0 - \text{amenity\_score})$$

   - **Branch A (Station $A_i$ — Corresponds to $i \in S$, "Take Item $i$")**:
     - **Power**: Fixed at $P(A_i) = 27.0$ kW $\implies t_{\text{charge}} = \frac{9.0}{27.0} \times 60 = 20.0$ minutes ($t_0 = 20.0$).
     - **Amenity Score**: Set to $A_i = 1.0 - \frac{w_i}{20.0} \in [0.0, 1.0]$.
     - **Time Contribution**:
       $$\text{Time}(A_i) = t_0 + 0 = 20.0 \text{ min}$$
     - **Discomfort Contribution**:
       $$\text{Discomfort}(A_i) = 5.0 + 20.0 \cdot \left(1.0 - \left(1.0 - \frac{w_i}{20.0}\right)\right) = 5.0 + w_i = d_0 + w_i$$
       where base discomfort $d_0 = 5.0$.

   - **Branch B (Station $B_i$ — Corresponds to $i \notin S$, "Leave Item $i$")**:
     - **Power**: Set to $P(B_i) = \frac{9.0 \text{ kWh}}{(20.0 + v_i)/60} \text{ kW} \implies t_{\text{charge}} = 20.0 + v_i = t_0 + v_i$.
       Since $v_i \in [0, 20]$, $t_{\text{charge}} \in [20, 40]$ minutes, guaranteeing $\text{WindowPenalty} = 0.0$.
     - **Amenity Score**: Set to premium luxury lounge $A_i = 1.0 \implies (1.0 - A_i) = 0.0$.
     - **Time Contribution**:
       $$\text{Time}(B_i) = t_0 + v_i = 20.0 + v_i \text{ min}$$
     - **Discomfort Contribution**:
       $$\text{Discomfort}(B_i) = 5.0 + (20.0 + v_i) \cdot (1.0 - 1.0) = 5.0 + 0 = d_0 + 0$$

5. **Strict Battery Feasibility on Both Branches (Including Spur Detours)**:
   - **Arrival SoC**:
     At every stage $i$, the vehicle drives the highway leg ($8.8$ kWh) and inbound spur ($0.2$ kWh):
     $$\text{SoC}_{\text{arr}} = \frac{E_{\text{start}} - (e_{\text{hwy}} + e_{\text{spur\_in}})}{E_{\text{usable}}} = \frac{15.0 - (8.8 + 0.2)}{30.0} = \frac{6.0 \text{ kWh}}{30.0 \text{ kWh}} = 0.20$$
     Since $0.20 > \text{reserve} = 0.10$, the vehicle arrives strictly above the safety reserve ($6.0 \text{ kWh} > 3.0 \text{ kWh}$) on both branches.
   - **Departure SoC**:
     Both branches recharge exactly $9.0$ kWh, departing at:
     $$\text{SoC}_{\text{dep}} = \frac{6.0 + 9.0}{30.0} = 0.50 \le 1.0$$
     strictly below the 100% capacity ceiling without clamping distortion.
   - Departing via the outbound spur ($0.2$ kWh) and the subsequent highway leg ($8.8$ kWh) consumes exactly $9.0$ kWh, arriving at stage $i+1$ with $\text{SoC}_{\text{arr}} = 0.20$.
   - Therefore, **both Branch A and Branch B are physically feasible at all stages**, guaranteeing that routing choices depend strictly on the time vs. discomfort budget trade-off.

6. **Shifted Thresholds**:
   - The constant unavoidable baseline offsets across all $n$ stages are:
     $$T_{\text{base}} = T_0 + n \cdot t_0 = T_0 + 20n$$
     $$D_{\text{base}} = n \cdot d_0 = 5n$$
   - We define the **shifted decision thresholds**:
     $$D_{\text{target}} = D_{\text{base}} + W = 5n + W$$
     $$T_{\text{target}} = T_{\text{base}} + \sum_{i=1}^{n} v_i - V^* = T_0 + 20n + \left( \sum_{i=1}^{n} v_i - V^* \right)$$

---

### 2.3 Proof of Equivalence

#### ($\Rightarrow$) If 0/1 Knapsack has a feasible solution $S \subseteq \{1, \dots, n\}$:
For each stage $i \in \{1, \dots, n\}$:
- If $i \in S$, choose **Branch A** (Station $A_i$):
  $$\text{Time contribution} = t_0, \quad \text{Discomfort contribution} = d_0 + w_i$$
- If $i \notin S$, choose **Branch B** (Station $B_i$):
  $$\text{Time contribution} = t_0 + v_i, \quad \text{Discomfort contribution} = d_0$$

Total Journey Discomfort:
$$D_{\text{total}} = \sum_{i=1}^{n} d_0 + \sum_{i \in S} w_i = 5n + \sum_{i \in S} w_i \le 5n + W = D_{\text{target}}$$

Total Journey Time:
$$T_{\text{total}} = T_0 + \sum_{i=1}^{n} t_0 + \sum_{i \notin S} v_i = T_{\text{base}} + \left( \sum_{i=1}^{n} v_i - \sum_{i \in S} v_i \right)$$
Since $\sum_{i \in S} v_i \ge V^*$, we have:
$$T_{\text{total}} \le T_{\text{base}} + \sum_{i=1}^{n} v_i - V^* = T_{\text{target}}$$
Thus, the EV planning itinerary satisfies both $T_{\text{total}} \le T_{\text{target}}$ and $D_{\text{total}} \le D_{\text{target}}$ while maintaining strict battery feasibility.

#### ($\Leftarrow$) If the EV routing problem has a feasible solution:
Let $(b_1, \dots, b_n) \in \{A, B\}^n$ be the sequence of branch choices at the $n$ parallel stages. Define:
$$S = \{i \mid b_i = A\}$$

From the comfort budget constraint $D_{\text{total}} \le D_{\text{target}}$:
$$5n + \sum_{i \in S} w_i \le 5n + W \implies \sum_{i \in S} w_i \le W$$

From the journey time bound $T_{\text{total}} \le T_{\text{target}}$:
$$T_{\text{base}} + \sum_{i \notin S} v_i \le T_{\text{base}} + \sum_{i=1}^{n} v_i - V^*$$
$$\sum_{i=1}^{n} v_i - \sum_{i \in S} v_i \le \sum_{i=1}^{n} v_i - V^* \implies \sum_{i \in S} v_i \ge V^*$$
Thus, $S$ is a valid subset for the 0/1 Knapsack problem satisfying both the weight budget $W$ and the target value $V^*$.

### 2.4 Complexity Classification: NP-Hard vs. NP-Complete
- **Continuous Formulation**: In the continuous setting where journey time and battery levels are real-valued, proving membership in NP is non-trivial because solution certificates are real-valued. Hence, the general constrained problem is classified as **NP-hard**.
- **Discretized Formulation**: When battery SoC is discretized to a grid $K$ and journey time/discomfort are discretized to integer or rational values, a polynomial-length certificate (the sequence of branch choices and discrete charge levels) can be verified in polynomial time $\mathcal{O}(|V_c|)$. In this discretized setting, the decision problem is **weakly NP-complete**. $\blacksquare$

---

## 3. Weak NP-Hardness and Pseudo-Polynomial Dynamic Programming

Because the reduction is from 0/1 Knapsack (which is weakly NP-hard, admitting pseudo-polynomial time solutions via dynamic programming), we analyze the pseudo-polynomial algorithm for the constrained problem.

### 3.1 Pseudo-Polynomial DP Formulation
If discomfort values are integers bounded by $D_{\max} \in \mathbb{Z}^+$:
- Define DP state:
  $$\text{dist}[v, s, d] = \text{minimum travel time to reach node } v \text{ with SoC level } s \text{ and cumulative discomfort } d$$
  where $v \in V_c$, $s \in \{0, \dots, K\}$, and $d \in \{0, \dots, D_{\max}\}$.

- **State Space Size**:
  $$|S_{\text{pseudo}}| = \mathcal{O}(|V_c| \cdot K \cdot D_{\max})$$

- **Transitions**:
  - Driving: $(u, s, d) \to (v, s', d)$ with $\Delta T = t_{\text{drive}}$.
  - Charging: $(u, s, d) \to (u, s_{\text{dep}}, d + \Delta d)$ with $\Delta T = t_{\text{charge}}(s, s_{\text{dep}})$.

- **Asymptotic Complexity**:
  $$\text{Time: } \mathcal{O}\left( (|E_c| \cdot K + |V_c| \cdot K^2) \cdot D_{\max} \right)$$
  $$\text{Space: } \mathcal{O}(|V_c| \cdot K \cdot D_{\max})$$

This confirms that the problem is **weakly NP-hard**: it can be solved in pseudo-polynomial time when $D_{\max}$ is bounded by an integer budget, but has no strongly polynomial algorithm unless $\text{P} = \text{NP}$.

---

## 4. References

- **Garey, M. R., & Johnson, D. S. (1979)**. *Computers and Intractability: A Guide to the Theory of NP-Completeness*. W. H. Freeman.
- **Hansen, P. (1980)**. *Bicriterion Path Problems*. Multiple Criteria Decision Making Theory and Application.
- **Warburton, A. (1987)**. *Approximation of Pareto optima in multiple-objective, shortest-path problems*. Operations Research.
