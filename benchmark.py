import argparse
import random
import string
import time
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed

def random_string(n=8):
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=n))

class VirtualUser:
    def __init__(self, base_url):
        self.base_url = base_url.rstrip('/')
        self.session = requests.Session()
        self.username = f"user_{random_string(6)}"
        self.email = f"{self.username}@benchmark.local"
        self.password = "BenchmarkPass123!"

    def run_user_journey(self):
        latencies = []
        errors = 0

        # 1. Register
        t0 = time.time()
        try:
            r = self.session.post(f"{self.base_url}/api/auth/register", json={
                "username": self.username,
                "email": self.email,
                "password": self.password,
                "display_name": f"Tester {self.username}"
            }, timeout=10)
            latencies.append(('Register', time.time() - t0, r.status_code == 201))
            if r.status_code != 201:
                errors += 1
        except Exception:
            errors += 1

        # 2. Add 2 Recipes
        for i in range(2):
            t0 = time.time()
            try:
                r = self.session.post(f"{self.base_url}/api/recipes", json={
                    "title": f"Recipe {i+1} by {self.username}",
                    "ingredients": "- 2 cups flour\n- 1 cup milk\n- 2 eggs",
                    "instructions": "1) Mix ingredients.\n2) Cook on skillet.",
                    "category": "Breakfast & Brunch"
                }, timeout=10)
                latencies.append(('Add Recipe', time.time() - t0, r.status_code == 201))
                if r.status_code != 201:
                    errors += 1
            except Exception:
                errors += 1

        # 3. Fetch Recipe Box (Read Query)
        t0 = time.time()
        try:
            r = self.session.get(f"{self.base_url}/api/recipes", timeout=10)
            latencies.append(('Get Recipes', time.time() - t0, r.status_code == 200))
            if r.status_code != 200:
                errors += 1
        except Exception:
            errors += 1

        # 4. Save Meal Plan
        t0 = time.time()
        try:
            r = self.session.post(f"{self.base_url}/api/planner/2026-09-15", json={
                "meals": {
                    "breakfast": "Pancakes",
                    "lunch": "Caesar Salad",
                    "dinner": "Homemade Pasta"
                },
                "notes": "Testing meal planner sync"
            }, timeout=10)
            latencies.append(('Save Plan', time.time() - t0, r.status_code == 200))
            if r.status_code != 200:
                errors += 1
        except Exception:
            errors += 1

        # 5. Add Groceries
        t0 = time.time()
        try:
            r = self.session.post(f"{self.base_url}/api/groceries", json={
                "item": "Milk\nEggs\nButter\nBread"
            }, timeout=10)
            latencies.append(('Add Groceries', time.time() - t0, r.status_code == 201))
            if r.status_code != 201:
                errors += 1
        except Exception:
            errors += 1

        # 6. Read Planner & Groceries (Dashboard Load)
        t0 = time.time()
        try:
            r1 = self.session.get(f"{self.base_url}/api/planner", timeout=10)
            r2 = self.session.get(f"{self.base_url}/api/groceries", timeout=10)
            ok = (r1.status_code == 200 and r2.status_code == 200)
            latencies.append(('Dashboard Load', time.time() - t0, ok))
            if not ok:
                errors += 1
        except Exception:
            errors += 1

        return latencies, errors

def main():
    parser = argparse.ArgumentParser(description="Multi-User Stress & Scale Benchmark")
    parser.add_argument("--url", default="http://localhost:5050", help="Base URL of the website")
    parser.add_argument("--users", type=int, default=50, help="Number of concurrent virtual users to simulate")
    args = parser.parse_args()

    print(f"\n🚀 Starting Multi-User Load Test")
    print(f"🎯 Target URL: {args.url}")
    print(f"👥 Virtual Users: {args.users} concurrent simulated accounts")
    print(f"⏳ Running realistic user workflows (Register → Create Recipes → Plan Meals → Groceries → Read Dashboard)...\n")

    start_time = time.time()
    all_latencies = []
    total_errors = 0

    with ThreadPoolExecutor(max_workers=min(args.users, 64)) as executor:
        futures = [executor.submit(VirtualUser(args.url).run_user_journey) for _ in range(args.users)]
        for f in as_completed(futures):
            user_latencies, errors = f.result()
            all_latencies.extend(user_latencies)
            total_errors += errors

    total_duration = time.time() - start_time
    total_requests = len(all_latencies)
    successful_requests = sum(1 for _, _, success in all_latencies if success)
    rps = total_requests / total_duration if total_duration > 0 else 0

    durations = [d * 1000 for _, d, success in all_latencies if success]
    durations.sort()

    p50 = durations[int(len(durations) * 0.50)] if durations else 0
    p95 = durations[int(len(durations) * 0.95)] if durations else 0
    p99 = durations[int(len(durations) * 0.99)] if durations else 0
    avg_latency = sum(durations) / len(durations) if durations else 0

    print("=" * 60)
    print("📊 BENCHMARK RESULTS & PERFORMANCE SUMMARY")
    print("=" * 60)
    print(f"⏱️  Total Test Time:       {total_duration:.2f} seconds")
    print(f"📨 Total HTTP Requests:   {total_requests}")
    print(f"✅ Successful Requests:   {successful_requests} ({successful_requests/total_requests*100:.1f}%)" if total_requests else "0")
    print(f"❌ Failed Requests:       {total_errors}")
    print(f"⚡ Throughput (RPS):      {rps:.1f} requests/second")
    print("-" * 60)
    print(f"📈 Average Latency:       {avg_latency:.1f} ms")
    print(f"🎯 50th Percentile (p50): {p50:.1f} ms")
    print(f"🎯 95th Percentile (p95): {p95:.1f} ms")
    print(f"🎯 99th Percentile (p99): {p99:.1f} ms")
    print("=" * 60 + "\n")

if __name__ == '__main__':
    main()
