"""Test con un cronograma de ejemplo (octubre 2026).

Las primeras 4 líneas de datos son las reales del plan original; el resto
sigue el mismo formato para completar las 7 fechas de Players esperadas
(29/9 A+, 3/10 Canchas, 10/10 EJ, 15/10 HdlS, 20/10 A+, 24/10 Canchas, 31/10 EJ),
porque el plan no incluía el cronograma completo del mes.
"""
from parser import parse_cronograma

CRONOGRAMA = """
✅ CRONOGRAMA DE COBERTURAS
🗓 Octubre, 2026
1ª Semana (29/9 al 3/10)
✨ A+ 29/9: Players
💡 HdlS • 1/10: Camaleones
🤝 EJ • 3/10: Solucionadores
⚽️ Canchas 3/10: Players
2ª Semana (6/10 al 10/10)
✨ A+ 6/10: Camaleones
💡 HdlS • 8/10: Solucionadores
🤝 EJ • 10/10: Players
3ª Semana (13/10 al 17/10)
✨ A+ 13/10: Solucionadores
💡 HdlS • 15/10: Players
🤝 EJ • 17/10: Camaleones
4ª Semana (20/10 al 24/10)
✨ A+ 20/10: Players
💡 HdlS • 22/10: Camaleones
⚽️ Canchas 24/10: Players
5ª Semana (27/10 al 31/10)
✨ A+ 27/10: Camaleones
🤝 EJ • 31/10: Players
"""

ESPERADAS = [
    (2026, 9, 29, "A+"),
    (2026, 10, 3, "Canchas"),
    (2026, 10, 10, "EJ"),
    (2026, 10, 15, "HdlS"),
    (2026, 10, 20, "A+"),
    (2026, 10, 24, "Canchas"),
    (2026, 10, 31, "EJ"),
]


def test_parse_cronograma_octubre():
    mes, anio, eventos = parse_cronograma(CRONOGRAMA)
    assert (mes, anio) == (10, 2026)
    obtenidas = [(e["anio"], e["mes"], e["dia"], e["categoria"]) for e in eventos]
    assert obtenidas == ESPERADAS, obtenidas


def test_texto_sin_header_no_es_cronograma():
    mes, anio, eventos = parse_cronograma("hola, cómo andás")
    assert mes is None and eventos == []


if __name__ == "__main__":
    test_parse_cronograma_octubre()
    test_texto_sin_header_no_es_cronograma()
    print("OK: las 7 fechas de Players coinciden.")
