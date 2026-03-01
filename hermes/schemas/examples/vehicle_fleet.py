"""Example schema: Mexican Slip de Flotilla vehicle extraction."""

from pydantic import BaseModel


class VehicleRecord(BaseModel):
    marca: str | None = None
    descripcion: str | None = None
    modelo: int | None = None
    numero_serie: str | None = None
    tipo_vehiculo: str | None = None
    cobertura: str | None = None
    suma_asegurada: float | None = None
    deducible: str | None = None
