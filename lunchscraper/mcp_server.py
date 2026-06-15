"""MCP Server for RHLunch - Expose lunch menu functionality to AI assistants."""

from datetime import date, datetime
from typing import Optional, List, Dict, Any
from mcp.server.fastmcp import FastMCP

from .nordrest_scraper import NordrestMenuScraper
from .kvartersmenyn_scraper import KvartersmenynsMenuScraper
from .nordrest_scraper import NordrestMenuScraper

# Initialize FastMCP server
mcp = FastMCP("RHLunch")

# Restaurant configurations
RESTAURANTS = {
    'gourmedia': {
        'name': 'Gourmedia',
        'type': 'nordrest',
        'url': 'https://www.nordrest.se/restaurang/gourmedia/'
    },
    'filmhuset': {
        'name': 'Filmhuset',
        'type': 'kvartersmenyn',
        'url': 'https://filmhuset.kvartersmenyn.se/'
    },
    'karavan': {
        'name': 'Karavan',
        'type': 'nordrest',
        'url': 'https://www.nordrest.se/restaurang/karavan/'
    },
}


def _create_scraper(restaurant_key: str):
    """Create appropriate scraper for the given restaurant."""
    config = RESTAURANTS.get(restaurant_key)
    if not config:
        raise ValueError(f"Unknown restaurant: {restaurant_key}")

    if config['type'] == 'nordrest':
        return NordrestMenuScraper(
            restaurant_url=config['url'],
            restaurant_name=config['name']
        )
    elif config['type'] == 'kvartersmenyn':
        return KvartersmenynsMenuScraper(
            restaurant_url=config['url'],
            restaurant_name=config['name']
        )
    elif config['type'] == 'nordrest':
        return NordrestMenuScraper(
            restaurant_url=config['url'],
            restaurant_name=config['name']
        )
    else:
        raise ValueError(f"Unknown restaurant type: {config['type']}")


def _filter_menu(menu: Dict[str, List[str]],
                 vegetarian_only: bool = False,
                 fish_only: bool = False,
                 meat_only: bool = False) -> Dict[str, List[str]]:
    """Filter menu based on dietary preferences."""
    # If menu has a general "menu" key, return it as-is (no filtering for uncategorized menus)
    if menu.get('menu'):
        return menu
    
    # Standard filtering for categorized menus
    if vegetarian_only:
        return {'vegetarian': menu.get('vegetarian', [])}
    elif fish_only:
        return {'fish': menu.get('fish', [])}
    elif meat_only:
        return {'meat': menu.get('meat', [])}
    return menu


def _format_menu_text(restaurant_name: str, menu: Dict[str, List[str]]) -> str:
    """Format menu as readable text."""
    lines = [f"\n📍 {restaurant_name}", "─" * 50]

    # Check for general "menu" key first (for menus without categorization)
    if menu.get('menu'):
        lines.append("\n🍽️ Menu:")
        for item in menu['menu']:
            lines.append(f"  • {item}")
    else:
        # Standard categorized menu
        if menu.get('vegetarian'):
            lines.append("\n🥬 Vegetarian:")
            for item in menu['vegetarian']:
                lines.append(f"  • {item}")

        if menu.get('fish'):
            lines.append("\n🐟 Fish:")
            for item in menu['fish']:
                lines.append(f"  • {item}")

        if menu.get('meat'):
            lines.append("\n🥩 Meat:")
            for item in menu['meat']:
                lines.append(f"  • {item}")

    if not any(menu.values()):
        lines.append("\n❌ No menu available")

    return "\n".join(lines)


@mcp.tool()
def list_restaurants() -> str:
    """List all available restaurants.

    Returns:
        A formatted string listing all available restaurants
    """
    lines = ["Available restaurants:"]
    for key, config in RESTAURANTS.items():
        lines.append(f"  • {key}: {config['name']}")
    return "\n".join(lines)


@mcp.tool()
def get_daily_menu(
    restaurant: Optional[str] = None,
    vegetarian_only: bool = False,
    fish_only: bool = False,
    meat_only: bool = False,
    target_date: Optional[str] = None
) -> str:
    """Get today's lunch menu from one or all restaurants.

    Args:
        restaurant: Restaurant key (gourmedia, filmhuset, karavan). If None, returns all restaurants.
        vegetarian_only: Show only vegetarian options
        fish_only: Show only fish options
        meat_only: Show only meat options
        target_date: Date in YYYY-MM-DD format. If None, uses today.

    Returns:
        Formatted menu text for the specified day
    """
    # Parse date
    menu_date = date.today()
    if target_date:
        try:
            menu_date = datetime.strptime(target_date, '%Y-%m-%d').date()
        except ValueError:
            return f"Error: Invalid date format. Use YYYY-MM-DD. Example: 2025-11-04"

    # Determine which restaurants to query
    restaurant_keys = [restaurant] if restaurant else list(RESTAURANTS.keys())

    # Validate restaurant key
    for key in restaurant_keys:
        if key not in RESTAURANTS:
            return f"Error: Unknown restaurant '{key}'. Use list_restaurants() to see available options."

    # Build result
    result = [f"🍽️ Lunch Menu for {menu_date.strftime('%A, %B %d, %Y')}\n"]

    for key in restaurant_keys:
        try:
            scraper = _create_scraper(key)
            menu = scraper.get_menu_for_day(menu_date)
            filtered_menu = _filter_menu(menu, vegetarian_only, fish_only, meat_only)
            result.append(_format_menu_text(RESTAURANTS[key]['name'], filtered_menu))
        except Exception as e:
            result.append(f"\n📍 {RESTAURANTS[key]['name']}")
            result.append("─" * 50)
            result.append(f"\n❌ Error: {str(e)}")

    return "\n".join(result)


@mcp.tool()
def get_weekly_menu(
    restaurant: Optional[str] = None,
    vegetarian_only: bool = False,
    fish_only: bool = False,
    meat_only: bool = False
) -> str:
    """Get the weekly lunch menu from one or all restaurants.

    Args:
        restaurant: Restaurant key (gourmedia, filmhuset, karavan). If None, returns all restaurants.
        vegetarian_only: Show only vegetarian options
        fish_only: Show only fish options
        meat_only: Show only meat options

    Returns:
        Formatted weekly menu text
    """
    # Determine which restaurants to query
    restaurant_keys = [restaurant] if restaurant else list(RESTAURANTS.keys())

    # Validate restaurant key
    for key in restaurant_keys:
        if key not in RESTAURANTS:
            return f"Error: Unknown restaurant '{key}'. Use list_restaurants() to see available options."

    # Build result
    result = ["🍽️ Weekly Lunch Menu\n"]

    for key in restaurant_keys:
        try:
            scraper = _create_scraper(key)
            weekly_menu = scraper.get_weekly_menu()

            result.append(f"\n📍 {RESTAURANTS[key]['name']}")
            result.append("─" * 50)

            day_names = {
                'måndag': 'Monday',
                'tisdag': 'Tuesday',
                'onsdag': 'Wednesday',
                'torsdag': 'Thursday',
                'fredag': 'Friday'
            }

            for swedish_day, english_day in day_names.items():
                if swedish_day not in weekly_menu:
                    continue

                menu = weekly_menu[swedish_day]
                filtered_menu = _filter_menu(menu, vegetarian_only, fish_only, meat_only)

                result.append(f"\n📅 {english_day}")

                # Check for general "menu" key first (for menus without categorization)
                if filtered_menu.get('menu'):
                    result.append("\n🍽️ Menu:")
                    for item in filtered_menu['menu']:
                        result.append(f"  • {item}")
                else:
                    # Standard categorized menu
                    if filtered_menu.get('vegetarian'):
                        result.append("\n🥬 Vegetarian:")
                        for item in filtered_menu['vegetarian']:
                            result.append(f"  • {item}")

                    if filtered_menu.get('fish'):
                        result.append("\n🐟 Fish:")
                        for item in filtered_menu['fish']:
                            result.append(f"  • {item}")

                    if filtered_menu.get('meat'):
                        result.append("\n🥩 Meat:")
                        for item in filtered_menu['meat']:
                            result.append(f"  • {item}")

                if not any(filtered_menu.values()):
                    result.append("  ❌ No menu available")

        except Exception as e:
            result.append(f"\n📍 {RESTAURANTS[key]['name']}")
            result.append("─" * 50)
            result.append(f"\n❌ Error: {str(e)}")

    return "\n".join(result)


def main():
    """Entry point for the MCP server."""
    mcp.run()


if __name__ == "__main__":
    main()
