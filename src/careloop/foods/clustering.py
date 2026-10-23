from math import isfinite, sqrt

FEATURES = {"protein": 25.0, "carbohydrate": 25.0, "fat": 100 / 9}
ALGORITHM = "macro-energy-kmeans-v1"
MAX_ITERATIONS = 30


def vector(food):
    """Divide by energy so g-based and ml-based foods need no density conversion."""
    nutrients = food["nutrients"]
    energy = nutrients.get("energy")
    if energy is None or energy <= 0 or any(nutrients.get(k) is None for k in FEATURES):
        return None
    values = [nutrients[k] / energy * 100 / scale for k, scale in FEATURES.items()]
    return values if all(isfinite(v) and abs(v) <= 1e100 for v in values) else None


def distance(left, right):
    return sqrt(sum((a - b) ** 2 for a, b in zip(left, right, strict=True)))


def fit(rows, clusters=4):
    points = {}
    excluded = []
    for row in sorted(rows, key=lambda r: str(r["id"])):
        identity = str(row["id"])
        point = vector(row["body"])
        if point is None:
            excluded.append(identity)
        else:
            points[identity] = point
    centroids = []
    if points:
        centroids.append(next(iter(points.values())))
    while len(centroids) < min(clusters, len(points)):
        farthest = max(points, key=lambda key: min(distance(points[key], c) for c in centroids))
        point = points[farthest]
        if point in centroids:
            break
        centroids.append(point)
    membership = {}
    iterations = 0
    for iteration in range(1, MAX_ITERATIONS + 1):
        iterations = iteration
        assigned = {
            key: min(range(len(centroids)), key=lambda i: distance(point, centroids[i]))
            for key, point in points.items()
        }
        if assigned == membership:
            break
        membership = assigned
        for index in range(len(centroids)):
            members = [points[key] for key in points if membership[key] == index]
            if members:
                centroids[index] = [
                    sum(column) / len(members) for column in zip(*members, strict=True)
                ]
    return {
        "algorithm": ALGORITHM,
        "features": list(FEATURES),
        "feature_scales_per_100_kcal": FEATURES,
        "requested_clusters": clusters,
        "centroids": centroids,
        "membership": membership,
        "excluded_food_ids": excluded,
        "iterations": iterations,
        "max_iterations": MAX_ITERATIONS,
    }


def retrieve(rows, source, model, method):
    origin = vector(source["body"])
    source_id = str(source["id"])
    candidates = []
    for row in rows:
        identity = str(row["id"])
        if identity == source_id:
            continue
        point = vector(row["body"])
        if method == "same_category":
            if row["body"]["category"] != source["body"]["category"]:
                continue
        elif origin is None or point is None:
            continue
        elif method == "cluster" and model["membership"].get(identity) != model["membership"].get(
            source_id
        ):
            continue
        similarity = distance(origin, point) if origin is not None and point is not None else None
        candidates.append((row, similarity))
    if method == "same_category":
        return sorted(candidates, key=lambda item: str(item[0]["id"]))
    return sorted(
        candidates,
        key=lambda item: (item[1] if item[1] is not None else float("inf"), str(item[0]["id"])),
    )
