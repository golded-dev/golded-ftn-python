from golded_ftn import repair_mojibake


def test_preserves_spaced_temperature() -> None:
    result = repair_mojibake("20 °C")
    assert result.text == "20 °C"
    assert not result.changed


def test_repairs_damage_beside_literal_degree() -> None:
    assert repair_mojibake("m°de at 10°").text == "møde at 10°"


def test_degree_contexts_and_mixed_encodings() -> None:
    for text in (
        "35°45",
        "-10°",
        "2°r",
        "20 °",
        "20\t°",
        "°C",
        "ca. °F",
        "ca. ° C",
        "°\tF",
        "AB> 20 °C",
    ):
        result = repair_mojibake(text)
        assert result.text == text
        assert not result.changed
        assert result.confidence == 0
    for damaged, expected in (
        ("SÃ¥dan at 10°", "Sådan at 10°"),
        ("AB> m°de at 10°", "AB> møde at 10°"),
        ("m°de at 20 °C", "møde at 20 °C"),
        ("2\nm°de", "2\nmøde"),
        ("2\n°l", "2\nøl"),
        ("°Code", "øCode"),
        ("SÃ¥dan ☃", "SÃ¥dan ☃"),
        ("Bruger m°de 🙂", "Bruger m°de 🙂"),
    ):
        assert repair_mojibake(damaged).text == expected


def test_repairs_text_without_reencoding_its_frame() -> None:
    result = repair_mojibake("─── Begrµnsning ───")
    assert result.text == "─── Begrænsning ───"
    assert result.changed
    assert 0 < result.confidence <= 1
    for text in ("─" * 32, "┌──────────┬──────────┐", "█▄▀"):
        result = repair_mojibake(text)
        assert result.text == text
        assert not result.changed
        assert result.confidence == 0


def test_repair_does_not_introduce_control_characters() -> None:
    text = "ikke på 240) ±‗´¯Ý\xad\xad▄█Ð·¹³²·¨°. Bag dem ved 200°."
    result = repair_mojibake(text)
    assert result.text == text
    assert not result.changed
    assert result.confidence == 0


def test_rejects_unsafe_mime_decoding_but_allows_tabs() -> None:
    for text in (
        "=?iso-8859-1?Q?abc=01?=",
        "=?iso-8859-1?Q?abc=7F?=",
        "=?iso-8859-1?Q?abc=86?=",
        "=?UTF-8?B?77+9?=",
        "\x86 =?iso-8859-1?Q?abc=86?=",
    ):
        result = repair_mojibake(text)
        assert result.text == text
        assert not result.changed
    assert repair_mojibake("=?iso-8859-1?Q?Ada=09S=F8rensen?=").text == "Ada\tSørensen"


def test_recovers_mislabelled_ascii_mime_word() -> None:
    result = repair_mojibake("=?US-ASCII?Q?p=E5?= mandag")
    assert result.text == "på mandag"
    assert result.changed
    assert result.confidence == 0.95


def test_mime_fallback_does_not_guess_other_declared_charsets() -> None:
    for text in (
        "=?UTF-8?Q?p=E5?= mandag",
        "=?UNKNOWN?Q?p=E5?= mandag",
        "=?US-ASCII?Q?p=86?= mandag",
    ):
        result = repair_mojibake(text)
        assert result.text == text
        assert not result.changed


def test_repairs_mixed_line_without_changing_correct_words() -> None:
    result = repair_mojibake("Søren skrev om s°getid i går")
    assert result.text == "Søren skrev om søgetid i går"
    assert result.changed
    assert 0 < result.confidence <= 1


def test_preserves_uuencoded_data_even_when_it_looks_like_mime() -> None:
    text = "M=?ISO-8859-1?Q?=E5?=".ljust(61, "A")
    result = repair_mojibake(text)
    assert result.text == text
    assert not result.changed
    assert result.confidence == 0


def test_preserves_pgp_armour_while_repairing_surrounding_text() -> None:
    text = (
        "Vi ses pÕ m°det\n"
        "-----BEGIN PGP SIGNED MESSAGE-----\n"
        "Hash: SHA256\n\n"
        "Vi ses pÕ m°det\n"
        "-----BEGIN PGP SIGNATURE-----\n"
        "=?ISO-8859-1?Q?=E5?=\n"
        "-----END PGP SIGNATURE-----\n"
        "Bruger m°de"
    )
    expected = text.replace("Vi ses pÕ m°det", "Vi ses på mødet", 1)
    expected = expected.removesuffix("Bruger m°de") + "Bruger møde"
    result = repair_mojibake(text)
    assert result.text == expected
    assert result.changed


def test_preserves_symbol_noise_instead_of_scoring_it_as_prose() -> None:
    text = "±‗´¯Ý\xad\xadÐ·¹³²·¨°"
    result = repair_mojibake(text)
    assert result.text == text
    assert not result.changed
    assert result.confidence == 0


def test_declared_multibyte_codec_does_not_raise_on_candidates() -> None:
    for charset in ("UTF-16", "UTF-32"):
        result = repair_mojibake("SÃ¥dan", charset)
        assert result.text == "Sådan"


def test_mixed_line_keeps_graphics_beside_ascii_words() -> None:
    text = "█ Foo▀ GRå █"
    result = repair_mojibake(text)
    assert result.text == text
    assert not result.changed


def test_preserves_reported_art_and_correct_text() -> None:
    for text in (
        "─ (Dan) Til/fra Sysop (2:231/116) ───────── SYSOP116 ─",
        "█ -[/] ¯ViL U´CL¯ Õ GRåVeDiGGeR Õ ALCATRAZ [\\]- █",
        "│ Medlemsmøde på torsdag │",
        "Det var 20 °C i går",
        "10 µm",
    ):
        result = repair_mojibake(text)
        assert result.text == text
        assert not result.changed
        assert result.confidence == 0
