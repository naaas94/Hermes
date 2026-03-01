"""Generate synthetic test fixtures for Hermes tests.

Run this script once to create small Excel and PDF files in tests/fixtures/.
Requires openpyxl and pymupdf to be installed.
"""

from __future__ import annotations

from pathlib import Path


def main() -> None:
    fixtures = Path(__file__).parent / "fixtures"
    fixtures.mkdir(exist_ok=True)

    _create_sample_excel(fixtures / "sample.xlsx")
    _create_sample_pdf_text(fixtures / "sample_text.pdf")
    _create_empty_excel(fixtures / "empty.xlsx")

    print(f"Fixtures created in {fixtures}")


def _create_sample_excel(path: Path) -> None:
    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Vehicles"

    headers = [
        "Marca", "Descripcion", "Modelo", "Numero Serie",
        "Tipo", "Cobertura", "Suma Asegurada", "Deducible",
    ]
    ws.append(headers)
    ws.append([
        "Toyota", "Corolla SE", 2023, "JTDS4RCE1P0000001",
        "Sedan", "Amplia", 350000.00, "5%",
    ])
    ws.append([
        "Honda", "Civic EX", 2022, "2HGFC2F60NH000002",
        "Sedan", "Basica", 280000.00, "10%",
    ])
    ws.append([
        "Ford", "Ranger XLT", 2024, "1FTER4FH0PLA00003",
        "Pickup", "Amplia", 620000.00, "5%",
    ])
    ws.append([
        "Nissan", "Versa Advance", 2023, "3N1CN8DV7PL000004",
        "Sedan", "Limitada", 310000.00, "15%",
    ])
    ws.append([
        "Chevrolet", "Aveo LT", 2021, "3G1TB5CF1ML000005",
        "Sedan", "Basica", 220000.00, "10%",
    ])

    wb.save(str(path))


def _create_sample_pdf_text(path: Path) -> None:
    import pymupdf

    doc = pymupdf.open()

    page = doc.new_page(width=612, height=792)
    text = (
        "SLIP DE FLOTILLA VEHICULAR\n\n"
        "Aseguradora: Seguros Atlas S.A.\n"
        "Poliza: POL-2024-001234\n\n"
        "Vehiculo 1:\n"
        "  Marca: Toyota\n"
        "  Descripcion: Corolla SE\n"
        "  Modelo: 2023\n"
        "  Numero de Serie: JTDS4RCE1P0000001\n"
        "  Tipo: Sedan\n"
        "  Cobertura: Amplia\n"
        "  Suma Asegurada: $350,000.00\n"
        "  Deducible: 5%\n\n"
        "Vehiculo 2:\n"
        "  Marca: Honda\n"
        "  Descripcion: Civic EX\n"
        "  Modelo: 2022\n"
        "  Numero de Serie: 2HGFC2F60NH000002\n"
        "  Tipo: Sedan\n"
        "  Cobertura: Basica\n"
        "  Suma Asegurada: $280,000.00\n"
        "  Deducible: 10%\n"
    )
    page.insert_text((72, 72), text, fontsize=11)
    del page

    page2 = doc.new_page(width=612, height=792)
    text2 = (
        "Vehiculo 3:\n"
        "  Marca: Ford\n"
        "  Descripcion: Ranger XLT\n"
        "  Modelo: 2024\n"
        "  Numero de Serie: 1FTER4FH0PLA00003\n"
        "  Tipo: Pickup\n"
        "  Cobertura: Amplia\n"
        "  Suma Asegurada: $620,000.00\n"
        "  Deducible: 5%\n"
    )
    page2.insert_text((72, 72), text2, fontsize=11)
    del page2

    doc.save(str(path))
    doc.close()


def _create_empty_excel(path: Path) -> None:
    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Empty"
    wb.save(str(path))


if __name__ == "__main__":
    main()
