import unittest
import json
import os
import tempfile
import sqlite3

# Import Flask app from recipe_api
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'recipe_api'))

# Use a temporary database for clean test isolation
temp_db_fd, temp_db_path = tempfile.mkstemp(suffix='.db')
os.environ['DATABASE_PATH'] = temp_db_path

from recipe_api.app import app, init_db

class MultiUserAndSocialFeedTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app.config['TESTING'] = True
        app.config['DEBUG'] = False
        cls.client = app.test_client()

    @classmethod
    def tearDownClass(cls):
        os.close(temp_db_fd)
        if os.path.exists(temp_db_path):
            os.remove(temp_db_path)

    def test_01_user_registration_and_auth(self):
        # Register User 1
        res = self.client.post('/api/auth/register', json={
            'username': 'chef_michaela',
            'email': 'michaela@test.com',
            'password': 'Password123!',
            'display_name': 'Michaela Chef'
        })
        self.assertEqual(res.status_code, 201)
        data = res.get_json()
        self.assertEqual(data['user']['username'], 'chef_michaela')
        self.assertEqual(data['user']['display_name'], 'Michaela Chef')

        # Check me
        me_res = self.client.get('/api/auth/me')
        self.assertEqual(me_res.status_code, 200)
        self.assertEqual(me_res.get_json()['user']['username'], 'chef_michaela')

        # Logout
        logout_res = self.client.post('/api/auth/logout')
        self.assertEqual(logout_res.status_code, 200)

        # Confirm unauthenticated
        unauth_me = self.client.get('/api/auth/me')
        self.assertEqual(unauth_me.status_code, 401)

    def test_02_password_reset_flow(self):
        # Register User 2
        self.client.post('/api/auth/register', json={
            'username': 'chef_alex',
            'email': 'alex@test.com',
            'password': 'OriginalPassword123!'
        })
        self.client.post('/api/auth/logout')

        # Request Forgot Password
        forgot_res = self.client.post('/api/auth/forgot-password', json={
            'email': 'alex@test.com'
        })
        self.assertEqual(forgot_res.status_code, 200)
        data = forgot_res.get_json()
        self.assertIn('dev_reset_token', data)
        token = data['dev_reset_token']

        # Reset Password using token
        reset_res = self.client.post('/api/auth/reset-password', json={
            'token': token,
            'new_password': 'BrandNewPassword123!'
        })
        self.assertEqual(reset_res.status_code, 200)

        # Verify old password fails
        old_login = self.client.post('/api/auth/login', json={
            'username': 'chef_alex',
            'password': 'OriginalPassword123!'
        })
        self.assertEqual(old_login.status_code, 401)

        # Verify new password succeeds
        new_login = self.client.post('/api/auth/login', json={
            'username': 'chef_alex',
            'password': 'BrandNewPassword123!'
        })
        self.assertEqual(new_login.status_code, 200)
        self.client.post('/api/auth/logout')

    def test_03_recipe_sharing_and_1click_cloning(self):
        # Login as Michaela
        self.client.post('/api/auth/login', json={
            'username': 'chef_michaela',
            'password': 'Password123!'
        })

        # Add recipe
        add_res = self.client.post('/api/recipes', json={
            'title': 'Grandma Italian Lasagna',
            'category': 'Pasta',
            'ingredients': '1 lb ground beef\n12 lasagna noodles\n2 cups ricotta\n3 cups mozzarella',
            'instructions': '1. Brown the beef.\n2. Layer noodles, ricotta, sauce, and cheese.\n3. Bake at 375F for 45 mins.',
            'prep_time': '25 mins',
            'cook_time': '45 mins',
            'difficulty': 'Medium',
            'servings': '8'
        })
        self.assertEqual(add_res.status_code, 201)
        recipe_id = add_res.get_json()['id']

        # Generate Share Token
        share_res = self.client.post(f'/api/recipes/{recipe_id}/share')
        self.assertEqual(share_res.status_code, 200)
        share_data = share_res.get_json()
        share_token = share_data['share_token']
        self.assertTrue(len(share_token) > 10)

        # Logout Michaela
        self.client.post('/api/auth/logout')

        # Public View (Unauthenticated)
        pub_res = self.client.get(f'/api/public/recipes/{share_token}')
        self.assertEqual(pub_res.status_code, 200)
        pub_data = pub_res.get_json()
        self.assertEqual(pub_data['title'], 'Grandma Italian Lasagna')
        self.assertEqual(pub_data['author']['display_name'], 'Michaela Chef')

        # Login as Alex and 1-Click Clone Recipe
        self.client.post('/api/auth/login', json={
            'username': 'chef_alex',
            'password': 'BrandNewPassword123!'
        })

        clone_res = self.client.post(f'/api/recipes/clone/{share_token}')
        self.assertEqual(clone_res.status_code, 201)
        clone_data = clone_res.get_json()
        cloned_id = clone_data['recipe_id']

        # Verify Alex now has this recipe in their box
        alex_recipes = self.client.get('/api/recipes').get_json()
        alex_recipe_titles = [r['title'] for r in alex_recipes]
        self.assertIn('Grandma Italian Lasagna', alex_recipe_titles)

        # Verify independence: Alex edits their cloned recipe
        self.client.put(f'/api/recipes/{cloned_id}', json={
            'title': 'Grandma Italian Lasagna (Alex Variation - Extra Cheese)'
        })

        # Alex sees modified title
        alex_rec = self.client.get(f'/api/recipes/{cloned_id}').get_json()
        self.assertEqual(alex_rec['title'], 'Grandma Italian Lasagna (Alex Variation - Extra Cheese)')

        # Login back as Michaela and verify Michaela's original is untouched
        self.client.post('/api/auth/logout')
        self.client.post('/api/auth/login', json={
            'username': 'chef_michaela',
            'password': 'Password123!'
        })
        michaela_rec = self.client.get(f'/api/recipes/{recipe_id}').get_json()
        self.assertEqual(michaela_rec['title'], 'Grandma Italian Lasagna')

    def test_04_community_food_feed_and_interactions(self):
        # Michaela is logged in; Michaela gets her recipe id
        m_recipes = self.client.get('/api/recipes').get_json()
        m_recipe_id = m_recipes[0]['id']

        # Michaela publishes a community post linking her recipe
        post_res = self.client.post('/api/community/posts', json={
            'content': 'Made my favorite homemade lasagna tonight! Perfect golden crust and melted cheese. Check out my recipe below! 🧀🍝',
            'image_url': 'https://images.unsplash.com/photo-1574894709920-11b28e7367e3?w=600',
            'recipe_id': m_recipe_id
        })
        self.assertEqual(post_res.status_code, 201)
        post_id = post_res.get_json()['post_id']

        # Logout Michaela and login as Alex
        self.client.post('/api/auth/logout')
        self.client.post('/api/auth/login', json={
            'username': 'chef_alex',
            'password': 'BrandNewPassword123!'
        })

        # Alex views community feed
        feed_res = self.client.get('/api/community/posts')
        self.assertEqual(feed_res.status_code, 200)
        posts = feed_res.get_json()
        self.assertTrue(len(posts) >= 1)
        feed_post = next(p for p in posts if p['id'] == post_id)
        self.assertEqual(feed_post['author']['username'], 'chef_michaela')
        self.assertIsNotNone(feed_post['recipe'])
        self.assertEqual(feed_post['recipe']['title'], 'Grandma Italian Lasagna')
        self.assertEqual(feed_post['likes_count'], 0)
        self.assertEqual(feed_post['liked_by_me'], False)

        # Alex likes Michaela's post
        like_res = self.client.post(f'/api/community/posts/{post_id}/like')
        self.assertEqual(like_res.status_code, 200)
        like_data = like_res.get_json()
        self.assertEqual(like_data['liked'], True)
        self.assertEqual(like_data['likes_count'], 1)

        # Alex adds a comment
        comment_res = self.client.post(f'/api/community/posts/{post_id}/comments', json={
            'comment': 'Looks absolutely incredible Michaela! Just saved it to my recipe box to make this weekend.'
        })
        self.assertEqual(comment_res.status_code, 201)
        comment_id = comment_res.get_json()['comment']['id']

        # Alex views comments
        comments_res = self.client.get(f'/api/community/posts/{post_id}/comments')
        self.assertEqual(comments_res.status_code, 200)
        comments = comments_res.get_json()
        self.assertEqual(len(comments), 1)
        self.assertEqual(comments[0]['author']['username'], 'chef_alex')
        self.assertEqual(comments[0]['is_mine'], True)

        # Alex deletes their comment
        del_comment = self.client.delete(f'/api/community/comments/{comment_id}')
        self.assertEqual(del_comment.status_code, 200)

        # Alex attempts to delete Michaela's post -> should fail (404 / unauthorized)
        del_post_alex = self.client.delete(f'/api/community/posts/{post_id}')
        self.assertEqual(del_post_alex.status_code, 404)

        # Michaela logs in and deletes her post -> succeeds
        self.client.post('/api/auth/logout')
        self.client.post('/api/auth/login', json={
            'username': 'chef_michaela',
            'password': 'Password123!'
        })
        del_post_michaela = self.client.delete(f'/api/community/posts/{post_id}')
        self.assertEqual(del_post_michaela.status_code, 200)

if __name__ == '__main__':
    unittest.main()
