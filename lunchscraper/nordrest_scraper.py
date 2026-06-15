"""Web scraper for Nordrest restaurant menus (via Castit menu widget)."""

import requests
from bs4 import BeautifulSoup
from datetime import date
from typing import Dict, List, Optional
import logging
from .base_scraper import BaseMenuScraper
from .dish_classifier import DishClassifier

logger = logging.getLogger(__name__)


class NordrestMenuScraper(BaseMenuScraper):
    """Scraper for Nordrest restaurant lunch menus rendered via the Castit widget."""

    def __init__(self, restaurant_url: str, restaurant_name: str = "Gourmedia"):
        super().__init__(restaurant_name)
        self.restaurant_url = restaurant_url
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'sv-SE,sv;q=0.9,en;q=0.8',
        })

    def _fetch_page(self) -> BeautifulSoup:
        """Fetch the restaurant page and return a BeautifulSoup object."""
        logger.debug(f"Fetching menu from {self.restaurant_url}")
        try:
            response = self.session.get(self.restaurant_url, timeout=10)
            response.raise_for_status()
            return BeautifulSoup(response.text, 'html.parser')
        except Exception as e:
            raise Exception(f"Failed to fetch menu page: {e}")

    def _parse_weekly_menu(self, soup: BeautifulSoup) -> Dict[str, Dict[str, List[str]]]:
        """Parse the weekly menu from the Castit widget embedded in the page."""
        weekly_menu = {}

        lunch_div = soup.find('div', class_='castit-lunch')
        if not lunch_div:
            logger.warning("Could not find castit-lunch widget on page")
            return weekly_menu

        # Find the active week panel
        week_panel = lunch_div.find('div', class_='is-active', attrs={'data-week-panel': True})
        if not week_panel:
            # Fall back to the first panel
            week_panel = lunch_div.find('div', attrs={'data-week-panel': True})
        if not week_panel:
            logger.warning("Could not find week panel in castit-lunch widget")
            return weekly_menu

        # Extract weekly specials (veckans rätt) — applied to every day
        weekly_specials = self._extract_weekly_specials(week_panel)
        if weekly_specials:
            logger.debug(
                f"Found weekly specials: {len(weekly_specials['vegetarian'])} veg, "
                f"{len(weekly_specials['fish'])} fish, {len(weekly_specials['meat'])} meat"
            )

        day_sections = week_panel.find_all('section', class_='castit-day')
        logger.debug(f"Found {len(day_sections)} day sections")

        for section in day_sections:
            # Skip the weekly specials column — handled separately
            if 'castit-week-specials-column' in (section.get('class') or []):
                continue

            title_span = section.find('h3', class_='castit-day__title')
            if not title_span:
                continue
            i18n_span = title_span.find('span', class_='castit-i18n')
            day_name = (i18n_span.get('data-sv') or i18n_span.get_text(strip=True)).lower() if i18n_span else ''
            if not day_name:
                continue

            dishes = self._extract_dishes(section)

            # Merge weekly specials into each day
            if weekly_specials:
                for category in ('vegetarian', 'fish', 'meat'):
                    dishes[category] = dishes[category] + weekly_specials[category]

            if any(dishes.values()):
                weekly_menu[day_name] = dishes
                logger.debug(
                    f"Parsed {day_name}: {len(dishes['vegetarian'])} veg, "
                    f"{len(dishes['fish'])} fish, {len(dishes['meat'])} meat"
                )

        return weekly_menu

    def _extract_weekly_specials(self, week_panel: BeautifulSoup) -> Dict[str, List[str]]:
        """Extract dishes from the 'Veckans rätter' weekly specials column, if present."""
        specials_section = week_panel.find('section', class_='castit-week-specials-column')
        if not specials_section:
            return {}
        return self._extract_dishes(specials_section)

    def _extract_dishes(self, day_section: BeautifulSoup) -> Dict[str, List[str]]:
        """Extract and classify dishes from a single day section."""
        dish_strings = []
        allergen_tags: List[List[str]] = []

        # Collect all castit-dish elements — either wrapped in castit-dish-wrap
        # (regular days) or directly inside castit-weekgroup (weekly specials).
        dish_elements = []
        for wrap in day_section.find_all('div', class_='castit-dish-wrap'):
            dish_div = wrap.find('div', class_='castit-dish')
            if dish_div:
                dish_elements.append(dish_div)
        for group in day_section.find_all('div', class_='castit-weekgroup'):
            for dish_div in group.find_all('div', class_='castit-dish', recursive=False):
                dish_elements.append(dish_div)

        for dish_div in dish_elements:
            title_el = dish_div.find('div', class_='castit-dish__title')
            if not title_el:
                continue
            title_span = title_el.find('span', class_='castit-i18n')
            title = (title_span.get('data-sv') or title_span.get_text(strip=True)).strip() if title_span else ''

            desc_el = dish_div.find('div', class_='castit-dish__desc')
            if desc_el:
                desc_span = desc_el.find('span', class_='castit-i18n')
                desc = (desc_span.get('data-sv') or desc_span.get_text(strip=True)).strip() if desc_span else ''
                full_dish = f"{title}, {desc}" if title and desc else title or desc
            else:
                full_dish = title

            allergen_el = dish_div.find('div', class_='castit-dish__allergens')
            allergens = [a.strip() for a in (allergen_el.get_text(separator='•').split('•') if allergen_el else [])]

            if full_dish:
                dish_strings.append(full_dish)
                allergen_tags.append(allergens)

        return self._classify_with_allergens(dish_strings, allergen_tags)

    def _classify_with_allergens(
        self,
        dishes: List[str],
        allergen_tags: List[List[str]],
    ) -> Dict[str, List[str]]:
        """
        Classify dishes using allergen tags and DishClassifier.

        Allergen tags containing 'Vegan' or 'Vegetarisk' directly indicate
        vegetarian dishes, overriding keyword-based classification.
        """
        result: Dict[str, List[str]] = {'vegetarian': [], 'fish': [], 'meat': []}

        for dish, allergens in zip(dishes, allergen_tags):
            allergens_lower = [a.lower() for a in allergens]
            if 'vegan' in allergens_lower or 'vegetarisk' in allergens_lower:
                result['vegetarian'].append(dish)
            else:
                # Delegate to keyword-based classifier
                classified = DishClassifier.classify_dishes([dish])
                for category in ('vegetarian', 'fish', 'meat'):
                    if classified.get(category):
                        result[category].extend(classified[category])
                        break
                else:
                    result['meat'].append(dish)

        return result

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

        logger.debug(f"Fetching menu for {target_date}")

        try:
            soup = self._fetch_page()
            weekly_menu = self._parse_weekly_menu(soup)
        except Exception as e:
            raise Exception(f"Failed to fetch menu: {e}")

        day_names = ['måndag', 'tisdag', 'onsdag', 'torsdag', 'fredag', 'lördag', 'söndag']
        day_of_week = target_date.weekday()

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
