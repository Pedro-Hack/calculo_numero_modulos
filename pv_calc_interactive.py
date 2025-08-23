#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Calculadora FV on-grid (interactiva por consola)

Permite ingresar:
- Consumo (kWh/mes o Wh/día), HSP, PR, temperaturas (frío/calor)
- Parámetros del inversor (hasta 8 MPPT, límites de tensión y corrientes)
- Parámetros del módulo (Wp, Vmp, Imp, Voc, Isc y coeficientes térmicos, Máx. tensión de sistema 1000/1500 V)
- Topología del arreglo: # en serie (S), # de strings en paralelo por MPPT (P), # de MPPT usados

Entrega:
- kWp requeridos para el objetivo
- Rango S permitido por tensiones (mín S por MPPT_min a calor, máx S por Vdc_max y por Vsys_max del módulo, y MPPT_max)
- Chequeos eléctricos (tensión/corriente)
- Producción estimada diaria y mensual
- Recomendaciones automáticas si la producción NO cubre la demanda
- Plan automático de distribución de strings por MPPT para cumplir el objetivo
"""

from dataclasses import dataclass
from typing import Optional, Dict, Any
import math

# --------- Modelos ---------
@dataclass
class Inverter:
    name: str
    mppt_min_v: float
    mppt_max_v: float
    vdc_max: float
    imax_mppt: float
    iscmax_mppt: float
    n_mppt: int

@dataclass
class Module:
    name: str
    wp: float
    vmp: float
    imp: float
    voc: float
    isc: float
    max_system_v: float
    gamma_pmax_pct_per_C: float
    beta_voc_pct_per_C: float
    alpha_isc_pct_per_C: float

# --------- Utilidades ---------
def to_float(s: str) -> float:
    s = s.strip().replace(",", ".")
    return float(s)

def ask_float(prompt: str, default: Optional[float] = None, minv: Optional[float] = None, maxv: Optional[float] = None) -> float:
    while True:
        txt = input(f"{prompt}" + (f" [{default}]" if default is not None else "") + ": ").strip()
        if not txt and default is not None:
            val = float(default)
        else:
            try:
                val = to_float(txt or "nan")
            except Exception:
                print("  -> Valor inválido, intenta de nuevo.")
                continue
        if (minv is not None and val < minv) or (maxv is not None and val > maxv):
            print(f"  -> Debe estar entre {minv} y {maxv}.")
            continue
        return val

def ask_int(prompt: str, default: Optional[int] = None, minv: Optional[int] = None, maxv: Optional[int] = None) -> int:
    while True:
        txt = input(f"{prompt}" + (f" [{default}]" if default is not None else "") + ": ").strip()
        if not txt and default is not None:
            val = int(default)
        else:
            try:
                val = int(to_float(txt))
            except Exception:
                print("  -> Valor inválido, intenta de nuevo.")
                continue
        if (minv is not None and val < minv) or (maxv is not None and val > maxv):
            print(f"  -> Debe estar entre {minv} y {maxv}.")
            continue
        return val

def ask_yesno(prompt: str, default: bool = False) -> bool:
    suf = " [S/n]" if default else " [s/N]"
    while True:
        txt = input(prompt + suf + ": ").strip().lower()
        if txt == "" and default is not None:
            return default
        if txt in ("s", "si", "sí", "y", "yes"):
            return True
        if txt in ("n", "no"):
            return False
        print("  -> Responde con s/n.")

def energy_daily_from_monthly_kwh(kwh_month: float, days_per_month: float = 30.0) -> float:
    return (kwh_month * 1000.0) / days_per_month

def required_pv_power_wp(E_daily_Wh: float, HSP: float, PR: float) -> float:
    if HSP <= 0 or PR <= 0:
        return math.nan
    return E_daily_Wh / (HSP * PR)

def temp_adjust(value_stc: float, coeff_pct_per_C: float, delta_T: float) -> float:
    return value_stc * (1.0 + (coeff_pct_per_C / 100.0) * delta_T)

def module_at_temps(mod: Module, T_cell_hot: float, T_amb_cold: float) -> Dict[str, float]:
    delta_hot = T_cell_hot - 25.0
    delta_cold = T_amb_cold - 25.0
    vmp_hot = temp_adjust(mod.vmp, mod.gamma_pmax_pct_per_C, delta_hot)
    voc_cold = temp_adjust(mod.voc, mod.beta_voc_pct_per_C, delta_cold)
    isc_cold = temp_adjust(mod.isc, mod.alpha_isc_pct_per_C, delta_cold)
    return dict(vmp_hot=vmp_hot, voc_cold=voc_cold, isc_cold=isc_cold)

def check_string(n_series: int, n_parallel: int, mod: Module, inv: Inverter,
                 T_cell_hot: float, T_amb_cold: float) -> Dict[str, Any]:
    temps = module_at_temps(mod, T_cell_hot, T_amb_cold)
    vmp_hot_str = n_series * temps["vmp_hot"]
    voc_cold_str = n_series * temps["voc_cold"]
    imp_str = mod.imp
    isc_cold_str = n_parallel * temps["isc_cold"]
    imp_total = n_parallel * imp_str
    checks = {
        "mppt_min_ok": vmp_hot_str >= inv.mppt_min_v,
        "mppt_max_ok": vmp_hot_str <= inv.mppt_max_v if inv.mppt_max_v > 0 else True,
        "vdc_max_ok": voc_cold_str <= min(inv.vdc_max, mod.max_system_v),
        "imax_ok": imp_total <= inv.imax_mppt,
        "iscmax_ok": isc_cold_str <= inv.iscmax_mppt,
    }
    ok = all(checks.values())
    return {
        "n_series": n_series,
        "n_parallel": n_parallel,
        "vmp_hot_string_V": vmp_hot_str,
        "voc_cold_string_V": voc_cold_str,
        "imp_string_A": imp_str,
        "isc_cold_total_A": isc_cold_str,
        "imp_total_A": imp_total,
        "checks": checks,
        "is_compatible": ok,
        "temps": temps,
    }

def estimate_production_kwh_day(total_wp: float, HSP: float, PR: float) -> float:
    return (total_wp / 1000.0) * HSP * PR

def suggest_series_range(mod: Module, inv: Inverter, T_cell_hot: float, T_amb_cold: float) -> Dict[str, int]:
    temps = module_at_temps(mod, T_cell_hot, T_amb_cold)
    vmp_hot_mod = temps["vmp_hot"]
    voc_cold_mod = temps["voc_cold"]
    min_series = math.ceil(inv.mppt_min_v / vmp_hot_mod) if vmp_hot_mod > 0 else 1
    vlimit = min(inv.vdc_max, mod.max_system_v)
    max_series_vlimit = math.floor(vlimit / voc_cold_mod) if voc_cold_mod > 0 else 999
    max_series_mppt = math.floor(inv.mppt_max_v / vmp_hot_mod) if inv.mppt_max_v > 0 and vmp_hot_mod > 0 else 999
    max_series = min(max_series_vlimit, max_series_mppt)
    return {
        "min_series": max(min_series, 1),
        "max_series_vlimit": max_series_vlimit,
        "vlimit_used": vlimit,
        "max_series_mppt": max_series_mppt,
        "max_series": max_series
    }

def format_checks(checks: Dict[str, bool]) -> str:
    mapping = {
        "mppt_min_ok": "Vmp_hot ≥ Vmppt_min",
        "mppt_max_ok": "Vmp_hot ≤ Vmppt_max",
        "vdc_max_ok": "Voc_cold ≤ min(Vdc_max inv, Vsys_max mod)",
        "imax_ok": "I_total ≤ Imax_MPPT",
        "iscmax_ok": "Isc_total ≤ Iscmax_MPPT",
    }
    lines = []
    for k, label in mapping items():
        status = "OK" if checks.get(k, False) else "FALLA"
        lines.append(f"  - {label}: {status}")
    return "\n".join(lines)

def plan_distribution(required_strings: int, n_mppt: int, max_parallel_per_mppt: int):
    dist = [0]*n_mppt
    remain = max(0, required_strings)
    for i in range(n_mppt):
        if remain <= 0: break
        dist[i] = min(1, remain)
        remain -= dist[i]
    level = 2
    while remain > 0 and level <= max_parallel_per_mppt:
        for i in range(n_mppt):
            if remain <= 0: break
            if dist[i] < level and dist[i] < max_parallel_per_mppt:
                dist[i] += 1
                remain -= 1
        level += 1
    return dist, remain

def main():
    print("OK")
if __name__ == "__main__":
    main()
