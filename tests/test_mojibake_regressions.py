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
