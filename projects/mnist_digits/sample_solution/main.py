import csv
import math
import sys
from pathlib import Path


ALGORITHM_NAME = "nearest_centroid"
DISTANCE_METRIC = "squared_euclidean"
NORMALIZATION = "none"
PROGRESS_STEPS = 10


def read_rows(path):
    rows = []
    with open(path, newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        pixel_names = [name for name in reader.fieldnames if name != "label"]
        for row in reader:
            label = int(row["label"])
            pixels = [float(row[name]) for name in pixel_names]
            rows.append((label, pixels))
    return rows, pixel_names


def infer_image_shape(feature_count):
    side = int(math.isqrt(feature_count))
    if side * side == feature_count:
        return side, side
    return 1, feature_count


def label_histogram(rows):
    counts = {}
    for label, _pixels in rows:
        counts[label] = counts.get(label, 0) + 1
    return dict(sorted(counts.items()))


def pixel_range(rows):
    values = [value for _label, pixels in rows for value in pixels]
    if not values:
        return 0.0, 0.0
    return min(values), max(values)


def build_centroids(training_rows):
    sums = {}
    counts = {}
    for label, pixels in training_rows:
        sums.setdefault(label, [0.0] * len(pixels))
        counts[label] = counts.get(label, 0) + 1
        for i, value in enumerate(pixels):
            sums[label][i] += value
    return {
        label: [value / counts[label] for value in values]
        for label, values in sums.items()
    }


def predict(pixels, centroids):
    best_label = None
    best_dist = float("inf")
    for label, center in centroids.items():
        dist = sum((a - b) ** 2 for a, b in zip(pixels, center))
        if dist < best_dist:
            best_dist = dist
            best_label = label
    return best_label


def print_instance_characteristics(instance, train_path, training_rows, test_rows, pixel_names):
    height, width = infer_image_shape(len(pixel_names))
    train_min, train_max = pixel_range(training_rows)
    test_min, test_max = pixel_range(test_rows)
    train_labels = label_histogram(training_rows)
    test_labels = label_histogram(test_rows)

    print("instance characteristics")
    print(f"  test instance file -> {instance.name}")
    print(f"  training file -> {train_path.name}")
    print(f"  training samples -> {len(training_rows)}")
    print(f"  test samples -> {len(test_rows)}")
    print(f"  image width -> {width}")
    print(f"  image height -> {height}")
    print(f"  pixel features -> {len(pixel_names)}")
    print(f"  training labels -> {train_labels}")
    print(f"  test labels -> {test_labels}")
    print(f"  training pixel range -> [{train_min:.1f}, {train_max:.1f}]")
    print(f"  test pixel range -> [{test_min:.1f}, {test_max:.1f}]")


def print_parameters(centroids):
    print("algorithm parameters")
    print(f"  algorithm -> {ALGORITHM_NAME}")
    print(f"  distance metric -> {DISTANCE_METRIC}")
    print(f"  normalization -> {NORMALIZATION}")
    print(f"  number of centroids -> {len(centroids)}")
    print(f"  progress checkpoints -> {PROGRESS_STEPS}")


def main():
    if len(sys.argv) != 2:
        print("usage: python3 main.py instance_file", file=sys.stderr)
        return 1

    instance = Path(sys.argv[1])
    train_path = instance.parent / "train_digits.csv"
    training_rows, train_pixel_names = read_rows(train_path)
    test_rows, test_pixel_names = read_rows(instance)
    if len(train_pixel_names) != len(test_pixel_names):
        print("training and test files do not have the same number of pixel columns", file=sys.stderr)
        return 1

    centroids = build_centroids(training_rows)
    print_instance_characteristics(instance, train_path, training_rows, test_rows, test_pixel_names)
    print_parameters(centroids)
    print("accuracy progression")

    correct = 0
    total = len(test_rows)
    checkpoint_stride = max(1, math.ceil(total / PROGRESS_STEPS))
    for index, (label, pixels) in enumerate(test_rows, start=1):
        correct += int(predict(pixels, centroids) == label)
        if index == 1 or index == total or index % checkpoint_stride == 0:
            running_accuracy = 100.0 * correct / max(1, index)
            print(f"  processed {index}/{total} -> running accuracy {running_accuracy:.2f}%")

    accuracy = 100.0 * correct / max(1, total)
    print(f"final accuracy -> {accuracy:.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
