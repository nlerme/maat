#include <algorithm>
#include <cstdlib>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <limits>
#include <numeric>
#include <random>
#include <vector>

static unsigned long long candidate_tours_with_fixed_start(int n) {
    unsigned long long result = 1;
    for (int k = 2; k <= n - 1; ++k) {
        result *= static_cast<unsigned long long>(k);
    }
    return result;
}

static double tour_length(const std::vector<int> &tour, const std::vector<std::vector<double>> &d) {
    double length = 0.0;
    const int n = static_cast<int>(tour.size());
    for (int i = 0; i < n; ++i) {
        length += d[tour[i]][tour[(i + 1) % n]];
    }
    return length;
}

static void two_opt(std::vector<int> &tour, const std::vector<std::vector<double>> &d) {
    const int n = static_cast<int>(tour.size());
    bool improved = true;
    int passes = 0;
    while (improved && passes < 8) {
        improved = false;
        ++passes;
        for (int i = 1; i < n - 2; ++i) {
            for (int k = i + 1; k < n - 1; ++k) {
                const int a = tour[i - 1];
                const int b = tour[i];
                const int c = tour[k];
                const int e = tour[k + 1];
                const double before = d[a][b] + d[c][e];
                const double after = d[a][c] + d[b][e];
                if (after + 1e-12 < before) {
                    std::reverse(tour.begin() + i, tour.begin() + k + 1);
                    improved = true;
                }
            }
        }
    }
}

static std::vector<int> randomized_nearest_neighbor(
    const std::vector<std::vector<double>> &d,
    std::mt19937 &rng,
    int candidate_pool_size
) {
    const int n = static_cast<int>(d.size());
    std::vector<int> tour;
    std::vector<int> unused;
    tour.reserve(n);
    unused.reserve(n - 1);
    tour.push_back(0);
    for (int city = 1; city < n; ++city) {
        unused.push_back(city);
    }

    while (!unused.empty()) {
        const int current = tour.back();
        std::sort(unused.begin(), unused.end(), [&](int a, int b) {
            return d[current][a] < d[current][b];
        });
        const int pool = std::min(candidate_pool_size, static_cast<int>(unused.size()));
        std::uniform_int_distribution<int> pick(0, pool - 1);
        const int selected_pos = pick(rng);
        const int selected_city = unused[selected_pos];
        tour.push_back(selected_city);
        unused.erase(unused.begin() + selected_pos);
    }
    return tour;
}

int main(int argc, char **argv) {
    if (argc != 2) {
        std::cerr << "usage: " << argv[0] << " instance_file\n";
        return EXIT_FAILURE;
    }

    std::ifstream in(argv[1]);
    int n = 0;
    in >> n;
    if (!in || n < 2 || n > 200) {
        std::cerr << "invalid TSP instance\n";
        return EXIT_FAILURE;
    }

    std::vector<std::vector<double>> d(n, std::vector<double>(n));
    for (int i = 0; i < n; ++i) {
        for (int j = 0; j < n; ++j) {
            if (!(in >> d[i][j])) {
                std::cerr << "invalid distance matrix\n";
                return EXIT_FAILURE;
            }
        }
    }

    const int nb_iterations = 200;
    const int candidate_pool_size = 3;
    const unsigned int prng_seed = 123456u;
    std::mt19937 rng(prng_seed);

    std::cout << std::fixed << std::setprecision(6);
    std::cout << "instance characteristics\n";
    std::cout << "cities -> " << n << "\n";
    std::cout << "tour cities -> " << n << "\n";
    std::cout << "closed tour edges -> " << n << "\n";
    std::cout << "candidate tours with fixed start city -> " << candidate_tours_with_fixed_start(n) << "\n";
    std::cout << "heuristic iterations -> " << nb_iterations << "\n";
    std::cout << "candidate pool size -> " << candidate_pool_size << "\n";
    std::cout << "prng seed -> " << prng_seed << "\n";
    std::cout << "distance matrix\n";
    for (int i = 0; i < n; ++i) {
        std::cout << "row " << i << " ->";
        for (int j = 0; j < n; ++j) {
            std::cout << ' ' << d[i][j];
        }
        std::cout << "\n";
    }

    double best = std::numeric_limits<double>::infinity();
    std::vector<int> best_tour;
    for (int iteration = 1; iteration <= nb_iterations; ++iteration) {
        std::vector<int> tour = randomized_nearest_neighbor(d, rng, candidate_pool_size);
        two_opt(tour, d);
        const double current = tour_length(tour, d);
        if (current < best) {
            best = current;
            best_tour = tour;
        }
        std::cout << "iteration " << iteration << " tour length -> " << best << "\n";
    }

    std::cout << "best tour ->";
    for (int city : best_tour) {
        std::cout << ' ' << city;
    }
    std::cout << " 0\n";
    std::cout << "final tour length -> " << best << "\n";
    return EXIT_SUCCESS;
}
