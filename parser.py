"""Parseo del cronograma mensual de coberturas: extrae solo las fechas de Players."""
import re
import unicodedata

MESES = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
    "julio": 7, "agosto": 8, "septiembre": 9, "setiembre": 9, "octubre": 10,
    "noviembre": 11, "diciembre": 12,
}

HEADER_RE = re.compile(r"🗓\s*([A-Za-zñÑáéíóúÁÉÍÓÚ]+),?\s*(\d{4})")
LINE_RE = re.compile(r"^\W*(A\+|HdlS|EJ|Canchas)\s*•?\s*(\d{1,2})/(\d{1,2}):\s*(\w+)")
ESCALA_HEADER_RE = re.compile(r"^ESCALA\s+.+?(\d{1,2})/(\d{1,2}):?\s*$", re.IGNORECASE)


def sin_acentos(s):
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def resolver_anio(mes_evento, mes_nominal, anio_nominal):
    """Elige el año más cercano al mes nominal del cronograma (maneja el cambio de año)."""
    diff = mes_evento - mes_nominal
    if diff > 6:
        return anio_nominal - 1
    if diff < -6:
        return anio_nominal + 1
    return anio_nominal


def parse_cronograma(texto):
    """Devuelve (mes_nominal, anio_nominal, [eventos de Players]) o (None, None, []) si no es un cronograma válido."""
    header = HEADER_RE.search(texto)
    if not header:
        return None, None, []
    nombre_mes = sin_acentos(header.group(1)).lower()
    mes_nominal = MESES.get(nombre_mes)
    anio_nominal = int(header.group(2))
    if mes_nominal is None:
        return None, None, []

    eventos = []
    for linea in texto.splitlines():
        m = LINE_RE.match(linea.strip())
        if not m:
            continue
        categoria, dia, mes, equipo = m.groups()
        if sin_acentos(equipo).lower() != "players":
            continue
        dia, mes = int(dia), int(mes)
        anio = resolver_anio(mes, mes_nominal, anio_nominal)
        eventos.append({"anio": anio, "mes": mes, "dia": dia, "categoria": categoria})

    eventos.sort(key=lambda e: (e["anio"], e["mes"], e["dia"]))
    return mes_nominal, anio_nominal, eventos


def parse_escala_header(texto):
    """Si el texto empieza con 'ESCALA ... DD/MM:' (la grilla de nombres con @), devuelve (dia, mes); si no, (None, None)."""
    texto = texto.strip()
    if not texto:
        return None, None
    primera_linea = texto.splitlines()[0].strip()
    m = ESCALA_HEADER_RE.match(primera_linea)
    if not m:
        return None, None
    return int(m.group(1)), int(m.group(2))
