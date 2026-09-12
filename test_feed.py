#!/usr/bin/env python3
"""
Intensive Multi-User Social Feed & High-Scale Load Benchmark Tool
-----------------------------------------------------------------
Simulates realistic, concurrent multi-user activity across the entire platform:
- Parallel account registration and secure session management
- Multi-recipe creation across categories
- Public recipe sharing & token generation
- Community Food Feed posting with attached recipe cards & food photos
- Feed browsing & social engagement (likes, multi-threaded comments)
- 1-Click recipe cloning / forking into personal boxes
- Meal planning & grocery list consolidation
- High-throughput concurrency stress testing

Usage Examples:
  # Run intensive 300-user community scale test against remote server:
  python3 test_feed.py --url http://192.168.0.225:5052 --users 300

  # Custom concurrency:
  python3 test_feed.py --url http://192.168.0.225:5052 --users 300 --concurrency 50
"""

import argparse
import random
import string
import time
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests

RECIPES_DATABASE = [
    {
        "title": "Creamy Tuscan Garlic Gnocchi",
        "category": "Pasta",
        "ingredients": "1 lb potato gnocchi\n2 cups fresh baby spinach\n1 cup heavy cream\n1/2 cup sun-dried tomatoes, sliced\n3 cloves garlic, minced\n1/2 cup grated parmesan\n1 tbsp olive oil\nSalt and black pepper to taste",
        "instructions": "1. Pan-sear gnocchi in olive oil until golden and crispy (5 mins).\n2. Sauté garlic and sun-dried tomatoes until fragrant.\n3. Pour in heavy cream and bring to a gentle simmer.\n4. Stir in fresh baby spinach and parmesan until melted into a velvety sauce.\n5. Toss with gnocchi and serve immediately!",
        "prep_time": "10 mins",
        "cook_time": "15 mins",
        "difficulty": "Easy",
        "servings": "4",
        "post_caption": "Whip this up whenever you need comfort food in under 20 minutes! The crispy gnocchi with sun-dried tomato cream sauce is unreal. 🍝✨",
        "image_url": "https://images.unsplash.com/photo-1551183053-bf91a1d81141?w=800&auto=format&fit=crop&q=80"
    },
    {
        "title": "Rustic Rosemary Sea Salt Focaccia",
        "category": "Baking & Bread",
        "ingredients": "4 cups bread flour\n2 tsp instant yeast\n2 tsp kosher salt\n1 3/4 cups lukewarm water\n1/4 cup extra virgin olive oil\n2 tbsp fresh rosemary leaves\nFlaky sea salt for topping",
        "instructions": "1. Combine flour, yeast, salt, and water in a bowl. Cover and let rise overnight in fridge.\n2. Transfer dough to an oiled 9x13 baking pan and proof until bubbly (2-3 hours).\n3. Drizzle generously with olive oil and dimple deeply with your fingertips.\n4. Scatter fresh rosemary and flaky sea salt on top.\n5. Bake at 425°F (220°C) for 22-26 minutes until golden brown!",
        "prep_time": "20 mins",
        "cook_time": "25 mins",
        "difficulty": "Medium",
        "servings": "8",
        "post_caption": "Nothing beats the aroma of freshly baked rosemary focaccia filling the house on a Sunday afternoon! Crisp bottom, pillowy interior. 🥖🌿",
        "image_url": "https://images.unsplash.com/photo-1586444248902-2f64eddc13df?w=800&auto=format&fit=crop&q=80"
    },
    {
        "title": "Smoked Paprika & Honey Glazed Salmon",
        "category": "Mains & Entrees",
        "ingredients": "4 salmon fillets (6 oz each)\n2 tbsp honey\n1 tbsp smoked paprika\n1 tbsp olive oil\n1 tbsp soy sauce\n1 clove garlic, finely grated\n1/2 lemon, juiced\nPinch of red pepper flakes",
        "instructions": "1. Whisk honey, smoked paprika, olive oil, soy sauce, garlic, and lemon juice.\n2. Pat salmon fillets dry and brush generously with glaze.\n3. Heat a cast-iron skillet over medium-high heat with olive oil.\n4. Sear salmon skin-side down for 4 mins, flip, baste with remaining glaze, and cook 3-4 mins.\n5. Garnish with chopped parsley and fresh lemon wedges.",
        "prep_time": "10 mins",
        "cook_time": "10 mins",
        "difficulty": "Easy",
        "servings": "4",
        "post_caption": "Crispy glazed salmon with smoky sweet flavors! Paired this with roasted asparagus and jasmine rice tonight. Quick, healthy dinner win. 🐟🔥",
        "image_url": "https://images.unsplash.com/photo-1467003909585-2f8a72700288?w=800&auto=format&fit=crop&q=80"
    },
    {
        "title": "Fresh Strawberry Matcha Swiss Roll",
        "category": "Dessert",
        "ingredients": "4 large eggs (separated)\n1/2 cup granulated sugar\n1/2 cup cake flour\n1 1/2 tbsp culinary grade matcha powder\n1/4 cup whole milk\n2 tbsp vegetable oil\n1 cup heavy whipping cream\n1/2 cup fresh diced strawberries\n1 tsp vanilla extract",
        "instructions": "1. Beat egg whites with sugar to stiff peaks. Whisk yolks with milk, oil, flour, and matcha.\n2. Gently fold meringue into matcha batter and spread onto parchment-lined baking sheet.\n3. Bake at 340°F (170°C) for 14 minutes. Roll warm cake in a towel to set shape.\n4. Whip cream with vanilla until thick. Unroll cooled cake, spread cream, and scatter diced strawberries.\n5. Roll tightly, chill for 1 hour, and slice with a warm knife!",
        "prep_time": "30 mins",
        "cook_time": "14 mins",
        "difficulty": "Hard",
        "servings": "6",
        "post_caption": "Japanese-inspired Strawberry Matcha Swiss Roll! The slight bitterness of green tea balances the sweet whipped cream and tart strawberries perfectly. 🍓🍵🍰",
        "image_url": "https://images.unsplash.com/photo-1578985545062-69928b1d9587?w=800&auto=format&fit=crop&q=80"
    },
    {
        "title": "Thai Coconut Curry Butternut Squash Soup",
        "category": "Soup",
        "ingredients": "1 large butternut squash, peeled and cubed\n1 can (14 oz) full-fat coconut milk\n2 tbsp Thai red curry paste\n1 medium onion, diced\n2 cloves garlic, minced\n1 tbsp grated fresh ginger\n3 cups vegetable broth\n1 tbsp lime juice\nToasted pumpkin seeds & cilantro for garnish",
        "instructions": "1. Sauté onion, garlic, and ginger in olive oil until soft (3-4 mins).\n2. Stir in Thai red curry paste and cook for 1 minute until fragrant.\n3. Add cubed butternut squash and vegetable broth. Bring to a boil, then simmer 20 mins.\n4. Blend with immersion blender until silky smooth.\n5. Stir in coconut milk and fresh lime juice. Ladle into bowls and top with toasted pumpkin seeds!",
        "prep_time": "15 mins",
        "cook_time": "25 mins",
        "difficulty": "Easy",
        "servings": "6",
        "post_caption": "Super silky butternut squash soup with a fragrant Thai coconut curry kick! Perfect cozy bowl for chilly evenings. 🥣🥥🌶️",
        "image_url": "https://images.unsplash.com/photo-1547592166-23ac45744acd?w=800&auto=format&fit=crop&q=80"
    },
    {
        "title": "Avocado & Crispy Prosciutto Egg Toast",
        "category": "Breakfast",
        "ingredients": "2 thick slices sourdough bread\n1 ripe avocado, mashed\n2 large eggs, poached or sunny side up\n2 slices prosciutto\n1 tbsp lemon juice\nRed pepper flakes, flaky salt & black pepper",
        "instructions": "1. Toast sourdough bread until deep golden.\n2. Crisp prosciutto in a hot dry skillet for 2 minutes until crunchy.\n3. Mash avocado with lemon juice, salt, and pepper; spread thickly over toast.\n4. Top each slice with a fried egg and crumbled crispy prosciutto.\n5. Finish with extra red pepper flakes and microgreens!",
        "prep_time": "5 mins",
        "cook_time": "5 mins",
        "difficulty": "Easy",
        "servings": "2",
        "post_caption": "Elevated weekend breakfast toast! That crispy prosciutto crunch on top of runny egg yolk and creamy avocado is unmatched. 🥑🍳🥓",
        "image_url": "https://images.unsplash.com/photo-1525351484163-7529414344d8?w=800&auto=format&fit=crop&q=80"
    },
    {
        "title": "Mediterranean Lemon Herb Orzo Salad",
        "category": "Salad",
        "ingredients": "2 cups cooked orzo pasta\n1 cup cherry tomatoes, halved\n1 English cucumber, diced\n1/2 cup Kalamata olives, pitted and sliced\n1/2 cup crumbled feta cheese\n1/4 cup red onion, finely diced\n1/4 cup extra virgin olive oil\n2 tbsp fresh lemon juice\n1 tbsp chopped fresh dill and oregano",
        "instructions": "1. Cook orzo in salted water until al dente, drain and rinse with cold water.\n2. In a large bowl, whisk olive oil, lemon juice, chopped herbs, salt, and black pepper.\n3. Add cooled orzo, tomatoes, cucumber, olives, and red onion. Toss gently.\n4. Fold in crumbled feta cheese.\n5. Chill for 30 minutes before serving so flavors meld together beautifully.",
        "prep_time": "15 mins",
        "cook_time": "8 mins",
        "difficulty": "Easy",
        "servings": "6",
        "post_caption": "Bright, zesty, and crunchy! This Mediterranean orzo salad is my go-to lunch meal prep for busy weeks. 🥗🍋🫒",
        "image_url": "https://images.unsplash.com/photo-1540420773420-3366772f4999?w=800&auto=format&fit=crop&q=80"
    },
    {
        "title": "Slow-Braised Red Wine Short Ribs",
        "category": "Mains & Entrees",
        "ingredients": "3 lbs bone-in beef short ribs\n1 bottle dry red wine (Cabernet or Pinot Noir)\n2 cups beef stock\n2 carrots, chopped\n2 stalks celery, chopped\n1 large yellow onion, diced\n4 cloves garlic, crushed\n2 tbsp tomato paste\nFresh thyme and rosemary sprigs",
        "instructions": "1. Season short ribs generously with salt and pepper. Brown heavily in a Dutch oven on all sides.\n2. Remove ribs; sauté carrots, celery, onion, and garlic. Stir in tomato paste.\n3. Deglaze with red wine, scraping brown bits. Add beef stock, herbs, and return ribs.\n4. Cover and braise in oven at 325°F (165°C) for 3 to 3.5 hours until fall-apart tender.\n5. Skim fat, reduce sauce until rich, and serve over creamy mashed potatoes or polenta!",
        "prep_time": "20 mins",
        "cook_time": "210 mins",
        "difficulty": "Medium",
        "servings": "6",
        "post_caption": "Slow-braised for 3.5 hours until meltingly tender. The red wine reduction over parmesan polenta was pure culinary heaven! 🍷🥩✨",
        "image_url": "https://images.unsplash.com/photo-1544025162-d76694265947?w=800&auto=format&fit=crop&q=80"
    }
]

COMMENTS_POOL = [
    "This looks unbelievable! Definitely saving this to my box for dinner this week. 👏",
    "Made this tonight and my family loved it! Thanks for sharing the recipe! 😋",
    "That crust looks absolute perfection! Any tip on oven rack placement?",
    "Saved to my recipes! Can't wait to make it this weekend. ⭐⭐⭐⭐⭐",
    "The plating and colors here are stunning! Great job chef! 🌟",
    "10/10 recipe! I added a pinch of red chili flakes and it was sensational. 🔥",
    "Bookmarked! Going right onto my meal planner for Tuesday dinner.",
    "Such a creative twist! Did you use whole milk or almond milk?",
    "Cooking this for date night tonight, wish me luck! 🥂",
    "The photos made me instantly hungry. 1-click saved! 📥"
]

CHEF_FIRST_NAMES = [
    "Michaela", "Marco", "Chloe", "Sam", "Elena", "Leo", "Rosa", "Oliver", 
    "Maya", "Lucas", "Sophie", "Gabe", "Hannah", "Noah", "Bella", "Julian",
    "Aria", "Mateo", "Zoe", "Arthur", "Camila", "Felix", "Ivy", "Theo"
]

def random_string(n=6):
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=n))

class IntensiveVirtualUser:
    def __init__(self, base_url, user_index):
        self.base_url = base_url.rstrip('/')
        self.session = requests.Session()
        self.index = user_index
        suffix = random_string(5)
        first_name = CHEF_FIRST_NAMES[user_index % len(CHEF_FIRST_NAMES)]
        self.username = f"{first_name.lower()}_{suffix}"
        self.display_name = f"Chef {first_name} {suffix.upper()}"
        self.email = f"{self.username}@virtualbox.benchmark"
        self.password = "BenchmarkSecretPassword2026!"
        self.created_recipes = []

    def execute_intensive_journey(self):
        latencies = []
        errors = 0

        # Helper for recording metrics
        def track_req(action_name, func):
            nonlocal errors
            t0 = time.time()
            try:
                res, is_ok = func()
                dur = time.time() - t0
                latencies.append((action_name, dur, is_ok))
                if not is_ok:
                    errors += 1
                return res
            except Exception:
                dur = time.time() - t0
                latencies.append((action_name, dur, False))
                errors += 1
                return None

        # 1. Register Account
        def do_register():
            r = self.session.post(f"{self.base_url}/api/auth/register", json={
                "username": self.username,
                "email": self.email,
                "password": self.password,
                "display_name": self.display_name
            }, timeout=12)
            return r, r.status_code == 201
        track_req('1. Register User', do_register)

        # 2. Create 2 Distinct Handcrafted Recipes
        recipes_to_create = random.sample(RECIPES_DATABASE, 2)
        created_recipe_ids = []
        for rec in recipes_to_create:
            def do_add_rec(r_data=rec):
                r = self.session.post(f"{self.base_url}/api/recipes", json={
                    "title": f"{r_data['title']} (by {self.display_name})",
                    "category": r_data["category"],
                    "ingredients": r_data["ingredients"],
                    "instructions": r_data["instructions"],
                    "prep_time": r_data.get("prep_time", ""),
                    "cook_time": r_data.get("cook_time", ""),
                    "difficulty": r_data.get("difficulty", "Easy"),
                    "servings": r_data.get("servings", "")
                }, timeout=12)
                if r.status_code == 201:
                    r_id = r.json().get("id")
                    created_recipe_ids.append((r_id, r_data))
                    return r, True
                return r, False
            track_req('2. Create Recipe', do_add_rec)

        # 3. Generate Public Share Tokens
        for r_id, _ in created_recipe_ids:
            def do_share(id_val=r_id):
                r = self.session.post(f"{self.base_url}/api/recipes/{id_val}/share", timeout=12)
                return r, r.status_code == 200
            track_req('3. Share Recipe Token', do_share)

        # 4. Post to Community Food Feed with Attached Recipe Card
        for r_id, r_data in created_recipe_ids:
            def do_feed_post(id_val=r_id, data_val=r_data):
                r = self.session.post(f"{self.base_url}/api/community/posts", json={
                    "content": f"{data_val['post_caption']} ~ Made with love by @{self.username}!",
                    "image_url": data_val["image_url"],
                    "recipe_id": id_val
                }, timeout=12)
                return r, r.status_code == 201
            track_req('4. Post to Feed', do_feed_post)

        # 5. Fetch Community Feed
        feed_posts = []
        def do_get_feed():
            nonlocal feed_posts
            r = self.session.get(f"{self.base_url}/api/community/posts?limit=50", timeout=12)
            if r.status_code == 200:
                feed_posts = r.json()
                return r, True
            return r, False
        track_req('5. Browse Feed Stream', do_get_feed)

        # 6. Like Community Posts
        if feed_posts:
            sample_posts = random.sample(feed_posts, min(len(feed_posts), 3))
            for p in sample_posts:
                def do_like(p_id=p['id']):
                    r = self.session.post(f"{self.base_url}/api/community/posts/{p_id}/like", timeout=12)
                    return r, r.status_code == 200
                track_req('6. Like Community Post', do_like)

        # 7. Post Comments on Other Chefs' Recipes
        if feed_posts:
            target_post = random.choice(feed_posts)
            comment_text = random.choice(COMMENTS_POOL)
            def do_comment(p_id=target_post['id'], c_text=comment_text):
                r = self.session.post(f"{self.base_url}/api/community/posts/{p_id}/comments", json={
                    "comment": c_text
                }, timeout=12)
                return r, r.status_code == 201
            track_req('7. Comment on Post', do_comment)

        # 8. 1-Click Fork / Clone a Shared Recipe from the Feed
        clonable_posts = [p for p in feed_posts if p.get('recipe') and p['recipe'].get('share_token')]
        if clonable_posts:
            target_clone = random.choice(clonable_posts)
            share_tok = target_clone['recipe']['share_token']
            def do_clone(token=share_tok):
                r = self.session.post(f"{self.base_url}/api/recipes/clone/{token}", timeout=12)
                return r, r.status_code == 201
            track_req('8. 1-Click Clone Recipe', do_clone)

        # 9. Meal Planner & Grocery Synchronization
        def do_plan_meal():
            r = self.session.post(f"{self.base_url}/api/planner/2026-09-18", json={
                "meals": {
                    "breakfast": "Avocado & Egg Sourdough",
                    "lunch": "Mediterranean Orzo Salad",
                    "dinner": "Tuscan Garlic Gnocchi"
                },
                "tasks": "Grocery run; Prep dinner ingredients",
                "notes": "Community dinner party!"
            }, timeout=12)
            return r, r.status_code == 200
        track_req('9. Sync Meal Planner', do_plan_meal)

        def do_add_groceries():
            r = self.session.post(f"{self.base_url}/api/groceries", json={
                "item": "Potato Gnocchi\nHeavy Cream\nSpinach\nParmesan\nSourdough Bread\nAvocados\nSalmon Fillets"
            }, timeout=12)
            return r, r.status_code == 201
        track_req('10. Add Groceries', do_add_groceries)

        # 10. Dashboard Read Multi-Query (Simulate Loading index.html)
        def do_read_dashboard():
            r1 = self.session.get(f"{self.base_url}/api/recipes", timeout=12)
            r2 = self.session.get(f"{self.base_url}/api/planner", timeout=12)
            r3 = self.session.get(f"{self.base_url}/api/groceries", timeout=12)
            r4 = self.session.get(f"{self.base_url}/api/community/posts?limit=3", timeout=12)
            ok = (r1.status_code == 200 and r2.status_code == 200 and r3.status_code == 200 and r4.status_code == 200)
            return r4, ok
        track_req('11. Full Dashboard Sync', do_read_dashboard)

        return latencies, errors

def print_progress(completed, total, start_time, total_requests):
    elapsed = time.time() - start_time
    rps = total_requests / elapsed if elapsed > 0 else 0
    percent = (completed / total) * 100
    bar_length = 30
    filled = int(bar_length * completed // total)
    bar = '█' * filled + '░' * (bar_length - filled)
    sys.stdout.write(f"\r⚡ [{bar}] {completed}/{total} Users ({percent:.1f}%) | {total_requests} Reqs | {rps:.1f} RPS")
    sys.stdout.flush()

def main():
    parser = argparse.ArgumentParser(description="Intensive Multi-User Social Feed Load & Stress Test")
    parser.add_argument("--url", default="http://localhost:5000", help="Base URL of the website")
    parser.add_argument("--users", type=int, default=300, help="Number of concurrent virtual users to simulate (default: 300)")
    parser.add_argument("--concurrency", type=int, default=50, help="Max parallel worker threads (default: 50)")
    args = parser.parse_args()

    print("\n" + "=" * 70)
    print("🚀 INTENSIVE COMMUNITY FOOD FEED & MULTI-USER LOAD TEST")
    print("=" * 70)
    print(f"🎯 Target Server:       {args.url}")
    print(f"👥 Virtual Users:       {args.users} concurrent simulated chefs/foodies")
    print(f"🧵 Parallel Concurrency: {args.concurrency} worker threads")
    print(f"🔄 Workflow:            Register → Add Recipes → Share Tokens → Post to Feed")
    print(f"                        → Browse Stream → Like Posts → Comment → 1-Click Clone")
    print(f"                        → Plan Meals → Add Groceries → Dashboard Sync")
    print("=" * 70 + "\n")

    start_time = time.time()
    all_latencies = []
    total_errors = 0
    completed_users = 0

    print(f"⏳ Executing heavy parallel traffic test across {args.users} accounts...\n")

    with ThreadPoolExecutor(max_workers=min(args.concurrency, args.users)) as executor:
        futures = [executor.submit(IntensiveVirtualUser(args.url, i).execute_intensive_journey) for i in range(args.users)]
        for f in as_completed(futures):
            user_latencies, errors = f.result()
            all_latencies.extend(user_latencies)
            total_errors += errors
            completed_users += 1
            print_progress(completed_users, args.users, start_time, len(all_latencies))

    total_duration = time.time() - start_time
    total_requests = len(all_latencies)
    successful_requests = sum(1 for _, _, success in all_latencies if success)
    rps = total_requests / total_duration if total_duration > 0 else 0

    durations = [d * 1000 for _, d, success in all_latencies if success]
    durations.sort()

    p50 = durations[int(len(durations) * 0.50)] if durations else 0
    p90 = durations[int(len(durations) * 0.90)] if durations else 0
    p95 = durations[int(len(durations) * 0.95)] if durations else 0
    p99 = durations[int(len(durations) * 0.99)] if durations else 0
    min_lat = min(durations) if durations else 0
    max_lat = max(durations) if durations else 0
    avg_latency = sum(durations) / len(durations) if durations else 0

    print("\n\n" + "=" * 70)
    print("📊 COMPREHENSIVE PERFORMANCE & STABILITY REPORT")
    print("=" * 70)
    print(f"⏱️  Total Duration:         {total_duration:.2f} seconds")
    print(f"📨 Total HTTP Requests:     {total_requests:,}")
    print(f"✅ Successful Requests:     {successful_requests:,} ({successful_requests/total_requests*100:.1f}%)" if total_requests else "0")
    print(f"❌ Failed Requests:         {total_errors}")
    print(f"⚡ System Throughput:       {rps:.1f} requests/second")
    print("-" * 70)
    print(f"📈 Latency (p50 / median):   {p50:.1f} ms")
    print(f"📈 Latency (p90):            {p90:.1f} ms")
    print(f"🎯 Latency (p95):            {p95:.1f} ms")
    print(f"🎯 Latency (p99):            {p99:.1f} ms")
    print(f"📉 Latency (Min / Max):      {min_lat:.1f} ms / {max_lat:.1f} ms")
    print(f"📊 Latency (Average):        {avg_latency:.1f} ms")
    print("=" * 70)

    # Action-by-Action Breakdown
    action_types = {}
    for action, dur, ok in all_latencies:
        if action not in action_types:
            action_types[action] = {"count": 0, "ok": 0, "durations": []}
        action_types[action]["count"] += 1
        if ok:
            action_types[action]["ok"] += 1
            action_types[action]["durations"].append(dur * 1000)

    print("\n📋 ACTION-BY-ACTION LATENCY BREAKDOWN")
    print("-" * 70)
    print(f"{'Action Name':<26} | {'Count':<7} | {'Avg (ms)':<9} | {'p95 (ms)':<9} | {'Success':<8}")
    print("-" * 70)
    for act_name, stats in sorted(action_types.items()):
        durs = sorted(stats["durations"])
        avg_d = sum(durs) / len(durs) if durs else 0
        p95_d = durs[int(len(durs) * 0.95)] if durs else 0
        succ_rate = f"{(stats['ok']/stats['count'])*100:.0f}%" if stats['count'] else "0%"
        print(f"{act_name:<26} | {stats['count']:<7} | {avg_d:<9.1f} | {p95_d:<9.1f} | {succ_rate:<8}")
    print("=" * 70)
    print(f"🌐 View Live Community Feed: {args.url}/feed.html")
    print(f"🏠 View Home Dashboard:      {args.url}/index.html")
    print("=" * 70 + "\n")

if __name__ == "__main__":
    main()
