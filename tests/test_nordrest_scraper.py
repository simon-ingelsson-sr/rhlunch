"""Tests for NordrestMenuScraper."""

from datetime import date
import pytest
import responses
from bs4 import BeautifulSoup
from lunchscraper.nordrest_scraper import NordrestMenuScraper
from tests.conftest import get_fixture_dates_with_file, load_fixture_file


def _make_dish(title: str, desc: str = "") -> str:
    """Helper to build a castit-dish HTML snippet."""
    desc_html = f'<div class="castit-dish__desc">{desc}</div>' if desc else ""
    return f"""
    <div class="castit-dish">
        <div class="castit-dish__left">
            <div class="castit-dish__title">{title}</div>
            {desc_html}
        </div>
    </div>
    """


def _make_day_section(sv_name: str, en_name: str, dishes_html: str, extra_classes: str = "") -> str:
    """Helper to build a castit-day section."""
    return f"""
    <section class="castit-day {extra_classes}">
        <h3 class="castit-day__title">
            <span class="castit-i18n" data-sv="{sv_name}" data-en="{en_name}">{sv_name}</span>
        </h3>
        <div class="castit-day__list">
            {dishes_html}
        </div>
    </section>
    """


SAMPLE_HTML = """
<html><body>
{monday}
{tuesday}
{wednesday}
{thursday}
{friday}
</body></html>
""".format(
    monday=_make_day_section("Måndag", "Monday",
        _make_dish("Kycklingfilé med currysås", "serveras med ris") +
        _make_dish("Falafel med hummus", "tzatziki och pitabröd")
    ),
    tuesday=_make_day_section("Tisdag", "Tuesday",
        _make_dish("Ugnsbakad lax med dill", "kokt potatis") +
        _make_dish("Köttfärssås med pasta", "riven ost")
    ),
    wednesday=_make_day_section("Onsdag", "Wednesday",
        _make_dish("Vegansk Pasta Bolognese", "lök och tomat")
    ),
    thursday=_make_day_section("Torsdag", "Thursday",
        _make_dish("Biff med bearnaisesås", "pommes och sallad")
    ),
    friday=_make_day_section("Fredag", "Friday",
        _make_dish("Fiskgratäng med ost", "kokt potatis")
    ),
)

SAMPLE_HTML_WITH_WEEKLY_SPECIAL = """
<html><body>
<section class="castit-day castit-day--week castit-week-specials-column">
    <h3 class="castit-day__title castit-week-specials-column__title">
        <span class="castit-i18n" data-sv="Veckans rätter" data-en="Dishes of the week">Veckans rätter</span>
    </h3>
    <div class="castit-day__list">
        {special}
    </div>
</section>
{monday}
</body></html>
""".format(
    special=_make_dish("Salladsbar", "25 kr/hg"),
    monday=_make_day_section("Måndag", "Monday",
        _make_dish("Kycklingfilé med currysås", "ris")
    ),
)


class TestNordrestMenuScraper:
    """Tests for NordrestMenuScraper class."""

    @pytest.fixture
    def scraper(self):
        return NordrestMenuScraper(
            restaurant_url="https://www.nordrest.se/restaurang/karavan/",
            restaurant_name="Karavan"
        )

    def test_init(self, scraper):
        assert scraper.restaurant_name == "Karavan"
        assert scraper.restaurant_url == "https://www.nordrest.se/restaurang/karavan/"
        assert scraper.session is not None

    # ------------------------------------------------------------------
    # _fetch_page
    # ------------------------------------------------------------------

    @responses.activate
    def test_fetch_page_success(self, scraper):
        responses.add(responses.GET, scraper.restaurant_url, body=SAMPLE_HTML, status=200)
        soup = scraper._fetch_page()
        assert isinstance(soup, BeautifulSoup)

    @responses.activate
    def test_fetch_page_failure(self, scraper):
        responses.add(responses.GET, scraper.restaurant_url, status=500)
        with pytest.raises(Exception, match="Failed to fetch menu page"):
            scraper._fetch_page()

    # ------------------------------------------------------------------
    # _extract_dishes_from_section
    # ------------------------------------------------------------------

    def test_extract_dishes_combines_title_and_desc(self, scraper):
        html = _make_day_section("Måndag", "Monday",
            _make_dish("Kycklingfilé med currysås", "serveras med ris")
        )
        soup = BeautifulSoup(html, 'html.parser')
        section = soup.find('section')
        dishes = scraper._extract_dishes_from_section(section)
        assert len(dishes) == 1
        assert "Kycklingfilé med currysås" in dishes[0]
        assert "serveras med ris" in dishes[0]

    def test_extract_dishes_no_desc(self, scraper):
        html = _make_day_section("Måndag", "Monday", _make_dish("Grönsakssoppa"))
        soup = BeautifulSoup(html, 'html.parser')
        section = soup.find('section')
        dishes = scraper._extract_dishes_from_section(section)
        assert dishes == ["Grönsakssoppa"]

    def test_extract_dishes_skips_too_short(self, scraper):
        html = _make_day_section("Måndag", "Monday", _make_dish("AB"))
        soup = BeautifulSoup(html, 'html.parser')
        section = soup.find('section')
        dishes = scraper._extract_dishes_from_section(section)
        assert dishes == []

    # ------------------------------------------------------------------
    # _parse_dishes
    # ------------------------------------------------------------------

    def test_parse_dishes_returns_menu_key(self, scraper):
        result = scraper._parse_dishes(["Kycklingfilé med currysås, serveras med ris"])
        assert 'menu' in result
        assert len(result['menu']) == 1

    def test_parse_dishes_strips_dietary_codes_and_appends_label(self, scraper):
        result = scraper._parse_dishes(["Pasta med grönsakssås (Vegansk)"])
        assert result['menu'][0].endswith("(vegansk)")

    def test_parse_dishes_strips_price_suffix(self, scraper):
        result = scraper._parse_dishes(["Salladsbar 25.90"])
        assert "25.90" not in result['menu'][0]

    def test_parse_dishes_empty_returns_empty_keys(self, scraper):
        result = scraper._parse_dishes([])
        assert result == {'menu': [], 'vegetarian': [], 'fish': [], 'meat': []}

    def test_parse_dishes_skips_too_short(self, scraper):
        result = scraper._parse_dishes(["ab", "ok"])
        assert result['menu'] == []

    # ------------------------------------------------------------------
    # _parse_weekly_menu
    # ------------------------------------------------------------------

    def test_parse_weekly_menu_finds_all_weekdays(self, scraper):
        soup = BeautifulSoup(SAMPLE_HTML, 'html.parser')
        menu = scraper._parse_weekly_menu(soup)
        assert set(menu.keys()) == {'måndag', 'tisdag', 'onsdag', 'torsdag', 'fredag'}

    def test_parse_weekly_menu_each_day_has_menu_items(self, scraper):
        soup = BeautifulSoup(SAMPLE_HTML, 'html.parser')
        menu = scraper._parse_weekly_menu(soup)
        for day, day_menu in menu.items():
            assert len(day_menu['menu']) > 0, f"No items for {day}"

    def test_parse_weekly_menu_monday_contains_expected_dishes(self, scraper):
        soup = BeautifulSoup(SAMPLE_HTML, 'html.parser')
        menu = scraper._parse_weekly_menu(soup)
        items = menu['måndag']['menu']
        assert any("Kycklingfilé med currysås" in d for d in items)
        assert any("Falafel med hummus" in d for d in items)

    def test_parse_weekly_menu_skips_week_specials_column(self, scraper):
        """Week-specials column should not appear as a day in the weekly menu."""
        soup = BeautifulSoup(SAMPLE_HTML_WITH_WEEKLY_SPECIAL, 'html.parser')
        menu = scraper._parse_weekly_menu(soup)
        assert 'veckans rätter' not in menu
        assert 'måndag' in menu

    def test_parse_weekly_menu_appends_weekly_specials_to_each_day(self, scraper):
        """Dishes from Veckans rätt should appear in every day's menu."""
        soup = BeautifulSoup(SAMPLE_HTML_WITH_WEEKLY_SPECIAL, 'html.parser')
        menu = scraper._parse_weekly_menu(soup)
        items = menu['måndag']['menu']
        assert any("Salladsbar" in d for d in items)

    def test_parse_weekly_menu_no_castit_sections_returns_empty(self, scraper):
        soup = BeautifulSoup("<html><body><p>No menu</p></body></html>", 'html.parser')
        assert scraper._parse_weekly_menu(soup) == {}

    def test_parse_weekly_menu_ignores_unrecognised_day_names(self, scraper):
        html = _make_day_section("Helgdag", "Holiday", _make_dish("Grönsakssoppa med bröd"))
        soup = BeautifulSoup(f"<html><body>{html}</body></html>", 'html.parser')
        assert scraper._parse_weekly_menu(soup) == {}

    # ------------------------------------------------------------------
    # get_menu_for_day
    # ------------------------------------------------------------------

    @responses.activate
    def test_get_menu_for_day_monday(self, scraper):
        responses.add(responses.GET, scraper.restaurant_url, body=SAMPLE_HTML, status=200)
        menu = scraper.get_menu_for_day(date(2025, 11, 10))  # Monday
        assert 'menu' in menu
        assert any("Kycklingfilé med currysås" in d for d in menu['menu'])

    @responses.activate
    def test_get_menu_for_day_tuesday(self, scraper):
        responses.add(responses.GET, scraper.restaurant_url, body=SAMPLE_HTML, status=200)
        menu = scraper.get_menu_for_day(date(2025, 11, 11))  # Tuesday
        assert any("Ugnsbakad lax med dill" in d for d in menu['menu'])

    @responses.activate
    def test_get_menu_for_day_not_found_raises(self, scraper):
        html = "<html><body>{}</body></html>".format(
            _make_day_section("Måndag", "Monday", _make_dish("Kycklingfilé med currysås"))
        )
        responses.add(responses.GET, scraper.restaurant_url, body=html, status=200)
        with pytest.raises(Exception, match="No menu found for tisdag"):
            scraper.get_menu_for_day(date(2025, 11, 11))  # Tuesday not in HTML

    @responses.activate
    def test_get_menu_for_day_fetch_failure_raises(self, scraper):
        responses.add(responses.GET, scraper.restaurant_url, status=503)
        with pytest.raises(Exception, match="Failed to fetch menu"):
            scraper.get_menu_for_day(date(2025, 11, 10))

    # ------------------------------------------------------------------
    # get_weekly_menu
    # ------------------------------------------------------------------

    @responses.activate
    def test_get_weekly_menu_returns_all_days(self, scraper):
        responses.add(responses.GET, scraper.restaurant_url, body=SAMPLE_HTML, status=200)
        weekly = scraper.get_weekly_menu()
        assert set(weekly.keys()) == {'måndag', 'tisdag', 'onsdag', 'torsdag', 'fredag'}

    @responses.activate
    def test_get_weekly_menu_fetch_failure_raises(self, scraper):
        responses.add(responses.GET, scraper.restaurant_url, status=500)
        with pytest.raises(Exception, match="Failed to fetch menu"):
            scraper.get_weekly_menu()


# ============================================================================
# Integration Tests with Real Fetched Fixtures
# ============================================================================


class TestNordrestMenuScraperWithRealFixtures:
    """Integration tests using real fetched HTML fixtures."""

    @pytest.mark.parametrize(
        "fixture_date",
        get_fixture_dates_with_file("nordrest_karavan.html"),
        ids=lambda d: f"karavan_{d.strftime('%Y_%m_%d')}"
    )
    def test_parse_real_karavan_html(self, fixture_date):
        html = load_fixture_file("nordrest_karavan.html", fixture_date)
        scraper = NordrestMenuScraper(
            restaurant_url="https://www.nordrest.se/restaurang/karavan/",
            restaurant_name="Karavan"
        )
        soup = BeautifulSoup(html, 'html.parser')
        weekly_menu = scraper._parse_weekly_menu(soup)

        assert isinstance(weekly_menu, dict), f"Failed to parse menu for {fixture_date}"
        assert len(weekly_menu) > 0, f"No menu items found for {fixture_date}"

        valid_days = {'måndag', 'tisdag', 'onsdag', 'torsdag', 'fredag', 'lördag', 'söndag'}
        for day, day_menu in weekly_menu.items():
            assert day in valid_days, f"Unexpected day '{day}' for {fixture_date}"
            assert 'menu' in day_menu
            assert len(day_menu['menu']) > 0, f"No dishes for {day} on {fixture_date}"

    @pytest.mark.parametrize(
        "fixture_date",
        get_fixture_dates_with_file("nordrest_gourmedia.html"),
        ids=lambda d: f"gourmedia_{d.strftime('%Y_%m_%d')}"
    )
    def test_parse_real_gourmedia_html(self, fixture_date):
        html = load_fixture_file("nordrest_gourmedia.html", fixture_date)
        scraper = NordrestMenuScraper(
            restaurant_url="https://www.nordrest.se/restaurang/gourmedia/",
            restaurant_name="Gourmedia"
        )
        soup = BeautifulSoup(html, 'html.parser')
        weekly_menu = scraper._parse_weekly_menu(soup)

        assert isinstance(weekly_menu, dict), f"Failed to parse menu for {fixture_date}"
        assert len(weekly_menu) > 0, f"No menu items found for {fixture_date}"

        valid_days = {'måndag', 'tisdag', 'onsdag', 'torsdag', 'fredag', 'lördag', 'söndag'}
        for day, day_menu in weekly_menu.items():
            assert day in valid_days, f"Unexpected day '{day}' for {fixture_date}"
            assert 'menu' in day_menu
            assert len(day_menu['menu']) > 0, f"No dishes for {day} on {fixture_date}"
