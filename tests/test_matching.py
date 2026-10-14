from bookshelf.matching import author_matches, core_title, match_score, normalize, title_similarity


def test_normalize_strips_accents_and_greek_tonos():
    assert normalize("Saint-Exupéry") == "saint exupery"
    assert normalize("Μικρός Πρίγκιπας") == "μικροσ πριγκιπασ"  # casefold folds final sigma


def test_core_title_drops_subtitle_and_article():
    assert core_title("The Name of the Rose: A Novel") == "name of the rose"
    assert core_title("Le Petit Prince") == "petit prince"


def test_title_similarity():
    assert title_similarity("Le Petit Prince", "Le petit prince") == 1.0
    assert title_similarity("Cien años de soledad", "Cien Anos De Soledad") == 1.0
    assert title_similarity("War and Peace", "Pride and Prejudice") < 0.72


def test_author_matches_on_surname():
    assert author_matches("Antoine de Saint-Exupéry", ["Antoine de Saint Exupéry"])
    assert author_matches("J. R. R. Tolkien", ["J.R.R. Tolkien"])
    assert not author_matches("Leo Tolstoy", ["Jane Austen"])
    assert author_matches(None, ["anyone"])


def test_match_score_rejects_wrong_author():
    assert match_score(["Emma"], "Jane Austen", "Emma", ["Someone Else"]) == 0.0
    assert match_score(["Emma"], "Jane Austen", "Emma", ["Jane Austen"]) == 1.0
