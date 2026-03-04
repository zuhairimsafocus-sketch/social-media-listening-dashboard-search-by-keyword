"""
Apify Social Media Scraper Integration
Detect public posts from Facebook, Instagram, TikTok based on keywords

UPDATE: Tambah multiple Facebook actor fallback chain
- Primary: scraper_one/facebook-posts-search
- Fallback 1: powerai/facebook-post-search-scraper (up to 5000 results)
- Fallback 2: alien_force/facebook-search-scraper (with date filter)
- Fallback 3: memo23/apify-facebook-post-search-scraper
- Fallback 4: easyapi/facebook-posts-search-scraper (legacy)
"""

from apify_client import ApifyClient
import pandas as pd
from datetime import datetime
import time
import re
import traceback

class ApifySocialScraper:
    """Wrapper for Apify social media scrapers"""
    
    def __init__(self, api_token, api_token_fb=None):
        """
        Initialize Apify client
        
        Args:
            api_token: Your Apify API token (for Instagram & TikTok)
            api_token_fb: Separate Apify API token for Facebook (optional)
        """
        self.client = ApifyClient(api_token)
        # Use separate client for Facebook if token provided
        if api_token_fb:
            self.client_fb = ApifyClient(api_token_fb)
            print("✅ Using separate API token for Facebook")
        else:
            self.client_fb = self.client
            print("ℹ️ Using same API token for all platforms")
    
    def search_instagram_hashtag(self, keyword, limit=20):
        """
        Search Instagram posts by hashtag
        """
        try:
            hashtag = keyword.replace(" ", "").lower()
            print(f"🔍 Searching Instagram for: #{hashtag}")
            
            run_input = {
                "hashtags": [hashtag],
                "resultsLimit": limit
            }
            
            run = self.client.actor("apify/instagram-hashtag-scraper").call(
                run_input=run_input
            )
            
            posts = []
            raw_items_ig = list(self.client.dataset(run["defaultDatasetId"]).iterate_items())
            
            # === DEBUG: Log first IG item to check for location fields ===
            if raw_items_ig:
                print(f"📊 [Instagram] First item keys: {list(raw_items_ig[0].keys())}")
                item0 = raw_items_ig[0]
                for k, v in item0.items():
                    location_keywords = ['location', 'city', 'place', 'region', 'country', 
                                         'geo', 'lat', 'lng', 'address', 'locale']
                    if any(lk in k.lower() for lk in location_keywords):
                        print(f"  📍 [Instagram] {k} ({type(v).__name__}): {str(v)[:300]}")
            
            for item in raw_items_ig:
                posts.append({
                    'platform': 'Instagram',
                    'keyword': keyword,
                    'content': item.get('caption', '')[:200],
                    'author': item.get('ownerUsername', 'Unknown'),
                    'likes': item.get('likesCount', 0),
                    'comments': item.get('commentsCount', 0),
                    'url': item.get('url', ''),
                    'image_url': item.get('displayUrl', ''),
                    'date': item.get('timestamp', ''),
                    'hashtags': ', '.join(item.get('hashtags', [])[:5])
                })
            
            print(f"✅ Found {len(posts)} Instagram posts for #{hashtag}")
            
            # Filter irrelevant posts
            relevant = [p for p in posts if self._is_relevant(p, keyword)]
            if len(relevant) < len(posts):
                print(f"🔍 Relevance filter: {len(posts)} → {len(relevant)} Instagram posts")
            return relevant
        
        except Exception as e:
            print(f"❌ Instagram error for '{keyword}': {str(e)}")
            return []
    
    def search_x_twitter(self, keyword, limit=20):
        """
        Search X (Twitter) posts by keyword + hashtag.
        Cuba multiple actors secara bergilir.
        """
        actor_methods = [
            ("altimis/scweet", self._x_scweet),
            ("watcher.data/search-x-by-keywords", self._x_watcher),
            ("epctex/twitter-search-scraper", self._x_epctex),
        ]
        
        request_limit = max(limit + 5, 10)
        
        for actor_name, actor_method in actor_methods:
            try:
                print(f"\n🐦 X/Twitter: Trying actor '{actor_name}'...")
                posts = actor_method(keyword, request_limit)
                
                if posts and len(posts) > 0:
                    # Filter relevan
                    before_filter = len(posts)
                    relevant_posts = [p for p in posts if self._is_relevant(p, keyword)]
                    after_filter = len(relevant_posts)
                    removed = before_filter - after_filter
                    
                    if removed > 0:
                        print(f"🔍 Relevance filter: {before_filter} → {after_filter} X posts ({removed} irrelevant removed)")
                    
                    if relevant_posts:
                        final_posts = relevant_posts[:limit]
                        print(f"✅ X/Twitter SUCCESS with '{actor_name}': {len(final_posts)} relevant posts")
                        return final_posts
                    else:
                        print(f"⚠️ X/Twitter '{actor_name}' returned {before_filter} posts but 0 relevant, trying next...")
                        continue
                else:
                    print(f"⚠️ X/Twitter '{actor_name}' returned 0 posts, trying next...")
                    continue
                    
            except Exception as e:
                error_msg = str(e).lower()
                print(f"❌ X/Twitter '{actor_name}' failed: {str(e)[:200]}")
                
                if 'rate limit' in error_msg:
                    print(f"   ⏳ Rate limit hit — trying next actor...")
                elif 'free trial' in error_msg or 'rent' in error_msg or 'expired' in error_msg:
                    print(f"   💰 Actor requires payment — trying next actor...")
                else:
                    print(f"   ❓ Error — trying next actor...")
                
                continue
        
        print("❌ ALL X/Twitter actors failed! No posts retrieved.")
        return []
    
    def _parse_x_item(self, item, keyword):
        """Parse an X/Twitter item from any actor into standard format"""
        # Extract AUTHOR - try multiple field names
        author = (item.get('author', '') or item.get('user', '') or 
                  item.get('username', '') or item.get('screen_name', '') or
                  item.get('authorName', '') or item.get('userScreenName', '') or 'Unknown')
        if isinstance(author, dict):
            author = author.get('username', author.get('screen_name', author.get('name', 'Unknown')))
        author = str(author) if author else 'Unknown'
        
        # Extract CONTENT
        content = ''
        content_fields = ['text', 'full_text', 'tweet_text', 'content', 'body', 
                          'tweetText', 'rawContent', 'renderedContent']
        for field in content_fields:
            val = item.get(field)
            if val and str(val) != 'nan' and str(val).strip():
                content = str(val)[:200]
                break
        
        # Extract engagement
        likes = item.get('likeCount', item.get('favorite_count', item.get('likes', 
                item.get('favouritesCount', item.get('favoriteCount', 0)))))
        comments = item.get('replyCount', item.get('reply_count', item.get('replies', 
                   item.get('repliesCount', 0))))
        retweets = item.get('retweetCount', item.get('retweet_count', item.get('retweets', 
                   item.get('retweetsCount', 0))))
        views = item.get('viewCount', item.get('views', item.get('viewsCount', 0)))
        
        try:
            likes = int(likes) if likes and str(likes) != 'nan' else 0
        except (ValueError, TypeError):
            likes = 0
        try:
            comments = int(comments) if comments and str(comments) != 'nan' else 0
        except (ValueError, TypeError):
            comments = 0
        try:
            retweets = int(retweets) if retweets and str(retweets) != 'nan' else 0
        except (ValueError, TypeError):
            retweets = 0
        try:
            views = int(views) if views and str(views) != 'nan' else 0
        except (ValueError, TypeError):
            views = 0
        
        # Extract URL
        url = item.get('url', item.get('tweetUrl', item.get('link', '')))
        if not url:
            tweet_id = item.get('id', item.get('tweetId', item.get('id_str', '')))
            if tweet_id and author and author != 'Unknown':
                url = f"https://x.com/{author}/status/{tweet_id}"
        
        # Extract DATE
        date = item.get('date', item.get('created_at', item.get('timestamp', 
               item.get('createdAt', item.get('datetime', '')))))
        if date and isinstance(date, (int, float)) and date > 0:
            try:
                if date > 10000000000:
                    date = datetime.fromtimestamp(date / 1000).isoformat()
                else:
                    date = datetime.fromtimestamp(date).isoformat()
            except (ValueError, OSError):
                date = ''
        elif date and str(date) == 'nan':
            date = ''
        
        # Extract hashtags
        hashtags = ''
        hashtag_data = item.get('hashtags', item.get('entities', {}).get('hashtags', []))
        if isinstance(hashtag_data, list):
            tag_names = []
            for h in hashtag_data[:5]:
                if isinstance(h, str):
                    tag_names.append(h)
                elif isinstance(h, dict):
                    tag_names.append(h.get('tag', h.get('text', '')))
            hashtags = ', '.join([t for t in tag_names if t])
        
        if not hashtags and content:
            found_tags = re.findall(r'#(\w+)', content)
            hashtags = ', '.join(found_tags[:5])
        
        # Extract location (if available from user profile)
        location = item.get('location', item.get('userLocation', 
                   item.get('author_location', item.get('geo', ''))))
        if isinstance(location, dict):
            location = location.get('name', location.get('full_name', ''))
        
        return {
            'platform': 'X',
            'keyword': keyword,
            'content': content if content and str(content) != 'nan' else '(no text)',
            'author': author if author and str(author) != 'nan' else 'Unknown',
            'likes': likes,
            'comments': comments,
            'shares': retweets,
            'views': views,
            'url': url if url and str(url) != 'nan' else '',
            'date': date if date and str(date) != 'nan' else '',
            'hashtags': hashtags,
            'user_location': str(location) if location and str(location) != 'nan' else ''
        }
    
    def _x_scweet(self, keyword, limit=20):
        """Primary: altimis/scweet - keyword + hashtag search"""
        print(f"🔍 [scweet] Searching X for: {keyword}")
        
        hashtag = keyword.replace(" ", "")
        
        run_input = {
            "source_mode": "search",
            "any_words": keyword.split(),
            "hashtags_any": [hashtag],
            "search_sort": "Latest",
            "max_items": limit
        }
        
        run = self.client.actor("altimis/scweet").call(run_input=run_input)
        
        run_status = run.get('status', 'UNKNOWN')
        print(f"📊 [scweet] Run status: {run_status}")
        
        raw_items = list(self.client.dataset(run["defaultDatasetId"]).iterate_items())
        print(f"📊 [scweet] Raw items: {len(raw_items)}")
        
        if not raw_items:
            return []
        
        print(f"📊 [scweet] First item keys: {list(raw_items[0].keys())}")
        self._save_debug_dump("scweet", raw_items)
        
        return [self._parse_x_item(item, keyword) for item in raw_items]
    
    def _x_watcher(self, keyword, limit=20):
        """Fallback 1: watcher.data/search-x-by-keywords"""
        print(f"🔍 [watcher] Searching X for: {keyword}")
        
        hashtag = f"#{keyword.replace(' ', '')}"
        
        run_input = {
            "keywords": [keyword, hashtag],
            "maxItems": limit,
            "sortBy": "latest",
            "includeReplies": False,
            "includeRetweets": False
        }
        
        run = self.client.actor("watcher.data/search-x-by-keywords").call(run_input=run_input)
        
        run_status = run.get('status', 'UNKNOWN')
        print(f"📊 [watcher] Run status: {run_status}")
        
        raw_items = list(self.client.dataset(run["defaultDatasetId"]).iterate_items())
        print(f"📊 [watcher] Raw items: {len(raw_items)}")
        
        if not raw_items:
            return []
        
        print(f"📊 [watcher] First item keys: {list(raw_items[0].keys())}")
        self._save_debug_dump("watcher", raw_items)
        
        return [self._parse_x_item(item, keyword) for item in raw_items]
    
    def _x_epctex(self, keyword, limit=20):
        """Fallback 2: epctex/twitter-search-scraper"""
        print(f"🔍 [epctex] Searching X for: {keyword}")
        
        run_input = {
            "searchTerms": [keyword],
            "maxItems": limit,
            "sort": "Latest"
        }
        
        run = self.client.actor("epctex/twitter-search-scraper").call(run_input=run_input)
        
        run_status = run.get('status', 'UNKNOWN')
        print(f"📊 [epctex] Run status: {run_status}")
        
        raw_items = list(self.client.dataset(run["defaultDatasetId"]).iterate_items())
        print(f"📊 [epctex] Raw items: {len(raw_items)}")
        
        if not raw_items:
            return []
        
        print(f"📊 [epctex] First item keys: {list(raw_items[0].keys())}")
        self._save_debug_dump("epctex", raw_items)
        
        return [self._parse_x_item(item, keyword) for item in raw_items]
    
    # ==============================================================
    # FACEBOOK - Multiple Actor Fallback Chain
    # ==============================================================
    
    def _is_relevant(self, post, keyword):
        """
        Check if a post is actually relevant to the keyword.
        Returns True if post content/hashtags contain at least one keyword word.
        """
        content = str(post.get('content', '')).lower()
        hashtags = str(post.get('hashtags', '')).lower()
        author = str(post.get('author', '')).lower()
        combined = f"{content} {hashtags} {author}"
        
        # Split keyword into individual words
        keyword_words = keyword.lower().strip().split()
        full_phrase = keyword.lower().strip()
        
        # Exact phrase match
        if full_phrase in combined:
            return True
        
        # Untuk multi-word keyword: match kalau MANA-MANA satu word ada
        # (sebelum ni ALL words kena ada — terlalu ketat)
        # Contoh: "line teruk" → post ada "line" ATAU "teruk" = relevant
        if any(word in combined for word in keyword_words):
            return True
        
        return False
    
    def _is_relevant_raw(self, raw_item, keyword):
        """
        Check relevance on RAW item (before parsing).
        Ini penting sebab raw item ada banyak fields yang mungkin
        mengandungi keyword tapi tak masuk dalam parsed 'content'.
        """
        # Gabungkan SEMUA string values dalam raw item
        all_text = ""
        for key, val in raw_item.items():
            if isinstance(val, str):
                all_text += " " + val.lower()
            elif isinstance(val, dict):
                for v2 in val.values():
                    if isinstance(v2, str):
                        all_text += " " + v2.lower()
        
        keyword_words = keyword.lower().strip().split()
        full_phrase = keyword.lower().strip()
        
        if full_phrase in all_text:
            return True
        
        if any(word in all_text for word in keyword_words):
            return True
        
        return False
    
    def search_facebook_posts(self, keyword, limit=20):
        """
        Search Facebook public posts by keyword.
        Cuba multiple actors secara bergilir — kalau satu gagal/rate limit,
        auto cuba yang seterusnya.
        Includes relevance filter to remove unrelated posts.
        """
        # powerai dulu sebab return lebih banyak posts + ada recentPosts option
        actor_methods = [
            ("powerai/facebook-post-search-scraper", self._fb_powerai),
            ("scraper_one/facebook-posts-search", self._fb_scraper_one),
            ("alien_force/facebook-search-scraper", self._fb_alien_force),
            ("memo23/apify-facebook-post-search-scraper", self._fb_memo23),
            ("easyapi/facebook-posts-search-scraper", self._fb_easyapi),
        ]
        
        # Request sedikit lebih untuk buffer selepas relevance filter
        request_limit = max(limit + 5, 10)
        
        for actor_name, actor_method in actor_methods:
            try:
                print(f"\n📘 Facebook: Trying actor '{actor_name}'...")
                raw_items, posts = actor_method(keyword, request_limit, return_raw=True)
                
                if posts and len(posts) > 0:
                    # Filter menggunakan RAW items (lebih banyak fields untuk check)
                    before_filter = len(posts)
                    relevant_posts = []
                    for i, p in enumerate(posts):
                        # Check raw item first (more fields), fallback to parsed post
                        if i < len(raw_items) and self._is_relevant_raw(raw_items[i], keyword):
                            relevant_posts.append(p)
                        elif self._is_relevant(p, keyword):
                            relevant_posts.append(p)
                    
                    after_filter = len(relevant_posts)
                    removed = before_filter - after_filter
                    
                    if removed > 0:
                        print(f"🔍 Relevance filter: {before_filter} → {after_filter} posts ({removed} irrelevant removed)")
                    
                    if relevant_posts:
                        final_posts = relevant_posts[:limit]
                        print(f"✅ Facebook SUCCESS with '{actor_name}': {len(final_posts)} relevant posts")
                        return final_posts
                    else:
                        print(f"⚠️ Facebook '{actor_name}' returned {before_filter} posts but 0 relevant, trying next...")
                        continue
                else:
                    print(f"⚠️ Facebook '{actor_name}' returned 0 posts, trying next...")
                    continue
                    
            except Exception as e:
                error_msg = str(e).lower()
                print(f"❌ Facebook '{actor_name}' failed: {str(e)[:200]}")
                
                if 'rate limit' in error_msg:
                    print(f"   ⏳ Rate limit hit — trying next actor...")
                elif 'free trial' in error_msg or 'rent' in error_msg or 'expired' in error_msg:
                    print(f"   💰 Actor requires payment — trying next actor...")
                elif 'not found' in error_msg:
                    print(f"   🔍 Actor not found — trying next actor...")
                else:
                    print(f"   ❓ Unknown error — trying next actor...")
                
                continue
        
        print("❌ ALL Facebook actors failed! No posts retrieved.")
        print("💡 Tips: Tunggu beberapa jam untuk rate limit reset, atau upgrade Apify plan.")
        return []
    
    def _save_debug_dump(self, actor_name, raw_items, num_items=2):
        """Save raw item dump to file for inspection"""
        try:
            import json
            debug_file = f"debug_fb_{actor_name.replace('/', '_')}.txt"
            with open(debug_file, 'w', encoding='utf-8') as f:
                f.write(f"=== DEBUG DUMP: {actor_name} ===\n")
                f.write(f"Total items: {len(raw_items)}\n")
                f.write(f"First item keys: {list(raw_items[0].keys())}\n\n")
                
                for i, item in enumerate(raw_items[:num_items]):
                    f.write(f"\n{'='*60}\n")
                    f.write(f"ITEM #{i+1}\n")
                    f.write(f"{'='*60}\n")
                    for k, v in item.items():
                        val_str = str(v)[:500]
                        val_type = type(v).__name__
                        location_keywords = ['location', 'city', 'place', 'region', 'country', 
                                             'geo', 'lat', 'lng', 'address', 'locale', 'hometown',
                                             'author', 'profile', 'user', 'title']
                        is_location = any(lk in k.lower() for lk in location_keywords)
                        marker = "📍" if is_location else "  "
                        f.write(f"  {marker} {k} ({val_type}): {val_str}\n")
                    f.write(f"\n")
            
            print(f"💾 Debug dump saved to: {debug_file}")
        except Exception as e:
            print(f"⚠️ Could not save debug dump: {e}")
    
    def _fb_scraper_one(self, keyword, limit=20, return_raw=False):
        """Primary: scraper_one/facebook-posts-search"""
        print(f"🔍 [scraper_one] Searching Facebook for: {keyword}")
        
        run_input = {
            "query": keyword,
            "resultsCount": limit,
            "searchType": "latest"
        }
        
        run = self.client_fb.actor("scraper_one/facebook-posts-search").call(
            run_input=run_input
        )
        
        run_status = run.get('status', 'UNKNOWN')
        print(f"📊 [scraper_one] Run status: {run_status}")
        
        raw_items = list(self.client_fb.dataset(run["defaultDatasetId"]).iterate_items())
        print(f"📊 [scraper_one] Raw items: {len(raw_items)}")
        
        if not raw_items:
            return ([], []) if return_raw else []
        
        print(f"📊 [scraper_one] First item keys: {list(raw_items[0].keys())}")
        self._save_debug_dump("scraper_one", raw_items)
        
        posts = [self._parse_fb_item(item, keyword) for item in raw_items]
        return (raw_items, posts) if return_raw else posts
    
    def _fb_powerai(self, keyword, limit=20, return_raw=False):
        """Fallback 1: powerai/facebook-post-search-scraper (up to 5000 results)"""
        print(f"🔍 [powerai] Searching Facebook for: {keyword}")
        
        run_input = {
            "keyword": keyword,
            "maxResults": limit,
            "recentPosts": True
        }
        
        run = self.client_fb.actor("powerai/facebook-post-search-scraper").call(
            run_input=run_input
        )
        
        run_status = run.get('status', 'UNKNOWN')
        print(f"📊 [powerai] Run status: {run_status}")
        
        raw_items = list(self.client_fb.dataset(run["defaultDatasetId"]).iterate_items())
        print(f"📊 [powerai] Raw items: {len(raw_items)}")
        
        if not raw_items:
            return ([], []) if return_raw else []
        
        print(f"📊 [powerai] First item keys: {list(raw_items[0].keys())}")
        self._save_debug_dump("powerai", raw_items)
        
        posts = [self._parse_fb_item(item, keyword) for item in raw_items]
        return (raw_items, posts) if return_raw else posts
    
    def _fb_alien_force(self, keyword, limit=20, return_raw=False):
        """Fallback 2: alien_force/facebook-search-scraper"""
        print(f"🔍 [alien_force] Searching Facebook for: {keyword}")
        
        run_input = {
            "keyword": keyword,
            "search_type": "posts",
            "max_posts": limit
        }
        
        run = self.client_fb.actor("alien_force/facebook-search-scraper").call(
            run_input=run_input
        )
        
        run_status = run.get('status', 'UNKNOWN')
        print(f"📊 [alien_force] Run status: {run_status}")
        
        raw_items = list(self.client_fb.dataset(run["defaultDatasetId"]).iterate_items())
        print(f"📊 [alien_force] Raw items: {len(raw_items)}")
        
        if not raw_items:
            return ([], []) if return_raw else []
        
        print(f"📊 [alien_force] First item keys: {list(raw_items[0].keys())}")
        
        posts = [self._parse_fb_item(item, keyword) for item in raw_items]
        return (raw_items, posts) if return_raw else posts
    
    def _fb_memo23(self, keyword, limit=20, return_raw=False):
        """Fallback 3: memo23/apify-facebook-post-search-scraper"""
        print(f"🔍 [memo23] Searching Facebook for: {keyword}")
        
        run_input = {
            "searchQuery": keyword,
            "maxResults": limit
        }
        
        run = self.client_fb.actor("memo23/apify-facebook-post-search-scraper").call(
            run_input=run_input
        )
        
        run_status = run.get('status', 'UNKNOWN')
        print(f"📊 [memo23] Run status: {run_status}")
        
        raw_items = list(self.client_fb.dataset(run["defaultDatasetId"]).iterate_items())
        print(f"📊 [memo23] Raw items: {len(raw_items)}")
        
        if not raw_items:
            return ([], []) if return_raw else []
        
        print(f"📊 [memo23] First item keys: {list(raw_items[0].keys())}")
        
        posts = [self._parse_fb_item(item, keyword) for item in raw_items]
        return (raw_items, posts) if return_raw else posts
    
    def _fb_easyapi(self, keyword, limit=20, return_raw=False):
        """Fallback 4 (legacy): easyapi/facebook-posts-search-scraper"""
        print(f"🔍 [easyapi] Searching Facebook for: {keyword}")
        
        run_input = {
            "searchQuery": keyword,
            "maxResults": limit
        }
        
        run = self.client_fb.actor("easyapi/facebook-posts-search-scraper").call(
            run_input=run_input
        )
        
        run_status = run.get('status', 'UNKNOWN')
        print(f"📊 [easyapi] Run status: {run_status}")
        
        raw_items = list(self.client_fb.dataset(run["defaultDatasetId"]).iterate_items())
        print(f"📊 [easyapi] Raw items: {len(raw_items)}")
        
        if not raw_items:
            return ([], []) if return_raw else []
        
        print(f"📊 [easyapi] First item keys: {list(raw_items[0].keys())}")
        
        posts = [self._parse_fb_item(item, keyword) for item in raw_items]
        return (raw_items, posts) if return_raw else posts
    
    # ==============================================================
    # PARSER - Normalize data from any Facebook actor
    # ==============================================================
    
    def _parse_fb_item(self, item, keyword):
        """Parse a Facebook post item from any actor into standard format"""
        # Extract AUTHOR
        author_raw = item.get('author', item.get('authorName', item.get('facebookName', 
                     item.get('user_name', item.get('userName', 'Unknown')))))
        if isinstance(author_raw, dict):
            author = author_raw.get('name', author_raw.get('displayName', 'Unknown'))
        else:
            author = str(author_raw) if author_raw else 'Unknown'
        
        # Extract CONTENT - try many field names
        content = ''
        content_fields = [
            'postText', 'text', 'message', 'content', 'body', 
            'description', 'caption', 'facebookText', 'post_text',
            'postContent', 'fullText'
        ]
        for field in content_fields:
            val = item.get(field)
            if val and str(val) != 'nan' and str(val).strip():
                content = str(val)[:200]
                break
        
        # Extract engagement - try many field names
        likes = item.get('reactionsCount', item.get('likesCount', item.get('likes', 
                item.get('facebookLikes', item.get('reactions', item.get('like_count', 0))))))
        comments = item.get('commentsCount', item.get('comments', 
                  item.get('facebookComments', item.get('comment_count', 0))))
        shares = item.get('sharesCount', item.get('shares', 
                 item.get('facebookShares', item.get('share_count', 0))))
        
        if isinstance(likes, dict):
            likes = likes.get('count', likes.get('total', 0))
        if isinstance(comments, dict):
            comments = comments.get('count', comments.get('total', 0))
        if isinstance(shares, dict):
            shares = shares.get('count', shares.get('total', 0))
        
        try:
            likes = int(likes) if likes and str(likes) != 'nan' else 0
        except (ValueError, TypeError):
            likes = 0
        try:
            comments = int(comments) if comments and str(comments) != 'nan' else 0
        except (ValueError, TypeError):
            comments = 0
        try:
            shares = int(shares) if shares and str(shares) != 'nan' else 0
        except (ValueError, TypeError):
            shares = 0
        
        # Extract URL
        url = item.get('url', item.get('postUrl', item.get('link', 
              item.get('facebookUrl', item.get('post_url', '')))))
        
        # Extract DATE
        date = item.get('timestamp', item.get('time', item.get('date', 
               item.get('facebookDate', item.get('created_time', item.get('publishedAt', ''))))))
        if date and isinstance(date, (int, float)) and date > 0:
            try:
                if date > 10000000000:
                    date = datetime.fromtimestamp(date / 1000).isoformat()
                else:
                    date = datetime.fromtimestamp(date).isoformat()
            except (ValueError, OSError):
                date = ''
        elif date and str(date) == 'nan':
            date = ''
        
        # Extract hashtags
        hashtags = ''
        post_text_full = item.get('postText', item.get('text', item.get('facebookText', 
                         item.get('message', item.get('content', '')))))
        if post_text_full and str(post_text_full) != 'nan':
            found_tags = re.findall(r'#(\w+)', str(post_text_full))
            hashtags = ', '.join(found_tags[:5])
        
        return {
            'platform': 'Facebook',
            'keyword': keyword,
            'content': content if content and str(content) != 'nan' else '(no text)',
            'author': author if author and str(author) != 'nan' else 'Unknown',
            'likes': likes,
            'comments': comments,
            'shares': shares,
            'url': url if url and str(url) != 'nan' else '',
            'date': date if date and str(date) != 'nan' else '',
            'page': author if author else '',
            'hashtags': hashtags
        }
    
    # ==============================================================
    # MULTI-PLATFORM SEARCH
    # ==============================================================
    
    def search_all_platforms(self, keywords, posts_per_keyword=20):
        """
        Search all platforms for multiple keywords
        """
        all_results = []
        
        for keyword in keywords:
            print(f"\n{'='*60}")
            print(f"🔎 Processing keyword: '{keyword}'")
            print(f"{'='*60}")
            
            instagram_posts = self.search_instagram_hashtag(keyword, posts_per_keyword)
            all_results.extend(instagram_posts)
            time.sleep(2)
            
            x_posts = self.search_x_twitter(keyword, posts_per_keyword)
            all_results.extend(x_posts)
            time.sleep(2)
            
            facebook_posts = self.search_facebook_posts(keyword, posts_per_keyword)
            all_results.extend(facebook_posts)
            time.sleep(2)
        
        df = pd.DataFrame(all_results)
        df['scraped_at'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        print(f"\n{'='*60}")
        print(f"✅ TOTAL RESULTS: {len(df)} posts across all platforms")
        print(f"{'='*60}")
        
        return df
    
    def get_summary_stats(self, df):
        """Get summary statistics from results"""
        if df.empty:
            return {}
        
        stats = {
            'total_posts': len(df),
            'by_platform': df['platform'].value_counts().to_dict(),
            'by_keyword': df['keyword'].value_counts().to_dict(),
            'total_engagement': {
                'likes': df['likes'].sum() if 'likes' in df.columns else 0,
                'comments': df['comments'].sum() if 'comments' in df.columns else 0,
                'shares': df.get('shares', pd.Series([0])).sum(),
                'views': df.get('views', pd.Series([0])).sum()
            }
        }
        
        return stats


if __name__ == "__main__":
    import sys
    from apify_credentials import APIFY_API_TOKEN, APIFY_API_TOKEN_FB
    
    scraper = ApifySocialScraper(APIFY_API_TOKEN, api_token_fb=APIFY_API_TOKEN_FB)
    
    if len(sys.argv) > 1:
        custom_keywords = sys.argv[1:]
    else:
        custom_keywords = ["line teruk"]
    
    print(f"🚀 Testing Facebook fallback chain with: {custom_keywords}")
    
    for kw in custom_keywords:
        posts = scraper.search_facebook_posts(kw, limit=10)
        print(f"\n📊 Results for '{kw}': {len(posts)} posts")
        for p in posts[:3]:
            print(f"   - @{p['author']}: {p['content'][:80]}...")