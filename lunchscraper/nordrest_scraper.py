"""Web scraper for Nordrest restaurant menus (WordPress/Elementor)."""

import requests
from bs4 import BeautifulSoup
from datetime import datetime, date
from typing import Dict, List, Optional
import re
import logging
from .base_scraper import BaseMenuScraper
from .dish_classifier import DishClassifier

logger = logging.getLogger(__name__)


class NordrestMenuScraper(BaseMenuScraper):
    """Scraper for Nordrest restaurant lunch menus."""

    def __init__(self, restaurant_url: str, restaurant_name: str):
        super().__init__(restaurant_name)
        self.restaurant_url = restaurant_url
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9,sv;q=0.8',
        })

    def _fetch_page(self) -> BeautifulSoup:
        """Fetch the restaurant page and return BeautifulSoup object."""
        logger.debug(f"Fetching menu from {self.restaurant_url}")
        try:
            response = self.session.get(self.restaurant_url, timeout=10)
            response.raise_for_status()
            return BeautifulSoup(response.text, 'html.parser')
        except Exception as e:
            raise Exception(f"Failed to fetch menu page: {e}")

    def _parse_weekly_menu(self, soup: BeautifulSoup) -> Dict[str, Dict[str, List[str]]]:
        """Parse the weekly menu from the page."""
        weekly_menu = {}

        # The menu is structured as accordion items with class 'accordion-item weekday-item'
        # Each day is in an accordion-header div
        day_names = ['Måndag', 'Tisdag', 'Onsdag', 'Torsdag', 'Fredag', 'Lördag', 'Söndag']
        
        # Find all accordion items
        accordion_items = soup.find_all('div', class_='accordion-item')
        
        for item in accordion_items:
            # Check if this is a weekday item
            if 'weekday-item' not in item.get('class', []):
                continue
            
            # Find the day header
            header = item.find('div', class_='accordion-header')
            if not header:
                continue
            
            day_text = header.get_text(strip=True)
            
            # Check if this is a valid day name
            day_found = None
            for day in day_names:
                if day.lower() == day_text.lower():
                    day_found = day
                    break
            
            if not day_found:
                continue
            
            # Find the accordion body/content
            body = item.find('div', class_='accordion-body') or item.find('div', class_='accordion-content')
            if not body:
                # If no accordion-body, get all text after the header
                body = item
            
            # Extract dishes from the body
            dishes_text = body.get_text(separator='\n')
            dishes = []
            
            for line in dishes_text.split('\n'):
                line = line.strip()
                if not line:
                    continue
                
                # Skip the day name if it appears again
                if line.lower() == day_found.lower():
                    continue
                
                # Skip lines that are just numbers (prices)
                if re.match(r'^\d+\.?\d*$', line):
                    continue
                
                # Skip very short lines
                if len(line) < 3:
                    continue
                
                dishes.append(line)
            
            # Parse the dishes
            if dishes:
                menu_items = self._parse_dishes(dishes)
                # Check for menu items (either in 'menu' key or in categorized keys)
                if menu_items.get('menu') or menu_items.get('vegetarian') or menu_items.get('fish') or menu_items.get('meat'):
                    weekly_menu[day_found.lower()] = menu_items
                    if menu_items.get('menu'):
                        logger.debug(f"Parsed {day_found}: {len(menu_items['menu'])} items")
                    else:
                        logger.debug(f"Parsed {day_found}: {len(menu_items.get('vegetarian', []))} veg, {len(menu_items.get('fish', []))} fish, {len(menu_items.get('meat', []))} meat")

        return weekly_menu

    def _parse_dishes(self, dishes: List[str]) -> Dict[str, List[str]]:
        """Parse a list of dish strings."""
        if not dishes:
            return {'menu': [], 'vegetarian': [], 'fish': [], 'meat': []}

        cleaned_dishes = []
        
        for dish in dishes:
            dish = dish.strip()
            
            # Skip very short lines
            if len(dish) < 5:
                continue
            
            # Extract dietary codes in parentheses like (L, G), (Vegansk), etc.
            dietary_info = re.findall(r'\(([^)]+)\)', dish)
            
            # Remove price numbers at the end (e.g., "844.02" or "1775.25")
            # Prices are typically at the end after dietary codes
            dish = re.sub(r'\s+\d+\.?\d*\s*$', '', dish)
            
            # Remove dietary codes in parentheses (we'll use them for classification)
            # But preserve the info by adding it to the text
            dietary_text = ' '.join(dietary_info).lower() if dietary_info else ''
            
            # Remove parentheses and their contents
            dish = re.sub(r'\s*\([^)]+\)\s*', ' ', dish)
            
            # Remove multiple spaces
            dish = re.sub(r'\s+', ' ', dish).strip()
            
            # Add dietary info back to dish text for better classification
            if dietary_text:
                if 'vegan' in dietary_text or 'vegansk' in dietary_text:
                    dish = f"{dish} (vegansk)"
                elif 'vegetarisk' in dietary_text or 'vego' in dietary_text:
                    dish = f"{dish} (vegetarisk)"
            
            if dish and len(dish) >= 5:
                cleaned_dishes.append(dish)

        # For Nordrest menus, we don't categorize - just return all dishes together
        # Return in a "menu" key for general display, but also populate other keys for compatibility
        return {
            'menu': cleaned_dishes,  # General menu list
            'vegetarian': [],  # Empty for compatibility
            'fish': [],  # Empty for compatibility
            'meat': []  # Empty for compatibility
        }

    def get_menu_for_day(self, target_date: Optional[date] = None) -> Dict[str, List[str]]:
        """
        Get the menu for a specific day.

        Args:
            target_date: The date to get menu for. If None, uses today.

        Returns:
            Dictionary with 'vegetarian', 'fish', and 'meat' menu items for the day.
        """
        if target_date is None:
            target_date = date.today()

        logger.debug(f"Fetching menu for date: {target_date} ({target_date.strftime('%A, %B %d, %Y')})")

        try:
            soup = self._fetch_page()
            weekly_menu = self._parse_weekly_menu(soup)
        except Exception as e:
            raise Exception(f"Failed to fetch menu: {e}")

        # Get the day of week (0=Monday, 6=Sunday)
        day_of_week = target_date.weekday()
        day_names = ['måndag', 'tisdag', 'onsdag', 'torsdag', 'fredag', 'lördag', 'söndag']

        if day_of_week >= len(day_names):
            logger.warning(f"Invalid day of week: {day_of_week}")
            return {'vegetarian': [], 'fish': [], 'meat': []}

        day_name = day_names[day_of_week]
        logger.debug(f"Looking for menu for day: {day_name}")

        if day_name not in weekly_menu:
            raise Exception(f"No menu found for {day_name}")

        return weekly_menu[day_name]

    def get_weekly_menu(self) -> Dict[str, Dict[str, List[str]]]:
        """
        Get the menu for the whole week.

        Returns:
            Dictionary with days as keys and menu items for each day.
        """
        logger.debug(f"Fetching weekly menu for {self.restaurant_name}")

        try:
            soup = self._fetch_page()
            weekly_menu = self._parse_weekly_menu(soup)
        except Exception as e:
            raise Exception(f"Failed to fetch menu: {e}")

        return weekly_menu

