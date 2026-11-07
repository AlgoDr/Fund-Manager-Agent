"""Unit tests for services.amount_parser.parse_amount_paise."""
import pytest
from services.amount_parser import parse_amount_paise


class TestNumericAmounts:
    """Tests for plain numeric amounts (with or without currency words)."""

    def test_plain_number(self):
        assert parse_amount_paise("350") == 35000

    def test_number_with_rupees(self):
        assert parse_amount_paise("350 rupees") == 35000

    def test_number_with_rs(self):
        assert parse_amount_paise("350 rs") == 35000

    def test_number_with_inr(self):
        assert parse_amount_paise("350 inr") == 35000

    def test_decimal_amount(self):
        assert parse_amount_paise("1.5") == 150

    def test_zero(self):
        assert parse_amount_paise("0") == 0


class TestShorthandSuffixes:
    """Tests for k / thousand / lakh / crore suffixes."""

    def test_k_suffix(self):
        assert parse_amount_paise("1.5k") == 150000

    def test_thousand_suffix(self):
        assert parse_amount_paise("2 thousand") == 200000

    def test_lakh_suffix(self):
        assert parse_amount_paise("1 lakh") == 10000000

    def test_lac_suffix(self):
        assert parse_amount_paise("1 lac") == 10000000

    def test_crore_suffix(self):
        assert parse_amount_paise("1 crore") == 1000000000

    def test_comma_separated(self):
        assert parse_amount_paise("1,000") == 100000


class TestNumberWords:
    """Tests for English number words."""

    def test_two_fifty(self):
        assert parse_amount_paise("two fifty") == 25000

    def test_fifteen_hundred(self):
        assert parse_amount_paise("fifteen hundred") == 150000

    def test_three_hundred(self):
        assert parse_amount_paise("three hundred") == 30000

    def test_two_thousand(self):
        assert parse_amount_paise("two thousand") == 200000

    def test_twenty_five(self):
        assert parse_amount_paise("twenty five") == 2500

    def test_one_hundred_twenty(self):
        assert parse_amount_paise("one hundred twenty") == 12000


class TestEdgeCases:
    """Tests for None, empty, and unparseable inputs."""

    def test_none(self):
        assert parse_amount_paise(None) is None

    def test_empty_string(self):
        assert parse_amount_paise("") is None

    def test_whitespace_only(self):
        assert parse_amount_paise("   ") is None

    def test_unparseable(self):
        assert parse_amount_paise("some random text") is None

    def test_just_currency_word(self):
        assert parse_amount_paise("rupees") is None