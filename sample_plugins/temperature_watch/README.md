# Temperature Watch

Pausa o timer quando a CPU ultrapassa a temperatura configurada.

## Configuração

| Parâmetro | Tipo | Padrão | Descrição |
|-----------|------|--------|-----------|
| `threshold_c` | int | `85` | Temperatura máxima em °C |

## Compatibilidade

| OS | Método | Requisito |
|----|--------|-----------|
| Linux/Mac | `psutil.sensors_temperatures()` | `pip install psutil` |
| Windows | WMI (`MSAcpi_ThermalZoneTemperature`) | `pip install wmi` |
| Windows (alt) | Open Hardware Monitor + WMI | Instalar OHM |

> **Nota:** No Windows, muitas placas-mãe não expõem temperatura via WMI padrão. O Open Hardware Monitor resolve isso.
