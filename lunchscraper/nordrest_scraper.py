"""Web scraper for Nordrest restaurant menus (via Castit menu widget)."""

import re
import requests
from bs4 import BeautifulSoup
from datetime import date
from typing import Dict, List, Optional
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
        """Parse the weekly menu from the Castit widget on the page."""
        weekly_menu = {}

        swedish_weekdays = {'måndag', 'tisdag', 'onsdag', 'torsdag', 'fredag', 'lördag', 'söndag'}

        for day_section in soup.find_all('section', class_='castit-day'):
            classes = day_section.get('class', [])
            # Skip week-special sections (e.g. "Veckans rätter")
            if 'castit-week-specials-column' in classes:
                continue

            # Get the Swedish day name from the title span's data-sv attribute
            title_span = day_section.find('span', class_='castit-i18n', attrs={'data-sv': True})
            if not title_span:
                continue
            day_sv = title_span.get('data-sv', '').strip().lower()
            if day_sv not in swedish_weekdays:
                continue

            # Extract dishes: title + optional description combined into one string
            dishes = []
            for dish_div in day_section.find_all('div', class_='castit-dish'):
                title_el = dish_div.find('div', class_='castit-dish__title')
                desc_el = dish_div.find('div', class_='castit-dish__desc')
                if not title_el:
                    continue
                dish_text = title_el.get_text(strip=True)
                if desc_el:
                    desc_text = desc_el.get_text(strip=True)
                    if desc_text:
                        dish_text = f"{dish_text}, {desc_text}"
                if dish_text and len(dish_text) >= 5:
                    dishes.append(dish_text)

            if dishes:
                menu_items = self._parse_dishes(dishes)
                if menu_items.get('menu') or menu_items.get('vegetarian') or menu_items.get('fish') or menu_items.get('meat'):
                    weekly_menu[day_sv] = menu_items
                    logger.debug(f"Parsed {day_sv}: {len(menu_items.get('menu', []))} items")

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
            target_date: The date to get the menu for. Defaults to today.

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
        logger.debug(f"Looking for menu for: {day_name}")

        if day_name not in weekly_menu:
            raise Exception(f"No menu found for {day_name}. Available days: {', '.join(weekly_menu.keys())}")

        return weekly_menu[day_name]

    def get_weekly_menu(self) -> Dict[str, Dict[str, List[str]]]:
        """
        Get the menu for the whole week.

        Returns:
            Dictionary with Swedish day names as keys and categorised menu items per day.
        """
        logger.debug(f"Fetching weekly menu for {self.restaurant_name}")

        try:
            soup = self._fetch_page()
            weekly_menu = self._parse_weekly_menu(soup)
        except Exception as e:
            raise Exception(f"Failed to fetch menu: {e}")

        return weekly_menu
