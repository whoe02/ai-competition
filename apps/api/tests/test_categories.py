import pytest

from kira.categories import CATEGORIES, UNCATEGORISED, infer, label_for, slugs


class TestVocabulary:
    def test_every_category_has_a_unique_slug(self):
        assert len(slugs()) == len(CATEGORIES)

    def test_slugs_are_lowercase_and_terse(self):
        assert all(slug.islower() and " " not in slug for slug in slugs())

    def test_covers_the_money_a_malaysian_household_moves(self):
        assert {"food", "groceries", "transport", "bills", "family", "charity"} <= set(slugs())

    def test_uncategorised_is_one_of_them(self):
        assert UNCATEGORISED in slugs()


class TestLabels:
    @pytest.mark.parametrize(
        ("slug", "expected"),
        [("food", "Food & drink"), ("family", "Family & gifts"), ("fees", "Fees & charges")],
    )
    def test_reads_the_way_a_person_would_say_it(self, slug, expected):
        assert label_for(slug) == expected

    def test_an_unknown_slug_still_reads_as_something(self):
        assert label_for("pet-grooming") == "Pet grooming"


class TestInference:
    """A read that guesses the category is better than one that hardcodes it."""

    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("lunch at the mamak", "food"),
            ("nasi lemak this morning", "food"),
            ("grab to the office", "transport"),
            ("topped up petrol", "transport"),
            ("the Tesco run", "groceries"),
            ("paid the Astro bill", "bills"),
            ("panadol from the pharmacy", "health"),
            ("cinema tickets", "fun"),
        ],
    )
    def test_it_reads_the_category_out_of_what_was_said(self, text, expected):
        assert infer(text) == expected

    def test_it_does_not_guess_when_nothing_points_anywhere(self):
        assert infer("that thing from the other day") == UNCATEGORISED

    def test_it_is_not_fooled_by_a_word_inside_another_word(self):
        assert infer("refunded the deposit") == UNCATEGORISED

    def test_every_inferred_slug_is_one_of_the_known_ones(self):
        assert infer("lunch") in slugs()
