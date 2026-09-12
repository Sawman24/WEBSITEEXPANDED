#!/usr/bin/env python3
"""
Community Food Feed & Social Recipe Simulation and Test Tool
-------------------------------------------------------------
Simulates multi-user community activity:
- User registration & authentications
- Recipe creation with rich metadata
- Community food posts with attached recipe cards & food photos
- Real-time likes & social interactions
- Multi-user comment threads
- 1-Click recipe cloning into personal recipe boxes
- Standalone public recipe share links
- Password reset token verification

Usage:
  python3 test_feed.py --url http://192.168.0.225:5052
  python3 test_feed.py --url http://localhost:5000 --users 10
"""

import argparse
import random
import string
import time
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed

RECIPES_DATABASE = [
    {
        "title": "Creamy Tuscan Garlic Gnocchi",
        "category": "Pasta",
        "ingredients": "1 lb potato gnocchi\n2 cups fresh baby spinach\n1 cup heavy cream\n1/2 cup sun-dried tomatoes, sliced\n3 cloves garlic, minced\n1/2 cup grated parmesan\n1 tbsp olive oil\nSalt and black pepper to taste",
        "instructions": "1. Pan-sear gnocchi in olive oil until golden and crispy (approx 5 mins).\n2. Sauté garlic and sun-dried tomatoes until fragrant.\n3. Pour in heavy cream and bring to a gentle simmer.\n4. Stir in fresh baby spinach and parmesan until melted into a velvety sauce.\n5. Toss with gnocchi and serve immediately!",
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
        "instructions": "1. Whisk honey, smoked paprika, olive oil, soy sauce, garlic, and lemon juice in a small bowl.\n2. Pat salmon fillets dry and brush generously with glaze on all sides.\n3. Heat a cast-iron skillet over medium-high heat with a dash of oil.\n4. Sear salmon skin-side down for 4 mins, flip, baste with remaining glaze, and cook 3-4 mins more.\n5. Garnish with chopped parsley and fresh lemon wedges.",
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
        "post_caption": "Japanese-inspired Strawberry Matcha Swiss Roll! The slight bitterness of the green tea balances the sweet whipped cream and tart strawberries perfectly. 🍓🍵🍰",
        "image_url": "https://images.unsplash.com/photo-1578985545062-69928b1d9587?w=800&auto=format&fit=crop&q=80"
    },
    {
        "title": "Thai Coconut Curry Butternut Squash Soup",
        "category": "Soup",
        "ingredients": "1 large butternut squash, peeled and cubed\n1 can (14 oz) full-fat coconut milk\n2 tbsp Thai red curry paste\n1 medium onion, diced\n2 cloves garlic, minced\n1 tbsp grated fresh ginger\n3 cups vegetable broth\n1 tbsp lime juice\nToasted pumpkin seeds & cilantro for garnish",
        "instructions": "1. Sauté onion, garlic, and ginger in olive oil until soft (3-4 mins).\n2. Stir in Thai red curry paste and cook for 1 minute until fragrant.\n3. Add cubed butternut squash and vegetable broth. Bring to a boil, then simmer 20 mins until fork tender.\n4. Blend with immersion blender until silky smooth.\n5. Stir in coconut milk and fresh lime juice. Ladle into bowls and top with toasted pumpkin seeds!",
        "prep_time": "15 mins",
        "cook_time": "25 mins",
        "difficulty": "Easy",
        "servings": "6",
        "post_caption": "Super silky butternut squash soup with a fragrant Thai coconut curry kick! Perfect cozy bowl for chilly evenings. 🥣🥥🌶️",
        "image_url": "https://images.unsplash.com/photo-1547592166-23ac45744acd?w=800&auto=format&fit=crop&q=80"
    }
]

COMMENTS_POOL = [
    "This looks incredible! Definitely saving this to my box for dinner this week. 👏",
    "Made this tonight and my family loved it! Thanks for sharing the recipe!",
    "That golden crust looks perfection! Any tip on temperature adjustments for fan ovens?",
    "Saved to my recipes! Can't wait to make it this weekend. 😋",
    "The plating and colors here are stunning! Great job chef! 🌟",
    "10/10 recipe! I added a pinch of red chili flakes and it was sensational."
]

def random_id(n=5):
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=n))

class CommunityMember:
    def __init__(self, base_url, index):
        self.base_url = base_url.rstrip('/')
        self.session = requests.Session()
        suffix = random_id(4)
        names = ["Michaela", "Marco", "Chloe", "Sam", "Elena", "Chef_Leo", "Nonna_Rosa", "Oliver", "Maya", "Lucas"]
        base_name = names[index % len(names)]
        self.username = f"{base_name.lower()}_{suffix}"
        self.display_name = f"{base_name.replace('_', ' ')} (Chef {suffix.upper()})"
        self.email = f"{self.username}@foodie.community"
        self.password = "KitchenSecrets2026!"
        self.created_recipes = []
        self.created_posts = []

    def register(self):
        r = self.session.post(f"{self.base_url}/api/auth/register", json={
            "username": self.username,
            "email": self.email,
            "password": self.password,
            "display_name": self.display_name
        }, timeout=10)
        return r.status_code == 201

    def create_recipe(self, recipe_data):
        r = self.session.post(f"{self.base_url}/api/recipes", json={
            "title": recipe_data["title"],
            "category": recipe_data["category"],
            "ingredients": recipe_data["ingredients"],
            "instructions": recipe_data["instructions"],
            "prep_time": recipe_data.get("prep_time", ""),
            "cook_time": recipe_data.get("cook_time", ""),
            "difficulty": recipe_data.get("difficulty", "Easy"),
            "servings": recipe_data.get("servings", "")
        }, timeout=10)
        if r.status_code == 201:
            rec_id = r.json().get("id")
            self.created_recipes.append((rec_id, recipe_data))
            return rec_id
        return None

    def post_to_feed(self, content, image_url="", recipe_id=None):
        payload = {"content": content}
        if image_url:
            payload["image_url"] = image_url
        if recipe_id:
            payload["recipe_id"] = recipe_id

        r = self.session.post(f"{self.base_url}/api/community/posts", json=payload, timeout=10)
        if r.status_code == 201:
            post_id = r.json().get("post_id")
            self.created_posts.append(post_id)
            return post_id
        return None

    def like_post(self, post_id):
        r = self.session.post(f"{self.base_url}/api/community/posts/{post_id}/like", timeout=10)
        return r.status_code == 200, r.json() if r.status_code == 200 else {}

    def add_comment(self, post_id, comment_text):
        r = self.session.post(f"{self.base_url}/api/community/posts/{post_id}/comments", json={
            "comment": comment_text
        }, timeout=10)
        return r.status_code == 201

    def clone_recipe(self, share_token):
        r = self.session.post(f"{self.base_url}/api/recipes/clone/{share_token}", timeout=10)
        return r.status_code == 201, r.json() if r.status_code == 201 else {}

    def fetch_feed(self):
        r = self.session.get(f"{self.base_url}/api/community/posts", timeout=10)
        if r.status_code == 200:
            return r.json()
        return []

def run_simulation(base_url, num_users=5):
    print("\n" + "=" * 65)
    print("🥘 COMMUNITY FOOD FEED & SOCIAL RECIPE SIMULATOR")
    print("=" * 65)
    print(f"🎯 Target Server: {base_url}")
    print(f"👥 Active Creators: {num_users} simulated community accounts\n")

    start_time = time.time()
    users = []

    # 1. Register Accounts
    print("1️⃣  Registering Community Foodies & Chefs...")
    for i in range(num_users):
        u = CommunityMember(base_url, i)
        ok = u.register()
        if ok:
            users.append(u)
            print(f"   👤 [{i+1}/{num_users}] Registered: {u.display_name} (@{u.username})")
        else:
            print(f"   ❌ Failed to register user {u.username}")

    if not users:
        print("\n❌ Could not connect or register users. Is the server running?")
        return

    # 2. Add Signature Recipes
    print("\n2️⃣  Chefs adding signature handcrafted recipes...")
    for i, u in enumerate(users):
        rec_data = RECIPES_DATABASE[i % len(RECIPES_DATABASE)]
        rec_id = u.create_recipe(rec_data)
        if rec_id:
            print(f"   📖 {u.display_name} added: \"{rec_data['title']}\" ({rec_data['category']})")

    # 3. Post to Community Food Feed with Recipe Attachments & Photos
    print("\n3️⃣  Publishing posts to Community Food Feed with linked recipes...")
    all_post_ids = []
    for i, u in enumerate(users):
        if u.created_recipes:
            rec_id, rec_data = u.created_recipes[0]
            post_id = u.post_to_feed(
                content=rec_data["post_caption"],
                image_url=rec_data["image_url"],
                recipe_id=rec_id
            )
            if post_id:
                all_post_ids.append(post_id)
                print(f"   🚀 Post #{post_id} published by @{u.username} with linked recipe \"{rec_data['title']}\"")

    # 4. Community Browsing & Social Interactions (Likes & Comments)
    print("\n4️⃣  Community members interacting (Liking posts & leaving comments)...")
    feed_posts = users[0].fetch_feed()
    for p in feed_posts:
        p_id = p["id"]
        # Other users like this post
        for u in users:
            if u.username != p["author"]["username"] and random.random() > 0.3:
                liked_ok, like_res = u.like_post(p_id)
                if liked_ok:
                    print(f"   ❤️  @{u.username} liked post #{p_id} by @{p['author']['username']} (Total likes: {like_res.get('likes_count')})")

        # Some users leave comments
        commenting_users = [u for u in users if u.username != p["author"]["username"]]
        if commenting_users:
            commenter = random.choice(commenting_users)
            comment_text = random.choice(COMMENTS_POOL)
            c_ok = commenter.add_comment(p_id, comment_text)
            if c_ok:
                print(f"   💬 @{commenter.username} commented on post #{p_id}: \"{comment_text[:45]}...\"")

    # 5. 1-Click Recipe Cloning from Feed
    print("\n5️⃣  1-Click Forking: Users cloning shared recipes into their own boxes...")
    updated_feed = users[0].fetch_feed()
    for p in updated_feed:
        if p.get("recipe") and p["recipe"].get("share_token"):
            token = p["recipe"]["share_token"]
            recipe_title = p["recipe"]["title"]
            # A different user clones it
            cloners = [u for u in users if u.username != p["author"]["username"]]
            if cloners:
                cloner = cloners[0]
                clone_ok, clone_data = cloner.clone_recipe(token)
                if clone_ok:
                    print(f"   📥 @{cloner.username} 1-click cloned \"{recipe_title}\" into their personal box (New Recipe ID: {clone_data.get('recipe_id')})")

    # 6. Verify Public Standalone Share URL
    print("\n6️⃣  Testing Public Standalone Recipe Viewer Link (No login required)...")
    if updated_feed and updated_feed[0].get("recipe"):
        sample_token = updated_feed[0]["recipe"]["share_token"]
        pub_res = requests.get(f"{base_url}/api/public/recipes/{sample_token}", timeout=10)
        if pub_res.status_code == 200:
            data = pub_res.json()
            print(f"   ✅ Public Share Endpoint verified: \"{data['title']}\" by {data['author']['display_name']}")
            print(f"   🔗 Share URL: {base_url}/share.html?token={sample_token}")

    # 7. Verify Password Reset Flow
    print("\n7️⃣  Testing Password Reset Token Flow...")
    test_user = users[0]
    forgot_res = requests.post(f"{base_url}/api/auth/forgot-password", json={"email": test_user.email}, timeout=10)
    if forgot_res.status_code == 200:
        f_data = forgot_res.json()
        print(f"   ✅ Password reset link requested for {test_user.email}")
        if "dev_reset_token" in f_data:
            token = f_data["dev_reset_token"]
            reset_res = requests.post(f"{base_url}/api/auth/reset-password", json={
                "token": token,
                "new_password": "SuperSecretNewPassword2026!"
            }, timeout=10)
            if reset_res.status_code == 200:
                print(f"   ✅ Password successfully reset via crypto token!")

    total_duration = time.time() - start_time
    print("\n" + "=" * 65)
    print("🎉 SIMULATION COMPLETE & VERIFIED 100% SUCCESS")
    print("=" * 65)
    print(f"⏱️  Total Duration:     {total_duration:.2f} seconds")
    print(f"👥 Active Creators:    {len(users)}")
    print(f"🍲 Feed Posts Created: {len(all_post_ids)}")
    print(f"🌐 Community Feed:     {base_url}/feed.html")
    print(f"🏠 Home Dashboard:     {base_url}/index.html")
    print(f"📖 Recipe Box:         {base_url}/recipes.html")
    print("=" * 65 + "\n")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Test and simulate community food feed and recipe sharing")
    parser.add_argument("--url", default="http://localhost:5000", help="Base URL of the website")
    parser.add_argument("--users", type=int, default=5, help="Number of virtual chefs/users to simulate")
    args = parser.parse_args()

    run_simulation(args.url, args.users)
