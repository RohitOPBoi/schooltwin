"""What the cameras report. Reality is the truth; cameras see a noisy, partial version of it."""


def observe(zone, n, rng, occlusion_start=0.6, max_loss=0.35):
    """Return how many of the n people in this zone a camera counts."""
    if zone.camera <= 0 or n <= 0:
        return 0
    density = n / max(zone.capacity, 1)
    loss = 0.0
    if density > occlusion_start:                  # crowds hide people from each other
        loss = min(max_loss * (density - occlusion_start) / (1 - occlusion_start), 0.6)
    return int(rng.binomial(n, zone.camera * (1 - loss)))


def estimate(zone, camera_count):
    """Best guess of the true count from a camera count (what the dashboard should show)."""
    return round(camera_count / zone.camera) if zone.camera > 0 else None
