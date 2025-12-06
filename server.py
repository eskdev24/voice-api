#!/usr/bin/env python3
"""
Buyvia Voice Recognition Service
Simple Flask server using Google Speech Recognition
Optimized for Ghanaian English accents
PERFORMANCE OPTIMIZED - Target: <1.5s response time
"""

import os
import io
import re
import tempfile
import logging
import time
from functools import lru_cache
from flask import Flask, request, jsonify
from flask_cors import CORS
import speech_recognition as sr
from pydub import AudioSegment
try:
    from rapidfuzz import process, fuzz
    FUZZY_AVAILABLE = True
except ImportError:
    FUZZY_AVAILABLE = False
    logger.warning("rapidfuzz not found. Fuzzy matching disabled.")

# Configure logging - reduce verbosity for speed
logging.basicConfig(level=logging.WARNING, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)

# Pre-initialize recognizer for reuse (avoid repeated initialization)
RECOGNIZER = sr.Recognizer()
RECOGNIZER.energy_threshold = 300  # Lower threshold for faster detection
RECOGNIZER.dynamic_energy_threshold = False  # Disable for consistency
RECOGNIZER.pause_threshold = 0.5  # Shorter pause detection

# Ghana accent pronunciation corrections - Expanded vocabulary
import json

GHANA_CORRECTIONS = {}
try:
    # Get the directory of the current script to ensure correct path
    current_dir = os.path.dirname(os.path.abspath(__file__))
    json_path = os.path.join(current_dir, 'ghana_corrections.json')
    
    with open(json_path, 'r') as f:
        GHANA_CORRECTIONS = json.load(f)
    print(f"Loaded {len(GHANA_CORRECTIONS)} correction rules from ghana_corrections.json")
except Exception as e:
    logger.error(f"Failed to load ghana_corrections.json: {e}")
    print(f"Error loading corrections: {e}")

@lru_cache(maxsize=1000)
def normalize_ghana_accent(text: str) -> str:
    """Normalize Ghana accent pronunciations - CACHED for speed"""
    if not text:
        return text
    
    text_lower = text.lower()
    
    # Handle common phrase mishearings (order matters - longer phrases first)
    phrase_corrections = [
        # Cart related
        ('go to cats', 'go to cart'),
        ('go to cat', 'go to cart'),
        ('go to cut', 'go to cart'),
        ('go to card', 'go to cart'),
        ('to cats', 'to cart'),
        ('to cat', 'to cart'),
        ('to cut', 'to cart'),
        ('to card', 'to cart'),
        ('go cats', 'go cart'),
        ('go cat', 'go cart'),
        ('go cut', 'go cart'),
        ('my cats', 'my cart'),
        ('my cat', 'my cart'),
        ('view cats', 'view cart'),
        ('view cat', 'view cart'),
        ('clear cats', 'clear cart'),
        ('clear cat', 'clear cart'),
        ('empty cats', 'empty cart'),
        ('empty cat', 'empty cart'),
        
        # Checkout related
        ('check outs', 'checkout'),
        ('chek out', 'checkout'),
        ('check owt', 'checkout'),
        
        # Search related
        ('search 4', 'search for'),
        ('look 4', 'look for'),
        ('searching 4', 'searching for'),
        
        # Home related
        ('go hom', 'go home'),
        ('go hum', 'go home'),
        ('back 2 home', 'back to home'),
        
        # Orders related
        ('my odas', 'my orders'),
        ('my oda', 'my order'),
        ('view odas', 'view orders'),
        
        # Add to cart
        ('add 2 cart', 'add to cart'),
        ('add 2 my cart', 'add to my cart'),
        ('put in cats', 'put in cart'),
        ('put in cat', 'put in cart'),
        
        # Remove from cart
        ('remove from cats', 'remove from cart'),
        ('remove from cat', 'remove from cart'),
        ('delete from cats', 'delete from cart'),
        ('delete from cat', 'delete from cart'),
        
        # Common Ghanaian expressions
        ('i dey find', 'i am looking for'),
        ('i dey search', 'i am searching for'),
        ('make i see', 'show me'),
        ('abeg', 'please'),
        ('e be like', 'it looks like'),
    ]
    
    for wrong, correct in phrase_corrections:
        if wrong in text_lower:
            text_lower = text_lower.replace(wrong, correct)
    
    # Word-level corrections
    words = text_lower.split()
    normalized = []
    
    for word in words:
        clean = word.strip('.,!?;:')
        
        # 1. Exact dictionary match (High confidence)
        if clean in GHANA_CORRECTIONS:
            normalized.append(GHANA_CORRECTIONS[clean])
            continue
            
        # 2. Fuzzy match against canonical terms (Medium confidence)
        if FUZZY_AVAILABLE:
            # Get valid canonical terms (values from dictionary + keys from exact matches)
            # Create a set of potential targets
            search_targets = set(GHANA_CORRECTIONS.values())
            search_targets.update(EXACT_MATCHES.keys())
            
            # Find best match
            # score_cutoff=85 means very close match required
            match = process.extractOne(
                clean, 
                search_targets, 
                scorer=fuzz.ratio, 
                score_cutoff=85
            )
            
            if match:
                normalized.append(match[0])
                continue
        
        # 3. No match found, keep original
        normalized.append(word)
    
    return ' '.join(normalized)

# ============== PRE-COMPILED PATTERNS FOR SPEED ==============
# Using frozensets for O(1) exact match lookups
EXACT_MATCHES = {
    # Single word exact matches
    'cart': ('navigate', 'cart', 0.95),
    'home': ('navigate', 'home', 0.95),
    'orders': ('navigate', 'orders', 0.95),
    'profile': ('navigate', 'profile', 0.95),
    'shop': ('navigate', 'shop', 0.95),
    'checkout': ('checkout', None, 0.9),
    'pay': ('checkout', None, 0.85),
    'help': ('help', None, 0.9),
    'momo': ('pay_with_momo', None, 0.95),
}

# Pre-compiled regex for product extraction
ADD_TO_CART_REGEX = re.compile(r'(?:add|put) (.+?) (?:to|in) (?:my |the )?cart')
SEARCH_REGEX = re.compile(r'(?:search|find|look) (?:for )?(.+)')

# Pattern groups - tuples of (patterns_tuple, command_type, confidence)
COMMAND_PATTERNS = [
    # ==== PAYMENT METHODS (highest priority - most specific) ====
    (('pay with momo', 'pay with mobile money', 'use momo', 'use mobile money', 
      'momo payment', 'mobile money payment', 'select momo', 'mtn momo', 
      'mtn mobile money', 'vodafone cash', 'airteltigo money', 'mobile money',
      'pay momo', 'pay using momo', 'pay using mobile money'), 
     'pay_with_momo', 0.95),
    
    (('pay with card', 'use card', 'card payment', 'credit card', 'debit card',
      'pay with visa', 'pay with mastercard', 'visa payment', 'pay card',
      'pay using card', 'use my card', 'use credit card', 'use debit card'), 
     'pay_with_card', 0.95),
    
    (('pay with cash', 'cash on delivery', 'cash payment', 'pay on delivery',
      'pay when i receive', 'pay at delivery', 'cod', 'pay cash',
      'cash when delivered', 'pay on arrival', 'pay at door'), 
     'pay_with_cash', 0.95),
    
    # ==== CART ACTIONS (ecommerce core - check before navigation) ====
    # Clear cart
    (('clear cart', 'clear my cart', 'empty cart', 'empty my cart',
      'remove all items', 'remove all from cart', 'delete all', 'clear all',
      'remove everything', 'delete everything', 'start fresh', 'reset cart'), 
     'clear_cart', 0.95),
    
    # Remove from cart - EXPANDED with many variations
    (('remove from cart', 'remove from my cart', 'delete from cart', 
      'remove this', 'remove it', 'remove item', 'remove the item',
      'delete this', 'delete it', 'delete item', 'take out of cart',
      'take it out', 'take this out', 'dont want this', "don't want this",
      'i dont want', "i don't want", 'cancel item', 'cancel this',
      'remove product', 'delete product', 'get rid of', 'take away'), 
     'remove_from_cart', 0.95),
    
    # Add to cart - EXPANDED
    (('add to cart', 'add to my cart', 'add this to cart', 'put in cart',
      'add it to cart', 'add this', 'buy this', 'i want this', 'get this',
      'i will take', "i'll take", 'put this in cart', 'add item',
      'add product', 'add it', 'put it in cart', 'include this',
      'i need this', 'give me this', 'i want to buy'), 
     'add_to_cart', 0.95),
    
    # Quantity changes
    (('increase quantity', 'add more', 'add one more', 'add another',
      'increase', 'plus one', '+1', 'one more', 'get more'), 
     'increase_quantity', 0.9),
    
    (('decrease quantity', 'reduce quantity', 'remove one', 'less',
      'minus one', '-1', 'one less', 'reduce', 'fewer'), 
     'decrease_quantity', 0.9),
    
    # ==== CHECKOUT (ecommerce core) ====
    (('checkout', 'check out', 'proceed to checkout', 'place order', 
      'complete order', 'pay now', 'make payment', 'ready to pay',
      'finish order', 'submit order', 'confirm order', 'complete purchase',
      'finalize order', 'buy now', 'purchase now', 'proceed to payment',
      'go to checkout', 'continue to checkout', 'process order',
      'i want to pay', "i'm ready to pay", 'ready to checkout',
      'complete my order', 'place my order', 'pay for items', 'pay for this'), 
     'checkout', 0.95),
    
    # ==== NAVIGATION - CART ====
    (('go to cart', 'go cart', 'open cart', 'view cart', 'show cart', 'my cart',
      'see cart', 'check cart', 'shopping cart', 'view my cart', 'show my cart',
      'open my cart', 'whats in my cart', "what's in my cart", 'cart please',
      'see my cart', 'check my cart', 'go to my cart', 'the cart'), 
     ('navigate', 'cart'), 0.95),
    
    # ==== NAVIGATION - HOME ====
    (('go to home', 'go home', 'back to home', 'home page', 'main page', 
      'back home', 'return home', 'take me home', 'homepage', 'main screen',
      'start page', 'landing page', 'go back home', 'back to start'), 
     ('navigate', 'home'), 0.95),
    
    # ==== NAVIGATION - ORDERS ====
    (('go to orders', 'my orders', 'view orders', 'show orders', 'order history',
      'see orders', 'check orders', 'past orders', 'previous orders',
      'view my orders', 'show my orders', 'check my orders', 'purchase history',
      'what did i order', 'my purchases', 'order status', 'all orders'), 
     ('navigate', 'orders'), 0.95),
    
    # Track order
    (('track order', 'track my order', 'where is my order', 'order tracking',
      'track delivery', 'where is my delivery', 'track package', 'track shipment',
      'delivery status', 'shipping status', 'when will it arrive',
      'when will my order arrive', 'order location', 'find my order'), 
     'track_order', 0.95),
    
    # Reorder
    (('reorder', 'order again', 'buy again', 'repeat order', 'same order',
      'order the same', 'reorder this', 'purchase again'), 
     'reorder', 0.9),
    
    # Cancel order
    (('cancel order', 'cancel my order', 'cancel this order', 'stop order',
      'cancel purchase', 'dont want order', "don't want order"), 
     'cancel_order', 0.9),
    
    # ==== NAVIGATION - PROFILE ====
    (('go to profile', 'my profile', 'my account', 'account', 'settings', 
      'profile', 'user profile', 'account settings', 'my settings',
      'view profile', 'open profile', 'profile page', 'account page'), 
     ('navigate', 'profile'), 0.95),
    
    # ==== NAVIGATION - SHOP/BROWSE ====
    (('go to shop', 'browse', 'all products', 'view products', 'shop', 'store',
      'browse products', 'see products', 'show products', 'product catalog',
      'view catalog', 'go shopping', 'start shopping', 'shop now',
      'explore products', 'product list', 'all items'), 
     ('navigate', 'shop'), 0.95),
    
    # Browse categories
    (('browse categories', 'show categories', 'view categories', 'categories',
      'product categories', 'all categories', 'category list'), 
     ('navigate', 'categories'), 0.9),
    
    # ==== PROFILE ACTIONS ====
    (('sign out', 'log out', 'logout', 'sign me out', 'log me out', 
      'exit account', 'leave account', 'logout please', 'sign off'), 
     'sign_out', 0.95),
    
    (('edit profile', 'edit my profile', 'update profile', 'change profile',
      'modify profile', 'profile settings', 'update my profile'), 
     'edit_profile', 0.9),
    
    (('voice settings', 'voice preferences', 'voice options', 'microphone settings',
      'speech settings', 'change voice settings', 'voice control settings'), 
     'voice_settings', 0.9),
    
    (('notification settings', 'notifications', 'notification preferences',
      'push notifications', 'manage notifications', 'change notifications',
      'alert settings', 'notification options'), 
     'notification_settings', 0.9),
    
    (('manage addresses', 'my addresses', 'delivery addresses', 'shipping addresses',
      'add address', 'edit address', 'change address', 'addresses',
      'saved addresses', 'address book', 'delivery address', 'shipping address'), 
     'manage_addresses', 0.9),
    
    (('change pin', 'change my pin', 'update pin', 'new pin', 'reset pin', 
      'modify pin', 'set pin', 'set new pin'), 
     'change_pin', 0.9),
    
    (('change password', 'change my password', 'update password', 'new password',
      'reset password', 'modify password', 'set password', 'set new password'), 
     'change_password', 0.9),
    
    (('help center', 'support', 'customer support', 'contact support',
      'get help', 'need help', 'faq', 'faqs', 'customer service',
      'help desk', 'contact us', 'support center'), 
     'help_center', 0.9),
    
    # ==== WISHLIST ====
    (('add to wishlist', 'save for later', 'wishlist', 'add to favorites',
      'favorite this', 'save item', 'bookmark', 'save this'), 
     'add_to_wishlist', 0.9),
    
    (('view wishlist', 'my wishlist', 'show wishlist', 'saved items',
      'my favorites', 'favorites', 'saved for later'), 
     ('navigate', 'wishlist'), 0.9),
    
    # ==== HELP ====
    (('help', 'help me', 'what can you do', 'commands', 'voice commands',
      'available commands', 'what can i say', 'how to use voice'), 
     'help', 0.9),
]

# Convert to sets for faster lookup
COMMAND_PATTERN_SETS = [
    (frozenset(patterns), cmd_type, conf) 
    for patterns, cmd_type, conf in COMMAND_PATTERNS
]

@lru_cache(maxsize=500)
def parse_command(text: str) -> dict:
    """Parse normalized text into a command - OPTIMIZED for speed"""
    if not text:
        return {"type": "unknown", "confidence": 0.0}
    
    text = text.lower().strip()
    
    # 1. Check exact single-word matches first (O(1))
    if text in EXACT_MATCHES:
        cmd_type, screen, conf = EXACT_MATCHES[text]
        if screen:
            return {"type": cmd_type, "screen": screen, "confidence": conf}
        return {"type": cmd_type, "confidence": conf}
    
    # 2. Check pattern groups (optimized iteration)
    for pattern_set, cmd_type, conf in COMMAND_PATTERN_SETS:
        for pattern in pattern_set:
            if pattern in text:
                if isinstance(cmd_type, tuple):
                    return {"type": cmd_type[0], "screen": cmd_type[1], "confidence": conf}
                return {"type": cmd_type, "confidence": conf}
    
    # 3. Check "add X to cart" pattern with regex
    cart_match = ADD_TO_CART_REGEX.search(text)
    if cart_match:
        product = cart_match.group(1).strip()
        if product and len(product) > 1:
            return {"type": "add_to_cart", "query": product, "confidence": 0.9}
    
    # 4. Check "buy X" pattern
    if text.startswith('buy ') and 'cart' not in text:
        product = text[4:].strip()
        if product and len(product) > 1:
            return {"type": "add_to_cart", "query": product, "confidence": 0.85}
    
    # 5. Check search patterns
    search_match = SEARCH_REGEX.search(text)
    if search_match:
        query = search_match.group(1).strip()
        return {"type": "search", "query": query or text, "confidence": 0.85}
    
    # 6. "i want X" or "i need X" patterns
    if 'i want' in text or 'i need' in text:
        for trigger in ['i want to buy ', 'i want ', 'i need ']:
            if trigger in text:
                query = text.split(trigger, 1)[-1].strip()
                if query and len(query) > 1 and query not in ['to pay', 'to checkout']:
                    return {"type": "add_to_cart", "query": query, "confidence": 0.8}
    
    # 7. "show me X" pattern
    if 'show me' in text:
        query = text.split('show me', 1)[-1].strip()
        if query:
            return {"type": "search", "query": query, "confidence": 0.85}
    
    # 8. Only treat as search if it doesn't look like an action command
    # Avoid treating navigation/action commands as search
    action_words = ['go', 'sign', 'log', 'show', 'open', 'view', 'check', 'clear', 
                    'add', 'remove', 'pay', 'navigate', 'my', 'the', 'back', 'take',
                    'edit', 'change', 'update', 'help', 'checkout', 'cart', 'home',
                    'orders', 'profile', 'settings', 'out', 'off', 'delete', 'empty',
                    'cancel', 'track', 'place', 'complete', 'proceed', 'confirm']
    text_words = text.split()
    
    # If text starts with or contains action words but wasn't matched, return unknown
    if text_words and text_words[0] in action_words:
        return {"type": "unknown", "confidence": 0.3, "raw_text": text}
    
    # Comprehensive list of action phrases that should NOT be treated as search
    action_phrases = [
        # Navigation
        'go to', 'go home', 'go back', 'go cart', 'go orders', 'go profile',
        # Cart actions
        'my cart', 'view cart', 'open cart', 'clear cart', 'empty cart',
        'remove from cart', 'delete from cart', 'add to cart', 'put in cart',
        'remove item', 'delete item', 'remove this', 'delete this',
        # Orders
        'my orders', 'view orders', 'track order', 'cancel order',
        # Auth
        'sign out', 'log out', 'sign in', 'log in',
        # Checkout
        'check out', 'checkout', 'pay now', 'pay with', 'place order',
        'complete order', 'confirm order', 'proceed to',
        # Profile
        'edit profile', 'change password', 'change pin', 'voice settings',
        'notification settings', 'manage addresses',
        # Help
        'help me', 'what can', 'how do i',
    ]
    
    # Check if any action phrase is in the text
    if any(phrase in text for phrase in action_phrases):
        return {"type": "unknown", "confidence": 0.3, "raw_text": text}
    
    # Only treat as search if long enough and looks like a product query
    if len(text) > 2:
        return {"type": "search", "query": text, "confidence": 0.5}
    
    return {"type": "unknown", "confidence": 0.0}


# Keep the old detailed parse function for reference but don't use it
def parse_command_detailed(text: str) -> dict:
    """Original detailed parse - kept for reference"""
    if not text:
        return {"type": "unknown", "confidence": 0.0}
    
    text = text.lower().strip()
    
    # CART ACTIONS - Check these FIRST before cart navigation
    # Clear cart
    clear_cart_patterns = [
        'clear cart', 'clear my cart', 'clear the cart',
        'empty cart', 'empty my cart', 'empty the cart',
        'remove all items', 'remove all', 'delete all items', 'delete all',
        'remove everything', 'delete everything', 'clear all',
        'clean cart', 'clean my cart', 'wipe cart'
    ]
    for pattern in clear_cart_patterns:
        if pattern in text:
            return {"type": "clear_cart", "confidence": 0.9}
    
    # Remove from cart
    remove_patterns = [
        'remove from cart', 'remove from my cart', 'remove from the cart',
        'delete from cart', 'delete from my cart',
        'take out of cart', 'take out from cart',
        'remove this', 'remove it', 'remove that',
        'delete this', 'delete it', 'delete that',
        'remove item', 'remove the item',
        'take this out', 'take it out',
        'i dont want this', "i don't want this",
        'cancel this item', 'cancel item'
    ]
    for pattern in remove_patterns:
        if pattern in text:
            # Extract product name if mentioned
            query = text
            for p in remove_patterns:
                query = query.replace(p, '').strip()
            return {"type": "remove_from_cart", "query": query if query else None, "confidence": 0.85}
    
    # Add to cart - Check for "add X to cart" pattern first (product name in middle)
    # Pattern: "add X to cart" or "put X in cart"
    cart_add_match = re.search(r'(?:add|put) (.+?) (?:to|in) (?:my |the )?cart', text)
    if cart_add_match:
        product = cart_add_match.group(1).strip()
        if product and len(product) > 1:
            return {"type": "add_to_cart", "query": product, "confidence": 0.9}
    
    # Pattern: "buy X" (without "to cart")
    if text.startswith('buy ') and 'cart' not in text:
        product = text[4:].strip()
        # Clean up common words
        for word in ['please', 'now', 'for me']:
            product = product.replace(word, '').strip()
        if product and len(product) > 1:
            return {"type": "add_to_cart", "query": product, "confidence": 0.85}
    
    # Pattern: "i want X" or "i need X" (for shopping intent)
    want_match = re.search(r'i (?:want|need)(?: to buy)? (.+)', text)
    if want_match:
        product = want_match.group(1).strip()
        # Clean up common words
        for word in ['please', 'now', 'it', 'this', 'that']:
            product = product.replace(word, '').strip()
        if product and len(product) > 1 and product not in ['to pay', 'to checkout', 'to go']:
            return {"type": "add_to_cart", "query": product, "confidence": 0.8}
    
    # Add to cart - standard patterns (product name after pattern)
    add_cart_patterns = [
        'add to cart', 'add to my cart', 'add to the cart',
        'put in cart', 'put in my cart', 'put in the cart',
        'add this', 'add it', 'add that',
        'buy this', 'buy it', 'buy that',
        'i want to buy', 'i want this', 'i want it', 'i want that',
        'get this', 'get it', 'get that',
        'i will take this', "i'll take this", 'i will take it',
        'put this in', 'put it in',
        'include this', 'include it'
    ]
    for pattern in add_cart_patterns:
        if pattern in text:
            # Extract product name if mentioned
            query = text
            for p in add_cart_patterns:
                query = query.replace(p, '').strip()
            return {"type": "add_to_cart", "query": query if query else None, "confidence": 0.85}
    
    # NAVIGATION COMMANDS (after cart actions)
    # Navigation - Cart
    cart_patterns = [
        'go to cart', 'goto cart', 'go cart',
        'open cart', 'open my cart', 'open the cart',
        'view cart', 'view my cart', 'view the cart',
        'show cart', 'show my cart', 'show the cart',
        'my cart', 'the cart', 'shopping cart',
        'see cart', 'see my cart', 'check cart', 'check my cart',
        'what is in my cart', "what's in my cart", 'whats in my cart',
        'cart items', 'my cart items'
    ]
    for pattern in cart_patterns:
        if pattern in text or text == 'cart':
            return {"type": "navigate", "screen": "cart", "confidence": 0.95}
    
    # Navigation - Home
    home_patterns = [
        'go to home', 'go home', 'goto home',
        'open home', 'home page', 'homepage',
        'main page', 'main screen', 'start page',
        'back to home', 'back home', 'return home',
        'take me home', 'bring me home'
    ]
    for pattern in home_patterns:
        if pattern in text or text == 'home':
            return {"type": "navigate", "screen": "home", "confidence": 0.95}
    
    # Navigation - Orders
    order_patterns = [
        'go to orders', 'goto orders', 'go orders',
        'my orders', 'my order', 'the orders',
        'view orders', 'view my orders', 'view order',
        'show orders', 'show my orders', 'show order',
        'order history', 'orders history', 'purchase history',
        'past orders', 'previous orders', 'old orders',
        'see orders', 'see my orders', 'check orders', 'check my orders',
        'what did i order', 'what have i ordered'
    ]
    for pattern in order_patterns:
        if pattern in text or text == 'orders':
            return {"type": "navigate", "screen": "orders", "confidence": 0.95}
    
    # Navigation - Profile
    profile_patterns = [
        'go to profile', 'goto profile', 'go profile',
        'my profile', 'the profile', 'user profile',
        'open profile', 'view profile', 'show profile',
        'account', 'my account', 'the account',
        'settings', 'my settings', 'app settings',
        'see profile', 'check profile'
    ]
    for pattern in profile_patterns:
        if pattern in text or text == 'profile':
            return {"type": "navigate", "screen": "profile", "confidence": 0.95}
    
    # Navigation - Shop
    shop_patterns = [
        'go to shop', 'goto shop', 'go shop',
        'open shop', 'the shop', 'view shop',
        'browse', 'browse products', 'browse items',
        'all products', 'see products', 'show products',
        'catalog', 'product catalog', 'view catalog',
        'go shopping', 'start shopping', 'shop now'
    ]
    for pattern in shop_patterns:
        if pattern in text or text == 'shop':
            return {"type": "navigate", "screen": "shop", "confidence": 0.95}
    
    # PAYMENT METHOD SELECTION - Check these BEFORE general checkout
    # Pay with Mobile Money (MoMo)
    momo_patterns = [
        'pay with momo', 'pay with mobile money', 'pay using momo',
        'pay using mobile money', 'use momo', 'use mobile money',
        'momo payment', 'mobile money payment',
        'select momo', 'select mobile money', 'choose momo',
        'i want to pay with momo', 'i want to pay with mobile money',
        'mtn momo', 'mtn mobile money', 'use mtn mobile money',
        'vodafone cash', 'use vodafone cash',
        'airteltigo money', 'use airteltigo money',
        'pay with mtn', 'pay with vodafone', 'pay with airteltigo',
        'mobile money', 'momo'
    ]
    for pattern in momo_patterns:
        if pattern in text:
            return {"type": "pay_with_momo", "confidence": 0.95}
    
    # Pay with Card
    card_patterns = [
        'pay with card', 'pay with my card', 'pay using card',
        'card payment', 'use card', 'use my card',
        'select card', 'choose card', 'credit card', 'debit card',
        'i want to pay with card', 'pay with visa', 'pay with mastercard',
        'visa payment', 'mastercard payment'
    ]
    for pattern in card_patterns:
        if pattern in text:
            return {"type": "pay_with_card", "confidence": 0.95}
    
    # Pay with Cash on Delivery
    cash_patterns = [
        'pay with cash', 'pay cash', 'cash on delivery',
        'cash payment', 'use cash', 'pay on delivery',
        'select cash', 'choose cash', 'cod',
        'i want to pay cash', 'i will pay cash',
        'pay when i receive', 'pay when it arrives',
        'pay on arrival', 'pay at delivery'
    ]
    for pattern in cash_patterns:
        if pattern in text:
            return {"type": "pay_with_cash", "confidence": 0.95}
    
    # General Checkout (without specific payment method)
    checkout_patterns = [
        'checkout', 'check out', 'checking out',
        'pay now', 'pay for this', 'pay for it', 'pay for items',
        'proceed to checkout', 'go to checkout', 'goto checkout',
        'complete order', 'complete my order', 'complete purchase',
        'place order', 'place my order', 'submit order',
        'finish order', 'finish my order', 'finalize order',
        'make payment', 'make a payment', 'process payment',
        'i want to pay', 'i am ready to pay', "i'm ready to pay",
        'ready to pay', 'ready to checkout',
        'buy now', 'purchase now', 'confirm order'
    ]
    for pattern in checkout_patterns:
        if pattern in text:
            return {"type": "checkout", "confidence": 0.9}
    
    # Pay (separate to avoid conflicts)
    if text == 'pay' or (text.startswith('pay ') and 'with' not in text):
        return {"type": "checkout", "confidence": 0.85}
    
    # Search - expanded triggers
    search_triggers = [
        'search for', 'search', 'searching for',
        'find', 'find me', 'finding',
        'look for', 'looking for', 'look up',
        'show me', 'show', 'display',
        'i want', 'i need', 'i am looking for', "i'm looking for",
        'where can i find', 'where is', 'where are',
        'do you have', 'have you got', 'got any',
        'can i get', 'can i see', 'let me see',
        'bring me', 'get me', 'give me'
    ]
    for trigger in search_triggers:
        if trigger in text:
            query = text.split(trigger, 1)[-1].strip()
            # Clean up common trailing words
            for word in ['please', 'thanks', 'thank you', 'now', 'quickly']:
                query = query.replace(word, '').strip()
            return {"type": "search", "query": query or text, "confidence": 0.85}
    
    # Help
    help_patterns = [
        'help', 'help me', 'i need help',
        'what can you do', 'what can i say', 'what can i do',
        'how do i', 'how to', 'how can i',
        'commands', 'voice commands', 'available commands',
        'assist me', 'assistance', 'support'
    ]
    for pattern in help_patterns:
        if pattern in text:
            return {"type": "help", "confidence": 0.9}
    
    # Unknown - might be a search (if it contains product-like words)
    product_indicators = [
        'phone', 'laptop', 'computer', 'tv', 'television',
        'shoe', 'shoes', 'shirt', 'dress', 'bag', 'watch',
        'headphone', 'earphone', 'charger', 'cable',
        'blender', 'kettle', 'iron', 'fan', 'fridge',
        'perfume', 'cream', 'soap', 'lotion',
        'kente', 'ankara', 'african'
    ]
    for indicator in product_indicators:
        if indicator in text:
            return {"type": "search", "query": text, "confidence": 0.7}
    
    # Default: treat as search if long enough
    if len(text) > 2:
        return {"type": "search", "query": text, "confidence": 0.5}
    
    return {"type": "unknown", "confidence": 0.0}


@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint"""
    return jsonify({"status": "healthy", "service": "Buyvia Voice"})


@app.route('/transcribe', methods=['POST'])
def transcribe():
    """Transcribe audio and parse command - OPTIMIZED for <1.5s response"""
    start_time = time.time()
    temp_path = None
    
    try:
        if 'file' not in request.files:
            return jsonify({"success": False, "error": "No audio file"}), 400
        
        audio_file = request.files['file']
        audio_data = audio_file.read()
        
        if len(audio_data) < 100:
            return jsonify({"success": False, "error": "Audio file too small"}), 400
        
        # Create temp file - use .wav extension
        temp_fd, temp_path = tempfile.mkstemp(suffix='.wav')
        os.close(temp_fd)
        
        # OPTIMIZED: Fast audio conversion
        convert_start = time.time()
        try:
            # Quick conversion - minimal processing
            audio = AudioSegment.from_file(io.BytesIO(audio_data))
            # Only convert if necessary (check sample rate)
            if audio.frame_rate != 16000 or audio.channels != 1:
                audio = audio.set_frame_rate(16000).set_channels(1)
            audio.export(temp_path, format='wav', parameters=["-q:a", "0"])
        except Exception:
            # Fallback: write raw data
            with open(temp_path, 'wb') as f:
                f.write(audio_data)
        convert_time = time.time() - convert_start
        
        # OPTIMIZED: Use pre-initialized recognizer
        recognize_start = time.time()
        raw_text = ""
        
        try:
            with sr.AudioFile(temp_path) as source:
                # Skip ambient noise adjustment for speed
                audio_recorded = RECOGNIZER.record(source)
                # Use Google with language hint for faster processing
                raw_text = RECOGNIZER.recognize_google(
                    audio_recorded, 
                    language="en-GH",  # Ghana English hint
                    show_all=False  # Only return best result
                )
        except sr.UnknownValueError:
            raw_text = ""
        except sr.RequestError as e:
            return jsonify({"success": False, "error": f"Speech API error: {e}"}), 503
        
        recognize_time = time.time() - recognize_start
        
        # OPTIMIZED: Fast normalize and parse (both cached)
        parse_start = time.time()
        normalized = normalize_ghana_accent(raw_text)
        command = parse_command(normalized)
        parse_time = time.time() - parse_start
        
        total_time = time.time() - start_time
        
        # Log timing only if slow (for debugging)
        if total_time > 1.5:
            logger.warning(f"⚠️ Slow response: {total_time:.2f}s (convert:{convert_time:.2f}s, recognize:{recognize_time:.2f}s, parse:{parse_time:.3f}s)")
        
        return jsonify({
            "success": True,
            "raw_text": raw_text,
            "normalized_text": normalized,
            "command": command,
            "timing_ms": int(total_time * 1000)
        })
        
    except Exception as e:
        import traceback
        logger.error(f"❌ Error: {e}\n{traceback.format_exc()}")
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        # Clean up temp file
        if temp_path and os.path.exists(temp_path):
            try:
                os.unlink(temp_path)
            except:
                pass


@app.route('/parse', methods=['POST'])
def parse():
    """Parse text command (for testing)"""
    try:
        data = request.get_json()
        text = data.get('text', '')
        
        normalized = normalize_ghana_accent(text)
        command = parse_command(normalized)
        
        return jsonify({
            "success": True,
            "raw_text": text,
            "normalized_text": normalized,
            "command": command
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/', methods=['GET'])
def root():
    """Service info"""
    return jsonify({
        "service": "Buyvia Voice Recognition",
        "endpoints": {
            "/health": "GET - Health check",
            "/transcribe": "POST - Transcribe audio file",
            "/parse": "POST - Parse text command"
        }
    })


if __name__ == '__main__':
    print("🚀 Starting Buyvia Voice Service...")
    print("🌐 http://192.168.0.104:5000")
    print("🇬🇭 Optimized for Ghanaian English")
    print()
    app.run(host='0.0.0.0', port=5000, debug=True)
