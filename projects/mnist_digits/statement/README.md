# Digit classification

This example demonstrates a MAAT project very different from TSP: Python code classifies small grayscale handwritten digit images stored as CSV rows.

The bundled offline dataset is generated from scikit-learn's handwritten-digits dataset and uses 8x8 grayscale images. It is MNIST-like in format and purpose, but intentionally small so the bundle can run without network downloads. The split is approximately 2/3 training and 1/3 test:

- `train_digits.csv` is mounted read-only beside each test instance;
- `test_public_digits.csv` and `test_private_digits.csv` are evaluation instances.

Your program receives one test CSV path as its only argument. For each execution, the reference solution prints:

- the instance characteristics: instance filename, training filename, number of training and test samples, image size, number of pixel features, label histograms and pixel ranges;
- the algorithm parameters and their values;
- the running accuracy progression at regular checkpoints;
- the final metric line parsed by MAAT.

The final metric line must be:

```text
final accuracy -> <percentage>
```

The leaderboard maximizes the mean `accuracy` over the test instances. A centroid-based Python reference solution is available in `sample_solution/main.py`.
