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

    def test_05_direct_photo_upload(self):
        # Login as Michaela
        self.client.post('/api/auth/login', json={
            'username': 'chef_michaela',
            'password': 'Password123!'
        })

        # Test base64 image upload
        import base64
        fake_png_bytes = b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82'
        base64_str = "data:image/png;base64," + base64.b64encode(fake_png_bytes).decode('utf-8')

        upload_res = self.client.post('/api/upload/image', json={
            'image_data': base64_str
        })
        self.assertEqual(upload_res.status_code, 201)
        upload_data = upload_res.get_json()
        self.assertIn('image_url', upload_data)
        self.assertTrue(upload_data['image_url'].startswith('/api/uploads/'))

        # Fetch uploaded image
        img_fetch = self.client.get(upload_data['image_url'])
        self.assertEqual(img_fetch.status_code, 200)

    def test_06_threaded_nested_comments(self):
        # Login as Michaela
        self.client.post('/api/auth/login', json={
            'username': 'chef_michaela',
            'password': 'Password123!'
        })

        # Create a post
        post_res = self.client.post('/api/community/posts', json={
            'content': 'Who loves sourdough baking? Any favorite hydration percentages?'
        })
        self.assertEqual(post_res.status_code, 201)
        post_id = post_res.get_json()['post_id']

        # Michaela adds top-level comment
        c1_res = self.client.post(f'/api/community/posts/{post_id}/comments', json={
            'comment': 'I usually start beginners with 70% hydration.'
        })
        self.assertEqual(c1_res.status_code, 201)
        c1_id = c1_res.get_json()['comment']['id']

        # Login as Alex and reply directly to c1
        self.client.post('/api/auth/logout')
        self.client.post('/api/auth/login', json={
            'username': 'chef_alex',
            'password': 'BrandNewPassword123!'
        })

        reply_res = self.client.post(f'/api/community/posts/{post_id}/comments', json={
            'comment': '70% is great! Do you do cold retard overnight?',
            'parent_id': c1_id,
            'reply_to_username': 'chef_michaela'
        })
        self.assertEqual(reply_res.status_code, 201)
        reply_id = reply_res.get_json()['comment']['id']

        # Get comments and verify nested structure
        comments_res = self.client.get(f'/api/community/posts/{post_id}/comments')
        self.assertEqual(comments_res.status_code, 200)
        comments = comments_res.get_json()
        self.assertEqual(len(comments), 1)  # 1 top-level
        self.assertEqual(comments[0]['id'], c1_id)
        self.assertEqual(len(comments[0]['replies']), 1)  # 1 nested reply
        self.assertEqual(comments[0]['replies'][0]['id'], reply_id)
        self.assertEqual(comments[0]['replies'][0]['reply_to_username'], 'chef_michaela')

    def test_07_friends_close_friends_and_recipe_box_visibility(self):
        # Michaela logs in and creates recipes with different visibilities
        self.client.post('/api/auth/logout')
        self.client.post('/api/auth/login', json={
            'username': 'chef_michaela',
            'password': 'Password123!'
        })
        me_res = self.client.get('/api/auth/me')
        michaela_id = me_res.get_json()['user']['id']

        # Public recipe
        self.client.post('/api/recipes', json={
            'title': 'Public Guacamole',
            'ingredients': 'Avocados, lime, salt',
            'instructions': 'Mash and serve',
            'visibility': 'public'
        })
        # Close friends only recipe
        self.client.post('/api/recipes', json={
            'title': 'Secret Family Brownies',
            'ingredients': 'Dark chocolate, butter, sugar, espresso',
            'instructions': 'Bake at 350F for 22m',
            'visibility': 'close_friends'
        })
        # Private recipe
        self.client.post('/api/recipes', json={
            'title': 'My Private Diary Stew',
            'ingredients': 'Mystery ingredient',
            'instructions': 'Top secret',
            'visibility': 'private'
        })

        # Alex logs in
        self.client.post('/api/auth/logout')
        self.client.post('/api/auth/login', json={
            'username': 'chef_alex',
            'password': 'BrandNewPassword123!'
        })

        # Alex follows Michaela
        follow_res = self.client.post(f'/api/friends/{michaela_id}')
        self.assertEqual(follow_res.status_code, 201)

        # Before Michaela designates Alex as close friend:
        # Alex views Michaela's Recipe Box -> only sees Public
        box1 = self.client.get(f'/api/users/{michaela_id}/recipes').get_json()
        box1_titles = [r['title'] for r in box1['recipes']]
        self.assertIn('Public Guacamole', box1_titles)
        self.assertNotIn('Secret Family Brownies', box1_titles)
        self.assertNotIn('My Private Diary Stew', box1_titles)

        # Now Michaela logs in and stars Alex as a Close Friend!
        self.client.post('/api/auth/logout')
        self.client.post('/api/auth/login', json={
            'username': 'chef_michaela',
            'password': 'Password123!'
        })
        me_alex = self.client.get('/api/auth/me')
        # Get alex id
        self.client.post('/api/auth/logout')
        self.client.post('/api/auth/login', json={
            'username': 'chef_alex',
            'password': 'BrandNewPassword123!'
        })
        alex_id = self.client.get('/api/auth/me').get_json()['user']['id']

        self.client.post('/api/auth/logout')
        self.client.post('/api/auth/login', json={
            'username': 'chef_michaela',
            'password': 'Password123!'
        })
        toggle_cf = self.client.post(f'/api/friends/{alex_id}/toggle-close-friend')
        self.assertEqual(toggle_cf.status_code, 200)
        self.assertTrue(toggle_cf.get_json()['is_close_friend'])

        # Alex logs back in and views Michaela's Recipe Box -> sees Public + Close Friends!
        self.client.post('/api/auth/logout')
        self.client.post('/api/auth/login', json={
            'username': 'chef_alex',
            'password': 'BrandNewPassword123!'
        })
        box2 = self.client.get(f'/api/users/{michaela_id}/recipes').get_json()
        box2_titles = [r['title'] for r in box2['recipes']]
        self.assertIn('Public Guacamole', box2_titles)
        self.assertIn('Secret Family Brownies', box2_titles)
        self.assertNotIn('My Private Diary Stew', box2_titles)
        self.assertTrue(box2['user']['they_made_me_close_friend'])

    def test_08_feed_filtering_and_moderation_quarantine(self):
        # Register user 3 (Sam) and user 4 (Jordan)
        self.client.post('/api/auth/register', json={
            'username': 'chef_sam',
            'email': 'sam@test.com',
            'password': 'Password123!'
        })
        self.client.post('/api/auth/register', json={
            'username': 'chef_jordan',
            'email': 'jordan@test.com',
            'password': 'Password123!'
        })

        # Login as Sam and create a bad spam post
        self.client.post('/api/auth/login', json={
            'username': 'chef_sam',
            'password': 'Password123!'
        })
        spam_res = self.client.post('/api/community/posts', json={
            'content': 'Spam post: click here for free gift cards www.badlink.xyz'
        })
        spam_post_id = spam_res.get_json()['post_id']

        # Report 1 by Alex
        self.client.post('/api/auth/logout')
        self.client.post('/api/auth/login', json={
            'username': 'chef_alex',
            'password': 'BrandNewPassword123!'
        })
        r1 = self.client.post(f'/api/community/posts/{spam_post_id}/report', json={'reason': 'spam'})
        self.assertEqual(r1.status_code, 200)
        self.assertFalse(r1.get_json()['quarantined'])

        # Report 2 by Michaela
        self.client.post('/api/auth/logout')
        self.client.post('/api/auth/login', json={
            'username': 'chef_michaela',
            'password': 'Password123!'
        })
        r2 = self.client.post(f'/api/community/posts/{spam_post_id}/report', json={'reason': 'spam'})
        self.assertEqual(r2.status_code, 200)
        self.assertFalse(r2.get_json()['quarantined'])

        # Report 3 by Jordan -> triggers auto-quarantine!
        self.client.post('/api/auth/logout')
        self.client.post('/api/auth/login', json={
            'username': 'chef_jordan',
            'password': 'Password123!'
        })
        r3 = self.client.post(f'/api/community/posts/{spam_post_id}/report', json={'reason': 'spam'})
        self.assertEqual(r3.status_code, 200)
        self.assertTrue(r3.get_json()['quarantined'])

        # Confirm post is no longer returned in the public feed
        feed_res = self.client.get('/api/community/posts')
        feed_ids = [p['id'] for p in feed_res.get_json()]
        self.assertNotIn(spam_post_id, feed_ids)

    def test_09_my_posts_hub_and_user_stats(self):
        # Michaela logs in
        self.client.post('/api/auth/logout')
        self.client.post('/api/auth/login', json={
            'username': 'chef_michaela',
            'password': 'Password123!'
        })

        # Michaela publishes a post
        p1 = self.client.post('/api/community/posts', json={
            'content': 'Michaela sourdough post for testing My Posts hub!'
        })
        self.assertEqual(p1.status_code, 201)
        p1_id = p1.get_json()['post_id']

        # Check Michaela's stats
        stats_res = self.client.get('/api/users/me/stats')
        self.assertEqual(stats_res.status_code, 200)
        stats = stats_res.get_json()
        self.assertEqual(stats['username'], 'chef_michaela')
        self.assertTrue(stats['posts_count'] >= 1)
        self.assertTrue(stats['recipes_count'] >= 1)
        self.assertIn('likes_received', stats)
        self.assertIn('comments_received', stats)
        self.assertIn('friends_count', stats)
        self.assertIn('close_friends_count', stats)

        # Michaela gets her own posts via filter=my_posts
        my_posts_res = self.client.get('/api/community/posts?filter=my_posts')
        self.assertEqual(my_posts_res.status_code, 200)
        my_posts = my_posts_res.get_json()
        self.assertTrue(len(my_posts) >= 1)
        for post in my_posts:
            self.assertEqual(post['author']['username'], 'chef_michaela')
            self.assertTrue(post['is_mine'])

        # Alex logs in
        self.client.post('/api/auth/logout')
        self.client.post('/api/auth/login', json={
            'username': 'chef_alex',
            'password': 'BrandNewPassword123!'
        })

        # Alex publishes a post
        p2 = self.client.post('/api/community/posts', json={
            'content': 'Alex specialty chocolate chip cookies!'
        })
        self.assertEqual(p2.status_code, 201)
        p2_id = p2.get_json()['post_id']

        # Alex calls filter=my_posts -> only sees Alex's posts
        alex_my_posts_res = self.client.get('/api/community/posts?filter=my_posts')
        self.assertEqual(alex_my_posts_res.status_code, 200)
        alex_my_posts = alex_my_posts_res.get_json()
        self.assertTrue(len(alex_my_posts) >= 1)
        for post in alex_my_posts:
            self.assertEqual(post['author']['username'], 'chef_alex')
            self.assertTrue(post['is_mine'])
            self.assertNotEqual(post['id'], p1_id)

if __name__ == '__main__':
    unittest.main()

