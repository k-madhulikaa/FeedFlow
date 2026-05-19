import time
import random
import hashlib
from collections import defaultdict, OrderedDict, deque
from dataclasses import dataclass, field
from typing import Optional

#DATA STRUCTURES

TOPICS = ["tech", "sports", "finance", "health", "politics", "science", "entertainment"]

@dataclass
class Article:
    id: int
    title: str
    topic: str
    score: float          # base quality score 0-10
    views: int = 0        # for trending boost

@dataclass
class UserProfile:
    user_id: int
    preferred_topics: list   # ordered by preference strength
    disliked_topics: list

# DATA GENERATION

def generate_articles(n=200) -> list[Article]:
    random.seed(42)
    articles = []
    for i in range(n):
        topic = random.choice(TOPICS)
        articles.append(Article(
            id=i,
            title=f"Article-{i}: {topic.capitalize()} Update #{random.randint(1,999)}",
            topic=topic,
            score=round(random.uniform(1, 10), 2),
            views=random.randint(0, 500)
        ))
    return articles

def generate_users(n=20) -> list[UserProfile]:
    random.seed(7)
    users = []
    for i in range(n):
        shuffled = TOPICS[:]
        random.shuffle(shuffled)
        preferred = shuffled[:3]
        disliked  = shuffled[5:]
        users.append(UserProfile(user_id=i, preferred_topics=preferred, disliked_topics=disliked))
    return users

# INPUT ENHANCEMENT: Hash-based article index (DAA)


def build_topic_index(articles: list[Article]) -> dict[str, list[Article]]:
    """Pre-index articles by topic — O(n) build, O(1) lookup per topic."""
    index = defaultdict(list)
    for article in articles:
        index[article.topic].append(article)
    return dict(index)

def rank_feed_with_index(user: UserProfile, index: dict, trending_ids: set, top_k=10) -> list[Article]:
    """Compute ranked feed using hash index — fast O(k) per topic."""
    candidates = []
    for topic in user.preferred_topics:
        candidates.extend(index.get(topic, []))
    
    # Remove disliked
    candidates = [a for a in candidates if a.topic not in user.disliked_topics]
    
    # Score = base_score + preference_weight + trending_boost
    def score_fn(a: Article):
        pref_weight = (3 - user.preferred_topics.index(a.topic)) * 1.5 \
                      if a.topic in user.preferred_topics else 0
        trend_boost = 2.0 if a.id in trending_ids else 0
        a.views += 1  # simulate access
        return a.score + pref_weight + trend_boost

    ranked = sorted(candidates, key=score_fn, reverse=True)
    return ranked[:top_k]

def rank_feed_linear_scan(user: UserProfile, articles: list[Article], trending_ids: set, top_k=10) -> list[Article]:
    """Compute ranked feed via linear scan — O(n) every time."""
    candidates = [a for a in articles
                  if a.topic in user.preferred_topics and a.topic not in user.disliked_topics]
    def score_fn(a: Article):
        pref_weight = (3 - user.preferred_topics.index(a.topic)) * 1.5 \
                      if a.topic in user.preferred_topics else 0
        trend_boost = 2.0 if a.id in trending_ids else 0
        return a.score + pref_weight + trend_boost
    ranked = sorted(candidates, key=score_fn, reverse=True)
    return ranked[:top_k]

# TRENDING BOOST (Bonus)

class TrendingTracker:
    """Tracks article accesses in a sliding window."""
    def __init__(self, window=10, threshold=3):
        self.window = window          # last N requests
        self.threshold = threshold    # min hits to be "trending"
        self.recent_accesses = deque()
        self.counts = defaultdict(int)

    def record(self, feed: list[Article]):
        for a in feed[:3]:  # top-3 articles are "seen"
            self.recent_accesses.append(a.id)
            self.counts[a.id] += 1

        # Evict old entries
        while len(self.recent_accesses) > self.window * 3:
            old = self.recent_accesses.popleft()
            self.counts[old] -= 1
            if self.counts[old] <= 0:
                del self.counts[old]

    def get_trending(self) -> set:
        return {aid for aid, cnt in self.counts.items() if cnt >= self.threshold}

#LRU CACHE (OS: LRU Page Replacement)

class LRUCache:
    def __init__(self, capacity: int):
        self.capacity = capacity
        self.cache = OrderedDict()   # key=user_id, val=feed
        self.hits = 0
        self.misses = 0
        self.evictions = 0
        self.history = []            # (user_id, HIT/MISS, evicted, frames_snapshot)

    def get(self, user_id: int) -> Optional[list]:
        if user_id in self.cache:
            self.cache.move_to_end(user_id)
            self.hits += 1
            self._record(user_id, "HIT", None)
            return self.cache[user_id]
        self.misses += 1
        return None

    def put(self, user_id: int, feed: list):
        evicted = None
        if user_id in self.cache:
            self.cache.move_to_end(user_id)
        else:
            if len(self.cache) >= self.capacity:
                evicted, _ = self.cache.popitem(last=False)
                self.evictions += 1
            self.cache[user_id] = feed
        self._record(user_id, "MISS", evicted)

    def _record(self, user_id, status, evicted):
        snapshot = list(self.cache.keys())
        self.history.append({
            "user": user_id,
            "status": status,
            "evicted": evicted,
            "frames": snapshot[:]
        })

    @property
    def hit_ratio(self): return self.hits / max(1, self.hits + self.misses)
    @property
    def miss_ratio(self): return self.misses / max(1, self.hits + self.misses)

#FIFO CACHE

class FIFOCache:
    def __init__(self, capacity: int):
        self.capacity = capacity
        self.cache = {}
        self.order = deque()
        self.hits = 0
        self.misses = 0

    def get(self, user_id):
        if user_id in self.cache:
            self.hits += 1
            return self.cache[user_id]
        self.misses += 1
        return None

    def put(self, user_id, feed):
        if user_id not in self.cache:
            if len(self.cache) >= self.capacity:
                old = self.order.popleft()
                del self.cache[old]
            self.cache[user_id] = feed
            self.order.append(user_id)

    @property
    def hit_ratio(self): return self.hits / max(1, self.hits + self.misses)

#OPTIMAL CACHE: needs future knowledge

class OptimalCache:
    def __init__(self, capacity: int, future_requests: list):
        self.capacity = capacity
        self.future = future_requests
        self.cache = {}
        self.hits = 0
        self.misses = 0
        self.current_step = 0

    def get(self, user_id):
        self.current_step += 1
        if user_id in self.cache:
            self.hits += 1
            return self.cache[user_id]
        self.misses += 1
        return None

    def put(self, user_id, feed):
        if user_id not in self.cache:
            if len(self.cache) >= self.capacity:
                # Evict page used furthest in future
                future_slice = self.future[self.current_step:]
                def next_use(uid):
                    try: return future_slice.index(uid)
                    except ValueError: return float('inf')
                evict = max(self.cache.keys(), key=next_use)
                del self.cache[evict]
            self.cache[user_id] = feed

    @property
    def hit_ratio(self): return self.hits / max(1, self.hits + self.misses)

#BENCHMARK:Index vs Linear Scan

def benchmark_speedup(users, articles, index, trending_ids, runs=300):
    results = {}

    # Linear scan timing
    t0 = time.perf_counter()
    for i in range(runs):
        u = users[i % len(users)]
        rank_feed_linear_scan(u, articles, trending_ids)
    linear_time = time.perf_counter() - t0

    # Index-based timing
    t0 = time.perf_counter()
    for i in range(runs):
        u = users[i % len(users)]
        rank_feed_with_index(u, index, trending_ids)
    index_time = time.perf_counter() - t0

    results["linear_ms"] = round(linear_time * 1000, 2)
    results["index_ms"]  = round(index_time  * 1000, 2)
    results["speedup"]   = round(linear_time / max(index_time, 1e-9), 2)
    return results

# MAIN SIMULATION

def run_simulation(cache_size=5, num_requests=60, seed=99):
    random.seed(seed)
    articles = generate_articles(200)
    users    = generate_users(20)
    index    = build_topic_index(articles)

    # Reference string — skewed to simulate locality (some users repeat)
    hot_users = [0, 1, 2, 3, 4]      # frequently requested
    ref_string = []
    for _ in range(num_requests):
        if random.random() < 0.6:
            ref_string.append(random.choice(hot_users))
        else:
            ref_string.append(random.randint(0, len(users) - 1))

    trending  = TrendingTracker(window=10, threshold=3)
    lru_cache = LRUCache(cache_size)
    fifo_cache= FIFOCache(cache_size)
    opt_cache = OptimalCache(cache_size, ref_string)

    print("=" * 65)
    print("  FeedFlow Simulation  |  Cache Size:", cache_size)
    print("=" * 65)
    print(f"\n📋 Reference String ({num_requests} requests):")
    print(" → ".join(map(str, ref_string)))
    print()

    print(f"{'Req':>4} {'User':>5} {'LRU':>5} {'FIFO':>5} {'OPT':>5}  Frames (LRU)")
    print("-" * 65)

    feeds_computed = 0
    for step, uid in enumerate(ref_string):
        user = users[uid]
        trending_ids = trending.get_trending()

        #LRU
        feed = lru_cache.get(uid)
        if feed is None:
            feed = rank_feed_with_index(user, index, trending_ids)
            lru_cache.put(uid, feed)
            trending.record(feed)
            feeds_computed += 1
            lru_status = "MISS"
        else:
            lru_status = "HIT "

        #FIFO
        f2 = fifo_cache.get(uid)
        if f2 is None:
            fifo_cache.put(uid, feed)
            fifo_status = "MISS"
        else:
            fifo_status = "HIT "

        #OPT
        f3 = opt_cache.get(uid)
        if f3 is None:
            opt_cache.put(uid, feed)
            opt_status = "MISS"
        else:
            opt_status = "HIT "

        frames = str(list(lru_cache.cache.keys()))
        print(f"{step+1:>4} {uid:>5}    {lru_status}  {fifo_status}  {opt_status}  {frames}")

    #Benchmark
    print("\n" + "=" * 65)
    print("  DAA: Input Enhancement Benchmark (300 feed computations)")
    print("=" * 65)
    bench = benchmark_speedup(users, articles, index, set())
    print(f"  Linear Scan : {bench['linear_ms']:>8.2f} ms")
    print(f"  Hash Index  : {bench['index_ms']:>8.2f} ms")
    print(f"  Speedup     : {bench['speedup']:>8.2f}×")

    #Stats
    print("\n" + "=" * 65)
    print("  Cache Performance Summary")
    print("=" * 65)
    print(f"  {'Algorithm':<12} {'Hits':>6} {'Misses':>8} {'Hit Ratio':>12}")
    print(f"  {'-'*40}")
    for name, c in [("LRU", lru_cache), ("FIFO", fifo_cache), ("Optimal", opt_cache)]:
        print(f"  {name:<12} {c.hits:>6} {c.misses:>8} {c.hit_ratio:>11.1%}")

    print(f"\n  Total feed recomputations avoided (LRU): {lru_cache.hits}")
    print(f"  Total feed recomputations needed  (LRU): {lru_cache.misses}")
    print(f"  Total evictions                   (LRU): {lru_cache.evictions}")

    print("\n" + "=" * 65)
    print("  Trending Articles (most accessed in last window)")
    print("=" * 65)
    trending_ids = trending.get_trending()
    if trending_ids:
        for aid in list(trending_ids)[:5]:
            a = articles[aid]
            print(f"  Article {aid:>3}: '{a.title[:45]}...' | views={a.views}")
    else:
        print("  No articles crossed the trending threshold yet.")

    return {
        "ref_string": ref_string,
        "lru": lru_cache,
        "fifo": fifo_cache,
        "opt": opt_cache,
        "bench": bench,
        "trending_ids": trending_ids,
        "history": lru_cache.history
    }

if __name__ == "__main__":
    run_simulation(cache_size=5, num_requests=60)
