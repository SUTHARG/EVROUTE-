# NP-Hardness of Constrained EV Routing with Dwell Comfort

## 1. Problem Formulation & Classification

In **Route.ev**, the EV itinerary optimization problem involves two conflicting criteria:
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
  $$T \le T_{\text{target}} \quad \text{and} \quad D \le W_{\max} \quad \text{and} \quad \text{SoC}(t) \ge \text{reserve}?$$

**Theorem 1**: The Constrained EV Journey Optimization Problem with Comfort Budget is **NP-hard** (specifically, weakly NP-hard).

---

## 2. Formal Proof of NP-Hardness via Reduction from 0/1 Knapsack

We prove NP-hardness by polynomial-time Karp reduction from the classical **0/1 Knapsack Problem**, a known NP-complete decision problem.

### 2.1 The 0/1 Knapsack Problem
Given:
- A set of $n$ items $\{1, 2, \dots, n\}$.
- For each item $i$, an integer weight $w_i \in \mathbb{Z}^+$ and an integer value $v_i \in \mathbb{Z}^+$.
- A maximum weight capacity $W \in \mathbb{Z}^+$.
- A target total value $V^* \in \mathbb{Z}^+$.

**Question**: Does there exist a subset $S \subseteq \{1, \dots, n\}$ such that:
$$\sum_{i \in S} w_i \le W \quad \text{and} \quad \sum_{i \in S} v_i \ge V^* \text{ ?}$$

---

### 2.2 Gadget Construction

Given an arbitrary instance of 0/1 Knapsack, we construct an EV corridor network with $n$ sequential charging stops as follows:

```
[Source] ===> [Charger 1] ===> [Charger 2] ===> ... ===> [Charger n] ===> [Destination]
```

1. **Corridor Structure**:
   - The road network consists of $n+1$ equidistant road segments:
     $$v_0 (\text{Source}) \to v_1 \to v_2 \to \dots \to v_n \to v_{n+1} (\text{Destination})$$
   - At each milestone node $v_i$ ($1 \le i \le n$), there is a charging station with battery charger $i$.
   - Driving time on each segment is a constant $t_{\text{drive}} = 60$ minutes.
   - Energy consumed on each segment between consecutive stations is $e_{\text{segment}} = 10.0$ kWh.

2. **Vehicle Parameters**:
   - Total battery capacity $B = 30.0$ kWh.
   - Usable battery fraction = $1.0$ ($30.0$ kWh usable).
   - Safety reserve fraction = $0.10$ ($3.0$ kWh reserve).
   - Start SoC = $0.50$ ($15.0$ kWh).

3. **Branch Gadget at Station $i$**:
   At each station $i$, the driver must choose between two distinct charging/dwell policies:

   - **Branch A ("Take Item $i$" into Knapsack)**:
     - The driver executes a rushed, minimal charge stop or skips amenities.
     - Extra dwell / charging time added: $\Delta T_i = 0$.
     - Discomfort incurred: $\Delta D_i = w_i$ (due to rushed dwell $< 20$ min or lack of amenities).
     - Battery recharge: vehicle recharges by $10.0$ kWh (restoring SoC to safely traverse to the next station).

   - **Branch B ("Leave Item $i$" out of Knapsack)**:
     - The driver takes a relaxed, extended comfort break with high amenities.
     - Extra dwell / charging time added: $\Delta T_i = v_i$.
     - Discomfort incurred: $\Delta D_i = 0$ (inside the ideal $[20, 40]$ min dwell sweet spot at a full-amenity charger).
     - Battery recharge: vehicle recharges by $10.0$ kWh (restoring SoC to safely traverse to the next station).

4. **Battery Feasibility on Both Branches**:
   - On both branches, the vehicle arrives at station $i$ with $15.0 - 10.0 = 5.0$ kWh, which is strictly above the $3.0$ kWh reserve ($\text{SoC} = 0.167 > 0.10$).
   - On both branches, the vehicle recharges by $10.0$ kWh back to $15.0$ kWh ($50\%$ SoC), comfortably below the $30.0$ kWh ceiling ($100\%$ clamping).
   - Hence, **both Branch A and Branch B are physically feasible for every item $i$**, ensuring the decision is unconstrained by battery failure and depends purely on the time vs. discomfort trade-off.

5. **Decision Targets**:
   - Set total discomfort budget:
     $$D_{\max} = W$$
   - Set maximum allowable total journey time:
     $$T_{\text{target}} = (n + 1) \cdot t_{\text{drive}} + \sum_{i=1}^{n} v_i - V^*$$

---

### 2.3 Proof of Equivalence

#### ($\Rightarrow$) If the Knapsack instance has a solution $S$:
For each item $i \in \{1, \dots, n\}$:
- If $i \in S$, select **Branch A** at station $i$:
  $$\Delta D_i = w_i, \quad \Delta T_i = 0$$
- If $i \notin S$, select **Branch B** at station $i$:
  $$\Delta D_i = 0, \quad \Delta T_i = v_i$$

Total Discomfort:
$$D_{\text{total}} = \sum_{i \in S} w_i + \sum_{i \notin S} 0 = \sum_{i \in S} w_i \le W = D_{\max}$$

Total Journey Time:
$$T_{\text{total}} = (n + 1) \cdot t_{\text{drive}} + \sum_{i \notin S} v_i = (n + 1) \cdot t_{\text{drive}} + \left( \sum_{i=1}^{n} v_i - \sum_{i \in S} v_i \right)$$
Since $\sum_{i \in S} v_i \ge V^*$:
$$T_{\text{total}} \le (n + 1) \cdot t_{\text{drive}} + \sum_{i=1}^{n} v_i - V^* = T_{\text{target}}$$
Thus, the EV planning problem has a feasible solution satisfying both thresholds.

#### ($\Leftarrow$) If the EV planning problem has a feasible solution:
Let $(b_1, \dots, b_n) \in \{A, B\}^n$ be the sequence of branch choices at the $n$ stations. Define:
$$S = \{i \mid b_i = A\}$$

Because the plan satisfies the discomfort budget $D_{\text{total}} \le D_{\max} = W$:
$$\sum_{i \in S} w_i \le W$$

Because the plan satisfies the time bound $T_{\text{total}} \le T_{\text{target}}$:
$$(n + 1) \cdot t_{\text{drive}} + \sum_{i \notin S} v_i \le (n + 1) \cdot t_{\text{drive}} + \sum_{i=1}^{n} v_i - V^*$$
$$\sum_{i=1}^{n} v_i - \sum_{i \in S} v_i \le \sum_{i=1}^{n} v_i - V^* \implies \sum_{i \in S} v_i \ge V^*$$
Thus, $S$ is a valid subset for the 0/1 Knapsack problem.

Since the reduction runs in $\mathcal{O}(n)$ time and 0/1 Knapsack is NP-complete, **the Constrained EV Journey Optimization Problem is NP-hard**. $\blacksquare$

---

## 3. Weak NP-Hardness and Pseudo-Polynomial Dynamic Programming

Because the reduction is from 0/1 Knapsack (which is weakly NP-hard, admitting pseudo-polynomial time solutions when input numbers are represented in unary), we analyze the corresponding pseudo-polynomial algorithm for the constrained EV routing problem.

### 3.1 Pseudo-Polynomial DP Formulation
If traveler discomfort values are non-negative integers bounded by $D_{\max} \in \mathbb{Z}^+$:
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

This confirms that the problem is **weakly NP-hard**: it can be solved in pseudo-polynomial time when $D_{\max}$ is bounded, but has no polynomial-time algorithm when weights are arbitrary unless $\text{P} = \text{NP}$.
