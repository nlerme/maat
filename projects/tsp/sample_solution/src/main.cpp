#include <algorithm>
#include <cstdlib>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <limits>
#include <numeric>
#include <vector>

static unsigned long long factorial(int n) {
    unsigned long long result = 1;
    for (int k = 2; k <= n; ++k) {
        result *= static_cast<unsigned long long>(k);
    }
    return result;
}

int main(int argc, char **argv) {
    if (argc != 2) {
        std::cerr << "usage: " << argv[0] << " instance_file\n";
        return EXIT_FAILURE;
    }

    std::ifstream in(argv[1]);
    int n = 0;
    in >> n;
    if (!in || n <= 1 || n > 12) {
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

    std::cout << std::fixed << std::setprecision(6);
    std::cout << "instance characteristics\n";
    std::cout << "cities -> " << n << "\n";
    std::cout << "tour cities -> " << n << "\n";
    std::cout << "closed tour edges -> " << n << "\n";
    std::cout << "candidate tours with fixed start city -> " << factorial(n - 1) << "\n";
    std::cout << "distance matrix\n";
    for (int i = 0; i < n; ++i) {
        std::cout << "row " << i << " ->";
        for (int j = 0; j < n; ++j) {
            std::cout << ' ' << d[i][j];
        }
        std::cout << "\n";
    }

    std::vector<int> perm(n - 1);
    std::iota(perm.begin(), perm.end(), 1);
    double best = std::numeric_limits<double>::infinity();
    long long iteration = 0;

    do {
        ++iteration;
        double length = d[0][perm.front()];
        for (int i = 1; i < n - 1; ++i) {
            length += d[perm[i - 1]][perm[i]];
        }
        length += d[perm.back()][0];
        best = std::min(best, length);
        std::cout << "iteration " << iteration << " tour length -> " << best << "\n";
    } while (std::next_permutation(perm.begin(), perm.end()));

    std::cout << "final tour length -> " << best << "\n";
    return EXIT_SUCCESS;
}
