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
          +---> [Station A_i: Fast DC P(A_i), Low Amenity] ---+
          |     (Time offset: 0, Discomfort offset: w_i)       |
--- (u_i) -+                                                   +---> (v_i) --->
          |                                                   |
          +---> [Station B_i: Tuned DC P(B_i), High Amenity] -+
                (Time offset: v_i, Discomfort offset: 0)
```

1. **Highway Layout and Baseline Offsets**:
   - The corridor connects $n+1$ highway milestones: $u_1 \to u_2 \to \dots \to u_n \to \text{Destination}$.
   - Baseline driving time across all highway segments:
     $$T_0 = (n + 1) \cdot t_{\text{drive}}$$
   - Driving distance between milestones: $d_{\text{leg}} = 60.0$ km.
   - Total energy consumed across each stage leg (including spurs): $e_{\text{leg}} = 9.0$ kWh.

2. **Decoupled Vehicle and Battery Parameters**:
   - **Crucial Decoupling Property**: In multi-stage EV routing, stages can become coupled if excess energy charged at stage $i$ carries over to stage $i+1$, potentially allowing skipping or reducing charge later. To strictly decouple the stages, we select vehicle battery capacity such that **the maximum possible departure energy equals the minimum feasible departure energy**:
     $$E_{\text{usable}} \equiv E_{\text{reserve}} + e_{\text{leg}}$$
   - Concrete parameter values:
     - Usable battery capacity: $E_{\text{usable}} = 12.0$ kWh.
     - Safety reserve fraction: $\text{reserve} = 0.25 \implies E_{\text{reserve}} = 0.25 \times 12.0 = 3.0$ kWh.
     - Highway stage transit energy: $e_{\text{leg}} = 9.0$ kWh.
     - Start SoC: $s_0 = 1.00$ ($12.0$ kWh).
     - Stop threshold: $\text{stop\_threshold} = 0.35$ (so arrival at $0.25 \le 0.35$ incurs zero premature stop penalty).

3. **Spur Detour Energy Balance and Exact Reserve Arrival**:
   - Every physical station sits on a spur connected to the highway milestone:
     - Outbound spur (leaving Station $i-1$ back to highway): $\Delta e_{\text{spur,out}} = 0.2$ kWh.
     - Highway transit between milestone $i-1$ and milestone $i$: $\Delta e_{\text{hwy}} = 8.6$ kWh.
     - Inbound spur (from highway into Station $i$): $\Delta e_{\text{spur,in}} = 0.2$ kWh.
     - Total inter-station energy:
       $$e_{\text{leg}} = \Delta e_{\text{spur,out}} + \Delta e_{\text{hwy}} + \Delta e_{\text{spur,in}} = 0.2 + 8.6 + 0.2 = 9.0 \text{ kWh}$$
   - For the initial leg (Origin $\to$ Station 1): highway transit ($8.8$ kWh) + inbound spur ($0.2$ kWh) = $9.0$ kWh.
   - For the terminal leg (Station $n \to$ Destination): outbound spur ($0.2$ kWh) + highway transit ($8.8$ kWh) = $9.0$ kWh.
   - **Arrival Energy**: Upon reaching any station $i$, the battery energy is:
     $$E_{\text{arr}} = E_{\text{dep}} - e_{\text{leg}} = 12.0 - 9.0 = 3.0 \text{ kWh} = E_{\text{reserve}} \quad (\text{SoC}_{\text{arr}} = 0.25)$$
     Arrival occurs **identically at the exact safety reserve** at every single stage!

4. **Elimination of Inter-Stage Energy Coupling**:
   - **Minimum Feasible Departure**: To reach stage $i+1$ consuming $e_{\text{leg}} = 9.0$ kWh while satisfying the safety reserve $E \ge 3.0$ kWh:
     $$E_{\text{dep}} \ge E_{\text{reserve}} + e_{\text{leg}} = 3.0 + 9.0 = 12.0 \text{ kWh}$$
   - **Maximum Feasible Departure**: The vehicle cannot hold more than its battery capacity:
     $$E_{\text{dep}} \le E_{\text{usable}} = 12.0 \text{ kWh}$$
   - Combining both inequalities:
     $$\text{Minimum feasible charge} = \text{Maximum feasible charge} = 12.0 \text{ kWh} \quad (\text{SoC}_{\text{dep}} = 1.00 = 100\%)$$
   - Therefore, at every station visited, the vehicle **must charge from exactly $25\%$ to exactly $100\%$ SoC** ($\Delta E = 9.0$ kWh).
   - Under-charging ($< 9.0$ kWh) causes immediate battery death on the next leg ($E_{\text{arr}} < 3.0$ kWh, violating the safety reserve).
   - Over-charging ($> 9.0$ kWh) is physically impossible due to the 100% capacity ceiling.
   - Hence, **zero carry-over energy is physically possible between stages**. The $n$ stages are mathematically and physically decoupled!

5. **Recomputing Charger Power with CC-CV Taper**:
   In Route.ev, charging power is not constant; it follows a physics-based Constant Current - Constant Voltage (CC-CV) taper:
   - For $\text{SoC} \in [0.25, 0.80]$ (Constant Current at $P_0$):
     $$\Delta t_{\text{CC}} = \frac{E_{\text{usable}} \cdot (0.80 - 0.25)}{P_0} \times 60 = \frac{60 \cdot 12.0 \cdot 0.55}{P_0} = \frac{396.0}{P_0} \text{ min}$$
   - For $\text{SoC} \in [0.80, 1.00]$ (Constant Voltage taper $P(s) = P_0 (4.60 - 4.50s)$ down to $0.10 P_0$):
     $$\Delta t_{\text{CV}} = \frac{E_{\text{usable}}}{4.50 \cdot P_0} \ln\left(\frac{4.60 - 4.50 \times 0.80}{4.60 - 4.50 \times 1.00}\right) \times 60 = \frac{720.0 \cdot \ln(10)}{4.50 \cdot P_0} \approx \frac{368.4136}{P_0} \text{ min}$$
   - Total charging duration from $0.25$ to $1.00$ as a function of charger power $P$:
     $$t_{\text{charge}}(P) = \Delta t_{\text{CC}} + \Delta t_{\text{CV}} = \frac{K_{\text{taper}}}{P}$$
     where:
     $$K_{\text{taper}} = 60 \cdot 12.0 \cdot \left(0.55 + \frac{\ln(10)}{4.50}\right) \approx 764.413615 \text{ kW}\cdot\text{min}$$

6. **Parallel Branch Construction Using Exact Model Formulas (Long-Dwell Regime)**:
   To accommodate arbitrary non-negative integer weights $w_i \in \mathbb{Z}^+$ and values $v_i \in \mathbb{Z}^+$ (unbounded by constant limits), we place both station branches into the **long-dwell regime** ($\text{dwell} > 40$ min), where the piecewise dwell window penalty is strictly linear:
   $$\text{penalty}_{\text{window}}(\text{dwell}) = 1.50 \cdot (\text{dwell} - 40.0) \quad \text{for } \text{dwell} > 40.0$$
   Total dwell discomfort for any stop in this regime with zero arrival penalty ($\text{SoC}_{\text{arr}} = 0.25 \le 0.35$) is:
   $$D(t, A) = t \cdot (1.0 - A) + 1.50 \cdot (t - 40.0) + 5.0 = t \cdot (2.50 - A) - 55.0$$

   We construct the station parameters for stage $i$ as follows:
   - Base stage charge duration:
     $$T_{A, i} = 50.0 + w_i + 2.0 \cdot v_i > 40.0 \text{ min}$$
     $$T_{B, i} = T_{A, i} + v_i = 50.0 + w_i + 3.0 \cdot v_i > 40.0 \text{ min}$$
   - Charger powers via closed-form continuous CC-CV taper:
     $$P(A_i) = \frac{K_{\text{taper}}}{T_{A, i}}, \quad P(B_i) = \frac{K_{\text{taper}}}{T_{B, i}}$$
     yielding exact physical recharge durations $t_{\text{charge}}(A_i) = T_{A, i}$ and $t_{\text{charge}}(B_i) = T_{B, i}$.
     $$\implies \Delta T_i = T_{B, i} - T_{A, i} = v_i$$
   - Amenity scores:
     - For **Branch B (Station $B_i$)**: set $A_{B, i} = 1.0$ (luxury lounge).
       $$D(B_i) = T_{B, i} \cdot (2.50 - 1.0) - 55.0 = 1.50 \cdot T_{B, i} - 55.0 \equiv D_{B, i}$$
     - For **Branch A (Station $A_i$)**: set
       $$A_{A, i} = 1.0 - \frac{w_i + 1.50 \cdot v_i}{T_{A, i}}$$
       Because $T_{A, i} = 50.0 + w_i + 2.0 \cdot v_i > w_i + 1.50 \cdot v_i$, we have $0 < \frac{w_i + 1.50 v_i}{T_{A, i}} < 1$, ensuring $A_{A, i} \in (0.0, 1.0)$ is a strictly valid normalized amenity score!
       Evaluating discomfort for Branch A:
       $$D(A_i) = T_{A, i} \cdot (1.0 - A_{A, i}) + 1.50 \cdot T_{A, i} - 55.0 = (w_i + 1.50 \cdot v_i) + 1.50 \cdot T_{A, i} - 55.0$$
       $$= 1.50 \cdot (T_{A, i} + v_i) - 55.0 + w_i = D_{B, i} + w_i$$
       $$\implies \Delta D_i = D(A_i) - D(B_i) = w_i$$

   Thus, for arbitrary integer weights $w_i$ and values $v_i$, choosing Branch A instead of Branch B:
   - Decreases journey time by exactly $v_i$ minutes.
   - Increases journey discomfort by exactly $w_i$ discomfort-minutes.

7. **Shifted Decision Thresholds**:
   - The constant baseline offsets across all $n$ stages are:
     $$T_{\text{base}} = T_0 + \sum_{i=1}^{n} T_{A, i}$$
     $$D_{\text{base}} = \sum_{i=1}^{n} D_{B, i}$$
   - We define the **shifted decision thresholds**:
     $$D_{\text{target}} = D_{\text{base}} + W = \sum_{i=1}^{n} D_{B, i} + W$$
     $$T_{\text{target}} = T_{\text{base}} + \sum_{i=1}^{n} v_i - V^* = T_0 + \sum_{i=1}^{n} T_{A, i} + \left( \sum_{i=1}^{n} v_i - V^* \right)$$

---

### 2.3 Proof of Equivalence

#### ($\Rightarrow$) If 0/1 Knapsack has a feasible solution $S \subseteq \{1, \dots, n\}$:
Construct an EV itinerary by setting the recharge at every stage $i$ to exactly $\Delta E = 9.0$ kWh, and choosing branches as follows:
- If $i \in S$, choose **Branch A** (Station $A_i$):
  $$\text{Time contribution} = T_{A, i}, \quad \text{Discomfort contribution} = D_{B, i} + w_i$$
- If $i \notin S$, choose **Branch B** (Station $B_i$):
  $$\text{Time contribution} = T_{A, i} + v_i, \quad \text{Discomfort contribution} = D_{B, i}$$

- **Battery Feasibility**: Recharging $\Delta E = 9.0$ kWh ensures arrival SoC is exactly $0.25 = \text{reserve}$ at all stages and destination, with no battery depletion.
- **Optimality of Recharge Amount**: Charging $\Delta E = 9.0$ kWh from $E_{\text{arr}} = 3.0$ kWh brings the battery to $E_{\text{dep}} = 12.0$ kWh ($100\%$ capacity). Recharging any less violates the safety reserve ($0.25$) on the subsequent leg, and recharging any more is physically impossible due to the 100% capacity limit. Hence $\Delta E = 9.0$ kWh is the unique feasible charge amount.

Total Journey Discomfort:
$$D_{\text{total}} = \sum_{i=1}^{n} D_{B, i} + \sum_{i \in S} w_i = D_{\text{base}} + \sum_{i \in S} w_i \le D_{\text{base}} + W = D_{\text{target}}$$

Total Journey Time:
$$T_{\text{total}} = T_0 + \sum_{i=1}^{n} T_{A, i} + \sum_{i \notin S} v_i = T_{\text{base}} + \left( \sum_{i=1}^{n} v_i - \sum_{i \in S} v_i \right)$$
Since $\sum_{i \in S} v_i \ge V^*$, we have:
$$T_{\text{total}} \le T_{\text{base}} + \sum_{i=1}^{n} v_i - V^* = T_{\text{target}}$$
Thus, the EV planning itinerary satisfies both $T_{\text{total}} \le T_{\text{target}}$ and $D_{\text{total}} \le D_{\text{target}}$ while maintaining strict battery feasibility.

#### ($\Leftarrow$) If the EV routing problem has a feasible solution:
Let the feasible EV itinerary have branch choices $(b_1, \dots, b_n) \in \{A, B\}^n$ and recharge amounts $(\Delta E_1, \dots, \Delta E_n)$.
- By battery feasibility, at each stage $i$, the recharge must satisfy $\Delta E_i \ge 9.0$ kWh to avoid dropping below the safety reserve ($0.25$).
- Because $E_{\text{usable}} = 12.0$ kWh and $E_{\text{arr}} = 3.0$ kWh, $\Delta E_i \le 12.0 - 3.0 = 9.0$ kWh.
- Therefore, every feasible solution must have $\Delta E_i = 9.0$ kWh identically at every stage.
- Thus, the branch choices $(b_1, \dots, b_n)$ uniquely dictate the solution with $\Delta E_i = 9.0$ kWh.

Define the item subset:
$$S = \{i \mid b_i = A\}$$

From the comfort budget constraint $D_{\text{total}} \le D_{\text{target}}$:
$$D_{\text{base}} + \sum_{i \in S} w_i \le D_{\text{base}} + W \implies \sum_{i \in S} w_i \le W$$

From the journey time bound $T_{\text{total}} \le T_{\text{target}}$:
$$T_{\text{base}} + \sum_{i \notin S} v_i \le T_{\text{base}} + \sum_{i=1}^{n} v_i - V^*$$
$$\sum_{i=1}^{n} v_i - \sum_{i \in S} v_i \le \sum_{i=1}^{n} v_i - V^* \implies \sum_{i \in S} v_i \ge V^*$$
Thus, $S$ is a valid subset for the 0/1 Knapsack problem satisfying both the weight budget $W$ and the target value $V^*$.

### 2.4 Complexity Classification: NP-Hard vs. NP-Complete
- **Continuous / Unbounded Formulation**: In the continuous setting where journey time and battery levels are real-valued, proving membership in NP is non-trivial because solution certificates are real-valued. Hence, the general constrained problem is classified as **NP-hard**.
- **Discretized Formulation**: When battery SoC is discretized to a grid $K$ and journey time/discomfort are discretized to integer or rational values, a polynomial-length certificate (the sequence of branch choices and discrete charge levels) can be verified in polynomial time $\mathcal{O}(|V_c|)$. In this discretized setting, the decision problem belongs to NP, and being NP-hard, is **weakly NP-complete**. $\blacksquare$

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

This confirms that the problem is **weakly NP-hard**: it can be solved in pseudo-polynomial time when $D_{\max}$ is bounded by an integer budget (which is polynomial when weights are bounded by a polynomial in $n$), but has no strongly polynomial algorithm unless $\text{P} = \text{NP}$.

---

## 4. References

- **Garey, M. R., & Johnson, D. S. (1979)**. *Computers and Intractability: A Guide to the Theory of NP-Completeness*. W. H. Freeman.
- **Hansen, P. (1980)**. *Bicriterion Path Problems*. Multiple Criteria Decision Making Theory and Application, Lecture Notes in Economics and Mathematical Systems, vol 177, pp. 109–127. Springer, Berlin, Heidelberg.
