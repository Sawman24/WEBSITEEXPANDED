import random
import string
from locust import HttpUser, task, between

def random_id(n=6):
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=n))

class VirtualCookbookUser(HttpUser):
    # Wait between 0.5 to 2.0 seconds between user actions (realistic simulation)
    wait_time = between(0.5, 2.0)

    def on_start(self):
        """Called automatically when each virtual user spawns - Registers and creates a session"""
        self.username = f"chef_{random_id()}"
        self.email = f"{self.username}@testload.com"
        self.password = "LoadTestPass123!"

        res = self.client.post("/api/auth/register", json={
            "username": self.username,
            "email": self.email,
            "password": self.password,
            "display_name": f"Chef {self.username.upper()}"
        })
        
        # Initial recipe creation
        if res.status_code == 201:
            self.client.post("/api/recipes", json={
                "title": f"Starter Recipe for {self.username}",
                "ingredients": "- 2 cups flour\n- 1 cup water\n- 1 tsp salt",
                "instructions": "1) Mix all ingredients.\n2) Knead dough.\n3) Bake at 400F.",
                "category": "Breads & Baking",
                "prep_time": "15 mins",
                "cook_time": "30 mins",
                "difficulty": "Easy"
            })

    @task(6)
    def browse_recipes(self):
        """Simulates browsing recipe cards and search filtering (most frequent action)"""
        self.client.get("/api/recipes", name="/api/recipes (Browse)")

    @task(4)
    def view_dashboard_and_planner(self):
        """Simulates viewing the upcoming meals and weekly calendar"""
        self.client.get("/api/planner", name="/api/planner (View)")

    @task(3)
    def check_grocery_list(self):
        """Simulates checking off groceries"""
        self.client.get("/api/groceries", name="/api/groceries (View)")

    @task(2)
    def view_pantry(self):
        """Simulates opening the What Can I Make? pantry tracker"""
        self.client.get("/api/pantry", name="/api/pantry (View)")

    @task(2)
    def add_new_recipe(self):
        """Simulates adding a new customized recipe"""
        dish_names = ["Garlic Butter Pasta", "Crispy Chicken Tacos", "Avocado Toast", "Beef Stir-Fry", "Berry Smoothie"]
        dish = random.choice(dish_names)
        self.client.post("/api/recipes", json={
            "title": f"{dish} #{random.randint(1, 999)}",
            "ingredients": "- 1 lb main ingredient\n- 2 tbsp olive oil\n- Spices to taste",
            "instructions": "1) Prep ingredients.\n2) Cook thoroughly.\n3) Garnish and serve warm.",
            "category": "Mains & Entrees",
            "prep_time": "10 mins",
            "cook_time": "20 mins",
            "difficulty": random.choice(["Easy", "Medium", "Hard"])
        }, name="/api/recipes (Add)")

    @task(1)
    def save_weekly_plan(self):
        """Simulates planning a meal on a specific date"""
        day = random.randint(1, 28)
        date_str = f"2026-09-{day:02d}"
        self.client.post(f"/api/planner/{date_str}", json={
            "meals": {
                "breakfast": "Scrambled Eggs & Toast",
                "lunch": "Turkey Club Sandwich",
                "dinner": "Grilled Salmon"
            },
            "tasks": "1) Defrost fish\n2) Prep salad",
            "notes": "Healthy dinner night"
        }, name="/api/planner/[date] (Save)")
