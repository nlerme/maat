# Traveling Salesman Problem

Each instance is a text file. The first line contains `n`; the next `n` lines contain an `n x n` symmetric distance matrix.

Your program receives the instance path as its only argument. It may print progress lines while it searches, but it must finish with the final parseable metric:

```text
instance characteristics
cities -> <n>
tour cities -> <n>
closed tour edges -> <n>
candidate tours with fixed start city -> <number>
distance matrix
row <i> -> <d_i0> <d_i1> ...
iteration <k> tour length -> <current_best>
final tour length -> <number>
```

The leaderboard minimizes the sum of `tour_length` over all instances. A simple exhaustive C++ reference solution is available in `sample_solution/src/main.cpp`. The originally provided random backtracking code is kept as `sample_solution/original_attached_random_backtracking.cpp` for reference, but the MAAT instance format uses explicit distance matrices.


Evaluation instances are named `tsp_<index>_<easy|medium|hard>_seed<seed>_cities<n>.txt`.
