#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Calculadora FV on-grid (interactiva por consola)

Permite ingresar:
- Consumo (kWh/mes o Wh/día), HSP, PR, temperaturas (frío/calor)
- Parámetros del inversor (hasta 8 MPPT, límites de tensión y corrientes)
- Parámetros del módulo (Wp, Vmp, Imp, Voc, Isc y coeficientes térmicos)
- Topología del arreglo: # en serie (S), # de strings en paralelo por MPPT (P), # de MPPT usados

Entrega:
- kWp requeridos para el objetivo
- Rango S permitido por tensiones (mín S por MPPT_min a calor, máx S por Vdc_max y MPPT_max)
- Chequeos eléctricos (tensión/corriente)
- Producción estimada diaria y mensual
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
        "vdc_max_ok": voc_cold_str <= inv.vdc_max,
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
    max_series_vdc = math.floor(inv.vdc_max / voc_cold_mod) if voc_cold_mod > 0 else 999
    max_series_mppt = math.floor(inv.mppt_max_v / vmp_hot_mod) if inv.mppt_max_v > 0 and vmp_hot_mod > 0 else 999
    max_series = min(max_series_vdc, max_series_mppt)
    return {
        "min_series": max(min_series, 1),
        "max_series_vdc": max_series_vdc,
        "max_series_mppt": max_series_mppt,
        "max_series": max_series
    }

def format_checks(checks: Dict[str, bool]) -> str:
    mapping = {
        "mppt_min_ok": "Vmp_hot ≥ Vmppt_min",
        "mppt_max_ok": "Vmp_hot ≤ Vmppt_max",
        "vdc_max_ok": "Voc_cold ≤ Vdc_max",
        "imax_ok": "I_total ≤ Imax_MPPT",
        "iscmax_ok": "Isc_total ≤ Iscmax_MPPT",
    }
    lines = []
    for k, label in mapping.items():
        status = "OK" if checks.get(k, False) else "FALLA"
        lines.append(f"  - {label}: {status}")
    return "\n".join(lines)

# --------- Flujo interactivo ---------
def main():
    print("=== CALCULADORA FV ON-GRID (INTERACTIVA) ===\n")

    # --- Sistema ---
    if ask_yesno("¿Ingresar consumo en Wh/día directamente?", default=False):
        E_daily_Wh = ask_float("Wh/día", 3833, 1)
        kwh_month = E_daily_Wh * 30.0 / 1000.0
    else:
        kwh_month = ask_float("Consumo mensual objetivo [kWh/mes]", 115.0, 0.1)
        dias = ask_float("Días por mes para el cálculo", 30.0, 1)
        E_daily_Wh = energy_daily_from_monthly_kwh(kwh_month, dias)

    HSP = ask_float("HSP [h/día]", 4.0, 0.1)
    PR = ask_float("PR [0-1]", 0.80, 0.1, 1.0)
    T_amb_min = ask_float("Temperatura ambiente mínima [°C]", 8.0, -50, 60)
    T_cell_hot = ask_float("Temperatura de celda caliente [°C]", 65.0, 25, 90)

    # --- Inversor ---
    print("\n--- Datos del inversor ---")
    inv_name = input("Nombre del inversor [Custom Inverter]: ").strip() or "Custom Inverter"
    n_mppt = ask_int("Cantidad de MPPT (1-8)", 2, 1, 8)
    mppt_min = ask_float("MPPT min [V]", 80.0, 10)
    mppt_max = ask_float("MPPT max [V]", 550.0, mppt_min)
    vdc_max = ask_float("Vdc máxima [V]", 600.0, mppt_max)
    imax = ask_float("Corriente máx por MPPT [A]", 11.0, 1)
    iscmax = ask_float("Isc máx por MPPT [A]", 13.8, 1)

    inv = Inverter(inv_name, mppt_min, mppt_max, vdc_max, imax, iscmax, n_mppt)

    # --- Módulo ---
    print("\n--- Datos del módulo FV ---")
    mod_name = input("Nombre del módulo [Custom Module]: ").strip() or "Custom Module"
    wp = ask_float("Wp del módulo [W]", 450.0, 1)
    vmp = ask_float("Vmp [V]", 41.5, 5)
    imp = ask_float("Imp [A]", 10.85, 1)
    voc = ask_float("Voc [V]", 49.3, 5)
    isc = ask_float("Isc [A]", 11.60, 1)
    gamma = ask_float("γ Pmax [%/°C] (negativo)", -0.35, -2, 0)
    beta = ask_float("β Voc [%/°C] (negativo)", -0.27, -2, 0)
    alpha = ask_float("α Isc [%/°C] (positivo)", 0.05, 0, 1)

    mod = Module(mod_name, wp, vmp, imp, voc, isc, gamma, beta, alpha)

    # --- Topología del arreglo ---
    print("\n--- Topología del arreglo ---")
    if ask_yesno("¿Calcular automáticamente el # en serie mínimo para activar el MPPT en calor?", default=True):
        # Sugerir rango de serie permitido
        rng = suggest_series_range(mod, inv, T_cell_hot, T_amb_min)
        n_series = rng["min_series"]
        print(f"  -> Serie mínimo sugerido (calor): {n_series}S (rango permitido: {rng['min_series']}S ... {rng['max_series']}S)")
    else:
        n_series = ask_int("Módulos en serie (S)", 3, 1)

    n_parallel = ask_int("Strings en paralelo por MPPT (P)", 1, 1)
    mppts_used = ask_int("MPPTs usados (cada uno con un string)", 1, 1, n_mppt)

    # --- Cálculos ---
    P_req_wp = required_pv_power_wp(E_daily_Wh, HSP, PR)

    # Rango seguro de serie
    rng = suggest_series_range(mod, inv, T_cell_hot, T_amb_min)

    # Chequeo por MPPT (paralelos en el mismo MPPT)
    res_mppt = check_string(n_series, n_parallel, mod, inv, T_cell_hot, T_amb_min)

    # Producción con MPPTs usados (cada uno con un string).
    total_strings = n_parallel * mppts_used
    total_wp = n_series * mod.wp * total_strings
    prod_day = estimate_production_kwh_day(total_wp, HSP, PR)
    prod_month = prod_day * 30.0

    # --- Reporte ---
    print("\n================= REPORTE =================")
    print(f"Objetivo: {kwh_month:.2f} kWh/mes  ->  {E_daily_Wh:.0f} Wh/día")
    print(f"HSP={HSP:.2f} h  PR={PR:.2f}  ->  Potencia FV requerida ≈ {P_req_wp/1000:.2f} kWp")
    print("\nInversor: ", inv.name)
    print(f"  MPPT: {inv.mppt_min_v:.0f}–{inv.mppt_max_v:.0f} V  |  Vdc_max: {inv.vdc_max:.0f} V")
    print(f"  Imax_MPPT: {inv.imax_mppt:.2f} A  |  Iscmax_MPPT: {inv.iscmax_mppt:.2f} A  |  MPPTs: {inv.n_mppt}")
    print("\nMódulo: ", mod.name)
    print(f"  STC: {mod.wp:.0f} Wp  Vmp={mod.vmp:.2f} V  Imp={mod.imp:.2f} A  Voc={mod.voc:.2f} V  Isc={mod.isc:.2f} A")
    temps = module_at_temps(mod, T_cell_hot, T_amb_min)
    print(f"  Coef: γ={mod.gamma_pmax_pct_per_C}%/°C  β={mod.beta_voc_pct_per_C}%/°C  α={mod.alpha_isc_pct_per_C}%/°C")
    print(f"  Térmico: Vmp_hot(mód)={temps['vmp_hot']:.2f} V  |  Voc_cold(mód)={temps['voc_cold']:.2f} V  |  Isc_cold(mód)={temps['isc_cold']:.2f} A")
    print("\n--- Serie permitida por tensiones ---")
    print(f"  Serie mínima (calor) por MPPT_min: {rng['min_series']}S")
    print(f"  Serie máxima por Vdc_max: {rng['max_series_vdc']}S  |  por MPPT_max: {rng['max_series_mppt']}S  =>  Máx permitido: {rng['max_series']}S")

    print("\n--- Configuración evaluada ---")
    print(f"  # en serie (S): {n_series}  |  Strings en paralelo por MPPT (P): {n_parallel}")
    print(f"  MPPTs usados: {mppts_used}  |  Strings totales: {total_strings}")
    print(f"  Vmp_hot(string): {res_mppt['vmp_hot_string_V']:.1f} V  |  Voc_cold(string): {res_mppt['voc_cold_string_V']:.1f} V")
    print(f"  I_operación(string): {res_mppt['imp_string_A']:.2f} A  |  Isc_total_cold (por MPPT): {res_mppt['isc_cold_total_A']:.2f} A")
    print("  Comprobaciones:")
    print(format_checks(res_mppt['checks']))

    print("\n--- Producción estimada ---")
    print(f"  Potencia pico total: {total_wp/1000:.2f} kWp")
    print(f"  Producción: {prod_day:.2f} kWh/d  (~{prod_month:.0f} kWh/mes)")

    # --- Sugerencias automáticas ---
    suggest = []
    if n_series < rng['min_series']:
        suggest.append(f"Aumenta serie al menos a {rng['min_series']}S para superar MPPT_min en calor.")
    if n_series > rng['max_series']:
        suggest.append(f"Reduce serie a máx {rng['max_series']}S para no exceder Vdc_max/MPPT_max en frío/calor.")
    if not res_mppt['checks']['imax_ok']:
        suggest.append("Corriente en operación supera Imax por MPPT: reduce paralelos por MPPT o usa más MPPTs.")
    if not res_mppt['checks']['iscmax_ok']:
        suggest.append("Isc_total_cold supera Iscmax por MPPT: reduce paralelos por MPPT o elige otro módulo.")
    if suggest:
        print("\n--- Recomendaciones ---")
        for s in suggest:
            print("  * " + s)

    print("\n==========================================")

if __name__ == "__main__":
    main()
