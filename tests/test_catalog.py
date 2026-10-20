from anime_vault.catalog import CATALOG, entries
from anime_vault.models import Status, canonical_id
from anime_vault.services import normalize, progress_percent


def test_complete_catalog_and_categories():
    data = entries()
    assert sum(len(titles.splitlines()) for _, titles in CATALOG.values()) == 145
    assert len(data) == len({item['_id'] for item in data}) == 145
    assert all(item['categories'] and item['format'] in {'movie', 'tv_series'} for item in data)
    by_title = {item['title']: item for item in data}
    assert by_title['The Promised Neverland']['recommendation_tags'] == ['season_1']
    assert by_title['Bocchi the Rock!']['categories'] == ['comedy_slice_of_life_series']
    assert by_title['The Girl Who Leapt Through Time']['categories'] == ['romance_movies']


def test_ids_are_stable_and_compact():
    assert canonical_id('My Anime!', 'movie') == canonical_id('My Anime!', 'movie')
    assert len(canonical_id('Our Dating Story: The Experienced You and The Inexperienced Me', 'tv_series')) < 30


def test_title_normalization_does_not_change_canonical_records():
    assert normalize('Hunter × Hunter') == normalize('Hunter x Hunter')
    assert normalize('A Silent Voice') != normalize('Your Name')


def test_progress_boundaries():
    assert progress_percent(3, 12) == 25
    assert progress_percent(3, None) is None
    for value in (-1, 13):
        try:
            progress_percent(value, 12)
        except ValueError:
            pass
        else:
            raise AssertionError('invalid progress accepted')


def test_status_values_are_exact():
    assert {value.value for value in Status} == {'PLAN_TO_WATCH', 'WATCHING', 'WATCHED', 'ON_HOLD', 'DROPPED'}
